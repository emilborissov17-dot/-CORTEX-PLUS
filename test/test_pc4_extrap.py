# -*- coding: utf-8 -*-
"""
The PC4 harness must not be able to leak the answer it is testing for.

An extrapolation test is worthless if a target above 10 reaches training, if the
symbols carry order the model could read off, or if the out-of-range set overlaps
what was trained. Each of those would produce a high score for the wrong reason,
and the score is the whole output.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.pc4_extrap import (MAXV, OUT_OF_RANGE, TRAIN_MAX, build_data,  # noqa: E402
                              vocabulary)


@pytest.fixture(scope="module")
def data():
    v = vocabulary()
    return (v,) + build_data(v)


def test_no_training_target_is_ever_above_ten(data):
    """THE INVARIANT THE WHOLE TEST RESTS ON."""
    _, _, _, _, raw_tr, _, _ = data
    assert max(r for _, _, _, r in raw_tr) <= TRAIN_MAX
    assert all(0 <= r <= TRAIN_MAX for _, _, _, r in raw_tr)


def test_every_out_of_range_result_HAS_a_token(data):
    """The spec's own 9+4=13 and 10+5=15 have no symbol in a 0..12 vocabulary: a
    perfect rule could not emit them, so scoring them would measure the vocabulary.
    The range covers the test set."""
    v = data[0]
    for a, b in OUT_OF_RANGE:
        assert a + b in v["num"], f"{a}+{b}={a + b} has no token"
    assert max(a + b for a, b in OUT_OF_RANGE) <= MAXV


def test_the_out_of_range_results_were_never_trained(data):
    _, _, _, _, raw_tr, _, raw_oo = data
    trained_targets = {r for _, _, _, r in raw_tr}
    for _, _, _, r in raw_oo:
        assert r not in trained_targets, f"result {r} was a training target"


def test_no_out_of_range_PROMPT_appears_in_training(data):
    """Not just the answer - the question too."""
    _, _, _, _, raw_tr, _, raw_oo = data
    seen = {(a, s, b) for a, s, b, _ in raw_tr}
    for a, s, b, _ in raw_oo:
        assert (a, s, b) not in seen, f"{a}{s}{b} was trained"


def test_held_in_and_train_do_not_overlap(data):
    _, _, _, _, raw_tr, raw_in, _ = data
    assert not ({(a, s, b) for a, s, b, _ in raw_tr}
                & {(a, s, b) for a, s, b, _ in raw_in})
    assert len(raw_in) == 30


def test_the_symbols_carry_no_order(data):
    """Tokens are shuffled, so alphabetical order must not track numeric order —
    otherwise the model could read the answer off the symbol itself."""
    v = data[0]
    toks = [v["num"][i] for i in range(MAXV + 1)]
    assert toks != sorted(toks), "the token sequence is alphabetically ordered"
    assert len(set(toks)) == len(toks), "a token is reused for two values"
    assert v["ops"]["+"] not in toks and v["ops"]["-"] not in toks


def test_the_mapping_is_deterministic():
    assert vocabulary()["num"] == vocabulary()["num"]
    assert vocabulary(1)["num"] != vocabulary(2)["num"]


def test_the_shuffled_control_really_breaks_the_mapping(data):
    """The memorisation control must not accidentally keep most pairs intact."""
    import random
    _, train, _, _, _, _, _ = data
    ys = [y for _, y in train]
    shuffled = ys[:]
    random.Random(20260906 + 999).shuffle(shuffled)
    kept = sum(1 for a, b in zip(ys, shuffled) if a == b)
    assert kept < 0.25 * len(ys), f"{kept}/{len(ys)} targets survived the shuffle"
