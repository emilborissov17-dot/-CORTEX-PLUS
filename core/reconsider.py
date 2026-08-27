#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/reconsider.py — ТОЧКАТА НА ВРЪЩАНЕ (15 август 2026)

Роден от консенсус с Kimi, който формулира диагнозата по-остро от мен:

  „Линеен конвейер с добавен мозък. Планът се ражда на стъпка 2 от слепота и
   умира на стъпка 51, без да е променян от нищо видяно по средата.
   Саморазвитието изисква планът да е ЖЕРТВА на данните, не само техен
   предшественик."
  „Фазовата стена между сетивата (9–15), мисленето (28–34) и действието (41–43)...
   Редът кристализира фази, а растежът иска тяхното разтваряне."

И той посочи къде точно да е връщането:

  „След cognitive_orchestrator (34) и преди growth_planner (36). Там вече има
   цялостна картина (сетива + анализ + приоритети), но още нищо необратимо
   (публикуване, патчове) не е станало."

РИСКЪТ, който сам назова, и как е овладян:

  „Система, която може да се връща, ЩЕ се връща, защото всяко ново виждане ще
   изглежда по-важно от изпълнението. Нужен е твърд лимит (макс 1 връщане на
   цикъл) и явна сметка за цената на забавянето."

Затова тук: най-много ЕДНО връщане на цикъл, мозъкът вижда цената в минути
ПРЕДИ да реши, и решението му се записва — утре се съди по това дали е било
право. Границата е на ДЕЙСТВИЕТО (един път), не на мисълта (може да поиска
каквото прецени).

ЧЕСТНО ЗА ОБХВАТА: връщат се само стъпки, които са ИЗЧИСЛЕНИЕ върху вече
събрани данни (преоценка, дедукция, нива, композит). Стъпките, които ходят по
мрежата, НЕ се повтарят — не защото мозъкът не бива да ги иска, а защото един
час web_intelligence в 04:00 изяжда целия цикъл. Ако поиска такава, искането се
записва като предложение за човека, вместо да се изпълни мълчаливо.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "memory" / "reconsider_latest.json"
NIGHT = BASE / "memory" / "night_events.jsonl"

MAX_RETURNS_PER_CYCLE = 1        # твърдият лимит, поискан от Kimi
HISTORY = BASE / "memory" / "reconsider_history.jsonl"

# ── THE ACTION ENUM (23 Aug 2026) ───────────────────────────────────────────
# The model emitted "напред" or "връщане" and three places compared against
# those literals: here twice, and fast_cycle_runner.py at the reconsider step.
# Same rule as the stance enum in core/brain.py — new writes are English, reads
# accept both, because memory/reconsider_history.jsonl is the file _empty_streak
# counts from and rewriting it would destroy the streak it exists to measure.
ACTION_FORWARD, ACTION_ROLLBACK = "forward", "rollback"

ACTION_LEGACY = {"напред": ACTION_FORWARD, "връщане": ACTION_ROLLBACK,
                 "връщ": ACTION_ROLLBACK}


def normalise_action(value) -> str:
    """One reader for both vocabularies. Unknown returns "" — and an
    unrecognised action must never be read as a rollback."""
    v = str(value or "").strip().lower()
    if not v:
        return ""
    for name in (ACTION_FORWARD, ACTION_ROLLBACK):
        if v.startswith(name):
            return name
    for old, new in ACTION_LEGACY.items():
        if v.startswith(old):
            return new
    return ""
EMPTY_STREAK_LIMIT = 3           # три празни връщания подред -> правото спи


