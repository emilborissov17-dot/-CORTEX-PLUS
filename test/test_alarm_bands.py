#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_alarm_bands.py — A RED LINE RINGS WHEN IT IS CROSSED, OR IT IS NOT A RED LINE.

WHAT THIS GUARDS
-----------------
One number per axis, past which a person is told AT ONCE. Three ways it can be
quietly useless, and a test for each:

  * a crossing that waits for the morning digest        -> not an alarm
  * a null threshold that alarms anyway                 -> noise, then muting
  * a threshold that is set but cannot be checked       -> armed, checking nothing

The third is the subtle one. If an axis has a threshold and no usable
direction, the sweep cannot know which side of the line is bad. Skipping it
would leave a red line that LOOKS armed. It reports CONFIG_ERROR instead.

WHY ALL 25 ARE null TODAY
--------------------------
A red line nobody chose is a number the system invented and then measured
itself against. The count is reported as AWAITING_HUMAN_VALUES so the emptiness
stays a standing question. scripts/propose_alarm_thresholds.py suggests values
— as proposals, into the SLA queue, never as defaults.

    venv\\Scripts\\python.exe -m pytest test/test_alarm_bands.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import alarm_bands as ab

REPO = pathlib.Path(__file__).resolve().parents[1]


def _fixture(tmp_path, axes: dict, values: dict):
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps({"BRANCH": axes}), encoding="utf-8")
    gp = tmp_path / "goal.json"
    gp.write_text(json.dumps({"metric_details": {
        f"m{i}": {"axis": a, "current": v} for i, (a, v) in enumerate(values.items())
    }}), encoding="utf-8")
    return dict(config_path=cp, goal_path=gp)


def _capture():
    sent = []
    return sent, lambda axis, text: sent.append({"axis": axis, "text": text})


# ---------------------------------------------------------------------------
# (a) A crossing sends immediately
# ---------------------------------------------------------------------------

# 25 axes / 173 weight until 21 Aug 2026, when GENERAL_SELF_REVIEW was retired
# (weight 6) and the break was declared in config/series_breaks.json. Pinned so
# a weight cannot move without an edit here, in the same commit.
AXIS_COUNT = 24
TOTAL_WEIGHT = 167.0


def test_a_crossing_alarms_and_sends(tmp_path):
    paths = _fixture(tmp_path,
                     {"A": {"direction": "lower_better", "alarm_threshold": 350.0,
                            "unit": "ppm"}},
                     {"A": 427.59})
    result = ab.sweep(**paths)
    sent, sender = _capture()
    ab.send(result, sender=sender)

    assert result["counts"][ab.ALARM] == 1
    assert len(sent) == 1, "a crossed red line did not send"
    assert "427.59" in sent[0]["text"] and "350" in sent[0]["text"]


def test_the_message_says_it_is_not_a_digest(tmp_path):
    """An alarm that reads like a report gets filed like one."""
    paths = _fixture(tmp_path,
                     {"A": {"direction": "lower_better", "alarm_threshold": 1.0}},
                     {"A": 9.0})
    sent, sender = _capture()
    ab.send(ab.sweep(**paths), sender=sender)
    assert "не е дайджест" in sent[0]["text"]


def test_the_send_path_bypasses_quiet_hours():
    """trigger=MANUAL is what carries the bypass through supervisor."""
    import inspect
    src = inspect.getsource(ab.send)
    assert 'trigger="MANUAL"' in src, (
        "an alarm that waits for 08:00 is a report, not an alarm"
    )


# ---------------------------------------------------------------------------
# (b) THE NEGATIVE CONTROL — a null threshold never alarms
# ---------------------------------------------------------------------------

def test_a_null_threshold_never_alarms(tmp_path):
    paths = _fixture(tmp_path,
                     {"A": {"direction": "lower_better", "alarm_threshold": None}},
                     {"A": 999999.0})
    result = ab.sweep(**paths)

    assert result["counts"][ab.ALARM] == 0, (
        "\n  AN UNSET BAND FIRED.\n"
        "  The value is absurd on purpose. A red line nobody chose must not\n"
        "  ring — that is a number the system invented and then measured\n"
        "  itself against.\n"
    )
    assert result["rows"][0]["verdict"] == ab.UNSET
    assert result["AWAITING_HUMAN_VALUES"] == 1


def test_the_live_config_has_every_band_unset_and_says_how_many():
    result = ab.sweep()
    assert result["axes"] == AXIS_COUNT
    assert result["AWAITING_HUMAN_VALUES"] == AXIS_COUNT
    assert result["alarms"] == []


def test_the_counter_reaches_the_cycle_report():
    counter = ab.for_cycle_report()
    assert counter["awaiting_human_values"] == AXIS_COUNT
    assert counter["axes"] == AXIS_COUNT


