#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_kill_policy_wiring.py — THE WATCHDOG ASKS BEFORE IT KILLS.

core/kill_policy.py is tested as a pure decision in test_kill_policy.py. Held
here: that supervisor.decide() actually routes through it, and that the routing
fails in the right direction.

The one that matters most is the replay of the kills the existence ledger blames
— internet_intelligence 6, daily_analysis 5, every one a NORMAL step past its
ceiling waiting on a model. Each destroyed the steps that would have followed.
They must now come out DEGRADE.

Worth keeping straight, and pinned below: last night (22 Aug, 05:09) was NOT one
of those. internet_intelligence sat at 3587s against a 3600s ceiling — thirteen
seconds short of a kill — and then DIED with no CYCLE_FINISHED. The watchdog
never got to decide. A different failure, and the kill policy does not address it.

    venv\\Scripts\\python.exe -m pytest test/test_kill_policy_wiring.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import core.kill_policy as kp  # noqa: E402
import supervisor  # noqa: E402


# ---------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------

def _obs(step, age, ceiling, **kw):
    return kp.Observation(step=step, priority=supervisor._step_priority(step),
                          heartbeat_age_sec=age, ceiling_sec=ceiling, **kw)


def test_last_nights_step_was_not_even_past_its_ceiling_yet():
    """22 Aug 2026, 05:09: step internet_intelligence, heartbeat age 3587s
    against a 3600s ceiling. It DIED (no CYCLE_FINISHED); it was not killed —
    13 seconds short. Pinned so the replay below is not confused with it."""
    d = kp.decide(_obs("internet_intelligence", 3587.0, 3600.0))
    assert d.verdict == kp.WAIT


def test_the_kills_the_ledger_blames_would_now_degrade():
    """The six internet_intelligence kills: a NORMAL step waiting on a model,
    past its ceiling, with a live process doing I/O. Every one destroyed the
    steps that would have followed."""
    d = kp.decide(_obs("internet_intelligence", 2762.0, 2700.0))
    assert d.verdict == kp.DEGRADE, (
        f"the step that ended six nights still gets {d.verdict}: {d.reason}")
    assert d.cause is None

    d = kp.decide(_obs("daily_analysis", 1243.0, 900.0))
    assert d.verdict == kp.DEGRADE, d.reason


def test_a_normal_step_is_never_killed_however_late_it_is():
    for age in (901.0, 3601.0, 86_400.0):
        d = kp.decide(kp.Observation(step="web_intelligence", priority=kp.NORMAL,
                                     heartbeat_age_sec=age, ceiling_sec=900.0))
        assert d.verdict != kp.KILL, (
            f"a NORMAL step was killed at {age}s. Slow is not a reason to kill — "
            f"that is the entire point of this module")


# ---------------------------------------------------------------------------
# The three causes that remain
# ---------------------------------------------------------------------------

def test_a_livelocked_process_is_killed():
    d = kp.decide(kp.Observation(step="web_intelligence", priority=kp.NORMAL,
                                 heartbeat_age_sec=1000.0, ceiling_sec=900.0,
                                 cpu_percent=99.0, io_idle_sec=120.0))
    assert d.verdict == kp.KILL and d.cause == kp.LIVELOCK


def test_missing_telemetry_is_not_a_livelock():
    """None means "not measured", and a measurement nobody took must never kill."""
    for cpu, io in ((None, None), (99.0, None), (None, 120.0)):
        d = kp.decide(kp.Observation(step="web_intelligence", priority=kp.NORMAL,
                                     heartbeat_age_sec=5000.0, ceiling_sec=900.0,
                                     cpu_percent=cpu, io_idle_sec=io))
        assert d.verdict != kp.KILL, (
            f"cpu={cpu} io_idle={io} produced a kill; absence of evidence is not "
            f"evidence of a livelock")


def test_a_critical_step_that_would_publish_stale_data_is_killed():
    d = kp.decide(kp.Observation(step="scoring_engine", priority=kp.CRITICAL,
                                 degraded=True, heartbeat_age_sec=100.0,
                                 ceiling_sec=900.0))
    assert d.verdict == kp.KILL and d.cause == kp.CRITICAL_INVARIANT_BROKEN


def test_a_critical_step_with_no_downstream_consumer_only_degrades():
    d = kp.decide(kp.Observation(step="brain_briefing", priority=kp.CRITICAL,
                                 degraded=True, heartbeat_age_sec=100.0,
                                 ceiling_sec=900.0))
    assert d.verdict == kp.DEGRADE


