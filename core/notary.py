#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/notary.py — НОТАРИУСЪТ НА АВТОНОМИЯТА (15 август 2026)

Роден от консенсус с Kimi, който отхвърли и моята позиция, и предпоставката на
въпроса. Емил питаше за „когнитивен оркестратор на всяка стъпка". Аз възразих, че
трети мислещ глас само дублира мозъка и графа. Kimi показа, че и двамата гледаме
накриво:

  „Грешиш, че политиката е нужна само при действие — тя трябва при ПРОИЗХОДА на
   данните. MeTTa следи какво зависи от какво, но не и ПОД КАКЪВ РЕЖИМ е
   произведено. Стъпка 18 може да има твърда порта, но ако входът ѝ е роден на
   стъпка 5 при channel_alive=false, портата е СЛЯПА."
  „Третият слой не е оркестратор — той е НОТАРИУС НА АВТОНОМИЯТА: на всяка стъпка
   подпечатва продукта с текущото ниво на доверие. Без тази верига на атестация,
   портата одобрява необратимо действие върху данни с неизвестен произход —
   архитектурна лъжа."
  „MeTTa е грешен език за това — той е дедуктивен, не деонтичен; 'позволено' не се
   извежда от факти. Нужен е ЛЕК СЛОЙ (не LLM)."

Значи трите гласа на всяка стъпка са три РАЗЛИЧНИ РОДА знание, не три мнения:
    мозъкът   — какво МИСЛЯ            (вероятностно)
    MeTTa     — какво СЛЕДВА ОТ ФАКТИТЕ (дедуктивно)
    нотариусът— ПОД КАКЪВ РЕЖИМ е произведено това (произход)

ТРИТЕ РЕШЕНИЯ, които той взе вместо мен
---------------------------------------
1) ВЕКТОР ЗА ЗАПИС, СКАЛАР ЗА ПОРТАТА.
   „Скаларът е min(вектор), портата отказва при подминаване на праг. Така пазиш
    защо, но решението е детерминистично."
   Възразих му на едно: min прави всички лоши състояния еднакви — „MeTTa мълчи"
   се лекува с рестарт, „входът е на 400 дни" не се лекува изобщо. Затова портата
   получава скалара ЗА РЕШЕНИЕТО и вектора ЗА ОБЯСНЕНИЕТО (виж refuse_reason).

2) НАСЛЕДЯВАНЕ С ИЗМИВАНЕ.
   „Наследява най-лошото, но с измиване: стъпка, валидирала входа си независимо
    срещу жив източник, слага свой печат. ТРАНСФОРМАЦИИТЕ НАСЛЕДЯВАТ;
    ВЕРИФИКАЦИИТЕ ПРЕЧУПВАТ."
   Това реши дилемата, която сам му поставих: иначе една ранна стъпка в лош режим
   осъжда всичко след себе си до края на цикъла. Нивото се вдига само с РАБОТА —
   отиване до жив източник — не с изчакване и не със самооценка.

3) КОЙ ПАЗИ НОТАРИУСА.
   „Append-only log ИЗВЪН ОБСЕГА на self_modifier... Supervisor сверява хеш на
    log-а при старт — системата не може да подмени минало, защото хешът е извън нея."
   Затова дневникът НЕ е в memory/. Портата на кода (safety/ast_gate.py) допуска
   писане само под ("memory","output","data","snapshots","daily"); attestation/ не е
   между тях, тоест самомодификацията статично не може да пише тук.

ЗА КАКВО ТОЗИ МОДУЛ НЕ СТАВА
----------------------------
Той не съди КАЧЕСТВОТО на данните — само режима, при който са родени. Число,
взето при пълно доверие от източник, който лъже, ще носи най-високия печат.
Това е работа на валидатора, не на нотариуса, и не бива да се бърка.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# ИЗВЪН обсега на self_modifier: safety/ast_gate.py допуска писане само под
# ("memory","output","data","snapshots","daily"). Тази папка не е между тях.
ATTEST_DIR = BASE / "attestation"
ATTEST_LOG = ATTEST_DIR / "attest.jsonl"
ATTEST_HEAD = ATTEST_DIR / "chain.head"          # последният хеш на веригата

