#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_memory_before_spawn.py — the supervisor asks the machine before it spends the night.

WHAT HAPPENED, 13 September 2026, from memory/existence_ledger.jsonl:

    07:54  CYCLE_DIED
    07:59  MISSED_RUN_CATCHUP  -> spawned with 2283 MB free -> died 09:29
    09:34  MISSED_RUN_CATCHUP  -> spawned with  138 MB free -> died 09:49
    09:49  CYCLE_FAILED_BUDGET_EXHAUSTED

The child carries the survival gate at fast_cycle_runner.py:2571 and never reached
it: the flight recorder shows the 09:34 run dying eight seconds in, inside
core/brain.py:409, asking a language model about the boot heartbeat with 46.7 MB
free. Everything the supervisor checked before spawning — the lock, the budget,
the schedule, the grace window — is bookkeeping about time. Nothing looked at the
machine, so the restart budget was spent in fifteen minutes on a machine that
could not have held a cycle at any point in them.

THIS IS NOT A NEW POLICY. config/scheduler.json already carries
max_refusal_retries_per_day: 3, and core/aggressive_cleanup already runs before a
refusal is charged. Memory simply enters the path that was already there.

THE MUTATION TEST is test_the_supervisor_does_not_spawn_when_the_gate_refuses:
it drives the real tick() into the real START branch with the real
core.homeostasis.assess monkeypatched to refuse, and asserts spawn_cycle was never
called. Delete the two lines at the call site and it goes red.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import supervisor as sup                       # noqa: E402

CFG = {"daily_hour": 3, "catchup_grace_hours": 20, "max_restarts_per_day": 2,
       "max_refusal_retries_per_day": 3, "step_ceilings_sec": {"_default": 900}}

REFUSE = {"can_start": False,
          "abort_reason": "RAM 99% (0.1GB free) — insufficient to run safely."}
ALLOW = {"can_start": True, "abort_reason": None}


def at(hour: int) -> datetime:
    return datetime.now().astimezone().replace(hour=hour, minute=5, second=0,
                                               microsecond=0)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    from memory import existence_ledger as el
    monkeypatch.setattr(sup, "STATE_PATH", tmp_path / "scheduler_state.json")
    monkeypatch.setattr(sup, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "BODY_SENSE_DIR", tmp_path / "body_sensorium")
    monkeypatch.setattr(el, "LEDGER_PATH", tmp_path / "existence_ledger.jsonl")
    # These tests are about the SPINE's START branch; today's collectors (task #8
    # B.B, test_collectors.py) are taken as done so the spine is the next action.
    monkeypatch.setattr(sup, "_collectors_state", lambda state, now: "done")
    return tmp_path


# ── the decision function, in isolation ──────────────────────────────────────

def test_an_allowing_gate_allows_the_spawn():
    ok, info = sup.memory_allows_spawn(at(12), CFG, assess=lambda: ALLOW)
    assert ok is True
    assert info["verdict"] == "the gate allows the start"
    assert info["before"]["can_start"] is True


def test_a_refusing_gate_that_cleaning_cures_charges_nothing():
    """A refusal that cleaning cured is not a refusal — Emil, 27 Aug 2026."""
    seq = [REFUSE, ALLOW]
    cleaned = []
    ok, info = sup.memory_allows_spawn(at(12), CFG, assess=lambda: seq.pop(0),
                                       clean=lambda: cleaned.append(1))
    assert ok is True, "cleaning cured the gate and the spawn was still refused"
    assert cleaned == [1], "the cleaning never ran"
    assert "cured" in info["verdict"] and "nothing is charged" in info["verdict"]


def test_a_gate_that_still_refuses_after_cleaning_refuses_the_spawn():
    ok, info = sup.memory_allows_spawn(at(12), CFG, assess=lambda: REFUSE,
                                       clean=lambda: None)
    assert ok is False
    assert info["verdict"] == "the gate still refuses after cleaning"
    assert info["after"]["abort_reason"] == REFUSE["abort_reason"]


def test_cleaning_runs_before_the_refusal_and_not_after():
    order = []
    def _assess():
        order.append("assess")
        return REFUSE
    sup.memory_allows_spawn(at(12), CFG, assess=_assess,
                            clean=lambda: order.append("clean"))
    assert order == ["assess", "clean", "assess"], order


