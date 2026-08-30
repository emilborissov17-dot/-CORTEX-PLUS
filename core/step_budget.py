#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/step_budget.py — A SLOW STEP DEGRADES. IT DOES NOT HANG, AND IT DOES NOT
STOP THE CYCLE.

THE DEFECT
-----------
Today a step gets one hard ceiling from config/scheduler.json and one behaviour
when it is exceeded: the watchdog kills the cycle. The existence ledger shows what
that costs — 11 kills, concentrated on two steps:

    kills_by_step   internet_intelligence 6,  daily_analysis 5

Both are LLM steps, and the shape is always the same: the cloud call blocks, the
step stops beating, the ceiling passes, the whole cycle dies for one step's
unavailable model. On 21 Aug 2026 that was
`LOCAL_MODEL_DEGRADATION` on internet_intelligence at 2762s against a 2700s
ceiling — one step took the day.

The blocking is the root cause, not the ceiling. A synchronous call to a dead
endpoint has no timeout the caller controls, so the step cannot fall back to
anything: it is already stuck when the fallback would have fired.

THE LADDER
-----------
One budget B per step, spent in thirds, never blocking:

    B = learned p95 x 1.5          (x1.5, not step_contract's SLOW_FACTOR of 3.0)

    cloud        timeout B/3   -> None or timeout: ABANDON, do not wait
    qwen2.5:3b   timeout B/3   -> kept warm (keep_alive=-1), does not share with 8b
    qwen3:8b     timeout B/3   -> ONLY if priority == CRITICAL and budget remains
    nothing finished           -> DEGRADED, value None, THE CYCLE CONTINUES

DEGRADED is a verdict, not an exception. The caller gets a result object and keeps
walking the step list. Nothing here raises on failure and nothing here kills.

WHAT "ABANDON" HONESTLY MEANS
------------------------------
Python cannot kill a thread. `cancel(no waiting)` is implemented as: run the
attempt on a DAEMON thread, join with a timeout, and on timeout stop waiting and
discard the result box. The abandoned call may still be running inside the
interpreter afterwards, holding its socket until the OS or the library times it
out. What is guaranteed is the only thing the cycle needs — THE LADDER DOES NOT
WAIT FOR IT, and its late result can never be mistaken for the current one.
Daemon=True so it also cannot hold the process open at exit.

    venv\\Scripts\\python.exe core/step_budget.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

# x1.5, deliberately. core/step_contract.SLOW_FACTOR is 3.0 and means something
# else: "loud enough to report as SLOW while it runs". A spending budget has to be
# tighter than a complaint threshold, or the budget is never the binding limit.
BUDGET_FACTOR = 1.5

# Below this, thirds are too small for any model call to land in and every step
# would degrade on arithmetic rather than on evidence. 30s => 10s per tier.
MIN_BUDGET_SEC = 30.0

# The smallest per-tier slice worth attempting. Below this a step's account counts
# as empty — see run_call(). Not a tuning knob: it is the claim that no model on
# this machine answers in under a second (the fastest measured warm 3b call is
# ~7s), so a slice smaller than this buys a socket and nothing else.
MIN_TIER_SEC = 1.0

OK = "OK"
DEGRADED = "DEGRADED"

CLOUD = "cloud"
LOCAL_3B = "local_3b"
LOCAL_8B = "local_8b"

CRITICAL = "CRITICAL"
NORMAL = "NORMAL"

# Attempt outcomes
DONE = "DONE"
TIMEOUT = "TIMEOUT"
EMPTY = "EMPTY"        # returned None — a declined answer, not a slow one
RAISED = "RAISED"
SKIPPED = "SKIPPED"


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------

def percentile(values: list, q: float):
    """The same nearest-rank rule core/step_contract.p95 uses, for any q.

    Kept identical on purpose: two percentile definitions over the same run
    history would let the budget and the SLOW verdict disagree about the same
    step, and nobody would know which one to believe.
    """
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if len(vals) < 2:
        return None
    idx = max(0, min(len(vals) - 1, int(round(q * (len(vals) - 1)))))
    return float(vals[idx])


def _load_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _baseline_labels(step: str) -> list:
    """Every key memory/step_contract_baseline.json might file this step under.

    The baseline is keyed by _run() LABELS (`internet_agent`), the cycle map by
    STEP NAMES (`internet_intelligence`). core/cycle_map.ALIASES is the existing
    label -> name table; inverting it is how a step name finds its own history
    instead of silently finding nothing and falling back to the config ceiling.
    """
    names = [step]
    try:
        from core.cycle_map import ALIASES
        names += [label for label, name in ALIASES.items() if name == step]
    except Exception:
        pass
    return names


def learned_seconds(step: str, baseline: Optional[dict] = None) -> list:
    """This step's observed durations, from whichever key the baseline files it under."""
    if baseline is None:
        baseline = _load_json(BASE / "memory" / "step_contract_baseline.json")
    for key in _baseline_labels(step):
        record = baseline.get(key)
        if isinstance(record, dict) and record.get("runs"):
            return [r.get("seconds", 0.0) for r in record["runs"]]
    return []


def ceiling_for(step: str, ceilings: Optional[dict] = None) -> float:
    """The human-set ceiling from config/scheduler.json — the fallback, not the budget."""
    if ceilings is None:
        ceilings = (_load_json(BASE / "config" / "scheduler.json")
                    .get("step_ceilings_sec") or {})
    return float(ceilings.get(step, ceilings.get("_default", 900)))


# The floor under a survival-mode ceiling. A p50 is the MEDIAN of observed runs,
# so using it raw as a ceiling means half of all runs breach it — that is the
# intended aggression of a night the system cannot afford. What is NOT intended
# is the degenerate case, and it is not hypothetical: measured 22 Aug 2026,
# data_scout's p50 produced a ceiling of ONE SECOND, against a budget of 471s.
# A step that usually no-ops has a tiny median and would be declared overrun
# before it had finished importing. Two minutes is enough for any step here to
# start and beat at least once.
MIN_SURVIVAL_CEILING_SEC = 120.0


def effective_ceiling(step: str, ceilings: Optional[dict] = None) -> float:
    """THE ONE CEILING. Everything that needs to know "how long may this step
    take" asks here — the watchdog through supervisor.ceiling_for, the budget
    through budget_for below.

    THE RULE, also written into config/scheduler.json's README:

        config/scheduler.json step_ceilings_sec is the SINGLE SOURCE OF TRUTH.
        It is human-tunable only. Everything else DERIVES from it and may only
        ever TIGHTEN it, never widen it.

    Two derivations exist today:
        survival mode   p50 of observed runs, floored at MIN_SURVIVAL_CEILING_SEC
        step_budget     B = learned p95 x 1.5, clamped to whatever this returns

    Before this function there were two independent readers of the same config
    and they disagreed in production. Measured 22 Aug 2026 with survival mode
    latched: internet_intelligence had a watchdog ceiling of 2397s and a budget
    of 3600s — the step was authorised to spend 1203s longer than the watchdog
    would tolerate. A budget that outlives its own ceiling is not a budget.
    """
    # WHOLE SECONDS, always. The watchdog compares an int; a fractional ceiling
    # here meant supervisor.ceiling_for truncated 2397.5 to 2397 while the budget
    # kept 2397.5, and the budget was then one second longer than the ceiling it
    # was supposed to be clamped to. A reconciliation that leaves a one-second
    # disagreement has not reconciled anything.
    base = float(int(ceiling_for(step, ceilings)))
    try:
        from core import survival_mode as _sm      # imported here: survival_mode
        from datetime import datetime as _dt        # imports THIS module at top
        today = _dt.now().astimezone().date().isoformat()
        active, _reason, _new = _sm.resolve(today)
        if not active:
            return base
        seconds, _source = _sm.p50_ceiling(step, ceilings=ceilings)
        return float(int(min(base, max(MIN_SURVIVAL_CEILING_SEC, float(seconds)))))
    except Exception:
        # A ceiling that cannot be derived falls back to the human number. Never
        # to a guess: this value decides what the watchdog acts on.
        return base


@dataclass
class Budget:
    step: str
    seconds: float
    source: str          # "p95" | "ceiling" | "p95_clamped_to_ceiling"
    runs_seen: int

    @property
    def per_tier(self) -> float:
        return self.seconds / 3.0


def budget_for(step: str, baseline: Optional[dict] = None,
               ceilings: Optional[dict] = None,
               factor: float = BUDGET_FACTOR) -> Budget:
    """B = learned p95 x factor, CLAMPED to the human ceiling, or the ceiling itself
    when there is no history.

    p95 needs at least two runs (core/step_contract.p95 returns None below that).
    Most steps here currently have two or three and many have none, so the ceiling
    fallback is the common path today; `source` says which was used rather than
    presenting a guess as a measurement.

    WHY THE CLAMP — found by running this, not by reasoning about it.
    internet_intelligence has exactly two recorded runs, 2397s and 2510s. With so
    few samples p95 IS the maximum, so B came out at 2510 x 1.5 = 3766s — WIDER
    than the 3600s ceiling a human set in config/scheduler.json on 21 Aug 2026.
    That file's own README says ceilings are human-tunable only, because "a system
    that can widen its own restart budget has no restart budget". A learned budget
    that silently exceeds the human number is exactly that. So the ceiling stays
    the outer bound and the learned value may only ever TIGHTEN it.
    """
    seen = learned_seconds(step, baseline)
    # effective_ceiling, not ceiling_for: under survival mode the watchdog acts on
    # a TIGHTER number, and a budget clamped to the looser one would authorise a
    # step to spend past the point where it is stopped. Measured before this
    # change: internet_intelligence, watchdog 2397s, budget 3600s.
    ceiling = effective_ceiling(step, ceilings)
    p95 = percentile(seen, 0.95)
    if p95 is None:
        return Budget(step, max(MIN_BUDGET_SEC, ceiling), "ceiling", len(seen))
    learned = p95 * factor
    if learned >= ceiling:
        return Budget(step, max(MIN_BUDGET_SEC, ceiling),
                      "p95_clamped_to_ceiling", len(seen))
    return Budget(step, max(MIN_BUDGET_SEC, learned), "p95", len(seen))


# ---------------------------------------------------------------------------
# Running one attempt without ever blocking past its slice
# ---------------------------------------------------------------------------

@dataclass
class Attempt:
    tier: str
    outcome: str
    elapsed_sec: float
    error: Optional[str] = None


def call_with_timeout(fn: Callable, timeout_sec: float):
    """Run fn() on a daemon thread; stop waiting at timeout_sec. Never raises.

    Returns (outcome, value, error, elapsed_sec). On TIMEOUT the thread is
    abandoned, still running — see the module docstring. The result box is dropped
    with it, so a late answer cannot leak into a later step.
    """
    box = {}

    def _target():
        # `except Exception`, not BaseException. test_no_bare_except.py keeps that
        # allowlist at two genuinely unavoidable entries, and this is not one of
        # them — growing a safety allowlist for a case that has a clean
        # alternative is how such lists stop meaning anything.
        #
        # The `done` flag is what makes the narrower catch safe. A worker killed
        # by a BaseException — a client library that calls sys.exit() on a hard
        # error — leaves `done` unset, so it is reported RAISED instead of
        # passing for EMPTY, which means "the model declined to answer". Reading
        # a crash as a decline is the quiet failure this repo keeps finding.
        # `done` is set on the SUCCESS path, not in a `finally`. A finally block
        # runs while a BaseException is propagating too, so it would mark the
        # crashed thread as having finished normally — which is the exact
        # confusion this flag exists to prevent. Caught by the test below.
        try:
            box["value"] = fn()
            box["done"] = True
        except Exception as e:                        # noqa: BLE001
            box["error"] = "{}: {}".format(type(e).__name__, e)

    thread = threading.Thread(target=_target, daemon=True,
                              name="step_budget_attempt")
    started = time.monotonic()
    thread.start()
    thread.join(timeout=max(0.0, timeout_sec))
    elapsed = time.monotonic() - started

    if thread.is_alive():
        return TIMEOUT, None, None, elapsed
    if "error" in box:
        return RAISED, None, box["error"], elapsed
    if not box.get("done"):
        return RAISED, None, "worker thread died without returning", elapsed
    value = box.get("value")
    if value is None:
        return EMPTY, None, None, elapsed
    return DONE, value, None, elapsed


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

@dataclass
class LadderResult:
    step: str
    outcome: str                     # OK | DEGRADED
    tier: Optional[str]              # which tier answered, None if none did
    value: Any
    budget_sec: float
    elapsed_sec: float
    attempts: list = field(default_factory=list)
    reason: str = ""

    @property
    def degraded(self) -> bool:
        return self.outcome == DEGRADED

    def as_dict(self) -> dict:
        d = asdict(self)
        d["attempts"] = [asdict(a) if isinstance(a, Attempt) else a
                         for a in self.attempts]
        return d


# ---------------------------------------------------------------------------
# STICKY CLOUD DEMOTION — CYCLE-SCOPED, RESET AT BOOT
# ---------------------------------------------------------------------------
#
# MEASURED, cycle 2026-08-22 11:22. Three steps produced nothing while 48-80s of
# their budget sat unused, and all three failed the same way:
#
#   cortex_strategist_agent  50s of B=120s   cloud=EMPTY local_3b=TIMEOUT
#   hyperclaw_orchestrator   40s of B=120s   cloud=EMPTY local_3b=TIMEOUT
#   cortex_reasoner          72s of B=120s   cloud=EMPTY local_3b=TIMEOUT
#
# EMPTY on the cloud tier means every provider was rate-limited or in cooldown —
# a declined answer, not a slow one. By the third such step the cloud is not
# coming back this cycle, and it was still being handed the first slice of every
# ladder while the local model, the only tier that could actually answer, was
# held to a third.
#
# So: after CLOUD_EMPTY_LIMIT empty cloud tiers in one cycle the cloud stops
# receiving a slice for the rest of that cycle. Sticky, because the condition it
# describes (a rate-limit window) does not clear inside a cycle; cycle-scoped and
# reset at boot, because it does clear overnight. In-memory on purpose: a cycle
# is one process, and a demotion that outlived the process would be a policy
# nobody set.

# ── ITEM 44.1 item 5 (30 Aug 2026): THE LIMIT IS A POLICY, SO IT LIVES IN CONFIG
#
# HUMAN APPROVAL (Emil Borissov, 29 August 2026), quoted here because
# config/scheduler.json is a GUARDED file:
#   "I approve moving CLOUD_EMPTY_LIMIT out of core/step_budget.py into
#    config/scheduler.json. The value stays 3 until measured evidence justifies
#    changing it. It is a policy parameter that decides how much of a cycle runs
#    on a 3B local model, and it belongs where a human can see it and set it."
#
# ABSENT KEY -> 3, SILENTLY. That is the documented default and absence is not an
# error; a fresh clone with no key must behave exactly as this file did before.
#
# PRESENT BUT UNREADABLE -> RAISE, LOUDLY. Defaulting to 3 on a malformed value
# would hide a broken policy file behind correct-looking behaviour, which is the
# defect this repository keeps finding in other shapes. A typo in a parameter
# that decides how much of a night runs on a 3B model must not be absorbed.
#
# RESOLVED AT IMPORT AND AGAIN AT reset_cycle(), NOT INSIDE THE LADDER. The one
# consumer, _note_cloud_outcome(), runs inside run_with_ladder() with no try
# around it — raising there would take down a step two hours into a night because
# of a config typo. Failing at import, and again at the boot step, puts the error
# where a policy-file error belongs: at the start, before anything depends on it.
CLOUD_EMPTY_LIMIT_DEFAULT = 3
_CLOUD_EMPTY_KEY = "cloud_empty_limit"


def cloud_empty_limit(cfg: Optional[dict] = None) -> int:
    """How many EMPTY cloud tiers trip the demotion. `cfg` is injectable so a
    test can pass its own dict and never touch the guarded file."""
    if cfg is None:
        cfg = _load_json(BASE / "config" / "scheduler.json")
    if _CLOUD_EMPTY_KEY not in (cfg or {}):
        return CLOUD_EMPTY_LIMIT_DEFAULT
    raw = cfg[_CLOUD_EMPTY_KEY]
    if isinstance(raw, bool):                      # bool is an int in Python
        raise ValueError(
            f"config/scheduler.json: {_CLOUD_EMPTY_KEY} is {raw!r}, a boolean. "
            f"It must be a whole number >= 1.")
    if isinstance(raw, float) and not raw.is_integer():
        # int(2.7) == 2 would silently truncate a policy value. A number that
        # does not mean what it says is the same defect as a malformed one.
        raise ValueError(
            f"config/scheduler.json: {_CLOUD_EMPTY_KEY} is {raw!r}. It counts "
            f"whole cloud tiers; {raw!r} would silently become {int(raw)}.")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"config/scheduler.json: {_CLOUD_EMPTY_KEY} is {raw!r}, which is not "
            f"a number. Remove the key to accept the default of "
            f"{CLOUD_EMPTY_LIMIT_DEFAULT}, or set a whole number >= 1. It is NOT "
            f"defaulted, because a malformed policy value that behaves like the "
            f"default is a broken file nobody notices.") from None
    if value < 1:
        raise ValueError(
            f"config/scheduler.json: {_CLOUD_EMPTY_KEY} is {value}, which would "
            f"demote the cloud before a single empty tier. Must be >= 1.")
    return value


