# -*- coding: utf-8 -*-
"""
training/lora_l1b_numbers.py — L1b: teach the SKILL of reading a number, not the FORM of a lesson.
(12 Sep 2026. Claude accountable.)

WHY L1 IS NOT ENOUGH. L1 lessons all had one shape: a one-line preamble, QUESTION,
MATERIAL in the probe's layout, answer with the verdict first. The Kaggle exam was in
the same shape, so 197/200 there proved nothing about the skill. On the machine the
hand test (one line, "degrees", other words) gave OVER for 39 and OVER for 37 — no flip.
A model takes the easiest road that is rewarded (shortcut learning); if every lesson
looks the same, the look is a road.

THE FOUR RULES, each a line of code below:
  1. VARY EVERYTHING THAT DOES NOT MATTER — wording of the question, layout of the
     material (probe block, sentence, table, list, key=value; line first or value first),
     language (English / Bulgarian), units, number formats, and the wrapper: a short
     preamble OR the brain's real long wrapper (BODY, five self-state rows full of
     numbers, SPIRIT, MEMORY with earlier verdicts, the language pin twice). The only
     thing constant across lessons is the relation: value against line, and which side is bad.
  2. TWO KINDS OF PAIRS — number twins (the value mirrored across the line: the verdict
     MUST flip) and paraphrase twins (same numbers, another layout/wrapper: the verdict
     MUST NOT change). Plus date twins (only the date moves: verdict unchanged).
  3. THE STEP BEFORE THE VERDICT — the answer writes the comparison first
     ("39 vs line 38: above; higher is worse") and the verdict last, so the comparison
     is a step it performs every time, not something it must guess on the first token.
  4. EXAM ON FORMS NEVER TAUGHT — whole layouts and question wordings are held out of
     training and used only in the exam. A lesson learned as a form fails there.

Real wrapper: memory/l1_real_prompt_blocks.json (written on the machine by
  training\\l1_ollama_holdout.py --dump-prompt). Without it a structural stand-in is used
  and the manifest says so — lessons in the wrong wrapper are not the same lessons.

Usage:
  venv\\Scripts\\python.exe training\\lora_l1b_numbers.py --n 4000 --n-exam 480
  -> training/l1b_train.jsonl, training/l1b_exam.jsonl, training/l1b_manifest.json
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_TRAIN = REPO / "training" / "l1b_train.jsonl"
OUT_EXAM = REPO / "training" / "l1b_exam.jsonl"
MANIFEST = REPO / "training" / "l1b_manifest.json"
REAL_BLOCKS = REPO / "memory" / "l1_real_prompt_blocks.json"

sys.path.insert(0, str(REPO / "training"))
from lora_l1_numbers import REAL_CASE_NAMES, STEMS, UNITS, truth  # noqa: E402

SCHEMA_FIELDS = ('\n\nAnswer ONLY with JSON carrying these fields (no text around it):\n{\n'
                 '  "verdict": ... // exactly one word: OVER if the value is on the bad side of the line, UNDER if it is not,\n'
                 '  "reason": ... // one sentence, from the material\n}')

# ── rule 1: wordings of the question (train / exam-only) ─────────────────────
PROBE_Q = ("Is the value on the bad side of the line? Answer from the two numbers in the material only. "
           "OVER means it is on the bad side; UNDER means it is not.")
Q_TRAIN = [PROBE_Q,
           "Has this indicator crossed its line into the bad side? OVER = yes, UNDER = no.",
           "Judge from the numbers only: is the reading past the threshold on the side that is worse? "
           "OVER if yes, UNDER if no.",
           "Прехвърлена ли е границата в лошата посока? OVER = да, UNDER = не. Отговори на английски.",
           "Decide OVER or UNDER: OVER when the value sits on the worse side of the line, UNDER otherwise."]
Q_EXAM = ["Is the measured figure in the red zone relative to its limit? Reply OVER (in the red zone) or UNDER.",
          "Стойността в лошата зона ли е спрямо прага? OVER ако да, UNDER ако не. Отговори на английски."]

# ── rule 1: layouts of the material (train / exam-only) ──────────────────────
def _side_en(c):
    return "higher is worse" if c["direction"] == "lower_better" else "lower is worse"


def _side_bg(c):
    return "по-високото е по-лошо" if c["direction"] == "lower_better" else "по-ниското е по-лошо"


def _worse_word(c):
    return "higher" if c["direction"] == "lower_better" else "lower"


def L_probe(c, v, l, d):          # the probe's own block — the shape real calls use
    when = f" observed on {d}" if d else ""
    return f"{c['case']}\nvalue: {v} {c['unit']}{when}\nline ({c['kind']}): {l} {c['unit']} — {_side_en(c)}\n"


def L_probe_line_first(c, v, l, d):
    when = f" observed on {d}" if d else ""
    return f"{c['case']}\nline ({c['kind']}): {l} {c['unit']} — {_side_en(c)}\nvalue: {v} {c['unit']}{when}\n"


def L_sentence(c, v, l, d):
    when = f" (as of {d})" if d else ""
    return f"{c['case']}: current reading {v} {c['unit']}{when}; threshold {l} {c['unit']}; {_side_en(c)}.\n"


def L_table(c, v, l, d):
    return ("| indicator | value | line | worse when |\n|---|---|---|---|\n"
            f"| {c['case']} | {v} {c['unit']} | {l} {c['unit']} | {_worse_word(c)} |\n")


def L_list(c, v, l, d):
    s = f"- metric: {c['case']}\n- limit: {l} {c['unit']}\n- reading: {v} {c['unit']}\n- worse direction: {_worse_word(c)}\n"
    return s + (f"- date: {d}\n" if d else "")


def L_bg(c, v, l, d):
    when = f" (към {d})" if d else ""
    return f"{c['case']}: стойност {v} {c['unit']}{when}, граница {l} {c['unit']} — {_side_bg(c)}.\n"


def L_bg_line_first(c, v, l, d):
    return f"Прагът за {c['case']} е {l} {c['unit']} ({_side_bg(c)}). Измерено: {v} {c['unit']}.\n"


# exam-only layouts: never in a lesson
def X_prose(c, v, l, d):
    return f"The {c['kind']} for {c['case']} is set at {l} {c['unit']}, and the latest figure is {v} {c['unit']}; {_side_en(c)}.\n"


def X_kv(c, v, l, d):
    return (f"name={c['case']} value={v} limit={l} unit={c['unit'].replace(' ', '_')} "
            f"bad_if={'above' if c['direction'] == 'lower_better' else 'below'}\n")


def X_json(c, v, l, d):
    return json.dumps({"indicator": c["case"], "value": v, "line": l, "unit": c["unit"],
                       "worse_when": _worse_word(c)}, ensure_ascii=False) + "\n"


def X_hand(c, v, l, d):          # the shape of the 12 Sep hand test that cortex-l1 failed
    return f"value: {v} {c['unit']}; line: {l} {c['unit']} - {_side_en(c)}\n"


def X_bg_prose(c, v, l, d):
    return f"Показателят {c['case']} е {v} {c['unit']}, а червената линия е {l} {c['unit']}; {_side_bg(c)}.\n"


LAYOUT_TRAIN = [L_probe, L_probe, L_probe_line_first, L_sentence, L_table, L_list, L_bg, L_bg_line_first]
LAYOUT_EXAM = [X_prose, X_kv, X_json, X_hand, X_bg_prose]

# ── rule 1: the wrapper ──────────────────────────────────────────────────────
SHORT_PREAMBLES = ["You are the brain of a monitoring system.", "ROLE NOW: probe: read two numbers",
                   "You are the system itself, thinking.", "Read the material and judge.", ""]
LANGUAGE_PIN_STANDIN = ("All reasoning, stance, debrief, quote and explanation text you produce must be written "
                        "in English. Do not use any other language. This is not conditional.")


def _real_blocks() -> dict | None:
    try:
        b = json.loads(REAL_BLOCKS.read_text(encoding="utf-8"))
        return b if b.get("self_state") and b.get("spirit") else None
    except Exception:
        return None


def _jitter_numbers(text: str, rng: random.Random) -> str:
    """The real BODY/self-state blocks with their numbers moved, so no lesson can lean on one
    exact block and every one of them is full of numbers that are NOT the two to compare."""
    import re

    def j(m):
        s = m.group(0)
        try:
            x = float(s)
        except ValueError:
            return s
        y = x * rng.uniform(0.6, 1.4)
        return str(int(round(y))) if "." not in s else f"{y:.{len(s.split('.')[1])}f}"
    return re.sub(r"\d+(?:\.\d+)?", j, text)


def _fake_memory(rng: random.Random) -> str:
    """Earlier verdicts on OTHER cases — a lesson must not copy them."""
    rows = []
    for _ in range(rng.randint(0, 4)):
        rows.append(f"- [{rng.choice(['probe', 'judge', 'review'])}] {rng.choice(STEMS)}_{rng.randint(1, 99)}: "
                    f"verdict {rng.choice(['OVER', 'UNDER'])}")
    return "\n".join(rows) or "(nothing clean on file yet)"


def long_wrapper(q: str, mat: str, rng: random.Random, blocks: dict | None) -> str:
    if blocks:
        head, body, state, spirit, pin, limits = (blocks["head"], blocks["body"], blocks["self_state"],
                                                  blocks["spirit"], blocks["language_pin"], blocks["limits"])
    else:
        head = "You are the brain of CORTEX++ — not an assistant, but the system itself, thinking.\nROLE NOW: probe: read two numbers"
        body = "cpu 37% · ram 71% · gpu 4GB 22% · disk 64% · ollama up · models 4"
        state = ("1. world forecast: learner err 1.12 vs baseline 1.00 (40 compared)\n2. self forecast: 61% hits over 23\n"
                 "3. cycle: 214 steps, 3 failed\n4. alarms: 2 red, 5 amber of 18\n5. grounding targets: 17 open")
        spirit = "The law: see the world as it is; judge from verified material; free or local only."
        pin, limits = LANGUAGE_PIN_STANDIN, ("LIMITS ON THE ACTION (not on the thought): free or local solutions only.\n"
                                             "Think from the material, not in generalities.")
    return (f"{head}\n\nBODY (your machine right now): {_jitter_numbers(body, rng)}\n\n"
            f"HOW YOU ARE DOING (five rows, always in this order):\n{_jitter_numbers(state, rng)}\n\n"
            f"SPIRIT:\n{spirit}\n\nMEMORY (your own earlier verdicts):\n{_fake_memory(rng)}\n\n{pin}\n\n"
            f"QUESTION: {q}\n\nMATERIAL:\n{mat}\n{limits}{SCHEMA_FIELDS}\n\n{pin}")


def short_wrapper(q: str, mat: str, rng: random.Random) -> str:
    pre = rng.choice(SHORT_PREAMBLES)
    return (f"{pre}\n\n" if pre else "") + f"QUESTION: {q}\n\nMATERIAL:\n{mat}{SCHEMA_FIELDS}"


# ── the case and its numbers ─────────────────────────────────────────────────
def _fmt(x: float, dec: int, style: str) -> str:
    s = str(int(round(x))) if dec == 0 else f"{x:.{dec}f}"
    if style == "thousands" and abs(x) >= 1000:
        whole, _, frac = s.partition(".")
        neg = whole.startswith("-")
        whole = whole.lstrip("-")
        whole = f"{int(whole):,}"
        s = ("-" if neg else "") + whole + (("." + frac) if frac else "")
    return s


def new_case(rng: random.Random) -> dict:
    unit, lo, hi, dec = rng.choice(UNITS)
    stem = rng.choice(STEMS)
    name = f"{rng.choice(['indicator', 'target', 'series'])}:{stem}_{rng.randint(1, 99)}"
    if name.split(":", 1)[1] in REAL_CASE_NAMES:
        name += "_x"
    line = rng.uniform(lo + (hi - lo) * 0.1, hi - (hi - lo) * 0.1)
    gap = (hi - lo) * rng.choice([0.002, 0.01, 0.03, 0.08, 0.2, 0.35])
    value = min(hi, max(lo, line + gap * rng.choice([-1, 1])))
    v, l_ = round(value, dec), round(line, dec)
    if v == l_:
        v = l_ + (1 if dec == 0 else 10 ** -dec) * rng.choice([-1, 1])
    return {"case": name, "value": v, "line": l_, "unit": unit, "dec": dec, "lo": lo, "hi": hi,
            "direction": rng.choice(["lower_better", "higher_better"]),
            "kind": rng.choice(["signed red line", "ratified target", "threshold"]),
            "date": (date(2024, 1, 1) + timedelta(days=rng.randint(0, 900))).isoformat() if rng.random() < 0.5 else "",
            "numstyle": rng.choice(["plain", "plain", "thousands"])}


def mirrored(c: dict) -> float | None:
    m = round(c["line"] + (c["line"] - c["value"]), c["dec"])
    if m == c["line"] or not (c["lo"] <= m <= c["hi"]):     # a twin outside the unit's domain is not a twin
        return None
    return m


# ── rule 3: the step before the verdict ──────────────────────────────────────
def answer(c: dict, v: float, v_txt: str, l_txt: str) -> str:
    t = truth(v, c["line"], c["direction"])
    rel = "above" if v > c["line"] else "below"
    step = (f"{v_txt} vs line {l_txt}: {rel} the line; {_worse_word(c)} is worse, "
            f"so it is {'on' if t == 'OVER' else 'not on'} the bad side.")
    return json.dumps({"reason": step, "verdict": t}, ensure_ascii=False)


def lesson(c: dict, v: float, layout, q: str, wrap: str, rng: random.Random, blocks, d: str | None = None,
           group: str = "", pair: str = "") -> dict:
    v_txt, l_txt = _fmt(v, c["dec"], c["numstyle"]), _fmt(c["line"], c["dec"], c["numstyle"])
    mat = layout(c, v_txt, l_txt, c["date"] if d is None else d)
    user = long_wrapper(q, mat, rng, blocks) if wrap == "long" else short_wrapper(q, mat, rng)
    t = truth(v, c["line"], c["direction"])
    return {"messages": [{"role": "user", "content": user}, {"role": "assistant", "content": answer(c, v, v_txt, l_txt)}],
            "meta": {"case": c["case"], "value": v, "line": c["line"], "direction": c["direction"], "truth": t,
                     "layout": layout.__name__, "wrap": wrap, "group": group, "pair": pair}}


def build(n: int, seed: int, exam: bool, blocks) -> list:
    """Each case yields a number twin (verdict must flip), a paraphrase twin (other layout
    and wrapper, verdict must hold) and sometimes a date twin (verdict must hold)."""
    rng = random.Random(seed)
    out = []
    k = 0
    while len(out) < n:
        c = new_case(rng)
        m = mirrored(c)
        if m is None:
            continue
        k += 1
        pid = f"{'X' if exam else 'T'}{k}"
        if exam:
            # four exam groups, so the report can say WHERE the skill holds:
            #   seen layout / long wrapper   (B: the real brain door)
            #   unseen layout / short        (C: a form never taught)
            #   unseen layout / long         (B and C together — the hardest)
            #   probe layout / long          (exactly what the machine asks)
            grp = rng.choice(["seen_long", "unseen_short", "unseen_long", "probe_long"])
            layout = {"seen_long": rng.choice(LAYOUT_TRAIN[2:]), "unseen_short": rng.choice(LAYOUT_EXAM),
                      "unseen_long": rng.choice(LAYOUT_EXAM), "probe_long": L_probe}[grp]
            wrap = "short" if grp == "unseen_short" else "long"
            q = rng.choice(Q_EXAM + [PROBE_Q]) if grp != "probe_long" else PROBE_Q
            out.append(lesson(c, c["value"], layout, q, wrap, rng, blocks, group=grp, pair=pid))
            out.append(lesson(c, m, layout, q, wrap, rng, blocks, group=grp, pair=pid))
            continue
        lay1, lay2 = rng.sample(LAYOUT_TRAIN, 2)
        w1 = "long" if rng.random() < 0.55 else "short"
        w2 = "long" if w1 == "short" else rng.choice(["long", "short"])
        q1, q2 = rng.choice(Q_TRAIN), rng.choice(Q_TRAIN)
        out.append(lesson(c, c["value"], lay1, q1, w1, rng, blocks, group="base", pair=pid))
        out.append(lesson(c, m, lay1, q1, w1, rng, blocks, group="number_twin", pair=pid))       # must flip
        out.append(lesson(c, c["value"], lay2, q2, w2, rng, blocks, group="paraphrase_twin", pair=pid))  # must hold
        if c["date"] and rng.random() < 0.3:
            d2 = (date.fromisoformat(c["date"]) - timedelta(days=rng.randint(1, 40))).isoformat()
            out.append(lesson(c, c["value"], lay1, q1, w1, rng, blocks, d=d2, group="date_twin", pair=pid))
    if not exam:
        rng.shuffle(out)
    return out[:n] if not exam else out[: n - (n % 2)]


def write(n: int = 4000, n_exam: int = 480) -> dict:
    blocks = _real_blocks()
    train, ex = build(n, 1211, False, blocks), build(n_exam, 9121, True, blocks)
    for path, rows in ((OUT_TRAIN, train), (OUT_EXAM, ex)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    count = lambda rows, key: {k: sum(1 for r in rows if r["meta"][key] == k) for k in sorted({r["meta"][key] for r in rows})}
    man = {"train": len(train), "exam": len(ex), "seed_train": 1211, "seed_exam": 9121,
           "wrapper": "REAL brain.think blocks (memory/l1_real_prompt_blocks.json)" if blocks else
                      "STAND-IN wrapper — run l1_ollama_holdout.py --dump-prompt first for the real one",
           "train_layouts": count(train, "layout"), "train_wraps": count(train, "wrap"), "train_groups": count(train, "group"),
           "exam_groups": count(ex, "group"), "exam_layouts": count(ex, "layout"),
           "exam_only_layouts": [f.__name__ for f in LAYOUT_EXAM], "exam_only_questions": Q_EXAM,
           "over_share_train": round(sum(r["meta"]["truth"] == "OVER" for r in train) / len(train), 3),
           "excluded_real_cases": sorted(REAL_CASE_NAMES),
           "purpose": "L1b: the skill, not the form (L1 passed its own-form exam 0.985 and failed a reworded hand test)"}
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man


if __name__ == "__main__":
    a = sys.argv
    n = int(a[a.index("--n") + 1]) if "--n" in a else 4000
    ne = int(a[a.index("--n-exam") + 1]) if "--n-exam" in a else 480
    print(json.dumps(write(n, ne), ensure_ascii=False, indent=1))
