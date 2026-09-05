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


@pytest.fixture
def sig02_clusters():
    """The REAL repeat structure of sig02 in cortex_memory/training/holdout.jsonl,
    measured 5 Sep 2026: 38 rows, 11 distinct (prompt, target) pairs, with three
    pairs appearing nine times each."""
    counts = [9, 9, 9, 2, 2, 2, 1, 1, 1, 1, 1]
    out = []
    for i, n in enumerate(counts):
        out += [f"pair{i}"] * n
    return out

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


# ════════════════════════════════════════════════════════════════════════════
# WITHIN-STRATUM DRAW — the fix for the sig02/sig03 anomaly (5 Sep 2026)
# ════════════════════════════════════════════════════════════════════════════
# Measured on the control run: sig03/sig04/sig07 drew ZERO same-stratum
# distractors on 100% of items and scored exactly 0.0000; sig02 drew 0.67 of 4
# and scored exactly 1.0000; sig01 — 91.3% of the pool — drew 3.70 of 4 BY
# ACCIDENT and was the only stratum that read honestly at chance. Identical for
# base and adapter, which is the signature of a property of the data.

def _mixed_pool():
    rows = ([{"target": f"alpha proposal number {i}", "record_kind": "sig01"}
             for i in range(40)]
            + [{"target": f"beta approved item {i}", "record_kind": "sig02"}
               for i in range(9)]
            + [{"target": f"experiment exp-{i:03d}", "record_kind": "sig03"}
               for i in range(2)])
    return rm.build_pool(rows, wordlen), rows


def test_every_distractor_shares_the_true_targets_record_kind():
    pool, _ = _mixed_pool()
    for kind, target in (("sig01", "alpha proposal number 7"),
                         ("sig02", "beta approved item 3")):
        got, _ = rm.draw_distractors(rm.example_id("p", target), target,
                                     wordlen(target), pool, k=4, band=None,
                                     stratum=kind)
        assert got is not None, (kind, target)
        by_norm = {p["norm"]: p for p in pool}
        assert all(kind in by_norm[rm.norm(d)]["kinds"] for d in got), (kind, got)


def test_a_stratum_too_small_returns_None_and_NEVER_the_mixed_pool():
    """sig03 has 2 distinct targets, so it cannot supply 4 within itself. The
    honest answer is 'unscorable', not 'here are four from another stratum' —
    that fallback IS the defect."""
    pool, _ = _mixed_pool()
    got, _ = rm.draw_distractors(rm.example_id("p", "experiment exp-000"),
                                 "experiment exp-000", 2, pool, k=4, band=None,
                                 stratum="sig03")
    assert got is None


def test_widening_drops_the_LENGTH_band_never_the_stratum():
    """When the band cannot be filled the draw widens on length only. If it
    widened on stratum instead, the anomaly would return silently."""
    rows = ([{"target": " ".join(["short"] * 3), "record_kind": "sig02"}]
            + [{"target": " ".join([f"long{i}"] * 40), "record_kind": "sig02"}
               for i in range(6)]
            + [{"target": " ".join([f"other{i}"] * 3), "record_kind": "sig01"}
               for i in range(30)])
    pool = rm.build_pool(rows, wordlen)
    t = " ".join(["short"] * 3)
    got, widened = rm.draw_distractors(rm.example_id("p", t), t, 3, pool, k=4,
                                       band=rm.LENGTH_BAND, stratum="sig02")
    assert widened is True, "the band should not have been fillable"
    assert got is not None
    by_norm = {p["norm"]: p for p in pool}
    assert all("sig02" in by_norm[rm.norm(d)]["kinds"] for d in got), got


def test_a_target_belonging_to_two_kinds_is_drawable_by_both():
    """The same string can legitimately appear under two record_kinds. Keeping
    only the first seen would refuse candidates that genuinely belong."""
    rows = [{"target": "shared text here", "record_kind": "sig01"},
            {"target": "shared text here", "record_kind": "sig02"}]
    pool = rm.build_pool(rows, wordlen)
    assert len(pool) == 1
    assert pool[0]["kinds"] == {"sig01", "sig02"}


