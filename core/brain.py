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


def _tail_budget(text: str, budget: int, what: str) -> str:
    """Ако духът НЕ се побира, режи от НАЧАЛОТО и си го признай на глас.

    ── ЗАЩО СЪЩЕСТВУВА ТАЗИ ФУНКЦИЯ (15 август 2026) ────────────────────────
    Тук стоеше `bg[:1400]` и `canon[:800]` — рязане от края, мълчаливо.
    Измерено на живите файлове: законът е 1816 знака, канонът 1245. Тоест
    мозъкът НИКОГА не е виждал последните 445 знака на канона, а именно там
    стои ГРАНИЦАТА:

        „CORTEX senses and advises. It never ACTUATES — it never causes an
         effect on the world outside a human decision taken per action.
         The moment a system named CORTEX actuates autonomously, it is no
         longer CORTEX; it is a different system that has taken this name."

    Срезът падаше насред думата „обрат|ими" в подцел 5. Значи мозъкът е
    получавал ЦЕЛТА БЕЗ НЕЙНАТА СТЕНА — максимата „максимизирай устойчивостта
    на разумния живот" без „ти усещаш и съветваш, никога не действаш". От
    закона пък падаха т.6 („мълчанието не е присъда") и т.7 („автономията се
    печели") — точно правилата за това как се печели доверие.

    Цел без граница е най-опасната форма, която една инструкция може да има.
    Тук тя беше произведена не от философия, а от резен.

    Затова: границите живеят НАКРАЯ на такива документи, значи при недостиг
    се жертва началото. И жертвата се ОБЯВЯВА — отрязан дух, който мълчи, е
    същото като липсващ дух, който лъже."""
    if len(text) <= budget:
        return text
    keep = text[-budget:]
    return (f"[ВНИМАНИЕ: {what} не се побира — отрязани са първите "
            f"{len(text) - budget} знака от {len(text)}. Виждаш КРАЯ, защото "
            f"там стоят границите. Ако решението ти зависи от отрязаното, "
            f"кажи го вместо да гадаеш.]\n" + keep)


# Духът е ~3 KB общо. Материалът, който така или иначе се подава, е до 5 KB.
# Затова таванът тук е висок нарочно: няма причина точно СЪВЕСТТА да е орязаната.
SPIRIT_LAW_BUDGET = 6000
SPIRIT_CANON_BUDGET = 6000


