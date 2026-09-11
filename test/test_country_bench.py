# -*- coding: utf-8 -*-
"""test/test_country_bench.py — the static-world transfer bench (10 Sep 2026)."""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("country_bench", REPO / "experiments" / "prophecy" / "country_bench.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)


def _synthetic(n=60, seed=1, signal=True):
    """Countries where the target is a known function of the features (+noise),
    or pure noise when signal=False — the negative control."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        e, g, r, el = rng.uniform(5, 10), rng.uniform(6, 11), rng.uniform(0, 60), rng.uniform(4, 10)
        y = (0.08 * e + 0.05 * g + 0.001 * r) / 1.4 if signal else rng.uniform(0, 1)
        y = min(1.0, max(0.0, y + rng.gauss(0, 0.02)))
        rows.append({"iso": f"C{i:03d}", "year": 2023, "log_energy_per_capita": e, "log_gdp_per_capita": g,
                     "renewables_share_energy": r, "log_elec_per_capita": el,
                     "v2x_rule": y, "v2x_corr_inv": y, "v2x_freexp_altinf": y})
    return rows


def test_leave_one_out_never_shows_the_country_its_own_value():
    table = _synthetic(20)
    seen = []
    def spy(train, x, target, feats):
        seen.append(any(r["iso"] == x["iso"] for r in train)); return 0.0
    cb.loo(table, "v2x_rule", cb.FEATURES, spy)
    assert seen and not any(seen)


def test_negative_control_no_signal_no_win():
    b = cb.bench(_synthetic(60, signal=False))
    r = b["targets"]["v2x_rule"]
    assert r["knn_k5"]["mae"] >= r["baseline_mean"]["mae"] * 0.9, "on pure noise the learner must not look like it learned"


def test_positive_control_known_cause_transfers():
    b = cb.bench(_synthetic(60, signal=True))
    r = b["targets"]["v2x_rule"]
    assert r["ridge_4_features"]["mae"] < r["baseline_mean"]["mae"] * 0.5
    assert r["ridge_4_features"]["closer_than_baseline"] > 45


def test_mutation_features_are_load_bearing(monkeypatch):
    """Ridge that ignores its features collapses to the baseline — proving the features do the predicting."""
    monkeypatch.setattr(cb, "ridge_predict", cb.mean_predict)
    b = cb.bench(_synthetic(60, signal=True))
    r = b["targets"]["v2x_rule"]
    assert r["ridge_4_features"]["mae"] == r["baseline_mean"]["mae"]
