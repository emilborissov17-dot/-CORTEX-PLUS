# -*- coding: utf-8 -*-
"""ITEM 34-A — a null score must never be replaced by an average of unrelated metrics.

THE DEFECT, cortex_scanner.py:62-72. When the latest history point has
score None, the else branch averaged every numeric value in that point's
`metrics` that happened to fall between 0 and 100, and published the mean as the
AXIS SCORE — into state["trends"]["scores"] at :73 and to
memory/cortex_full_state.json at :166. Metrics are not commensurable with a
score and not with each other; a percentage, a count and a ratio that all land
in 0..100 would be averaged into a number that means nothing and looks like a
measurement.

Kimi: "The ELSE branch invents axis scores by averaging unrelated metrics that
happen to fall in 0..100 — active fabrication, worse than omission."

WHY IT IS BEING FIXED NOW, WHILE IT CANNOT FIRE. Measured 2026-08-29 and
independently reproduced: 0 axes fabricated today, 0 of 1848 points in all
history would ever have fabricated. The branch has never fired. Kimi: "Fix 62-72
while the module is still dead so the fabrication path is disarmed before
automation makes it reachable." Step 2 wires scan() into the cycle; this lands
first and must be green before that begins.

THE ZERO IS A DATED FACT, NOT A PROPERTY — it was measured on one day, and
nothing prevents _extract_metrics returning data while _compute_axis_score
returns None. THIS FILE IS WHAT TURNS IT INTO A PROPERTY. The gating test feeds
the exact shape that has never occurred in 1848 real points and asserts nothing
is invented from it.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import cortex_scanner  # noqa: E402

OUT = BASE / "memory" / "cortex_full_state.json"
_OUT_BEFORE = hashlib.sha256(OUT.read_bytes()).hexdigest() if OUT.exists() else "ABSENT"


def _scores_for(history: dict) -> dict:
    """Run the scanner's axis-score loop over a fixed history, nothing else."""
    return cortex_scanner.axis_scores(history)


# ── the gating test Kimi named ─────────────────────────────────────────────

def test_a_null_score_never_auto_averages_even_under_dirty_input():
    """THE SHAPE THAT HAS NEVER OCCURRED IN 1848 REAL POINTS.

    score None, and several numeric metrics all inside 0..100 — a percentage, a
    count and a ratio, mutually incommensurable. The old branch would have
    published their mean, 47.3, as this axis's score.
    """
    dirty = {"DEEP_TIME_RISKS_REVIEW": [{
        "date": "2026-08-29", "score": None,
        "metrics": {"asteroid_risk_pct": 12.0, "observatories_online": 88.0,
                    "coverage_ratio": 42.0},
    }]}
    scores = _scores_for(dirty)
    assert "DEEP_TIME_RISKS_REVIEW" not in scores, (
        "a score was invented by averaging unrelated metrics — the fabrication "
        f"this item exists to disarm. Got {scores.get('DEEP_TIME_RISKS_REVIEW')}")


def test_the_specific_mean_the_old_branch_would_have_published_is_absent():
    """Pinned to the number, so a future reimplementation cannot sneak it back
    under a different shape."""
    dirty = {"AX": [{"date": "d", "score": None,
                     "metrics": {"a": 10.0, "b": 20.0, "c": 30.0}}]}
    assert _scores_for(dirty).get("AX") != 20.0
    assert "AX" not in _scores_for(dirty)


def test_a_single_metric_is_not_a_score_either():
    """One value in range is the most plausible-looking case and still not a score."""
    assert "AX" not in _scores_for(
        {"AX": [{"date": "d", "score": None, "metrics": {"only": 55.0}}]})


def test_metrics_outside_the_range_are_not_a_score_either():
    assert "AX" not in _scores_for(
        {"AX": [{"date": "d", "score": None, "metrics": {"big": 900.0}}]})


# ── the negative control ───────────────────────────────────────────────────

def test_a_real_score_is_unaffected():
    scores = _scores_for({"AX": [{"date": "d", "score": 61.4,
                                  "metrics": {"a": 10.0}}]})
    assert scores["AX"] == 61.4


def test_a_real_score_is_still_range_checked():
    """0..100 only — the existing guard must survive the change."""
    assert "AX" not in _scores_for({"AX": [{"date": "d", "score": 900.0}]})
    assert _scores_for({"AX": [{"date": "d", "score": 0.0}]})["AX"] == 0.0
    assert _scores_for({"AX": [{"date": "d", "score": 100.0}]})["AX"] == 100.0


def test_only_the_latest_point_is_read():
    """Unchanged behaviour: entries[-1]. 34-B was DROPPED — an axis with no
    score is routed to trends.insufficient, which cortex_dashboard.html renders
    at :87 as a count and at :89 by name labelled INSUFFICIENT. It does not
    vanish, and that was our misdescription, not a defect."""
    scores = _scores_for({"AX": [{"date": "old", "score": 50.0},
                                 {"date": "new", "score": 70.0}]})
    assert scores["AX"] == 70.0


def test_an_empty_or_malformed_axis_is_skipped_not_crashed():
    assert _scores_for({"A": [], "B": "not a list", "C": [{}]}) == {}


# ── the live output ────────────────────────────────────────────────────────

def test_the_live_state_file_was_not_touched():
    after = hashlib.sha256(OUT.read_bytes()).hexdigest() if OUT.exists() else "ABSENT"
    assert after == _OUT_BEFORE
