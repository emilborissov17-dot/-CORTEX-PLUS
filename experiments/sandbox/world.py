#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/sandbox/world.py — A SMALL WORLD WITH A HIDDEN CAUSAL STRUCTURE.
(10 September 2026. Kimi Round 32: "a pilot in a flight simulator is not flying a
plane" — legitimate under the 31 Jul wall IF the true structure is hidden from every
process, non-linear, with colliders and mediators, 10 variables, black-box
observe()/intervene() API, 400 observational + 100 interventional.)

WHY THIS EXISTS
---------------
§VI forbids the system from acting on the world. It does not forbid a simulation.
Points 5/8 (causality from intervention), 6 (credit assignment) and 12
(action -> consequence) cannot be tested on annual World Bank figures; here they
can, with ground truth, in minutes, on CPU.

THE CONTRACT
------------
- `World(seed)` builds a random DAG over N=10 variables with at least one
  collider (A -> C <- B), one mediator chain (A -> M -> Y) and one confounder
  (Z -> A, Z -> Y). Mechanisms are NON-LINEAR (tanh, squares, products) plus
  Gaussian noise. Different seeds, different worlds.
- The learner sees ONLY `variables()`, `observe(n)` and `intervene(var, value, n)`.
  The structure lives in `World._truth` and is read by the grader alone
  (`truth_for_grader`). test/test_sandbox.py holds a structural check that
  experiments/sandbox/learners.py never references `_truth`, `truth_for_grader`
  or `mechanisms` — a learner that peeks is a ceremony, and the check is on
  identifiers in code, not on prose.
- Every call is COUNTED (`spent()`), so a learner's information budget is a
  measurable quantity, not a courtesy.

`intervene` is the do-operator: the variable is clamped to `value`, its own
mechanism and noise are cut, every descendant is resampled through the true
mechanisms. Non-descendants are unaffected — that is the fact a correlational
learner cannot know and a causal one must.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

N_VARS = 10
NOISE = 0.3


class World:
    def __init__(self, seed: int = 0, n_vars: int = N_VARS):
        self.seed = seed
        self._rng = np.random.default_rng(seed)
        self.n = n_vars
        self._names = [f"v{i}" for i in range(n_vars)]
        self._calls = {"observe": 0, "intervene": 0, "samples": 0}
        self._truth = self._build()

    # ── the hidden structure ────────────────────────────────────────────────
    def _build(self) -> dict:
        rng = self._rng
        n = self.n
        while True:
            # random DAG in topological order 0..n-1, edge prob 0.3
            parents = {i: [j for j in range(i) if rng.random() < 0.3] for i in range(n)}
            # force the three motifs the brief requires, in the first six variables
            parents[2] = sorted(set(parents[2]) | {0, 1})          # collider: 0 -> 2 <- 1
            parents[4] = sorted(set(parents[4]) | {3})             # mediator: 3 -> 4 -> 5
            parents[5] = sorted(set(parents[5]) | {4})
            parents[6] = sorted(set(parents[6]) | {0})             # confounder: 0 -> 6, 0 -> 7, 6 -> 7
            parents[7] = sorted(set(parents[7]) | {0, 6})
            if all(len(p) <= 4 for p in parents.values()):
                break
        mech: dict[int, Callable] = {}
        for i in range(n):
            ps = parents[i]
            kinds = [rng.choice(["lin", "tanh", "sq", "prod"]) for _ in ps]
            w = rng.uniform(0.6, 1.4, size=len(ps)) * rng.choice([-1, 1], size=len(ps))
            bias = rng.uniform(-0.3, 0.3)

            def f(x_par, kinds=kinds, w=w, bias=bias):
                out = bias
                for k, wi, xp in zip(kinds, w, x_par):
                    if k == "lin":
                        out += wi * xp
                    elif k == "tanh":
                        out += wi * math.tanh(1.5 * xp)
                    elif k == "sq":
                        out += wi * 0.5 * (xp * xp - 1.0)
                    else:  # prod with the first parent
                        out += wi * 0.5 * xp * x_par[0]
                return out
            mech[i] = f
        return {"parents": parents, "mechanisms": mech}

    # ── the black-box API ───────────────────────────────────────────────────
    def variables(self) -> list[str]:
        return list(self._names)

    def observe(self, n: int) -> np.ndarray:
        """n rows x N_VARS, drawn from the observational distribution."""
        self._calls["observe"] += 1
        self._calls["samples"] += n
        return self._sample(n, do=None)

    def intervene(self, var: str, value: float, n: int) -> np.ndarray:
        """do(var := value): n rows with var clamped, descendants resampled."""
        self._calls["intervene"] += 1
        self._calls["samples"] += n
        return self._sample(n, do=(self._names.index(var), float(value)))

    def spent(self) -> dict:
        return dict(self._calls)

    def _sample(self, n: int, do) -> np.ndarray:
        rng = self._rng
        X = np.zeros((n, self.n))
        for i in range(self.n):
            if do is not None and do[0] == i:
                X[:, i] = do[1]
                continue
            ps = self._truth["parents"][i]
            f = self._truth["mechanisms"][i]
            noise = rng.normal(0.0, NOISE, size=n)
            for r in range(n):
                X[r, i] = f([X[r, j] for j in ps]) + noise[r]
        return X


# ── grader only ─────────────────────────────────────────────────────────────

def truth_for_grader(world: World) -> dict:
    """The hidden graph. Imported by the BENCH/GRADER only. A learner module that
    references this name fails test_sandbox.py::test_learners_never_peek."""
    return {"parents": {world._names[i]: [world._names[j] for j in ps]
                        for i, ps in world._truth["parents"].items()}}


def descendants(world: World, var: str) -> set[str]:
    par = truth_for_grader(world)["parents"]
    out, frontier = set(), {var}
    while frontier:
        nxt = set()
        for v, ps in par.items():
            if any(p in frontier for p in ps) and v not in out:
                nxt.add(v)
        out |= nxt
        frontier = nxt
    return out
