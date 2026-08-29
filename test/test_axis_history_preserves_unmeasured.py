# -*- coding: utf-8 -*-
"""ITEM 12(c) — a dated point is never deleted, and an empty one never scores.

THE DEFECT. memory/trend_tracker.py loaded the whole file, dropped every point
whose metrics were falsy, and wrote the survivors back over the original:

    238:    history = _load_history()
    241:        history[axis] = [e for e in history[axis] if e.get("metrics")]
    296:    _save_history(history)        # HISTORY_FILE.write_text(...)

Measured on the live file 2026-08-29 (sha256 1947f1fc381b...): 1848 points, 31
axes, and 7 points with falsy metrics — all dated 2026-08-29, on BODY_SCAN,
DEEP_TIME_RISKS_REVIEW, GENERAL_SELF_REVIEW, GOAL_PROGRESS_REVIEW,
HYPERCLAW_PLAN, LONG_TERM_FUTURE_REVIEW and PLANETARY_POTENTIAL_REVIEW. Those
seven axes held exactly ONE point each: written by one cycle, deleted by the
next. They have never had a history.

THE SHAPE MATTERS AND COST ME A WRONG ANSWER. The points carry "metrics": {} —
a PRESENT key holding an empty dict, not an absent key. A test written against
`"metrics" not in e` matches nothing on this data. Both shapes are covered here.

THE DECISION (Kimi, binding, 2026-08-29): PRESERVE-AND-MARK, not delete.
"Coverage data — distinguishing 'ran and found nothing' from 'did not run' — is
exactly what this system has been silently destroying. A marker makes the
emptiness explicit and searchable; deletion makes it invisible."

AND THE MARKER ALONE IS NOT ENOUGH, which is why the block is in the same file
as the preservation. No consumer of axis_history.json reads any flag — verified
across all eight readers — so nothing downstream will honour "measured": false
on its own. Two sites inside trend_tracker itself would be poisoned by a
preserved point:
    286:  "score_prev": history[axis][-2]["score"]      indexes blindly
    290:  "history_days": len(history[axis])            counts everything
Both are fixed here. _compute_trend at :114 was already correct —
`[h for h in history[-5:] if h.get("metrics")]` — the read-time skip that is the
right pattern and was already present in the same file.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from memory import trend_tracker as tt  # noqa: E402

LIVE = BASE / "memory" / "axis_history.json"
_LIVE_BEFORE = hashlib.sha256(LIVE.read_bytes()).hexdigest() if LIVE.exists() else "ABSENT"

THE_SEVEN = ["BODY_SCAN", "DEEP_TIME_RISKS_REVIEW", "GENERAL_SELF_REVIEW",
             "GOAL_PROGRESS_REVIEW", "HYPERCLAW_PLAN", "LONG_TERM_FUTURE_REVIEW",
             "PLANETARY_POTENTIAL_REVIEW"]


def _round_trip(tmp_path, history):
    """_load_history -> the filter -> _save_history, against a temp file."""
    p = tmp_path / "axis_history.json"
    p.write_text(json.dumps(history), encoding="utf-8")
    orig = tt.HISTORY_FILE
    try:
        tt.HISTORY_FILE = p
        loaded = tt._load_history()
        kept = tt.retain(loaded)
        tt._save_history(kept)
        return json.loads(p.read_text(encoding="utf-8"))
    finally:
        tt.HISTORY_FILE = orig


# ── the failing case, in both shapes ───────────────────────────────────────

def test_a_point_with_empty_metrics_survives_the_round_trip(tmp_path):
    """THE LIVE SHAPE: a present key holding {}."""
    back = _round_trip(tmp_path, {"DEEP_TIME_RISKS_REVIEW": [
        {"date": "2026-08-28", "metrics": {"co2": 1.0}, "score": 50.0},
        {"date": "2026-08-29", "metrics": {}, "score": None},
    ]})
    dates = [e["date"] for e in back["DEEP_TIME_RISKS_REVIEW"]]
    assert dates == ["2026-08-28", "2026-08-29"], (
        "the unmeasured point was deleted — this is the whole defect")


def test_a_point_with_no_metrics_key_at_all_survives_too(tmp_path):
    back = _round_trip(tmp_path, {"AX": [
        {"date": "2026-08-28", "metrics": {"x": 1.0}, "score": 50.0},
        {"date": "2026-08-29", "score": None},
    ]})
    assert [e["date"] for e in back["AX"]] == ["2026-08-28", "2026-08-29"]


def test_the_survivor_is_marked_measured_false(tmp_path):
    back = _round_trip(tmp_path, {"AX": [
        {"date": "2026-08-29", "metrics": {}, "score": None}]})
    assert back["AX"][0]["measured"] is False, (
        "preserved without a marker is just a silent empty row")


def test_a_real_point_is_marked_measured_true_and_otherwise_untouched(tmp_path):
    original = {"date": "2026-08-28", "metrics": {"co2": 1.0}, "score": 50.0,
                "score_source": "engine", "score_scale": "0-100"}
    back = _round_trip(tmp_path, {"AX": [dict(original)]})
    got = back["AX"][0]
    assert got["measured"] is True
    for k, v in original.items():
        assert got[k] == v, f"{k} was altered on a measured point"


def test_nothing_is_ever_dropped_whatever_the_shape(tmp_path):
    back = _round_trip(tmp_path, {"AX": [
        {"date": "d1", "metrics": {"a": 1}},
        {"date": "d2", "metrics": {}},
        {"date": "d3"},
        {"date": "d4", "metrics": None},
    ]})
    assert len(back["AX"]) == 4, "retain() must never shorten a series"
    assert [e["measured"] for e in back["AX"]] == [True, False, False, False]


# ── the block: a marker nobody reads must not be the only defence ──────────

def test_history_days_counts_only_measured_points():
    """:290 counted every point, so preserving would inflate it."""
    series = [{"date": "d1", "metrics": {"a": 1}}, {"date": "d2", "metrics": {}}]
    assert tt.measured_days(series) == 1


def test_score_prev_skips_unmeasured_points():
    """:286 indexed [-2] blindly, which can be an unmeasured point."""
    series = [
        {"date": "d1", "metrics": {"a": 1}, "score": 40.0},
        {"date": "d2", "metrics": {"a": 2}, "score": 50.0},
        {"date": "d3", "metrics": {}, "score": None},
    ]
    assert tt.previous_measured_score(series) == 50.0


def test_score_prev_is_none_when_there_is_no_earlier_measured_point():
    assert tt.previous_measured_score(
        [{"date": "d1", "metrics": {}, "score": None}]) is None


def test_an_axis_whose_latest_point_is_unmeasured_is_blocked():
    assert tt.axis_is_blocked([{"date": "d1", "metrics": {}, "score": None}]) is True
    assert tt.axis_is_blocked([{"date": "d1", "metrics": {"a": 1}}]) is False
    assert tt.axis_is_blocked([]) is True, "an empty series is not a measured one"


def test_a_blocked_axis_is_never_given_a_trend():
    """INSUFFICIENT_DATA, not a trend computed over nothing."""
    assert tt._compute_trend([
        {"date": "d1", "metrics": {}}, {"date": "d2", "metrics": {}}]
    ) == "INSUFFICIENT_DATA"


# ── live state ─────────────────────────────────────────────────────────────

def test_the_live_axis_history_was_not_touched():
    after = hashlib.sha256(LIVE.read_bytes()).hexdigest() if LIVE.exists() else "ABSENT"
    assert after == _LIVE_BEFORE, "memory/axis_history.json moved during the test run"