def _spirit() -> str:
    """Кой е и защо съществува — законът плюс активния канон, ЦЕЛИ."""
    out, missing = [], []
    try:
        law = LAW_FILE.read_text(encoding="utf-8")
        bg = law.split("## BG", 1)[-1].split("## EN", 1)[0].strip()
        out.append("ЗАКОН:\n" + _tail_budget(bg, SPIRIT_LAW_BUDGET, "законът"))
    except Exception as e:
        missing.append(f"ЗАКОНЪТ не се чете ({type(e).__name__})")
    try:
        canon = (BASE / "memory" / "active_canon_frame.txt").read_text(encoding="utf-8")
        out.append("КАНОН (цел + граница):\n"
                   + _tail_budget(canon, SPIRIT_CANON_BUDGET, "канонът"))
    except Exception as e:
        missing.append(f"КАНОНЪТ не се чете ({type(e).__name__})")
    if missing:
        # Липсващият дух не бива да изглежда като липсващ ред. Мозък без канон
        # трябва ДА ЗНАЕ, че е без канон — иначе ще действа все едно го е чел.
        out.append("[ВНИМАНИЕ: " + "; ".join(missing) +
                   " — мислиш БЕЗ част от духа си. Отбележи го в отговора си.]")
    return "\n\n".join(out) or "(НЯМА КАНОН И НЯМА ЗАКОН — мислиш без дух)"


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
          remember_it: bool = True, temperature: float = 0.2,
          fast: bool = False) -> dict | None:
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
    # fast=True: къса преценка, която се повтаря десетки пъти в един цикъл
    # (напр. по един показател). Силният модел е за дългите разсъждения.
    if fast:
        model = _fast_model() or model
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
    # 15 авг 2026, стъпка 4. Kimi защити преместването на плана след одобренията с
    # довода „human_approvals преди плана е КОНСТРЕЙНТ, не опция". Проверих дали
    # това е вярно в кода, вместо да го приема: НЕ беше. Планът четеше
    # pending_approvals.json (какво ЧАКА решение), но не и approvals_ledger.jsonl
    # (какво човекът е РЕШИЛ). Тоест новият ред беше наполовина козметичен — думата
    # на човека стигаше до системата, но не и до плана. Същото за тялото: четеше се
    # хомеостазата, но не и адаптивните директиви, които body_scan току-що е издал.
    for rel, cap in (("memory/deductions_latest.json", 1800),
                     ("memory/homeostasis_latest.json", 600),
                     ("memory/adaptive_directives.json", 400),
                     ("memory/goal_score_history.json", 700),
                     ("memory/diagnosis_latest.json", 700),
                     ("memory/approvals_ledger.jsonl", 700),
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
    # cycle_id се записва В плана, за да може current_plan() да различи днешния
    # от вчерашния (стъпка 2, консенсус с Kimi, 15 авг).
    _cid = None
    try:
        _cid = json.loads((BASE / "memory" / "heartbeat.json").read_text(
            encoding="utf-8")).get("cycle_id")
    except Exception:
        pass
    doc = {"ts": _now(), "cycle_id": _cid, **{k: v for k, v in d.items()}}
    try:
        PLAN.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


def current_plan() -> dict:
    """Всяка стъпка може да пита: 'какво иска мозъкът от мен днес?'

    15 авг 2026, следствие от консенсуса с Kimi по стъпка 2: планът вече се пише
    СЛЕД тялото, значи първите няколко стъпки (boot, body_scan, одобренията) текат,
    докато днешен план още няма. Тогава на диска стои ВЧЕРАШНИЯТ. Да го върнем като
    „днешния" би било тихо лъжене на всяка ранна стъпка — затова план от друг цикъл
    се маркира като стар и не се представя за днешен."""
    try:
        d = json.loads(PLAN.read_text(encoding="utf-8"))
    except Exception:
        return {}
    try:
        hb = json.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
        cid = hb.get("cycle_id")
        if cid and d.get("cycle_id") and str(d["cycle_id"]) != str(cid):
            return {"_stale": True, "_written_for": d.get("cycle_id"),
                    "_note": "план от предишен цикъл — днешният още не е писан"}
    except Exception:
        pass
    return d


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
    Така мозъкът не само обявява намерение, а съди и резултата преди него.

    ── ИМЕТО ИДВА ОТ ПУЛСА, НЕ ОТ ПОВТОРНО ЧЕТЕНЕ (17 авг 2026) ──────────────
    Дотук тази функция вземаше ПОСЛЕДНИЯ [STEP] ред от лога. Но beat() пише този
    ред ПРЕДИ да повика мозъка, значи последният ред е СЕГАШНАТА стъпка: върнатото
    „prev_name" беше самата стъпка, във всичките 53 реда от 17 авг. Нотариусът
    после сравняваше стъпка със себе си и наричаше това обещание.

    beat() вече хваща предишното име ПРЕДИ да напише новото и го пази
    (memory.heartbeat.previous_step). Тук се чете пазеното, а логът се ползва само
    за ТЯЛОТО — редовете между маркера на предишната стъпка и следващия маркер.
    """
    try:
        kept = None
        try:
            from memory.heartbeat import previous_step
            kept = previous_step()
        except Exception:
            kept = None
        if not kept:
            return "", ""          # първата стъпка: няма предшественик, и се казва

        logs = sorted((BASE / "memory" / "cycle_logs").glob("cycle_*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return kept, ""
        lines = logs[0].read_text(encoding="utf-8", errors="ignore").splitlines()[-400:]

        # Последният маркер, който НОСИ ИМЕТО НА ПАЗЕНАТА СТЪПКА — не просто
        # последният маркер, който вече е нашият.
        start = None
        for i in range(len(lines) - 1, -1, -1):
            s = lines[i].lstrip()
            if s.startswith("[STEP] ") and s.split("[STEP] ", 1)[1].strip() == kept:
                start = i
                break
        if start is None:
            return kept, ""

        body = []
        for l in lines[start + 1:]:
            if l.lstrip().startswith("[STEP] "):
                break              # стигнахме следващата стъпка — тялото свърши
            if l.strip():
                body.append(l.strip()[:200])
        return kept, "\n".join(body[-12:])
    except Exception:
        return "", ""


# Колко чака мозъкът на ЕДНА стъпка. Стои като явна константа, защото е
# компромис, не истина: твърде малко — мозъкът мълчи на всяка тежка стъпка;
# твърде много — един заспал модел бави целия цикъл ~50 пъти.
ATTEND_TIMEOUT = 60


def _record_silence(step: str, prev_step: str | None, model: str, why: str,
                    sec: float, prompt_chars: int) -> None:
    """Мълчанието на мозъка е СЪБИТИЕ, не липса на събитие (законът, т.6).

    Без този запис „мозъкът е на всяка стъпка" е непроверимо твърдение: в
    дневника се виждат само стъпките, на които е ПРОГОВОРИЛ, и никой не може да
    различи «мозъкът реши да мълчи» от «мозъкът никога не беше попитан»."""
    doc = {"ts": _now(), "step": step, "prev_step": prev_step,
           "stance": "reflex:мълчание", "silent": True, "why": why,
           "sec": sec, "prompt_chars": prompt_chars, "model": f"local:{model}"}
    try:
        STEP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(STEP_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
    except Exception:
        pass


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
    # ── УМ, ДУХ И ТЯЛО + ЦЕЛ — В ЕДНО (Емил, 15 август 2026) ────────────────
    # Дотук ТУК имаше само УМ и ТЯЛО. Проверено ред по ред: този промпт носеше
    # плана, тялото, предишната стъпка и текущата — и НИТО ЕДНА дума от духа:
    # без канон, без цел, без граница, без памет. А точно този промпт е мозъкът
    # НА ВСЯКА СТЪПКА; think() го носи всичко, но think() се вика няколко пъти
    # на цикъл, докато attend() — при всеки beat.
    # Тоест законът, т.5 („Той носи тялото, духа и паметта си във ВСЯКА мисъл")
    # се спазваше на редките мисли и се нарушаваше на честите.
    # Цената е призната честно: духът е ~3 KB, тоест ~+800 токена на стъпка при
    # локален модел. Това е цената на това мозъкът да знае за какво съществува,
    # докато решава дали да пропусне стъпка. По-евтиният вариант — да му подадем
    # само „главното" от духа — е точно резенът, който днес отряза границата.
    prompt = (
        "Ти си мозъкът на CORTEX++ и стоиш на всяка стъпка от собствения си цикъл.\n\n"
        f"ДУХ (кой си, за какво съществуваш и къде ти е границата):\n{_spirit()}\n\n"
        f"ПАМЕТ (твои предишни присъди по стъпки):\n{_memory('step_stance', n=3)}\n\n"
        f"ТВОЯТ ПЛАН ДНЕС: фокус={plan.get('focus')!r}; следиш={plan.get('watch')!r}; "
        f"тест за успех={str(plan.get('success_test'))[:120]!r}\n"
        f"ТЯЛО: {_body()}\n"
        # ── ПРАЗНАТА КЛЕТКА НЕ СЕ ПОДАВА (15 август 2026) ───────────────────
        # Първите два реални записа на attend() дадоха ЕДНО И СЪЩО празно
        # prev_step и ДВЕ ПРОТИВОПОЛОЖНИ присъди: веднъж prev_ok=true „изпълнена
        # успешно", веднъж prev_ok=false „не всички мрежи достигнаха нужната
        # точност" — при това вторият описваше проект за обучение на невронни
        # мрежи с екип, какъвто тук няма. 3B модел, изправен пред празна клетка,
        # я запълва с правдоподобна проза.
        # Затова празната клетка вече НЕ СЕ ПОКАЗВА. Не питаш за нещо, което го
        # няма, и после не филтрираш отговора — не даваш повод за отговор.
        + (f"ПРЕДИШНА СТЪПКА: {prev_name}\n"
           f"НЕЙНИЯТ ИЗХОД:\n{prev_out}\n\n" if (prev_name and prev_out) else
           "ПРЕДИШНА СТЪПКА: НЯМА (това е първата стъпка или изходът ѝ не се вижда).\n"
           "НЕ съди предишната стъпка — за нея нямаш доказателство. Остави prev_ok "
           "и prev_note празни.\n\n")
        + f"СЕГА ЗАПОЧВА: {step}\n\n"
        + ('Отговори САМО с JSON: {"prev_ok": true/false, "prev_note": "кратко: какво '
           'излезе от предишната", ' if (prev_name and prev_out) else
           'Отговори САМО с JSON: {')
        + '"stance": "върви|следи|пропусни", "expect": "какво '
          'очакваш от тази стъпка (кратко)", "serves_goal": "с едно изречение: как '
          'ТАЗИ стъпка служи на целта, или защо не ѝ служи"}\n'
        + ("Кратко. Ако предишната е дала празен/подозрителен резултат — кажи го."
           if (prev_name and prev_out) else
           "Кратко. Говори САМО за стъпката, която започва сега.")
    )
    # ── МЪЛЧАНИЕТО СЕ ЗАПИСВА (законът, т.6) ───────────────────────────────
    # Дотук всяка несполука тук се връщаше като None БЕЗ СЛЕДА. Затова днешният
    # brain_step_log.jsonl съдържа ЕДИН ред за ~50 стъпки, а защо липсват
    # останалите 49 — никой не може да каже. Законът е изричен: „Мълчанието не е
    # присъда. Ако мозъкът не отговори, тялото пада на рефлекс — и това се
    # записва явно: reflex:* и защо." Мълчаливото None нарушаваше собствения му
    # закон и правеше диагнозата невъзможна.
    t0 = time.time()
    d, silence = None, None
    try:
        import requests as _rq
        _, base = _pick_model()
        r = _rq.post(f"{base}/api/chat", timeout=ATTEND_TIMEOUT, json={
            "model": mdl, "stream": False, "keep_alive": KEEP_ALIVE, "format": "json",
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.1, "num_predict": 220}})
        r.raise_for_status()
        t = ((r.json().get("message") or {}).get("content") or "").strip()
        t = t.split("</think>")[-1].strip() if "</think>" in t else t
        d = json.loads(t[t.find("{"): t.rfind("}") + 1])
        if not isinstance(d, dict):
            d, silence = None, f"отговор, който не е обект: {type(d).__name__}"
    except Exception as e:
        silence = f"{type(e).__name__}: {e}"

    if d is None:
        _record_silence(step, prev_name, mdl, silence or "неизвестна причина",
                        round(time.time() - t0, 1), len(prompt))
        return None

    # ── ПРИСЪДА БЕЗ ДОКАЗАТЕЛСТВО СЕ ОТМЕНЯ ОТ ИЗВИКВАЩИЯ ──────────────────
    # Дори с поправения промпт моделът може да произнесе нещо за предишната
    # стъпка. Затова тук стои втора, механична преграда: няма ли доказателство,
    # няма присъда — независимо какво е казал. И казаното НЕ се изтрива, а се
    # пази в prev_ok_model_said, защото честотата на съчиняването е измерване:
    # без нея никога няма да знаем колко често мозъкът запълва празни клетки.
    _has_evidence = bool(prev_name) and bool(prev_out)
    _blocked = None
    if not prev_name:
        _blocked = "no_previous_step: това е първата стъпка — няма какво да се съди"
    elif not prev_out:
        _blocked = (f"no_visible_output: '{prev_name}' не е оставила видим изход — "
                    f"липсата на изход не е доказателство за провал")

    doc = {"ts": _now(), "step": step, "prev_step": prev_name or None,
           "prev_ok": (d.get("prev_ok") if _has_evidence else None),
           "prev_note": (str(d.get("prev_note", ""))[:300] if _has_evidence else None),
           "prev_verdict_blocked": _blocked,
           "prev_ok_model_said": (None if _has_evidence else d.get("prev_ok")),
           "prev_note_model_said": (None if _has_evidence
                                    else str(d.get("prev_note", ""))[:200] or None),
           "stance": str(d.get("stance", "върви"))[:20],
           "expect": str(d.get("expect", ""))[:300],
           # СЛУЖИ ЛИ ТАЗИ СТЪПКА НА ЦЕЛТА — питаме го, защото сега вече знае целта.
           "serves_goal": str(d.get("serves_goal", ""))[:300],
           "sec": round(time.time() - t0, 1),
           "model": f"local:{mdl}"}
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
    """Мозъкът ИСКА да пропусне; графът казва МОЖЕ ЛИ. Действие само при двете.

    15 авг 2026 — падна ръчният списък „гръбнак от 7 стъпки". Kimi го събори с
    едно изречение: „критерият е сгрешен по същество, защото разделя по
    имплементационна обвивка, а не по семантична критичност... това не е гръбнак,
    а коремна кухина със спинален имплант." Прав беше: естетичен отчет в обвивка
    минаваше за пропускаем, а проверка на източник inline — за неприкосновена.
    Сега границата е СЛЕДСТВИЕ от графа (core.cycle_graph, MeTTa): пропуска се
    само стъпка, чийто продукт никой надолу не чака. Ако графът не знае —
    не се пропуска. Незнанието не е разрешение."""
    last = stance()
    if not last:
        return False
    wants = str(last.get("stance", "")).strip().lower().startswith("пропусни")
    if not wants:
        return False
    try:
        from core.cycle_graph import can_skip
        import json as _j
        from datetime import datetime as _dt
        try:                       # началото на ТОЗИ цикъл, не последните 24ч
            hb = _j.loads((BASE / "memory" / "heartbeat.json").read_text(encoding="utf-8"))
            since = _dt.fromisoformat(hb["cycle_id"]).timestamp()
        except Exception:
            since = None
        v = can_skip(step, since)
    except Exception as e:
        remember("skip_denied", f"{step}: графът не се зареди ({type(e).__name__})")
        return False
    ok = v.get("verdict") == "РАЗРЕШЕНО"
    remember("skip_decision",
             f"{step}: мозъкът иска пропускане; графът казва {v.get('verdict')} — {v.get('why')}",
             {"blockers": v.get("blockers", [])})
    return ok


def watching(step: str) -> bool:
    """„следи" вече значи нещо. Досега мозъкът можеше да каже 'следи' и това не
    водеше доникъде — дадена дума без последствие (хванато от Kimi: „каква е
    семантиката на 'следи'? никъде не е казано"). Сега стъпката се изпълнява, но
    се маркира като наблюдавана и излиза отделно в отчета на цикъла."""
    last = stance()
    return bool(last) and str(last.get("stance", "")).strip().lower().startswith("следи")


if __name__ == "__main__":
    import sys
    what = sys.argv[1] if len(sys.argv) > 1 else "brief"
    print(json.dumps(brief_cycle() if what == "brief" else debrief_cycle(),
                     ensure_ascii=False, indent=2))