def test_an_unavailable_gate_fails_OPEN():
    """A broken import must not become a system that never wakes up. That is a
    worse failure than the one this guards against, and it is silent."""
    def _boom():
        raise ImportError("no homeostasis here")
    ok, info = sup.memory_allows_spawn(at(12), CFG, assess=_boom)
    assert ok is True
    assert "failing open" in info["verdict"]


def test_the_recorded_numbers_are_real_and_the_decision_is_not_made_from_them():
    """The psutil reading is written down so a refusal can be checked later. The
    verdict still comes from the gate: here the gate ALLOWS while the machine is
    whatever it is, and the answer follows the gate."""
    ok, info = sup.memory_allows_spawn(at(12), CFG, assess=lambda: ALLOW)
    assert ok is True
    seen = info["before"]
    assert seen["ram_free_mb"] is None or seen["ram_free_mb"] > 0
    assert seen["ram_percent"] is None or 0 <= seen["ram_percent"] <= 100


# ── the accounting: a refusal, never a restart ───────────────────────────────

def test_a_refusal_is_charged_to_the_refusal_pool_and_not_the_restart_pool(sandbox):
    state = {}
    now = at(12)
    act = sup._memory_refusal_action(now, CFG, state, {"verdict": "v",
                                                       "after": {"abort_reason": "RAM 99%"}})
    night = sup.cycle_day(now, CFG)
    assert state["refusals"][night] == 1
    assert not state.get("restarts"), "a refusal was charged as a restart"
    assert act.kind == sup.NOTHING


def test_the_day_stays_owed_so_a_recovered_machine_can_still_run(sandbox):
    """'not now' must not become 'not tonight'. The next tick may find memory
    freed, and the night is still owed."""
    state = {"last_run_date": None}
    sup._memory_refusal_action(at(12), CFG, state, {"verdict": "v"})
    assert not state.get("last_run_date")
    assert "survival_sleep" not in state


def test_at_the_budget_it_stops_trying_and_says_so(sandbox):
    night = sup.cycle_day(at(12), CFG)
    state = {"refusals": {night: 3}}
    act = sup._memory_refusal_action(at(12), CFG, state, {"verdict": "v"})
    assert act.kind == sup.SURVIVAL_SLEEP
    assert state["survival_sleep"]["refusals"] == 3
    assert state["refusals"][night] == 3, "the pool was charged past its budget"


# ── the mutation test: remove the call site and this goes red ────────────────

def test_the_supervisor_does_not_spawn_when_the_gate_refuses(sandbox, monkeypatch):
    """The real tick(), the real START branch, the real call site."""
    import core.homeostasis as homeo
    spawned = []
    monkeypatch.setattr(homeo, "assess", lambda verbose=True: REFUSE)
    monkeypatch.setattr(sup, "spawn_cycle", lambda *a, **k: spawned.append(a) or 4242)
    monkeypatch.setattr(sup, "load_config", lambda *a, **k: CFG, raising=False)
    try:
        from core import aggressive_cleanup as ac
        monkeypatch.setattr(ac, "cure_refusal", lambda **k: {"cured": False,
                                                             "counted": True,
                                                             "why": "test"})
    except Exception:
        pass

    act = sup.tick(now=at(12))

    assert spawned == [], (
        f"the supervisor spawned a cycle while the gate was refusing: {act.kind}. "
        f"The two lines in front of spawn_cycle are the guard; without them the "
        f"night of 13 Sep 2026 repeats.")
    st = sup.load_state()
    night = sup.cycle_day(at(12), CFG)
    assert (st.get("refusals") or {}).get(night, 0) >= 1, "no refusal was charged"
    assert not (st.get("restarts") or {}).get(night), "a restart was charged instead"


def test_the_supervisor_does_spawn_when_the_gate_allows(sandbox, monkeypatch):
    """The other direction, so the guard cannot pass by refusing everything."""
    import core.homeostasis as homeo
    spawned = []
    monkeypatch.setattr(homeo, "assess", lambda verbose=True: ALLOW)
    monkeypatch.setattr(sup, "spawn_cycle", lambda *a, **k: spawned.append(a) or 4242)
    sup.tick(now=at(12))
    assert spawned, "the gate allowed the start and nothing was spawned"
