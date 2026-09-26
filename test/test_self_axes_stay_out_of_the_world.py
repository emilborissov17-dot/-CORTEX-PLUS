# -*- coding: utf-8 -*-
"""
test/test_self_axes_stay_out_of_the_world.py — BODY_SCAN and the other self axes
never reach a world-facing aggregate (C4 F, 26 Sep 2026).

Found on 26 Sep 2026: goal_score was clean, but memory/goal_score_history.json
"scores" carried BODY_SCAN (the machine's capacity %, 29.8) next to the world
axes. The daily rationale averaged them (59.9 instead of 61.9 over the world) and
named BODY_SCAN as the day's biggest mover.

The rule: a self axis is refused LOUDLY by goal_score (raise, not skip), kept out
of feedback_loop's world scores (it goes to the self-model), and ignored by the
rationale average even in history rows written before the fix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import goal_score_calculator as g  # noqa: E402


def test_the_self_axes_are_named():
    assert {"BODY_SCAN", "GENERAL_SELF_REVIEW", "GOAL_PROGRESS_REVIEW"} <= g.SELF_AXES


def test_no_self_axis_reaches_goal_score_on_the_live_goal_tree():
    r = g.compute_goal_score(trends={}, last_obs={}, targets=g.load_targets())
    scored = {a for a, v in (r.get("axis_scores") or {}).items()
              if (v.get("score") if isinstance(v, dict) else v) is not None}
    assert not scored & g.SELF_AXES, f"self axes scored into goal_score: {scored & g.SELF_AXES}"


def test_a_self_axis_in_the_goal_tree_is_refused_loudly():
    """NEGATIVE CONTROL: BODY_SCAN with a real metric in the goal tree must raise,
    not be scored and not be skipped in silence. Remove the raise and this fails."""
    targets = {"SELF": {"BODY_SCAN": {"primary_metric": "ram_free_mb", "target_value": 4000,
                                      "direction": "higher_better", "weight": 5}}}
    with pytest.raises(ValueError, match="BODY_SCAN"):
        g.compute_goal_score(trends={}, last_obs={"ram_free_mb": 3000}, targets=targets)


def test_the_self_reference_still_passes_as_none():
    targets = {"SELF": {"GOAL_PROGRESS_REVIEW": {"primary_metric": "goal_score",
                                                 "weight": 8}}}
    r = g.compute_goal_score(trends={}, last_obs={}, targets=targets)
    v = (r.get("axis_scores") or {}).get("GOAL_PROGRESS_REVIEW")
    assert (v.get("score") if isinstance(v, dict) else v) is None


def test_feedback_loop_keeps_self_axes_out_of_the_world_scores(tmp_path, monkeypatch):
    from agents.core import feedback_loop as fl
    master = tmp_path / "master.json"
    master.write_text(json.dumps({"snapshots": {
        "BODY_SCAN": {"capacity_pct": 29.8},
        "WATER_REVIEW": {"score": 0.7},
    }}), encoding="utf-8")
    monkeypatch.setattr(fl, "MASTER_SNAP", master)
    monkeypatch.setattr(fl, "_measured_axis_scores", lambda: {"WATER_REVIEW": 73.7})
    scores = fl.read_current_scores()
    assert "BODY_SCAN" not in scores and scores.get("WATER_REVIEW") == 73.7
    assert "BODY_SCAN" in fl.read_current_scores.last_self, "the self-model lost it"


def test_the_rationale_average_ignores_self_axes_in_old_rows(tmp_path, monkeypatch):
    from experiments.needs import needs_report as nr
    (tmp_path / "memory").mkdir()
    rows = [{"timestamp": "d1", "scores": {"WATER_REVIEW": 70.0, "BODY_SCAN": 90.0}},
            {"timestamp": "d2", "scores": {"WATER_REVIEW": 70.0, "BODY_SCAN": 10.0}}]
    (tmp_path / "memory" / "goal_score_history.json").write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(nr, "REPO", tmp_path)
    monkeypatch.setattr(nr, "RATIONALE_DIR", tmp_path / "out")
    out = nr.push_rationale()
    text = next((tmp_path / "out").glob("RATIONALE_*.md")).read_text(encoding="utf-8")
    assert "70.0/100" in text and "BODY_SCAN" not in text, (out, text)


def test_a_self_axis_page_is_never_published(tmp_path, monkeypatch):
    """GENERAL_SELF_REVIEW had its own page in the public reports folder on
    2026-09-25. The page and its line in the Daily index are both withheld."""
    import github_publisher as gp
    folder = tmp_path / "2026-09-26"
    folder.mkdir()
    (folder / "water_review_web_intel.json").write_text(json.dumps({"axis": "WATER_REVIEW"}), encoding="utf-8")
    (folder / "general_self_review_web_intel.json").write_text(
        json.dumps({"axis": "GENERAL_SELF_REVIEW"}), encoding="utf-8")
    pushed = {}
    monkeypatch.setattr(gp, "_push_file", lambda path, content, message: pushed.__setitem__(path, content))
    monkeypatch.setattr(gp, "cycle_date", lambda now_utc=None: "2026-09-26")
    got = gp.publish_cycle(folder)
    assert got["published"] == 1
    assert "reports/2026-09-26/general_self_review.md" not in pushed
    assert "GENERAL_SELF_REVIEW" not in pushed["reports/2026-09-26/index.md"]
    assert "WATER_REVIEW" in pushed["reports/2026-09-26/index.md"]
