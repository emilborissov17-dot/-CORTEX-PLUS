# -*- coding: utf-8 -*-
"""C: the quiet phase reads the layer that actually moves.

THE CASE. core/consolidation.py read only cortex_memory/archive/*/signals.json. Those
are assembled in step 24 from auto_levels detail — the ANNUAL layer. World Bank
indicators do not change nightly, so the same value sat at both ends of the window:
gdp_per_capita_usd = 14405.8 in cycle_000050 (25 Aug) and in cycle_000065 (12 Sep).
That is where 46 of 48 "constant_series" rejections came from. The series were not
flat because the world is still; the module was reading the one layer that cannot
move inside thirty days.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import consolidation as K  # noqa: E402

TODAY = date(2026, 9, 12)


def _write(tmp_path, rows):
    p = tmp_path / "daily_tier.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def _rising(n=30, metric="quakes.quake_m45_count", start=10.0, step=0.5):
    return [{"date": (TODAY - timedelta(days=n - 1 - i)).isoformat(),
             "indicator": metric, "value": start + i * step} for i in range(n)]


def test_a_daily_file_becomes_a_series_that_reaches_the_fit(tmp_path):
    p = _write(tmp_path, _rising())
    cycles = K.read_daily_tier(window_days=30, path=p, today=TODAY)
    series = K.build_series(cycles)
    key = ("DAILY", "quakes.quake_m45_count")
    assert key in series, "the daily layer must produce a series"
    pts = series[key]
    assert len(pts) == 30
    fit = K._fit(pts)
    assert fit is not None, "the series must reach _fit, not die in the filters"
    assert fit["slope"] > 0 and fit["sigma"] >= 0
    assert len(pts) >= K.MIN_POINTS and fit["span_days"] >= K.MIN_SPAN_DAYS


def test_two_rows_for_one_day_do_not_double_the_weight(tmp_path):
    """Two readings of one day are not two observations of a trend. Last wins."""
    rows = _rising()
    dup = dict(rows[-1]); dup["value"] = 999.0          # same day, later line
    p = _write(tmp_path, rows + [dup])
    series = K.build_series(K.read_daily_tier(30, p, TODAY))
    pts = series[("DAILY", "quakes.quake_m45_count")]
    assert len(pts) == 30, "a repeated day must not add a point"
    assert pts[-1][1] == 999.0, "the LAST row for a day wins"
    days = [d for d, _ in pts]
    assert len(days) == len(set(days)), "one point per day"


def test_a_row_without_a_numeric_value_is_skipped(tmp_path):
    """A missing reading is not a zero, and a flag is not a measurement."""
    rows = _rising(n=6) + [
        {"date": TODAY.isoformat(), "indicator": "bad.none", "value": None},
        {"date": TODAY.isoformat(), "indicator": "bad.text", "value": "n/a"},
        {"date": TODAY.isoformat(), "indicator": "bad.bool", "value": True},
        {"date": TODAY.isoformat(), "indicator": "bad.missing"},
        {"indicator": "bad.nodate", "value": 1.0},
        {"date": "not-a-date", "indicator": "bad.baddate", "value": 1.0},
        {"date": TODAY.isoformat(), "value": 5.0},
    ]
    p = _write(tmp_path, rows)
    series = K.build_series(K.read_daily_tier(30, p, TODAY))
    metrics = {m for _, m in series}
    assert not any(m.startswith("bad.") for m in metrics), f"a non-numeric row entered: {metrics}"
    assert ("DAILY", "quakes.quake_m45_count") in series


def test_a_boolean_is_not_a_number():
    """isinstance(True, int) is True in Python; a flag entering a least-squares fit
    as 1.0 is exactly the true-shaped nonsense this module must refuse."""
    assert isinstance(True, int)
    rows = [{"date": TODAY.isoformat(), "indicator": "m", "value": True}]
    assert K.read_daily_tier(30, _write_tmp(rows), TODAY) == []


def _write_tmp(rows):
    import tempfile
    p = Path(tempfile.mkdtemp()) / "d.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def test_the_window_applies_to_the_daily_layer_too(tmp_path):
    """Not a back door to a longer history."""
    old = [{"date": (TODAY - timedelta(days=400)).isoformat(), "indicator": "m", "value": 1.0}]
    p = _write(tmp_path, old + _rising(n=5, metric="m", start=2.0))
    got = K.read_daily_tier(window_days=30, path=p, today=TODAY)
    days = [c["date"] for c in got]
    assert all(d >= TODAY - timedelta(days=30) for d in days), "a row outside the window entered"
    assert len(days) == 5


def test_a_missing_or_unreadable_file_is_empty_not_an_exception(tmp_path):
    assert K.read_daily_tier(30, tmp_path / "nope.jsonl", TODAY) == []
    junk = tmp_path / "junk.jsonl"
    junk.write_text("{not json\n\n[]\n1\n", encoding="utf-8")
    assert K.read_daily_tier(30, junk, TODAY) == []


def test_the_daily_layer_merges_before_the_filters(tmp_path):
    """It must face MIN_POINTS / MIN_SPAN_DAYS / sigma like any other series — a
    layer that skipped them would be privileged, not measured."""
    p = _write(tmp_path, _rising(n=3, metric="tooshort.series"))
    rec = K.run(write=False, window_days=30, archive=tmp_path / "no_archive",
                today=TODAY, daily=p)
    assert rec["rejected"]["too_few_points"] >= 1, "the daily layer must be filtered too"


def test_no_model_and_no_network_still_holds():
    """The FORBIDDEN list is the whole reason this step may run unattended."""
    assert K.imported_forbidden(BASE / "core" / "consolidation.py") == set()


def test_a_test_cannot_read_the_live_daily_tier():
    """The autouse fixture in test/conftest.py must redirect the path.

    This is the guard for the defect that produced this fixture: run() reading the
    real memory/daily_tier.jsonl inside tests that had built a sealed world, so five
    of them saw 4 hypotheses where their own fixture says 0.
    """
    live = BASE / "memory" / "daily_tier.jsonl"
    assert K.DAILY_TIER != live, "conftest must redirect consolidation.DAILY_TIER away from memory/"
    rec = K.run(write=False, window_days=30, archive=BASE / "no_such_archive",
                today=TODAY)
    assert rec["emitted"] == 0, "a sealed world must stay sealed inside a test"
