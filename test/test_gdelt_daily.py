# -*- coding: utf-8 -*-
"""
GDELT_DAILY wiring — built, tested, and deliberately NOT activated.

The registration must not go live before the 03:04 cycle, so one test asserts it is
still absent. That test is meant to be flipped tomorrow, by hand, in the same commit
that adds the entry — which is the point: activation becomes a decision somebody makes
rather than something that drifts in.

The 3-day counts below are REAL, measured from the real files on 2026-09-07. They are
recorded here as a fixture rather than re-fetched, because a guard test must not
depend on a rate-limited third party.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.gdelt_daily import (EXTRACT_PATH, INDICATOR, UNITS,  # noqa: E402
                             count_from_zip, is_registered, recent_days,
                             registration_entry, series)
from tools.first_bet import series_moved  # noqa: E402

# measured 2026-09-07 from https://data.gdeltproject.org/events/<day>.export.CSV.zip
REAL = {
    "20260903": {"rows": 117020, "sqldate_match": 114504, "zip_bytes": 7348025},
    "20260904": {"rows": 107037, "sqldate_match": 104882, "zip_bytes": 6747569},
    "20260905": {"rows": 66878, "sqldate_match": 65683, "zip_bytes": 3983991},
}


def _fake_zip(day: str, n_match: int, n_other: int = 0) -> bytes:
    """A hand-written export in the real shape: 58 TSV columns, no header."""
    rows = []
    for i in range(n_match):
        c = [""] * 58
        c[0], c[1] = str(1000000 + i), day
        rows.append("\t".join(c))
    for i in range(n_other):
        c = [""] * 58
        c[0], c[1] = str(2000000 + i), "20160905"      # an old event, reported today
        rows.append("\t".join(c))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{day}.export.CSV", "\n".join(rows) + "\n")
    return buf.getvalue()


# ── 1. the series moved across the last 3 available days ────────────────────
def test_series_moved_is_true_on_the_real_three_day_payload():
    """THE PRECONDITION FIRST BET REQUIRES. Real counts, real files."""
    counts = [REAL[d]["rows"] for d in ("20260903", "20260904", "20260905")]
    assert counts == [117020, 107037, 66878]
    assert series_moved(counts) is True
    filtered = [REAL[d]["sqldate_match"] for d in ("20260903", "20260904", "20260905")]
    assert series_moved(filtered) is True, "it must move under EITHER definition"


# ── 2. the gate resolves GDELT_DAILY once the registration is present ───────
def test_the_gate_resolves_the_indicator_with_the_staged_registration(tmp_path, monkeypatch):
    """The staged entry, injected into a TEMP trends file — the live one is untouched.

    The chain is judge -> _default_resolver -> _resolves -> evaluator.ground_truth,
    which reads cortex_memory/abstractions/trends.json[axis] and takes values[-1].
    """
    import evaluator
    from core.proposal_intake import judge

    counts = [REAL[d]["rows"] for d in ("20260903", "20260904", "20260905")]
    staged = tmp_path / "trends_latest.json"
    staged.write_text(json.dumps(registration_entry(counts)), encoding="utf-8")
    monkeypatch.setattr(evaluator, "TRENDS_PATH", str(staged))

    from datetime import timedelta
    v = judge({"indicator": INDICATOR, "expected_delta": -5000.0,
               "deadline": (date.today() + timedelta(days=2)).isoformat()},
              cadence_check=lambda i, d: None,
              scale_check=lambda i, d: (None, "injected"))
    assert v["verdict"] == "ADMITTED", v


def test_without_the_registration_the_gate_refuses_it_by_name(tmp_path, monkeypatch):
    """The other half: the refusal must NAME the missing series, not shrug."""
    import evaluator
    from core.proposal_intake import judge
    empty = tmp_path / "trends_latest.json"
    empty.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(evaluator, "TRENDS_PATH", str(empty))
    from datetime import timedelta
    v = judge({"indicator": INDICATOR, "expected_delta": -5000.0,
               "deadline": (date.today() + timedelta(days=2)).isoformat()},
              cadence_check=lambda i, d: None,
              scale_check=lambda i, d: (None, "injected"))
    assert v["verdict"] == "REFUSED"
    assert "indicator" in v["missing"]
    assert INDICATOR in v["why"]


# ── 3. NOT ACTIVATED — this is the tripwire ─────────────────────────────────
def test_the_registration_is_NOT_live_yet():
    """Flip this tomorrow, in the same commit that adds the entry.

    Until then it proves cortex_memory/abstractions/trends.json has not been touched, which is the
    condition the 03:04 cycle has to run under for tonight's gate report to be
    comparable with this morning's.
    """
    import evaluator
    live = json.loads(Path(evaluator.TRENDS_PATH).read_text(encoding="utf-8"))
    assert live, "trends.json is empty - this test would pass vacuously"
    assert INDICATOR not in live
    assert is_registered() is False, (
        "GDELT_DAILY is now live in trends.json. If that was deliberate, "
        "invert this assertion in the same commit; if not, the registration leaked "
        "in before the cycle.")


def test_metric_details_does_not_carry_it_either():
    """metric_details is not its own file - it is a key inside
    snapshots/master/goal_score_latest.json (evaluator.py:22). The first version of
    this test looked for memory/metric_details.json, did not find it, and SKIPPED -
    passing while checking nothing."""
    import evaluator
    snap = json.loads(Path(evaluator.GOAL_SNAP_PATH).read_text(encoding="utf-8"))
    details = snap.get("metric_details") or {}
    assert details, "metric_details is empty - this test would pass vacuously"
    assert INDICATOR not in details


# ── 4. the counting, and the trap in it ─────────────────────────────────────
def test_the_row_count_is_the_event_count():
    raw = _fake_zip("20260903", n_match=1200)
    assert count_from_zip(raw, "20260903", sqldate_filter=False) == 1200


def test_the_sqldate_filter_changes_the_number_and_is_not_a_default_nobody_chose():
    """~2% of a daily export is older events reported today. Both counts are
    defensible; they are different, and which one is meant must be chosen."""
    raw = _fake_zip("20260903", n_match=1000, n_other=25)
    assert count_from_zip(raw, "20260903", sqldate_filter=False) == 1025
    assert count_from_zip(raw, "20260903", sqldate_filter=True) == 1000
    ratio = REAL["20260903"]["sqldate_match"] / REAL["20260903"]["rows"]
    assert 0.95 < ratio < 0.99, "the real files sit around 98%"


def test_series_uses_the_injected_fetcher_and_never_the_network():
    days = ["20260903", "20260904"]
    fake = {d: _fake_zip(d, n_match=REAL[d]["sqldate_match"] // 1000) for d in days}
    got = series(days, fetcher=lambda d: fake[d])
    assert [d for d, _ in got] == days
    assert [c for _, c in got] == [114, 104]


# ── 5. the registration entry has the shape evaluator expects ───────────────
def test_the_registration_entry_is_a_list_whose_last_value_is_the_reading():
    e = registration_entry([117020, 107037, 66878])
    assert list(e) == [INDICATOR]
    assert isinstance(e[INDICATOR], list)
    assert e[INDICATOR][-1] == 66878, "ground_truth takes values[-1]"


def test_recent_days_never_asks_for_today():
    """A day's file is published ~07:00 UTC the NEXT day; today returns 404."""
    days = recent_days(3, today=date(2026, 9, 7))
    assert days == ["20260904", "20260905", "20260906"]
    assert date.today().strftime("%Y%m%d") not in recent_days(3)


def test_the_extract_path_and_units_are_recorded():
    assert "export.CSV" in EXTRACT_PATH and "row count" in EXTRACT_PATH
    assert "events per day" in UNITS
