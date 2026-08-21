#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/survival_mode.py — WHEN THE BUDGET IS SPENT, DEGRADE. DO NOT DIE.

WHAT IT REPLACES
-----------------
Today, when the restart budget is exhausted, supervisor.py stops:

    !!! RESTART BUDGET EXHAUSTED — the system is NOT running.
    Human intervention required.

memory/scheduler_state.json says how normal that is. The budget has been spent
2/2 on sixteen of the last seventeen days. "Fail loudly and wait for a human" is
not an exceptional path here; it is most nights. A system that stops on most
nights is not being safe, it is being absent.

Survival mode is the other answer to the same condition: run only the CRITICAL
steps, cut every ceiling to p50, keep the data local, and let the day produce
something. It degrades until 03:00. It does not die.

THE BYPASS THIS MODULE IS BUILT AROUND
---------------------------------------
Found while orienting on 21 Aug 2026, and it decides the whole design.

At 16:09 UTC the supervisor logged the budget exhausted and refused to restart.
At 17:00 UTC a cycle started anyway, and `supervisor --status` reported it
healthy. The scheduled task starts cycles on its own clock; the restart budget
bounds only the SUPERVISOR's restarts. So a fresh cycle process begins life with
an in-process restart counter of zero and no idea that the day is already lost.

Therefore survival mode must NEVER be derived from anything held in memory. It is
resolved from two files on disk, both of which outlive any process:

    memory/scheduler_state.json   written by the supervisor: restarts per day,
                                  and the `failure` block for the current day
    memory/survival_state.json    written here: the latched flag, so a mode
                                  entered by one process is seen by the next

A cycle started by the scheduler at 03:00 reads the same two files the supervisor
wrote at 02:40 and reaches the same conclusion. That is the entire point.

    venv\\Scripts\\python.exe core/survival_mode.py --selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.step_budget import CRITICAL, NORMAL, ceiling_for, learned_seconds, percentile

BASE = pathlib.Path(__file__).resolve().parents[1]

PRIORITY_FILE = "step_priority.json"
STATE_FILE = "survival_state.json"
SCHEDULER_STATE_FILE = "scheduler_state.json"

# The alarm the human gets, once per entry. Kept as a constant because the dedup
# key downstream is date:subject[:40] and a drifting subject would defeat it.
NOTICE_SUBJECT = "ENTERING SURVIVAL MODE"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# The priority table
# ---------------------------------------------------------------------------

def load_priorities(base: Optional[pathlib.Path] = None) -> dict:
    """step -> CRITICAL | NORMAL, from config/step_priority.json.

    A missing or unreadable file yields an EMPTY table, which makes every step
    NORMAL — and survival mode with an empty CRITICAL set runs nothing. That is
    deliberate: a survival mode that invents its own protected list when its
    config is gone is worse than one that visibly does nothing, because the
    invented list would look authoritative. plan() names the condition.
    """
    cfg = _load_json((base or BASE) / "config" / PRIORITY_FILE)
    return {step: CRITICAL for step in (cfg.get("CRITICAL") or [])}


def priority_of(step: str, table: Optional[dict] = None,
                base: Optional[pathlib.Path] = None) -> str:
    if table is None:
        table = load_priorities(base)
    return table.get(step, NORMAL)


def is_critical(step: str, table: Optional[dict] = None,
                base: Optional[pathlib.Path] = None) -> bool:
    return priority_of(step, table, base) == CRITICAL


# ---------------------------------------------------------------------------
# The persisted flag
# ---------------------------------------------------------------------------

def read_state(base: Optional[pathlib.Path] = None) -> dict:
    return _load_json((base or BASE) / "memory" / STATE_FILE)