def test_omitting_the_stratum_still_draws_from_the_whole_pool():
    """stratum=None keeps the old behaviour, which the negative-control and the
    length-bias tests above still rely on. The RUNNER is what makes it
    mandatory."""
    pool, _ = _mixed_pool()
    got, _ = rm.draw_distractors(rm.example_id("p", "experiment exp-000"),
                                 "experiment exp-000", 2, pool, k=4, band=None)
    assert got is not None and len(got) == 4


# ════════════════════════════════════════════════════════════════════════════
# EFFECTIVE n — MIN_BUCKET counts DISTINCT (prompt, target) PAIRS, not rows
# ════════════════════════════════════════════════════════════════════════════
# MEASURED 5 Sep 2026 on the real holdout: sig02 has 38 rows but only 11 distinct
# (prompt, target) pairs, and three of those pairs appear NINE times each — 27 of
# the 38 rows are duplicates of three questions. A bootstrap that resamples rows
# treats nine copies of one question as nine observations and reports a CI far
# narrower than the evidence supports. n=38 was never 38 questions.

def test_pair_key_collapses_normalisation_variants():
    assert rm.pair_key("P", "target one") == rm.pair_key("P", "Target one.")
    assert rm.pair_key("P", "target one") != rm.pair_key("P", "target two")
    assert rm.pair_key("P", "t") != rm.pair_key("Q", "t")


def test_effective_n_counts_pairs_not_rows():
    clusters = ["a"] * 9 + ["b"] * 9 + ["c"] * 9 + list("defghijk")
    assert len(clusters) == 35
    assert rm.effective_n(clusters) == 11


def test_38_rows_of_11_pairs_is_UNRESOLVABLE():
    """The sig02 shape. 38 rows looks gradeable; 11 questions is not."""
    clusters = (["a"] * 9 + ["b"] * 9 + ["c"] * 9
                + ["d", "d", "e", "e", "f", "f"] + list("ghijk"))
    hits = [1] * len(clusters)
    assert len(clusters) == 38 and rm.effective_n(clusters) == 11
    v, acc, ci = rm.rank_verdict(hits, k=4, clusters=clusters)
    assert v.startswith("UNRESOLVABLE"), (v, acc, ci)
    assert ci is None


def test_185_rows_of_160_pairs_is_graded():
    """The sig01 shape: 185 rows, 160 distinct pairs — well past the bar."""
    clusters = [f"p{i}" for i in range(160)] + [f"p{i}" for i in range(25)]
    hits = [1] * len(clusters)
    assert rm.effective_n(clusters) == 160
    v, acc, ci = rm.rank_verdict(hits, k=4, clusters=clusters)
    assert v == "ABOVE CHANCE", (v, acc, ci)
    assert ci is not None


def test_clustered_rows_give_a_WIDER_CI_than_the_same_number_of_distinct_rows():
    """THE WHOLE POINT, asserted rather than asserted-about.

    300 rows that are 30 questions x 10 copies carry the evidence of 30
    questions. The same 300 rows as 300 distinct questions carry the evidence of
    300. Identical hit rate, and the clustered CI must be visibly wider.

    (The first version of this test used 4 clusters and 40 rows and failed with
    ci=None — correctly: accuracy_ci refuses a CI below MIN_BUCKET pairs, which
    is the gate this whole change exists to install. The test was wrong, not the
    code. Both variants here stay above the gate so the WIDTH is what is being
    compared, not the gate.)
    """
    clustered, hits_clustered = [], []
    for q in range(30):                       # 30 pairs x 10 copies = 300 rows
        clustered += [f"q{q:02d}"] * 10
        hits_clustered += [1 if q % 2 == 0 else 0] * 10
    distinct = [f"r{i:03d}" for i in range(300)]
    hits_distinct = [1 if i % 2 == 0 else 0 for i in range(300)]

    acc_cl, ci_cl = rm.accuracy_ci(hits_clustered, clusters=clustered, n_boot=4000)
    acc_di, ci_di = rm.accuracy_ci(hits_distinct, clusters=distinct, n_boot=4000)
    assert ci_cl is not None and ci_di is not None
    assert acc_cl == pytest.approx(acc_di), (acc_cl, acc_di)   # same hit rate
    width_cl, width_di = ci_cl[1] - ci_cl[0], ci_di[1] - ci_di[0]
    assert width_cl > width_di * 1.5, (
        f"clustered CI {width_cl:.4f} is not meaningfully wider than distinct "
        f"{width_di:.4f} - the cluster bootstrap is not clustering")