# Нивата. 3 = пълно доверие, 0 = нищо не се знае за произхода.
FULL, REDUCED, MINIMAL, UNKNOWN = 3, 2, 1, 0
LEVEL_NAMES = {3: "level_3 (пълно)", 2: "level_2 (намалено)",
               1: "level_1 (минимално)", 0: "level_0 (неизвестен произход)"}

# Прагът, под който НЕОБРАТИМО действие не се разрешава. Некласифицираното пада
# към най-ограниченото — както е в проекта на OpenClaw (default_unclassified).
IRREVERSIBLE_MIN = REDUCED

# Стъпки, които ВЕРИФИЦИРАТ срещу жив външен източник, вместо само да преработват.
# Само те имат право да ПРЕЧУПЯТ наследеното (Kimi: „верификациите пречупват").
# Списъкът е нарочно къс и явен: всяко добавяне тук е разширяване на правото за
# измиване и трябва да се вижда в diff-а.
VERIFIERS = {
    "global_indicators",     # ~20 живи HTTP източника
    "sensorium_ingest",      # сензорни капки с проверка на веригата
    "browser_scout",         # ходи по реални страници
    "internet_intelligence",
    "web_intelligence",
}

_STALE_DAYS = (2, 30, 365)   # праговете за давност на входовете


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── ПЕТТЕ МЕХАНИЧНИ СЪСТОЯНИЯ ───────────────────────────────────────────────
# Нито едно от тях не е мнение и нито едно не вика LLM. Всяко се чете от нещо,
# което вече съществува в системата. Затова печатът е АТЕСТАЦИЯ, а не самооценка:
# системата не може да си го подари, може само да го заслужи.

def _witness_state() -> tuple:
    """Проговори ли символният свидетел (MeTTa)."""
    try:
        from core import metta_check as mc
        if mc._ENGINE:
            return FULL, f"MeTTa: {mc._ENGINE}"
        # не строим тук нарочно — строенето е работа на metta_check, не на нотариуса
        return (FULL, f"MeTTa: {mc._ENGINE}") if mc._ENGINE else (UNKNOWN, "MeTTa мълчи")
    except Exception as e:
        return UNKNOWN, f"MeTTa недостъпен: {type(e).__name__}"


def _human_state() -> tuple:
    """Стигна ли човешката дума дотук."""
    try:
        from experiments.needs.approve_reader import channel_alive
        ok, why = channel_alive()
        if not ok:
            return UNKNOWN, f"човешкият канал: {why}"
        return (FULL, f"човешкият канал: {why}") if "alive" in why else \
               (REDUCED, f"човешкият канал: {why}")
    except Exception as e:
        return MINIMAL, f"човешкият канал непроверим: {type(e).__name__}"


def _thought_state() -> tuple:
    """Кой мисли: външен доставчик, или само локален малък модел."""
    try:
        d = json.loads((BASE / "snapshots" / "master" /
                        "dependency_check_latest.json").read_text(encoding="utf-8"))
        paths = d.get("thinking_paths") or []
        if not paths:
            return UNKNOWN, "няма нито един път до мислене"
        if paths == ["local_brain"]:
            return MINIMAL, "мисли само локалният модел"
        return FULL, f"пътища до мислене: {len(paths)}"
    except Exception:
        return MINIMAL, "състоянието на мисленето е непроверено"


