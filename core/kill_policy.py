#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/kill_policy.py — SLOW IS NOT A REASON TO KILL.

WHAT IT REPLACES
-----------------
Today the watchdog has exactly one question — has the heartbeat gone stale past
this step's ceiling — and exactly one answer: kill the cycle. The existence
ledger has 11 kills and 39 deaths against 29 finished cycles, and the kills sit
on two steps:

    kills_by_step   internet_intelligence 6,  daily_analysis 5

Every one of those was a slow LLM step. Not a corrupted process, not a runaway
loop — a step waiting on a model. The whole cycle was destroyed each time to
punish one step for being slow, and the 26 steps after it lost the night.

With core/step_budget.py in place, slowness has a better answer: the step spends
its budget, gets no result, and is marked DEGRADED while the cycle walks on. Once
that exists, killing for slowness is not merely harsh, it is redundant.

THE THREE REASONS THAT REMAIN
------------------------------
    (a) CRITICAL_INVARIANT_BROKEN  a CRITICAL step is DEGRADED and continuing
                                   would publish something false
    (b) LIVELOCK                   CPU burning, zero I/O, for 60s
    (c) CUDA_UNRECOVERABLE         the context is gone or memory is corrupt

Everything else is DEGRADE or WAIT. A NORMAL step that is merely slow is DEGRADED
and is never killed, at any age, past any ceiling.

WHY (a) IS A KILL AND NOT JUST A DEGRADE
-----------------------------------------
Because of the failure core/phase_resume.py already names: scoring reads
yesterday's snapshots, produces a composite from last night's numbers, and stamps
it with today's date. The output looks current. A cycle that keeps walking after a
degraded scoring_engine does not merely lose a measurement — it MANUFACTURES one.
Stopping is better than publishing a number nobody can tell is stale.

So the invariant table below is not "which steps are important". It is "which
steps have a downstream consumer that would present their stale output as fresh".
That is a narrower question and it is the only one that earns a kill.

    JUDGMENT CALL, FLAGGED: the table is this module's opinion, defended above
    but not derived from anything mechanical. It is small on purpose — five
    entries — because every entry is a licence to destroy a night's work.

    venv\\Scripts\\python.exe core/kill_policy.py --selftest
