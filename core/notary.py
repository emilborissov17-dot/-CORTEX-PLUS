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

# ── ЯВНИ МАРКЕРИ ЗА ПРЕДШЕСТВЕНИКА ─────────────────────────────────────────
# Извикващият ТРЯБВА да каже кое от двете е вярно. Няма стойност по подразбиране,
# която значи доверие: PREV_UNKNOWN е подразбирането и той струва 0.
PREV_UNKNOWN = "__prev_unknown__"      # никой не знае / не е казал -> UNKNOWN
PREV_NONE = "__no_previous_step__"     # явно: това Е първата стъпка -> FULL

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


# Колко пресен трябва да е самият ОТЧЕТ, за да значи нещо: approve_reader върви
# на всеки цикъл и на всеки 10 мин по график, така че запис на повече от 6 часа
# описва канала от снощи, не отсега.
HUMAN_CHECK_FRESH_H = 6
# Колко назад „човек е писал" още е доказателство, че някой наглежда канала.
# Одобренията не са ежедневни; седмица е щедро, но крайно.
HUMAN_ACT_DAYS = 7


def _age_hours(ts: str | None):
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0
    except Exception:
        return None


def _human_state() -> tuple:
    """Стигна ли човешката дума дотук — и колко от нея наистина е доказана.

    КАКВО ТОЗИ ПРОВЕРКА МОЖЕ И КАКВО НЕ МОЖЕ ДА ДОКАЖЕ (17 авг 2026)
    -----------------------------------------------------------------
    Три различни неща стояха слети в едно:

      ДОСТИЖИМОСТ  Telegram върна 200. Доказва, че ТРАНСПОРТЪТ работи.
                   За човек не доказва нищо.
      ПРИСЪСТВИЕ   човек наистина е писал нещо през канала наскоро. Слабо, но
                   истинско доказателство, че някой наглежда.
      СЪГЛАСИЕ     човек е одобрил ТОВА действие. Каналът НИКОГА не доказва
                   това — съгласието е за отделно действие и живее в
                   pending_approvals/declined_approvals, не тук.

    Дотук „200 OK, 0 нови съобщения" даваше FULL — най-високата оценка за
    човешки произход се присъждаше на факт за един HTTP endpoint. Затова
    таванът тук е РЕАЛНОСТТА: без следа от човешко действие каналът стига най-
    много до REDUCED. FULL иска човек наистина да е проговорил.

    И, измерено преди поправката:

        не проверен изобщо   -> REDUCED(2)  МИНАВА портата
        проверен, мъртъв     -> UNKNOWN(0)  спира
        запис нечетим        -> REDUCED(2)  МИНАВА портата

    Тоест най-евтиният начин да отвориш портата беше да не гледаш. Липсата на
    проверка вече не може да струва повече от проверена лоша новина: всичко
    непроверено е UNKNOWN, наравно с мъртъв канал.
    """
    try:
        from experiments.needs.approve_reader import channel_state
        st = channel_state()
    except Exception as e:
        # Непроверимо е UNKNOWN, не MINIMAL. Преди беше MINIMAL — пак по-високо
        # от проверен провал, същата дупка с друго име.
        return UNKNOWN, f"човешкият канал непроверим: {type(e).__name__}"

    state = str(st.get("state", "unknown"))
    why = str(st.get("why", ""))
    tag = f"човешкият канал: {state}: {why}"

    if state in ("unknown", "dead"):
        return UNKNOWN, tag
    if state == "not_configured":
        # Проверен, определен отговор: няма човешки път. Знанието е честно, но
        # път до човек няма — под прага за необратимо.
        return MINIMAL, tag

    if state != "alive":
        return UNKNOWN, f"{tag} (непознато състояние)"

    checked_h = _age_hours(st.get("ts"))
    if checked_h is None:
        return UNKNOWN, f"{tag} — записът няма годно време"
    if checked_h > HUMAN_CHECK_FRESH_H:
        return MINIMAL, (f"{tag} — но проверката е отпреди "
                         f"{checked_h:.0f}ч (>{HUMAN_CHECK_FRESH_H}ч)")

    acted_h = _age_hours(st.get("last_human_msg_utc"))
    if acted_h is not None and acted_h <= HUMAN_ACT_DAYS * 24:
        return FULL, f"{tag} — човек е писал преди {acted_h:.0f}ч"
    return REDUCED, (f"{tag} — каналът отговаря, но няма човешко действие"
                     + (f" от {acted_h / 24:.0f}д" if acted_h is not None else " изобщо"))


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


