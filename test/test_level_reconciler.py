#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_level_reconciler.py — AN AXIS AT 3.4/100 WAS BEING CALLED MEDIUM.

WHAT WENT WRONG
----------------
auto_levels writes a level word from its own thresholds. goal_score_calculator
writes a 0..1 score from the measured value, its target and its direction.
Nothing compared them, and on 21 August 2026:

    SOCIAL_RELATIONS_REVIEW     MEDIUM   score 0.034    (3.4/100)
    HUMAN_WELL_BEING_REVIEW     MEDIUM   score 0.9025
    CLIMATE_GLOBAL_RISK_REVIEW  LOW      score 0.8185

Everything reading a level word — self_modifier choosing which axis deserves a
patch, the orchestrator, the reports — was reading a word its own number
contradicts.

THE POLARITY RULING, 21 August 2026 (Emil)
-------------------------------------------
This file first asserted the opposite of what it now asserts, and that is worth
leaving visible. The two _RISK_ axes were held back as FLAGGED because nobody
had said whether LOW meant "low risk" or "far from goal" — a disagreement there
was evidence of an unanswered question, not of an error.

The question is answered. ONE rule for all 25 axes: the LEVEL WORD describes
CLOSENESS TO GOAL. LOW = far from goal = bad, everywhere. Risk inverts ONCE, at
measurement, and never again in the label.

  * SOCIAL_RELATIONS 3.4/MEDIUM      -> CORRECTED LOW
  * CLIMATE_GLOBAL_RISK 81.85/LOW    -> CORRECTED HIGH
  * and HIGH on a risk axis is rendered "ниво HIGH (нисък риск)" for people

The FLAGGED path stays, exercised by a fixture: no axis is unpinned today, but
a new one could arrive before anyone says what its score means.

    venv\\Scripts\\python.exe -m pytest test/test_level_reconciler.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import level_reconciler as lr

REPO = pathlib.Path(__file__).resolve().parents[1]

PINNED_AXIS = "SOCIAL_RELATIONS_REVIEW"
# Named for what it WAS before the 21 Aug ruling; kept so the history
# of this test file stays legible.
UNPINNED_AXIS = "CLIMATE_GLOBAL_RISK_REVIEW"


def _fixture(tmp_path, levels: dict, scores: dict, pinned: list[str]):
    lp = tmp_path / "auto_levels.json"
    lp.write_text(json.dumps({a: {"level": w} for a, w in levels.items()}),
                  encoding="utf-8")
    gp = tmp_path / "goal.json"
    gp.write_text(json.dumps({"metric_details": {
        f"m{i}": {"axis": a, "score": s} for i, (a, s) in enumerate(scores.items())
    }}), encoding="utf-8")
    cp = tmp_path / "config.json"
    cp.write_text(json.dumps({"BRANCH": {
        a: ({"score_meaning": "goodness"} if a in pinned else {})
        for a in set(levels) | set(scores)}}), encoding="utf-8")
    return dict(levels_path=lp, goal_path=gp, config_path=cp)


# 1 ---------------------------------------------------------------------------

def test_social_relations_is_corrected_to_low_on_live_data():
    """THE FIRST PROOF, against the real files on this machine."""
    result = lr.reconcile()
    row = next((r for r in result["rows"] if r["axis"] == PINNED_AXIS), None)

    assert row is not None, f"{PINNED_AXIS} is not in auto_levels.json"
    assert row["verdict"] == lr.CORRECTED, (
        f"\n  AN AXIS AT {round(row['score'] * 100, 1)}/100 IS STILL CALLED "
        f"{row['level']}.\n  verdict={row['verdict']}\n"
    )
    assert row["corrected_to"] == "LOW"
    assert row["score"] < 0.33


# 2 ---------------------------------------------------------------------------

def test_climate_global_risk_is_corrected_to_high_under_the_ruling():
    """THE SECOND PROOF, rewritten by Emil's polarity ruling of 21 August.

    This test used to assert the opposite — that a _RISK_ axis is FLAGGED and
    never corrected — because nobody had said whether LOW meant "low risk" or
    "far from goal". The ruling settled it: the level word describes CLOSENESS
    TO GOAL on every axis, risk inverts once at measurement and never in the
    label. So 81.85/100 is HIGH, and the axis is corrected like any other.
    """
    result = lr.reconcile()
    row = next((r for r in result["rows"] if r["axis"] == UNPINNED_AXIS), None)

    assert row is not None
    assert row["verdict"] == lr.CORRECTED, (
        f"\n  CLIMATE_GLOBAL_RISK WAS {row['verdict']}, NOT CORRECTED.\n"
        f"  Under the ruling there is nothing left to be ambiguous about:\n"
        f"  the word means closeness to goal on every axis.\n"
    )
    assert row["corrected_to"] == "HIGH"
    assert row["score"] == pytest.approx(0.8185)


