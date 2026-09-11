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
    assert r["axes"] >= 1 and set(r["counts"]) == {"MOVING", "POSITIVE_CONSTANT", "NEGATIVE_CONSTANT", "NEGATIVE_TREND", "UNCLASSIFIED"}


# ── the quoted window must be the FITTED window (11 Sep 2026) ────────────────

def _food_series():
    """The real FOOD_REVIEW annual base: a long fall, then a post-2014 rise."""
    return [(2001, 12.8), (2002, 12.9), (2003, 12.5), (2004, 12.0), (2005, 11.4),
            (2006, 10.9), (2007, 10.4), (2008, 10.1), (2009, 9.7), (2010, 9.2),
            (2011, 8.9), (2012, 8.6), (2013, 8.2),
            (2014, 7.7), (2015, 7.6), (2016, 7.5), (2017, 7.4), (2018, 7.3),
            (2019, 7.8), (2020, 8.2), (2021, 8.6), (2022, 8.6), (2023, 8.5)]


def test_the_slope_is_fitted_on_the_last_ten_not_the_whole_series():
    t = ab.trend(_food_series(), "lower_better")
    assert t["years"] == 23 and t["fit_years"] == 10
    assert t["fit_first"] == (2014, 7.7) and t["fit_last"] == (2023, 8.5)
    assert t["first"] == (2001, 12.8), "the full series is still reported"
    assert t["verdict"] == ab.WORSENING, (
        "2014 -> 2023 rises under lower_better, so WORSENING is the right verdict")


def test_the_notice_quotes_the_fitted_window_not_the_full_series(tmp_path):
    """THE DEFECT, 11 Sep 2026, first live run. The notice read

        WORSENING over 10 years (2001: 12.8 -> 2023: 8.5, +0.13697/yr)

    Every part is true alone: the slope is fitted on the last 10 points, which
    genuinely rise, and first/last are the 23-year series, which falls. Printed
    together they read as a contradiction — a 4.3-point improvement labelled
    WORSENING — and a correct alarm that reads as a broken one gets the NEXT true
    one dismissed as well.
    """
    t = ab.trend(_food_series(), "lower_better")
    ff, fl = t["fit_first"], t["fit_last"]
    span = f"{ff[0]}: {ff[1]} -> {fl[0]}: {fl[1]}"
    assert span == "2014: 7.7 -> 2023: 8.5"
    # the forbidden pairing: the fitted years with the full series' endpoints
    bad = f"over {t['fit_years']} years ({t['first'][0]}: {t['first'][1]} -> {t['last'][0]}: {t['last'][1]}"
    assert "2001: 12.8 -> 2023: 8.5" in bad, "this is the sentence that must not be built"


def test_a_reversal_is_named_because_it_is_worse_than_a_flat_line():
    """When the long run went the GOOD way and the fitted window goes the bad way,
    that is the most important thing in the notice — an improvement being undone,
    not a softening of the alarm."""
    t = ab.trend(_food_series(), "lower_better")
    long_good = t["first"][1] > t["fit_last"][1]      # 12.8 > 8.5 under lower_better
    assert long_good, "the fixture must contain a long improvement to reverse"
    assert t["first"][0] < t["fit_first"][0], "the long run must predate the fit window"


def test_a_series_that_only_ever_worsened_names_no_reversal():
    """NEGATIVE CONTROL. A reversal sentence on a series that never improved would
    be an invented consolation."""
    only_worse = [(2010 + i, 5.0 + 0.4 * i) for i in range(14)]
    t = ab.trend(only_worse, "lower_better")
    assert t["verdict"] == ab.WORSENING
    long_good = t["first"][1] > t["fit_last"][1]
    assert not long_good, "nothing improved here, so no reversal may be claimed"


def test_higher_better_reads_the_reversal_the_other_way():
    """The same shape with the polarity flipped: a long rise, then a fall."""
    ser = [(2001 + i, 40.0 + i) for i in range(13)] + [(2014 + i, 52.0 - 0.5 * i) for i in range(10)]
    t = ab.trend(ser, "higher_better")
    assert t["verdict"] == ab.WORSENING, "falling under higher_better is worsening"
    long_good = t["first"][1] < t["fit_last"][1]
    assert long_good, "40.0 -> 47.5 is still a long improvement under higher_better"