CLOUD_EMPTY_LIMIT = cloud_empty_limit()

# ── ITEM 44.1 (29 Aug 2026): THE DEMOTION STOPS OUTLIVING ITS OWN CAUSE ─────
#
# WHAT THE STICKY VERSION DID, measured from the cycle of 2026-08-29. Groq was
# rate-limited early, three cloud tiers came back EMPTY, and the cloud was
# demoted "for the rest of this cycle" at 14:5x. From that moment 66 of the
# cycle's 71 local answers had NO cloud rung attempted, and the log holds ZERO
# cloud attempts for the remaining 2h20m. The cooldowns that caused it are
# 60/120/180s, capped at 180 — THE DEMOTION OUTLIVED THEM BY TWO HOURS.
#
# Kimi: "Tie demotion lifetime to the longest active cooldown expiry. Criterion:
# transient failures (429s) should not outlast their own recovery signal. When
# the last cooldown expires, re-probe the cloud tier before permanently
# defaulting to local."
#
# HIS OBJECTION, AND WHERE IT IS ANSWERED: "Re-probing after cooldown expiry
# risks hammering a rate-limited backend, getting the free tier banned or
# IP-blocked, turning a transient rate limit into permanent account loss."
#
# The answer is NOT the backoff — it is the PRECONDITION on the line
# `if now < _cooldown_until: return True`. A probe can only happen once EVERY
# backend's own signalled window has already elapsed, so no probe is ever sent
# into a window a provider told us about. That is the opposite of hammering: it
# is waiting exactly as long as we were asked to, and no longer.
#
# The exponential floor below covers the one case the precondition cannot: the
# provider's REAL window was longer than the one it declared. 300s doubling to
# 600, 1200, capped at 1800.
#   * why 300 to start — it must exceed the cooldown cap of 180s, or the floor
#     would add nothing over the precondition that already holds;
#   * why doubling — a provider still refusing after 5 minutes is not 5 minutes
#     from recovering, and each failure is evidence the declared window was
#     wrong;
#   * why a 1800s cap — over a 2h20m cycle the worst case is ~5 probes, which is
#     not a burst by any reading; an uncapped floor would silently become the
#     sticky demotion again, under a longer name.
#
# WALL CLOCK, NOT monotonic: these expiries are compared against cooldown
# deadlines produced by core/groq_backend with time.time(), and mixing the two
# clocks would make the comparison meaningless.
PROBE_FLOOR_START_SEC = 300.0
PROBE_FLOOR_MAX_SEC = 1800.0

