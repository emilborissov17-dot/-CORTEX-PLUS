# -*- coding: utf-8 -*-
"""
training/rank_metric.py — the five named failure modes, each with the test that
catches it. Written BEFORE the metric is run on a GPU, on purpose.

The first metric was replaced because a negative control trained on deranged
pairs scored +1.2204 nats IMPROVED on novel held-out targets. NLL of the target
measures how probable the text is, and house style is enough to lower it. The
replacement asks a question style cannot answer: among ten real targets from the
same pool, is the TRUE one ranked lowest?

Chance is 1/(K+1) = 0.10. Every test here runs in the main suite — no torch, no
GPU, no network — because the metric logic is deliberately kept out of
eval_adapter.py, whose torch import makes its own tests INERT under venv/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import training.rank_metric as rm            # noqa: E402


def wordlen(s: str) -> int:
    """Stand-in tokenizer: token count ~ word count. Enough to exercise banding."""
    return max(1, len(str(s).split()))


def pool_of(targets):
    return rm.build_pool([{"target": t} for t in targets], wordlen)


# ════════════════════════════════════════════════════════════════════════════
# norm() — the fix, and the two cases that proved it was too weak
# ════════════════════════════════════════════════════════════════════════════

BASE = "proposal: raise the sampling rate"


def test_a_trailing_full_stop_now_reads_as_SEEN():
    """This ASSERTION IS INVERTED from test_eval_harness.py's, deliberately. That
    test documented the weakness; this one documents the fix, and the old test is
    updated in the same commit so the pair can never disagree."""
    assert rm.norm(BASE + ".") == rm.norm(BASE)


def test_a_capital_now_reads_as_SEEN():
    assert rm.norm("Proposal: raise the sampling rate") == rm.norm(BASE)


def test_whitespace_still_reads_as_SEEN():
    assert rm.norm("proposal:  raise   the sampling rate\n ") == rm.norm(BASE)


@pytest.mark.parametrize("suffix", [".", "!", "?", "...", ",", ";", ":", '."', ".)"])
def test_every_trailing_punctuation_variant_collapses(suffix):
    assert rm.norm(BASE + suffix) == rm.norm(BASE)


def test_norm_does_not_strip_punctuation_from_the_MIDDLE():
    """Only trailing. Collapsing internal punctuation would merge genuinely
    different targets and hide real distinctions."""
    assert rm.norm("a. b") != rm.norm("a b")


def test_norm_is_idempotent():
    assert rm.norm(rm.norm(BASE + ". ")) == rm.norm(BASE)


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 5 — duplicate pool
# ════════════════════════════════════════════════════════════════════════════

def test_the_pool_is_deduplicated_under_norm():
    """744 distinct targets in 1323 rows. Drawing from raw rows would let common
    boilerplate dominate the distractors, making the task easy for the wrong
    reason."""
    pool = pool_of(["alpha one", "alpha one", "Alpha one.", "beta two", "beta two  "])
    assert len(pool) == 2, [p["target"] for p in pool]
    assert len({p["norm"] for p in pool}) == 2


def test_the_pool_drops_empty_and_whitespace_targets():
    pool = pool_of(["real target", "", "   ", "\n"])
    assert [p["norm"] for p in pool] == [rm.norm("real target")]


def test_the_pool_order_is_stable_across_calls():
    """Distractor draws index into the pool, so an unstable order would break the
    paired comparison even with a fixed seed."""
    a = [p["norm"] for p in pool_of(["c x", "a y", "b z"])]
    b = [p["norm"] for p in pool_of(["b z", "c x", "a y"])]
    assert a == b


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 2 — distractor collision
# ════════════════════════════════════════════════════════════════════════════

def test_the_true_target_is_never_drawn_as_its_own_distractor():
    pool = pool_of([f"target number {i}" for i in range(40)])
    t = "target number 7"
    got, _ = rm.draw_distractors(rm.example_id("p", t), t, wordlen(t), pool, band=None)
    assert got is not None
    assert all(rm.norm(d) != rm.norm(t) for d in got), got


@pytest.mark.parametrize("variant", [
    "target number 7.", "Target number 7", "target  number   7", "target number 7 ",
])
def test_a_normalisation_VARIANT_of_the_target_is_excluded_too(variant):
    """The collision that the old norm() would have missed. A distractor equal to
    the true target under normalisation makes the item unscorable — the model is
    asked to rank a string below itself."""
    pool = pool_of([f"target number {i}" for i in range(40)] + [variant])
    t = "target number 7"
    got, _ = rm.draw_distractors(rm.example_id("p", t), t, wordlen(t), pool, band=None)
    assert all(rm.norm(d) != rm.norm(t) for d in got), (variant, got)


def test_too_small_a_pool_returns_None_rather_than_a_short_set():
    """Unscorable is reported, never silently scored as a miss."""
    pool = pool_of(["a b", "c d", "e f"])
    got, _ = rm.draw_distractors(rm.example_id("p", "a b"), "a b", 2, pool, band=None)
    assert got is None


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 1 — length bias
# ════════════════════════════════════════════════════════════════════════════

def _len_pool():
    out = []
    for n in (2, 4, 8, 10, 12, 20, 40):
        for j in range(12):
            out.append(" ".join([f"w{n}x{j}"] * n))
    return pool_of(out)


def test_banded_distractors_stay_within_the_length_band():
    pool = _len_pool()
    t = " ".join(["tt"] * 10)
    got, widened = rm.draw_distractors(rm.example_id("p", t), t, 10, pool,
                                       band=rm.LENGTH_BAND)
    assert got is not None and not widened
    lo, hi = 10 * (1 - rm.LENGTH_BAND), 10 * (1 + rm.LENGTH_BAND)
    assert all(lo <= wordlen(d) <= hi for d in got), [(d, wordlen(d)) for d in got]


def test_the_unmatched_variant_exists_and_really_is_unmatched():
    """band=None is reported ALONGSIDE the banded number so the length-bias gap is
    visible rather than assumed away."""
    pool = _len_pool()
    t = " ".join(["tt"] * 10)
    got, _ = rm.draw_distractors(rm.example_id("p", t), t, 10, pool, band=None)
    assert got is not None
    assert len({wordlen(d) for d in got}) > 1, "the unbanded draw is accidentally banded"


def test_widening_is_reported_when_the_band_cannot_be_filled():
    """A band too sparse to supply K distractors must SAY it widened. Silently
    falling back would hide exactly the bias the band exists to remove."""
    pool = pool_of([" ".join(["x"] * 3)] + [" ".join([f"y{i}"] * 50) for i in range(30)])
    t = " ".join(["tt"] * 3)
    got, widened = rm.draw_distractors(rm.example_id("p", t), t, 3, pool,
                                       band=rm.LENGTH_BAND)
    assert widened is True
    assert got is not None, "widening should still produce a scorable item"


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 4 — unpaired comparison
# ════════════════════════════════════════════════════════════════════════════

def test_base_and_adapter_draw_IDENTICAL_distractor_sets():
    """The seed depends on the example id alone — not the model, not the call
    order — so the two runs are paired by construction."""
    pool = pool_of([f"target number {i}" for i in range(60)])
    t = "target number 7"
    eid = rm.example_id("prompt p", t)
    first, _ = rm.draw_distractors(eid, t, wordlen(t), pool, band=None)
    second, _ = rm.draw_distractors(eid, t, wordlen(t), pool, band=None)
    assert first == second


def test_the_seed_survives_a_separate_process():
    """sha256, not Python's hash(): hash() is salted per process, so a seed built
    from it would differ between the base run and the adapter run and build the
    unpaired failure straight in."""
    import subprocess
    code = ("import sys; sys.path.insert(0, r'%s');"
            "import training.rank_metric as rm;"
            "print(rm.example_id('prompt p', 'target number 7'))" % REPO)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == rm.example_id("prompt p", "target number 7")


def test_different_examples_get_different_draws():
    """Paired, not constant. If every example drew the same nine distractors the
    metric would measure one comparison repeated N times."""
    pool = pool_of([f"target number {i}" for i in range(60)])
    draws = set()
    for i in range(20):
        t = f"target number {i}"
        got, _ = rm.draw_distractors(rm.example_id(f"p{i}", t), t, wordlen(t),
                                     pool, band=None)
        draws.add(tuple(got))
    assert len(draws) > 15, f"only {len(draws)} distinct draws in 20 examples"


# ════════════════════════════════════════════════════════════════════════════
# FAILURE MODE 3 — chance calibration
# ════════════════════════════════════════════════════════════════════════════

def test_a_random_model_scores_at_chance_over_2000_items():
    """THE CALIBRATION. A model whose NLL is noise must land at 0.10 with the CI
    containing it. If this fails, the metric has a bias and no result read from
    it means anything."""
    rng = np.random.default_rng(11)
    hits = []
    for _ in range(2000):
        nlls = rng.normal(3.0, 1.0, rm.K_DISTRACTORS + 1)
        hits.append(rm.hit(nlls[0], nlls[1:]))
    acc, ci = rm.accuracy_ci(hits)
    assert ci is not None
    assert ci[0] <= rm.CHANCE <= ci[1], (
        f"random model scored {acc:.4f}, CI [{ci[0]:.4f}, {ci[1]:.4f}] — "
        f"does not contain chance {rm.CHANCE}")


def test_a_random_model_is_called_AT_CHANCE_not_above_it():
    rng = np.random.default_rng(12)
    hits = [rm.hit(*(lambda v: (v[0], v[1:]))(rng.normal(3.0, 1.0, 10)))
            for _ in range(2000)]
    v, acc, ci = rm.rank_verdict(hits)
    assert v == "AT CHANCE", (v, acc, ci)


def test_a_LENGTH_BIASED_model_beats_chance_unbanded_and_is_pulled_back_by_banding():
    """THE TEST WITH TEETH for failure mode 1.

    The calibration test above uses noise, where ties have probability zero and
    accuracy is 0.10 by construction — it validates the scoring rule and nothing
    else. This one models the actual bias: a model whose per-token NLL falls with
    target length, knowing NOTHING about the mapping.

    MEASURED FIRST, THEN ASSERTED (and the first assertion was wrong): a
    length-biased model does NOT inflate aggregate accuracy. It REDISTRIBUTES it.
    Short targets beat all nine distractors almost always; long targets lose
    almost always; the mean came out at 0.062 — BELOW chance — which would have
    read as "the model is worse than random" if only the aggregate were looked at.

    So the signature of length bias is the SPREAD across length groups, not the
    mean. That is what this asserts, and it is why the unmatched variant is
    reported alongside the banded one instead of being assumed away.
    """
    lengths = [2, 4, 6, 8, 10, 14, 20, 30]
    pool = pool_of([" ".join([f"w{n}v{j}"] * n) for n in lengths for j in range(14)])

    def biased_nll(target):          # shorter -> lower NLL. No prompt at all.
        return 1.0 + 0.05 * wordlen(target)

    def run(band):
        per_len: dict = {}
        for n in lengths:
            hits = []
            for j in range(14):
                t = " ".join([f"w{n}v{j}"] * n)
                got, _ = rm.draw_distractors(rm.example_id(f"p{n}_{j}", t), t,
                                             wordlen(t), pool, band=band)
                if got is None:
                    continue
                hits.append(rm.hit(biased_nll(t), [biased_nll(d) for d in got]))
            if hits:
                per_len[n] = float(np.mean(hits))
        return per_len

    unbanded = run(None)
    banded = run(rm.LENGTH_BAND)

    assert len(unbanded) >= 4 and len(banded) >= 4, (unbanded, banded)
    spread_u = max(unbanded.values()) - min(unbanded.values())
    spread_b = max(banded.values()) - min(banded.values())

    # MEASURED 5 Sep 2026: unbanded per-length accuracy was
    # {2: 0.50, 4: 0.0, 6: 0.0, 8: 0.0, 10: 0.0, 14: 0.0, 20: 0.0, 30: 0.0},
    # spread 0.500, against chance 0.10. The threshold sits below the observed
    # value rather than on it, so the test is not brittle to a fixture tweak.
    #
    # Why the short group is 0.50 and not 1.0: this fake NLL depends on length
    # ALONE, so a same-length distractor ties exactly, and a tie scores 0. That
    # also makes the BANDED numbers collapse to zero here — an artefact of the
    # fixture, not a defect of banding. A real model does not tie on two
    # different strings of equal length.
    assert spread_u > 0.3, (
        f"the fixture does not reproduce length bias: per-length accuracy "
        f"{unbanded}, spread {spread_u:.3f}. This test would prove nothing.")
    assert spread_b < spread_u, (
        f"banding did not reduce the length-bias spread: banded {spread_b:.3f} "
        f"({banded}) >= unbanded {spread_u:.3f} ({unbanded})")


def test_chance_is_exactly_one_over_K_plus_one():
    assert rm.K_DISTRACTORS == 9
    assert rm.CHANCE == pytest.approx(0.10)


def test_a_perfect_model_is_ABOVE_CHANCE_and_a_reversed_one_is_BELOW():
    assert rm.rank_verdict([1] * 100)[0] == "ABOVE CHANCE"
    assert rm.rank_verdict([0] * 100)[0] == "BELOW CHANCE"


# ════════════════════════════════════════════════════════════════════════════
# Scoring rules
# ════════════════════════════════════════════════════════════════════════════

def test_a_tie_scores_zero():
    """Strictly lowest. A tie is indifference, and scoring it as a hit inflates
    accuracy exactly where the model does not know."""
    assert rm.hit(1.0, [1.0, 2.0, 3.0]) == 0
    assert rm.hit(1.0, [1.0000001, 2.0]) == 1


def test_the_true_target_is_scored_before_the_distractors():
    """A stateful nll_fn (a cache, a KV reuse bug) must not be primed by having
    seen nine distractors first."""
    order = []
    rm.score_example(lambda p, t: order.append(t) or 1.0, "p", "TRUE", ["d1", "d2"])
    assert order[0] == "TRUE", order


def test_under_29_items_is_UNRESOLVABLE_and_30_is_graded():
    assert rm.MIN_BUCKET == 30
    assert rm.rank_verdict([1] * 29)[0] == "UNRESOLVABLE (n<30)"
    assert rm.rank_verdict([1] * 29)[2] is None
    assert rm.rank_verdict([1] * 30)[0] == "ABOVE CHANCE"


# ════════════════════════════════════════════════════════════════════════════
# The pre-registered decision rule
# ════════════════════════════════════════════════════════════════════════════

def test_beating_chance_is_not_enough_it_must_also_beat_the_control():
    """Both conditions, fixed before any run. A run that clears 0.10 but sits
    inside the control's interval has not been distinguished from the null."""
    rng = np.random.default_rng(3)
    control = [1 if rng.random() < 0.35 else 0 for _ in range(400)]
    run = [1 if rng.random() < 0.36 else 0 for _ in range(400)]
    ok, why = rm.beats_control(run, control)
    assert not ok, why
    assert "control" in why


def test_a_run_clearly_above_the_control_passes():
    rng = np.random.default_rng(4)
    control = [1 if rng.random() < 0.12 else 0 for _ in range(400)]
    run = [1 if rng.random() < 0.60 else 0 for _ in range(400)]
    ok, why = rm.beats_control(run, control)
    assert ok, why


def test_a_run_at_chance_fails_even_if_the_control_is_worse():
    rng = np.random.default_rng(5)
    control = [1 if rng.random() < 0.02 else 0 for _ in range(400)]
    run = [1 if rng.random() < 0.10 else 0 for _ in range(400)]
    ok, why = rm.beats_control(run, control)
    assert not ok, why
    assert "chance" in why