"""
from __future__ import annotations

import json
import time
import pathlib
import sys
from dataclasses import asdict, dataclass
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.step_budget import CRITICAL, NORMAL

BASE = pathlib.Path(__file__).resolve().parents[1]

# Verdicts
KILL = "KILL"
DEGRADE = "DEGRADE"
WAIT = "WAIT"

# Causes — only these three may ever carry a KILL.
CRITICAL_INVARIANT_BROKEN = "CRITICAL_INVARIANT_BROKEN"
LIVELOCK = "LIVELOCK"
CUDA_UNRECOVERABLE = "CUDA_UNRECOVERABLE"

# Livelock: BOTH conditions, sustained. CPU alone is a busy step; idle I/O alone
# is a step waiting on a model, which is the thing we just stopped killing.
LIVELOCK_CPU_PERCENT = 80.0
LIVELOCK_IO_IDLE_SEC = 60.0

# CUDA states that mean the context cannot be recovered in-process.
# OOM IS DELIBERATELY ABSENT: an out-of-memory failure is a recoverable, often
# transient condition — the smaller model still fits, and killing the cycle for
# it throws away the fallback that would have worked.
CUDA_FATAL_STATES = frozenset({
    "MEMORY_CORRUPT",
    "CONTEXT_LOST",
    "UNRECOVERABLE",
    "ECC_UNCORRECTABLE",
})
CUDA_RECOVERABLE_STATES = frozenset({"OK", "OOM", "BUSY", "UNKNOWN", ""})

# Steps whose stale output a downstream consumer would present as fresh.
SAFETY_INVARIANTS = {
    "canon_load": "the canon is verified before the brain is allowed to act on it",
    "update_master": "the master snapshot dated today would carry yesterday's data",
    "scoring_engine": "a composite would be published from stale snapshots, "
                      "stamped with today's date",
    "goal_score_calculator": "goal scores would be published from a composite "
                             "that was never computed today",
    "merklememory_commit": "the audit chain would gain a silent gap",
}


@dataclass
class Observation:
    """Everything the decision needs, passed in rather than probed.

    Same discipline supervisor.decide() already uses: the policy stays pure, so a
    test can assert that a healthy 40-minute web_intelligence step is never killed
    without needing a 40-minute step.
    """
    step: str
    priority: str = NORMAL
    degraded: bool = False
    heartbeat_age_sec: float = 0.0
    ceiling_sec: float = 900.0
    cpu_percent: Optional[float] = None
    io_idle_sec: Optional[float] = None
    cuda_state: str = "OK"


@dataclass
class KillDecision:
    verdict: str
    cause: Optional[str]
    reason: str

    @property
    def kill(self) -> bool:
        return self.verdict == KILL

    def as_dict(self) -> dict:
        return asdict(self)


def broken_invariant(step: str, degraded: bool,
                     invariants: Optional[dict] = None) -> Optional[str]:
    """The named invariant this degraded step breaks, or None.

    A step that is not degraded breaks nothing: the invariant is about missing
    output, not about the step being slow on the way to producing it.
    """
    if not degraded:
        return None
    return (SAFETY_INVARIANTS if invariants is None else invariants).get(step)


# ---------------------------------------------------------------------------
# Gathering the observation — the impure half, kept apart from the decision
# ---------------------------------------------------------------------------

IO_STATE_FILE = "watchdog_io.json"


def _io_totals(proc) -> Optional[int]:
    """Total bytes+ops this process has done, or None if the OS will not say.

    Windows denies io_counters() for some processes even to their own user, and a
    denial is NOT evidence of idleness — it is absence of evidence. Returning None
    keeps that distinction, and decide() treats None as "not livelock".
    """
    try:
        io = proc.io_counters()
    except Exception:
        return None
    return int(getattr(io, "read_bytes", 0) + getattr(io, "write_bytes", 0)
               + getattr(io, "read_count", 0) + getattr(io, "write_count", 0))


def observe(pid: Optional[int],
            step: str,
            priority: str = NORMAL,
            degraded: bool = False,
            heartbeat_age_sec: float = 0.0,
            ceiling_sec: float = 900.0,
            base: Optional[pathlib.Path] = None,
            cpu_interval: float = 1.0) -> Observation:
    """Build an Observation of a live cycle. Never raises.

    io_idle_sec CANNOT BE MEASURED IN ONE SAMPLE. The supervisor is a short-lived
    tick that exits in milliseconds; "this process has done no I/O for 60s" is a
    statement about a span it does not live through. So the last non-zero I/O
    total and the time it was seen are persisted in memory/watchdog_io.json, and
    io_idle_sec is the age of that mark. The first tick after a cycle starts has
    nothing to compare against and reports None — which decide() reads as "not
    livelocked", the safe direction: a missing measurement must never be grounds
    for a kill.

    Every field that cannot be established is None rather than a default. A
    default here would be a fabricated observation, and this is the one function
    in the repo whose output can end a cycle.
    """
    root = base or BASE
    obs = Observation(step=step or "unknown", priority=priority, degraded=degraded,
                      heartbeat_age_sec=heartbeat_age_sec, ceiling_sec=ceiling_sec,
                      cpu_percent=None, io_idle_sec=None, cuda_state="OK")
    if not pid:
        return obs

    try:
        import psutil
    except Exception:
        return obs

    try:
        proc = psutil.Process(int(pid))
    except Exception:
        return obs                      # gone; a dead process is not livelocked

    try:
        # interval= blocks for that long and returns a real percentage. The
        # interval-less form returns 0.0 on a first call, which would read as an
        # idle process and is exactly the wrong lie in this function.
        obs.cpu_percent = float(proc.cpu_percent(interval=cpu_interval))
    except Exception:
        obs.cpu_percent = None

    total = _io_totals(proc)
    if total is None:
        return obs

    path = root / "memory" / IO_STATE_FILE
    now = time.time()
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        prev = {}

    same_process = (prev.get("pid") == int(pid))
    if same_process and prev.get("io_total") == total:
        obs.io_idle_sec = max(0.0, now - float(prev.get("since", now)))
        mark = prev                      # unchanged: keep the original timestamp
    else:
        mark = {"pid": int(pid), "io_total": total, "since": now}
        obs.io_idle_sec = 0.0 if same_process else None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mark, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return obs


def decide(obs: Observation,
           invariants: Optional[dict] = None) -> KillDecision:
    """The only function in this repo allowed to conclude KILL.

    Order matters: the process-level causes are checked FIRST, because a livelocked
    or CUDA-dead process cannot be trusted to degrade gracefully — there is nothing
    left running that could record the degradation.
    """
    # (c) CUDA context unrecoverable — memory corrupt, not OOM.
    state = (obs.cuda_state or "").upper()
    if state in CUDA_FATAL_STATES:
        return KillDecision(
            KILL, CUDA_UNRECOVERABLE,
            "CUDA state {} cannot be recovered in-process; the step cannot "
            "degrade because nothing is left to degrade with".format(state))

    # (b) Livelock — CPU burning, zero I/O, sustained.
    if (obs.cpu_percent is not None and obs.io_idle_sec is not None
            and obs.cpu_percent >= LIVELOCK_CPU_PERCENT
            and obs.io_idle_sec >= LIVELOCK_IO_IDLE_SEC):
        return KillDecision(
            KILL, LIVELOCK,
            "livelock: {:.0f}% CPU with no I/O for {:.0f}s (>= {:.0f}%, "
            "{:.0f}s) — burning, not working".format(
                obs.cpu_percent, obs.io_idle_sec,
                LIVELOCK_CPU_PERCENT, LIVELOCK_IO_IDLE_SEC))

    # (a) A CRITICAL step degraded in a way that would publish something false.
    if obs.priority == CRITICAL and obs.degraded:
        invariant = broken_invariant(obs.step, obs.degraded, invariants)
        if invariant:
            return KillDecision(
                KILL, CRITICAL_INVARIANT_BROKEN,
                "CRITICAL step {!r} is DEGRADED and continuing breaks a safety "
                "invariant: {}".format(obs.step, invariant))
        return KillDecision(
            DEGRADE, None,
            "CRITICAL step {!r} is DEGRADED, but no downstream consumer would "
            "publish its stale output as fresh; the cycle continues".format(obs.step))

    if obs.degraded:
        return KillDecision(
            DEGRADE, None,
            "{} step {!r} is DEGRADED; the cycle continues".format(
                obs.priority, obs.step))

    # Slow. This is the branch that used to kill.
    if obs.heartbeat_age_sec > obs.ceiling_sec:
        return KillDecision(
            DEGRADE, None,
            "step {!r} is past its ceiling ({:.0f}s > {:.0f}s) but is not "
            "livelocked and CUDA is fine — slow is not a reason to kill; "
            "mark it DEGRADED".format(obs.step, obs.heartbeat_age_sec,
                                      obs.ceiling_sec))

    return KillDecision(
        WAIT, None,
        "step {!r} is healthy ({:.0f}s / {:.0f}s)".format(
            obs.step, obs.heartbeat_age_sec, obs.ceiling_sec))


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/kill_policy.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    try:
        from core.survival_mode import load_priorities
        table = load_priorities()
        print("  step_priority.json   LIVE ({} CRITICAL)".format(len(table)))
    except Exception as e:
        print("  step_priority.json   INERT ({}: {})".format(type(e).__name__, e))
        table = {}
        ok = False

    try:
        from core.cycle_map import STEPS
        names = {s for s, *_ in STEPS}
        print("  cycle_map            LIVE ({} steps)".format(len(names)))
    except Exception as e:
        print("  cycle_map            INERT ({}: {})".format(type(e).__name__, e))
        names = set()
        ok = False

    try:
        sup = (BASE / "supervisor.py").read_text(encoding="utf-8", errors="replace")
        wired = "kill_policy" in sup
    except OSError:
        wired = False
    print("  supervisor.py        {}".format(
        "WIRED" if wired else
        "NOT WIRED — the watchdog still kills on a stale heartbeat alone"))

    unknown = sorted(set(SAFETY_INVARIANTS) - names) if names else []
    if unknown:
        print("  WARNING: invariants name non-existent steps: {}".format(unknown))
        ok = False
    else:
        print("  invariant steps all exist in cycle_map: OK")

    not_critical = sorted(s for s in SAFETY_INVARIANTS if table and s not in table)
    if not_critical:
        print("  WARNING: invariant steps that are NOT CRITICAL (so their "
              "invariant can never fire): {}".format(not_critical))
        ok = False
    else:
        print("  every invariant step is CRITICAL: OK")

    # The two that matter most.
    slow_normal = decide(Observation("internet_intelligence", NORMAL,
                                     heartbeat_age_sec=2762, ceiling_sec=2700))
    assert slow_normal.verdict == DEGRADE, slow_normal
    print("  yesterday's kill replayed -> {} ({})".format(
        slow_normal.verdict, slow_normal.reason[:60]))

    oom = decide(Observation("scoring_engine", CRITICAL, cuda_state="OOM"))
    assert oom.verdict != KILL, oom
    print("  CUDA OOM             -> {} (not a kill)".format(oom.verdict))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
