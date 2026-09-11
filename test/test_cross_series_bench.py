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


def test_e2_a_series_that_follows_another_gets_a_surviving_concept():
    # B follows A's move of the previous day; A and C are independent walks.
    w = _world()
    # add D that moves WITH A on the same day, so A's concept contains D
    import random
    rng = random.Random(7)
    a = [v for _, v in w["A"]]
    d = [5.0]
    for i in range(1, len(a)):
        d.append(d[-1] + (a[i] - a[i - 1]) + rng.gauss(0, 0.2))
    w["D"] = list(zip([x for x, _ in w["A"]], d))
    b = CB.bench(w)
    ca = b["targets"]["A"]["concept"]
    assert ca["members"].get("D") == 1 and "+D" in ca["name"]
    assert "C" not in ca["members"]                                  # an independent walk is not in the concept
    assert b["verdict"]["concepts_found"] >= 2


def test_e4_conformal_quantile_and_coverage_are_honest():
    assert CB._conformal_q([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.8) == 9   # ceil(11*0.8)=9th smallest
    b = CB.bench(_world())
    cov = b["targets"]["B"]["conformal"]["ridge_all"]
    assert cov["n"] > 50 and 0.6 <= cov["coverage"] <= 0.97          # ~80% by construction on a stationary world
    assert b["verdict"]["conformal_level"] == 0.8
    md = CB.markdown(b)
    assert "## E2" in md and "## E4" in md


# ── STAGE 1 / STAGE 2 (Emil, 11 Sep 2026): direction first, then the % step ────

def test_direction_is_learned_where_there_is_something_to_learn():
    b = CB.bench(_world())
    dB = b["direction"]["B"]["1"]
    assert dB["wins"] and dB["best_model"] in ("ridge_all", "ridge_concept") and dB["rate"][dB["best_model"]] > 0.8
    dC = b["direction"]["C"]["1"]                                    # an independent random walk
    assert not dC["wins"]
    assert set(b["direction"]["B"]) == {"1", "5", "20"}
    assert "B@1d" in b["verdict"]["direction_wins"] and b["verdict"]["stage"].startswith("2")


def test_overlapping_windows_shrink_the_sample():
    d = CB._direction_verdict({"ridge_all": 60, "ridge_own": 50, "ridge_concept": 50, "ewma": 50,
                               "always_up": 50, "momentum": 45, "train_majority": 50}, 100, 20,
                              ("ridge_all", "ridge_own", "ridge_concept", "ewma"))
    assert d["n_eff"] == 5.0 and not d["wins"]                       # 60% on 5 effective samples is not a win
    d1 = CB._direction_verdict({"ridge_all": 61, "ridge_own": 50, "ridge_concept": 50, "ewma": 50,
                                "always_up": 50, "momentum": 45, "train_majority": 50}, 100, 1,
                               ("ridge_all", "ridge_own", "ridge_concept", "ewma"))
    assert d1["z"] == 2.2 and d1["wins"]


def test_the_percent_range_is_reported_and_the_report_leads_with_direction():
    b = CB.bench(_world())
    pr = b["direction"]["B"]["1"]["pct_range"]["ridge_all"]
    assert pr["n"] > 50 and pr["mean_half_width_pct"] > 0 and 0.6 <= pr["coverage"] <= 0.97
    md = CB.markdown(b)
    assert md.index("## STAGE 1") < md.index("## STAGE 2") < md.index("## E2")
