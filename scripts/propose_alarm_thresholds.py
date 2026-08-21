#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/propose_alarm_thresholds.py — SUGGEST THE RED LINES; DO NOT DRAW THEM.

WHY
----
25 axes have alarm_threshold: null, and every one is a number a person has to
choose. Asking Emil to write 25 numbers into a config by hand is how the file
stays empty for a year. So the system proposes a value per axis and files them
as PROPOSALS — into the same queue and the same 24-hour SLA clock as everything
else, approvable from the phone.

A SUGGESTION IS NOT A DEFAULT. Nothing here writes into target_config. The
nulls stay null until a human signs each one, and core/alarm_bands.py never
alarms on a null. The whole point of the empty bands is that they are a
standing question; a script that answered its own question would erase it.

WHERE THE NUMBERS COME FROM
----------------------------
Only from what the config already says about the axis — its target, its
direction and its own rationale line. In that order of preference:

  reference_worst   the config's own record of how bad it has been
  a number in the rationale   e.g. "current ~74%", "SDG2: near-zero hunger"
  a fraction of the target    the fallback, and the weakest, and it says so

Each proposal carries one line of reasoning naming which of the three it used,
so a reader can tell a grounded suggestion from an arithmetic one.

    venv/Scripts/python.exe scripts/propose_alarm_thresholds.py
    venv/Scripts/python.exe scripts/propose_alarm_thresholds.py --write
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "target_config.json"
OUT = BASE / "memory" / "threshold_proposals.json"

# How far past the target a red line sits when nothing better is available.
# Deliberately blunt: a number nobody can justify precisely should at least be
# one nobody can mistake for precision.
FALLBACK_MARGIN = 0.5

NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%?")

# ── CITATION NUMBERS ARE NOT THRESHOLDS ───────────────────────────────────
# Caught on the first run, before this shipped. CLIMATE_GLOBAL_RISK's rationale
# reads "(Rockström et al. 2009, Nature 461:472; ... safe boundary ~350 ppm)"
# and the extractor proposed a red line of 461 ppm — the volume number of the
# journal. A suggestion drawn from a bibliography looks exactly like one drawn
# from science, which is the whole reason each proposal has to name its basis.
#
# Everything inside a parenthesised citation, plus any four-digit year and any
# volume:page pair, is removed before numbers are read.
_CITATION = re.compile(
    r"\([^)]*(?:et al\.|,\s*\d{4}|Nature|Science|IPCC|doi)[^)]*\)", re.I)
_VOLUME_PAGE = re.compile(r"\b\d+\s*:\s*\d+\b")
_YEAR = re.compile(r"\b(?:1[89]|20)\d{2}\b")


# KNOWN FALSE NEGATIVE, stated rather than engineered around: a real threshold
# that happens to look like a year — 1900, 2000 — is stripped with the
# citations. The failure is SAFE in one direction only: the axis falls through
# to the fallback basis, whose reasoning line begins NOTHING IN THE CONFIG
# SUPPORTS A NUMBER HERE. A missing suggestion reads as ignorance; a wrong one
# would read as science.
def strip_citations(text: str) -> str:
    text = _CITATION.sub(" ", text or "")
    text = _VOLUME_PAGE.sub(" ", text)
    return _YEAR.sub(" ", text)


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def axes():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    for branch, group in cfg.items():
        if branch.startswith("_") or not isinstance(group, dict):
            continue
        for axis, spec in group.items():
            if isinstance(spec, dict):
                yield axis, spec


def numbers_in(text: str) -> list[float]:
    return [float(m.group(1)) for m in NUM.finditer(strip_citations(text))]


def propose(axis: str, spec: dict) -> dict:
    target = _num(spec.get("target_value"))
    direction = spec.get("direction")
    worst = _num(spec.get("reference_worst"))
    rationale = spec.get("rationale") or ""

    if target is None or direction not in ("lower_better", "higher_better",
                                           "stable_better"):
        return {"axis": axis, "suggested": None, "basis": "none",
                "reasoning": (f"no target_value or usable direction "
                              f"(target={target}, direction={direction!r}) — "
                              f"there is nothing to draw a line relative to"),
                "target": target, "direction": direction}

    # 1. the config's own record of how bad it has been
    if worst is not None:
        line = target + (worst - target) * 0.5
        return {"axis": axis, "suggested": round(line, 4), "basis": "reference_worst",
                "reasoning": (f"halfway between the target {target} and the "
                              f"config's own reference_worst {worst} — the line "
                              f"sits where half the known ground has been lost"),
                "target": target, "direction": direction,
                "reference_worst": worst}

    # 2. a number the rationale itself states
    candidates = [n for n in numbers_in(rationale)
                  if n != target and 0 < n < max(target * 10, 1000)]
    if candidates:
        if direction == "higher_better":
            usable = [n for n in candidates if n < target]
            pick = max(usable) if usable else None
        else:
            usable = [n for n in candidates if n > target]
            pick = min(usable) if usable else None
        if pick is not None:
            return {"axis": axis, "suggested": round(float(pick), 4),
                    "basis": "rationale",
                    "reasoning": (f"the axis's own rationale names {pick}: "
                                  f"{rationale[:90]!r} — the line is drawn at the "
                                  f"level the config already treats as the "
                                  f"present state"),
                    "target": target, "direction": direction}

    # 3. the weakest, and it says so
    if direction == "higher_better":
        line = target * (1 - FALLBACK_MARGIN)
    elif direction == "lower_better":
        line = target * (1 + FALLBACK_MARGIN)
    else:
        line = abs(target) * FALLBACK_MARGIN
    return {"axis": axis, "suggested": round(float(line), 4), "basis": "fallback",
            "reasoning": (f"NOTHING IN THE CONFIG SUPPORTS A NUMBER HERE. This is "
                          f"target {target} moved {int(FALLBACK_MARGIN * 100)}% in "
                          f"the bad direction — arithmetic, not evidence. Treat it "
                          f"as a prompt to choose, not as a recommendation"),
            "target": target, "direction": direction}


def build() -> dict:
    rows = [propose(a, s) for a, s in axes()]
    by_basis: dict[str, int] = {}
    for r in rows:
        by_basis[r["basis"]] = by_basis.get(r["basis"], 0) + 1
    return {
        "_what_this_is": (
            "SUGGESTED alarm thresholds, one per axis, derived only from what "
            "config/target_config.json already says. These are PROPOSALS: "
            "nothing here is written into the config, and core/alarm_bands.py "
            "never alarms on a null. The nulls stay null until a human signs "
            "each one."),
        "_basis_meanings": {
            "reference_worst": "the config's own record of how bad it has been",
            "rationale": "a number the axis's own rationale line states",
            "fallback": "arithmetic off the target — the weakest, and it says so",
            "none": "no target or direction; nothing to draw a line relative to",
        },
        "ts": datetime.now(timezone.utc).isoformat(),
        "axes": len(rows),
        "by_basis": by_basis,
        "proposals": rows,
    }


def main() -> int:
    data = build()
    print(f"{data['axes']} axes | basis: {data['by_basis']}\n")
    for r in data["proposals"]:
        s = "—" if r["suggested"] is None else r["suggested"]
        print(f"  {r['axis']:<34} {str(s):>12}  [{r['basis']}]")
        print(f"      {r['reasoning'][:110]}")
    if "--write" not in sys.argv:
        print("\nDRY RUN. Nothing written. Re-run with --write.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(BASE)} — these are proposals, not defaults")
    return 0


if __name__ == "__main__":
    sys.exit(main())
