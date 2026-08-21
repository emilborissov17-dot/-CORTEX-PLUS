"""Killing is right only three ways. Everything else degrades.

The case these tests are built around is real and dated. On 21 Aug 2026 at 16:08
UTC the watchdog killed pid 132556 because internet_intelligence had not beaten
for 2762s against a 2700s ceiling. Nothing was corrupt and nothing was looping —
a model was slow. The cycle died and the 26 steps after it lost the night. The
existence ledger holds ten more of the same shape.

test_yesterdays_kill_would_not_happen_now replays exactly that observation.
"""
import pytest

from core.kill_policy import (CRITICAL_INVARIANT_BROKEN, CUDA_FATAL_STATES,
                              CUDA_UNRECOVERABLE, DEGRADE, KILL, LIVELOCK,
                              LIVELOCK_CPU_PERCENT, LIVELOCK_IO_IDLE_SEC,
                              SAFETY_INVARIANTS, WAIT, KillDecision, Observation,
                              broken_invariant, decide)
from core.step_budget import CRITICAL, NORMAL


# ── the case this module was written for ───────────────────────────────────

def test_yesterdays_kill_would_not_happen_now():
    """pid 132556, 16:08 UTC, 21 Aug 2026 — replayed exactly."""
    d = decide(Observation("internet_intelligence", priority=NORMAL,
                           heartbeat_age_sec=2762.0, ceiling_sec=2700.0,
                           cpu_percent=3.0, io_idle_sec=0.5, cuda_state="OK"))

    assert d.verdict == DEGRADE
    assert d.kill is False
    assert "slow is not a reason to kill" in d.reason


def test_a_normal_step_is_never_killed_however_late_it_is():
    for age in (901, 5_000, 50_000, 10 ** 9):
        d = decide(Observation("web_intelligence", priority=NORMAL,
                               heartbeat_age_sec=age, ceiling_sec=900))
        assert d.verdict == DEGRADE, f"a NORMAL step was killed at {age}s"


def test_a_healthy_long_step_is_left_alone():
    d = decide(Observation("web_intelligence", priority=NORMAL,
                           heartbeat_age_sec=2400, ceiling_sec=3600))
    assert d.verdict == WAIT
    assert d.cause is None


# ── (a) a CRITICAL step whose stale output would be published as fresh ─────

def test_a_degraded_critical_step_that_breaks_an_invariant_is_killed():
    d = decide(Observation("scoring_engine", priority=CRITICAL, degraded=True))

    assert d.verdict == KILL
    assert d.cause == CRITICAL_INVARIANT_BROKEN
    assert "stamped with today's date" in d.reason


def test_a_degraded_critical_step_with_no_invariant_only_degrades():
    """CRITICAL is not by itself a licence to kill."""
    d = decide(Observation("brain_briefing", priority=CRITICAL, degraded=True))

    assert d.verdict == DEGRADE
    assert d.cause is None
    assert "the cycle continues" in d.reason


def test_a_critical_step_that_is_merely_slow_is_not_killed():
    """Not degraded yet — still working. The invariant is about missing output."""
    d = decide(Observation("scoring_engine", priority=CRITICAL, degraded=False,
                           heartbeat_age_sec=9_000, ceiling_sec=900))
    assert d.verdict == DEGRADE
    assert d.cause is None


def test_a_degraded_normal_step_on_an_invariant_name_is_not_killed():
    """The invariant fires on CRITICAL only, so a mis-set priority table cannot
    silently turn a NORMAL step into a killable one."""
    d = decide(Observation("scoring_engine", priority=NORMAL, degraded=True))
    assert d.verdict == DEGRADE


def test_broken_invariant_needs_the_step_to_actually_be_degraded():
    assert broken_invariant("scoring_engine", degraded=False) is None
    assert broken_invariant("scoring_engine", degraded=True)
    assert broken_invariant("browser_scout", degraded=True) is None


def test_the_invariant_table_can_be_injected():
    d = decide(Observation("browser_scout", priority=CRITICAL, degraded=True),
               invariants={"browser_scout": "a made-up invariant"})
    assert d.verdict == KILL
    assert "a made-up invariant" in d.reason


# ── (b) livelock ───────────────────────────────────────────────────────────

def test_livelock_is_killed():
    d = decide(Observation("daily_analysis", priority=NORMAL,
                           cpu_percent=99.0, io_idle_sec=61.0))

    assert d.verdict == KILL
    assert d.cause == LIVELOCK
    assert "burning, not working" in d.reason


def test_high_cpu_with_live_io_is_a_working_step():
    d = decide(Observation("daily_analysis", cpu_percent=99.0, io_idle_sec=0.2))
    assert d.verdict == WAIT


def test_idle_io_at_low_cpu_is_a_step_waiting_on_a_model():
    """The exact profile of the step we just stopped killing."""
    d = decide(Observation("internet_intelligence", cpu_percent=2.0,
                           io_idle_sec=3_000.0, heartbeat_age_sec=3_000,
                           ceiling_sec=2_700))
    assert d.verdict == DEGRADE
    assert d.cause is None


