#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/arc_f1.py — Ф1: ПЪРВОТО ВЪНШНО ИЗМЕРВАНЕ НА ОБОБЩАВАНЕ.

ПОСТАНОВКА
----------
Какво се иска : моделът вижда няколко двойки вход->изход и трябва да произведе
                изходната решетка за НОВ вход. Правилото не му се казва.
Какво вижда   : само решетките. Нула контекст, нула обяснение, нула подсказка.
Кой решава    : моделът, ДВА опита (правилото на ARC).
Кой проверява : КОД. Точно съвпадение на цялата решетка. Не модел.
Известни слабости:
  - неразчетен отговор се брои за ПРОВАЛ, не се изключва. Изключването би ни
    дало по-хубаво число, отколкото заслужаваме.
  - задача, чиято подсказка не се побира в контекста, се брои за провал със
    собствена причина (too_long), за да не се скрие зад общия резултат.
  - единственото непроверено място е ask_model(): тук нямаше Ollama.

ГЛУПАВАТА БАЗА, измерена преди всякакъв модел, върху същите 419 двойки:
    "копирай входа"  ->  0 от 419 = 0.00%
Нула. Значи всяко ненулево число е обобщаване, а не евтин трик — за разлика от
пазарите, където глупавото правило бие модела.

    venv/Scripts/python.exe tools/arc_f1.py --selftest
    venv/Scripts/python.exe tools/arc_f1.py --baseline
    venv/Scripts/python.exe tools/arc_f1.py --model qwen2.5:3b --limit 50
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
TASKS = BASE / "data" / "arc_eval_400.json"
OUT = BASE / "claude" / "reports"
OLLAMA = "http://127.0.0.1:11434/api/generate"

NUM_PREDICT = 1100      # решетка 30x30 = 900 цифри + нови редове. 2048 беше
                        # три минути безсмислено дописване на процесор.
