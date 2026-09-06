# -*- coding: utf-8 -*-
"""
The indicator history that did not exist. Written 6 Sep 2026, failing first.

MEASURED that morning: `memory/axis_observations.jsonl` was absent and 0 of 177
archived snapshots carried an `axis_observations` block, so nothing in the system
could say what a WATER_REVIEW delta of +1.2 is on that indicator's own scale.
`goal_score_history.json` is NOT a substitute — it stores a normalised 0-100
score, a different quantity (INEQUALITY_POVERTY_REVIEW: 10.4 as an indicator,
82.67 as a score on the same day).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import axis_history as ah          # noqa: E402

# TODAY'S COVERAGE, recorded 6 Sep 2026. The test asserts against the LIVE count
# so a real change in what the cycle measures reads as a change; this number is
# here to say what it was when the test was written.
INDICATORS_ON_6_SEP = 13


def test_a_cycle_writes_one_line_per_gradeable_indicator(tmp_path):
    from core.gate_contract import gradeable_indicators
    live = gradeable_indicators()
    out = tmp_path / "axis_observations.jsonl"
    rec = ah.record(cycle_id="c1", path=out)

    numeric = {k: v for k, v in live.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    assert rec["written"] == len(numeric), (
        f"wrote {rec['written']} lines for {len(numeric)} numeric gradeable "
        f"indicators")
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == len(numeric)
    assert all(isinstance(r["value"], float) for r in rows), "a value is not numeric"


def test_todays_coverage_is_still_thirteen():
    """If this fails, the cycle measures a different number of axes than it did
    on 6 Sep. That is a finding about coverage, not a broken test — read it,
    then update the constant."""
    from core.gate_contract import gradeable_indicators
    n = len(gradeable_indicators())
    assert n == INDICATORS_ON_6_SEP, (
        f"measured_axes() now returns {n}, was {INDICATORS_ON_6_SEP} on 6 Sep")


def test_every_record_carries_the_five_fields(tmp_path):
    out = tmp_path / "o.jsonl"
    ah.record({"WATER_REVIEW": 73.6686}, source_step="unit_test",
              cycle_id="c1", path=out)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    for f in ("utc", "indicator", "value", "unit", "source_step", "cycle_id"):
        assert f in row, f
    assert row["source_step"] == "unit_test"


def test_units_come_from_target_config_and_are_never_invented():
    units = ah._units()
    assert units.get("WATER_REVIEW") == "percent of population"
    assert units.get("CLIMATE_GLOBAL_RISK_REVIEW") == "ppm"
    assert ah.unit_for("A_THING_NOBODY_DECLARED", units) == ah.UNDECLARED


def test_an_undeclared_unit_is_named_not_guessed(tmp_path):
    out = tmp_path / "o.jsonl"
    rec = ah.record({"MADE_UP_AXIS": 1.0}, path=out)
    assert rec["undeclared_units"] == ["MADE_UP_AXIS"]
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["unit"] == "UNDECLARED"


def test_a_non_numeric_value_is_dropped_not_coerced(tmp_path):
    out = tmp_path / "o.jsonl"
    rec = ah.record({"WATER_REVIEW": 73.6, "BROKEN": "n/a", "FLAG": True}, path=out)
    assert rec["written"] == 1, "a string or a bool reached the history"


def test_the_file_is_append_only(tmp_path):
    out = tmp_path / "o.jsonl"
    ah.record({"WATER_REVIEW": 1.0}, path=out)
    ah.record({"WATER_REVIEW": 2.0}, path=out)
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 2
    assert [v for _, v in ah.load("WATER_REVIEW", out)] == [1.0, 2.0]


# ── the range, which 3b judges against ───────────────────────────────────────

def test_range_counts_DAYS_not_rows(tmp_path):
    """A cycle that runs twice in a night is one day of evidence, not two."""
    out = tmp_path / "o.jsonl"
    for v in (1.0, 2.0, 3.0):
        out.open("a", encoding="utf-8").write(json.dumps(
            {"utc": "2026-09-06T01:00:00+00:00", "indicator": "X",
             "value": v, "unit": "u", "source_step": "s", "cycle_id": None}) + "\n")
    r = ah.daily_range("X", path=out)
    assert r["n"] == 1, f"three rows on one day counted as {r['n']} days"
    assert r["min"] == 1.0 and r["max"] == 3.0 and r["range"] == 2.0


def test_an_empty_history_reports_zero_not_a_default_range(tmp_path):
    r = ah.daily_range("NOTHING", path=tmp_path / "missing.jsonl")
    assert r["n"] == 0 and r["range"] is None, (
        "an absent history must be a named unknown, never a default range")