def _write_state(state: dict, base: Optional[pathlib.Path] = None) -> None:
    path = (base or BASE) / "memory" / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def derived_from_disk(scheduler_state: dict, cfg: dict, today: str) -> tuple:
    """(should_be_active, reason) from what the SUPERVISOR persisted. No memory.

    Two independent triggers, either sufficient:
      * restarts for `today` have reached max_restarts_per_day
      * a `failure` block is recorded for `today`

    The second exists because the supervisor writes it on the same tick it gives
    up, and a reader that only counted restarts would miss a day lost some other
    way.
    """
    budget = int(cfg.get("max_restarts_per_day", 2))
    used = int((scheduler_state.get("restarts") or {}).get(today, 0))
    if used >= budget:
        return True, ("restart budget exhausted for {} ({}/{}) — persisted in "
                      "scheduler_state.json".format(today, used, budget))

    failure = scheduler_state.get("failure") or {}
    if failure.get("date") == today:
        return True, ("a failure is recorded for {} on step {!r}".format(
            today, failure.get("wedged_step")))

    return False, "restarts {}/{} for {}, no failure recorded".format(
        used, budget, today)


def resolve(today: str,
            base: Optional[pathlib.Path] = None,
            scheduler_state: Optional[dict] = None,
            cfg: Optional[dict] = None) -> tuple:
    """(active, reason, is_new_entry) — the answer any process can reach alone.

    The latched flag wins if it is for TODAY; otherwise the day's state is
    re-derived. A latch from yesterday is not carried over: survival mode is a
    property of a day, and 03:00 is a fresh start by design.
    """
    root = base or BASE
    if scheduler_state is None:
        scheduler_state = _load_json(root / "memory" / SCHEDULER_STATE_FILE)
    if cfg is None:
        cfg = _load_json(root / "config" / "scheduler.json")

    latched = read_state(root)
    if latched.get("active") and latched.get("date") == today:
        return True, latched.get("reason", "latched"), False

    should, reason = derived_from_disk(scheduler_state, cfg, today)
    return should, reason, should


def enter(today: str, reason: str,
          base: Optional[pathlib.Path] = None,
          notifier: Optional[Callable] = None) -> dict:
    """Latch the flag and send AT MOST ONE notice, ever, per day.

    `notifier` is injected and defaults to None — this module never reaches for
    Telegram itself. On 16 Aug 2026 a test in this repo sent a REAL emergency
    alarm to the human's phone about a failure that never happened, and then
    suppressed that day's genuine alarm through the dedup key. A module that
    imports its own alarm path can be made to do that again by any caller that
    forgets to mock it. One that takes the notifier as an argument cannot.

    The `notified` flag lives in the persisted state, so the once-ness survives a
    process death — which matters precisely here, where the expected caller is a
    fresh cycle process that knows nothing about the one before it.
    """
    root = base or BASE
    state = read_state(root)

    already = bool(state.get("active") and state.get("date") == today)
    notified = bool(state.get("notified") and state.get("date") == today)

    new_state = {
        "active": True,
        "date": today,
        "reason": reason,
        "since_utc": state.get("since_utc") if already else _now_utc(),
        "notified": notified,
        "entries": int(state.get("entries", 0)) + (0 if already else 1),
    }

    if notifier is not None and not notified:
        try:
            notifier(NOTICE_SUBJECT, reason)
            new_state["notified"] = True
        except Exception as e:                        # noqa: BLE001
            # A failed alarm must not become a failed survival mode. Record it
            # and stay un-notified so a later tick can try again.
            new_state["notify_error"] = "{}: {}".format(type(e).__name__, e)

    _write_state(new_state, root)
    return new_state


def clear(base: Optional[pathlib.Path] = None) -> dict:
    state = {"active": False, "cleared_utc": _now_utc()}
    _write_state(state, base)
    return state


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

