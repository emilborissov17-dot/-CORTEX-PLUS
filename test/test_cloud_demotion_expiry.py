# -*- coding: utf-8 -*-
"""ITEM 44.1 — a transient failure must not outlive its own recovery signal.

WHAT HAPPENED, MEASURED FROM THE CYCLE OF 2026-08-29. Groq was rate-limited
early. Three cloud tiers came back EMPTY. At log line 1644 the cloud was DEMOTED
"for the rest of this cycle". From that point 66 of the cycle's 71 local answers
had NO cloud rung attempted at all, and zero cloud attempts appear in the log for
the remaining two hours and twenty minutes.

The cooldowns that caused it are 60/120/180s, capped. THE DEMOTION OUTLIVED THEM
BY TWO HOURS. Kimi:

    "Tie demotion lifetime to the longest active cooldown expiry. Criterion:
     transient failures (429s) should not outlast their own recovery signal.
     When the last cooldown expires, re-probe the cloud tier before permanently
     defaulting to local."

AND HIS OBJECTION, WHICH THE DESIGN MUST ANSWER RATHER THAN SURVIVE:

    "Re-probing after cooldown expiry risks hammering a rate-limited backend,
     getting the free tier banned or IP-blocked, turning a transient rate limit
     into permanent account loss."

The answer is not the backoff alone — it is the PRECONDITION. A probe may only
happen after every backend's own signalled cooldown window has already elapsed,
so a probe is by construction never sent into a window the provider told us
about. The exponential floor covers the remaining case: the provider's real
window was longer than the one it declared. test_a_probe_is_never_sent_into_an_
active_cooldown is the precondition; test_a_failed_probe_rearms_with_a_longer_
floor is the floor.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import step_budget as sb  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_demotion_state():
    """Every test starts from boot state and leaves it there. The demotion is
    process-global by design, so a test that leaked it would poison the rest of
    the suite in file order — which is the kind of failure nobody attributes."""
    sb.reset_cycle()
    yield
    sb.reset_cycle()


def _trip_demotion():
    """Drive the real counter to the limit rather than setting a private flag,
    so the test exercises the path the cycle takes.

    THE PRECONDITION IS ON THE TRIP, NOT ON cloud_demoted(), and the difference
    is the item. Before 44.1 the two were the same question. Now "the demotion
    tripped" is a fact about the past and "the cloud is excluded right now" is a
    question about the clock — a demotion whose cooldowns have all expired is
    tripped AND eligible for a probe. Asserting cloud_demoted() here would be
    asserting the stickiness this change removes.
    """
    for _ in range(sb.CLOUD_EMPTY_LIMIT):
        sb._note_cloud_outcome(sb.EMPTY)
    assert sb._cloud_demoted_at is not None, "precondition: demotion did not trip"


# ── (a) demotion set, all cooldowns expired -> cloud is eligible ────────────

def test_when_every_cooldown_has_expired_the_cloud_is_eligible_again():
    """THE CORE OF THE ITEM. Today cloud_demoted() is a sticky boolean that
    stays True until reset_cycle() at the next boot, so this fails on HEAD."""
    _trip_demotion()
    sb.note_cooldown_until(sb._now_wall() - 1.0)      # expired one second ago
    assert sb.cloud_demoted() is False, (
        "the demotion outlived every cooldown that caused it. A 429 is a "
        "time-bounded signal; a demotion that ignores its expiry converts a "
        "transient failure into a two-hour policy.")


# ── (b) demotion set, a cooldown still active -> cloud is NOT probed ───────

def test_a_probe_is_never_sent_into_an_active_cooldown():
    """KIMI'S OBJECTION, ANSWERED BY PRECONDITION RATHER THAN BY BACKOFF.
    While any backend's own signalled window is still open, the cloud stays
    demoted and no probe is attempted. A probe can therefore never be sent into
    a window the provider told us to wait out."""
    _trip_demotion()
    sb.note_cooldown_until(sb._now_wall() + 120.0)    # still cooling
    assert sb.cloud_demoted() is True, (
        "the cloud was made eligible while a backend's own cooldown was still "
        "running — this is precisely the hammering Kimi warned about")


# ── (c) a failed probe re-arms with a strictly longer floor ────────────────

def test_a_failed_probe_rearms_with_a_strictly_longer_floor():
    """One probe, not a resumption. If it comes back EMPTY the demotion returns
    with a longer floor each time, so a provider whose real window exceeded its
    declared one is not asked again at the same cadence."""
    _trip_demotion()
    sb.note_cooldown_until(sb._now_wall() - 1.0)
    assert sb.cloud_demoted() is False                # eligible: the probe may go

    first = sb.note_probe_failed()                    # probe came back EMPTY
    assert sb.cloud_demoted() is True, "a failed probe must re-arm the demotion"

    sb.note_cooldown_until(sb._now_wall() - 1.0)      # cooldowns expired again
    assert sb.cloud_demoted() is True, (
        "the re-armed floor was ignored — after a failed probe the demotion must "
        "hold for its own floor even once cooldowns have expired")

    # A SECOND failed probe, because the claim is about GROWTH and one floor
    # cannot be compared with itself. (The first draft of this test read
    # probe_floor_sec() after a single failure and asserted it exceeded the
    # value that produced it — an assertion that could never hold. Found by
    # running the tests against HEAD before writing the fix, which is the reason
    # that order is required.)
    second = sb.note_probe_failed()
    assert second > first, (
        f"the floor did not grow: {first}s then {second}s. Without growth a "
        f"backend whose real window is longer than its declared one is probed "
        f"at a fixed cadence forever.")


def test_the_probe_is_one_attempt_and_not_a_burst():
    """'ONE probe, not a resumption' has to be visible in the state, not only in
    a comment: after eligibility is consumed by a probe, the next question gets
    False until the floor expires."""
    _trip_demotion()
    sb.note_cooldown_until(sb._now_wall() - 1.0)
    assert sb.cloud_demoted() is False
    sb.note_probe_failed()
    assert sb.cloud_demoted() is True
    assert sb.cloud_demoted() is True                 # asked twice, still armed


def test_a_successful_probe_clears_the_demotion_entirely():
    _trip_demotion()
    sb.note_cooldown_until(sb._now_wall() - 1.0)
    sb.note_probe_succeeded()
    assert sb.cloud_demoted() is False
    assert sb.cloud_state()["cloud_empty"] == 0, (
        "a successful probe must reset the empty counter too, or the next single "
        "empty tier re-trips a demotion that was just disproved")


# ── (d) a local-tier answer counts as degraded ─────────────────────────────

def test_a_local_tier_answer_increments_the_degraded_count():
    """THE DISHONEST COUNTER. On 2026-08-29 every [BUDGET] line said degraded=0
    while twelve step contracts said DEGRADED, because degraded_calls only
    counted "no tier answered" — and a local answer returns OK with
    tier=local_3b. Kimi: "The budget ledger's degraded=0 is dishonest because it
    reports functional success while hiding that scored outputs came from a
    model the provenance system cannot trust."
    """
    sb.begin_step("t_local", sb.NORMAL, ceilings={"_default": 900})
    try:
        res = sb.LadderResult("t_local", sb.OK, sb.LOCAL_3B, "x", 900.0, 1.0,
                              [], "answered by local_3b")
        sb._charge(1.0, res)
        st = sb.current_step()
        assert st["degraded_calls"] == 1, (
            "a local-tier answer was not counted as degraded; the budget ledger "
            "would report degraded=0 for a step that ran entirely on the 3B")
    finally:
        sb.end_step()


def test_no_tier_answered_keeps_its_own_separate_name():
    """The old fact is REAL and DIFFERENT — 'nothing answered at all' is not the
    same event as 'the local model answered'. One word, two meanings, was the
    bug; the fix is two names, not a redefinition that loses one of them."""
    sb.begin_step("t_none", sb.NORMAL, ceilings={"_default": 900})
    try:
        res = sb.LadderResult("t_none", sb.DEGRADED, None, None, 900.0, 1.0,
                              [], "no tier produced a result")
        sb._charge(1.0, res)
        st = sb.current_step()
        assert st["no_tier_calls"] == 1, "the no-tier count lost its own name"
        assert st["degraded_calls"] == 1, (
            "a step where nothing answered is degraded too — the contract says "
            "so, and the ledger must agree")
    finally:
        sb.end_step()


def test_a_cloud_answer_is_not_degraded():
    """The negative control. Without it, a counter that simply incremented on
    every call would pass both tests above."""
    sb.begin_step("t_cloud", sb.NORMAL, ceilings={"_default": 900})
    try:
        res = sb.LadderResult("t_cloud", sb.OK, sb.CLOUD, "x", 900.0, 1.0,
                              [], "answered by cloud")
        sb._charge(1.0, res)
        st = sb.current_step()
        assert st["degraded_calls"] == 0 and st["no_tier_calls"] == 0
    finally:
        sb.end_step()
