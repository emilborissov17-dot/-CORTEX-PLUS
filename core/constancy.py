#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/constancy.py — ПОСТОЯНСТВОТО КАТО ИЗМЕРВАНЕ, НЕ КАТО МЪЛЧАНИЕ (15 авг 2026)

Емил, 15 август, поправяйки доктрина, не бъг:

  „АКО НЕ СЕ ПРОМЕНЯ ДАДЕНА СТОЙНОСТ ПО ПРИНЦИП — ТОВА НЕ ТРЯБВА ДА Е ЛИПСА НА
   УСЕЩАНЕ, А 'РЕГИСТРИРАНЕ НА КОНСТАНТА', КОЕТО САМО ПО СЕБЕ СИ Е УСЕЩАНЕ...
   НАЛИЧИЕТО НА ПОСТОЯННИ ПОКАЗАТЕЛИ ЗА КИСЛОРОД, ВЪГЛЕРОД И АЗОТ В АТМОСФЕРАТА —
   ЛОШО ЛИ Е? ИЛИ ГИ ИСКАМЕ КОНСТАНТНИ, ЗА ДА ПРОДЪЛЖИ ЖИВОТЪТ НА ЗЕМЯТА?...
   ОТДЕЛНИТЕ ИНДИКАТОРИ ТРЯБВА ДА СЕ РАЗГЛЕЖДАТ И В КОНТЕКСТА НА ОСТАНАЛИТЕ."

Досега цялата система гонеше ПРОМЯНАТА: trend_tracker мери посока, пулсът сее
семена само от движещи се серии, дедукцията се задейства от влошаване. Плоската
серия минаваше за „мъртъв сензор" или за нищо. Но 20.95% кислород в атмосферата
не е нищо — това е условието за живот, и точно неговата НЕПРОМЕННОСТ е добрата
новина. Тревогата там е обърната: движението е алармата.

Този модул прави две неща, които системата не можеше:

  1. КОНСТАНТАТА СЕ РЕГИСТРИРА. За всяка серия се смятат механичните факти
     (брой точки, различни стойности, разсейване, откога не е мръднала). После
     МОЗЪКЪТ казва в какъв режим ОЧАКВА да е този показател и дали видяното е
     здраве, тревога или подозрение. Аз не му давам списък с режими — той ги
     кръщава (закон, т.2).

  2. ПОКАЗАТЕЛИТЕ СЕ ЧЕТАТ ЗАЕДНО. Втори пас дава на мозъка ЦЯЛАТА таблица
     наведнъж и иска връзки между показатели — всяка подпряна на поне два
     назовани индикатора, иначе е приказка.

Изход: memory/constancy_latest.json, memory/constellation_latest.json
        (и двата се четат от отчета на цикъла).

  venv\\Scripts\\python.exe -m core.constancy
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
HIST = BASE / "memory" / "axis_history.json"
COMPOSED = BASE / "memory" / "composed_indicators.json"
OUT = BASE / "memory" / "constancy_latest.json"
OUT_JOINT = BASE / "memory" / "constellation_latest.json"

MIN_POINTS = 4          # под това няма какво да се твърди за режим
NEAR_ZERO_CV = 0.002    # 0.2% разсейване — практически константа


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _facts(values: list, dates: list) -> dict:
    """Механичните факти за серия. Без интерпретация — тя е на мозъка."""
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    if len(vals) < MIN_POINTS:
        return {}
    distinct = len(set(vals))
    mean = statistics.fmean(vals)
    stdev = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    cv = (stdev / abs(mean)) if mean else (0.0 if stdev == 0 else float("inf"))
    # откога не е мръднала: колко последователни точки в края са еднакви
    frozen = 1
    for a, b in zip(reversed(vals), reversed(vals[:-1])):
        if a == b:
            frozen += 1
        else:
            break
    span_days = None
    try:
        d0 = datetime.fromisoformat(str(dates[0])[:10])
        d1 = datetime.fromisoformat(str(dates[-1])[:10])
        span_days = (d1 - d0).days
    except Exception:
        pass
    return {
        "n": len(vals), "distinct": distinct,
        "first": vals[0], "last": vals[-1],
        "min": min(vals), "max": max(vals),
        "mean": round(mean, 6), "cv": round(cv, 6),
        "frozen_tail_points": frozen if distinct > 1 else len(vals),
        "span_days": span_days,
        "observed": ("НЕПОДВИЖНА" if distinct == 1 else
                     "ПОЧТИ НЕПОДВИЖНА" if cv < NEAR_ZERO_CV else "ПОДВИЖНА"),
    }


