#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/verify_checkpoint_map.py — CAN EVERY NAME THE RUNNER WRITES BE SHOWN?

A checkpoint that core/cycle_map.py cannot resolve lights no square in the
cockpit and appears in no report. It is not an error anywhere — it is dropped,
silently, and the checklist simply under-reports. On the 23 Aug 2026 cycle ten
of thirty-one recorded names were dropped that way.

This asks two questions and answers both from disk, with NO CYCLE RUNNING:

  1. REPLAY — take the last sealed cycle's checkpoint set out of
     memory/cycle_resume.jsonl and resolve every name against the map.
  2. REACH  — take every name fast_cycle_runner.py CAN write (its beat() labels
     and its _run() labels, read out of the source) and resolve those too.

Question 2 is the one that matters going forward: the replay can only ever
contain names that were written under the old arrangement, where 15 of the first
16 steps could not checkpoint at all.

    venv/Scripts/python.exe scripts/verify_checkpoint_map.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.cycle_map import (ALIAS, ALIASES, STEP, STEPS, SUBSTEP,  # noqa: E402
                            SUBSTEPS, UNKNOWN, resolve)

RESUME = BASE / "memory" / "cycle_resume.jsonl"
LEDGER = BASE / "memory" / "existence_ledger.jsonl"
RUNNER = BASE / "fast_cycle_runner.py"


def runner_labels() -> tuple:
    """(beat labels, _run labels) as the source actually spells them."""
    src = RUNNER.read_text(encoding="utf-8", errors="replace")
    beats = re.findall(r"(?<!def )beat\(\s*[\"']([A-Za-z0-9_]+)[\"']", src)
    runs = re.findall(r"_run\(\s*[\"']([A-Za-z0-9_]+)[\"']", src)
    return list(dict.fromkeys(beats)), list(dict.fromkeys(runs))


def last_sealed_cycle_id():
    """The newest cycle_id the existence ledger recorded as FINISHED."""
    try:
        rows = [json.loads(l) for l in
                LEDGER.read_text(encoding="utf-8", errors="replace").splitlines()
                if l.strip()]
    except OSError:
        return None
    for row in reversed(rows):
        if str(row.get("event", "")).upper().startswith("CYCLE_FINISHED"):
            return row.get("cycle_id")
    return None


def checkpoints(cycle_id: str) -> list:
    out = []
    try:
        lines = RESUME.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("cycle_id") == cycle_id and row.get("last_completed_step"):
            out.append(row)
    return out


def _report(title: str, names: list) -> tuple:
    kinds = {STEP: [], ALIAS: [], SUBSTEP: [], UNKNOWN: []}
    for n in names:
        canon, kind = resolve(n)
        kinds[kind].append((n, canon))
    resolved = len(names) - len(kinds[UNKNOWN])
    print("\n{}".format(title))
    print("  {}/{} names resolve".format(resolved, len(names)))
    for kind in (STEP, ALIAS, SUBSTEP):
        if kinds[kind]:
            print("    {:<8} {}".format(kind, len(kinds[kind])))
    if kinds[UNKNOWN]:
        print("    FALLS ON THE FLOOR ({}): {}".format(
            len(kinds[UNKNOWN]), ", ".join(n for n, _ in kinds[UNKNOWN])))
    else:
        print("    nothing falls on the floor")
    return resolved, len(names)


def main() -> int:
    print("scripts/verify_checkpoint_map.py")
    print("  map: {} STEPS entries ({} distinct names), {} aliases, {} substeps"
          .format(len(STEPS), len({s[0] for s in STEPS}), len(ALIASES),
                  len(SUBSTEPS)))

    cid = last_sealed_cycle_id()
    print("  last sealed cycle: {}".format(cid or "(none in the ledger)"))

    rc = (0, 0)
    if cid:
        rows = checkpoints(cid)
        names = list(dict.fromkeys(r["last_completed_step"] for r in rows))
        hows = {}
        for r in rows:
            hows[r.get("how", "returned")] = hows.get(r.get("how", "returned"), 0) + 1
        print("  {} checkpoint(s) recorded, {} distinct name(s); how={}"
              .format(len(rows), len(names), hows))
        rc = _report("REPLAY — the last sealed cycle's checkpoint set:", names)

    beats, runs = runner_labels()
    union = list(dict.fromkeys(beats + runs))
    print("\n  runner writes from {} beat() label(s) and {} _run() label(s); "
          "{} distinct".format(len(beats), len(runs), len(union)))
    reach = _report("REACH — every name fast_cycle_runner.py can write:", union)

    # The one number a human should read: how many of the cycle's own steps can
    # now put themselves on record. Every beat() label is a step boundary.
    print("\n  STEP BOUNDARIES THAT CAN NOW CHECKPOINT: {}/{}".format(
        sum(1 for b in beats if resolve(b)[1] != UNKNOWN), len(beats)))
    return 0 if (rc[0] == rc[1] and reach[0] == reach[1]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
