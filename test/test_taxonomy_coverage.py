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