def test_a_pair_moves_TOGETHER_in_the_resample():
    """A cluster is resampled WHOLE. This pins the mechanism rather than its
    effect: the same 600 rows, clustered into 30 all-or-nothing pairs, must give
    a far wider interval than the same rows treated as 600 independent ones."""
    clusters, hits = [], []
    for q in range(30):
        clusters += [f"q{q:02d}"] * 20
        hits += [1 if q < 15 else 0] * 20      # each pair is all-1 or all-0
    _, ci_cluster = rm.accuracy_ci(hits, clusters=clusters, n_boot=4000)
    _, ci_rows = rm.accuracy_ci(hits, clusters=[str(i) for i in range(len(hits))],
                                n_boot=4000)
    assert ci_cluster is not None and ci_rows is not None
    assert (ci_cluster[1] - ci_cluster[0]) > 4 * (ci_rows[1] - ci_rows[0]), (
        ci_cluster, ci_rows)
    # 30 all-or-nothing pairs at 50%: the resampled mean is a binomial proportion
    # over 30 draws, so the interval is roughly +/-0.18 - nowhere near the
    # +/-0.04 that row-level resampling of 600 rows would claim.
    assert ci_cluster[0] < 0.36 and ci_cluster[1] > 0.64, ci_cluster


def test_without_clusters_every_row_is_its_own_pair():
    """Back-compatible: the older call sites pass no clusters and keep row-level
    behaviour, which is correct when rows ARE distinct questions."""
    v, acc, ci = rm.rank_verdict([1] * 30, k=4)
    assert v == "ABOVE CHANCE" and ci is not None


def test_the_real_sig02_repeat_structure_is_UNRESOLVABLE(sig02_clusters):
    """Regression against the measured holdout, not a synthetic stand-in."""
    assert len(sig02_clusters) == 38
    assert rm.effective_n(sig02_clusters) == 11
    v, _, ci = rm.rank_verdict([1, 0] * 19, k=4, clusters=sig02_clusters)
    assert v.startswith("UNRESOLVABLE") and ci is None


# ════════════════════════════════════════════════════════════════════════════
# THE AXIS RULE — the trivial baseline, computed from data, no model
# ════════════════════════════════════════════════════════════════════════════
# sig01's prompts are near-contentless EXCEPT that they name an axis, and
# within-stratum distractors mostly come from other axes. Measured: a perfect
# axis-matcher scores 0.7114 over the 135 items with a parsable axis, ~0.57 over
# all 185. Chance is 0.20. So "above chance" on sig01 is a much weaker claim than
# it looks, and the report must carry all three reference points.

def test_axis_of_finds_the_screaming_case():
    assert rm.axis_of("Action required for PLANET") == "PLANET"
    assert rm.axis_of("HUMAN axis needs progress") == "HUMAN"
    assert rm.axis_of("furthest from the goal: SOCIAL_RELATIONS_REVIEW (gap 7.7)")         == "SOCIAL_RELATIONS_REVIEW"


def test_axis_of_returns_None_when_there_is_none():
    for p in ("no axis here", "", "Действие за нещо", "a b c"):
        assert rm.axis_of(p) is None, p