_cloud_empty = 0
_cloud_demoted_at = None          # the empty-count at which it tripped
_cooldown_until = 0.0             # the LONGEST active cooldown, pushed in
_probe_floor_until = 0.0          # a failed probe holds the demotion this long
_probe_failures = 0


def _now_wall() -> float:
    """Wall clock, so it is comparable with groq_backend's cooldown deadlines."""
    return time.time()


def note_cooldown_until(ts: float) -> float:
    """Told by core/groq_backend whenever it sets a cooldown.

    PUSHED, NOT PULLED, and the direction is forced: groq_backend imports this
    module, so this module cannot import groq_backend to ask. _set_cooldown is
    the single place any cooldown is created, which makes it the one call site.
    Only ever moves later — the demotion must respect the LONGEST window.
    """
    global _cooldown_until
    with _step_lock:
        _cooldown_until = max(_cooldown_until, float(ts))
        return _cooldown_until


def reset_cycle() -> dict:
    """Forget the demotion. Called from the runner's boot step, once per cycle."""
    global _cloud_empty, _cloud_demoted_at, _cooldown_until
    global _probe_floor_until, _probe_failures
    global CLOUD_EMPTY_LIMIT
    # Re-read at boot: a human who edits the policy during the day should see it
    # take effect on the next cycle without a restart, and a malformed edit
    # should stop THAT cycle at its first step rather than midway through.
    CLOUD_EMPTY_LIMIT = cloud_empty_limit()
    was = {"cloud_empty": _cloud_empty,
           "cloud_demoted": _cloud_demoted_at is not None}
    _cloud_empty, _cloud_demoted_at = 0, None
    _cooldown_until, _probe_floor_until, _probe_failures = 0.0, 0.0, 0
    return was


