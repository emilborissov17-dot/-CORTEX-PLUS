#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The last viable tier gets the remainder, and an empty cloud stops asking.

Both rules exist because of one measured night (cycle_2026-08-22_112231):
three steps produced nothing while 48-80s of a 120s budget went unoffered,
because the 8b was outside its window and the two tiers that DID exist were
still splitting the budget three ways.

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
                       cloud=lambda: None, local_3b=lambda: None,
                       local_8b=None)
    assert slices == [40.0, 120.0], slices          # was [40.0, 40.0]
    assert res.outcome == sb.DEGRADED


def test_one_viable_tier_gets_the_whole_budget(monkeypatch):
    slices, _ = _run(monkeypatch, [sb.TIMEOUT],
                     cloud=None, local_3b=lambda: None, local_8b=None)
    assert slices == [120.0], slices


def test_three_viable_tiers_still_split_it(monkeypatch):
    slices, _ = _run(monkeypatch, [sb.EMPTY, sb.EMPTY, sb.TIMEOUT],
                     cloud=lambda: None, local_3b=lambda: None,
                     local_8b=lambda: None, priority=sb.CRITICAL)
    assert slices[:2] == [40.0, 40.0], slices
    assert slices[2] == 120.0, slices               # the last one takes the rest


def test_a_normal_step_does_not_count_8b_as_viable(monkeypatch):
    """8b is CRITICAL-only, so on a NORMAL step the 3b is the last viable tier."""
    slices, _ = _run(monkeypatch, [sb.EMPTY, sb.TIMEOUT],
                     cloud=lambda: None, local_3b=lambda: None,
                     local_8b=lambda: None, priority=sb.NORMAL)
    assert slices == [40.0, 120.0], slices


def test_cloud_is_demoted_after_three_empty_tiers(monkeypatch):
    """UPDATED BY ITEM 44.1 (29 Aug 2026), and the update is the item.

    cloud_demoted() used to mean "the trip happened". It now means "the cloud is
    excluded RIGHT NOW", which is a question about the clock: a demotion whose
    cooldowns have all expired is tripped AND eligible for one probe. The old
    identity between the two is precisely how a 180s cooldown became a two-hour
    exclusion on 2026-08-29.

    What this test guards is unchanged and still guarded: three EMPTY tiers trip
    it, and while it is in force the cloud is SKIPPED with a named reason and the
    local tier gets the whole remaining slice. The cooldown pushed below is what
    puts it in force — in production the EMPTY tiers come from rate limits, which
    set exactly such a window.
    """
    sb.reset_cycle()
    assert not sb.cloud_demoted()
    for _ in range(sb.CLOUD_EMPTY_LIMIT):
        _run(monkeypatch, [sb.EMPTY, sb.TIMEOUT],
             cloud=lambda: None, local_3b=lambda: None, local_8b=None)
    assert sb.cloud_state()["tripped"], sb.cloud_state()
    sb.note_cooldown_until(sb._now_wall() + 300.0)     # a live rate-limit window
    assert sb.cloud_demoted(), sb.cloud_state()

    slices, res = _run(monkeypatch, [sb.TIMEOUT],
                       cloud=lambda: None, local_3b=lambda: None,
                       local_8b=None)
    assert slices == [120.0], slices
    skipped = [a for a in res.attempts if a.tier == sb.CLOUD]
    assert skipped and skipped[0].outcome == sb.SKIPPED
    assert "demoted" in (skipped[0].error or "")


def test_the_demotion_is_cycle_scoped(monkeypatch):
    """Still true and still worth guarding: boot clears everything.

    ITEM 44.1 made the demotion TIME-bounded as well as cycle-bounded — it now
    expires with the cooldowns that caused it — but reset_cycle() must still wipe
    the slate, including the pushed cooldown and any probe floor. A demotion that
    survived a boot would be a policy nobody set.
    """
    sb.reset_cycle()
    for _ in range(sb.CLOUD_EMPTY_LIMIT):
        _run(monkeypatch, [sb.EMPTY, sb.TIMEOUT],
             cloud=lambda: None, local_3b=lambda: None, local_8b=None)
    sb.note_cooldown_until(sb._now_wall() + 300.0)
    assert sb.cloud_demoted()
    sb.reset_cycle()                       # what the runner does at boot
    assert not sb.cloud_demoted()
    assert sb.cloud_state()["cloud_empty"] == 0
    assert sb.cloud_state()["tripped"] is False
    assert sb.cloud_state()["cooldown_until_in"] == 0.0, (
        "reset_cycle left a pushed cooldown behind — the next cycle would "
        "inherit an exclusion window from the last one")


def test_a_non_empty_cloud_never_demotes(monkeypatch):
    """TIMEOUT is a slow cloud, not a declining one. Only EMPTY counts."""
    sb.reset_cycle()
    for _ in range(sb.CLOUD_EMPTY_LIMIT + 2):
        _run(monkeypatch, [sb.TIMEOUT, sb.TIMEOUT],
             cloud=lambda: None, local_3b=lambda: None, local_8b=None)
    assert not sb.cloud_demoted(), sb.cloud_state()


def test_the_runner_resets_it_at_boot():
    src = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                    errors="replace")
    assert "step_budget" in src and "reset_cycle()" in src, (
        "cycle-scoped demotion with no boot reset is a permanent policy")