@dataclass
class SurvivalPlan:
    active: bool
    reason: str
    run: list = field(default_factory=list)
    skip: list = field(default_factory=list)
    ceilings: dict = field(default_factory=dict)      # step -> (seconds, source)
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def p50_ceiling(step: str, baseline: Optional[dict] = None,
                ceilings: Optional[dict] = None) -> tuple:
    """(seconds, source). p50 of observed runs, or the config ceiling untouched.

    "Cut every ceiling to p50" is only meaningful where a p50 exists. Where it
    does not, the ceiling is left ALONE rather than divided by a made-up factor —
    a fabricated tighter ceiling on a step with no history is just a new way to
    kill a healthy step.
    """
    seen = learned_seconds(step, baseline)
    p50 = percentile(seen, 0.5)
    if p50 is None:
        return ceiling_for(step, ceilings), "ceiling (no p50: {} run(s))".format(len(seen))
    return p50, "p50 of {} run(s)".format(len(seen))


def plan(steps: list, active: bool, reason: str = "",
         table: Optional[dict] = None,
         baseline: Optional[dict] = None,
         ceilings: Optional[dict] = None,
         base: Optional[pathlib.Path] = None) -> SurvivalPlan:
    """Which steps run, and under which ceilings.

    Inactive is not a special case with its own code path — every step runs, and
    the ceilings are the ordinary ones. Same function, so the plan is inspectable
    on a normal night too.
    """
    if table is None:
        table = load_priorities(base)

    warnings = []
    if active and not table:
        warnings.append(
            "config/step_priority.json is missing or empty: NO step is CRITICAL, "
            "so survival mode would run nothing. Refusing to guess a list.")

    run, skip, out = [], [], {}
    for step in steps:
        critical = table.get(step, NORMAL) == CRITICAL
        if active and not critical:
            skip.append(step)
            continue
        run.append(step)
        out[step] = (p50_ceiling(step, baseline, ceilings) if active
                     else (ceiling_for(step, ceilings), "ceiling"))

    return SurvivalPlan(active, reason, run, skip, out, warnings)


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/survival_mode.py --selftest")
    print("  repo base            {}".format(BASE))
    ok = True

    table = load_priorities()
    if table:
        print("  step_priority.json   LIVE ({} CRITICAL steps)".format(len(table)))
    else:
        print("  step_priority.json   INERT (missing or empty)")
        ok = False

    sched_path = BASE / "memory" / SCHEDULER_STATE_FILE
    sched = _load_json(sched_path)
    print("  scheduler_state.json {}".format(
        "LIVE ({} days of restarts recorded)".format(len(sched.get("restarts") or {}))
        if sched else "INERT — survival mode cannot be derived without it"))
    if not sched:
        ok = False

    state_path = BASE / "memory" / STATE_FILE
    print("  survival_state.json  exists={}".format(state_path.exists()))

    try:
        from core.cycle_map import STEPS
        names = [s for s, *_ in STEPS]
        print("  cycle_map            LIVE ({} steps)".format(len(names)))
    except Exception as e:
        print("  cycle_map            INERT ({}: {})".format(type(e).__name__, e))
        return 1

    for name in ("supervisor.py", "fast_cycle_runner.py"):
        try:
            wired = "survival_mode" in (BASE / name).read_text(encoding="utf-8",
                                                               errors="replace")
        except OSError:
            wired = False
        print("  {:<20} {}".format(
            name, "WIRED" if wired else
            "NOT WIRED — budget exhausted still means STOP, not survive"))

    # Read-only: what would today look like?
    today = datetime.now().date().isoformat()
    cfg = _load_json(BASE / "config" / "scheduler.json")
    should, reason, _ = resolve(today, scheduler_state=sched, cfg=cfg)
    print("  would be active today {}  ({})".format(should, reason))

    p = plan(names, active=True, table=table)
    print("  under survival mode  run {} / skip {}".format(len(p.run), len(p.skip)))
    for w in p.warnings:
        print("  WARNING: {}".format(w))

    unknown = sorted(set(table) - set(names))
    if unknown:
        print("  WARNING: CRITICAL names not in cycle_map: {}".format(unknown))
        ok = False
    else:
        print("  every CRITICAL name exists in cycle_map: OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