def _inputs_for(step: str) -> tuple:
    """(входовете на стъпката, ОТКЪДЕ идва списъкът).

    Два източника, в този ред на предимство (18 авг 2026):
      1. config/step_inputs.json — НАПИСАН от човек за стъпките, които назовава.
      2. статичният скенер (core/cycle_graph.scan_requires през metta_check._REQ).

    Източникът се връща заедно със списъка, за да може портата да КАЖЕ на какво
    се е доверила. Ниво без произход на решението е число; с произход е запис.

    Стъпка, за която никой не е писал, минава по точка 2 непроменена — включително
    когато скенерът мълчи и списъкът е празен, което си остава НЕИЗВЕСТНО.
    """
    try:
        from core.declared_inputs import for_step, SOURCE_WRITTEN
        written = for_step(step)
        if written is not None:
            return list(written), SOURCE_WRITTEN
    except Exception:
        pass                                   # няма файл -> както преди файла
    try:
        from core.declared_inputs import SOURCE_SCANNER as _src
    except Exception:
        _src = "the static scanner"
    try:
        from core.metta_check import _REQ
        return list(_REQ.get(step, [])), _src
    except Exception:
        return [], _src


def _age_state(inputs: list, source: str | None = None) -> tuple:
    """Колко стар е НАЙ-СТАРИЯТ вход, който тази стъпка чете.

    Давността е факт за произхода, не преценка: число от миналата година, влязло
    в днешния композит, е произведено при по-малко доверие, независимо колко е
    красив източникът.

    `source` е ОТКЪДЕ е списъкът (виж _inputs_for). Влиза в обяснението, а не в
    оценката: кой е обявил входовете не прави входовете по-пресни."""
    tail = f" (входовете идват от {source})" if source else ""
    if not inputs:
        # ── FAIL CLOSED (17 авг 2026) ───────────────────────────────────────
        # Тук стоеше `return FULL, "стъпката не чете входове"` — празният списък
        # се четеше като „няма какво да остарее, значи всичко е наред". Но празен
        # списък не значи „не чете входове"; значи „не знаем какво чете".
        # Измерено срещу docs/MODULE_MAP.json: 27 от 53 стъпки подават празен
        # списък, и 17 от тях ЧЕТАТ файлове — през пътища, които никой статичен
        # скенер не може да разреши. Липсата на доказателство се оценяваше като
        # максимално доказателство.
        # Това е и правилото, което core/cycle_graph.py обявява в своя докстринг:
        # „неизвестното НЕ е пропускаемо".
        return UNKNOWN, "no declared inputs - provenance unknown" + tail
    now = datetime.now(timezone.utc).timestamp()
    oldest, oldest_name = None, None
    for rel in inputs:
        p = BASE / rel
        try:
            m = (max((c.stat().st_mtime for c in p.rglob("*") if c.is_file()), default=0)
                 if p.is_dir() else p.stat().st_mtime)
        except Exception:
            return UNKNOWN, f"вход липсва: {rel}" + tail
        if m and (oldest is None or m < oldest):
            oldest, oldest_name = m, rel
    if oldest is None:
        return UNKNOWN, "възрастта на входовете е неизвестна" + tail
    days = (now - oldest) / 86400.0
    d2, d30, d365 = _STALE_DAYS
    lvl = FULL if days <= d2 else REDUCED if days <= d30 else \
        MINIMAL if days <= d365 else UNKNOWN
    return lvl, f"най-стар вход {oldest_name}: {days:.1f} дни" + tail


def _promise_state(prev_step: str | None, step: str | None = None) -> tuple:
    """Удържала ли е предишната стъпка обявения си продукт.

    НЯМА ПОДРАЗБИРАНЕ, КОЕТО ЗНАЧИ ДОВЕРИЕ (17 авг 2026). Дотук `not prev_step`
    връщаше FULL — тоест „никой не ми каза предшественика" се четеше като
    „предишната си удържа думата". may_act() вика attest() БЕЗ prev_step, значи
    точно на портата — единственото място, където векторът се налага — това
    измерение беше структурно FULL. Едно от пет изключено, тихо.

    Сега трите случая са РАЗЛИЧНИ и само първият е доверие:
      PREV_NONE      — явно обявено „това е първата стъпка"      -> FULL
      PREV_UNKNOWN / None / празно — никой не е казал            -> UNKNOWN
      prev_step == step — стъпката е свой собствен предшественик -> UNKNOWN
    """
    if prev_step == PREV_NONE:
        return FULL, "няма предишна стъпка (обявено явно)"
    if prev_step is None or prev_step == PREV_UNKNOWN or not str(prev_step).strip():
        return UNKNOWN, ("предишната стъпка не е обявена — обещанието е "
                         "непроверимо, а непроверимото не е удържано")
    if step is not None and str(prev_step) == str(step):
        # Сравнение със себе си не е доказателство. Виж core/brain.py:
        # _prev_step_output() чете ПОСЛЕДНИЯ [STEP] ред от лога, а beat() пише
        # този ред ПРЕДИ да повика мозъка — затова „предишната" е самата стъпка,
        # във всичките 53 реда от 17 авг. Тази проверка не поправя причината;
        # тя спира резултатът ѝ да минава за удържано обещание.
        return UNKNOWN, (f"'{step}' е обявена за свой собствен предшественик — "
                         f"сравнение със себе си не е доказателство")
    try:
        from core import cycle_map as cm
        from core.metta_check import _cycle_start
        kept, detail = cm.kept_promise(prev_step, _cycle_start())
        lvl = {"ОБНОВИ": FULL, "ЧАСТИЧНО": REDUCED,
               "НЕ ПИПНА": MINIMAL, "НЕ ЗНАЕМ": UNKNOWN}.get(kept, UNKNOWN)
        return lvl, f"{prev_step}: {kept}"
    except Exception as e:
        return UNKNOWN, f"обещанието непроверимо: {type(e).__name__}"