# ---------------------------------------------------------------------------
# (c) THE OTHER NEGATIVE CONTROL — a missing direction is an error, not a skip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("direction", [None, "", "up", "better", 5])
def test_a_threshold_without_a_usable_direction_is_a_config_error(tmp_path,
                                                                  direction):
    paths = _fixture(tmp_path,
                     {"A": {"direction": direction, "alarm_threshold": 10.0}},
                     {"A": 99.0})
    result = ab.sweep(**paths)
    row = result["rows"][0]

    assert row["verdict"] == ab.CONFIG_ERROR, (
        f"\n  A THRESHOLD IS SET AND THE CHECK WAS {row['verdict']}.\n"
        f"  direction={direction!r} — the sweep cannot tell which side of the\n"
        f"  line is bad. Skipping leaves a red line that LOOKS armed and\n"
        f"  checks nothing, which is worse than having no line at all.\n"
    )
    assert "cannot tell which side" in row["why"]
    assert result["counts"][ab.ALARM] == 0


def test_config_errors_are_surfaced_not_buried(tmp_path):
    paths = _fixture(tmp_path,
                     {"A": {"direction": "sideways", "alarm_threshold": 1.0}},
                     {"A": 2.0})
    result = ab.sweep(**paths)
    assert len(result["config_errors"]) == 1
    assert ab.for_cycle_report()["config_errors"] == 0  # live config is clean


# ---------------------------------------------------------------------------
# (d) Which side is bad
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,threshold,direction,expected", [
    (427.59, 350.0, "lower_better", True),
    (300.00, 350.0, "lower_better", False),
    (350.00, 350.0, "lower_better", False),
    (20.0, 50.0, "higher_better", True),
    (80.0, 50.0, "higher_better", False),
    (50.0, 50.0, "higher_better", False),
])
def test_direction_decides_which_side_crosses(value, threshold, direction,
                                              expected):
    assert ab.crossed(value, threshold, direction) is expected


def test_stable_better_alarms_on_either_side():
    assert ab.crossed(12.0, 2.0, "stable_better", target=10.0) is False
    assert ab.crossed(13.0, 2.0, "stable_better", target=10.0) is True
    assert ab.crossed(7.0, 2.0, "stable_better", target=10.0) is True


def test_an_unusable_direction_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        ab.crossed(1.0, 2.0, "whatever")


# ---------------------------------------------------------------------------
# (e) An armed band with nothing measured
# ---------------------------------------------------------------------------

def test_a_set_band_on_an_unmeasured_axis_is_reported_not_alarmed(tmp_path):
    """Silence from a band that is watching nothing must not read as safety."""
    paths = _fixture(tmp_path,
                     {"A": {"direction": "lower_better", "alarm_threshold": 1.0}},
                     {})
    result = ab.sweep(**paths)
    assert result["rows"][0]["verdict"] == ab.NO_VALUE
    assert "nothing measured this axis" in result["rows"][0]["why"]


# ---------------------------------------------------------------------------
# (f) The migration and the proposals
# ---------------------------------------------------------------------------

def test_the_migration_was_composite_neutral():
    cfg = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    total = sum(spec.get("weight", 0) or 0
                for b, axes in cfg.items() if not b.startswith("_")
                for spec in axes.values())
    assert total == TOTAL_WEIGHT


def test_every_axis_has_the_key_and_every_value_is_null():
    cfg = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    axes = {a: s for b, g in cfg.items() if not b.startswith("_")
            for a, s in g.items()}
    assert len(axes) == AXIS_COUNT
    for axis, spec in axes.items():
        assert "alarm_threshold" in spec, f"{axis} has no band"
        assert spec["alarm_threshold"] is None, (
            f"{axis} has a threshold nobody signed — suggestions are proposals, "
            f"not defaults"
        )


def test_the_proposals_exist_and_name_their_basis():
    path = REPO / "memory" / "threshold_proposals.json"
    assert path.exists(), "no suggestions were generated for Emil to approve"
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["axes"] == 25
    for row in data["proposals"]:
        assert row["basis"] in ("reference_worst", "rationale", "fallback", "none")
        assert row["reasoning"], f"{row['axis']} suggests a number with no reason"


def test_a_fallback_suggestion_says_it_is_not_evidence():
    data = json.loads((REPO / "memory" / "threshold_proposals.json")
                      .read_text(encoding="utf-8"))
    fallbacks = [r for r in data["proposals"] if r["basis"] == "fallback"]
    assert fallbacks
    for row in fallbacks:
        assert "NOTHING IN THE CONFIG SUPPORTS" in row["reasoning"]


def test_a_citation_number_is_not_proposed_as_a_threshold():
    """CLIMATE's rationale cites 'Nature 461:472'. The first run proposed a red
    line of 461 ppm — a journal volume number."""
    from scripts.propose_alarm_thresholds import numbers_in
    cited = ("Planetary Boundaries safe CO2 ceiling (Rockström et al. 2009, "
             "Nature 461:472; pre-industrial ~280 ppm, safe boundary ~350 ppm)")
    assert 461.0 not in numbers_in(cited), (
        "a bibliography entry was read as science"
    )

    data = json.loads((REPO / "memory" / "threshold_proposals.json")
                      .read_text(encoding="utf-8"))
    climate = next(r for r in data["proposals"]
                   if r["axis"] == "CLIMATE_GLOBAL_RISK_REVIEW")
    assert climate["suggested"] != 461.0


# ---------------------------------------------------------------------------
# (g) Wiring
# ---------------------------------------------------------------------------

def test_the_sweep_runs_right_after_scoring():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert '"alarm_bands", "12.42"' in src
    assert src.index('beat("scoring_engine", "12.4")') < \
        src.index('beat("alarm_bands", "12.42")')
