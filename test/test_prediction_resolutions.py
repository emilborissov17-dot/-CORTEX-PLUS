# -*- coding: utf-8 -*-
"""ITEM 7.3b — the record K4 has nothing to score without.

The item's acceptance, verbatim: "a fixture writes one prediction row and one
resolution row and reads them back; the real file is byte-identical after the
fixture run." The real file does not exist yet, so byte-identical means IT MUST
STILL NOT EXIST when these tests finish — an absent file that quietly becomes a
one-row file during a test run is exactly the live-state leak the standing rule
is about, and "unchanged" has to cover creation too.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import prediction_resolutions as pr  # noqa: E402


def _state(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


_LIVE_BEFORE = _state(pr.LEDGER)


# ── the acceptance, written first ──────────────────────────────────────────

def test_one_prediction_and_one_resolution_written_and_read_back(tmp_path):
    p = tmp_path / "prediction_resolutions.jsonl"

    pred = pr.record_prediction(
        axis="CLIMATE_GLOBAL_RISK_REVIEW", domain="planet",
        predicted_centre=0.52, predicted_low=0.44, predicted_high=0.61,
        alpha=0.2, ts="2026-08-28T20:00:00+00:00", write=True, path=p)

    res = pr.record_resolution(pred, observed_value=0.57,
                               resolved_ts="2026-08-29T20:00:00+00:00",
                               write=True, path=p)

    back = pr.load(p)
    assert len(back) == 2
    assert back[0]["event"] == "PREDICTION"
    assert back[1]["event"] == "RESOLUTION"

    for field in ("ts", "axis", "domain", "predicted_centre", "predicted_low",
                  "predicted_high", "alpha"):
        assert field in back[0], f"the item names {field} on the prediction line"
    for field in ("observed_value", "resolved_ts"):
        assert field in back[1], f"the item names {field} on the resolution line"

    assert back[0] == pred and back[1] == res, "what was read back is not what was written"


def test_the_two_rows_join_and_the_band_is_judged():
    """A resolution carries its own band so one line can be scored alone."""
    pred = pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2,
                                ts="2026-08-28T20:00:00+00:00")
    res = pr.record_resolution(pred, 0.55)
    assert res["prediction_id"] == pred["prediction_id"]
    assert res["predicted_low"] == 0.4 and res["predicted_high"] == 0.6
    assert res["inside"] is True
    assert pr.record_resolution(pred, 0.99)["inside"] is False


def test_the_bounds_are_inclusive_and_decided_in_one_place():
    pred = pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2,
                                ts="2026-08-28T20:00:00+00:00")
    assert pr.record_resolution(pred, 0.4)["inside"] is True
    assert pr.record_resolution(pred, 0.6)["inside"] is True


# ── the id, and what it is for ─────────────────────────────────────────────

def test_the_id_is_deterministic_so_a_retry_does_not_open_a_second_prediction():
    a = pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2, ts="T")
    b = pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2, ts="T")
    assert a["prediction_id"] == b["prediction_id"]


def test_two_open_predictions_on_one_axis_do_not_cross_wires(tmp_path):
    """The reason the id exists. Matching by (axis, domain) and time order
    pairs these two backwards the moment both are open at once."""
    p = tmp_path / "pr.jsonl"
    first = pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2,
                                 ts="2026-08-01T00:00:00+00:00", write=True, path=p)
    second = pr.record_prediction("A", "human", 0.9, 0.8, 1.0, 0.2,
                                  ts="2026-08-02T00:00:00+00:00", write=True, path=p)
    pr.record_resolution(second, 0.95, write=True, path=p)

    j = pr.pairs(p)
    assert len(j["resolved"]) == 1 and len(j["open"]) == 1
    assert j["resolved"][0]["prediction_id"] == second["prediction_id"]
    assert j["open"][0]["prediction_id"] == first["prediction_id"]
    assert j["resolved"][0]["inside"] is True


def test_open_and_orphan_populations_are_reported_not_averaged_away(tmp_path):
    p = tmp_path / "pr.jsonl"
    pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2, ts="T1",
                         write=True, path=p)
    stray = pr.record_prediction("B", "planet", 0.5, 0.4, 0.6, 0.2, ts="T2")
    pr.record_resolution(stray, 0.5, write=True, path=p)  # its prediction never sealed

    j = pr.pairs(p)
    assert len(j["open"]) == 1
    assert len(j["orphan_resolutions"]) == 1
    assert j["coverage"] is None, "no resolved pair means no coverage, not 0%"


def test_coverage_is_none_on_an_empty_file(tmp_path):
    assert pr.pairs(tmp_path / "nope.jsonl")["coverage"] is None


# ── refusals ───────────────────────────────────────────────────────────────

def test_an_inside_out_band_is_refused():
    with pytest.raises(ValueError, match="inside out"):
        pr.record_prediction("A", "human", 0.5, 0.9, 0.1, 0.2)


def test_resolving_something_that_is_not_a_prediction_is_refused():
    with pytest.raises(ValueError, match="not a prediction row"):
        pr.record_resolution({"event": "RESOLUTION"}, 0.5)


# ── dry run ────────────────────────────────────────────────────────────────

def test_both_writers_are_dry_by_default(tmp_path):
    p = tmp_path / "pr.jsonl"
    pred = pr.record_prediction("A", "human", 0.5, 0.4, 0.6, 0.2, path=p)
    pr.record_resolution(pred, 0.5, path=p)
    assert not p.exists(), "a dry run created the ledger"
    assert pr.load(p) == []


# ── live state ─────────────────────────────────────────────────────────────

def test_the_real_ledger_is_unchanged_including_still_not_existing():
    after = _state(pr.LEDGER)
    assert after == _LIVE_BEFORE, (
        f"{pr.LEDGER} moved during the test run: {_LIVE_BEFORE} -> {after}. "
        f"An absent file that becomes a one-row file is not 'unchanged'.")
