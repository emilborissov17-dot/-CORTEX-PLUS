# -*- coding: utf-8 -*-
"""test/test_sandbox.py — the hidden world and the learners that must not peek (10 Sep 2026)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
SB = REPO / "experiments" / "sandbox"
sys.path.insert(0, str(SB))

import world as W  # noqa: E402
import learners as Lm  # noqa: E402


def test_learners_never_peek():
    """Structural: the learners module must not reference the grader-only names.
    Checked on identifiers in code, not on prose."""
    tree = ast.parse((SB / "learners.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("_truth", "truth_for_grader", "mechanisms", "descendants"):
        assert forbidden not in names, f"learners.py references {forbidden}"
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and "world" in ast.dump(n) for n in ast.walk(tree))


def test_world_has_the_three_motifs_and_is_reproducible():
    w1, w2 = W.World(5), W.World(5)
    t = W.truth_for_grader(w1)["parents"]
    assert {"v0", "v1"} <= set(t["v2"])                 # collider
    assert "v3" in t["v4"] and "v4" in t["v5"]           # mediator chain
    assert "v0" in t["v6"] and {"v0", "v6"} <= set(t["v7"])  # confounder
    assert np.allclose(w1.observe(20), w2.observe(20))


def test_intervention_moves_descendants_only():
    w = W.World(3)
    X = w.observe(2000)
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Y = w.intervene("v0", float(mu[0] + 2 * sd[0]), 2000)
    shift = np.abs(Y.mean(0) - mu) / sd
    desc = W.descendants(w, "v0")
    for j, nm in enumerate(w.variables()):
        if nm == "v0":
            assert np.allclose(Y[:, 0], mu[0] + 2 * sd[0])
        elif nm not in desc:
            assert shift[j] < 0.15, f"{nm} is not a descendant of v0 and moved by {shift[j]:.2f} sd"


def test_every_call_is_counted():
    w = W.World(1)
    w.observe(10); w.intervene("v1", 0.0, 5)
    assert w.spent() == {"observe": 1, "intervene": 1, "samples": 15}


def test_negative_control_shuffled_data_learns_nothing():
    """Rows shuffled per column destroy every dependence: the causal learner
    must discover (almost) no edges, and must predict 'nothing moves'."""
    w = W.World(2)
    X = w.observe(400)
    rng = np.random.default_rng(0)
    Xs = np.stack([rng.permutation(X[:, j]) for j in range(X.shape[1])], axis=1)
    L = Lm.ANMCausal().fit(Xs, w.variables())
    assert sum(len(p) for p in L.parents.values()) <= 3
    p = L.predict("v0", float(Xs[:, 0].mean() + 2 * Xs[:, 0].std()))
    assert all(abs(p[nm] - Xs[:, j].mean()) < 0.2 * Xs[:, j].std() for j, nm in enumerate(w.variables()) if nm != "v0")


def test_acting_revises_the_graph(monkeypatch):
    """Mutation net: with update() neutered the graph cannot improve; with it on, it must."""
    w = W.World(1000)
    X = w.observe(400)
    names = w.variables()
    truth = W.truth_for_grader(w)["parents"]

    def recall(L):
        d = L.discovered()
        return sum(1 for v, ps in truth.items() for p in ps if p in d[v]) / sum(len(ps) for ps in truth.values())
    L = Lm.ANMCausal().fit(X, names)
    r0 = recall(L)
    rng = np.random.default_rng(1)
    for _ in range(3):
        for i in L.least_known()[:4]:
            v = float(L.mu[i] + rng.choice([-1.5, 1.5]) * L.sd[i])
            L.update(names[i], v, w.intervene(names[i], v, 50))
    assert recall(L) > r0 + 0.15, "twelve of its own interventions must teach the learner structure observation could not"
    # neutered
    L2 = Lm.ANMCausal().fit(X, names)
    monkeypatch.setattr(L2, "update", lambda *a, **k: None)
    for i in L2.least_known()[:4]:
        L2.update(names[i], 0.0, w.intervene(names[i], 0.0, 50))
    assert recall(L2) == pytest.approx(r0)


def test_t6_after_scores_without_touching_the_world():
    """Mechanical net for T6A. The after-action credit hit-rate is only
    comparable to the before-action one if both answer the SAME questions:
    same targets, same candidate values, same Monte-Carlo ground truth. The
    forbidden shortcut is to call the question builder twice — fresh targets and
    a freshly estimated truth, reported as a before/after difference.

    So scoring must be pure: if `_t6_score` ever queries the world again, the
    world's spend counter moves and this fails. Remove the split and it fails.
    """
    import bench as B  # noqa: PLC0415
    w = W.World(11)
    X = w.observe(300)
    sd = X.std(axis=0) + 1e-9
    qs, rand_hits = B._t6_questions(w, X, np.random.default_rng(0), sd, k=3)
    L = Lm.ANMCausal().fit(X, w.variables())
    spent_before = w.spent()
    s1 = B._t6_score(qs, {"a": L})
    s2 = B._t6_score(qs, {"a": L})
    assert w.spent() == spent_before, "scoring credit must not query the world"
    assert s1 == s2, "scoring must be deterministic"
    assert 0.0 <= s1["a"] <= 1.0 and 0 <= rand_hits <= 3
    # the questions are a fixed list, not a generator that would be consumed
    assert len(qs) == 3 and all(len(q["cands"]) == len(w.variables()) - 1 for q in qs)


def test_t6a_verdict_fails_on_a_tie_and_on_beating_nobody():
    """Behavioural net on the pre-registered T6A rule, run on synthetic numbers.

    A learner that spent 20 interventions and then answers credit exactly as
    well as it did from observation alone is a FAIL, and so is one that improves
    but still cannot beat the correlational learner. Drop the margin to 0, or
    drop the naive comparison, and this test fails."""
    import bench as B  # noqa: PLC0415

    def summary(after, before=0.44, naive=0.44):
        return {"t8": {"anm_causal": {"direction_acc": 0.9, "false_move_nondesc": 0.1},
                       "naive_correlation": {"direction_acc": 0.7, "false_move_nondesc": 0.8}},
                "t6": {"anm_causal": before, "naive_correlation": naive},
                "t6_after": after, "t12_curve": [1.0, 0.5]}

    assert B.verdicts(summary(0.44))["T6A"] == "FAIL", "a tie must not pass"
    assert B.verdicts(summary(0.58))["T6A"] == "FAIL", "an improvement of exactly < margin must not pass"
    assert B.verdicts(summary(0.59))["T6A"] == "PASS"
    # improves by a mile, but the correlational learner is better: still FAIL
    assert B.verdicts(summary(0.70, before=0.20, naive=0.85))["T6A"] == "FAIL"
    assert B.T6A_MARGIN == 0.15, "the pre-registered margin was changed after the fact"
