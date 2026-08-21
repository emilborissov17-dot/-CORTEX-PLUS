#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/migrate_pin_score_meaning.py — SAY WHAT A SCORE MEANS, WHERE IT IS NOT ARGUABLE.

THE AMBIGUITY
--------------
core/metta_parallel R3 found this on 20 August and again on 21 August:

    auto_levels.json         CLIMATE_GLOBAL_RISK_REVIEW -> LOW
    goal_score_latest.json   CLIMATE_GLOBAL_RISK_REVIEW -> 0.8185

Whether those two disagree depends on something nobody wrote down. If the score
means GOODNESS, 81.85/100 is healthy and a level of LOW contradicts it. If a
_RISK_ axis's level means RISK, then LOW risk and a high goodness score AGREE
perfectly. The same two numbers are either a contradiction or a match, and the
system has no way to tell.

WHAT THIS MIGRATION DOES, AND DELIBERATELY DOES NOT
-----------------------------------------------------
It writes "score_meaning": "goodness" onto the 23 axes where the reading is not
arguable — higher_better, lower_better and stable_better all normalise to a
0..1 goodness score in goal_score_calculator, so a high score is a good state
and a level word must be read the same way.

THE POLARITY RULING (21 August 2026, Emil) settled what this migration first
refused to guess. One rule for all 25 axes: THE LEVEL WORD DESCRIBES CLOSENESS
TO GOAL — LOW = far from goal = bad, everywhere. Risk inverts ONCE, at
measurement, and never again in the label.

So the two _RISK_ axes are pinned too. CLIMATE_GLOBAL_RISK at 81.85/100 is
HIGH: close to goal. Human-facing reports translate that to "ниво HIGH (нисък
риск)" so the word reads correctly to a person, and renaming the axes so their
names stop inviting the wrong reading belongs to the August axis migration.

COMPOSITE-NEUTRAL. score_meaning is metadata: goal_score_calculator does not
read it, no weight moves, and the composite before and after must be identical
to the digit. The script refuses to write if it is not.

    venv/Scripts/python.exe scripts/migrate_pin_score_meaning.py          # dry run
    venv/Scripts/python.exe scripts/migrate_pin_score_meaning.py --write
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "target_config.json"

GOODNESS = "goodness"
UNAMBIGUOUS = ("higher_better", "lower_better", "stable_better")


def axes_of(cfg: dict):
    for branch, axes in cfg.items():
        if branch.startswith("_") or not isinstance(axes, dict):
            continue
        for axis, spec in axes.items():
            if isinstance(spec, dict):
                yield branch, axis, spec


def is_ambiguous(axis: str, spec: dict) -> str | None:
    """Returns the reason this axis must stay unpinned, or None.

    ── THE POLARITY RULING, 21 August 2026, Emil ──────────────────────────
    One rule for all 25 axes: THE LEVEL WORD DESCRIBES CLOSENESS TO GOAL.
    LOW = far from goal = bad, on every axis without exception. Risk inverts
    ONCE, at measurement — the score is already risk-inverted — and never
    again in the label.

    That resolves what this function used to refuse. The two _RISK_ axes were
    held back because "LOW" could be read as "low risk", the opposite polarity.
    Under the ruling it cannot: LOW always means far from goal. So they are
    pinned like everything else, and CLIMATE_GLOBAL_RISK at 81.85/100 is HIGH —
    close to goal — with the human-facing reports adding "(нисък риск)" so the
    word reads correctly to a person.

    Renaming the two axes so their names stop inviting the wrong reading is
    Emil's, and belongs to the August axis migration, not here.

    The function stays because the SHAPE of the rule is still needed: an axis
    whose direction is not one of the three normalising forms cannot be pinned
    by anything but a human.
    """
    if spec.get("direction") not in UNAMBIGUOUS:
        return f"direction {spec.get('direction')!r} is not one of {UNAMBIGUOUS}"
    return None


def composite() -> float | None:
    try:
        goal = json.loads((BASE / "snapshots" / "master" /
                           "goal_score_latest.json").read_text(encoding="utf-8"))
        return goal.get("composite_score")
    except Exception:
        return None


def plan() -> tuple[list, list]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    pin, leave = [], []
    for _, axis, spec in axes_of(cfg):
        why = is_ambiguous(axis, spec)
        (leave if why else pin).append((axis, spec.get("direction"), why))
    return pin, leave


def main() -> int:
    write = "--write" in sys.argv
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    pin, leave = plan()

    print(f"PIN score_meaning={GOODNESS!r} on {len(pin)} axes:")
    for axis, direction, _ in pin:
        print(f"  {axis:<34} {direction}")
    print(f"\nLEAVE UNPINNED — for Emil, {len(leave)} axes:")
    for axis, direction, why in leave:
        print(f"  {axis:<34} {direction}\n      {why}")

    before = composite()
    for _, axis, spec in axes_of(cfg):
        if not is_ambiguous(axis, spec):
            spec["score_meaning"] = GOODNESS

    total = sum(s.get("weight", 0) or 0 for _, _, s in axes_of(cfg))
    print(f"\ntotal weight {total} | axes {len(pin) + len(leave)} | "
          f"composite {before}")

    if not write:
        print("\nDRY RUN. Nothing written. Re-run with --write.")
        return 0

    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    after_total = sum(s.get("weight", 0) or 0
                      for _, _, s in axes_of(json.loads(
                          CONFIG.read_text(encoding="utf-8"))))
    print(f"\nwrote {CONFIG.relative_to(BASE)} — weight {total} -> {after_total}")
    if after_total != total:
        print("WEIGHT MOVED. This migration is supposed to be composite-neutral.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