# ---------------------------------------------------------------------------
# observe() — the impure half
# ---------------------------------------------------------------------------

def test_observe_without_a_pid_measures_nothing_and_kills_nothing(tmp_path):
    obs = kp.observe(pid=None, step="x", heartbeat_age_sec=9999.0,
                     ceiling_sec=1.0, base=tmp_path)
    assert obs.cpu_percent is None and obs.io_idle_sec is None
    assert kp.decide(obs).verdict != kp.KILL


def test_observe_on_a_dead_pid_is_not_a_livelock(tmp_path):
    obs = kp.observe(pid=999_999_999, step="x", base=tmp_path, cpu_interval=0.0)
    assert obs.cpu_percent is None or obs.io_idle_sec is None
    assert kp.decide(obs).verdict != kp.KILL


def test_the_first_observation_of_a_process_reports_unknown_io_idle(tmp_path):
    """One sample cannot establish a span. The supervisor tick does not live
    through 60 seconds, so the first look must not claim idleness."""
    import os
    (tmp_path / "memory").mkdir()
    obs = kp.observe(pid=os.getpid(), step="x", base=tmp_path, cpu_interval=0.0)
    assert obs.io_idle_sec is None, (
        "the first tick claimed to know how long the process had been idle")


def test_a_second_observation_can_measure_idleness(tmp_path):
    import os
    (tmp_path / "memory").mkdir()
    kp.observe(pid=os.getpid(), step="x", base=tmp_path, cpu_interval=0.0)
    obs = kp.observe(pid=os.getpid(), step="x", base=tmp_path, cpu_interval=0.0)
    if obs.io_idle_sec is None:
        pytest.skip("this OS will not report io_counters for our own process")
    assert obs.io_idle_sec >= 0.0


def test_observe_writes_only_into_the_base_it_was_given(tmp_path):
    import os
    (tmp_path / "memory").mkdir()
    kp.observe(pid=os.getpid(), step="x", base=tmp_path, cpu_interval=0.0)
    assert (tmp_path / "memory" / kp.IO_STATE_FILE).exists()


# ---------------------------------------------------------------------------
# The supervisor's helpers
# ---------------------------------------------------------------------------

def test_an_unknown_step_is_treated_as_NORMAL():
    assert supervisor._step_priority("no_such_step") == kp.NORMAL, (
        "guessing CRITICAL would let a typo in the priority table license a kill")


def test_a_known_critical_step_is_reported_critical():
    assert supervisor._step_priority("scoring_engine") == kp.CRITICAL


def test_degraded_is_read_from_the_contract_report(tmp_path, monkeypatch):
    report = tmp_path / "memory" / "step_contract_latest.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"steps": [
        {"step": "scoring_engine", "verdict": "DEGRADED"},
        {"step": "data_scout", "verdict": "OK"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(supervisor, "BASE", tmp_path)
    assert supervisor._step_is_degraded("scoring_engine") is True
    assert supervisor._step_is_degraded("data_scout") is False


def test_an_unreadable_contract_reports_not_degraded(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "BASE", tmp_path)
    assert supervisor._step_is_degraded("scoring_engine") is False, (
        "for a CRITICAL step, `degraded` is half of the only condition that "
        "authorises a kill; it must never be invented")


# ---------------------------------------------------------------------------
# The routing itself
# ---------------------------------------------------------------------------

def test_the_supervisor_consults_the_policy_before_killing():
    import inspect
    src = inspect.getsource(supervisor.decide)
    assert "_kp.decide(" in src, "the watchdog no longer asks the policy"
    assert src.index("_kp.decide(") < src.rindex("_kill_or_fail("), (
        "the policy is consulted after the kill is already decided")


def test_a_broken_policy_falls_back_to_the_old_ceiling_rule():
    """Stated out loud because it is a real trade: if kill_policy cannot answer,
    the watchdog behaves exactly as it did on every prior night — it kills on a
    stale heartbeat. Loud, and no worse than the status quo ante."""
    import inspect
    src = inspect.getsource(supervisor.decide)
    assert "falling back to the ceiling rule" in src
    assert "_kp_decision is not None and not _kp_decision.kill" in src, (
        "a policy that failed to produce a decision must not be read as 'do not "
        "kill' — that would turn an import error into a hung cycle")