def cloud_demoted() -> bool:
    """Is the cloud excluded RIGHT NOW? Time-bounded, not cycle-bounded.

    False here does not mean "healthy" — it means ELIGIBLE FOR ONE PROBE. The
    caller that acts on it must report the outcome through note_probe_failed()
    or note_probe_succeeded(), or the next call will probe again.
    """
    if _cloud_demoted_at is None:
        return False
    now = _now_wall()
    if now < _cooldown_until:
        return True                  # a backend's own window is still open
    if now < _probe_floor_until:
        return True                  # a probe already failed; serve its floor
    return False


def probe_floor_sec() -> float:
    """The floor the NEXT failed probe would impose. Reads only."""
    return min(PROBE_FLOOR_START_SEC * (2 ** _probe_failures),
               PROBE_FLOOR_MAX_SEC)


def note_probe_failed() -> float:
    """The one probe came back EMPTY. Re-arm with a longer floor; return it."""
    global _probe_failures, _probe_floor_until
    with _step_lock:
        floor = min(PROBE_FLOOR_START_SEC * (2 ** _probe_failures),
                    PROBE_FLOOR_MAX_SEC)
        _probe_failures += 1
        _probe_floor_until = _now_wall() + floor
    print("[BUDGET] cloud re-probe FAILED; demotion re-armed for {:.0f}s "
          "(failure #{})".format(floor, _probe_failures))
    return floor


