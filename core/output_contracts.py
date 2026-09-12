#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/output_contracts.py — РАЗУМЕН ЛИ Е ИЗХОДЪТ. (12 Sep 2026)

ПОСТАНОВКА
  Какво се иска      : всеки файл, който системата пише в memory/, да бъде проверен
                       срещу предварително обявено определение за „здрав изход".
  Какво се вижда     : самият файл, и — за числовите твърдения — записът на серията,
                       върху която са направени. Нищо от бъдещето.
  Кой решава         : код. Никакъв модел, никаква мрежа, никакъв подпроцес.
  Кой проверява      : аритметика — сравнение, домейн, сумиране, свежест.
  Известни слабости  : (1) договорът лови само това, което е обявил — правдоподобно
                       грешно число минава; (2) праговете за свежест са избрани на ръка
                       и са съждение, не измерване; (3) празен или липсващ файл се
                       отчита като MISSING, а не като „минава", защото „нямам данни"
                       никога не бива да чете като „всичко е добре".

ЗАЩО СЪЩЕСТВУВА. На 12 септември 2026 два дефекта минаха през всичко останало:

  * memory/canon_invariants.json държеше инвариант, чийто урок беше буквата "c"
    (тестова фикстура с cycle_id "c1"), и той влизаше в подсказката на мозъка при
    ВСЯКА стъпка. Всеки ред от кода беше покрит. Всеки тест беше зелен.
  * memory/consolidation_queue.json предсказа "quakes.quake_m45_count надолу до
    -20.84, интервал [-35.67, -6.01]". Брой земетресения. Аритметиката — точна,
    клоните — взети, резултатът — невъзможен.

Покритие, vulture, import-linter и правилата по образец не хващат нито един от
двата: и в двата случая кодът се изпълнява и е формално прав. Липсваше проверка на
САМИЯ РЕЗУЛТАТ. Това е тя.

РАЗЛИКАТА ОТ ТЕСТ. Тестът съди код върху измислен вход. Договорът съди изхода, който
машината наистина е написала тази нощ, върху данните, които наистина е видяла. Затова
се пуска в цикъла, а не в пакета тестове — и пада шумно, в нощта, в която числото е
безсмислено, не когато някой се сети да погледне.

Usage:
  venv\\Scripts\\python.exe -m core.output_contracts            # проверява всичко
  venv\\Scripts\\python.exe -m core.output_contracts --json
  venv\\Scripts\\python.exe -m core.output_contracts --selftest
Пише memory/output_contracts_latest.json. Не поправя нищо — договорът съди, не лекува.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEM = REPO / "memory"
LATEST = MEM / "output_contracts_latest.json"

FRESH_HOURS = 48          # изход на нощен процес, непипан два дни, е заспал
MIN_LESSON_CHARS = 20     # същият под като в core/canon.py — законът е един
MIN_LESSON_WORDS = 3
MIN_RECORD = 10           # под толкова точки серията не дава основание за домейн
RANGE_SLACK = 3.0         # предсказание отвъд наблюдаваното +/- 3 сигми е твърдение
                          # за невиждана територия и иска отделно основание


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _age_hours(p: Path) -> float | None:
    if not p.is_file():
        return None
    import time
    return round((time.time() - p.stat().st_mtime) / 3600.0, 1)


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _rows(p: Path) -> list:
    out = []
    try:
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except OSError:
        pass
    return out


def _num(x) -> bool:
    """Число, но НЕ булево: isinstance(True, int) е True в Python, и флаг,
    влязъл в аритметика като 1.0, е точно безсмислицата с формата на истина."""
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ── договорите ───────────────────────────────────────────────────────────────
# Всеки връща списък от нарушения. Празен списък = минава. Всяко нарушение носи
# ИМЕТО на договора и стойността, която го е нарушила — доклад без стойността
# праща човек да търси, вместо да поправя.

