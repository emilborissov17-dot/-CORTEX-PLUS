#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_snapshot_carry_forward.py — a fetch failure must never destroy a value.

WHAT HAPPENED (measured 2026-08-03). fetch_all() returned a fresh dict and the cycle
wrote it over snapshots/master/global_indicators_latest.json wholesale. One slow minute
at the World Bank API turned eleven metrics into None — safe_water_access_pct,
life_expectancy, infant_mortality_per1k, undernourishment_pct, gini_mean, forest_area_pct,
literacy_rate_adult_pct, threatened_mammals_no, co2_emissions_kt and more.

That file is the origin of 41 of the 43 file-kind sources in the portfolio. 26 composer
sources across 9 axes died on it. Nothing about the world had changed; the World Bank
answered every one of those indicators in 0.3-0.4s when re-probed minutes later.

The composer has had the right rule for months — last-known-good, carried forward with
loud ageing, refused once too old. It simply was not applied one layer earlier, at the
file the composer reads.

Carried is not laundered into fresh. `_carried` names every metric served from a previous
cycle and dates it to the ORIGINAL observation, not to the last time it was copied
forward, so a value carried for a month cannot pass as today's reading.

  venv\\Scripts\\python.exe test\\test_snapshot_carry_forward.py
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import global_indicators as G  # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)


def ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ── the carry itself ─────────────────────────────────────────────────────────

OLD_TS = ago(24)
old = {"safe_water_access_pct": 73.6686, "life_expectancy": 73.48, "poverty_190_pct": 10.4}
new = {"safe_water_access_pct": None, "life_expectancy": 74.0, "poverty_190_pct": None}

carried = {}
merged = G._carry_forward(new, old, OLD_TS, carried)

check("a metric that FAILED this cycle keeps its previous value",
      merged["safe_water_access_pct"] == 73.6686)
check("...and the other failure too", merged["poverty_190_pct"] == 10.4)
check("a metric that SUCCEEDED takes the new value, not the old",
      merged["life_expectancy"] == 74.0)
check("exactly the failures are recorded as carried",
      set(carried) == {"safe_water_access_pct", "poverty_190_pct"})
check("...each with the value it is serving",
      carried["safe_water_access_pct"]["value"] == 73.6686)
check("...and dated, so it cannot pass as this cycle's reading",
      carried["safe_water_access_pct"]["since"] == OLD_TS
      and 23 < carried["safe_water_access_pct"]["age_hours"] < 25)
check("the carried map travels IN the section, where a reader trips over it",
      merged["_carried"] == carried)

# the age must be the ORIGINAL observation, not the last copy-forward
second = {"safe_water_access_pct": None}
carried2 = {}
merged2 = G._carry_forward(second, merged, ago(1), carried2)
check("carrying a carried value keeps the ORIGINAL date — otherwise a value copied "
      "forward for a month would look one cycle old, forever",
      carried2["safe_water_access_pct"]["since"] == OLD_TS
      and carried2["safe_water_access_pct"]["age_hours"] > 23)

check("a metric missing from BOTH cycles stays missing rather than being invented",
      G._carry_forward({"never_seen": None}, {}, OLD_TS, {})["never_seen"] is None)
check("nothing is carried when nothing failed",
      G._carry_forward({"a": 1.0}, {"a": 0.5}, OLD_TS, {}) == {"a": 1.0})
check("a 0.0 reading is a VALUE and is not treated as a failure to be overwritten",
      G._carry_forward({"a": 0.0}, {"a": 99.0}, OLD_TS, {})["a"] == 0.0)
check("internal bookkeeping keys are never carried as if they were metrics",
      "_carried" not in G._carry_forward({"a": None}, {"a": 1.0, "_carried": {"x": 1}},
                                         OLD_TS, {}).get("_carried", {}))
check("a missing previous section is survivable", G._carry_forward({"a": None}, None,
                                                                   OLD_TS, {}) == {"a": None})


# ── fetch_all wires it, and reports it ───────────────────────────────────────

_real = G._SECTIONS
G._SECTIONS = [
    ("wb", lambda: {"good": 1.0, "flaky": None}, "FakeBank"),
    ("other", lambda: {"always": 2.0}, "FakeOther"),
]
try:
    prev = {"timestamp": OLD_TS,
            "wb": {"good": 0.9, "flaky": 42.0},
            "other": {"always": 1.0}}
    res = G.fetch_all(previous=prev)
finally:
    G._SECTIONS = _real

check("fetch_all carries a failed metric across", res["wb"]["flaky"] == 42.0)
check("...and takes the fresh one where the fetch worked", res["wb"]["good"] == 1.0)
check("...counting fresh and carried separately in _health",
      res["_health"]["fresh_this_cycle"] == 2
      and res["_health"]["carried_from_a_previous_cycle"] == 1)
check("...and stating the rule in the file itself",
      "never overwrites a good value with null" in res["_health"]["rule"])

_real2 = G._SECTIONS
G._SECTIONS = [("wb", lambda: {"good": 1.0, "flaky": None}, "FakeBank")]
try:
    cold = G.fetch_all(previous=None)
finally:
    G._SECTIONS = _real2
check("with no previous snapshot nothing is invented — a first run is honest about "
      "what it could not get",
      cold["wb"]["flaky"] is None and cold["_health"]["missing_everywhere"] == 1)


# ── the live file, as it now stands ──────────────────────────────────────────

SNAP = REPO / "snapshots" / "master" / "global_indicators_latest.json"
if SNAP.exists():
    live = json.loads(SNAP.read_text(encoding="utf-8"))
    wb = live.get("world_bank") or {}
    nulls = [k for k, v in wb.items() if not k.startswith("_") and v is None]
    check(f"the live world_bank block is populated ({len(wb)} keys, {len(nulls)} null)",
          len(nulls) <= 1)
    check("the metrics that killed 26 sources are back",
          all(wb.get(k) is not None for k in
              ("safe_water_access_pct", "life_expectancy", "infant_mortality_per1k")))
    check("...and food too",
          (live.get("food") or {}).get("undernourishment_pct") is not None)
    check("the snapshot carries a _health block a human can read at a glance",
          isinstance(live.get("_health"), dict))

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