def note_probe_succeeded() -> None:
    """The cloud answered. Clear the demotion AND the empty counter.

    The counter must go too: leaving it at the limit would let the very next
    empty tier re-trip a demotion the probe has just disproved.
    """
    global _cloud_empty, _cloud_demoted_at, _probe_floor_until, _probe_failures
    with _step_lock:
        _cloud_empty, _cloud_demoted_at = 0, None
        _probe_floor_until, _probe_failures = 0.0, 0
    print("[BUDGET] cloud re-probe SUCCEEDED; demotion cleared, "
          "normal laddering resumes")


def cloud_state() -> dict:
    now = _now_wall()
    return {"cloud_empty": _cloud_empty, "demoted": cloud_demoted(),
            # TRIPPED is a fact about the past; DEMOTED is a question about the
            # clock. Before ITEM 44.1 they were the same boolean, which is how a
            # 180s cooldown became a two-hour exclusion.
            "tripped": _cloud_demoted_at is not None,
            "limit": CLOUD_EMPTY_LIMIT,
            "cooldown_until_in": round(max(0.0, _cooldown_until - now), 1),
            "probe_floor_in": round(max(0.0, _probe_floor_until - now), 1),
            "probe_failures": _probe_failures}


def _note_cloud_outcome(outcome: str) -> None:
    """Count empty cloud tiers; trip the demotion once, out loud."""
    global _cloud_empty, _cloud_demoted_at
    if outcome != EMPTY:
        return
    _cloud_empty += 1
    if _cloud_demoted_at is None and _cloud_empty >= CLOUD_EMPTY_LIMIT:
        _cloud_demoted_at = _cloud_empty
        print("[BUDGET] cloud tier DEMOTED for the rest of this cycle: "
              "{} empty cloud tiers (limit {}). The local tiers get the whole "
              "budget from here.".format(_cloud_empty, CLOUD_EMPTY_LIMIT))