def test_a_risk_axis_carries_its_human_translation():
    """HIGH on an axis named GLOBAL_RISK reads as danger and means the
    opposite. The machine keeps one rule; the person gets a translation."""
    assert lr.human_level("CLIMATE_GLOBAL_RISK_REVIEW", "HIGH") == "ниво HIGH (нисък риск)"
    assert lr.human_level("DEEP_TIME_RISKS_REVIEW", "LOW") == "ниво LOW (висок риск)"
    assert lr.human_level("ENERGY_REVIEW", "LOW") == "ниво LOW", (
        "an ordinary axis must not be given a risk gloss"
    )


def test_the_correction_row_carries_the_translation():
    result = lr.reconcile()
    row = next(r for r in result["corrections"] if r["axis"] == UNPINNED_AXIS)
    assert row["human"] == "ниво HIGH (нисък риск)"


def test_the_flag_path_still_exists_for_a_genuinely_unpinnable_axis(tmp_path):
    """No axis is unpinned today, but the mechanism must survive: an axis whose
    direction is not one of the normalising forms still cannot be judged."""
    paths = _fixture(tmp_path, {"WEIRD": "LOW"}, {"WEIRD": 0.9}, [])
    result = lr.reconcile(**paths)
    assert result["rows"][0]["verdict"] == lr.FLAGGED
    assert result["corrections"] == []


def test_no_unpinned_axis_appears_among_the_corrections():
    result = lr.reconcile()
    pinned = lr.pinned_axes()
    for row in result["corrections"]:
        assert row["axis"] in pinned, f"{row['axis']} was corrected while unpinned"


# 3 ---------------------------------------------------------------------------

# The ruling covered every axis in the tree. 25 -> 24 on 21 Aug 2026 when
# GENERAL_SELF_REVIEW was retired (declared in config/series_breaks.json). The
# number is pinned so the ruling's scope cannot narrow by accident; changing it
# has to be a visible edit, in the same commit as the tree.
PINNED_AXIS_COUNT = 24
TOTAL_WEIGHT = 167.0


def test_all_axes_are_pinned_after_the_ruling():
    """The ruling's scope, pinned so it cannot quietly narrow again."""
    pinned = set(lr.pinned_axes())
    cfg = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    everything = {a for b, axes in cfg.items() if not b.startswith("_")
                  for a in axes}

    assert pinned == everything, f"unpinned: {sorted(everything - pinned)}"
    assert len(pinned) == PINNED_AXIS_COUNT
    for risk in ("CLIMATE_GLOBAL_RISK_REVIEW", "DEEP_TIME_RISKS_REVIEW"):
        assert risk in pinned, f"{risk} is still unpinned"


def test_the_score_meaning_migration_moved_no_weight():
    """score_meaning is metadata. If a weight moved, it was not neutral.

    The total is 167 since 21 Aug 2026 — 173 minus GENERAL_SELF_REVIEW's 6. That
    is the ONLY sanctioned way this number may change, and it is written down in
    config/series_breaks.json. Any other drift means a weight moved without a
    declared break, which is exactly what rule 1.3 forbids.
    """
    cfg = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    total = sum(spec.get("weight", 0) or 0
                for b, axes in cfg.items() if not b.startswith("_")
                for spec in axes.values())
    assert total == TOTAL_WEIGHT, (
        f"total weight is {total}, expected {TOTAL_WEIGHT}. If a weight really "
        "moved, declare the break in config/series_breaks.json in the same commit.")

    breaks = json.loads((REPO / "config" / "series_breaks.json")
                        .read_text(encoding="utf-8"))["breaks"]
    latest = breaks[-1]["measured_effect"]["total_weight"]
    assert latest["after"] == TOTAL_WEIGHT, (
        "the newest declared break does not end at the weight the tree actually "
        f"carries ({latest['after']} vs {TOTAL_WEIGHT})")


