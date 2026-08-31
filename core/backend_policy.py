#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/backend_policy.py — NOT EVERY FAILURE IS THE SAME FAILURE.

WHAT WENT WRONG (measured 20 August 2026, cycle 20:12:54)
----------------------------------------------------------
The cycle was killed by the watchdog on `daily_analysis` after 1243 s against a
900 s ceiling. Inside that one step:

    24  402 Client Error: Payment Required   (Cerebras)
    42  rate limit                            (Groq / OpenRouter / Gemini)
    14  ALL cloud backends down -> LOCAL qwen3:8b (DEGRADED)

Cerebras was asked NINE times in that step and answered 402 every time. A 402 is
not a transient failure — it is an account that will not serve this run at all.
Retrying it is not resilience, it is spending the step's clock on a certainty.
And once all four are exhausted, the chain falls to a local model that takes
minutes per call, so the step cannot finish inside any ceiling.

THE THREE RULES
----------------
  402 / Payment Required  -> PERMANENTLY DISABLED for the rest of this process.
                             Not a cooldown. The account state will not change
                             between now and the end of the cycle.
  429 / rate limit        -> cooldown, as before. This one really is transient.
  3 consecutive all-cloud failures INSIDE ONE STEP
                          -> stop attempting cloud for the rest of that step.
                             The step has already proven the cloud is gone; the
                             remaining axes should go straight to local and let
                             the step finish, degraded, inside its ceiling.

The per-step counter resets on begin_step(). A later step gets a fresh chance,
because a rate limit window can expire between steps.

SELF-DIRECTED CALLS NEVER TOUCH THE CLOUD
------------------------------------------
phase_debrief, brain_stance, autopsy, step_prediction — the system thinking
about ITSELF. These are the calls that must keep working precisely when the
cloud is gone, because that is when there is something to think about. They are
also the calls whose latency is charged to a step's ceiling for no external
benefit. core/brain.py already reaches Ollama directly, so today this is true by
accident; here it becomes true by rule, and a test holds it.

    venv\\Scripts\\python.exe core/backend_policy.py --selftest