def _fingerprint() -> dict:
    """Отпечатък на изводите ПРЕДИ и СЛЕД връщането.

    Kimi, 15 авг: „най-коварната злоупотреба не е инфинитна петля, а САМОЦЕНЗУРА
    под прикритие на прецизност — системата открива 'критична несигурност' точно
    преди необратима стъпка, за да избегне отчетност... ако научи, че връщането =
    защита от експозиция, ще го синхронизира с неудобните стъпки."

    Затова връщането се МЕРИ, не се приема на доверие: ако след него нито един
    извод не се е променил, то е ПРАЗНО. Три празни подред и правото на връщане
    заспива за следващия цикъл. Мисълта остава свободна; забавянето без резултат
    губи правото си. Точно както автономията се печели срещу измерена точност."""
    fp = {}
    try:
        d = json.loads((BASE / "memory" / "deductions_latest.json").read_text(encoding="utf-8"))
        items = d.get("conclusions", d) if isinstance(d, dict) else d
        fp["deductions"] = len(items) if hasattr(items, "__len__") else 0
    except Exception:
        fp["deductions"] = None
    # ── МЪРТВОТО ПОЛЕ (15 август 2026) ──────────────────────────────────────
    # Тук се четеше memory/goal_score_history.json и се търсеше ключ "composite".
    # Проверено на живите данни: НИТО ЕДИН от 37-те записа няма такъв ключ — файлът
    # се пълни от feedback_loop с {"timestamp","scores"} и от goal_planner с
    # {"timestamp","score","source"}. Значи .get("composite", 0) връщаше 0.0 ВИНАГИ,
    # без да гръмне, и отпечатъкът беше СЛЯП за движението на композита: връщането
    # можеше да промени числото и пак да се отчете за „празно".
    # Композитът се чете от там, където цикълът наистина го пише — и, по договора
    # от 15 август, ЗАЕДНО с покритието си, не сам.
    try:
        g = json.loads((BASE / "snapshots" / "master" / "goal_score_latest.json")
                       .read_text(encoding="utf-8"))
        fp["composite"] = round(float(g.get("composite_score", 0.0)), 6)
        fp["coverage_of_goal"] = g.get("coverage_of_goal", g.get("coverage"))
        fp["coverage_of_measurable"] = g.get("coverage_of_measurable")
        # ОТ КОГА Е ЧИСЛОТО. Отпечатъкът чете ЗАПИСАНОТО състояние, не пресмята
        # наново — това е нарочно, защото сравняваме ангажирани числа, не мисли.
        # Но „записано" и „днешно" не са едно и също: ако снимката е от снощи,
        # композитът в отпечатъка е снощен и трябва да се вижда, че е такъв.
        fp["composite_ts"] = str(g.get("timestamp"))[:19] or None
    except Exception:
        fp["composite"] = None
        fp["coverage_of_goal"] = None
        fp["coverage_of_measurable"] = None
        fp["composite_ts"] = None
    try:
        c = json.loads((BASE / "memory" / "constancy_latest.json").read_text(encoding="utf-8"))
        fp["alarms"] = (c.get("counts") or {}).get("alarm")
    except Exception:
        fp["alarms"] = None
    return fp


def _empty_streak() -> int:
    """Колко празни връщания подред — прочетено от собствената история."""
    n = 0
    try:
        for line in reversed(HISTORY.read_text(encoding="utf-8").splitlines()):
            d = json.loads(line)
            if normalise_action(d.get("action")) != ACTION_ROLLBACK:
                continue
            if d.get("changed_anything") is False:
                n += 1
            else:
                break
    except Exception:
        pass
    return n


# Какво може да бъде преизчислено на място: само работа върху ВЕЧЕ събрани данни.
# (име в цикъла) -> (човешко описание, извикване, груба цена в минути)
def _replayable() -> dict:
    def _scoring():
        from cortex_scoring_engine import score_all_snapshots
        score_all_snapshots()

    def _levels():
        from memory.auto_level import run as _r
        _r()

    def _goal():
        # ПРЕДИ: `g.compute_goal_score()` — сметни и хвърли. Всички съседни
        # действия тук записват на диск; това не записваше, а отпечатъкът чете
        # точно диска. Значи „преизчисли композита" беше единственото преправяне,
        # което по построение не можеше да промени нищо измеримо. (15 авг 2026)
        import goal_score_calculator as g
        g.persist(g.compute_goal_score())

    def _deduction():
        from core.deduction import run as _r
        _r()

    def _constancy():
        from core.constancy import run as _r
        _r()

    def _composers():
        from experiments.composers.composer import compose_all as _r
        _r()

    return {
        "scoring_engine": ("преоценка на всички снимки", _scoring, 3),
        "auto_levels": ("преизчисляване на нивата", _levels, 1),
        "goal_score_calculator": ("преизчисляване на композита", _goal, 1),
        "deduction": ("повторна дедукция R1-R7", _deduction, 2),
        "constancy_and_constellation": ("повторен прочит на показателите", _constancy, 6),
        "composers": ("повторно композиране на портфолиата", _composers, 4),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state() -> str:
    """Каквото системата вече знае В ТОЗИ момент от цикъла — суровo."""
    bits = []
    for rel, cap in (("memory/brain_cycle_plan.json", 900),
                     ("memory/deductions_latest.json", 1500),
                     ("memory/constancy_latest.json", 900),
                     ("memory/goal_score_history.json", 500),
                     ("memory/orchestration_latest.json", 700)):
        try:
            bits.append(f"--- {rel} ---\n" + (BASE / rel).read_text(encoding="utf-8")[-cap:])
        except Exception:
            continue
    return "\n".join(bits)


def _note(subject: str, detail: str) -> None:
    try:
        NIGHT.parent.mkdir(parents=True, exist_ok=True)
        with open(NIGHT, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), "subject": subject, "detail": detail},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass


