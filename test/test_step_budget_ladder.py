"""The degradation ladder: a dead cloud must degrade the STEP, not hang the CYCLE.

Every model call here is a stub. Nothing in this file reaches Ollama, a cloud
endpoint, or the network, and nothing starts a cycle. The thing under test is the
control flow, and the control flow is exactly what broke on the live machine:
internet_intelligence blocked on a model that never answered, stopped beating, and
took the whole cycle down with it 6 times.
"""
import threading
import time

import pytest

from core.step_budget import (CLOUD, CRITICAL, DEGRADED, DONE, EMPTY, LOCAL_3B,
                              LOCAL_8B, NORMAL, OK, RAISED, SKIPPED, TIMEOUT,
                              Budget, budget_for, call_with_timeout, percentile,
                              run_with_ladder)


def _budget(seconds=3.0):
    return Budget("test_step", seconds, "ceiling", 0)


def _outcomes(result):
    return {a.tier: a.outcome for a in result.attempts}


# ── the headline: a dead cloud ─────────────────────────────────────────────

def test_a_cloud_that_returns_none_degrades_and_returns():
    """The literal ask: stubbed cloud returns None -> step degrades, cycle proceeds."""
    result = run_with_ladder("test_step", NORMAL, _budget(),
                             cloud=lambda: None, local_3b=lambda: None)

    assert result.outcome == DEGRADED
    assert result.value is None
    assert result.tier is None
    assert _outcomes(result)[CLOUD] == EMPTY
    assert "cycle continues" in result.reason


def test_a_none_returning_cloud_is_not_waited_out():
    """`if None, cancel (no waiting)` — falling through must be instant, not B/3."""
    started = time.monotonic()
    result = run_with_ladder("test_step", NORMAL, _budget(seconds=30.0),
                             cloud=lambda: None, local_3b=lambda: None)
    elapsed = time.monotonic() - started

    assert result.outcome == DEGRADED
    assert elapsed < 1.0, f"declining tiers consumed {elapsed:.1f}s of a 10s slice"


def test_a_cloud_that_hangs_forever_does_not_hang_the_ladder():
    """The real failure mode. A synchronous call here is what killed the cycle."""
    release = threading.Event()

    def hangs_until_released():
        release.wait(timeout=120)
        return "too late"

    try:
        started = time.monotonic()
        result = run_with_ladder("test_step", NORMAL, _budget(seconds=1.5),
                                 cloud=hangs_until_released,
                                 local_3b=lambda: None)
        elapsed = time.monotonic() - started

        assert result.outcome == DEGRADED
        assert _outcomes(result)[CLOUD] == TIMEOUT
        # B=1.5 => slice 0.5s. Generous ceiling; the point is bounded, not exact.
        assert elapsed < 5.0, f"the ladder waited {elapsed:.1f}s on a hung cloud"
    finally:
        release.set()          # never leave the daemon thread parked on a wait


def test_an_abandoned_late_answer_cannot_leak_into_the_result():
    """The honest limit of `abandon`: the thread lives on. Its value must not."""
    release = threading.Event()

    def answers_after_release():
        release.wait(timeout=120)
        return "LATE ANSWER"

    result = run_with_ladder("test_step", NORMAL, _budget(seconds=1.5),
                             cloud=answers_after_release, local_3b=lambda: None)
    assert result.outcome == DEGRADED

    release.set()
    time.sleep(0.2)            # let the abandoned thread finish and return
    assert result.value is None, "a late answer reached a result already returned"


# ── the tiers, in order ────────────────────────────────────────────────────

def test_cloud_answers_and_no_local_model_is_touched():
    calls = []
    result = run_with_ladder(
        "test_step", CRITICAL, _budget(),
        cloud=lambda: "from cloud",
        local_3b=lambda: calls.append(LOCAL_3B) or "3b",
        local_8b=lambda: calls.append(LOCAL_8B) or "8b")

    assert result.outcome == OK
    assert result.tier == CLOUD
    assert result.value == "from cloud"
    assert calls == [], "a tier ran after the ladder already had an answer"


def test_falls_through_to_local_3b_when_cloud_declines():
    result = run_with_ladder("test_step", NORMAL, _budget(),
                             cloud=lambda: None,
                             local_3b=lambda: "from 3b")

    assert result.outcome == OK
    assert result.tier == LOCAL_3B
    assert result.value == "from 3b"


def test_8b_runs_for_a_critical_step():
    result = run_with_ladder("test_step", CRITICAL, _budget(),
                             cloud=lambda: None,
                             local_3b=lambda: None,
                             local_8b=lambda: "from 8b")

    assert result.outcome == OK
    assert result.tier == LOCAL_8B


def test_8b_is_never_loaded_for_a_normal_step():
    """The expensive model is the one thing priority actually gates."""
    loaded = []

    result = run_with_ladder("test_step", NORMAL, _budget(),
                             cloud=lambda: None,
                             local_3b=lambda: None,
                             local_8b=lambda: loaded.append(True) or "from 8b")

    assert result.outcome == DEGRADED
    assert loaded == [], "8b was loaded for a NORMAL step"
    assert _outcomes(result)[LOCAL_8B] == SKIPPED


