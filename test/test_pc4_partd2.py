# -*- coding: utf-8 -*-
"""
D2 adds a replay buffer, a fixed reward mass, and a HELD-OUT out-of-range set that is
the primary metric. Each of those is a new way to get a good number dishonestly.

The one that matters most: if a held-out prompt ever reaches the buffer or a training
batch, the primary metric stops being generalisation and becomes training accuracy,
and every number in the report still looks plausible. That is checked here by what the
loop is actually HANDED, not by reading the source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.pc4_partc import TRAIN_MAX, vocabulary  # noqa: E402
from tools.pc4_partd import LEAKAGE_SLACK, OUT_OF_RANGE_D, reward_for, verify  # noqa: E402
from tools.pc4_partd2 import (EVAL_ROUNDS, HELD_OUT_OOR, NOT_EVALUABLE,  # noqa: E402
                              REWARD_MASS, scale_to_reward_mass)


# ── the held-out set ────────────────────────────────────────────────────────
def test_held_out_prompts_are_disjoint_from_the_paid_ones():
    """THE TEST THE WHOLE PRIMARY METRIC RESTS ON."""
    assert not (set(HELD_OUT_OOR) & set(OUT_OF_RANGE_D))


def test_every_held_out_prompt_is_actually_out_of_range():
    for a, b in HELD_OUT_OOR:
        assert a + b > TRAIN_MAX


def test_every_held_out_prompt_can_be_asked():
    """11+3 is in the brief and is NOT here, because the input vocabulary covers
    0..10 and there is no symbol for eleven. A prompt the model cannot be shown must
    not be scored as a prompt it got wrong."""
    v = vocabulary("c2")
    for a, b in HELD_OUT_OOR:
        assert a in v["num"] and b in v["num"], f"{a}+{b} cannot be encoded"
    for a, b in NOT_EVALUABLE:
        assert a not in v["num"] or b not in v["num"], (
            f"{a}+{b} IS representable — it belongs in HELD_OUT_OOR, not in the "
            f"not-evaluable list")


def test_no_held_out_prompt_ever_enters_the_buffer_or_a_training_batch():
    """THE LEAK TEST. It spies on what the loop is handed rather than reading the
    source: every row that reaches weighted_loss is captured and checked against the
    held-out prompts' own encodings."""
    torch = pytest.importorskip("torch")
    import tools.pc4_partd2 as d2

    vocab = vocabulary("c2")
    from tools.pc4_partc import EQ, END, PAD, build_data
    train, held_in, oor, *_ = build_data(vocab)
    toks = [PAD, END, EQ] + sorted({t for p, y in train + held_in + oor for t in p + y})
    toks = list(dict.fromkeys(toks))
    stoi = {t: i for i, t in enumerate(toks)}
    itos = {i: t for t, i in stoi.items()}
    V = len(stoi)

    forbidden = {(vocab["num"][a], vocab["ops"]["+"], vocab["num"][b], EQ)
                 for a, b in HELD_OUT_OOR}
    seen_rows = []

    real = d2.weighted_loss

    def spy(model, rows, weights, stoi_, V_):
        seen_rows.extend(rows)
        return real(model, rows, weights, stoi_, V_)

    # An untrained model at k=2 samples nothing correct, trips "no exploration, no
    # signal" at round 0, and never builds a batch at all - so the spy would see an
    # empty list and the test would pass by vacuum. Forcing the verifier to accept
    # everything makes the reward flow, fills the buffer, and puts the routing under
    # maximum pressure: if a held-out prompt can reach a batch, it reaches it here.
    real_verify = d2.verify
    d2.verify = lambda completion, a, b, mark: True
    d2.weighted_loss = spy
    try:
        model = d2.build_model(V, 4 + d2.MAX_NEW + 2, 1)
        d2.run_loop2(model, vocab, train, held_in, stoi, itos, V,
                     rounds=2, k=2, seed=1, include_out_of_range=True,
                     lr=1e-4, label="main")
    finally:
        d2.weighted_loss = real
        d2.verify = real_verify

    assert seen_rows, "no training batch was built — the spy never fired"
    for prompt, _ in seen_rows:
        assert tuple(prompt) not in forbidden, (
            f"a HELD-OUT prompt reached a training batch: {prompt}")


