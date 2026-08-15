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
    try:
        h = json.loads((BASE / "memory" / "goal_score_history.json").read_text(encoding="utf-8"))
        last = h[-1] if isinstance(h, list) and h else h
        fp["composite"] = round(float((last or {}).get("composite", 0)), 6)
    except Exception:
        fp["composite"] = None
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
            if d.get("action") != "връщане":
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
        import goal_score_calculator as g
        g.compute_goal_score()

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

    Връща {'action': 'напред'|'връщане', ...}. Изпълнява най-много едно връщане."""
    rep = {"ts": _now(), "action": "напред", "replayed": None}
    plays = _replayable()
    menu = "\n".join(f"- {k}: {v[0]} (~{v[2]} мин)" for k, v in plays.items())

    try:
        from core import brain
    except Exception as e:
        rep["error"] = f"{type(e).__name__}: {e}"
        return rep

    d = brain.think(
        role="стопанин на цикъла, по средата на пътя",
        question=(
            "Сутринта ти написа план, преди да си видял каквото и да е. Сега си "
            "минал сетивата, оценяването и дедукцията. Въпросът е прост и е твой: "
            "тази картина обезсмисля ли нещо, което вече е направено?\n\n"
            "Ако да — можеш да върнеш ЕДНА стъпка за преизчисление, ЕДИН път за "
            "цикъл. Ето какво е преизчислимо и колко струва:\n" + menu + "\n\n"
            "Цената е реална: тези минути се вадят от нощта и забавят всичко "
            "надолу. Връщане, което не променя извод, е загубено време. Ако "
            "нищо не е сгрешено — кажи 'напред' без свян; това също е решение.\n"
            "Ако ти трябва нещо, което НЕ е в списъка (напр. ново обхождане на "
            "мрежата), кажи го в 'wants' — няма да се изпълни сега, но ще стигне "
            "до човека."),
        evidence=_state(),
        schema={
            "action": "напред или връщане",
            "step": "ако връщане: кое точно от списъка (иначе празно)",
            "why": "какво в днешната картина обезсмисля свършеното",
            "expect": "какво очакваш да се промени след преизчислението",
            "wants": "какво би поискал, ако нямаше ограничения (или празно)",
        },
        kind="reconsider")

    if not d:
        rep["why"] = "мозъкът мълчи — цикълът продължава напред"
        return rep

    rep.update({k: v for k, v in d.items() if not k.startswith("_")})
    rep["by"] = d.get("_model")

    want_back = str(d.get("action", "")).strip().lower().startswith("връщ")
    step = str(d.get("step", "")).strip()

    # правото спи, ако последните три връщания не са променили нищо
    streak = _empty_streak()
    if want_back and streak >= EMPTY_STREAK_LIMIT:
        rep["action"] = "напред"
        rep["suspended"] = (f"{streak} празни връщания подред — правото на връщане "
                            f"спи този цикъл; върни се пак, когато връщане промени извод")
        _note("RECONSIDER: правото спи", rep["suspended"])
        return rep
    if not want_back:
        rep["action"] = "напред"
        _note("RECONSIDER: напред", str(d.get("why", ""))[:300])
        return rep

    if step not in plays:
        rep["action"] = "напред"
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
    rep.update({"action": "връщане", "replayed": step, "ok": ok, "error": err,
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

    try:
        brain.remember("reconsider",
                       f"върнах {step}: {str(d.get('why',''))[:200]}",
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
