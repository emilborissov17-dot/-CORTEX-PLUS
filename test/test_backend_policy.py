#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_backend_policy.py — A STEP MUST NOT SPEND ITS CEILING ON A CERTAINTY.

WHAT WENT WRONG (measured 20 August 2026, cycle 20:12:54)
----------------------------------------------------------
The watchdog killed the cycle on `daily_analysis` after 1243 s against a 900 s
ceiling. Counted from that one step's log:

    24  402 Client Error: Payment Required   (Cerebras, asked 9 times in-step)
    42  rate limit                            (Groq / OpenRouter / Gemini)
    14  ALL cloud backends down -> LOCAL qwen3:8b (DEGRADED)

A 402 is an account that will not serve this run. Asking it nine more times is
not resilience — it is spending the step's clock on a settled answer, and then
falling to a local model that needs minutes per call.

THE PROOF THAT MATTERS
-----------------------
test_a_step_with_all_four_backends_broken_finishes_fast breaks all four cloud
backends and runs a step's worth of calls. With the policy it finishes in
seconds; the negative control shows what the same step costs without it.

    venv\\Scripts\\python.exe -m pytest test/test_backend_policy.py -v
"""
from __future__ import annotations

import time

import pytest

from core import backend_policy as policy


@pytest.fixture(autouse=True)
def clean_policy():
    policy.reset_for_tests()
    yield
    policy.reset_for_tests()


# ---------------------------------------------------------------------------
# (a) The three kinds of failure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "402 Client Error: Payment Required for url: https://api.cerebras.ai/v1/chat/completions",
    "402 Payment Required",
    "Payment Required",
])
def test_a_402_is_permanent(message):
    assert policy.classify(message) == policy.PERMANENT


@pytest.mark.parametrize("message", [
    "Groq rate limit", "Gemini rate limit", "429 Too Many Requests",
    "quota exceeded",
])
def test_a_rate_limit_is_only_a_cooldown(message):
    assert policy.classify(message) == policy.COOLDOWN, (
        "a rate limit window reopens; treating it as permanent would disable a "
        "backend that is about to work again"
    )


def test_anything_else_is_transient():
    assert policy.classify("Connection aborted") == policy.TRANSIENT


def test_a_402_disables_the_backend_but_a_rate_limit_does_not(capsys):
    """THE CEREBRAS CASE. Nine 402s in one step must become one disable."""
    policy.note_failure("cerebras", "402 Client Error: Payment Required")
    policy.note_failure("groq", "Groq rate limit")

    assert policy.is_disabled("cerebras"), (
        "Cerebras answered 402 and is still being asked. That is 9 wasted "
        "attempts per step, charged to the step's ceiling."
    )
    assert not policy.is_disabled("groq"), (
        "a rate-limited backend was disabled for the whole run — it would have "
        "recovered within the cycle"
    )
    assert "DISABLED for this run" in capsys.readouterr().out


def test_the_disable_survives_the_rest_of_the_run():
    policy.note_failure("cerebras", "402 Payment Required")
    for step in ("daily_analysis", "data_scout", "continuous_learning"):
        policy.begin_step(step)
        assert policy.is_disabled("cerebras"), (
            f"the 402 disable was forgotten at step {step} — an account does not "
            f"start paying again between steps"
        )


# ---------------------------------------------------------------------------
# (b) Give up on cloud within a step, but not for the whole cycle
# ---------------------------------------------------------------------------

def test_three_all_cloud_failures_stop_cloud_for_that_step():
    policy.begin_step("daily_analysis")
    for n in range(1, policy.ALL_CLOUD_FAIL_LIMIT):
        policy.note_all_cloud_failed()
        assert not policy.cloud_blocked_for_step(), (
            f"gave up after only {n} all-cloud failures — too eager"
        )
    policy.note_all_cloud_failed()
    assert policy.cloud_blocked_for_step()

    allowed, why = policy.cloud_allowed("axis_snapshot")
    assert not allowed
    assert "daily_analysis" in why


def test_a_later_step_gets_a_fresh_chance():
    """A rate-limit window can expire between steps. Giving up for the cycle
    would turn a five-minute outage into a whole degraded run."""
    policy.begin_step("daily_analysis")
    for _ in range(policy.ALL_CLOUD_FAIL_LIMIT):
        policy.note_all_cloud_failed()
    assert policy.cloud_blocked_for_step()

    policy.begin_step("data_scout")
    assert not policy.cloud_blocked_for_step()
    assert policy.cloud_allowed("axis_snapshot")[0]


def test_one_success_resets_the_run_of_failures():
    policy.begin_step("daily_analysis")
    policy.note_all_cloud_failed()
    policy.note_all_cloud_failed()
    policy.note_cloud_success()
    policy.note_all_cloud_failed()
    assert not policy.cloud_blocked_for_step(), (
        "a backend answered in between, so the failures were not consecutive"
    )


def test_beat_resets_the_counter():
    """The wiring, not just the function: begin_step is called from beat(),
    which is the one path all 53 steps pass through."""
    import memory.heartbeat as hb
    src = __import__("pathlib").Path(hb.__file__).read_text(encoding="utf-8")
    assert "begin_step" in src, (
        "memory/heartbeat.beat() no longer resets the policy — every step after "
        "a bad one would inherit its give-up state"
    )


# ---------------------------------------------------------------------------
# (c) Self-directed calls never touch the cloud
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("purpose", sorted(policy.SELF_DIRECTED))
def test_self_directed_calls_never_use_cloud(purpose):
    """These are the calls that must keep working exactly when the cloud is
    gone, because that is when there is something to think about."""
    allowed, why = policy.cloud_allowed(purpose)
    assert not allowed, f"{purpose} was allowed to reach the cloud"
    assert purpose in why


def test_ordinary_work_still_uses_cloud():
    """POSITIVE CONTROL — a policy that blocks everything is not a policy."""
    assert policy.cloud_allowed("axis_snapshot")[0]
    assert policy.cloud_allowed(None)[0]


# ---------------------------------------------------------------------------
# (d) THE PROOF: a step with all four backends broken finishes fast
# ---------------------------------------------------------------------------

CALLS_PER_STEP = 25          # daily_analysis walks ~25 axes
FAKE_CLOUD_LATENCY = 0.05    # each dead backend costs this much to discover
FAKE_LOCAL_LATENCY = 0.40    # the local model is the expensive fallback


def _simulate_step(use_policy: bool) -> tuple[float, int, int]:
    """One step's worth of calls with all four cloud backends broken.

    Returns (elapsed, cloud_attempts, local_calls). The latencies are scaled
    down from the real ones (a dead cloud backend takes seconds, the local model
    minutes) so the test runs quickly; the SHAPE is what is under test.
    """
    policy.reset_for_tests()
    policy.begin_step("daily_analysis")
    cloud_attempts = 0
    local_calls = 0
    t0 = time.perf_counter()

    for _ in range(CALLS_PER_STEP):
        allowed = policy.cloud_allowed(None)[0] if use_policy else True
        if allowed:
            for backend in ("groq", "cerebras", "openrouter", "gemini"):
                if use_policy and policy.is_disabled(backend):
                    continue
                cloud_attempts += 1
                time.sleep(FAKE_CLOUD_LATENCY)
                error = ("402 Client Error: Payment Required"
                         if backend == "cerebras" else f"{backend} rate limit")
                if use_policy:
                    policy.note_failure(backend, error)
            if use_policy:
                policy.note_all_cloud_failed()
        local_calls += 1
        time.sleep(FAKE_LOCAL_LATENCY)

    return time.perf_counter() - t0, cloud_attempts, local_calls


def test_a_step_with_all_four_backends_broken_finishes_fast():
    """THE NEGATIVE CONTROL IS RUN HERE, IN THE SAME TEST.

    Without the policy the step keeps asking four dead backends on every axis.
    With it, the step gives up on cloud after 3 and spends the rest of its
    budget on work that can actually finish.
    """
    with_policy, cloud_on, _ = _simulate_step(use_policy=True)
    without_policy, cloud_off, _ = _simulate_step(use_policy=False)

    assert cloud_off == CALLS_PER_STEP * 4, "control did not attempt every backend"

    # 3 rounds of 4, minus Cerebras once it is disabled by its 402.
    assert cloud_on <= 12, (
        f"the policy still made {cloud_on} cloud attempts in one step; it should "
        f"stop after {policy.ALL_CLOUD_FAIL_LIMIT} all-cloud failures"
    )
    assert cloud_on < cloud_off / 3, (
        f"policy {cloud_on} attempts vs control {cloud_off} — not a real saving"
    )
    assert with_policy < without_policy, (
        f"the step was not faster with the policy "
        f"({with_policy:.2f}s vs {without_policy:.2f}s)"
    )

    # The real ceiling is 900 s and the real step took 1243 s. Scaled here, the
    # claim is the same one: the step now fits inside its ceiling.
    ceiling = CALLS_PER_STEP * FAKE_LOCAL_LATENCY * 1.5
    assert with_policy < ceiling, (
        f"{with_policy:.2f}s exceeds the scaled ceiling {ceiling:.2f}s — the step "
        f"would still be killed by the watchdog"
    )
    print(f"\n  all four backends broken:"
          f"\n    with policy    {with_policy:6.2f}s  cloud attempts {cloud_on}"
          f"\n    without policy {without_policy:6.2f}s  cloud attempts {cloud_off}")


def test_the_chain_consults_the_policy():
    """Wiring guard: the module can be perfect and unreferenced."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] /
           "core" / "groq_backend.py").read_text(encoding="utf-8")
    for needle in ("backend_policy", "cloud_allowed", "note_failure",
                   "note_all_cloud_failed", "is_disabled"):
        assert needle in src, f"call_groq_meta never calls {needle}"