def run_with_ladder(step: str,
                    priority: str,
                    budget: Budget,
                    cloud: Optional[Callable] = None,
                    local_3b: Optional[Callable] = None,
                    local_8b: Optional[Callable] = None,
                    now: Callable = time.monotonic) -> LadderResult:
    """Spend B across the tiers. Return a verdict; never raise, never kill.

    `priority` gates the 8b tier only. Everything else is the same for a CRITICAL
    and a NORMAL step, because degrading is right for both — what differs is
    whether the expensive model is worth loading to avoid it.

    THE LAST VIABLE TIER GETS WHAT IS LEFT, NOT A THIRD (23 Aug 2026).
    `per_tier` is B/3 whether or not three tiers exist. On the night measured
    above only two did — the 8b is offered only inside its residency window
    (core/groq_backend passes None outside it), so the ladder was cloud, then 3b,
    then nothing. The 3b was capped at 40s of a 120s budget and timed out; 70s of
    that budget was never offered to the only tier that could have used it.
    A third of a budget is the right share when there are three claimants. When
    there is one, it is an unspent budget and a DEGRADED step.

    Viability is decided BEFORE the walk, so "last" means last in fact and not
    last in the list: a tier with no callable, a NORMAL step's 8b, and a demoted
    cloud are all out before the first slice is cut.
    """
    started = now()
    attempts: list = []

    demoted = cloud_demoted()
    tiers = [
        (CLOUD, cloud, not demoted,
         "cloud demoted this cycle after {} empty tiers".format(_cloud_empty)),
        (LOCAL_3B, local_3b, True, ""),
        (LOCAL_8B, local_8b, priority == CRITICAL,
         "priority is {}, 8b is CRITICAL-only".format(priority)),
    ]

    viable = [t for t, fn, allowed, _why in tiers if fn is not None and allowed]
    last_viable = viable[-1] if viable else None

    for tier, fn, allowed, why in tiers:
        if fn is None:
            attempts.append(Attempt(tier, SKIPPED, 0.0, "no callable supplied"))
            continue
        if not allowed:
            attempts.append(Attempt(tier, SKIPPED, 0.0, why))
            # ITEM 44.1 (3). THIS LINE IS WHY TWO HOURS WENT UNNOTICED. On
            # 2026-08-29 the cloud was skipped on 66 consecutive calls and the
            # log said so ONCE, in aggregate, at the moment of demotion. A skip
            # that writes nothing is indistinguishable from a call that was
            # never made.
            print("  [LADDER] {} SKIPPED for {}: {}".format(tier, step, why))
            continue

        spent = now() - started
        remaining = budget.seconds - spent
        if remaining <= 0:
            attempts.append(Attempt(tier, SKIPPED, 0.0, "budget exhausted"))
            print("  [LADDER] {} SKIPPED for {}: budget exhausted mid-chain "
                  "({:.0f}s of B={:.0f}s already spent)".format(
                      tier, step, spent, budget.seconds))
            continue

        # THE WHOLE REMAINDER when nothing viable comes after this tier;
        # otherwise the declared share, still clamped by what is actually left.
        slice_sec = (remaining if tier == last_viable
                     else min(budget.per_tier, remaining))

        outcome, value, error, elapsed = call_with_timeout(fn, slice_sec)
        attempts.append(Attempt(tier, outcome, round(elapsed, 3), error))
        if tier == CLOUD:
            _note_cloud_outcome(outcome)

        if outcome == DONE:
            return LadderResult(
                step, OK, tier, value, budget.seconds,
                round(now() - started, 3), attempts,
                "answered by {} in {:.1f}s".format(tier, elapsed))

    total = now() - started
    return LadderResult(
        step, DEGRADED, None, None, budget.seconds, round(total, 3), attempts,
        "no tier produced a result within B={:.0f}s ({}); "
        "step marked DEGRADED, cycle continues".format(
            budget.seconds, ", ".join(
                "{}={}".format(a.tier, a.outcome) for a in attempts)))