def canon_invariants(path: Path | None = None) -> list:
    """Законът се чете на всяка стъпка. Буква не може да е закон."""
    p = path or (MEM / "canon_invariants.json")
    doc = _load(p)
    if doc is None:
        return [{"contract": "canon_invariants", "why": "MISSING or unreadable", "path": str(p.name)}]
    bad = []
    for i, inv in enumerate(doc.get("invariants") or []):
        lesson = (inv.get("lesson") if isinstance(inv, dict) else inv) or ""
        lesson = str(lesson).strip()
        if len(lesson) < MIN_LESSON_CHARS or len(lesson.split()) < MIN_LESSON_WORDS:
            bad.append({"contract": "canon_invariants", "index": i,
                        "why": f"lesson too short to be law ({len(lesson)} chars, "
                               f"{len(lesson.split())} words)", "value": lesson[:60]})
        ev = str((inv.get("evidence") if isinstance(inv, dict) else "") or "")
        if re.search(r"\(c\d+\.\.c\d+\)", ev):
            bad.append({"contract": "canon_invariants", "index": i,
                        "why": "evidence names test-fixture cycle ids", "value": ev[:80]})
    return bad


def consolidation_queue(queue: Path | None = None, tier: Path | None = None) -> list:
    """Предсказание, което нарушава домейна на своята серия, е грешен МОДЕЛ, не
    грешно число — затова се съди тук, а не се подрязва там."""
    q = queue or (MEM / "consolidation_queue.json")
    doc = _load(q)
    if doc is None:
        return [{"contract": "consolidation_queue", "why": "MISSING or unreadable", "path": q.name}]
    obs = _observed(tier or (MEM / "daily_tier.jsonl"))
    bad, unjudged = [], []
    for h in doc.get("hypotheses") or []:
        name, lo, hi, pred = h.get("metric"), h.get("lo"), h.get("hi"), h.get("predicted")
        tag = {"contract": "consolidation_queue", "metric": name}
        if not all(_num(v) for v in (lo, hi, pred)):
            bad.append({**tag, "why": "lo/hi/predicted not all numeric"}); continue
        if not (lo <= pred <= hi):
            bad.append({**tag, "why": f"predicted {pred} outside its own interval [{lo}, {hi}]"})
        vals = obs.get(name) or obs.get(str(name).split(".")[-1])
        # „НЯМАМ ОСНОВАНИЕ" НЕ Е „НАРУШЕНИЕ". Първата версия на този договор
        # обяви co2_annual_increase за извън записа си, защото в дневния слой има
        # 2 точки, и двете 1.9: сигма 0, значи всяко число е „извън". А хипотезата
        # е напасната върху архива, не върху този слой. Договор, който вика
        # напразно, бива изключен от първия, който го види — затова прагът е тук,
        # а пропуснатите се БРОЯТ, за да се вижда колко не са съдени.
        if not vals or len(vals) < MIN_RECORD or _sigma(vals) <= 0:
            unjudged.append({"metric": name, "points": len(vals or []),
                             "why": "no record long enough in the daily tier to judge against"})
            continue
        if all(v >= 0 and float(v).is_integer() for v in vals) and lo < 0:
            bad.append({**tag, "why": f"a count cannot go below zero, yet lo={lo}",
                        "observed_min": min(vals), "points": len(vals)})
        mn, mx = min(vals), max(vals)
        sigma = _sigma(vals)
        if pred < mn - RANGE_SLACK * sigma or pred > mx + RANGE_SLACK * sigma:
            bad.append({**tag, "why": f"predicted {pred} is outside the observed record "
                                      f"[{mn}, {mx}] by more than {RANGE_SLACK} sigma "
                                      f"({sigma:.3f}, n={len(vals)})"})
    if unjudged:
        bad.append({"contract": "consolidation_queue", "why": "NOT A VIOLATION — recorded so that "
                    "unjudged hypotheses cannot pass for judged ones", "unjudged": unjudged,
                    "severity": "note"})
    return bad


def consolidation_bookkeeping(path: Path | None = None) -> list:
    """Отхвърлените плюс издадените ТРЯБВА да са точно разгледаните.

    Аритметично тъждество, не съждение: серия, която е нито издадена, нито
    отхвърлена по някаква причина, е серия, изпаднала между два филтъра — и
    точно това е начинът, по който един ден изчезва половината вход, без
    никой да падне.
    """
    p = path or (MEM / "consolidation_latest.json")
    doc = _load(p)
    if doc is None:
        return [{"contract": "consolidation_bookkeeping", "why": "MISSING or unreadable", "path": p.name}]
    considered = doc.get("series_considered")
    rej = sum(v for v in (doc.get("rejected") or {}).values() if _num(v))
    emitted, trunc = doc.get("emitted") or 0, doc.get("truncated") or 0
    if not _num(considered):
        return [{"contract": "consolidation_bookkeeping", "why": "series_considered missing"}]
    if rej + emitted + trunc != considered:
        return [{"contract": "consolidation_bookkeeping",
                 "why": f"rejected {rej} + emitted {emitted} + truncated {trunc} "
                        f"= {rej + emitted + trunc}, but {considered} series were considered",
                 "lost": considered - (rej + emitted + trunc)}]
    return []


