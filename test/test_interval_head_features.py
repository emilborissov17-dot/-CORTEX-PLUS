# -*- coding: utf-8 -*-
"""
test/test_interval_head_features.py — THE FEATURES MUST BE REAL FEATURES.

A feature is real if it is available at prediction time. A feature that is the
answer wearing a hat looks identical on a scoreboard and is worthless in
production, so the properties that matter here are:

  * prev1/2/3 use STRICTLY EARLIER rows of the same step, never the row itself
    and never a later one
  * an absent value is 0 AND A FLAG, never 0 alone — writing 0 with no flag
    tells the head "this step took no time last cycle", which is a measurement,
    and a false one
  * the protocol is UNCHANGED: same whole-step holdout, same flat baseline, same
    hashed control, same seed. A new arm compared under a new protocol is not a
    comparison.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import interval_head as ih   # noqa: E402

N = {name: i for i, name in enumerate(ih.ROW_FEATURE_NAMES)}


def row(ts, key, value):
    return {"ts": ts, "key": key, "value": value, "target": "step_seconds"}


# --------------------------------------------------------------------------- #
# prev1/2/3 look only backwards
# --------------------------------------------------------------------------- #

def test_the_previous_durations_are_strictly_earlier():
    rows = [
        row("2026-08-16T03:00:00+00:00", "a", 10.0),
        row("2026-08-17T03:00:00+00:00", "a", 20.0),
        row("2026-08-18T03:00:00+00:00", "a", 30.0),
        row("2026-08-19T03:00:00+00:00", "a", 40.0),
    ]
    F, _names, _cov = ih.row_features(rows)
    # newest first: for the 4th row those are 30, 20, 10
    assert math.isclose(F[3][N["prev1_log"]], math.log(30.0), rel_tol=1e-9)
    assert math.isclose(F[3][N["prev2_log"]], math.log(20.0), rel_tol=1e-9)
    assert math.isclose(F[3][N["prev3_log"]], math.log(10.0), rel_tol=1e-9)
    assert F[3][N["prev_count"]] == 3


def test_a_rows_own_value_is_never_among_its_previous_durations():
    """The single way this feature could be the target in disguise."""
    rows = [row("2026-08-16T03:00:00+00:00", "a", 999.0)]
    F, _n, _c = ih.row_features(rows)
    assert F[0][N["prev1_log"]] == 0.0
    assert F[0][N["has_prev"]] == 0.0
    assert not math.isclose(F[0][N["prev1_log"]], math.log(999.0))


def test_a_later_row_never_leaks_backwards():
    rows = [
        row("2026-08-16T03:00:00+00:00", "a", 10.0),
        row("2026-08-17T03:00:00+00:00", "a", 5000.0),
    ]
    F, _n, _c = ih.row_features(rows)
    assert F[0][N["prev_count"]] == 0, "the first row saw the future"
    assert math.isclose(F[1][N["prev1_log"]], math.log(10.0), rel_tol=1e-9)


def test_the_history_is_per_step_not_global():
    rows = [
        row("2026-08-16T03:00:00+00:00", "a", 10.0),
        row("2026-08-16T03:05:00+00:00", "b", 900.0),
        row("2026-08-17T03:00:00+00:00", "a", 20.0),
    ]
    F, _n, _c = ih.row_features(rows)
    assert math.isclose(F[2][N["prev1_log"]], math.log(10.0), rel_tol=1e-9), (
        "step 'a' inherited step 'b' duration")


def test_rows_out_of_timestamp_order_are_still_handled_by_time():
    """The log is appended to by several writers; the order on disk is not a
    guarantee, and a feature that trusts it would silently read the future."""
    rows = [
        row("2026-08-19T03:00:00+00:00", "a", 40.0),
        row("2026-08-16T03:00:00+00:00", "a", 10.0),
    ]
    F, _n, _c = ih.row_features(rows)
    assert F[1][N["prev_count"]] == 0
    assert math.isclose(F[0][N["prev1_log"]], math.log(10.0), rel_tol=1e-9)


# --------------------------------------------------------------------------- #
# Absent is zero AND a flag
# --------------------------------------------------------------------------- #

def test_every_may_be_missing_feature_has_a_presence_flag():
    assert "has_prev" in ih.ROW_FEATURE_NAMES
    assert "has_ram" in ih.ROW_FEATURE_NAMES


def test_a_missing_value_is_flagged_not_merely_zeroed():
    rows = [row("2026-08-16T03:00:00+00:00", "a", 10.0)]
    F, _n, _c = ih.row_features(rows)
    assert F[0][N["prev1_log"]] == 0.0
    assert F[0][N["has_prev"]] == 0.0, (
        "a zero with no flag tells the head the step took no time last cycle")


def test_the_coverage_of_each_optional_feature_is_reported():
    """A feature absent everywhere is not a feature, and a table that does not
    say so implies it was one."""
    rows = [row("2026-08-16T03:00:00+00:00", "a", 10.0),
            row("2026-08-17T03:00:00+00:00", "a", 20.0)]
    _F, _n, cov = ih.row_features(rows)
    assert "prev_durations_present" in cov
    assert "ram_free_present" in cov
    assert cov["prev_durations_present"] == 0.5


# --------------------------------------------------------------------------- #
# Hour-of-day is on a circle; the ordinal counts within a cycle
# --------------------------------------------------------------------------- #

def test_the_hour_is_a_circle_so_2300_and_0100_are_near():
    a = ih.row_features([row("2026-08-16T23:00:00+00:00", "a", 1.0)])[0][0]
    b = ih.row_features([row("2026-08-16T01:00:00+00:00", "a", 1.0)])[0][0]
    far = ih.row_features([row("2026-08-16T12:00:00+00:00", "a", 1.0)])[0][0]
    def d(u, v):
        return math.dist([u[N["hour_sin"]], u[N["hour_cos"]]],
                         [v[N["hour_sin"]], v[N["hour_cos"]]])
    assert d(a, b) < d(a, far), "23:00 and 01:00 are not near each other"


def test_the_ordinal_restarts_with_each_cycle():
    rows = [
        row("2026-08-16T03:00:00+00:00", "a", 1.0),
        row("2026-08-16T03:10:00+00:00", "b", 1.0),
        # a gap larger than CYCLE_GAP_SEC starts a new cycle
        row("2026-08-17T03:00:00+00:00", "a", 1.0),
    ]
    F, _n, cov = ih.row_features(rows)
    assert [F[i][N["step_ordinal"]] for i in range(3)] == [1.0, 2.0, 1.0]
    assert cov["cycles_detected"] == 2
    assert [F[i][N["cycles_since_boot"]] for i in range(3)] == [0.0, 0.0, 1.0]


def test_the_cycle_gap_is_a_measured_constant_not_a_guess():
    """4,343 s to 10,293 s with nothing in between, on the live log. Any
    threshold inside that gap yields the same partition."""
    assert ih.CYCLE_GAP_SEC == 7200
    assert 4343 < ih.CYCLE_GAP_SEC < 10293


# --------------------------------------------------------------------------- #
# The protocol did not move
# --------------------------------------------------------------------------- #

def test_the_features_widen_the_input_and_change_nothing_else():
    src = (REPO / "core" / "interval_head.py").read_text(encoding="utf-8")
    assert "HOLDOUT_FRACTION = 0.25" in src
    assert "SEED = 20260821" in src
    assert "EPOCHS = 400" in src
    assert "def split_by_step" in src
    assert "flat_baseline" in src


def test_the_row_features_are_appended_not_substituted():
    """The arm must be embedding PLUS features; replacing the embedding would be
    a different experiment reported under the same name."""
    src = (REPO / "core" / "interval_head.py").read_text(encoding="utf-8")
    assert "np.hstack([X, F])" in src


def test_all_four_arms_exist_and_are_the_same_protocol():
    labels = [a for a, _ in ih.ARMS]
    assert len(labels) == 4
    kws = [k for _, k in ih.ARMS]
    assert {(k["force_fallback"], k["row_feats"]) for k in kws} == {
        (False, False), (True, False), (False, True), (True, True)}


def test_compare_does_not_write_training_rows_by_default():
    """A comparison is not a training run and must not append four rows to
    memory/interval_head_runs.jsonl as though it were."""
    src = (REPO / "core" / "interval_head.py").read_text(encoding="utf-8")
    assert "def compare(write: bool = False)" in src


def test_the_table_says_plainly_when_nothing_beats_the_baseline():
    fake = {"ts": "x", "flat_baseline_heldout": 8.4337, "any_arm_beats_flat": False,
            "arms": [{"arm": "A", "heldout": 16.7, "coverage": 0.11,
                      "width_sec": 16.0, "beats_flat": False,
                      "embedding": "e", "row_feature_coverage": None}]}
    text = ih.compare_table(fake)
    assert "LOSES to flat" in text
    assert "NO ARM BEATS THE FLAT BASELINE" in text
    assert "Goodhart" in text, (
        "the table does not say why it is not being tuned until it wins")
