# -*- coding: utf-8 -*-
"""
Part C asks whether a COMPOSITIONAL output representation lifts the ceiling that
Part A2 hit. The harness must not lift it by accident.

The specific ways this experiment could report a number for the wrong reason:
an answer above ten reaching training; an out-of-range prompt being trained; a
tally answer longer than ten marks appearing in the corpus; the symbols leaking
their own order; or the order probe returning a correlation it did not measure.
One test each.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.pc4_partc import (MAX_RESULT, OUT_OF_RANGE, TRAIN_MAX,  # noqa: E402
                             build_data, encode_result, order_probe, spearman,
                             vocabulary)


@pytest.fixture(scope="module", params=["c1", "c2"])
def rep(request):
    v = vocabulary(request.param)
    return (request.param, v) + build_data(v)


def test_no_training_result_is_ever_above_ten(rep):
    """THE INVARIANT THE WHOLE EXPERIMENT RESTS ON."""
    _, _, _, _, _, raw_tr, _, _ = rep
    assert max(r for _, _, _, r in raw_tr) <= TRAIN_MAX
    assert all(0 <= r <= TRAIN_MAX for _, _, _, r in raw_tr)


def test_the_out_of_range_prompts_were_never_trained(rep):
    _, _, _, _, _, raw_tr, _, raw_oo = rep
    seen = {(a, s, b) for a, s, b, _ in raw_tr}
    for a, s, b, _ in raw_oo:
        assert (a, s, b) not in seen, f"{a}{s}{b} was trained"


def test_held_in_and_train_do_not_overlap(rep):
    _, _, _, _, _, raw_tr, raw_in, _ = rep
    assert not ({(a, s, b) for a, s, b, _ in raw_tr}
                & {(a, s, b) for a, s, b, _ in raw_in})
    assert len(raw_in) == 30


def test_the_symbols_carry_no_order(rep):
    """Shuffled, so alphabetical order must not track numeric order - otherwise the
    answer can be read off the symbol instead of induced."""
    _, v = rep[0], rep[1]
    toks = [v["num"][i] for i in range(TRAIN_MAX + 1)]
    assert toks != sorted(toks), "the symbols are in alphabetical order"
    assert len(set(toks)) == len(toks), "a symbol stands for two values"


def test_the_mapping_is_deterministic(rep):
    name = rep[0]
    assert vocabulary(name)["num"] == vocabulary(name)["num"]
    assert vocabulary(name, 1)["num"] != vocabulary(name, 2)["num"]


# --- C1: composition, not a new symbol --------------------------------------
def test_c1_never_trains_a_two_symbol_answer():
    v = vocabulary("c1")
    train, _, _, _, _, _ = build_data(v)
    assert {len(y) for _, y in train} == {1}, "a composed answer reached training"


def test_c1_out_of_range_answers_are_exactly_two_symbols():
    v = vocabulary("c1")
    _, _, oor, _, _, _ = build_data(v)
    assert {len(y) for _, y in oor} == {2}


def test_c1_every_piece_of_an_out_of_range_answer_HAS_been_emitted_before():
    """The whole premise of C1. The model is not being asked for a new symbol -
    only for two old ones in an order it has never produced."""
    v = vocabulary("c1")
    train, _, oor, _, _, _ = build_data(v)
    emitted = {t for _, y in train for t in y}
    for _, y in oor:
        for t in y:
            assert t in emitted, f"{t} was never emitted in training"


def test_c1_the_ten_marker_is_the_symbol_for_ten():
    v = vocabulary("c1")
    assert v["ten"] == v["num"][TRAIN_MAX]
    assert encode_result(v, 12) == [v["ten"], v["num"][2]]
    assert encode_result(v, 15) == [v["ten"], v["num"][5]]
    assert encode_result(v, 10) == [v["num"][10]]


# --- C2: a length never produced --------------------------------------------
def test_c2_never_trains_more_than_ten_marks():
    v = vocabulary("c2")
    train, _, _, _, _, _ = build_data(v)
    assert max(len(y) for _, y in train) <= TRAIN_MAX


def test_c2_out_of_range_lengths_were_never_trained():
    v = vocabulary("c2")
    train, _, oor, _, _, _ = build_data(v)
    trained = {len(y) for _, y in train}
    for _, y in oor:
        assert len(y) not in trained, f"length {len(y)} was trained"
        assert TRAIN_MAX < len(y) <= MAX_RESULT


def test_c2_uses_exactly_one_output_symbol():
    v = vocabulary("c2")
    _, _, oor, _, _, _ = build_data(v)
    train, _, _, _, _, _ = build_data(v)
    assert {t for _, y in train + oor for t in y} == {v["mark"]}


def test_c2_zero_is_the_empty_answer():
    assert encode_result(vocabulary("c2"), 0) == []


# --- the order probe must measure what it claims ----------------------------
def test_spearman_is_right_at_the_ends():
    assert spearman([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert abs(spearman([1, 1, 1, 1], [1, 2, 3, 4])) <= 1.0


def test_the_probe_recovers_an_order_that_is_really_there():
    """A embedding table built ON a line must read as a line."""
    stoi = {f"s{v}": v for v in range(11)}
    E = np.zeros((11, 64))
    rng = np.random.default_rng(0)
    E += rng.normal(0, 0.01, E.shape)
    for v in range(11):
        E[v, 0] = v * 1.0                      # the line, in dimension 0
    out = order_probe(E, stoi, {v: f"s{v}" for v in range(11)})
    assert out["abs_spearman"] >= 0.99


def test_the_probe_does_not_invent_an_order_that_is_not_there():
    stoi = {f"s{v}": v for v in range(11)}
    rng = np.random.default_rng(1)
    E = rng.normal(0, 1.0, (11, 64))
    out = order_probe(E, stoi, {v: f"s{v}" for v in range(11)})
    assert out["abs_spearman"] < 0.9, out["abs_spearman"]


def test_the_probe_only_reads_symbols_it_was_given():
    """Rows that never took a gradient must not enter the correlation."""
    stoi = {f"s{v}": v for v in range(16)}
    E = np.zeros((16, 8))
    for v in range(11):
        E[v, 0] = v
    E[11:, 0] = 999.0                          # untrained rows, wildly off the line
    out = order_probe(E, stoi, {v: f"s{v}" for v in range(11)})
    assert out["n_values"] == 11
    assert out["abs_spearman"] >= 0.99


def test_out_of_range_pairs_are_the_ones_the_spec_named():
    assert OUT_OF_RANGE[:3] == [(10, 2), (9, 4), (10, 5)]
    assert max(a + b for a, b in OUT_OF_RANGE) == MAX_RESULT
