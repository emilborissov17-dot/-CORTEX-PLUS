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
    ceiling = ceiling_for(step, ceilings)
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
    """
    slice_sec = budget.per_tier
    started = now()
    attempts: list = []

    tiers = [
        (CLOUD, cloud, True),
        (LOCAL_3B, local_3b, True),
        (LOCAL_8B, local_8b, priority == CRITICAL),
    ]

    for tier, fn, allowed in tiers:
        if fn is None:
            attempts.append(Attempt(tier, SKIPPED, 0.0, "no callable supplied"))
            continue
        if not allowed:
            attempts.append(Attempt(tier, SKIPPED, 0.0,
                                    "priority is {}, 8b is CRITICAL-only".format(priority)))
            continue

        spent = now() - started
        remaining = budget.seconds - spent
        if remaining <= 0:
            attempts.append(Attempt(tier, SKIPPED, 0.0, "budget exhausted"))
            continue

        outcome, value, error, elapsed = call_with_timeout(
            fn, min(slice_sec, remaining))
        attempts.append(Attempt(tier, outcome, round(elapsed, 3), error))

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
            "degraded_calls": 0,
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