# 4 ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,word", [
    (0.90, "HIGH"), (0.66, "HIGH"), (0.65, "MEDIUM"),
    (0.33, "MEDIUM"), (0.32, "LOW"), (0.034, "LOW"), (0.0, "LOW"),
])
def test_the_bands_are_what_they_say(score, word):
    assert lr.level_for(score) == word


# 5 ---------------------------------------------------------------------------

def test_an_agreeing_axis_is_left_alone(tmp_path):
    """POSITIVE CONTROL — a reconciler that corrects everything is not one."""
    paths = _fixture(tmp_path, {"A": "HIGH"}, {"A": 0.9}, ["A"])
    result = lr.reconcile(**paths)
    assert result["rows"][0]["verdict"] == lr.AGREES
    assert result["corrections"] == []


def test_an_axis_with_no_score_is_not_guessed_at(tmp_path):
    paths = _fixture(tmp_path, {"A": "MEDIUM"}, {}, ["A"])
    result = lr.reconcile(**paths)
    assert result["rows"][0]["verdict"] == lr.NO_SCORE


# 6 ---------------------------------------------------------------------------

def test_a_correction_carries_its_rationale(tmp_path):
    paths = _fixture(tmp_path, {"A": "MEDIUM"}, {"A": 0.034}, ["A"])
    row = lr.reconcile(**paths)["corrections"][0]

    assert row["corrected_to"] == "LOW"
    assert "3.4/100" in row["why"]
    assert "score_meaning=goodness" in row["why"]
    assert "threshold someone chose" in row["why"], (
        "the rationale must say WHY the number outranks the word"
    )


# 7 ---------------------------------------------------------------------------

def test_apply_writes_the_word_back_and_records_where_it_came_from(tmp_path):
    paths = _fixture(tmp_path, {"A": "MEDIUM"}, {"A": 0.034}, ["A"])
    corrections = tmp_path / "corrections.jsonl"
    result = lr.reconcile(**paths)

    moved = lr.apply(result, levels_path=paths["levels_path"],
                     corrections_path=corrections)
    assert moved == 1

    levels = json.loads(paths["levels_path"].read_text(encoding="utf-8"))
    assert levels["A"]["level"] == "LOW"
    assert levels["A"]["corrected_from"] == "MEDIUM"
    assert levels["A"]["corrected_by"] == "level_reconciler"


def test_flagged_rows_are_recorded_too_but_the_word_is_untouched(tmp_path):
    paths = _fixture(tmp_path, {"R": "LOW"}, {"R": 0.8185}, [])
    corrections = tmp_path / "corrections.jsonl"
    result = lr.reconcile(**paths)

    lr.apply(result, levels_path=paths["levels_path"],
             corrections_path=corrections)

    levels = json.loads(paths["levels_path"].read_text(encoding="utf-8"))
    assert levels["R"]["level"] == "LOW", "an unpinned axis was rewritten"
    assert "corrected_by" not in levels["R"]

    rows = [json.loads(l) for l in corrections.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert any(r["verdict"] == lr.FLAGGED for r in rows), (
        "a flagged axis left no record — it would be invisible until someone "
        "went looking"
    )


# 8 ---------------------------------------------------------------------------

def test_the_flagged_channel_is_empty_now_and_that_is_the_point():
    """Every axis is pinned, so nothing should be flagged. An entry here means
    a new axis arrived without anyone saying what its score means."""
    flagged = lr.for_phase_report()
    assert isinstance(flagged, list)
    assert flagged == [], (
        f"axes nobody has ruled on: {[r['axis'] for r in flagged]}"
    )


# 9 ---------------------------------------------------------------------------

def test_the_runner_calls_it_after_auto_levels():
    """A reconciler nobody calls is a comment about level drift."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert '"level_reconcile", "12.55"' in src
    assert "core.level_reconciler" in src


def test_it_runs_between_the_levels_and_the_score():
    """Order matters: it corrects the word auto_levels just wrote, before
    anything downstream reads it."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    a = src.index('beat("auto_levels", "12.5")')
    r = src.index('beat("level_reconcile", "12.55")')
    g = src.index('beat("goal_score_calculator", "12.6")')
    assert a < r < g


# 10 --------------------------------------------------------------------------

def test_a_broken_input_file_does_not_raise(tmp_path):
    """Fail-open: a reconciler that cannot read must not take the step down."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = lr.reconcile(levels_path=bad, goal_path=bad, config_path=bad)
    assert result["axes"] == 0
    assert result["corrections"] == []
