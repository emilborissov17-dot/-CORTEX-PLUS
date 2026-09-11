#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/daily_tier.py — THE WORLD THAT MOVES, KEPT. (10 Sep 2026, AGI-5.)

THE DEFECT, MEASURED
--------------------
Every night step 2.5 fetches 20 sources into snapshots/master/global_indicators
_latest.json — USGS quakes per UTC day, SPY/GLD/UUP closes, GBIF observations,
GDELT tone, arXiv/GitHub AI counts, NEO approaches, NOAA CO2 — and then the
next night OVERWRITES it. There is no archive: snapshots/master holds five
"_latest" files and nothing else. Of the 76 numeric leaves fetched on 10 Sep,
17 reach memory/axis_history.json through the axis reviews, and those are the
annual ones. The daily ones — the only part of the world that moves at the
system's sampling rate — were fetched ~100 times and kept zero times.

That is why world_forecast.py found 8 moving indicators out of 104, all of
them CLIMATE, and why 609 of 736 axis_next predictions were degenerate. The
system was not short of a world that moves. It was throwing it away.

WHAT THIS DOES
--------------
One append-only file, memory/daily_tier.jsonl, one row per (indicator, date):

    {"date", "indicator": "section.key", "value", "date_basis", "cycle_ts"}

  * `date` is the OBSERVATION date when the section states one (co2.co2_date,
    quakes.last_date, markets.last_date), else the fetch date — and
    `date_basis` says which ("source" / "fetch"), so a fetch-dated row can
    never be mistaken for a source-dated one.
  * a value the snapshot carried forward from a previous cycle (`_carried`)
    is NOT a new observation and is not written. Counted, named, skipped.
  * parameters are not observations: min_magnitude, *_year, thresholds,
    year fractions. Listed in NOT_OBSERVATIONS, by name.
  * idempotent: an (indicator, date) already on file is skipped, so running
    twice in a morning writes nothing twice.

BACKFILL FROM THE SOURCE'S OWN RECORD
-------------------------------------
USGS (fdsnws count with explicit UTC day bounds — core/usgs_quakes.py) and
Yahoo (3-month chart — core/market_daily.py) publish their own history, dated
by the source. `--backfill` writes those days with date_basis "source". It
does not invent a history for anything else: a source with no record starts
tonight.

world_forecast.load_series() reads this tier alongside axis_history, so from
the first morning the world loop has something that moves to predict.

Usage:
  venv\\Scripts\\python.exe core/daily_tier.py                 # record tonight's snapshot
  venv\\Scripts\\python.exe core/daily_tier.py --backfill 60   # USGS + markets from the source
  venv\\Scripts\\python.exe core/daily_tier.py --selftest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SNAPSHOT = REPO / "snapshots" / "master" / "global_indicators_latest.json"
TIER = REPO / "memory" / "daily_tier.jsonl"

SKIP_SECTIONS = {"timestamp", "sources", "_health"}
# a section's own statement of WHEN the value is from, if it makes one
DATE_FIELDS = ("co2_date", "last_date")
# numbers that describe the query, not the world
NOT_OBSERVATIONS = {
    "quakes.min_magnitude", "neo.neo_dist_threshold_au", "temperature.temp_anomaly_year",
    "sea_level.sea_level_year_fraction", "displaced.unhcr_year", "conflicts.ucdp_year",
    "nuclear.source_year", "media.news_tone_datapoints",
}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def rows_from_snapshot(snap: dict) -> tuple[list[dict], dict]:
    """Pure. (rows, counts). Nothing carried, nothing parametric, nothing non-numeric."""
    ts = str(snap.get("timestamp") or "")
    fetch_date = ts[:10] if ts else datetime.now(timezone.utc).date().isoformat()
    rows, counts = [], {"observed": 0, "carried_skipped": 0, "not_observation": 0}
    for section, data in snap.items():
        if section in SKIP_SECTIONS or section.startswith("_") or not isinstance(data, dict):
            continue
        carried = set((data.get("_carried") or {}).keys())
        src_date = next((str(data[f])[:10] for f in DATE_FIELDS if data.get(f)), None)
        for key, val in data.items():
            if key.startswith("_") or not _num(val):
                continue
            name = f"{section}.{key}"
            if name in NOT_OBSERVATIONS or key.endswith("_year"):
                counts["not_observation"] += 1
                continue
            if key in carried:
                counts["carried_skipped"] += 1
                continue
            rows.append({"date": src_date or fetch_date, "indicator": name, "value": float(val),
                         "date_basis": "source" if src_date else "fetch", "cycle_ts": ts})
            counts["observed"] += 1
    return rows, counts


