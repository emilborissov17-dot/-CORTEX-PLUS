#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/compare_mover_rules.py — MY CONSTANT vs THIS MACHINE'S OWN HISTORY.

ONE MOMENT, TWO RULES, SIDE BY SIDE.

  FIXED     what cockpit/pulse.py has always done: rank by relative movement
            against the previous reading, judged by a flat 15%. An operator's
            number. It knows nothing about this machine.
  HISTORY   cockpit/norms.py: rank by |value - median| / (1.4826 x MAD), where
            the median and the MAD come from THIS sensor's own recorded
            samples. A sensor with fewer than MIN_SAMPLES falls back to the
            fixed rule and the row says so.

The moment is the newest row of memory/somatic_history.jsonl, and the "previous
reading" the fixed rule needs is the row before it. Both rules are therefore
looking at exactly the same instant, which is the only way the comparison means
anything.

    venv/Scripts/python.exe scripts/compare_mover_rules.py
    venv/Scripts/python.exe scripts/compare_mover_rules.py --path <history.jsonl>
"""
from __future__ import annotations

import argparse
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import norms as nm  # noqa: E402


def fixed_rank(newest: dict, previous: dict, top: int = 3) -> list:
    """The old rule, on its own terms: relative move against the last reading."""
    rows = []
    for key, value in newest.items():
        prev = previous.get(key)
        if not isinstance(prev, (int, float)):
            continue
        if prev == 0:
            move = None if value == 0 else 1.0
        else:
            move = abs(float(value) - float(prev)) / abs(float(prev))
        rows.append({"key": key, "value": value, "move": move,
                     "over": move is not None and move > nm.FIXED_MOVE_THRESHOLD})
    rows.sort(key=lambda r: (r["move"] is None, -(r["move"] or 0.0)))
    return rows[:top]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(nm.HISTORY))
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args(argv)

    path = pathlib.Path(args.path)
    hist = nm.history(path)
    newest, previous = nm.last_two(path)
    if not newest:
        print("no recorded probe at {} — /api/somatic has not run since "
              "recording was wired".format(path))
        return 1

    total = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    with_norm = sum(1 for v in hist.values() if len(v) >= nm.MIN_SAMPLES)
    print("scripts/compare_mover_rules.py")
    print("  history      {}".format(path))
    print("  {} probe(s) recorded; {} of {} sensors have >= {} samples"
          .format(total, with_norm, len(hist), nm.MIN_SAMPLES))
    print()

    print("  FIXED — my constant: relative move vs the previous reading, "
          "flat {:.0%}".format(nm.FIXED_MOVE_THRESHOLD))
    fixed = fixed_rank(newest, previous, args.top)
    for i, r in enumerate(fixed, 1):
        print("    {}. {:<22} {:<12} moved {:>8}   {}".format(
            i, r["key"], r["value"],
            "?" if r["move"] is None else "{:.0%}".format(r["move"]),
            "over the threshold" if r["over"] else "under the threshold"))

    print()
    print("  HISTORY — this machine's own norm: |value - median| / spread")
    readings = [{"key": k, "value": v, "unit": ""} for k, v in newest.items()]
    ranked = nm.rank(readings, hist, previous, top=args.top)
    for i, r in enumerate(ranked, 1):
        print("    {}. {:<22} {:<12} {:>6} spreads  [{}]  typical={} n={}".format(
            i, r["key"], r["value"], r["score"], r["rule"], r["typical"],
            r["samples"]))

    fixed_keys = [r["key"] for r in fixed]
    hist_keys = [r["key"] for r in ranked]
    print()
    print("  WHERE THEY DIFFER")
    if fixed_keys == hist_keys:
        print("    the two rules agree on all {} at this moment — which happens, "
              "and is not evidence that the rules are the same".format(args.top))
    only_fixed = [k for k in fixed_keys if k not in hist_keys]
    only_hist = [k for k in hist_keys if k not in fixed_keys]
    for k in only_fixed:
        vals = hist.get(k) or []
        n = nm.norm_for(vals)
        dev = nm.deviation(newest.get(k), n)
        print("    loud under FIXED, quiet under HISTORY: {:<20} "
              "{} spread(s) from a typical {} over {} samples".format(
                  k, "?" if dev is None else round(dev, 2), n["typical"], n["n"]))
        print("      -> it moves this much all the time on this machine")
    for k in only_hist:
        prev = previous.get(k)
        move = (None if not isinstance(prev, (int, float)) or prev == 0
                else abs(newest[k] - prev) / abs(prev))
        print("    quiet under FIXED, loud under HISTORY: {:<20} "
              "moved only {}".format(
                  k, "?" if move is None else "{:.1%}".format(move)))
        print("      -> a small move, but not a move this sensor makes")
    if not only_fixed and not only_hist and fixed_keys != hist_keys:
        print("    the same {} sensors, in a different order: FIXED {} vs "
              "HISTORY {}".format(args.top, fixed_keys, hist_keys))

    print()
    print("  the rules are not one scale, so every ranked row names the one "
          "that judged it:")
    for rule, meaning in nm.RULE_MEANING.items():
        print("    {:<8} {}".format(rule, meaning))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