def test_the_held_out_set_is_evaluated_at_the_rounds_the_brief_names():
    assert EVAL_ROUNDS == (0, 5, 10, 15, 20)


# ── the reward mass ─────────────────────────────────────────────────────────
def test_rewarded_rows_carry_about_twenty_percent_of_the_batch():
    """D's signal was 0.2% of the rows by accident. Here it is 20% by construction,
    and this is the arithmetic that makes it so."""
    for n_rewarded in (1, 5, 50, 500):
        for n_in_range in (102, 200):
            ws = scale_to_reward_mass([1.0] * n_rewarded, n_in_range)
            share = sum(ws) / (sum(ws) + n_in_range)
            assert abs(share - REWARD_MASS) < 1e-9, share


def test_the_relative_reward_structure_survives_the_rescaling():
    """A 1.5 must still be worth exactly 1.5 times a 1.0 after scaling, or the bonus
    for answering above ten has been quietly flattened."""
    ws = scale_to_reward_mass([1.0, 1.5, 1.0], 102)
    assert abs(ws[1] / ws[0] - 1.5) < 1e-9
    assert abs(ws[2] / ws[0] - 1.0) < 1e-9


def test_an_empty_reward_set_does_not_blow_up_or_invent_weight():
    assert scale_to_reward_mass([], 102) == []
    assert scale_to_reward_mass([0.0, 0.0], 102) == [0.0, 0.0]


def test_the_mass_is_the_pre_registered_one():
    assert REWARD_MASS == 0.20


# ── everything D pinned, still pinned ───────────────────────────────────────
def test_the_verifier_and_reward_are_unchanged_from_D():
    """D2 is a new pre-registration, not a re-tuning: the verifier and the reward
    are imported from D rather than redefined, so they cannot drift."""
    assert verify(["QG"] * 12, 10, 2, "QG") is True
    assert verify(["QX"] * 12, 10, 2, "QG") is False
    assert reward_for(True, 10, 2) == 1.5
    assert reward_for(True, 5, 5) == 1.0
    assert reward_for(False, 10, 2) == 0.0


def test_the_leakage_rule_is_unchanged_from_D():
    assert LEAKAGE_SLACK == 0.05


def test_the_paid_prompts_are_unchanged_from_D():
    assert OUT_OF_RANGE_D == [(10, 2), (7, 5), (9, 4), (10, 4)]


# ── the field names must not assert what the code does not check ────────────
@pytest.mark.parametrize("path", ["claude/reports/PC4_PARTD_samples.jsonl",
                                  "claude/reports/PC4_PARTD2_samples.jsonl"])
def test_n_marks_counts_marks_and_n_tokens_counts_tokens(path):
    """Added 6 Sep after an independent recount found `n_marks` counting non-marks:
    3,673 completions in D and 3,957 in D2 contain a token that is not the mark, and
    the field counted them. That made the pre-registered leakage rule
    'P(output >= 11 MARKS)' run as P(length >= 11).

    This reads the committed evidence rather than the code, so it fails if the files
    are ever regenerated by a version that reintroduces the conflation."""
    import json
    from collections import Counter
    p = Path(path)
    if not p.exists():
        pytest.skip(f"{path} not present")
    recs = [json.loads(l) for l in p.open(encoding="utf-8")]
    mark = Counter(t for r in recs if r["a"] + r["b"] <= TRAIN_MAX
                   for t in r["completion"]).most_common(1)[0][0]
    for r in recs:
        c = r["completion"]
        assert r["n_tokens"] == len(c), r
        assert r["n_marks"] == sum(1 for t in c if t == mark), r
    assert any(r["n_marks"] != r["n_tokens"] for r in recs), (
        "no row distinguishes the two fields - this test would pass vacuously")