def daily_tier(path: Path | None = None) -> list:
    """Движещият се свят трябва да ПРОДЪЛЖАВА да се движи и да е без дубликати."""
    p = path or (MEM / "daily_tier.jsonl")
    rows = _rows(p)
    if not rows:
        return [{"contract": "daily_tier", "why": "MISSING or empty", "path": p.name}]
    bad, seen = [], set()
    for r in rows:
        if not (r.get("date") and r.get("indicator") and _num(r.get("value"))):
            bad.append({"contract": "daily_tier", "why": "row missing date/indicator/numeric value",
                        "value": str(r)[:90]}); continue
        key = (r["indicator"], r["date"])
        if key in seen:
            bad.append({"contract": "daily_tier", "why": "duplicate (indicator, date)",
                        "value": f"{key[0]} {key[1]}"})
        seen.add(key)
    newest = max((r["date"] for r in rows if r.get("date")), default=None)
    age = _age_hours(p)
    if age is not None and age > FRESH_HOURS:
        bad.append({"contract": "daily_tier", "why": f"not written for {age} hours",
                    "newest_date": newest})
    return bad


def merkle_verify(path: Path | None = None) -> list:
    """Доказателството или държи, или файлът лъже, че е държало."""
    p = path or (MEM / "merkle_verify_latest.json")
    doc = _load(p)
    if doc is None:
        return [{"contract": "merkle_verify", "why": "MISSING or unreadable", "path": p.name}]
    bad = []
    if doc.get("ok") is not True:
        bad.append({"contract": "merkle_verify", "why": "ok is not true", "value": doc.get("ok")})
    if doc.get("stored_hash") != doc.get("recomputed"):
        bad.append({"contract": "merkle_verify", "why": "stored_hash != recomputed",
                    "value": f'{doc.get("stored_hash")} vs {doc.get("recomputed")}'})
    if not (_num(doc.get("signals")) and doc["signals"] > 0):
        bad.append({"contract": "merkle_verify", "why": "sealed zero signals",
                    "value": doc.get("signals")})
    return bad


def learner_state(path: Path | None = None) -> list:
    """Всяко алфа е тегло между 0 и 1 и е напаснато върху поне една точка."""
    p = path or (MEM / "learner_state.json")
    doc = _load(p)
    if doc is None:
        return [{"contract": "learner_state", "why": "MISSING or unreadable", "path": p.name}]
    bad = []
    for key, v in (doc or {}).items():
        a, n = (v or {}).get("alpha"), (v or {}).get("fitted_on")
        if not (_num(a) and 0.0 <= a <= 1.0):
            bad.append({"contract": "learner_state", "key": key, "why": "alpha outside [0, 1]", "value": a})
        if not (_num(n) and n > 0):
            bad.append({"contract": "learner_state", "key": key, "why": "fitted_on is not positive", "value": n})
    return bad


def cycle_reviews(path: Path | None = None) -> list:
    """Присъдата е от истински цикъл, а урокът е ключ, не проза и не число.

    cycle_id "c1" е подписът на фикстура. Точно този подпис стоеше в канона.
    """
    p = path or (MEM / "brain_cycle_reviews.jsonl")
    rows = _rows(p)
    if not rows:
        return [{"contract": "cycle_reviews", "why": "MISSING or empty", "path": p.name}]
    bad = []
    for r in rows:
        cid = str(r.get("cycle_id") or "")
        if not re.match(r"^\d{4}-\d\d-\d\dT", cid):
            bad.append({"contract": "cycle_reviews", "why": "cycle_id is not a timestamp "
                                                            "(test fixture in live state?)", "value": cid[:40]})
        key = r.get("lesson_key")
        if key is None:
            continue                     # преди поправката B полето не съществува
        k = str(key).strip()
        if k and (len(k.split()) > 8 or re.search(r"\d", k)):
            bad.append({"contract": "cycle_reviews", "why": "lesson_key too long or carries a number "
                                                            "(unique per night by construction)", "value": k[:60]})
    return bad