def _series_from_history() -> dict:
    """{(ос, метрика): (стойности, дати)} от реалната история на осите."""
    try:
        hist = json.loads(HIST.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for axis, entries in hist.items():
        if not isinstance(entries, list):
            continue
        buckets: dict = {}
        for e in entries[-40:]:
            for name, v in (e.get("metrics") or {}).items():
                if isinstance(v, (int, float)):
                    buckets.setdefault(name, ([], []))
                    buckets[name][0].append(v)
                    buckets[name][1].append(e.get("date"))
        for name, (vals, dates) in buckets.items():
            out[(axis, name)] = (vals, dates)
    return out


def _units() -> dict:
    """Мерната единица и източникът на всяка ос — контекст за мозъка."""
    try:
        comp = json.loads(COMPOSED.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for axis, doc in comp.items():
        a = ((doc.get("composed") or {}).get("anchor") or {})
        out[axis] = {"unit": a.get("unit"), "org": a.get("org"), "value": a.get("value")}
    return out


# ── 1. ВСЯКА СЕРИЯ ПООТДЕЛНО: очакван режим и присъда ────────────────────────

def judge_series(limit: int = 24) -> dict:
    series = _series_from_history()
    units = _units()
    rows = []
    for (axis, metric), (vals, dates) in series.items():
        f = _facts(vals, dates)
        if f:
            rows.append({"axis": axis, "metric": metric, "unit":
                         (units.get(axis) or {}).get("unit"), **f})
    # най-напред неподвижните — точно те бяха невидими досега
    rows.sort(key=lambda r: (r["observed"] != "НЕПОДВИЖНА", r["axis"]))
    rows = rows[:limit]

    try:
        from core import brain
    except Exception:
        brain = None

    for r in rows:
        if not brain:
            r["verdict"] = None
            continue
        d = brain.think(
            role="тълкувател на показател",
            question=(
                f"Показателят '{r['metric']}' на ос {r['axis']} "
                f"({r.get('unit') or 'без обявена единица'}) се държи така, както е "
                f"описано в материала. Въпросът НЕ е 'мърда ли' — а В КАКЪВ РЕЖИМ "
                f"ТРЯБВА да бъде този показател по своята природа, и здраво ли е "
                f"видяното спрямо това.\n\n"
                f"Помни: неподвижността не е липса на сигнал. Има величини, чиято "
                f"постоянност Е добрата новина (делът на кислорода в атмосферата), "
                f"и други, чиято неподвижност е симптом (замръзнал сензор или "
                f"застой). Ти решаваш кое от двете е това — и как се казва режимът."),
            evidence=json.dumps(r, ensure_ascii=False, indent=2),
            schema={
                "expected_regime": "как ТИ наричаш режима, в който този показател "
                                   "трябва да бъде по своята природа",
                "why_expected": "на какво основание очакваш точно този режим",
                "healthy": "true/false — здраво ли е видяното спрямо очакваното",
                "alarm": "true/false — има ли повод за тревога",
                "reading": "какво ТОЧНО ти казва тази серия, с едно-две изречения",
            },
            kind="constancy", fast=True)
        r["verdict"] = {k: v for k, v in (d or {}).items() if not k.startswith("_")} or None
        if d:
            r["by"] = d.get("_model")

    doc = {"ts": _now(), "rows": rows,
           "counts": {"total": len(rows),
                      "still": sum(1 for r in rows if r["observed"] != "ПОДВИЖНА"),
                      "alarm": sum(1 for r in rows
                                   if str((r.get("verdict") or {}).get("alarm")).lower() == "true")}}
    try:
        OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


# ── 2. ВСИЧКИ ЗАЕДНО: съзвездието, не отделната звезда ───────────────────────

def judge_together(rows: list | None = None) -> dict | None:
    """Показателите в контекста на останалите. Всяка връзка трябва да назове поне
    два индикатора — иначе е приказка, не наблюдение."""
    if rows is None:
        try:
            rows = json.loads(OUT.read_text(encoding="utf-8")).get("rows", [])
        except Exception:
            return None
    if not rows:
        return None
    try:
        from core import brain
    except Exception:
        return None

    table = "\n".join(
        f"{r['axis']}.{r['metric']} [{r.get('unit') or '?'}]: {r['observed']}, "
        f"последно={r['last']}, размах={r['min']}..{r['max']}, cv={r['cv']}, n={r['n']}"
        + (f" — ти го чете като: {(r.get('verdict') or {}).get('reading','')[:120]}"
           if r.get("verdict") else "")
        for r in rows)

    d = brain.think(
        role="четец на цялата картина",
        question=("Досега си съдил всеки показател поотделно. Сега ги виж ЗАЕДНО. "
                  "Какво казва СЪЧЕТАНИЕТО им, което нито един поотделно не казва? "
                  "Търси: показатели, които би трябвало да се движат заедно, а не се "
                  "движат; неподвижност на едно място, която придобива смисъл заради "
                  "движение на друго; и обратното. Всяка връзка трябва да назове поне "
                  "ДВА конкретни показателя от таблицата — иначе не я казвай."),
        evidence=table,
        schema={
            "relations": "списък от връзки; всяка назовава поне два показателя "
                         "и казва какво следва от съчетанието им",
            "most_telling": "коя връзка е най-показателна и защо",
            "what_would_change_my_mind": "какво наблюдение би оборило този прочит",
        },
        kind="constellation")
    if not d:
        return None
    doc = {"ts": _now(), "n_rows": len(rows),
           **{k: v for k, v in d.items() if not k.startswith("_")},
           "by": d.get("_model")}
    try:
        OUT_JOINT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return doc


def run(limit: int = 24) -> dict:
    doc = judge_series(limit)
    joint = judge_together(doc.get("rows"))
    return {"constancy": doc, "constellation": joint}


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    res = run(n)
    c = res["constancy"]["counts"]
    print(f"показатели: {c['total']} | неподвижни: {c['still']} | тревожни: {c['alarm']}")
    for r in res["constancy"]["rows"][:8]:
        v = r.get("verdict") or {}
        print(f"- {r['axis']}.{r['metric']}: {r['observed']} -> "
              f"{v.get('expected_regime','?')} | здраво={v.get('healthy')} "
              f"тревога={v.get('alarm')}")
        if v.get("reading"):
            print(f"    {str(v['reading'])[:160]}")
    j = res.get("constellation") or {}
    if j:
        print("\nЗАЕДНО:", str(j.get("most_telling"))[:300])
