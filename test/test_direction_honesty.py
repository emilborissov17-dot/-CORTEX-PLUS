# -*- coding: utf-8 -*-
"""test/test_direction_honesty.py — is STAGE 1 (direction) an honest exam? (11 Sep 2026)

Emil: "how exactly do we know it catches a pattern when there is one and invents none
when there is none?" By worlds whose answer we wrote ourselves:
  A — a pure random walk;  B — each day moves `follow` × A's move of yesterday + noise.
Measured by hand on 11 Sep: follow=0 -> 0 false wins in 40 worlds; 0.3 -> 7/20; 0.6 -> 12/12;
1.0 -> 12/12. Pinned here on fewer worlds so it runs on every change:
  * no pattern: at most 1 false win in 10 worlds (the exam does not invent learning)
  * a medium pattern: caught in every one of 3 worlds (the exam can see learning)
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
import cross_series_bench as CB  # noqa: E402


def _world(seed: int, follow: float, n: int = 250) -> dict:
    rng = random.Random(seed)
    ds = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    a, b = [100.0], [50.0]
    for i in range(1, n):
        a.append(a[-1] + rng.gauss(0, 1))
        b.append(b[-1] + follow * ((a[i - 1] - a[i - 2]) if i >= 2 else 0.0) + rng.gauss(0, 1))
    return {"A": list(zip(ds, a)), "B": list(zip(ds, b))}


def test_no_pattern_no_learning_claimed():
    wins = sum(CB.walk(_world(s, 0.0), "B", extras=False)["direction"]["wins"] for s in range(10))
    assert wins <= 1


def test_a_medium_pattern_is_always_caught():
    assert all(CB.walk(_world(100 + s, 0.6), "B", extras=False)["direction"]["wins"] for s in range(3))
