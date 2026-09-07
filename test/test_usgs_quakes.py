# -*- coding: utf-8 -*-
"""
USGS_QUAKE_M45_DAILY — wiring tests, and the tripwire flipped in the same commit that
registers it.

The counts below are REAL, measured 2026-09-07 from the fdsnws count API. They are
recorded rather than re-fetched so a guard test never depends on a third party being up.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.usgs_quakes import (EXTRACT_PATH, INDICATOR, MIN_MAG, UNITS,  # noqa: E402
                             complete_days, count_url, day_bounds, is_registered,
                             parse_count, registration_entry, series)
from tools.first_bet import series_moved  # noqa: E402

# measured 2026-09-07 via fdsnws/event/1/count, minmagnitude=4.5, UTC calendar days
REAL = {"2026-09-02": 17, "2026-09-03": 24, "2026-09-04": 12,
        "2026-09-05": 13, "2026-09-06": 15}
LIVE_SERIES = [12, 13, 15]          # the three complete days registered today


# ── the count moved, and it has no weekly signature ─────────────────────────
def test_the_count_moved_across_the_last_three_complete_days():
    assert LIVE_SERIES == [REAL["2026-09-04"], REAL["2026-09-05"], REAL["2026-09-06"]]
    assert series_moved(LIVE_SERIES) is True


def test_there_is_no_weekend_collapse_which_is_the_reason_for_the_switch():
    """GDELT halves at weekends (117,020 Thu / 107,037 Fri / 66,878 Sat), so beating
    persistence there is calendar arithmetic. 2026-09-04..06 is Fri/Sat/Sun and reads
    12 / 13 / 15 — the weekend is the HIGH end, not a collapse."""
    fri, sat, sun = REAL["2026-09-04"], REAL["2026-09-05"], REAL["2026-09-06"]
    assert date(2026, 9, 4).weekday() == 4 and date(2026, 9, 6).weekday() == 6
    weekend = (sat + sun) / 2
    weekdays = (REAL["2026-09-02"] + REAL["2026-09-03"] + fri) / 3
    assert 0.5 < weekend / weekdays < 2.0, (
        f"weekend {weekend} vs weekday {weekdays}: if this ever fails, the premise of "
        f"debuting here instead of on GDELT is gone")


# ── the day boundary ────────────────────────────────────────────────────────
def test_the_day_is_a_UTC_CALENDAR_day_not_a_rolling_window():
    """THE TRAP THAT DECIDED THE DESIGN. The obvious feed, 4.5_day.geojson, is a
    rolling 24 h window ending whenever you ask — measured 2026-09-07 07:17 UTC it
    spanned 09-06 10:32 to 09-07 05:50. A bet sealed against a rolling window cannot
    be graded, because the window moves before grading."""
    s, e = day_bounds(date(2026, 9, 6))
    assert s == "2026-09-06T00:00:00" and e == "2026-09-07T00:00:00"
    url = count_url(date(2026, 9, 6))
    assert "starttime=2026-09-06T00%3A00%3A00" in url
    assert "endtime=2026-09-07T00%3A00%3A00" in url
    assert "4.5_day.geojson" not in url


def test_today_is_never_counted_because_it_is_still_running():
    days = complete_days(3, today=date(2026, 9, 7))
    assert days == [date(2026, 9, 4), date(2026, 9, 5), date(2026, 9, 6)]
    assert date(2026, 9, 7) not in days
    assert datetime.now(timezone.utc).date() not in complete_days(3)


def test_the_threshold_is_in_the_query_not_applied_afterwards():
    """'count' must be M4.5+ ONLY. If the threshold were applied after fetching, an
    all_day feed would silently include M1.0 events."""
    assert MIN_MAG == 4.5
    assert "minmagnitude=4.5" in count_url(date(2026, 9, 6))


# ── parsing ─────────────────────────────────────────────────────────────────
def test_parse_count_reads_count_and_not_maxAllowed():
    """maxAllowed is a QUOTA that looks like a count. A reader grabbing the first
    integer gets 20000."""
    assert parse_count('{"count":15,"maxAllowed":20000}') == 15
    assert parse_count({"count": 0, "maxAllowed": 20000}) == 0


def test_a_truncated_response_is_an_error_not_a_number():
    with pytest.raises(ValueError, match="truncated"):
        parse_count({"count": 20000, "maxAllowed": 20000})


def test_a_response_without_count_raises_rather_than_defaulting():
    with pytest.raises(ValueError, match="no 'count'"):
        parse_count({"maxAllowed": 20000})


def test_series_uses_the_injected_fetcher_and_never_the_network():
    days = complete_days(3, today=date(2026, 9, 7))
    got = series(days, fetcher=lambda d: REAL[d.isoformat()])
    assert [c for _, c in got] == LIVE_SERIES


# ── the gate ────────────────────────────────────────────────────────────────
def test_the_gate_ADMITS_the_indicator_now_that_it_is_registered():
    """THE TRIPWIRE, FLIPPED. Registered in this same commit, so this reads the LIVE
    trends.json — no temp file, no injection."""
    from core.proposal_intake import judge
    v = judge({"indicator": INDICATOR, "expected_delta": 3.0,
               "deadline": (date.today() + timedelta(days=1)).isoformat()},
              cadence_check=lambda i, d: None,
              scale_check=lambda i, d: (None, "injected"))
    assert v["verdict"] == "ADMITTED", v


def test_the_registration_IS_live_and_carries_the_real_series():
    """Was `assert is_registered() is False` until this commit. Flipped here, with the
    registration, deliberately and by hand."""
    import evaluator
    live = json.loads(Path(evaluator.TRENDS_PATH).read_text(encoding="utf-8"))
    assert INDICATOR in live, "the registration did not land"
    assert live[INDICATOR] == LIVE_SERIES
    assert is_registered() is True


def test_ground_truth_returns_the_last_value():
    import evaluator
    v, trail = evaluator.ground_truth(INDICATOR)
    assert v == LIVE_SERIES[-1] == 15, (v, trail)


def test_the_extract_path_and_units_are_recorded():
    assert "count" in EXTRACT_PATH and "minmagnitude=4.5" in EXTRACT_PATH
    assert "UTC day" in UNITS and "4.5" in UNITS


# ── the cadence declaration, found missing by the dry run ───────────────────
def test_the_indicator_has_a_declared_cadence():
    """FOUND BY THE DRY RUN, NOT BY THIS SUITE. Every gate test above injects
    cadence_check, so none of them could see that USGS_QUAKE_M45_DAILY had no entry in
    config/indicator_cadence.json — the first real dry run refused all 8 candidates
    with 'has no declared cadence'. An injected collaborator hides exactly the wiring
    it stands in for."""
    cfg = json.loads((REPO / "config" / "indicator_cadence.json")
                     .read_text(encoding="utf-8"))
    entry = cfg["indicators"].get(INDICATOR)
    assert entry, f"{INDICATOR} has no cadence declaration"
    assert entry["cadence"] == "daily"
    assert entry["last_observed_from"] == "quakes.last_date"


def test_the_snapshot_carries_the_observation_date_the_cadence_points_at():
    snap = json.loads((REPO / "snapshots" / "master" /
                       "global_indicators_latest.json").read_text(encoding="utf-8"))
    q = snap.get("quakes") or {}
    assert q.get("last_date"), "quakes.last_date is missing — cadence cannot resolve"
    assert q.get("min_magnitude") == MIN_MAG
    assert isinstance(q.get("quake_m45_count"), int)


def test_the_gate_admits_with_the_REAL_cadence_check_not_an_injected_one():
    """The end-to-end that the injected tests could not do."""
    from core.proposal_intake import judge
    v = judge({"indicator": INDICATOR, "expected_delta": 3.0,
               "deadline": (date.today() + timedelta(days=1)).isoformat()},
              scale_check=lambda i, d: (None, "injected: scale needs 7 observations"))
    assert v["verdict"] == "ADMITTED", v
