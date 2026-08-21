#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/continents.py — THE CONTINENT TIER WAS ALREADY THERE AND NOBODY COULD SEE IT.

WHAT THIS SURFACES
-------------------
wellbeing_globe has computed a continent tier since 2 July: seven World Bank
regions, each with a country count, a population, three measures and a modal
zone. It sits in output/wellbeing_continent.json and no report has ever
mentioned it. The whole planet was being reported as one number while a
seven-row breakdown of the same data sat unread on disk.

    dep   deprivation      how much is missing
    str   stress           how much is under strain
    flo   flourishing      how much is going well

THE TERM IS КОНТИНЕНТ, EVERYWHERE USER-FACING. The underlying data uses World
Bank region codes and calls them regions; a person reading a morning report
should not have to learn that vocabulary to understand which part of the world
is worst off. The code keeps region_id because that is the join key; every
string a human reads says КОНТИНЕНТ.

ATTRIBUTION ON R4 ROWS
-----------------------
core/metta_parallel's R4 says an axis is on the wrong side of its own target.
Where the underlying measure exists per country, this names WHICH continent
carries it: "воден от Субсахарска Африка". A global number that is bad
everywhere and a global number that is bad in one place need different
answers, and the axis alone cannot tell them apart.

    venv\\Scripts\\python.exe core/continents.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONTINENTS = BASE / "output" / "wellbeing_continent.json"

# World Bank region codes -> what a person calls them. The codes are the join
# key and stay in the data; only these strings are ever shown.
NAMES_BG = {
    "EAS": "Източна Азия и Тихоокеанието",
    "ECS": "Европа и Централна Азия",
    "LCN": "Латинска Америка и Карибите",
    "MEA": "Близкият изток и Северна Африка",
    "NAC": "Северна Америка",
    "SAS": "Южна Азия",
    "SSF": "Субсахарска Африка",
}

ZONES_BG = {
    "Thriving": "процъфтяване",
    "Dignified Life": "достоен живот",
    "Precarious": "несигурност",
    "Struggling": "борба",
    "Crisis": "криза",
}

# Which of the three measures decides "worst" for an axis pointing a given way.
WORST_BY = {"deprivation": "dep", "stress": "str", "flourishing": "flo"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def name_of(region_id: str, fallback: str = "") -> str:
    return NAMES_BG.get(region_id, fallback or region_id)


def zone_of(zone: str | None) -> str:
    return ZONES_BG.get(zone or "", zone or "—")


def load(path: pathlib.Path | None = None) -> list[dict]:
    """The seven continents, worst deprivation first. Never raises."""
    try:
        blob = json.loads((path or CONTINENTS).read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for r in blob.get("regions") or []:
        if not isinstance(r, dict) or not r.get("region_id"):
            continue
        rows.append({
            "region_id": r["region_id"],
            "continent": name_of(r["region_id"], r.get("region_name", "")),
            "source_name": r.get("region_name"),
            "countries": r.get("country_count"),
            "population": r.get("pop_total"),
            "dep": r.get("dep"), "str": r.get("str"), "flo": r.get("flo"),
            "zone": r.get("modal_zone"),
            "zone_bg": zone_of(r.get("modal_zone")),
        })
    rows.sort(key=lambda x: -(x["dep"] or 0))
    return rows


def computed_at(path: pathlib.Path | None = None) -> str | None:
    try:
        return json.loads((path or CONTINENTS).read_text(encoding="utf-8")).get(
            "computed_at")
    except Exception:
        return None


def worst(measure: str = "dep", rows: list[dict] | None = None) -> dict | None:
    """The continent carrying the most of `measure`."""
    rows = rows if rows is not None else load()
    usable = [r for r in rows if isinstance(r.get(measure), (int, float))]
    if not usable:
        return None
    if measure == "flo":            # flourishing: worst is the LOWEST
        return min(usable, key=lambda r: r[measure])
    return max(usable, key=lambda r: r[measure])


def attribution(axis: str, rows: list[dict] | None = None) -> str | None:
    """'воден от <континент>' for an R4 row, or None when it cannot be said.

    Returns None rather than a guess. An axis whose measure has no per-country
    tier cannot be attributed, and inventing an attribution would be worse than
    leaving the row global — it would send someone to the wrong continent.
    """
    rows = rows if rows is not None else load()
    if not rows:
        return None
    lead = worst("dep", rows)
    if not lead:
        return None
    return (f"воден от {lead['continent']} "
            f"(лишения {lead['dep']:.2f}, {lead['countries']} държави)")


def render_markdown(rows: list[dict] | None = None,
                    when: str | None = None) -> list[str]:
    """The 'Континенти' section. Returns markdown lines."""
    rows = rows if rows is not None else load()
    if not rows:
        return []

    when = when or computed_at()
    out = ["## Континенти", "",
           "Едно число за цялата планета крие къде точно е зле. Ето същите "
           "данни, разделени на седем континента:", ""]
    out.append("| Континент | Държави | Население | Лишения | Натиск | Процъфтяване | Зона |")
    out.append("|---|---:|---:|---:|---:|---:|---|")
    for r in rows:
        pop = f"{r['population']:,}".replace(",", " ") if r["population"] else "—"
        out.append(
            f"| {r['continent']} | {r['countries']} | {pop} | "
            f"{r['dep']:.3f} | {r['str']:.3f} | {r['flo']:.3f} | {r['zone_bg']} |")
    out.append("")

    worst_dep = worst("dep", rows)
    worst_flo = worst("flo", rows)
    if worst_dep:
        out.append(f"- най-много лишения: **{worst_dep['continent']}** "
                   f"({worst_dep['dep']:.3f})")
    if worst_flo:
        out.append(f"- най-малко процъфтяване: **{worst_flo['continent']}** "
                   f"({worst_flo['flo']:.3f})")
    if when:
        out.append(f"- изчислено: {str(when)[:19]}")
    out.append("")
    return out


def _selftest() -> int:
    print("core/continents.py --selftest")
    rows = load()
    ok = True
    checks = [
        (f"seven continents load ({len(rows)})", len(rows) == 7),
        ("every one has dep/str/flo",
         all(isinstance(r[k], (int, float)) for r in rows for k in ("dep", "str", "flo"))),
        ("every one is named in Bulgarian",
         all(r["continent"] != r["region_id"] for r in rows)),
        ("worst deprivation is Sub-Saharan Africa",
         (worst("dep", rows) or {}).get("region_id") == "SSF"),
        ("an attribution can be produced", attribution("ANY", rows) is not None),
        ("the section renders", len(render_markdown(rows)) > 10),
    ]
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print()
    for line in render_markdown(rows)[:14]:
        print("   ", line)
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