# ── помощни за домейна на серия ──────────────────────────────────────────────

def _observed(tier: Path) -> dict:
    """indicator -> наблюдаваните стойности. Ключът се държи и с, и без раздела,
    защото консолидацията пише metric понякога като 'quakes.x', понякога като 'x'."""
    out: dict = {}
    for r in _rows(tier):
        ind, v = r.get("indicator"), r.get("value")
        if ind and _num(v):
            out.setdefault(ind, []).append(float(v))
            out.setdefault(str(ind).split(".")[-1], []).append(float(v))
    return out


def _sigma(vals: list) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5


CONTRACTS = (canon_invariants, consolidation_queue, consolidation_bookkeeping,
             daily_tier, merkle_verify, learner_state, cycle_reviews)


def check_all() -> dict:
    viol, ran = [], []
    for fn in CONTRACTS:
        ran.append(fn.__name__)
        try:
            viol.extend(fn())
        except Exception as exc:        # договор, който гръмва, е нарушен договор,
            viol.append({"contract": fn.__name__,   # не мълчалив успех
                         "why": f"the contract itself raised {type(exc).__name__}: {exc}"})
    hard = [v for v in viol if v.get("severity") != "note"]
    rec = {"ts": _now(), "contracts": ran, "violations": viol, "n": len(hard),
           "notes": len(viol) - len(hard), "ok": not hard, "uses_model": False}
    try:
        LATEST.parent.mkdir(parents=True, exist_ok=True)
        LATEST.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return rec


def summary_line(rec: dict) -> str:
    if rec["ok"]:
        return f"[CONTRACTS] {len(rec['contracts'])} contracts, 0 violations"
    by = {}
    for v in rec["violations"]:
        if v.get("severity") == "note":
            continue
        by[v["contract"]] = by.get(v["contract"], 0) + 1
    worst = ", ".join(f"{k}={n}" for k, n in sorted(by.items(), key=lambda kv: -kv[1]))
    return f"[CONTRACTS] {rec['n']} VIOLATION(S) across {len(by)} contract(s): {worst}"


def _selftest() -> int:
    print("core/output_contracts --selftest")
    print(f"  memory tree : {'LIVE ' if MEM.is_dir() else 'ABSENT '}{MEM}")
    print(f"  contracts   : {len(CONTRACTS)}")
    # всеки договор трябва да ХВАНЕ нарочно счупен вход, иначе е декорация
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        (t / "canon.json").write_text('{"invariants": [{"lesson": "c", '
                                      '"evidence": "carried forward (c1..c1)"}]}', encoding="utf-8")
        n = len(canon_invariants(t / "canon.json"))
        print(f"  bites 'c' as law            : {'YES' if n >= 2 else 'NO -- decoration'} ({n} found)")
        (t / "tier.jsonl").write_text("\n".join(
            json.dumps({"date": f"2026-08-{d0:02d}", "indicator": "quakes.q", "value": 20 + d0})
            for d0 in range(1, 20)), encoding="utf-8")
        (t / "q.json").write_text(json.dumps({"hypotheses": [
            {"metric": "quakes.q", "predicted": -20.84, "lo": -35.67, "hi": -6.01}]}), encoding="utf-8")
        n = len(consolidation_queue(t / "q.json", t / "tier.jsonl"))
        print(f"  bites -20.84 earthquakes    : {'YES' if n >= 1 else 'NO -- decoration'} ({n} found)")
        (t / "c.json").write_text('{"series_considered": 109, "emitted": 5, "truncated": 0, '
                                  '"rejected": {"a": 50, "b": 4}}', encoding="utf-8")
        n = len(consolidation_bookkeeping(t / "c.json"))
        print(f"  bites lost series (109!=59) : {'YES' if n >= 1 else 'NO -- decoration'} ({n} found)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    rec = check_all()
    print(summary_line(rec))
    for v in rec["violations"][:20]:
        print("  " + json.dumps(v, ensure_ascii=False))
    if "--json" in sys.argv:
        print(json.dumps(rec, ensure_ascii=False, indent=1))
    sys.exit(0)