# ---------------------------------------------------------------------------
# ONE BUDGET PER STEP, SHARED BY EVERY CALL THE STEP MAKES
# ---------------------------------------------------------------------------
#
# run_with_ladder() above spends B on ONE attempt-chain. A real step does not make
# one model call — daily_analysis made 24 in a single run on 20 Aug. Handing each
# of them the full B would give that step a budget of 24 x B, which is not a
# budget. So the step opens an account, every call draws from what is left, and
# when it is empty the remaining calls degrade immediately without touching the
# network.
#
# Deliberately module-level rather than passed down: 127 call sites reach
# call_groq_meta, across 25 files, and threading a budget object through all of
# them is a refactor with no owner. A step is a serial, single-threaded region of
# one process, so a process-global "current step" is a true description of it. The
# lock is for the daemon threads run_with_ladder abandons, not for concurrency.

_step_lock = threading.Lock()
_open_step: Optional[dict] = None


def begin_step(step: str, priority: str = NORMAL,
               baseline: Optional[dict] = None,
               ceilings: Optional[dict] = None) -> dict:
    """Open this step's account. Idempotent per step; re-opening resets it."""
    global _open_step
    budget = budget_for(step, baseline, ceilings)
    with _step_lock:
        _open_step = {
            "step": step,
            "priority": priority,
            "budget": budget,
            "spent": 0.0,
            "calls": 0,
            # TWO COUNTERS, ITEM 44.1 (29 Aug 2026). `degraded_calls` used to
            # mean ONLY "no tier answered", so on 2026-08-29 every [BUDGET] line
            # read degraded=0 while TWELVE step contracts read DEGRADED — a step
            # that ran entirely on the 3B reported functional success.
            # Kimi: "The budget ledger's degraded=0 is dishonest because it
            # reports functional success while hiding that scored outputs came
            # from a model the provenance system cannot trust."
            # So `degraded_calls` now means what the step contract means by the
            # word — the answer did not come from the cloud — and the older,
            # narrower and still REAL fact keeps its own name below. One word
            # with two meanings was the bug; the fix is two names, not a
            # redefinition that loses one of them.
            "degraded_calls": 0,      # answered by a local tier, OR nothing answered
            "no_tier_calls": 0,       # nothing answered at all
            "tiers": {},
            "started": time.monotonic(),
        }
        return dict(_open_step)


def end_step() -> Optional[dict]:
    """Close the account and return what it spent. None if none was open."""
    global _open_step
    with _step_lock:
        if _open_step is None:
            return None
        out = dict(_open_step)
        out["wall_sec"] = round(time.monotonic() - out["started"], 3)
        _open_step = None
    return out


def current_step() -> Optional[dict]:
    with _step_lock:
        return dict(_open_step) if _open_step is not None else None


def remaining_sec() -> Optional[float]:
    with _step_lock:
        if _open_step is None:
            return None
        return max(0.0, _open_step["budget"].seconds - _open_step["spent"])