MAX_PROMPT_CHARS = 12000   # под контекста на 3B; по-дълга задача се брои за провал
ATTEMPTS = ((0.0, "greedy"), (0.8, "sampled"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── решетка <-> текст ───────────────────────────────────────────────────────

def ser(grid: list) -> str:
    """Ред на ред, по една цифра на клетка. Без разделители: моделът брои
    позиции по-лесно, а разчитането става еднозначно."""
    return "\n".join("".join(str(c) for c in row) for row in grid)


def parse(text: str) -> list | None:
    """Вади ПОСЛЕДНИЯ блок от редове, които са само цифри и са еднакво дълги.

    Последният, а не първият: малките модели често преповтарят входа, преди да
    дадат отговора. Еднакво дълги: решетка с назъбен ръб не е решетка, и е
    по-честно да откажем, отколкото да я подравним вместо модела.
    """
    best = None
    cur: list[str] = []
    for line in (text or "").replace("\r", "").split("\n") + [""]:
        s = line.strip().strip("`").replace(" ", "").replace(",", "")
        if s and s.isdigit():
            cur.append(s)
            continue
        if cur:
            if len(set(len(r) for r in cur)) == 1:
                best = cur           # запазва последния валиден блок
            cur = []
    if not best:
        return None
    return [[int(c) for c in row] for row in best]



def diagnose(text: str) -> str:
    """ЗАЩО не се разчете. Данните от 13 сеп показаха, че UNPARSED слепва два
    РАЗЛИЧНИ провала, а различни провали не бива да делят една дума:

      ragged  моделът НАПИСА решетка, но редовете ѝ са с различна дължина
              (00dbd492: редове от 20, 21 и 22 цифри). Опитал е и се е счупил
              на геометрията.
      prose   моделът върна проза или код — "you would need to run this
              function with your input data" (05a7bcf2). Изобщо не е опитал.
      empty   нищо използваемо.

    Първото е неумение. Второто е неподчинение. Лекуват се с различни неща.
    """
    lines = [l.strip().strip("`").replace(" ", "").replace(",", "")
             for l in (text or "").split("\n")]
    digit = [l for l in lines if l and l.isdigit()]
    if len(digit) >= 2 and len(set(len(r) for r in digit)) > 1:
        return "ragged"
    if not digit:
        return "prose" if len((text or "").strip()) > 40 else "empty"
    return "empty"


def build_prompt(task: dict) -> str:
    parts = ["You are given example grids. Each example shows an input grid and",
             "the output grid produced from it by one hidden rule.",
             "Infer the rule and apply it to the final input.",
             "Answer with the output grid ONLY: digits, one row per line.",
             "No words, no explanation, no code fences.", ""]
    for i, ex in enumerate(task["train"], 1):
        parts += [f"Example {i} input:", ser(ex["input"]),
                  f"Example {i} output:", ser(ex["output"]), ""]
    parts += ["Final input:", ser(task["test"][0]["input"]), "", "Output grid:"]
    return "\n".join(parts)


# ── единственото непроверено място ──────────────────────────────────────────

def ask_model(model: str, prompt: str, temperature: float, timeout: int) -> str:
    """Прати текст, върни текст. Всичко останало в този файл е изпитано без
    модел; тази функция не може да бъде, защото средата нямаше Ollama."""
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": temperature, "num_predict": NUM_PREDICT},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


# ── глупавите бази, през СЪЩИЯ съдия ────────────────────────────────────────

def baseline_copy(task: dict) -> list:
    return task["test"][0]["input"]


def baseline_zeros(task: dict) -> list:
    g = task["test"][0]["input"]
    return [[0] * len(g[0]) for _ in g]


BASELINES = {"copy_input": baseline_copy, "all_zeros": baseline_zeros}


# ── пускът ──────────────────────────────────────────────────────────────────

def run(model: str, tasks: dict, limit: int | None, timeout: int,
        max_seconds: float, journal: pathlib.Path, baseline: str | None):
    done = set()
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["task"])
            except Exception:
                pass
    ids = [t for t in sorted(tasks) if t not in done]
    if limit:
        ids = ids[:limit]

    t0 = time.time()
    if not baseline:
        print(f"[Ф1] {len(ids)} задачи, модел {model}. Първият отговор може\n[Ф1] да се забави ~1 минута, докато моделът се зареди от студено.", flush=True)
    hit = miss = unparsed = too_long = 0
    why_counts = collections.Counter()
    journal.parent.mkdir(parents=True, exist_ok=True)
    fh = open(journal, "a", encoding="utf-8")

    for n, tid in enumerate(ids, 1):
        if time.time() - t0 > max_seconds:
            print(f"[Ф1] стоп по време след {n-1} задачи", flush=True)
            break
        task = tasks[tid]
        truth = task["test"][0]["output"]
        row = {"ts": _now(), "task": tid, "model": baseline or model,
               "attempts": [], "verdict": None}

        if baseline:
            got = BASELINES[baseline](task)
            ok = got == truth
            row["attempts"] = [{"how": baseline, "parsed": True, "hit": ok}]
            row["verdict"] = "HIT" if ok else "MISS"
        else:
            prompt = build_prompt(task)
            if len(prompt) > MAX_PROMPT_CHARS:
                too_long += 1
                row["verdict"] = "TOO_LONG"
                row["prompt_chars"] = len(prompt)
                fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
                print(f"[Ф1] {n}/{len(ids)} {tid} TOO_LONG ({len(prompt)})")
                continue
            for temp, how in ATTEMPTS:
                print(f"[Ф1] {n}/{len(ids)} {tid} ... питам {model} ({how}, "
                      f"{len(prompt)} знака)", flush=True)
                t1 = time.time()
                try:
                    raw = ask_model(model, prompt, temp, timeout)
                    err = None
                except Exception as exc:                      # noqa: BLE001
                    raw, err = "", f"{type(exc).__name__}: {exc}"
                got = parse(raw)
                a = {"how": how, "temperature": temp, "sec": round(time.time()-t1, 1),
                     "parsed": got is not None, "hit": got == truth,
                     "why": None if got is not None else diagnose(raw),
                     "raw_tail": (raw or "")[-400:], "error": err}
                if err:
                    hint = ("  <- моделът не отговори навреме; вдигни --timeout "
                            "или моделът върви на процесор" if "imeout" in err else "")
                    print(f"[Ф1]      ГРЕШКА: {err}{hint}", flush=True)
                else:
                    _w = {"ragged": "НАЗЪБЕНА решетка", "prose": "ПРОЗА/КОД",
                          "empty": "нищо"}.get(a["why"], "НЕразчетено")
                    print(f"[Ф1]      {a['sec']} s, "
                          f"{'разчетена решетка' if a['parsed'] else _w}"
                          f"{' — ПОПАДЕНИЕ' if a['hit'] else ''}", flush=True)
                row["attempts"].append(a)
                if a["hit"]:
                    break
            row["verdict"] = ("HIT" if any(a["hit"] for a in row["attempts"])
                              else "UNPARSED" if not any(a["parsed"] for a in row["attempts"])
                              else "MISS")

        if row["verdict"] == "HIT":
            hit += 1
        elif row["verdict"] == "UNPARSED":
            unparsed += 1; miss += 1
            why_counts[next((a["why"] for a in row["attempts"] if a.get("why")), "empty")] += 1
        else:
            miss += 1
        fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
        print(f"[Ф1] {n}/{len(ids)} {tid} {row['verdict']}  "
              f"({hit} попадения от {hit+miss})", flush=True)

    fh.close()
    seen = hit + miss + too_long
    print(f"\n[Ф1] {baseline or model}: {hit} от {seen} = "
          f"{100*hit/seen if seen else 0:.2f}%   "
          f"(неразчетени {unparsed} {dict(why_counts) or ''}, "
          f"твърде дълги {too_long}, {time.time()-t0:.0f} s)")
    return {"model": baseline or model, "seen": seen, "hit": hit,
            "unparsed": unparsed, "unparsed_why": dict(why_counts),
            "too_long": too_long,
            "pct": round(100*hit/seen, 2) if seen else 0.0}


# ── самопроверка: всичко освен ask_model, върху ИСТИНСКИТЕ задачи ───────────

def selftest(tasks: dict) -> int:
    bad = 0
    for tid, t in tasks.items():
        for ex in t["train"] + t["test"]:
            for g in (ex["input"], ex["output"]):
                if parse(ser(g)) != g:
                    print(f"ПАДНА подредба/разчитане: {tid}", flush=True); bad += 1
    print(f"подредба+разчитане върху всички задачи: {'ГРЕШКИ' if bad else 'ОК'}", flush=True)

    cases = [
        ("123\n456", [[1, 2, 3], [4, 5, 6]], "чист блок"),
        ("Here you go:\n```\n12\n34\n```", [[1, 2], [3, 4]], "в ограда и с проза"),
        ("input was:\n99\n99\noutput:\n12\n34", [[1, 2], [3, 4]], "взима ПОСЛЕДНИЯ блок"),
        ("1 2\n3 4", [[1, 2], [3, 4]], "интервали"),
        ("12\n345", None, "назъбено -> отказ"),
        ("no digits here", None, "без цифри -> отказ"),
        ("", None, "празно -> отказ"),
    ]
    for text, want, why in cases:
        got = parse(text)
        ok = got == want
        print(f"  {'ОК ' if ok else 'ПАДНА'} {why}: {got!r}", flush=True)
        bad += 0 if ok else 1

    t = next(iter(tasks.values()))
    p = build_prompt(t)
    assert "Final input:" in p and "Output grid:" in p
    lens = sorted(len(build_prompt(x)) for x in tasks.values())
    print(f"  подсказка: медиана {lens[len(lens)//2]}, "
          f"макс {lens[-1]}, над {MAX_PROMPT_CHARS}: "
          f"{sum(1 for L in lens if L > MAX_PROMPT_CHARS)} от {len(lens)}", flush=True)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--tasks", default=str(TASKS))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--max-seconds", type=float, default=3600)
    ap.add_argument("--baseline", choices=sorted(BASELINES))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    tasks = json.loads(pathlib.Path(a.tasks).read_text(encoding="utf-8"))
    if a.selftest:
        return 1 if selftest(tasks) else 0

    tag = a.baseline or a.model.replace(":", "_").replace("/", "_")
    journal = OUT / f"ARC_F1_{tag}.jsonl"
    res = run(a.model, tasks, a.limit, a.timeout, a.max_seconds, journal, a.baseline)
    (OUT / f"ARC_F1_{tag}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
