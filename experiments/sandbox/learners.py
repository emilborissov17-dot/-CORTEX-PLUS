#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/sandbox/learners.py — three ways to answer "what happens if I set X?"
from data. None of them may look at the world's structure; see world.py and
test_sandbox.py::test_learners_never_peek.

  NaiveCorrelation   E[Y | X = v] from observational data, one regressor.
                     The spectator: it will move non-descendants of X because
                     they are correlated with X through confounders.
  AdjustedRegression "control for everything": Y ~ f(X) + all other variables.
                     Wrong in a different way — it adjusts for mediators (blocks
                     the effect) and colliders (opens a path).
  ANMCausal          A non-neural causal learner. Skeleton from partial
                     correlations, edges oriented by the additive-noise
                     criterion (the direction whose residual is less dependent
                     on its input), one non-linear mechanism per variable
                     fitted on its discovered parents, and do(X := v) answered
                     by FORWARD SIMULATION through the discovered graph.
                     Non-descendants stay put by construction.
                     `update()` lets it learn from its own interventions
                     (point 12: action -> consequence -> revised model).

Every learner reports the SAME thing: for do(X := v), the predicted mean of
every other variable. The bench scores those against the true intervention.
"""
from __future__ import annotations

import numpy as np

PC_THRESHOLD = 0.15
RIDGE = 1e-2


def _basis(x: np.ndarray) -> np.ndarray:
    """Per-parent non-linear features: x, x^2 - 1, tanh(1.5x)."""
    return np.stack([x, 0.5 * (x * x - 1.0), np.tanh(1.5 * x)], axis=1)


def _design(X: np.ndarray, cols: list[int]) -> np.ndarray:
    parts = [np.ones((X.shape[0], 1))]
    for c in cols:
        parts.append(_basis(X[:, c]))
    if len(cols) >= 2:
        parts.append((X[:, cols[0]] * X[:, cols[1]])[:, None])
    return np.concatenate(parts, axis=1)


def _hsic(x: np.ndarray, y: np.ndarray, n_max: int = 300) -> float:
    """Biased HSIC estimate with RBF kernels (median-heuristic bandwidth) —
    a dependence measure that sees non-linear, non-correlational dependence."""
    if len(x) > n_max:
        idx = np.linspace(0, len(x) - 1, n_max).astype(int)
        x, y = x[idx], y[idx]
    def K(v):
        d = (v[:, None] - v[None, :]) ** 2
        med = np.median(d[d > 0]) if np.any(d > 0) else 1.0
        return np.exp(-d / (med + 1e-12))
    n = len(x)
    H = np.eye(n) - np.ones((n, n)) / n
    Kx, Ky = H @ K(x) @ H, H @ K(y) @ H
    return float(np.sum(Kx * Ky) / (n * n))


def _ridge(A: np.ndarray, y: np.ndarray, lam: float = RIDGE) -> np.ndarray:
    p = A.shape[1]
    return np.linalg.solve(A.T @ A + lam * np.eye(p), A.T @ y)


class _Base:
    def fit(self, X: np.ndarray, names: list[str]) -> "_Base":
        self.names = list(names)
        self.X = X.copy()
        self.mu = X.mean(axis=0)
        self.sd = X.std(axis=0) + 1e-9
        return self

    def update(self, var: str, value: float, X_int: np.ndarray) -> None:
        """Default: interventional data is ignored (a spectator does not learn from acting)."""

    def predict(self, var: str, value: float) -> dict:
        raise NotImplementedError


class NaiveCorrelation(_Base):
    def predict(self, var: str, value: float) -> dict:
        i = self.names.index(var)
        out = {}
        A = _design(self.X, [i])
        a_new = _design(np.array([[value if k == i else 0.0 for k in range(self.X.shape[1])]]), [i])
        for j, nm in enumerate(self.names):
            if j == i:
                continue
            w = _ridge(A, self.X[:, j])
            out[nm] = float((a_new @ w)[0])
        return out


class AdjustedRegression(_Base):
    def predict(self, var: str, value: float) -> dict:
        i = self.names.index(var)
        out = {}
        for j, nm in enumerate(self.names):
            if j == i:
                continue
            others = [k for k in range(self.X.shape[1]) if k not in (i, j)]
            A = np.concatenate([_design(self.X, [i]), self.X[:, others]], axis=1)
            w = _ridge(A, self.X[:, j])
            row = np.array([[value if k == i else self.mu[k] for k in range(self.X.shape[1])]])
            a_new = np.concatenate([_design(row, [i]), row[:, others]], axis=1)
            out[nm] = float((a_new @ w)[0])
        return out


class ANMCausal(_Base):
    def fit(self, X: np.ndarray, names: list[str]) -> "ANMCausal":
        super().fit(X, names)
        self._rows = [(X.copy(), None)]          # (data, intervened index or None)
        self._probed = set()
        self._discover()
        self._fit_mechanisms()
        return self

    # -- structure from observational data only ------------------------------
    def _discover(self) -> None:
        X = self._obs_only()
        n = X.shape[1]
        Z = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-9)
        prec = np.linalg.pinv(np.cov(Z, rowvar=False) + 1e-3 * np.eye(n))
        d = np.sqrt(np.diag(prec))
        pcorr = -prec / np.outer(d, d)
        adj = {(a, b) for a in range(n) for b in range(a + 1, n) if abs(pcorr[a, b]) > PC_THRESHOLD}
        # orientation: additive-noise criterion
        nbrs = {i: sorted({a for a, b in adj if b == i} | {b for a, b in adj if a == i}) for i in range(n)}

        def dep(a, b):  # residual dependence if a -> b, measured by HSIC
            # b is regressed on ALL its skeleton neighbours (a among them): in the
            # true direction the residual is b's own noise and independent of a;
            # in the false one it is not. Pairwise regression was not enough
            # (multi-parent nodes: recall 0.31, 8/22 edges reversed, 10 Sep), and
            # correlation with the regression's own features is zero by
            # construction in both directions (first run: recall 0.065).
            cols = [c for c in nbrs[b] if c != a][:3]
            A = _design(X, [a] + cols)
            r = X[:, b] - A @ _ridge(A, X[:, b])
            return _hsic(X[:, a], r)
        self.skeleton = sorted(adj)
        self.anm = {}
        for a, b in adj:
            dab, dba = dep(a, b), dep(b, a)
            self.anm[(a, b)] = (a, b, dba - dab) if dab <= dba else (b, a, dab - dba)
        self.evidence = {}          # (cause, effect) -> |mean shift| seen under do(cause)
        self._orient()

    def _orient(self) -> None:
        """Every skeleton edge gets a direction: interventional evidence first
        (do(a) moved b and do(b) did not move a => a -> b), the observational
        ANM verdict only where no intervention has spoken. This is the point
        of acting: observation leaves orientation ambiguous, action settles it."""
        n = len(self.names)
        edges = []
        for a, b in self.skeleton:
            ab, ba = self.evidence.get((a, b), 0.0), self.evidence.get((b, a), 0.0)
            probed_a, probed_b = (a in self._probed), (b in self._probed)
            if probed_a or probed_b:
                if ab > ba:
                    edges.append((a, b, 10.0 + ab)); continue
                if ba > ab:
                    edges.append((b, a, 10.0 + ba)); continue
                if probed_a and probed_b and ab == 0.0 and ba == 0.0:
                    continue                      # neither moves the other: the edge was spurious
            edges.append(self.anm[(a, b)])
        edges.sort(key=lambda e: -e[2])
        parents = {i: [] for i in range(n)}
        for a, b, _ in edges:
            parents[b].append(a)
            if self._has_cycle(parents):
                parents[b].remove(a)
        self.parents = parents
        self.order = self._topo(parents)

    @staticmethod
    def _has_cycle(parents) -> bool:
        seen, stack = set(), set()
        def visit(v):
            if v in stack:
                return True
            if v in seen:
                return False
            seen.add(v); stack.add(v)
            if any(visit(p) for p in parents[v]):
                return True
            stack.discard(v)
            return False
        return any(visit(v) for v in parents)

    @staticmethod
    def _topo(parents) -> list[int]:
        order, done = [], set()
        while len(order) < len(parents):
            for v in parents:
                if v not in done and all(p in done for p in parents[v]):
                    order.append(v); done.add(v)
        return order

    # -- mechanisms, from every row where the variable was NOT clamped -------
    def _obs_only(self) -> np.ndarray:
        return np.concatenate([X for X, do in self._rows if do is None], axis=0)

    def _fit_mechanisms(self) -> None:
        self.w = {}
        for i in range(len(self.names)):
            rows = [X for X, do in self._rows if do != i]
            X = np.concatenate(rows, axis=0)
            A = _design(X, self.parents[i])
            self.w[i] = _ridge(A, X[:, i])

    def update(self, var: str, value: float, X_int: np.ndarray) -> None:
        """Action -> consequence -> revised WORLD MODEL. What do(var) moved is a
        descendant; what it left alone is not. That evidence re-orients the
        skeleton, then every mechanism is refit on everything seen so far."""
        i = self.names.index(var)
        self._rows.append((X_int.copy(), i))
        self._probed.add(i)
        shift = np.abs(X_int.mean(axis=0) - self.mu) / self.sd
        for j in range(len(self.names)):
            if j != i:
                s = float(shift[j]) if shift[j] > 0.25 else 0.0
                self.evidence[(i, j)] = max(self.evidence.get((i, j), 0.0), s)
        # a strong shift with no discovered path from var to j is an edge the
        # skeleton missed: acting adds what observing could not see
        self._orient()
        reach = self._reachable(i)
        for j in range(len(self.names)):
            if j != i and shift[j] > 0.5 and j not in reach:
                e = (min(i, j), max(i, j))
                if e not in self.skeleton:
                    self.skeleton.append(e)
                    self.anm[e] = (i, j, 0.0)
        self._orient()
        self._fit_mechanisms()

    def _reachable(self, i: int) -> set:
        out, frontier = set(), {i}
        while frontier:
            nxt = {v for v in range(len(self.names)) if any(p in frontier for p in self.parents[v]) and v not in out}
            out |= nxt
            frontier = nxt
        return out

    def least_known(self) -> list[int]:
        """Variables to probe next: those touching the most edges that no
        intervention has spoken about yet — the model's own uncertainty."""
        score = {i: 0 for i in range(len(self.names))}
        for a, b in self.skeleton:
            if a not in self._probed and b not in self._probed:
                score[a] += 1; score[b] += 1
        return sorted(score, key=lambda i: -score[i])

    # -- do(X := v) by forward simulation -------------------------------------
    def predict(self, var: str, value: float) -> dict:
        i = self.names.index(var)
        x = self.mu.copy()
        x[i] = value
        for v in self.order:
            if v == i:
                continue
            if not self.parents[v]:
                x[v] = self.mu[v]                  # exogenous: unaffected
                continue
            x[v] = float((_design(x[None, :], self.parents[v]) @ self.w[v])[0])
        return {nm: float(x[j]) for j, nm in enumerate(self.names) if j != i}

    def discovered(self) -> dict:
        return {self.names[v]: [self.names[p] for p in ps] for v, ps in self.parents.items()}


LEARNERS = {"naive_correlation": NaiveCorrelation, "adjusted_regression": AdjustedRegression,
            "anm_causal": ANMCausal}