def run_call(cloud: Optional[Callable] = None,
             local_3b: Optional[Callable] = None,
             local_8b: Optional[Callable] = None,
             now: Callable = time.monotonic) -> LadderResult:
    """One model call, laddered, charged to the OPEN STEP's account.

    With no step open this still works — it just gets a default budget and keeps
    no running total, so a call made outside a step (a script, a selftest) is
    never blocked by an account that does not exist.
    """
    state = current_step()
    if state is None:
        return run_with_ladder("_no_step", NORMAL,
                               Budget("_no_step", MIN_BUDGET_SEC * 2, "default", 0),
                               cloud, local_3b, local_8b, now)

    left = remaining_sec() or 0.0
    # WHY NOT `left <= 0` (measured, not reasoned): each call spends a THIRD of
    # what remains, so the account decays geometrically and never actually
    # reaches zero. Four abandoned calls against B=0.9s left 0.171s. The total
    # spend is still bounded by B, so the step's clock was safe — but the
    # "degrade without touching the network" branch was unreachable, and the step
    # went on making calls with slices of 0.3s, 0.2s, 0.13s, none of which any
    # model could answer in. Useless calls that still cost a socket.
    #
    # So the account is empty when no TIER could land in its slice. One second is
    # generous for that: the fastest real answer measured on this box is ~7s.
    # In production this floor never binds — real budgets are 900-3600s, so the
    # slices are 300-1200s.
    if left / 3.0 < MIN_TIER_SEC:
        # The step has spent its budget. Not an error and not a kill: the step
        # keeps running, it just stops being allowed to wait for models.
        res = LadderResult(
            state["step"], DEGRADED, None, None, state["budget"].seconds, 0.0,
            [Attempt(CLOUD, SKIPPED, 0.0, "step budget exhausted")],
            "step budget of {:.0f}s already spent by {} earlier call(s); this one "
            "degrades without waiting".format(state["budget"].seconds,
                                              state["calls"]))
        print("  [LADDER] ALL TIERS SKIPPED for {}: account empty — B={:.0f}s "
              "spent by {} earlier call(s), no tier could land in the "
              "remainder".format(state["step"], state["budget"].seconds,
                                 state["calls"]))
        _charge(0.0, res)
        return res

    # The per-call budget is EXACTLY what is left, so the thirds shrink as the
    # step spends. No MIN_BUDGET_SEC floor here, and that is the whole point:
    # the floor belongs to budget_for(), which sets the STEP's budget, and
    # applying it again per call let a call be granted 30s out of an account
    # holding 6 — measured, first run of this code: "1 model call, 10s of B=6s".
    # A budget that a call may exceed is not a budget, it is a suggestion.
    call_budget = Budget(state["step"], left,
                         state["budget"].source, state["budget"].runs_seen)
    res = run_with_ladder(state["step"], state["priority"], call_budget,
                          cloud, local_3b, local_8b, now)
    _charge(res.elapsed_sec, res)
    return res


def _charge(seconds: float, res: LadderResult) -> None:
    with _step_lock:
        if _open_step is None:
            return
        _open_step["spent"] += float(seconds or 0.0)
        _open_step["calls"] += 1
        if res.outcome == DEGRADED:
            # Nothing answered. Still degraded, and ALSO its own distinct fact.
            _open_step["no_tier_calls"] += 1
            _open_step["degraded_calls"] += 1
        elif res.tier is not None and res.tier != CLOUD:
            # A local tier answered. The step contract already calls this
            # DEGRADED; until now the ledger did not.
            _open_step["degraded_calls"] += 1
        if res.tier:
            _open_step["tiers"][res.tier] = _open_step["tiers"].get(res.tier, 0) + 1


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/step_budget.py --selftest")
    print("  repo base            {}".format(BASE))

    ok = True
    baseline_path = BASE / "memory" / "step_contract_baseline.json"
    baseline = _load_json(baseline_path)
    if baseline:
        print("  step_contract        LIVE ({} labels with history)".format(len(baseline)))
    else:
        print("  step_contract        INERT (no {})".format(baseline_path.name))
        ok = False

    try:
        from core.cycle_map import ALIASES, STEPS
        print("  cycle_map            LIVE ({} steps, {} aliases)".format(
            len(STEPS), len(ALIASES)))
    except Exception as e:
        print("  cycle_map            INERT ({}: {})".format(type(e).__name__, e))
        ok = False
        STEPS = []

    sched = _load_json(BASE / "config" / "scheduler.json")
    print("  scheduler.json       {}".format(
        "LIVE ({} ceilings)".format(len(sched.get("step_ceilings_sec") or {}))
        if sched else "INERT"))

    try:
        runner = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                           errors="replace")
        wired = "step_budget" in runner
    except OSError:
        wired = False
    print("  fast_cycle_runner    {}".format(
        "WIRED" if wired else
        "NOT WIRED — steps still take the old single hard ceiling"))

    if STEPS:
        by_p95 = [s for s, *_ in STEPS if budget_for(s, baseline).source == "p95"]
        print("  budgets from p95     {}/{} steps "
              "(the rest fall back to the config ceiling)".format(
                  len(by_p95), len(STEPS)))
        for name in ("internet_intelligence", "daily_analysis", "web_intelligence"):
            b = budget_for(name, baseline)
            print("    {:<24} B={:>7.0f}s  per-tier={:>6.0f}s  "
                  "source={} runs={}".format(name, b.seconds, b.per_tier,
                                             b.source, b.runs_seen))

    # A dead cloud must degrade, not hang.
    b = Budget("selftest", 3.0, "ceiling", 0)
    t0 = time.monotonic()
    res = run_with_ladder("selftest", NORMAL, b,
                          cloud=lambda: None, local_3b=lambda: None)
    took = time.monotonic() - t0
    assert res.outcome == DEGRADED and res.value is None, res
    assert took < 2.0, "a None-returning cloud must not consume its slice"
    print("  dead-cloud smoke     DEGRADED in {:.3f}s, value=None".format(took))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
