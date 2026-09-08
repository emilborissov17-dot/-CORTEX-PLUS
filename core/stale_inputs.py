#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/stale_inputs.py — A GATE SHUT BY AN OLD FILE MUST SAY WHICH FILE.

THE DEFECT THIS CLOSES (8 Sep 2026)
------------------------------------
core/notary._age_state() takes the OLDEST declared input of a step and turns it
into one number. That number then flows into own = min(five dimensions), and the
gate refuses. The refusal sentence does name the oldest file — but only when the
age dimension happened to tie for the minimum, and only inside a string.

So a single dead file can hold a gate shut for months and read, from outside, as
"the notary is being cautious". Measured on this repo:

    memory/self_awareness.json   last written 2026-03-11, 180.7 days
    with it:     age = MINIMAL(1)   -> own = 1 -> below IRREVERSIBLE_MIN(2)
    without it:  age = FULL(3)      -> the age dimension stops binding

One file, no writer anywhere in the repo, and it was the whole of the age
dimension for step 18.

WHAT THIS DOES
---------------
Answers, mechanically and at any time: which declared inputs of `step` are older
than the threshold at which age stops being FULL-or-REDUCED and starts dragging a
step below the line. The runner writes the answer to memory/night_events.jsonl on
every gate crossing, PASS OR REFUSE — a gate that opens while standing on a
half-year-old input is the more dangerous case and used to print nothing.

THE THRESHOLD IS NOT A NEW NUMBER. It is stale_days[1] from
config/passage_rules.json — the same boundary the notary uses to drop a step from
REDUCED to MINIMAL. Inventing a second threshold here would be exactly the drift
that config/passage_rules.json exists to end.

WHAT THIS IS NOT
-----------------
It grants nothing, lifts nothing, decides nothing, and appends no attestation. It
does not make an old file young. The only thing it changes is that an old file
stops being invisible.

    venv\\Scripts\\python.exe core/stale_inputs.py --selftest
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Sentinel for "the file the step declares does not exist at all". Distinct from
# a large age: a missing input and an ancient one need different fixes, and
# collapsing them into one number is how the second gets mistaken for the first.
MISSING = None


def _threshold_days() -> float:
    """The boundary past which age drags a step below the line, from the one
    ruleset. Fail-safe: on an unreadable ruleset, flag EVERYTHING older than the
    tightest threshold rather than nothing — silence is never the safe default
    here either.
    """
    try:
        from core.passage_rules import RULES
        return float(RULES["stale_days"][1])
    except Exception:
        return 2.0


def stale_inputs_for(step: str, days: float | None = None) -> list[dict]:
    """[{artifact, age_days, missing}] — declared inputs old enough to bind.

    Reads core.notary._inputs_for, imported rather than reimplemented, so this
    sees exactly the list the gate grades. A second copy of that lookup would
    drift and start reporting a staleness the notary does not act on.
    """
    limit = _threshold_days() if days is None else float(days)
    try:
        from core.notary import _inputs_for, BASE
    except Exception as exc:                                     # noqa: BLE001
        raise RuntimeError(f"cannot read the notary's input lookup: {exc}") from exc

    declared, _src = _inputs_for(step)
    now = time.time()
    out: list[dict] = []
    for rel in declared:
        path = Path(BASE) / rel
        try:
            if path.is_dir():
                mtime = max((c.stat().st_mtime for c in path.rglob("*")
                             if c.is_file()), default=0)
            else:
                mtime = path.stat().st_mtime
        except Exception:
            out.append({"artifact": rel, "age_days": MISSING, "missing": True})
            continue
        if not mtime:
            out.append({"artifact": rel, "age_days": MISSING, "missing": True})
            continue
        age = (now - mtime) / 86400.0
        if age > limit:
            out.append({"artifact": rel, "age_days": round(age, 1),
                        "missing": False})
    return sorted(out, key=lambda d: d["artifact"])


def describe(step: str, stale: list[dict] | None = None,
             days: float | None = None) -> str:
    """One line naming every stale input, for the night event."""
    limit = _threshold_days() if days is None else float(days)
    stale = stale_inputs_for(step, days) if stale is None else stale
    if not stale:
        return f"{step}: every declared input is newer than {limit:g} days"
    parts = "; ".join(
        f"{s['artifact']} (MISSING)" if s["missing"]
        else f"{s['artifact']} ({s['age_days']}d)"
        for s in stale)
    return (f"{step}: {len(stale)} stale input(s) past {limit:g} days — {parts}. "
            f"The OLDEST of these sets this step's age dimension, and age is one "
            f"of the five that own=min() is taken over, so any one of them can "
            f"hold this gate shut on its own.")


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/stale_inputs.py --selftest")
    try:
        from core.notary import _inputs_for  # noqa: F401
        print("  core.notary._inputs_for  : LIVE")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  core.notary._inputs_for  : INERT ({type(exc).__name__}: {exc})")
        print("  RESULT: BROKEN")
        return 1

    try:
        from core.passage_rules import RULES
        print(f"  threshold from ruleset   : LIVE ({_threshold_days():g} days, "
              f"stale_days={RULES['stale_days']})")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  threshold from ruleset   : INERT ({type(exc).__name__}: {exc}) "
              f"— falling back to {_threshold_days():g} days")

    for step in ("self_modifier", "execute_patches", "github_publish"):
        stale = stale_inputs_for(step)
        print(f"  {step}: {len(stale)} stale input(s)")
        for s in stale:
            age = "MISSING" if s["missing"] else f"{s['age_days']}d"
            print(f"      {s['artifact']}  {age}")

    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(_selftest())