def _age_state(inputs: list) -> tuple:
    """Колко стар е НАЙ-СТАРИЯТ вход, който тази стъпка чете.

    Давността е факт за произхода, не преценка: число от миналата година, влязло
    в днешния композит, е произведено при по-малко доверие, независимо колко е
    красив източникът."""
    if not inputs:
        return FULL, "стъпката не чете входове"
    now = datetime.now(timezone.utc).timestamp()
    oldest, oldest_name = None, None
    for rel in inputs:
        p = BASE / rel
        try:
            m = (max((c.stat().st_mtime for c in p.rglob("*") if c.is_file()), default=0)
                 if p.is_dir() else p.stat().st_mtime)
        except Exception:
            return UNKNOWN, f"вход липсва: {rel}"
        if m and (oldest is None or m < oldest):
            oldest, oldest_name = m, rel
    if oldest is None:
        return UNKNOWN, "възрастта на входовете е неизвестна"
    days = (now - oldest) / 86400.0
    d2, d30, d365 = _STALE_DAYS
    lvl = FULL if days <= d2 else REDUCED if days <= d30 else \
        MINIMAL if days <= d365 else UNKNOWN
    return lvl, f"най-стар вход {oldest_name}: {days:.1f} дни"


def _promise_state(prev_step: str | None) -> tuple:
    """Удържала ли е предишната стъпка обявения си продукт."""
    if not prev_step:
        return FULL, "няма предишна стъпка"
    try:
        from core import cycle_map as cm
        from core.metta_check import _cycle_start
        kept, detail = cm.kept_promise(prev_step, _cycle_start())
        lvl = {"ОБНОВИ": FULL, "ЧАСТИЧНО": REDUCED,
               "НЕ ПИПНА": MINIMAL, "НЕ ЗНАЕМ": UNKNOWN}.get(kept, UNKNOWN)
        return lvl, f"{prev_step}: {kept}"
    except Exception as e:
        return UNKNOWN, f"обещанието непроверимо: {type(e).__name__}"


def vector(step: str, prev_step: str | None = None, inputs: list | None = None) -> dict:
    """Петте състояния — записът, който пази ЗАЩО."""
    if inputs is None:
        try:
            from core.metta_check import _REQ
            inputs = list(_REQ.get(step, []))
        except Exception:
            inputs = []
    w, wl = _witness_state()
    h, hl = _human_state()
    t, tl = _thought_state()
    a, al = _age_state(inputs)
    p, pl = _promise_state(prev_step)
    return {"witness": w, "human": h, "thought": t, "age": a, "promise": p,
            "why": {"witness": wl, "human": hl, "thought": tl, "age": al, "promise": pl}}


# ── НАСЛЕДЯВАНЕТО ───────────────────────────────────────────────────────────

def _stamps() -> dict:
    """Последният печат на всеки продукт в ТЕКУЩИЯ цикъл."""
    out = {}
    try:
        from core.metta_check import _cycle_start
        since = _cycle_start()
    except Exception:
        since = 0
    try:
        for line in ATTEST_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            try:
                if datetime.fromisoformat(d["ts"]).timestamp() < since:
                    continue
            except Exception:
                continue
            for f in d.get("products", []):
                out[f] = d
    except Exception:
        pass
    return out


def attest(step: str, prev_step: str | None = None) -> dict:
    """Подпечатва продуктите на стъпката. Лек, детерминистичен, без LLM."""
    try:
        from core import cycle_map as cm
        products = []
        for name, _idx, _purpose, prod, _bb in cm.STEPS:
            if name == step:
                products = list(prod)
                break
        from core.metta_check import _REQ
        inputs = list(_REQ.get(step, []))
    except Exception:
        products, inputs = [], []

    vec = vector(step, prev_step, inputs)
    own = min(vec[k] for k in ("witness", "human", "thought", "age", "promise"))

    # НАСЛЕДЯВАНЕ: най-лошото от печатите на входовете...
    stamps = _stamps()
    inherited, from_who = FULL, None
    for rel in inputs:
        s = stamps.get(rel)
        if s and s.get("level") is not None and s["level"] < inherited:
            inherited, from_who = s["level"], rel

    # ...ОСВЕН ако тази стъпка е ВЕРИФИКАЦИЯ срещу жив източник: тя пречупва.
    verified = step in VERIFIERS
    level = own if verified else min(own, inherited)

    rec = {"ts": _now(), "step": step, "prev_step": prev_step,
           "vector": {k: vec[k] for k in ("witness", "human", "thought", "age", "promise")},
           "why": vec["why"], "own": own, "inherited": inherited,
           "inherited_from": from_who, "verifier": verified, "level": level,
           "level_name": LEVEL_NAMES.get(level, str(level)),
           "products": products, "inputs": inputs}
    _append(rec)
    return rec