"""
from __future__ import annotations

import sys
import threading

# Purposes that are the system reasoning about itself. Never cloud.
SELF_DIRECTED = frozenset({
    "phase_debrief",
    "brain_stance",
    "autopsy",
    "step_prediction",
})

# How many consecutive "every cloud backend failed" events inside ONE step
# before the step gives up on cloud entirely.
ALL_CLOUD_FAIL_LIMIT = 3

PERMANENT, COOLDOWN, TRANSIENT = "permanent", "cooldown", "transient"

_lock = threading.Lock()
_disabled: dict[str, str] = {}          # backend -> reason, for the whole process
_step: str | None = None
_all_cloud_failures_this_step = 0
_local_only = False                     # process-wide: no cloud at all
_local_only_reason = ""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify(exc: BaseException | str) -> str:
    """Which of the three kinds of failure is this?

    Matched on the text because the chain raises plain RuntimeError/ValueError
    with the provider's message inside; there is no typed error to switch on.
    """
    text = str(exc).lower()
    if "402" in text or "payment required" in text:
        return PERMANENT
    if "429" in text or "rate limit" in text or "quota" in text:
        return COOLDOWN
    return TRANSIENT


# ---------------------------------------------------------------------------
# Per-run disabling
# ---------------------------------------------------------------------------

def note_failure(backend: str, exc: BaseException | str) -> str:
    """Record one backend failure. Returns its classification.

    A PERMANENT failure disables the backend for the rest of the process. The
    caller still handles cooldowns itself — this module does not own the clock,
    only the verdict.
    """
    kind = classify(exc)
    if kind == PERMANENT:
        with _lock:
            if backend not in _disabled:
                _disabled[backend] = str(exc)[:200]
                print(f"  [POLICY] {backend} DISABLED for this run "
                      f"— {classify(exc)}: {str(exc)[:90]}")
    return kind


def is_disabled(backend: str) -> bool:
    with _lock:
        return backend in _disabled


def disabled_backends() -> dict[str, str]:
    with _lock:
        return dict(_disabled)


# ---------------------------------------------------------------------------
# Per-step give-up
# ---------------------------------------------------------------------------

def begin_step(step: str | None) -> None:
    """A new step starts: forget how badly the previous one went.

    Called from memory.heartbeat.beat(), which is the one path every step
    passes through.
    """
    global _step, _all_cloud_failures_this_step
    with _lock:
        if step != _step:
            _step = step
            _all_cloud_failures_this_step = 0


def current_step() -> str | None:
    with _lock:
        return _step


def note_all_cloud_failed() -> int:
    """Every cloud backend failed for one call. Returns the running count."""
    global _all_cloud_failures_this_step
    with _lock:
        _all_cloud_failures_this_step += 1
        n = _all_cloud_failures_this_step
    if n == ALL_CLOUD_FAIL_LIMIT:
        print(f"  [POLICY] {n} consecutive all-cloud failures in step "
              f"{_step!r} — cloud is off for the rest of this step")
    return n


def note_cloud_success() -> None:
    """A cloud backend answered: the run of failures is broken."""
    global _all_cloud_failures_this_step
    with _lock:
        _all_cloud_failures_this_step = 0


def cloud_blocked_for_step() -> bool:
    with _lock:
        return _all_cloud_failures_this_step >= ALL_CLOUD_FAIL_LIMIT


# ---------------------------------------------------------------------------
# The one question the chain asks
# ---------------------------------------------------------------------------

def block_cloud(reason: str) -> None:
    """Declare this PROCESS local-only. Not a failure count — a decision.

    Added 21 Aug 2026 for scripts/micro_cycle.py, which promises to run in
    10-15 minutes without touching a cloud model. Until now the only way to make
    that promise true was to hope no step reached for one. A promise enforced by
    hope is a promise with no mechanism, which is the class of defect the whole
    repo is aimed at. This is the mechanism: one flag, checked at the same gate
    every other cloud decision passes through, so there is no second door.
    """
    global _local_only, _local_only_reason
    with _lock:
        _local_only = True
        _local_only_reason = reason
    print(f"  [POLICY] cloud is off for this process — {reason}")


def local_only() -> tuple:
    with _lock:
        return _local_only, _local_only_reason


def cloud_allowed(purpose: str | None = None) -> tuple[bool, str]:
    """May this call try the cloud at all? Returns (allowed, reason)."""
    blocked, why = local_only()
    if blocked:
        return False, f"process declared local-only: {why}"
    if purpose in SELF_DIRECTED:
        return False, f"self-directed call ({purpose}) never uses cloud"
    if cloud_blocked_for_step():
        return False, (f"{ALL_CLOUD_FAIL_LIMIT} consecutive all-cloud failures "
                       f"in step {current_step()!r}")
    return True, "ok"


def reset_for_tests() -> None:
    """Tests only. The process-lifetime state above is deliberately global."""
    global _step, _all_cloud_failures_this_step, _local_only, _local_only_reason
    with _lock:
        _disabled.clear()
        _step = None
        _all_cloud_failures_this_step = 0
        _local_only = False
        _local_only_reason = ""


def _selftest() -> int:
    ok = True
    reset_for_tests()

    print("core/backend_policy.py --selftest")
    checks = [
        ("402 is permanent",
         classify("402 Client Error: Payment Required for url: ...") == PERMANENT),
        ("rate limit is a cooldown", classify("Groq rate limit") == COOLDOWN),
        ("anything else is transient", classify("Connection reset") == TRANSIENT),
    ]

    # A SYNTHETIC NAME ON PURPOSE (31 Aug 2026). This check is about the RULE
    # — a 402 is permanent and disables its backend — not about any one
    # provider. It used to name cerebras, which retired that day; a selftest
    # that dies with the provider it happened to cite was testing the wrong
    # thing. "acme" cannot be retired.
    note_failure("acme", "402 Client Error: Payment Required")
    checks.append(("402 disables the backend", is_disabled("acme")))
    note_failure("groq", "Groq rate limit")
    checks.append(("rate limit does NOT disable", not is_disabled("groq")))

    begin_step("daily_analysis")
    for _ in range(ALL_CLOUD_FAIL_LIMIT):
        note_all_cloud_failed()
    checks.append(("3 all-cloud failures block the step", cloud_blocked_for_step()))
    begin_step("data_scout")
    checks.append(("a new step gets a fresh chance", not cloud_blocked_for_step()))

    allowed, why = cloud_allowed("autopsy")
    checks.append(("self-directed never uses cloud", not allowed))
    allowed, _ = cloud_allowed("axis_snapshot")
    checks.append(("ordinary work may use cloud", allowed))

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    reset_for_tests()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
