# -*- coding: utf-8 -*-
"""test/test_taxonomy_coverage.py — the SEEN rule of tools/taxonomy_coverage.py.

The failure this file exists to stop: a subcategory counted SEEN on a number
whose observation date nobody knows. So the refusals come first — an undated
key, a year-resolution key, a processing timestamp, an unknown source class —
and the mutation test proves the date guard is load-bearing: with it removed,
the same synthetic subcategory flips to SEEN, so the first assertion would fail.

Synthetic evidence only; the live memory/ files never decide a test here.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from core import taxonomy as tx  # noqa: E402
import ask  # noqa: E402
import taxonomy_coverage as tc  # noqa: E402

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
SPELLINGS = ask.load_spellings()


def _row(value=1.0, date="2026-09-30", shape="iso_date", age=1.0, cls="independent"):
    obs = {"date": date, "shape": shape, "age_days": age} if date else {"missing": "none"}
    return {"via": "t", "value": value, "obs": obs, "org": "x", "class": cls, "class_why": ""}


def _cov(evidence: dict, mapping: dict) -> dict:
    km = {k: {"subcategory": s} for k, s in mapping.items()}
    out = tc.coverage(km, evidence, tx.load())
    return {s["id"]: s for s in out["subcategories"]} | {"_totals": out["totals"]}


# ── refusals ───────────────────────────────────────────────────────────────
def test_a_key_without_an_observation_date_cannot_make_a_subcategory_seen():
    ev = {"k": [_row(date=None)]}                     # value yes, independent yes, date NO
    s = _cov(ev, {"k": "C1.1"})["C1.1"]
    assert s["seen"] is False
    assert s["fails"] == [tc.FAIL_CHANGE]


def test_mutation_without_the_date_guard_the_same_subcategory_would_be_seen(monkeypatch):
    """If is_change_key stopped requiring a date, the test above must fail.
    This is that mutation, applied: the undated key now flips the verdict."""
    monkeypatch.setattr(tc, "is_change_key", lambda rows: any(tc._num(r.get("value")) for r in rows))
    s = _cov({"k": [_row(date=None)]}, {"k": "C1.1"})["C1.1"]
    assert s["seen"] is True


def test_a_year_resolution_date_is_not_a_change_key():
    s = _cov({"k": [_row(date="2025-12-31", shape="year", age=1.0)]}, {"k": "C1.1"})["C1.1"]
    assert tc.FAIL_CHANGE in s["fails"]


def test_a_day_older_than_the_limit_is_not_a_change_key():
    s = _cov({"k": [_row(age=tc.CHANGE_MAX_AGE_DAYS + 0.1)]}, {"k": "C1.1"})["C1.1"]
    assert tc.FAIL_CHANGE in s["fails"]


def test_unknown_and_self_reported_are_not_independent():
    for cls in ("unknown", "self_reported"):
        s = _cov({"k": [_row(cls=cls)]}, {"k": "C1.1"})["C1.1"]
        assert s["fails"] == [tc.FAIL_SOURCE], cls


def test_a_key_without_a_value_fails_state():
    s = _cov({"k": [_row(value=None)]}, {"k": "C1.1"})["C1.1"]
    assert tc.FAIL_STATE in s["fails"]
    s = _cov({"k": [_row(value=float("nan"))]}, {"k": "C1.1"})["C1.1"]
    assert tc.FAIL_STATE in s["fails"]


def test_a_subcategory_with_no_key_names_that():
    s = _cov({}, {})["A1.3"]
    assert s["fails"] == [tc.FAIL_NO_KEY]


def test_all_three_conditions_make_it_seen():
    assert _cov({"k": [_row()]}, {"k": "C1.1"})["C1.1"]["seen"] is True


# ── dates come from registered spellings only ───────────────────────────────
def test_a_processing_timestamp_is_never_an_observation_date():
    rec = {"ts": "2026-09-30T00:00:00+00:00", "timestamp": "2026-09-30", "generated_at": "2026-09-30"}
    assert "missing" in tc.date_in_record(rec, SPELLINGS, None, NOW)


def test_a_registered_spelling_is_read():
    out = tc.date_in_record({"co2_date": "2026-09-20", "co2_ppm": 425.0}, SPELLINGS, None, NOW)
    assert out["spelling"] == "co2_date" and out["shape"] == "iso_date" and out["date"] == "2026-09-20"


def test_a_year_map_is_read_at_the_keys_own_field_not_its_oldest_entry():
    rec = {"_observed_years": {"a": "2017", "b": "2024"}}
    assert tc.date_in_record(rec, SPELLINGS, "b", NOW)["date"] == "2024-12-31"
    assert "missing" in tc.date_in_record(rec, SPELLINGS, "c", NOW)


# ── domain E is separate ─────────────────────────────────────────────────────
def test_a_seen_system_subcategory_never_enters_the_world_total():
    t = _cov({"e": [_row()], "w": [_row()]}, {"e": "E1.3", "w": "C1.1"})["_totals"]
    assert t["world"]["seen"] == 1 and t["world"]["of"] == 105
    assert t["system_E"]["seen"] == 1 and t["system_E"]["of"] == 18
    assert "E" not in t["world"]["domains"]
    assert t["overall"] == {**t["overall"], "seen": 2, "of": 123}


def test_selftest_controls_hold():
    r = tc.selftest()
    assert r["ok"], r["controls"]


@pytest.mark.parametrize("bad", ["", "{", "[]"])
def test_an_unreadable_key_map_is_a_refusal_not_an_empty_report(tmp_path, monkeypatch, bad):
    p = tmp_path / "taxonomy_key_map.json"
    p.write_text(bad, encoding="utf-8")
    monkeypatch.setattr(tx, "KEY_MAP", p)
    with pytest.raises(tc.Refused):
        tc.run(NOW)


# ── ATOMS n/105 ─────────────────────────────────────────────────────────────
def test_atoms_count_world_only_and_skips_retracted(tmp_path, monkeypatch):
    import json as _j
    from core import atoms as at
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "ret.jsonl")
    monkeypatch.setattr(ci, "ACCEPTED", tmp_path / "acc.jsonl")
    root = tmp_path / "atoms"
    rec = {"axis": "TAXONOMY:C2.1", "key": "forest_area_pct", "value": 31.0, "unit": "pct", "url": "https://x",
           "quote": "31.0", "subcategory": "C2.1", "place": "WLD", "period": "2023"}
    row = {"card_key": "k1", "judged_utc": "t", "verdict": "ACCEPTED", "record": rec}
    ci.ACCEPTED.write_text(_j.dumps(row) + chr(10), encoding="utf-8")
    at.write(row, root=root)
    t1 = tc.atoms_totals(tx.load(), root=root)
    assert t1["world"] == {"with_atoms": 1, "of": 105} and t1["system_E"]["with_atoms"] == 0
    ci.retract("k1", reason="test", by="test")
    assert tc.atoms_totals(tx.load(), root=root)["world"]["with_atoms"] == 0


# ── C-OC-2 Part 4a: the three conditions hold on ONE key ─────────────────────
def test_c51_split_across_two_keys_is_not_seen():
    """The live case of 1 Oct 2026: C5.1 had CHANGE on quakes.quake_m45_count
    (dated, class unknown) and SOURCE on usgs_quakes_daily (independent, no
    date). Under the one-key rule that is NOT SEEN, and the reason says why."""
    ev = {"quakes.quake_m45_count": [_row(cls="unknown")],
          "usgs_quakes_daily": [_row(date=None, cls="independent")]}
    s = _cov(ev, {"quakes.quake_m45_count": "C5.1", "usgs_quakes_daily": "C5.1"})["C5.1"]
    assert s["seen"] is False
    assert s["fails"] == [tc.FAIL_SPLIT]


def test_one_key_holding_all_three_is_seen():
    ev = {"k": [_row()], "other": [_row(date=None, cls="unknown")]}
    assert _cov(ev, {"k": "C1.1", "other": "C1.1"})["C1.1"]["seen"] is True


def test_mutation_any_key_per_condition_would_call_the_split_case_seen(monkeypatch):
    monkeypatch.setattr(tc, "key_holds_all", lambda rows: True)
    ev = {"quakes.quake_m45_count": [_row(cls="unknown")],
          "usgs_quakes_daily": [_row(date=None, cls="independent")]}
    assert _cov(ev, {"quakes.quake_m45_count": "C5.1", "usgs_quakes_daily": "C5.1"})["C5.1"]["seen"] is True


# ── C-OC-2 Part 4b: CURRENT from the period's own granularity ────────────────
from datetime import date as _date  # noqa: E402

TODAY = _date(2026, 10, 1)


@pytest.mark.parametrize("period,expected", [
    ("2026-08-17", True),            # 45 days before 2026-10-01
    ("2026-08-16", False),           # 46 days
    ("2026-08-17T23:59:00", True),   # an ISO datetime is day-dated
    ("2026-06", True),               # last day 2026-06-30 -> 93 days
    ("2026-05", False),              # last day 2026-05-31 -> 123 days
    ("2023", True),                  # this year - 3
    ("2022", False),                 # this year - 4
    ("1790857400000", False),        # epoch milliseconds: granularity unknown
    ("Q3 2026", False),              # unknown shape
])
def test_current_bounds_and_off_by_one(period, expected):
    assert tc.period_is_current(period, TODAY) is expected


def test_month_bound_off_by_one_exactly():
    # 2026-06-03's month ends 2026-06-30; 120 days after is 2026-10-28
    assert tc.period_is_current("2026-06", _date(2026, 10, 28)) is True
    assert tc.period_is_current("2026-06", _date(2026, 10, 29)) is False


def test_granularity_is_read_from_the_period_never_declared():
    assert tc.period_granularity("2024") == "year"
    assert tc.period_granularity("2024-07") == "month"
    assert tc.period_granularity("2024-07-09") == "day"
    assert tc.period_granularity("2024-07-09T10:00:00+00:00") == "day"
    assert tc.period_granularity("1790857400000") is None


def test_current_counts_world_atoms_only_and_skips_retracted(tmp_path, monkeypatch):
    import json as _j
    from core import atoms as at
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "ret.jsonl")
    monkeypatch.setattr(ci, "ACCEPTED", tmp_path / "acc.jsonl")
    root = tmp_path / "atoms"
    def put(key, sub, period, ck):
        rec = {"axis": f"TAXONOMY:{sub}", "key": key, "value": 1.0, "unit": "u", "url": "https://x/" + key,
               "quote": "1.0", "subcategory": sub, "place": "WLD", "period": period}
        row = {"card_key": ck, "judged_utc": "t", "verdict": "ACCEPTED", "record": rec}
        with ci.ACCEPTED.open("a", encoding="utf-8") as fh:
            fh.write(_j.dumps(row) + chr(10))
        at.write(row, root=root)
    put("a", "C2.1", "2024", "k1")      # current
    put("b", "C3.3", "2019", "k2")      # stale
    t = tc.current_totals(tx.load(), TODAY, root=root)
    assert t["world"] == {"current": 1, "of": 105}
    ci.retract("k1", reason="test", by="test")
    assert tc.current_totals(tx.load(), TODAY, root=root)["world"]["current"] == 0
