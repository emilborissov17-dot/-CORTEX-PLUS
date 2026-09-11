# -*- coding: utf-8 -*-
"""test/test_axis_backfill.py — the years behind every axis (11 Sep 2026, Emil).

Pinned:
  * World Bank and NOAA payloads parse oldest-first, nulls dropped
  * merge is idempotent; a revised source value replaces the row, not duplicates it
  * the annual base lives in its OWN file — memory/axis_history.json is untouched
  * WB_CODES agrees with goal_score_calculator's obs_map
  * trend(): FLAT / IMPROVING / WORSENING against the axis's direction; <5 years -> no verdict
  * constancy(): an axis far from target with a FLAT decade is NEGATIVE_TREND and in `stagnation`;
    an IMPROVING one is MOVING; the base extends the history span past the 400-day window
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import axis_backfill as AB  # noqa: E402
from core import alarm_bands as ab  # noqa: E402

WB = [{"page": 1}, [{"date": "2022", "value": 73.4}, {"date": "2021", "value": None},
                    {"date": "2020", "value": 72.9}, {"date": "2000", "value": 61.0}]]
NOAA = "# comment\n# year mean unc\n  2023   421.08   0.12\n  2022   418.53   0.12\n"


def test_parsers():
    assert AB.parse_wb(WB) == [(2000, 61.0), (2020, 72.9), (2022, 73.4)]
    assert AB.parse_wb([{"message": "err"}]) == [] and AB.parse_wb("junk") == []
    assert AB.parse_noaa_annual(NOAA) == [(2022, 418.53), (2023, 421.08)]


def test_merge_is_idempotent_and_revises_in_place():
    h = {}
    r = AB.merge(h, "WATER_REVIEW", "safe_water_access_pct", [(2000, 61.0), (2020, 72.9)], "wb", now="t")
    assert r["added"] == 2 and r["first"] == 2000 and r["last"] == 2020
    r = AB.merge(h, "WATER_REVIEW", "safe_water_access_pct", [(2000, 61.0), (2020, 72.9)], "wb", now="t2")
    assert r["added"] == 0 and r["revised"] == 0 and h["WATER_REVIEW"][0]["fetched"] == "t"
    r = AB.merge(h, "WATER_REVIEW", "safe_water_access_pct", [(2020, 73.0), (2022, 73.4)], "wb", now="t3")
    assert r["added"] == 1 and r["revised"] == 1 and len(h["WATER_REVIEW"]) == 3
    assert [x["date"] for x in h["WATER_REVIEW"]] == ["2000-12-31", "2020-12-31", "2022-12-31"]


def test_run_writes_only_the_annual_file(tmp_path):
    t = tmp_path / "targets.json"
    t.write_text(json.dumps({"G": {"WATER_REVIEW": {"primary_metric": "safe_water_access_pct"},
                                   "CLIMATE_GLOBAL_RISK_REVIEW": {"primary_metric": "co2_ppm_mauna_loa"},
                                   "X": {"primary_metric": "nothing_here"}}}), encoding="utf-8")
    get = lambda url: NOAA if "noaa" in url else json.dumps(WB)  # noqa: E731
    out = AB.run(get=get, path=tmp_path / "annual.json", targets_path=t, now="t")
    assert out["axes_with_series"] == 2 and out["added"] == 5
    assert not (tmp_path / "axis_history.json").exists()
    assert AB.series_for("WATER_REVIEW", tmp_path / "annual.json") == [(2000, 61.0), (2020, 72.9), (2022, 73.4)]
    out2 = AB.run(get=get, path=tmp_path / "annual.json", targets_path=t, now="t")
    assert out2["added"] == 0 and out2["revised"] == 0
    bad = AB.run(get=lambda u: (_ for _ in ()).throw(OSError("down")), path=tmp_path / "a2.json", targets_path=t)
    assert bad["axes_with_series"] == 0 and all(r["error"].startswith("fetch_failed") for r in bad["rows"])


def test_wb_codes_agree_with_goal_score_calculator():
    src = (REPO / "goal_score_calculator.py").read_text(encoding="utf-8")
    for metric, code in AB.WB_CODES.items():
        assert f'"{metric}"' in src and f"wb_{code}" in src, (metric, code)


def test_trend_verdicts():
    up = [(2010 + i, 60.0 + i) for i in range(12)]
    assert ab.trend(up, "higher_better")["verdict"] == ab.IMPROVING
    assert ab.trend(up, "lower_better")["verdict"] == ab.WORSENING
    flat = [(2010 + i, 50.0 + (0.001 if i % 2 else 0)) for i in range(12)]
    assert ab.trend(flat, "higher_better")["verdict"] == ab.FLAT
    assert ab.trend(up[:4], "higher_better")["verdict"] is None
    t = ab.trend(up, "higher_better")
    assert t["first"] == (2010, 60.0) and t["last"] == (2021, 71.0) and t["fit_years"] == 10 and t["slope_per_year"] == 1.0


def _goal(tmp_path, axis, score, direction, current, target):
    g = tmp_path / "goal.json"
    g.write_text(json.dumps({"metric_details": {axis: {"axis": axis, "score": score, "direction": direction,
                                                       "current": current, "target": target}}}), encoding="utf-8")
    return g


def _annual(tmp_path, axis, metric, series):
    a = tmp_path / "annual.json"
    h = {}
    AB.merge(h, axis, metric, series, "wb", now="t")
    a.write_text(json.dumps(h), encoding="utf-8")
    return a


def _hist(tmp_path, axis, value, days=("2026-03-09", "2026-09-10")):
    h = tmp_path / "axis_history.json"
    h.write_text(json.dumps({axis: [{"date": d, "metrics": {"m": value}} for d in days]}), encoding="utf-8")
    return h


def test_far_from_target_with_a_flat_decade_is_negative_trend(tmp_path):
    ax = "WATER_REVIEW"
    r = ab.constancy(goal_path=_goal(tmp_path, ax, 0.3, "higher_better", 30.0, 100.0),
                     history_path=_hist(tmp_path, ax, 30.0),
                     annual_path=_annual(tmp_path, ax, "safe_water_access_pct", [(2000 + i, 30.0) for i in range(25)]),
                     now=date(2026, 9, 11))
    row = r["rows"][0]
    assert row["class"] == ab.NEGATIVE_TREND and r["stagnation"] and row["history_days"] > 400
    assert "FLAT" in row["why"] and row["trend"]["years"] == 25


def test_far_from_target_but_improving_is_moving(tmp_path):
    ax = "WATER_REVIEW"
    r = ab.constancy(goal_path=_goal(tmp_path, ax, 0.3, "higher_better", 30.0, 100.0),
                     history_path=_hist(tmp_path, ax, 30.0),
                     annual_path=_annual(tmp_path, ax, "safe_water_access_pct", [(2000 + i, 10.0 + i) for i in range(25)]),
                     now=date(2026, 9, 11))
    row = r["rows"][0]
    assert row["class"] == ab.MOVING and "IMPROVING" in row["why"] and not r["stagnation"]


def test_without_a_base_the_short_window_still_says_unclassified(tmp_path):
    ax = "WATER_REVIEW"
    r = ab.constancy(goal_path=_goal(tmp_path, ax, 0.3, "higher_better", 30.0, 100.0),
                     history_path=_hist(tmp_path, ax, 30.0), annual_path=tmp_path / "absent.json",
                     now=date(2026, 9, 11))
    assert r["rows"][0]["class"] == ab.UNCLASSIFIED and r["rows"][0]["trend"]["verdict"] is None