def test_8b_is_skipped_when_the_budget_is_already_spent():
    """CRITICAL is necessary but not sufficient — `and budget remains`."""
    ticks = iter([0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    loaded = []

    result = run_with_ladder("test_step", CRITICAL, _budget(seconds=10.0),
                             cloud=lambda: None,
                             local_3b=lambda: None,
                             local_8b=lambda: loaded.append(True) or "from 8b",
                             now=lambda: next(ticks))

    assert result.outcome == DEGRADED
    assert loaded == []
    assert _outcomes(result)[LOCAL_8B] == SKIPPED


# ── nothing here raises, nothing here kills ────────────────────────────────

def test_a_raising_tier_is_recorded_and_the_ladder_continues():
    def boom():
        raise RuntimeError("ollama connection refused")

    result = run_with_ladder("test_step", NORMAL, _budget(),
                             cloud=boom, local_3b=lambda: "from 3b")

    assert result.outcome == OK
    assert result.tier == LOCAL_3B
    assert _outcomes(result)[CLOUD] == RAISED
    assert "ollama connection refused" in result.attempts[0].error


def test_every_tier_failing_returns_a_verdict_rather_than_raising():
    def boom():
        raise RuntimeError("down")

    result = run_with_ladder("test_step", CRITICAL, _budget(),
                             cloud=boom, local_3b=boom, local_8b=boom)

    assert result.outcome == DEGRADED
    assert result.degraded is True
    assert result.value is None


def test_missing_callables_are_skipped_not_crashed():
    result = run_with_ladder("test_step", NORMAL, _budget(), cloud=None,
                             local_3b=None, local_8b=None)
    assert result.outcome == DEGRADED
    assert all(a.outcome == SKIPPED for a in result.attempts)


# ── the budget ─────────────────────────────────────────────────────────────

def test_budget_is_p95_times_one_and_a_half_not_three():
    baseline = {"a_step": {"runs": [{"seconds": s} for s in (10, 20, 30, 40)]}}
    b = budget_for("a_step", baseline=baseline, ceilings={"_default": 100000})

    assert b.source == "p95"
    assert b.seconds == pytest.approx(40 * 1.5)
    assert b.per_tier == pytest.approx(20.0)


def test_budget_never_exceeds_the_human_ceiling():
    """The clamp. config/scheduler.json says ceilings are human-tunable only."""
    baseline = {"a_step": {"runs": [{"seconds": s} for s in (2397, 2510)]}}
    b = budget_for("a_step", baseline=baseline, ceilings={"a_step": 3600})

    assert b.seconds == 3600, "a learned budget widened a human-set ceiling"
    assert b.source == "p95_clamped_to_ceiling"


def test_budget_falls_back_to_the_ceiling_without_history():
    b = budget_for("never_run", baseline={}, ceilings={"_default": 900})
    assert b.source == "ceiling"
    assert b.seconds == 900
    assert b.runs_seen == 0


def test_a_single_run_is_not_enough_for_a_percentile():
    """Matches core/step_contract.p95, which returns None below two samples."""
    assert percentile([42.0], 0.95) is None
    b = budget_for("a_step", baseline={"a_step": {"runs": [{"seconds": 42}]}},
                   ceilings={"_default": 900})
    assert b.source == "ceiling"


def test_budget_finds_history_filed_under_the_agent_label():
    """The baseline is keyed by _run() labels, the cycle map by step names."""
    baseline = {"internet_agent": {"runs": [{"seconds": s} for s in (100, 200)]}}
    b = budget_for("internet_intelligence", baseline=baseline,
                   ceilings={"_default": 100000})

    assert b.source == "p95", "step name failed to find its own history via ALIASES"
    assert b.runs_seen == 2


def test_percentile_agrees_with_step_contract_p95():
    """Two percentile definitions over one history would let the budget and the
    SLOW verdict disagree about the same step."""
    from core.step_contract import p95 as contract_p95

    for values in ([1.0, 2.0], [5, 5, 5, 100], [10, 20, 30, 40, 50], [3.5, 1.25]):
        assert percentile(list(values), 0.95) == contract_p95(list(values))


def test_a_tiny_budget_is_floored_so_thirds_stay_usable():
    b = budget_for("a_step", baseline={"a_step": {"runs": [{"seconds": s}
                                                           for s in (0.1, 0.2)]}},
                   ceilings={"_default": 900})
    assert b.seconds >= 30.0
    assert b.per_tier >= 10.0


# ── the primitive ──────────────────────────────────────────────────────────

def test_call_with_timeout_reports_each_shape():
    assert call_with_timeout(lambda: "v", 5)[:2] == (DONE, "v")
    assert call_with_timeout(lambda: None, 5)[0] == EMPTY

    outcome, value, error, _ = call_with_timeout(
        lambda: (_ for _ in ()).throw(ValueError("nope")), 5)
    assert outcome == RAISED and value is None and "nope" in error

    release = threading.Event()
    try:
        outcome, value, _, elapsed = call_with_timeout(
            lambda: release.wait(timeout=120), 0.3)
        assert outcome == TIMEOUT and value is None
        assert elapsed < 3.0
    finally:
        release.set()


def test_the_attempt_thread_is_a_daemon():
    """A non-daemon abandoned thread would hold the interpreter open at exit."""
    seen = {}

    def record():
        seen["daemon"] = threading.current_thread().daemon
        return "done"

    call_with_timeout(record, 5)
    assert seen["daemon"] is True


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_worker_killed_by_a_baseexception_reports_raised_not_empty():
    """A crash must not pass for a decline.

    `except Exception` deliberately does not catch this (test_no_bare_except.py
    keeps that allowlist small), so the `done` flag is what tells the two apart.
    Without it, sys.exit() inside a model client would look exactly like a model
    that answered None — and the ladder would record a declined answer where a
    crash happened.
    """
    def dies_hard():
        raise SystemExit(3)

    outcome, value, error, _ = call_with_timeout(dies_hard, 5)

    assert outcome == RAISED
    assert value is None
    assert "died without returning" in error