# ── APPEND-ONLY ВЕРИГА ──────────────────────────────────────────────────────
# Всеки ред носи хеша на предишния. Върхът стои в chain.head. Подмяна на минало
# къса веригата и се вижда отвън — от супервайзора, не от системата.

def _append(rec: dict) -> None:
    try:
        ATTEST_DIR.mkdir(parents=True, exist_ok=True)
        try:
            prev = ATTEST_HEAD.read_text(encoding="utf-8").strip()
        except Exception:
            prev = "GENESIS"
        rec["prev"] = prev
        body = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
        rec["hash"] = h
        with open(ATTEST_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tmp = ATTEST_HEAD.with_suffix(".tmp")
        tmp.write_text(h, encoding="utf-8")
        os.replace(tmp, ATTEST_HEAD)
    except Exception:
        pass


def verify_chain() -> dict:
    """Сверява веригата. Вика се от супервайзора ПРИ СТАРТ — отвън, не отвътре."""
    if not ATTEST_LOG.exists():
        return {"ok": True, "records": 0, "note": "няма още атестации"}
    prev, n = "GENESIS", 0
    try:
        for line in ATTEST_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            claimed, stored_prev = d.pop("hash", None), d.get("prev")
            if stored_prev != prev:
                return {"ok": False, "records": n,
                        "broken_at": n + 1, "why": "връзката към предишния ред не съвпада"}
            body = json.dumps(d, ensure_ascii=False, sort_keys=True)
            h = hashlib.sha256((prev + body).encode("utf-8")).hexdigest()
            if h != claimed:
                return {"ok": False, "records": n, "broken_at": n + 1,
                        "why": "съдържанието на реда е променяно след записа"}
            prev, n = h, n + 1
    except Exception as e:
        return {"ok": False, "records": n, "why": f"{type(e).__name__}: {e}"}
    try:
        head = ATTEST_HEAD.read_text(encoding="utf-8").strip()
    except Exception:
        head = None
    if head and head != prev:
        return {"ok": False, "records": n, "why": "върхът на веригата не съвпада с дневника"}
    return {"ok": True, "records": n, "head": prev[:16]}


# ── ПОРТАТА ─────────────────────────────────────────────────────────────────

def may_act(step: str) -> tuple:
    """Разрешено ли е НЕОБРАТИМО действие сега. (може_ли, обяснение).

    Скаларът решава (Kimi: детерминистично). Векторът обяснява — това е моето
    възражение към чистия min: „MeTTa мълчи" и „входът е на 400 дни" дават едно и
    също ниво, но искат различни действия. Портата трябва да каже КОЕ липсва.
    """
    rec = attest(step)
    lvl = rec["level"]
    if lvl >= IRREVERSIBLE_MIN:
        return True, f"{rec['level_name']}"
    weak = [k for k, v in rec["vector"].items() if v == lvl]
    why = "; ".join(rec["why"][k] for k in weak)
    src = (f" (наследено от {rec['inherited_from']})"
           if rec["inherited"] < rec["own"] and rec["inherited_from"] else "")
    return False, f"{rec['level_name']}{src} — слабо звено: {why}"


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        print(json.dumps(verify_chain(), ensure_ascii=False, indent=2))
    else:
        s = next((a for a in sys.argv[1:] if not a.startswith("--")), "global_indicators")
        print(json.dumps(attest(s), ensure_ascii=False, indent=2))
        print("\nможе ли необратимо:", may_act(s))
