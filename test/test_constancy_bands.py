# -*- coding: utf-8 -*-
"""test/test_constancy_bands.py — the constant is a signal (Emil, 11 Sep 2026).

An unchanged number is still observed and recorded. Unchanged AND near the goal
is a POSITIVE constant (held). Unchanged AND far from the goal is NON-PROGRESS
and a STAGNATION notice. Movement is judged against the axis's own cadence, so
an annual series is not called stagnant for being annual. Notices are weekly.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import alarm_bands as ab  # noqa: E402

NOW = _dt.date(2026, 9, 11)


def _files(tmp_path, details, history, cadence):
    g = tmp_path / "goal.json"; g.write_text(json.dumps({"metric_details": details}), encoding="utf-8")
    h = tmp_path / "hist.json"; h.write_text(json.dumps(history), encoding="utf-8")
    c = tmp_path / "cad.json"; c.write_text(json.dumps({"indicators": cadence}), encoding="utf-8")
    return dict(goal_path=g, history_path=h, cadence_path=c, now=NOW)


def _series(axis_days, values):
    """axis history: one entry per (days_ago, value)."""
    return [{"date": (NOW - _dt.timedelta(days=d)).isoformat(), "metrics": {"m": v}} for d, v in zip(axis_days, values)]


def _detail(axis, score, target=1.0):
    return {"axis": axis, "current": 0.3, "target": target, "direction": "higher_better", "score": score}


def test_far_from_goal_and_still_is_non_progress(tmp_path):
    kw = _files(tmp_path, {"m": _detail("REFUGEES", 0.03)},
                {"REFUGEES": _series([500, 400, 300, 200, 100, 1], [29.4] * 6)}, {"REFUGEES": {"cadence": "annual"}})
    r = ab.constancy(**kw)
    assert r["counts"]["NEGATIVE_CONSTANT"] == 1 and r["stagnation"][0]["axis"] == "REFUGEES"
    assert "NON-PROGRESS" in r["stagnation"][0]["why"]


def test_near_goal_and_still_is_a_positive_constant_not_an_alarm(tmp_path):
    kw = _files(tmp_path, {"m": _detail("DIGNITY", 0.95)},
                {"DIGNITY": _series([500, 400, 300, 200, 100, 1], [0.95] * 6)}, {"DIGNITY": {"cadence": "annual"}})
    r = ab.constancy(**kw)
    assert r["counts"]["POSITIVE_CONSTANT"] == 1 and r["stagnation"] == []


def test_an_annual_series_is_not_stagnant_for_being_annual(tmp_path):
    """Unchanged for 200 nights, far from goal — but the window for annual is 400 days and
    the history is 200 days: UNCLASSIFIED, never NEGATIVE_CONSTANT."""
    kw = _files(tmp_path, {"m": _detail("POVERTY", 0.2)},
                {"POVERTY": _series([200, 150, 100, 50, 1], [10.4] * 5)}, {"POVERTY": {"cadence": "annual"}})
    r = ab.constancy(**kw)
    assert r["counts"]["UNCLASSIFIED"] == 1 and r["stagnation"] == []


def test_a_daily_series_that_moved_last_week_is_moving(tmp_path):
    kw = _files(tmp_path, {"m": _detail("CO2", 0.2)},
                {"CO2": _series([60, 40, 20, 5, 1], [427.0, 427.1, 427.2, 427.3, 427.3])}, {"CO2": {"cadence": "daily"}})
    r = ab.constancy(**kw)
    assert r["rows"][0]["class"] == "MOVING" and r["rows"][0]["days_since_change"] == 5


def test_a_daily_series_frozen_for_two_months_far_from_goal_is_stagnant(tmp_path):
    kw = _files(tmp_path, {"m": _detail("CONFLICT", 0.1)},
                {"CONFLICT": _series([120, 90, 61, 30, 1], [56, 56, 56, 56, 56])}, {"CONFLICT": {"cadence": "daily"}})
    r = ab.constancy(**kw)
    assert r["rows"][0]["class"] == "NEGATIVE_CONSTANT"


def test_stagnation_notice_goes_out_once_per_axis_and_says_non_progress(tmp_path):
    kw = _files(tmp_path, {"m": _detail("REFUGEES", 0.03)},
                {"REFUGEES": _series([500, 1], [29.4, 29.4])}, {"REFUGEES": {"cadence": "annual"}})
    r = ab.constancy(**kw)
    sent = []
    assert ab.send_stagnation(r, sender=lambda a, t: sent.append((a, t))) == 1
    assert sent[0][0] == "REFUGEES" and "ЗАСТОЙ" in sent[0][1] and "Ненапредък" in sent[0][1]


def test_missing_files_never_raise(tmp_path):
    r = ab.constancy(goal_path=tmp_path / "no.json", history_path=tmp_path / "no.json", cadence_path=tmp_path / "no.json")
    assert r["axes"] == 0 and r["stagnation"] == []


def test_the_live_repo_classifies_without_error():
    r = ab.constancy()
    assert r["axes"] >= 1 and set(r["counts"]) == {"MOVING", "POSITIVE_CONSTANT", "NEGATIVE_CONSTANT", "UNCLASSIFIED"}