def record(snapshot_path: Path = SNAPSHOT, tier_path: Path = TIER, dry: bool = False) -> dict:
    """Append tonight's observations. Idempotent on (indicator, date)."""
    try:
        snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"snapshot unreadable: {exc}", "written": 0}
    rows, counts = rows_from_snapshot(snap)
    have = {(r.get("indicator"), r.get("date")) for r in _read(tier_path)}
    new = [r for r in rows if (r["indicator"], r["date"]) not in have]
    if new and not dry:
        tier_path.parent.mkdir(parents=True, exist_ok=True)
        with tier_path.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts.update(written=len(new), already_on_file=len(rows) - len(new), dry=dry)
    return counts


def backfill(days: int = 60, tier_path: Path = TIER, usgs_fetch=None, market_fetch=None,
             dry: bool = False) -> dict:
    """USGS per-UTC-day counts and Yahoo daily closes from the source's own record.
    Fetchers injectable so the tests never touch the network."""
    from core import usgs_quakes as uq
    from core import market_daily as md
    ts = datetime.now(timezone.utc).isoformat()
    rows = []
    errors = {}
    try:
        for d, c in uq.series(uq.complete_days(days), fetcher=usgs_fetch):
            rows.append({"date": d.isoformat(), "indicator": "quakes.quake_m45_count", "value": float(c),
                         "date_basis": "source", "cycle_ts": ts, "backfill": True})
    except Exception as exc:  # noqa: BLE001
        errors["usgs"] = str(exc)
    for sym in md.ASSETS:
        try:
            payload = (market_fetch or md.fetch_chart)(sym)
            for d, px in md.parse_chart(payload):
                rows.append({"date": d.isoformat(), "indicator": f"markets.{sym.lower()}_adjclose",
                             "value": float(px), "date_basis": "source", "cycle_ts": ts, "backfill": True})
        except Exception as exc:  # noqa: BLE001
            errors[sym] = str(exc)
    have = {(r.get("indicator"), r.get("date")) for r in _read(tier_path)}
    new = [r for r in rows if (r["indicator"], r["date"]) not in have]
    if new and not dry:
        tier_path.parent.mkdir(parents=True, exist_ok=True)
        with tier_path.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"fetched": len(rows), "written": len(new), "errors": errors, "dry": dry}


def series(tier_path: Path = TIER) -> dict[str, list[tuple[str, float]]]:
    """{indicator: [(date, value)]} sorted by date, one value per date (first written wins)."""
    out: dict[str, dict[str, float]] = {}
    for r in _read(tier_path):
        ind, d, v = r.get("indicator"), r.get("date"), r.get("value")
        if ind and d and _num(v):
            out.setdefault(ind, {}).setdefault(d, float(v))
    return {k: sorted(dv.items()) for k, dv in out.items()}


def _selftest() -> int:
    print("core/daily_tier.py --selftest")
    snap = {"timestamp": "2026-09-10T00:21:52+00:00",
            "co2": {"co2_ppm": 427.15, "co2_annual_increase": 1.9, "co2_date": "2026-08-30"},
            "quakes": {"quake_m45_count": 12, "last_date": "2026-09-09", "min_magnitude": 4.5},
            "food": {"undernourishment_pct": 8.5, "food_production_index": 100.0,
                     "_carried": {"food_production_index": {"value": 100.0, "since": "2026-08-01"}}},
            "nuclear": {"nuclear_warheads_total": 12000, "source_year": 2024},
            "_health": {"fresh_this_cycle": 5}}
    rows, c = rows_from_snapshot(snap)
    by = {r["indicator"]: r for r in rows}
    checks = [
        ("source-dated when the section says when", by["co2.co2_ppm"]["date"] == "2026-08-30"
         and by["co2.co2_ppm"]["date_basis"] == "source"),
        ("quakes dated by last_date", by["quakes.quake_m45_count"]["date"] == "2026-09-09"),
        ("fetch-dated otherwise, and says so", by["food.undernourishment_pct"]["date"] == "2026-09-10"
         and by["food.undernourishment_pct"]["date_basis"] == "fetch"),
        ("a carried value is not an observation", "food.food_production_index" not in by
         and c["carried_skipped"] == 1),
        ("parameters are not observations", "quakes.min_magnitude" not in by
         and "nuclear.source_year" not in by and c["not_observation"] == 2),
        ("_health is not a section", not any(k.startswith("_health") for k in by)),
    ]
    live = series() if TIER.exists() else {}
    moving = {k: v for k, v in live.items() if len({x for _, x in v}) > 1}
    checks.append((f"live tier readable ({len(live)} indicators, {len(moving)} moving)", True))
    ok = True
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        n = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 and sys.argv[i + 1].isdigit() else 60
        print(json.dumps(backfill(n, dry="--dry" in sys.argv), ensure_ascii=False))
    print(json.dumps(record(dry="--dry" in sys.argv), ensure_ascii=False))