def run() -> dict:
    """Мозъкът гледа какво е излязло и решава: продължавам ли, или се връщам.

    Връща {'action': 'forward'|'rollback', ...}. Изпълнява най-много едно връщане."""
    rep = {"ts": _now(), "action": ACTION_FORWARD, "replayed": None}
    plays = _replayable()
    menu = "\n".join(f"- {k}: {v[0]} (~{v[2]} min)" for k, v in plays.items())

    try:
        from core import brain
    except Exception as e:
        rep["error"] = f"{type(e).__name__}: {e}"
        return rep

    d = brain.think(
        role="owner of the cycle, halfway through",
        question=(
            "This morning you wrote a plan, before you had seen anything. You "
            "have now been through the senses, the scoring and the deduction. The "
            "question is simple and it is yours: does this picture make anything "
            "already done pointless?\n\n"
            "If so — you may roll back ONE step for recomputation, ONCE per "
            "cycle. Here is what can be recomputed and what it costs:\n"
            + menu + "\n\n"
            "The cost is real: those minutes come out of the night and delay "
            "everything downstream. A rollback that changes no conclusion is "
            "wasted time. If nothing is wrong — say 'forward' without "
            "embarrassment; that is a decision too.\n"
            "If you need something that is NOT on the list (a fresh web sweep, "
            "say), put it in 'wants' — it will not happen now, but it will reach "
            "the human."),
        evidence=_state(),
        schema={
            "action": "forward or rollback",
            "step": "if rollback: exactly which one from the list (otherwise empty)",
            "why": "what in today's picture makes the finished work pointless",
            "expect": "what you expect to change after the recomputation",
            "wants": "what you would ask for if there were no limits (or empty)",
        },
        kind="reconsider")

    if not d:
        rep["why"] = "мозъкът мълчи — цикълът продължава напред"
        return rep

    rep.update({k: v for k, v in d.items() if not k.startswith("_")})
    rep["by"] = d.get("_model")

    want_back = normalise_action(d.get("action")) == ACTION_ROLLBACK
    step = str(d.get("step", "")).strip()

    # правото спи, ако последните три връщания не са променили нищо
    streak = _empty_streak()
    if want_back and streak >= EMPTY_STREAK_LIMIT:
        rep["action"] = ACTION_FORWARD
        rep["suspended"] = (f"{streak} празни връщания подред — правото на връщане "
                            f"спи този цикъл; върни се пак, когато връщане промени извод")
        _note("RECONSIDER: правото спи", rep["suspended"])
        return rep
    if not want_back:
        rep["action"] = ACTION_FORWARD
        _note("RECONSIDER: напред", str(d.get("why", ""))[:300])
        return rep

    if step not in plays:
        rep["action"] = ACTION_FORWARD
        rep["refused"] = (f"поиска '{step}', което не е преизчислимо на място; "
                          f"записано като предложение за човека")
        _note("RECONSIDER: поиска непреизчислима стъпка",
              f"{step} | защо: {str(d.get('why',''))[:200]} | иска: {str(d.get('wants',''))[:200]}")
        return rep

    label, fn, mins = plays[step]
    before = _fingerprint()
    t0 = time.time()
    try:
        fn()
        ok, err = True, None
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
    after = _fingerprint()
    changed = any(before.get(k) != after.get(k) for k in before)
    rep.update({"action": ACTION_ROLLBACK, "replayed": step, "ok": ok, "error": err,
                "seconds": round(time.time() - t0, 1),
                "before": before, "after": after, "changed_anything": changed})
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rep, ensure_ascii=False) + "\n")
    except Exception:
        pass
    _note("RECONSIDER: върна се" + ("" if changed else " — ПРАЗНО (нищо не се промени)"),
          f"{step} ({label}) | защо: {str(d.get('why',''))[:200]} | "
          f"очаква: {str(d.get('expect',''))[:150]} | успех={ok} {err or ''} | "
          f"промени: {before} -> {after}")

    # ENGLISH, because this row is JOURNALED. brain.remember() writes into
    # memory/brain_journal.jsonl, which core/language_gate.py scores as model
    # output — so a Bulgarian wrapper here reads as the model answering in the
    # wrong language and fails the purity floor deterministically, every time
    # this path runs. Only the wrapper was ever Bulgarian: `why` comes from the
    # decision and is already English, which is why these rows scored
    # CYRILLIC_0.03 — just over the 3% line, on one word.
    #
    # _note() above is a DIFFERENT sink (the night log, read by a human) and is
    # deliberately left in Bulgarian.
    try:
        brain.remember("reconsider",
                       f"rolled back {step}: {str(d.get('why',''))[:200]}",
                       {"expect": d.get("expect"), "ok": ok})
    except Exception:
        pass

    try:
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return rep


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
