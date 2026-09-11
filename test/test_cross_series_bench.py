# -*- coding: utf-8 -*-
"""test/test_cross_series_bench.py — E1 (11 Sep 2026). Synthetic worlds with a known answer:
  * B = A shifted one day + small noise: ridge on ALL lags must beat persistence on B,
    and beat ridge on B's own lags; transfer A->B is judged, not assumed
  * a pure random walk: no model is allowed to be declared a winner by construction
    (the bench only reports; this test pins that it does not crash and counts honestly)
  * the learning curve has one entry per k; a short series is refused with a reason
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
import cross_series_bench as CB  # noqa: E402


def _dates(n):
    d0 = date(2026, 3, 1)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _world(n=120, seed=1):
    rng = random.Random(seed)
    ds = _dates(n)
    a = [100.0]
    for _ in range(n - 1):
        a.append(a[-1] + rng.gauss(0, 1.0))
    b = [50.0]
    for i in range(1, n):
        b.append(b[-1] + (a[i - 1] - a[i - 2] if i >= 2 else 0.0) + rng.gauss(0, 0.1))   # B follows A's last move
    c = [10.0]
    for _ in range(n - 1):
        c.append(c[-1] + rng.gauss(0, 1.0))
    return {"A": list(zip(ds, a)), "B": list(zip(ds, b)), "C": list(zip(ds, c))}


def test_a_series_that_follows_another_is_predicted_from_the_other():
    b = CB.bench(_world())
    rb = b["targets"]["B"]["mae"]
    assert rb["ridge_all"] < rb["persistence"] * 0.6
    assert rb["ridge_all"] < rb["ridge_own"]
    assert b["verdict"]["ridge_all_beats_persistence"] >= 1
    lc = b["learning_curve"]["B"]
    assert set(lc) == {"10", "20", "40", "80"} and lc["80"]["beats"]


def test_transfer_is_judged_per_pair():
    b = CB.bench(_world())
    assert "A -> B" in b["transfer"] and "B -> A" in b["transfer"]
    assert b["verdict"]["transfer_pairs"] == 6
    for v in b["transfer"].values():
        assert v["beats"] == (v["transfer_mae"] < v["persistence_mae"])


def test_short_series_and_too_few_series_are_refused_with_a_reason():
    w = _world(n=30)
    assert "error" in CB.bench(w)
    w2 = _world(); w2["A"] = w2["A"][:20]
    b = CB.bench(w2)
    assert "A" not in b["usable"] and b["verdict"]["targets"] == 2


def test_ridge_solves_a_known_system():
    X = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]]
    y = [2.0, 3.0, 5.0, 7.0]
    w = CB.ridge_fit(X, y, lam=0.0)
    assert abs(w[0] - 2.0) < 1e-9 and abs(w[1] - 3.0) < 1e-9


def test_markdown_carries_the_verdict():
    md = CB.markdown(CB.bench(_world()))
    assert "**Verdict:**" in md and "| B |" in md and "A -> B" in md
