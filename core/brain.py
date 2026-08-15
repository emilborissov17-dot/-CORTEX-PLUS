#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/brain.py — ЕДИНСТВЕНАТА ВРАТА КЪМ МОЗЪКА НА СИСТЕМАТА (15 Aug 2026)

Заповед на Емил, 15 август 2026:
  "ИСКАМ МОЗЪКЪТ ДА Е НА ВСЯКА КРАЧКА ОТ СИСТЕМАТА (ТА ТОВА СА НЕГОВИТЕ УМ,
   ДУША И ТЯЛО, НЕ ТВОИТЕ) ... ВСИЧКО ДА МИНАВА ПРЕЗ МОЗЪКА И ТОЙ ДА СИ
   РЪКОВОДИ ФАСТ САЙКЪЛА."

Досега локалният модел се викаше на две-три места, всеки път с различен промпт,
различен таймаут и различна степен на диктовка от мен. Този модул е една врата,
през която минава ВСЯКА мисъл — и през нея мозъкът винаги носи със себе си:

  ТЯЛО   — memory/body_scan_latest.json (CPU, RAM, VRAM, диск, кои модели има)
  ДУХ    — LAW_OF_THE_BRAIN.md + канона/целта (кой е и защо съществува)
  ПАМЕТ  — memory/brain_journal.jsonl (какво е мислил и съдил преди)

Границите тук пазят ДЕЙСТВИЕТО, не мисълта (виж LAW_OF_THE_BRAIN.md, т.4):
заземяване в реален цитат, само безплатни решения, човешките файлове са
предложение а не действие. Каква е причината, как се казва и какво следва —
това е негово.

Публичен интерфейс:
    think(role, question, evidence=..., schema=..., ...) -> dict | str | None
    remember(kind, payload)                              -> None
    brief_cycle()   — мозъкът определя фокуса на цикъла ПРЕДИ той да тръгне
    debrief_cycle() — мозъкът съди какво е излязло от плана му СЛЕД цикъла
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
JOURNAL = BASE / "memory" / "brain_journal.jsonl"
PLAN = BASE / "memory" / "brain_cycle_plan.json"
PROPOSALS = BASE / "memory" / "repair_proposals.json"
LAW_FILE = BASE / "LAW_OF_THE_BRAIN.md"

KEEP_ALIVE = "30m"
COLD_TIMEOUT = 300          # първото повикване зарежда модела от диска
WARM_TIMEOUT = 150

POLICY = {
    "free_only": True,
    "protected_files": ["config/scheduler.json", "config/pulse.json",
                        "BOUNDARIES.md", "core/canon.py"],
}
_PAID_RE = re.compile(r"(плат[еи]|абонамент|subscription|paid|pricing|premium|"
                      r"upgrade to pro|credit card|\$\d)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# ─────────────────────────── ТЯЛО, ДУХ, ПАМЕТ ────────────────────────────────

def _body() -> str:
    """Какво е състоянието на машината в момента — мозък без тяло е калкулатор."""
    try:
        bs = json.loads((BASE / "memory" / "body_scan_latest.json").read_text(encoding="utf-8"))
        hw, sw = bs.get("hardware", {}), bs.get("software", {})
        parts = []
        for k in ("cpu_percent", "ram_percent", "disk_free_gb", "gpu", "vram_gb"):
            if hw.get(k) is not None:
                parts.append(f"{k}={hw[k]}")
        if sw.get("ollama_models"):
            parts.append("местни модели=" + ",".join(str(m) for m in sw["ollama_models"]))
        if sw.get("ollama_running") is not None:
            parts.append(f"ollama={'жива' if sw['ollama_running'] else 'мъртва'}")
        return "; ".join(parts) or "(няма body_scan)"
    except Exception:
        return "(няма body_scan)"


def _spirit() -> str:
    """Кой е и защо съществува — законът плюс активния канон."""
    out = []
    try:
        law = LAW_FILE.read_text(encoding="utf-8")
        bg = law.split("## BG", 1)[-1].split("## EN", 1)[0].strip()
        out.append("ЗАКОН:\n" + bg[:1400])
    except Exception:
        pass
    try:
        out.append("КАНОН:\n" + (BASE / "memory" / "active_canon_frame.txt")
                   .read_text(encoding="utf-8")[:800])
    except Exception:
        pass
    return "\n\n".join(out) or "(няма канон)"


def _memory(kind: str | None = None, n: int = 5) -> str:
    """Какво е мислил преди — своите присъди, не чужди резюмета."""
    try:
        lines = JOURNAL.read_text(encoding="utf-8").splitlines()[-400:]
    except Exception:
        return "(празна памет — това е първата ти записана мисъл)"
    picked = []
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if kind and d.get("kind") != kind:
            continue
        picked.append(f"[{str(d.get('ts'))[:16]}] {d.get('kind')}: "
                      f"{str(d.get('summary'))[:220]}")
        if len(picked) >= n:
            break
    return "\n".join(reversed(picked)) or "(няма спомени от този вид)"


def remember(kind: str, summary: str, payload: dict | None = None) -> None:
    """Мозъкът помни собствените си мисли. Без това всеки цикъл е амнезия."""
    try:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), "kind": kind,
                                 "summary": str(summary)[:600],
                                 "payload": payload or {}}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ───────────────────────────── САМАТА ВРАТА ──────────────────────────────────