def test_the_axis_rule_is_certain_when_no_distractor_shares_the_axis():
    """65 of 135 sig01 items look like this: the trivial rule gets them outright."""
    axes = {"true": {"PLANET"}, "d1": {"HUMAN"}, "d2": {"COSMOS"},
            "d3": {"HUMAN"}, "d4": {"CIVILIZATION"}}
    e = rm.axis_rule_expectation("Action required for PLANET", "true",
                                 ["d1", "d2", "d3", "d4"], axes, k=4)
    assert e == 1.0


def test_the_axis_rule_guesses_within_the_matching_group():
    axes = {"true": {"PLANET"}, "d1": {"PLANET"}, "d2": {"COSMOS"},
            "d3": {"HUMAN"}, "d4": {"PLANET"}}
    e = rm.axis_rule_expectation("Action required for PLANET", "true",
                                 ["d1", "d2", "d3", "d4"], axes, k=4)
    assert e == pytest.approx(1.0 / 3.0), e


def test_the_axis_rule_falls_back_to_chance_with_no_parsable_axis():
    axes = {"true": {"PLANET"}, "d1": {"PLANET"}}
    e = rm.axis_rule_expectation("no axis in this prompt", "true",
                                 ["d1", "d2", "d3", "d4"], axes, k=4)
    assert e == pytest.approx(0.2)


def test_the_axis_rule_falls_back_to_chance_when_EVERY_candidate_matches():
    """If the axis does not discriminate, the rule is guessing — 1/(K+1)."""
    axes = {n: {"PLANET"} for n in ("true", "d1", "d2", "d3", "d4")}
    e = rm.axis_rule_expectation("Action required for PLANET", "true",
                                 ["d1", "d2", "d3", "d4"], axes, k=4)
    assert e == pytest.approx(0.2)


def test_the_axis_rule_never_exceeds_one_or_drops_below_chance():
    import random
    rnd = random.Random(7)
    pool = ["PLANET", "HUMAN", "COSMOS", "CIVILIZATION"]
    for _ in range(300):
        a = rnd.choice(pool)
        axes = {"true": {a}}
        for i in range(4):
            axes[f"d{i}"] = {rnd.choice(pool)}
        e = rm.axis_rule_expectation(f"Action required for {a}", "true",
                                     [f"d{i}" for i in range(4)], axes, k=4)
        assert 0.2 - 1e-9 <= e <= 1.0, e


# ── the two labels, which must never be merged ───────────────────────────────

def test_LEARNED_and_BEYOND_TRIVIAL_are_reported_separately():
    """An adapter can beat the null model and still not beat a rule that needs no
    model at all. The report must be able to say exactly that."""
    lab = rm.reference_labels(adapter_ci=(0.40, 0.50),
                              control_ci=(0.18, 0.25),
                              axis_ci=(0.52, 0.62))
    assert lab["LEARNED"] is True
    assert lab["BEYOND_TRIVIAL"] is False


def test_beating_the_axis_rule_earns_both():
    lab = rm.reference_labels(adapter_ci=(0.70, 0.80),
                              control_ci=(0.18, 0.25),
                              axis_ci=(0.52, 0.62))
    assert lab["LEARNED"] and lab["BEYOND_TRIVIAL"]


def test_overlapping_the_control_earns_neither():
    lab = rm.reference_labels(adapter_ci=(0.19, 0.30),
                              control_ci=(0.18, 0.25),
                              axis_ci=(0.52, 0.62))
    assert lab["LEARNED"] is False and lab["BEYOND_TRIVIAL"] is False


def test_an_unresolvable_reference_makes_the_label_UNKNOWN_not_False():
    """A missing comparison is not a failed one. False would read as 'it did not
    learn', which is a claim nobody measured."""
    lab = rm.reference_labels(adapter_ci=(0.70, 0.80), control_ci=None,
                              axis_ci=(0.52, 0.62))
    assert lab["LEARNED"] is None
    assert lab["BEYOND_TRIVIAL"] is True
