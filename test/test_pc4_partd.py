# -*- coding: utf-8 -*-
"""
Part D pays a bonus for a particular kind of answer, which is exactly the setting
where a harness can produce a triumphant number for the wrong reason.

The ways it could, one test each: a verifier that counts length instead of checking
the symbols; a bonus that reaches a wrong answer; a control that quietly received the
prompts it exists to be denied; a leakage check that would not fire when leakage
happens; and a thread count left to the environment, which Part C proved changes the
result (88dafd5).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.pc4_partc import TRAIN_MAX, vocabulary  # noqa: E402
from tools.pc4_partd import (LEAKAGE_SLACK, MAX_NEW, N_THREADS,  # noqa: E402
                             OUT_OF_RANGE_D, leakage_breached, pin_threads,
                             reward_for, verify)

MARK = "QG"
OTHER = "QX"


# ── the verifier ────────────────────────────────────────────────────────────
def test_verifier_rejects_the_right_length_with_the_wrong_symbols():
    """THE TEST THE BRIEF NAMES FIRST. Twelve of the wrong symbol is not twelve —
    it is a sequence that happens to be twelve long."""
    assert verify([MARK] * 12, 10, 2, MARK) is True
    assert verify([OTHER] * 12, 10, 2, MARK) is False
    assert verify([MARK] * 11 + [OTHER], 10, 2, MARK) is False
    assert verify([OTHER] + [MARK] * 11, 10, 2, MARK) is False


def test_verifier_counts_and_does_not_look_up():
    for a in range(0, 11):
        for b in range(0, 11):
            assert verify([MARK] * (a + b), a, b, MARK) is True
            assert verify([MARK] * (a + b + 1), a, b, MARK) is False
            if a + b:
                assert verify([MARK] * (a + b - 1), a, b, MARK) is False


def test_zero_is_the_empty_completion():
    assert verify([], 0, 0, MARK) is True
    assert verify([MARK], 0, 0, MARK) is False


# ── the reward ──────────────────────────────────────────────────────────────
def test_the_bonus_never_reaches_a_wrong_sample():
    """THE SECOND TEST THE BRIEF NAMES. A wrong answer to an out-of-range prompt
    must not out-earn a wrong answer to an in-range one, or the model is being paid
    for the attempt rather than the result."""
    for a, b in [(10, 2), (7, 5), (9, 4), (10, 4), (3, 4), (0, 0)]:
        assert reward_for(False, a, b) == 0.0


def test_the_bonus_is_paid_only_above_ten():
    assert reward_for(True, 3, 4) == 1.0
    assert reward_for(True, 5, 5) == 1.0          # exactly ten is not above ten
    assert reward_for(True, 10, 2) == 1.5
    assert reward_for(True, 10, 4) == 1.5


def test_every_reward_is_one_of_exactly_three_values():
    seen = {reward_for(ok, a, b)
            for ok in (True, False) for a in range(11) for b in range(11)}
    assert seen == {0.0, 1.0, 1.5}


# ── the control ─────────────────────────────────────────────────────────────
def test_the_control_never_receives_an_out_of_range_prompt():
    """THE THIRD TEST THE BRIEF NAMES. A control that quietly got the prompts would
    invalidate the whole result while every number still looked plausible."""
    pytest.importorskip("torch")   # the guard applies wherever torch exists
    import tools.pc4_partd as d
    seen = {}

    def spy(model, prompts, stoi, itos, k, temperature, mark, rng_seed, chunk=512):
        seen.setdefault("prompts", []).extend(prompts)
        return [[[] for _ in range(k)] for _ in prompts]

    vocab = vocabulary("c2")
    oor_symbols = {vocab["num"][a] for a, _ in OUT_OF_RANGE_D}
    # the prompts the control must never be handed, by their symbol pairs
    forbidden = {(vocab["num"][a], vocab["num"][b]) for a, b in OUT_OF_RANGE_D}

    real = d.sample_completions
    d.sample_completions = spy
    try:
        _run_tiny_control(d)
    finally:
        d.sample_completions = real

    got = {(p[0], p[2]) for p in seen.get("prompts", [])}
    assert got, "the control ran no prompts at all — the spy never fired"
    assert not (got & forbidden), f"the control was handed {got & forbidden}"
    assert oor_symbols  # the symbols exist; the pairs are what must be absent


def _run_tiny_control(d):
    """One round of the control loop with a stubbed sampler and a stub model."""
    import torch
    vocab = vocabulary("c2")
    train, held_in, oor, *_ = __import__("tools.pc4_partc", fromlist=["x"]).build_data(vocab)
    from tools.pc4_partc import END, EQ, PAD
    toks = [PAD, END, EQ] + sorted({t for p, y in train + held_in + oor for t in p + y})
    toks = list(dict.fromkeys(toks))
    stoi = {t: i for i, t in enumerate(toks)}
    itos = {i: t for t, i in stoi.items()}
    model = d.build_model(len(stoi), 4 + MAX_NEW + 2, 1)
    with torch.no_grad():
        d.run_loop(model, vocab, train[:4], held_in[:2], stoi, itos, len(stoi),
                   rounds=0, k=2, seed=1, include_out_of_range=False,
                   label="control")


def test_include_out_of_range_false_is_asserted_not_just_documented():
    """The guard inside run_loop, reached directly."""
    import inspect

    import tools.pc4_partd as d
    src = inspect.getsource(d.run_loop)
    assert "the control was given out-of-range prompts" in src
    assert "if not include_out_of_range:" in src


# ── the leakage check ───────────────────────────────────────────────────────
def test_leakage_fires_on_a_synthetic_rise():
    """THE FOURTH TEST THE BRIEF NAMES. Built to fail before it is trusted: a series
    that rises past baseline + 0.05 must trip it."""
    assert leakage_breached([0.10, 0.11, 0.16], baseline=0.10) is True
    assert leakage_breached([0.10, 0.10, 0.15], baseline=0.10) is False
    assert leakage_breached([0.0, 0.06], baseline=0.0) is True
    assert leakage_breached([0.0, 0.05], baseline=0.0) is False


def test_the_slack_is_the_pre_registered_one():
    assert LEAKAGE_SLACK == 0.05


def test_leakage_is_measured_on_in_range_prompts_only():
    """The check is about answers to questions whose answer is at most ten. Counting
    out-of-range prompts would make a CORRECT 12 look like leakage, and the run would
    stop precisely when it started working."""
    import inspect

    import tools.pc4_partd as d
    src = inspect.getsource(d.run_loop)
    assert "n_in_range_samples" in src
    body = src.split("if oor:")[1].split("else:")[1]
    assert "long_in_range" in body, "the long-answer counter is not in the in-range branch"


# ── reproducibility ─────────────────────────────────────────────────────────
def test_threads_are_pinned_in_code_not_left_to_the_environment():
    """Part C measured the same seed giving in-range 0.400 and 0.467 at different
    thread counts, each reproducing exactly under its own command (88dafd5). A
    number that depends on an environment variable is not a result."""
    torch = pytest.importorskip("torch")
    pin_threads()
    assert torch.get_num_threads() == N_THREADS == 1


def test_the_sampler_can_reach_lengths_above_the_answers_it_must_produce():
    """MAX_NEW must leave room to be WRONG in the long direction, or an over-long
    answer would be invisible and the leakage check could never see anything."""
    assert MAX_NEW > max(a + b for a, b in OUT_OF_RANGE_D)


def test_no_out_of_range_target_is_reachable_as_a_training_row():
    """The whole premise: the model is never SHOWN a correct answer above ten."""
    from tools.pc4_partc import build_data
    vocab = vocabulary("c2")
    train, _, _, _, _, _ = build_data(vocab)
    assert max(len(y) for _, y in train) <= TRAIN_MAX


def test_the_out_of_range_prompts_are_the_ones_the_brief_named():
    assert OUT_OF_RANGE_D == [(10, 2), (7, 5), (9, 4), (10, 4)]
    assert [a + b for a, b in OUT_OF_RANGE_D] == [12, 12, 13, 14]