def test_livelock_needs_the_full_sixty_seconds():
    d = decide(Observation("daily_analysis", cpu_percent=99.0,
                           io_idle_sec=LIVELOCK_IO_IDLE_SEC - 0.1))
    assert d.verdict == WAIT

    d = decide(Observation("daily_analysis", cpu_percent=99.0,
                           io_idle_sec=LIVELOCK_IO_IDLE_SEC))
    assert d.verdict == KILL


def test_livelock_needs_the_cpu_threshold_too():
    d = decide(Observation("daily_analysis",
                           cpu_percent=LIVELOCK_CPU_PERCENT - 0.1,
                           io_idle_sec=600.0))
    assert d.verdict == WAIT


def test_missing_telemetry_never_invents_a_livelock():
    """psutil unavailable must not read as 'burning'."""
    for cpu, io in ((None, None), (99.0, None), (None, 600.0)):
        d = decide(Observation("daily_analysis", cpu_percent=cpu, io_idle_sec=io))
        assert d.verdict != KILL, f"killed on cpu={cpu} io={io}"


# ── (c) CUDA ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("state", sorted(CUDA_FATAL_STATES))
def test_an_unrecoverable_cuda_context_is_killed(state):
    d = decide(Observation("scoring_engine", cuda_state=state))
    assert d.verdict == KILL
    assert d.cause == CUDA_UNRECOVERABLE


def test_cuda_oom_is_not_a_kill():
    """OOM is recoverable and often transient — the smaller model still fits.
    Killing for it throws away the fallback that would have worked."""
    d = decide(Observation("scoring_engine", priority=CRITICAL, cuda_state="OOM"))
    assert d.verdict != KILL
    assert d.cause != CUDA_UNRECOVERABLE


def test_cuda_state_is_matched_case_insensitively():
    assert decide(Observation("x", cuda_state="memory_corrupt")).verdict == KILL


def test_an_unknown_cuda_state_is_not_fatal():
    for state in ("OK", "", "BUSY", "UNKNOWN", "something_new"):
        d = decide(Observation("x", cuda_state=state))
        assert d.cause != CUDA_UNRECOVERABLE, state


# ── precedence ─────────────────────────────────────────────────────────────

def test_process_level_causes_outrank_step_level_ones():
    """A livelocked process cannot be trusted to degrade gracefully — there is
    nothing left running that could record the degradation."""
    d = decide(Observation("scoring_engine", priority=CRITICAL, degraded=True,
                           cuda_state="MEMORY_CORRUPT",
                           cpu_percent=99.0, io_idle_sec=600.0))
    assert d.cause == CUDA_UNRECOVERABLE


def test_livelock_outranks_a_broken_invariant():
    d = decide(Observation("scoring_engine", priority=CRITICAL, degraded=True,
                           cpu_percent=99.0, io_idle_sec=600.0))
    assert d.cause == LIVELOCK


# ── the shape of the policy itself ─────────────────────────────────────────

def test_only_three_causes_can_ever_carry_a_kill():
    """The guard against a fourth reason being added without a decision."""
    allowed = {CRITICAL_INVARIANT_BROKEN, LIVELOCK, CUDA_UNRECOVERABLE}
    observations = [
        Observation("scoring_engine", CRITICAL, degraded=True),
        Observation("x", cuda_state="CONTEXT_LOST"),
        Observation("x", cpu_percent=100.0, io_idle_sec=999.0),
        Observation("x", NORMAL, heartbeat_age_sec=10 ** 6),
        Observation("x", CRITICAL, degraded=True, heartbeat_age_sec=10 ** 6),
        Observation("merklememory_commit", CRITICAL, degraded=True),
    ]
    for obs in observations:
        d = decide(obs)
        if d.verdict == KILL:
            assert d.cause in allowed, f"kill on an unlisted cause: {d.cause}"
        else:
            assert d.cause is None


def test_the_invariant_table_stays_small():
    """Every entry is a licence to destroy a night's work."""
    assert len(SAFETY_INVARIANTS) <= 8, (
        "the invariant table is growing; each entry re-authorises a kill and "
        "should be argued for individually")


def test_every_decision_carries_a_reason():
    for obs in (Observation("x"), Observation("x", cuda_state="CONTEXT_LOST"),
                Observation("scoring_engine", CRITICAL, degraded=True)):
        d = decide(obs)
        assert isinstance(d, KillDecision)
        assert d.reason.strip()


def test_every_invariant_step_is_critical_in_the_shipped_table():
    """An invariant on a NORMAL step can never fire — it would be decoration."""
    from core.survival_mode import load_priorities

    table = load_priorities()
    for step in SAFETY_INVARIANTS:
        assert table.get(step) == CRITICAL, (
            f"{step} carries a safety invariant but is not CRITICAL, so its "
            f"invariant is unreachable")


def test_every_invariant_step_exists_in_the_cycle():
    from core.cycle_map import STEPS

    names = {s for s, *_ in STEPS}
    unknown = set(SAFETY_INVARIANTS) - names
    assert not unknown, f"invariants name non-existent steps: {unknown}"