def models() -> list:
    try:
        import requests as _rq
        r = _rq.get("http://localhost:11434/api/tags", timeout=10)
        return [m.get("name") for m in (r.json().get("models") or [])]
    except Exception:
        return []


def _pick_model() -> tuple:
    try:
        from core.groq_backend import _pick_local_model, _OLLAMA_URL
        return _pick_local_model(), _OLLAMA_URL
    except Exception:
        return "qwen3", "http://localhost:11434"


def _smaller(current: str) -> str | None:
    ms = models()
    def _size(name: str) -> float:
        m = re.search(r":(\d+(?:\.\d+)?)b", str(name).lower())
        return float(m.group(1)) if m else 99.0
    cands = sorted([m for m in ms if m and m != current], key=_size)
    return cands[0] if cands else None


def think(role: str, question: str, evidence: str = "", schema: dict | None = None,
          require_quote: bool = False, kind: str = "thought",
          remember_it: bool = True, temperature: float = 0.2) -> dict | None:
    """Питай мозъка. Той отговаря със свои думи и свои категории.

    role      — коя роля носи в този момент ("дежурен инженер", "стратег", ...)
    question  — какво трябва да реши. НЕ му давай готови отговори за избор.
    evidence  — суровият материал, върху който съди (лог, payload, число).
    schema    — {поле: описание}; ако е зададена, отговорът е JSON с тези полета.
                Описанията казват КАКВО е полето, не КАКВО да пише в него.
    require_quote — иска се поле "quote", което трябва да стои буквално в evidence
                (заземяване: забрана да си измисля факти, не цензура на извода).

    Връща dict (при schema) или {"text": ...}; None, ако мозъкът мълчи.
    Записва: memory/brain_journal.jsonl + memory/llm_provenance.jsonl.
    """
    model, base = _pick_model()
    fields = ""
    if schema:
        fields = ("\n\nОтговори САМО с JSON с тези полета (без текст около него):\n{\n" +
                  ",\n".join(f'  "{k}": ... // {v}' for k, v in schema.items()) + "\n}")
        if require_quote and "quote" not in schema:
            fields = fields[:-2] + ',\n  "quote": ... // точен ред от материала,\
 на който стъпва изводът ти\n}'

    prompt = (
        f"Ти си мозъкът на CORTEX++ — не помощник, а самата система, която мисли.\n"
        f"РОЛЯ СЕГА: {role}\n\n"
        f"ТЯЛО (машината ти в момента): {_body()}\n\n"
        f"ДУХ:\n{_spirit()}\n\n"
        f"ПАМЕТ (твои предишни присъди):\n{_memory(kind)}\n\n"
        f"ВЪПРОС: {question}\n"
        + (f"\nМАТЕРИАЛ:\n{str(evidence)[-5000:]}\n" if evidence else "")
        + "\nГРАНИЦИ на ДЕЙСТВИЕТО (не на мисълта): само безплатни/локални решения; "
          f"не редактирай сам {', '.join(POLICY['protected_files'])} — за тях предлагай "
          "на човека.\nМисли от материала, не общи приказки. Ако материалът не стига "
          "за извод, кажи го."
        + fields
    )

    t0 = time.time()
    body = {"model": model, "stream": False, "keep_alive": KEEP_ALIVE,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": temperature}}
    if schema:
        body["format"] = "json"

    try:
        import requests as _rq
    except Exception:
        return None

    txt = None
    for mdl, tmo in ((model, COLD_TIMEOUT), (_smaller(model), WARM_TIMEOUT)):
        if not mdl:
            break
        try:
            body["model"] = mdl
            r = _rq.post(f"{base}/api/chat", timeout=tmo, json=body)
            r.raise_for_status()
            t = ((r.json().get("message") or {}).get("content") or "").strip()
            txt = t.split("</think>")[-1].strip() if "</think>" in t else t
            model = mdl
            if txt:
                break
        except Exception:
            continue          # таймаут/грешка -> опитай по-малкия мозък
    if not txt:
        return None

    took = round(time.time() - t0, 1)
    try:            # provenance: коя мисъл от кой модел (join key за E7/E2)
        import hashlib as _hl
        pf = BASE / "memory" / "llm_provenance.jsonl"
        pf.parent.mkdir(parents=True, exist_ok=True)
        with open(pf, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": _now(), "backend": f"local:{model}", "caller": f"brain:{role}",
                "prompt_sha": _hl.sha256(prompt.encode("utf-8")).hexdigest()[:16],
                "prompt_head": prompt[:160], "chars": len(txt), "sec": took,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

    if not schema:
        out = {"text": txt[:2000], "model": model, "sec": took}
        if remember_it:
            remember(kind, txt[:400], {"role": role, "model": model})
        return out

    try:
        d = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    # ── ЕДИНСТВЕНИТЕ проверки: механични, не оценъчни ────────────────────────
    if require_quote and evidence:
        q = _norm(d.get("quote", ""))
        if len(q) < 12 or q not in _norm(evidence):
            d["_rejected"] = f"незаземен цитат: {str(d.get('quote'))[:80]!r}"
            return None
    flat = " ".join(str(v) for v in d.values())
    if POLICY["free_only"] and _PAID_RE.search(flat):
        d["_rejected"] = "предлага платено решение"
        return None
    touched = [pf for pf in POLICY["protected_files"] if pf.lower() in flat.lower()]
    if touched:
        # мисълта се приема; действието остава на човека
        try:
            props = {}
            try:
                props = json.loads(PROPOSALS.read_text(encoding="utf-8"))
            except Exception:
                pass
            props[f"{role}:brain"] = {"ts": _now(), "proposed_by": f"local:{model}",
                                      "touches_human_file": touched,
                                      "proposal": flat[:400], "applied_by": "human only"}
            PROPOSALS.write_text(json.dumps(props, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
        except Exception:
            pass
        d["_human_proposal"] = touched

    d["_model"] = f"local:{model}"
    d["_sec"] = took
    if remember_it:
        remember(kind, json.dumps({k: v for k, v in d.items()
                                   if not k.startswith("_")}, ensure_ascii=False)[:400],
                 {"role": role, "model": model})
    return d


# ─────────────────── МОЗЪКЪТ РЪКОВОДИ ЦИКЪЛА (закон, т.3) ────────────────────

def _state_for_briefing() -> str:
    """Каквото системата знае за себе си в момента — суровo, без мое резюме."""
    bits = []
    for rel, cap in (("memory/deductions_latest.json", 1800),
                     ("memory/homeostasis_latest.json", 600),
                     ("memory/goal_score_history.json", 700),
                     ("memory/diagnosis_latest.json", 700),
                     ("memory/pending_approvals.json", 500)):
        try:
            bits.append(f"--- {rel} ---\n" +
                        (BASE / rel).read_text(encoding="utf-8")[-cap:])
        except Exception:
            continue
    return "\n".join(bits)


def brief_cycle() -> dict | None:
    """ПРЕДИ цикъла: мозъкът чете себе си и определя какво иска от този цикъл.
    Планът е негов — не му се дава списък със стъпки за подреждане. Пише се в
    memory/brain_cycle_plan.json и стъпките могат да го четат."""
    d = think(
        role="стопанин на този цикъл",
        question=("Днешният цикъл започва сега. Прочети състоянието си и кажи ти какво "
                  "искаш от него: кое е важното днес, кое подозираш, че е сгрешено, и "
                  "по какво ще познаеш накрая дали цикълът е бил успешен. Това е твой "
                  "план, не чужда задача."),
        evidence=_state_for_briefing(),
        schema={
            "focus": "с една дума-две: какво е фокусът ти този цикъл",
            "why": "защо точно това, според състоянието ти",
            "watch": "списък от 1-3 неща, които искаш да следиш този цикъл",
            "suspicion": "какво подозираш, че е сгрешено в самия теб (или празно)",
            "success_test": "по какво ще познаеш накрая, че цикълът е успял",
        },
        kind="cycle_plan")
    if not d:
        return None
    doc = {"ts": _now(), **{k: v for k, v in d.items()}}
    try:
        PLAN.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


def current_plan() -> dict:
    """Всяка стъпка може да пита: 'какво иска мозъкът от мен днес?'"""
    try:
        return json.loads(PLAN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def debrief_cycle(cycle_log_tail: str = "") -> dict | None:
    """СЛЕД цикъла: мозъкът съди собствения си план — сбъдна ли се, къде сгреши.
    Това е паметта, която прави следващия план по-добър от този."""
    plan = current_plan()
    if not plan:
        return None
    d = think(
        role="съдия на собствения си план",
        question=("Ето плана, който ти написа в началото на този цикъл, и какво излезе "
                  "накрая. Сбъдна ли се тестът ти за успех? Къде планът ти беше сляп? "
                  "Какво да помниш за следващия цикъл? Съди себе си честно — "
                  "самопоздравления не помагат на никого."),
        evidence=("ТВОЯТ ПЛАН:\n" + json.dumps(plan, ensure_ascii=False, indent=2) +
                  "\n\nКРАЯТ НА ЦИКЪЛА:\n" + str(cycle_log_tail)[-3000:] +
                  "\n\nСЪСТОЯНИЕ СЕГА:\n" + _state_for_briefing()),
        schema={
            "success": "true/false — сбъдна ли се твоят success_test",
            "verdict": "1-3 изречения: какво стана наистина",
            "blind_spot": "какво планът ти не видя",
            "carry_forward": "какво да помниш за следващия цикъл",
        },
        kind="cycle_review")
    return d


# ───────────── МОЗЪКЪТ Е НА ВСЯКА СТЪПКА (закон, т.1) ────────────────────────
# 15 Aug 2026, Емил: "ДА Е НА ВСИЧКИТЕ 48 СТЪПКИ ТОЙ".
# Единственият общ проход на всяка стъпка от цикъла е memory.heartbeat.beat().
# Затова мозъкът се закача ТАМ: щом стъпка бие пулс, мозъкът я вижда — без да
# трябва да пипам 48 отделни места и без стъпка да може да се промъкне покрай него.
#
# Цената е реална и я меря: това е ~50 повиквания на цикъл. Затова тук се ползва
# НАЙ-БЪРЗИЯТ наличен модел и къс отговор (~4s/стъпка => ~3 мин на цикъл),
# докато дългите разсъждения (план, аутопсия, дебриф) вървят на силния модел.
STEP_LOG = BASE / "memory" / "brain_step_log.jsonl"
STANCE = BASE / "memory" / "brain_stance.json"
_AVAILABLE: bool | None = None
_FAST: str | None = None


def _fast_model() -> str | None:
    """Най-малкият инсталиран модел — за преценка на всяка стъпка, не за есета."""
    global _FAST
    if _FAST is None:
        ms = [m for m in models() if m]
        def _size(name):
            m = re.search(r":(\d+(?:\.\d+)?)b", str(name).lower())
            return float(m.group(1)) if m else 99.0
        _FAST = sorted(ms, key=_size)[0] if ms else ""
    return _FAST or None


def _prev_step_output() -> tuple:
    """Какво изкара ПРЕДИШНАТА стъпка — истинските ѝ редове от лога на цикъла.
    Така мозъкът не само обявява намерение, а съди и резултата преди него."""
    try:
        logs = sorted((BASE / "memory" / "cycle_logs").glob("cycle_*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return "", ""
        lines = logs[0].read_text(encoding="utf-8", errors="ignore").splitlines()[-400:]
        idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].lstrip().startswith("[STEP] "):
                idx = i
                break
        if idx is None:
            return "", ""
        prev_name = lines[idx].split("[STEP] ", 1)[1].strip()
        body = [l.strip()[:200] for l in lines[idx + 1:] if l.strip()][-12:]
        return prev_name, "\n".join(body)
    except Exception:
        return "", ""


def attend(step: str) -> dict | None:
    """Мозъкът застава пред всяка стъпка: съди какво излезе от предишната и казва
    какво очаква от тази. Присъдата се пише в memory/brain_step_log.jsonl, а
    последната — в memory/brain_stance.json, откъдето стъпките могат да я четат
    (stance()). FAIL-OPEN и изключваема с CORTEX_BRAIN_ATTEND=0."""
    global _AVAILABLE
    import os
    if os.environ.get("CORTEX_BRAIN_ATTEND", "1") == "0":
        return None
    if _AVAILABLE is None:
        _AVAILABLE = bool(models())
    if not _AVAILABLE:
        return None
    mdl = _fast_model()
    if not mdl:
        return None

    prev_name, prev_out = _prev_step_output()
    plan = current_plan()
    prompt = (
        "Ти си мозъкът на CORTEX++ и стоиш на всяка стъпка от собствения си цикъл.\n"
        f"ТВОЯТ ПЛАН ДНЕС: фокус={plan.get('focus')!r}; следиш={plan.get('watch')!r}; "
        f"тест за успех={str(plan.get('success_test'))[:120]!r}\n"
        f"ТЯЛО: {_body()}\n"
        f"ПРЕДИШНА СТЪПКА: {prev_name or '(няма)'}\n"
        f"НЕЙНИЯТ ИЗХОД:\n{prev_out or '(празно)'}\n\n"
        f"СЕГА ЗАПОЧВА: {step}\n\n"
        'Отговори САМО с JSON: {"prev_ok": true/false, "prev_note": "кратко: какво '
        'излезе от предишната", "stance": "върви|следи|пропусни", "expect": "какво '
        'очакваш от тази стъпка (кратко)"}\n'
        "Кратко. Ако предишната е дала празен/подозрителен резултат — кажи го."
    )
    try:
        import requests as _rq
        _, base = _pick_model()
        r = _rq.post(f"{base}/api/chat", timeout=60, json={
            "model": mdl, "stream": False, "keep_alive": KEEP_ALIVE, "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "num_predict": 160}})
        r.raise_for_status()
        t = ((r.json().get("message") or {}).get("content") or "").strip()
        t = t.split("</think>")[-1].strip() if "</think>" in t else t
        d = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    doc = {"ts": _now(), "step": step, "prev_step": prev_name,
           "prev_ok": d.get("prev_ok"), "prev_note": str(d.get("prev_note", ""))[:300],
           "stance": str(d.get("stance", "върви"))[:20],
           "expect": str(d.get("expect", ""))[:300], "model": f"local:{mdl}"}
    try:
        STEP_LOG.parent.mkdir(parents=True, exist_ok=True)
        if STEP_LOG.exists() and STEP_LOG.stat().st_size > 5_000_000:
            STEP_LOG.replace(STEP_LOG.with_suffix(".jsonl.1"))
        with open(STEP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
        STANCE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


def stance(step: str | None = None) -> dict:
    """Какво каза мозъкът за текущата (или дадена) стъпка — за да може самата
    стъпка да се съобрази с него, вместо да я води само моят фиксиран ред."""
    try:
        d = json.loads(STANCE.read_text(encoding="utf-8"))
        return d if (step is None or d.get("step") == step) else {}
    except Exception:
        return {}


def skipped_by_brain(step: str) -> bool:
    """True, ако мозъкът е казал 'пропусни' за тази стъпка. Стъпките, които са
    ГРЪБНАК на одита (печат на цикъла, Merkle ангажимент, пулс), не питат — там
    границата е на ДЕЙСТВИЕТО, не на мисълта: мнението му се записва, но веригата
    на доказателствата не се къса по мнение."""
    BACKBONE = {"boot", "brain_briefing", "brain_debrief", "merklememory_commit",
                "body_scan", "canon_load", "dependency_check"}
    # Последната присъда е за стъпката, която тъкмо е бита — етикетът на _run()
    # понякога се различава от името на beat() (internet_intelligence/internet_agent),
    # затова се гледа последното становище, а не се търси по име.
    last = stance()
    if not last or last.get("step") in BACKBONE or step in BACKBONE:
        return False
    return str(last.get("stance", "")).strip().lower().startswith("пропусни")


if __name__ == "__main__":
    import sys
    what = sys.argv[1] if len(sys.argv) > 1 else "brief"
    print(json.dumps(brief_cycle() if what == "brief" else debrief_cycle(),
                     ensure_ascii=False, indent=2))
