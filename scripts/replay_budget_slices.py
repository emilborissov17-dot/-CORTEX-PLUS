#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/replay_budget_slices.py — OLD SLICE vs NEW SLICE, ON THE NIGHT IT COST.

THE NIGHT
----------
memory/cycle_logs/cycle_2026-08-22_112231.log. Three steps produced nothing
while 48-80 seconds of their budget sat unused, and all three failed the same
way — the log says so in its own words:

    [LLM] DEGRADED: no tier produced a result within B=120s
          (cloud=EMPTY, local_3b=TIMEOUT, local_8b=SKIPPED)

cloud=EMPTY means every provider was rate-limited or in cooldown: a declined
answer, not a slow one, and it costs whatever the chain took to decline.
local_3b=TIMEOUT means the 3b was cut off at its slice — B/3 = 40s — against a
measured mean of ~23s for a warm answer. local_8b=SKIPPED because the 8b is
offered only inside its residency window, so there were only ever TWO tiers on
that ladder, splitting the budget three ways.

WHAT IS REPLAYED
-----------------
The real run_with_ladder(), with call_with_timeout replaced by a recorder that
returns the outcome the log recorded and reports the slice it was handed. No
wall-clock, no model, no sleeping — the slice arithmetic is what is under test
and it is exercised exactly as the cycle exercises it.

The cloud's elapsed time is DERIVED, not measured: the log records the step's
total spend and the fact that the 3b consumed its whole slice, so
cloud_elapsed = spent - 40. That derivation is printed with the numbers.

    venv/Scripts/python.exe scripts/replay_budget_slices.py
"""
from __future__ import annotations

import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import core.step_budget as sb  # noqa: E402

LOG = BASE / "memory" / "cycle_logs" / "cycle_2026-08-22_112231.log"
STEPS = ("cortex_strategist_agent", "hyperclaw_orchestrator", "cortex_reasoner")

BUDGET_RE = re.compile(
    r"\[BUDGET\] (?P<step>[A-Za-z0-9_]+): (?P<calls>\d+) model call\(s\), "
    r"(?P<spent>[\d.]+)s of B=(?P<budget>[\d.]+)s, tiers=(?P<tiers>\S+) "
    r"degraded=(?P<degraded>\d+)")


def from_log() -> list:
    """The three steps as the log recorded them. Nothing typed by hand."""
    try:
        text = LOG.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("  cannot read {}: {}".format(LOG, exc))
        return []
    out = []
    for m in BUDGET_RE.finditer(text):
        if m.group("step") in STEPS and m.group("tiers") == "{}":
            out.append({"step": m.group("step"),
                        "spent": float(m.group("spent")),
                        "budget": float(m.group("budget"))})
    return out


class Recorder:
    """Stands in for call_with_timeout. Records the slice, returns the outcome."""

    def __init__(self, script):
        self.script = list(script)      # [(outcome, elapsed), ...] in tier order
        self.slices = []
        self.i = 0

    def __call__(self, fn, timeout_sec):
        outcome, elapsed = self.script[min(self.i, len(self.script) - 1)]
        self.slices.append(round(timeout_sec, 1))
        self.i += 1
        return outcome, None, None, elapsed


def replay(step: str, budget_sec: float, cloud_elapsed: float) -> dict:
    """One step through the REAL ladder, with the recorder in place of the clock."""
    budget = sb.Budget(step, budget_sec, "replayed", 0)
    # cloud declines after cloud_elapsed; the 3b consumes whatever it is given.
    rec = Recorder([(sb.EMPTY, cloud_elapsed), (sb.TIMEOUT, 0.0)])
    real, sb.call_with_timeout = sb.call_with_timeout, rec

    # The ladder measures elapsed with now(); the second reading is the point
    # at which the cloud declined, which is what the 3b's remainder is cut from.
    class _Clock:
        def __init__(self):
            self.calls = 0

        def __call__(self):
            # first call is `started`; afterwards report the cloud's spend
            self.calls += 1
            return 0.0 if self.calls <= 1 else cloud_elapsed

    try:
        res = sb.run_with_ladder(step, sb.NORMAL, budget,
                                 cloud=lambda: None,
                                 local_3b=lambda: None,
                                 local_8b=None,          # outside its window
                                 now=_Clock())
    finally:
        sb.call_with_timeout = real
    return {"slices": rec.slices, "attempts": res.attempts}


def main() -> int:
    print("scripts/replay_budget_slices.py")
    print("  log: {}".format(LOG.name))
    rows = from_log()
    if not rows:
        print("  no matching [BUDGET] lines — nothing to replay")
        return 1

    print("\n  Only two tiers were viable that night: the 8b is offered only")
    print("  inside its residency window, so local_8b=SKIPPED on all three.")
    print("  OLD: every tier got B/3, whether or not three tiers existed.")
    print("  NEW: the LAST VIABLE tier gets the whole remainder.\n")

    header = ("  {:<24} {:>6} {:>7} {:>9} {:>9} {:>9} {:>9}".format(
        "step", "B", "spent", "cloud", "3b OLD", "3b NEW", "unused OLD"))
    print(header)
    print("  " + "-" * (len(header) - 2))

    sb.reset_cycle()
    for row in rows:
        b, spent = row["budget"], row["spent"]
        old_slice = b / 3.0
        cloud_elapsed = round(spent - old_slice, 1)   # 3b timed out at its slice
        out = replay(row["step"], b, cloud_elapsed)
        new_slice = out["slices"][-1]
        print("  {:<24} {:>5.0f}s {:>6.0f}s {:>8.0f}s {:>8.0f}s {:>8.0f}s "
              "{:>8.0f}s".format(row["step"], b, spent, cloud_elapsed,
                                 old_slice, new_slice, b - spent))

    print("\n  cloud state after the three: {}".format(sb.cloud_state()))

    print("\n  A FOURTH STEP, same night, same B — the demotion is now in force:")
    out = replay("a_fourth_step", 120.0, 0.0)
    tiers = ", ".join("{}={}".format(a.tier, a.outcome) for a in out["attempts"])
    print("    slices handed out: {}   ({})".format(out["slices"], tiers))
    print("    the cloud is not called at all, so the 3b is the only viable")
    print("    tier and receives the whole 120s instead of 40s.")

    sb.reset_cycle()
    print("\n  after reset_cycle() (the runner calls it at boot): {}".format(
        sb.cloud_state()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
