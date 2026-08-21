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

THE TWO PROOFS
---------------
  * SOCIAL_RELATIONS 3.4/MEDIUM -> CORRECTED LOW
  * an unpinned _RISK_ axis is FLAGGED, never corrected

The second is the one that keeps this honest. On a _RISK_ axis, LOW might mean
"low risk" — the opposite polarity. A disagreement there is not evidence of an
error, it is evidence that nobody has said what the word means. Correcting it
would be guessing, and guessing is how the drift started.

    venv\\Scripts\\python.exe -m pytest test/test_level_reconciler.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import level_reconciler as lr

REPO = pathlib.Path(__file__).resolve().parents[1]

PINNED_AXIS = "SOCIAL_RELATIONS_REVIEW"
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

def test_an_unpinned_risk_axis_is_flagged_never_corrected():
    """THE SECOND PROOF. It disagrees just as loudly and must not be touched."""
    result = lr.reconcile()
    row = next((r for r in result["rows"] if r["axis"] == UNPINNED_AXIS), None)

    assert row is not None
    assert row["verdict"] == lr.FLAGGED, (
        f"\n  AN UNPINNED _RISK_ AXIS WAS {row['verdict']}.\n"
        f"  On a risk axis LOW may mean low RISK — the opposite polarity. A\n"
        f"  disagreement is not evidence of an error here, it is evidence that\n"
        f"  nobody has said what the word means. That is Emil's call.\n"
    )
    assert "corrected_to" not in row
    assert "RISK" in row["why"]


def test_no_unpinned_axis_appears_among_the_corrections():
    result = lr.reconcile()
    pinned = lr.pinned_axes()
    for row in result["corrections"]:
        assert row["axis"] in pinned, f"{row['axis']} was corrected while unpinned"


# 3 ---------------------------------------------------------------------------

def test_exactly_the_two_risk_axes_are_unpinned():
    """The migration's scope, pinned so it cannot quietly widen."""
    pinned = set(lr.pinned_axes())
    cfg = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    everything = {a for b, axes in cfg.items() if not b.startswith("_")
                  for a in axes}
    unpinned = everything - pinned

    assert unpinned == {"CLIMATE_GLOBAL_RISK_REVIEW", "DEEP_TIME_RISKS_REVIEW"}, (
        f"the unpinned set moved: {sorted(unpinned)}"
    )
    assert len(pinned) == 23


def test_the_migration_was_composite_neutral():
    """score_meaning is metadata. If a weight moved, it was not neutral."""
    cfg = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    total = sum(spec.get("weight", 0) or 0
                for b, axes in cfg.items() if not b.startswith("_")
                for spec in axes.values())
    assert total == 173.0, f"total weight is {total}, was 173"


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

def test_the_flagged_rows_reach_the_phase_report():
    flagged = lr.for_phase_report()
    assert isinstance(flagged, list)
    assert all(r["verdict"] == lr.FLAGGED for r in flagged)
    assert any(r["axis"] == UNPINNED_AXIS for r in flagged)


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