def vector(step: str, prev_step: str | None = PREV_UNKNOWN,
           inputs: list | None = None, inputs_source: str | None = None) -> dict:
    """Петте състояния — записът, който пази ЗАЩО."""
    if inputs is None:
        inputs, resolved_src = _inputs_for(step)
        inputs_source = inputs_source or resolved_src
    w, wl = _witness_state()
    h, hl = _human_state()
    t, tl = _thought_state()
    a, al = _age_state(inputs, inputs_source)
    p, pl = _promise_state(prev_step, step)
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


def attest(step: str, prev_step: str | None = PREV_UNKNOWN) -> dict:
    """Подпечатва продуктите на стъпката. Лек, детерминистичен, без LLM."""
    try:
        from core import cycle_map as cm
        products = []
        for name, _idx, _purpose, prod, _bb in cm.STEPS:
            if name == step:
                products = list(prod)
                break
    except Exception:
        products = []
    inputs, inputs_source = _inputs_for(step)

    vec = vector(step, prev_step, inputs, inputs_source)
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
           "products": products, "inputs": inputs,
           "inputs_source": inputs_source}
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

def may_act(step: str, prev_step: str | None = PREV_UNKNOWN) -> tuple:
    """Разрешено ли е НЕОБРАТИМО действие сега. (може_ли, обяснение).

    Скаларът решава (Kimi: детерминистично). Векторът обяснява — това е моето
    възражение към чистия min: „MeTTa мълчи" и „входът е на 400 дни" дават едно и
    същo ниво, но искат различни действия. Портата трябва да каже КОЕ липсва.

    И РАЗРЕШЕНИЕТО СЕ ОБЯСНЯВА (18 авг 2026). Дотук отказът носеше причина, а
    „да" носеше само името на нивото — тоест единственият случай, в който системата
    пипа света, беше и единственият, за който записът не казваше НА КАКВО се е
    доверила. Сега и двата отговора назовават откъде идва списъкът с входове:
    написан от човек в config/step_inputs.json, или изведен от скенера.
    """
    rec = attest(step, prev_step)
    lvl = rec["level"]
    if lvl >= IRREVERSIBLE_MIN:
        return True, f"{rec['level_name']} — {rec['why']['age']}"
    weak = [k for k, v in rec["vector"].items() if v == lvl]
    why = "; ".join(rec["why"][k] for k in weak)
    src = (f" (наследено от {rec['inherited_from']})"
           if rec["inherited"] < rec["own"] and rec["inherited_from"] else "")
    if not why:
        # НАСЛЕДЕНОТО НИВО СИ НЯМА ИЗМЕРЕНИЕ. Нито едно от петте не е равно на lvl,
        # защото lvl не е дошло от вектора на ТАЗИ стъпка, а от печата на неин вход.
        # Дотук това даваше „слабо звено:" и празно след двоеточието — отказ без
        # причина, точно в случая, който отказът трябва да обясни най-добре.
        why = (f"нивото не е на тази стъпка: собственото ѝ е "
               f"{LEVEL_NAMES.get(rec['own'], rec['own'])}, а входът "
               f"{rec['inherited_from']} носи "
               f"{LEVEL_NAMES.get(rec['inherited'], rec['inherited'])} от този цикъл"
               if rec.get("inherited_from") else
               f"нивото не съвпада с нито едно измерение: {rec['vector']}")
    return False, f"{rec['level_name']}{src} — слабо звено: {why}"


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        print(json.dumps(verify_chain(), ensure_ascii=False, indent=2))
    else:
        s = next((a for a in sys.argv[1:] if not a.startswith("--")), "global_indicators")
        print(json.dumps(attest(s), ensure_ascii=False, indent=2))
        print("\nможе ли необратимо:", may_act(s))
