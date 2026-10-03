#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The last viable tier gets the remainder.

The rule exists because of one measured night (cycle_2026-08-22_112231): three steps
produced nothing while 48-80s of a 120s budget went unoffered, because the 8b was
outside its window and the tiers that DID exist were still splitting the budget three
ways. C-CLOUD-2 (3 Oct 2026, R45): the cloud tier and its demotion are deleted; the
tiers are the local 3b and, for a CRITICAL step, the 8b.

The slice each tier is handed is what these tests read. call_with_timeout is
replaced by a recorder, so no thread sleeps and no clock is involved.
"""
from __future__ import annotations

import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import core.step_budget as sb  # noqa: E402


class Recorder:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.slices = []
        self.i = 0

    def __call__(self, fn, timeout_sec):
        outcome = self.outcomes[min(self.i, len(self.outcomes) - 1)]
        self.slices.append(round(timeout_sec, 1))
        self.i += 1
        return outcome, None, None, 0.0


def _run(monkeypatch, outcomes, **kw):
    rec = Recorder(outcomes)
    monkeypatch.setattr(sb, "call_with_timeout", rec)
    budget = sb.Budget("s", 120.0, "test", 0)
    res = sb.run_with_ladder("s", kw.pop("priority", sb.NORMAL), budget,
                             now=lambda: 0.0, **kw)
    return rec.slices, res


def test_two_viable_tiers_give_the_last_one_the_remainder(monkeypatch):
    slices, res = _run(monkeypatch, [sb.EMPTY, sb.TIMEOUT],
                       local_3b=lambda: None, local_8b=lambda: None, priority=sb.CRITICAL)
    assert slices == [40.0, 120.0], slices
    assert res.outcome == sb.DEGRADED


def test_one_viable_tier_gets_the_whole_budget(monkeypatch):
    slices, _ = _run(monkeypatch, [sb.TIMEOUT], local_3b=lambda: None, local_8b=None)
    assert slices == [120.0], slices


def test_a_normal_step_does_not_count_8b_as_viable(monkeypatch):
    """8b is CRITICAL-only, so on a NORMAL step the 3b is the last viable tier."""
    slices, res = _run(monkeypatch, [sb.TIMEOUT],
                       local_3b=lambda: None, local_8b=lambda: None, priority=sb.NORMAL)
    assert slices == [120.0], slices
    skipped = [a for a in res.attempts if a.tier == sb.LOCAL_8B]
    assert skipped and skipped[0].outcome == sb.SKIPPED


def test_mutation_a_fixed_third_would_starve_the_last_tier(monkeypatch):
    """What the rule replaced: every tier capped at B/3."""
    budget = sb.Budget("s", 120.0, "test", 0)
    assert round(budget.per_tier, 1) == 40.0
    slices, _ = _run(monkeypatch, [sb.TIMEOUT], local_3b=lambda: None, local_8b=None)
    assert slices[0] > budget.per_tier, "the last viable tier must get more than a third"
