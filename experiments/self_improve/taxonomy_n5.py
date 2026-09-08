#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/self_improve/taxonomy_n5.py — DOES THE TAXONOMY HOLD, LIVE, N TIMES?

The measurement the domain/categories split was built to be judged by, run
against the REAL local model on the REAL journal problem. No mocks anywhere.

WHY THE BAR IS NOT "IDENTICAL ANSWERS"
---------------------------------------
The local model runs at temperature 0.4, hardcoded in production
(core.groq_backend._call_local_as), so identical answers were never the standard.
The standard is that the answer lands in the right PLACE every time:

    * domain == "internal" on every run — a JSON parser is a fault in the
      instrument, not a gap in how the instrument measures the world;
    * every category from config/internal_axes.json;
    * NEVER a world axis. The failure this replaced produced four of them for
      this exact problem — TECHNOLOGY_AI, TECHNOLOGY_INFRA, DEEP_TIME_RISKS,
      GOAL_PROGRESS — each real, each a guess.

TWO LAYERS, REPORTED SEPARATELY
--------------------------------
    the CLASSIFICATION   domain + categories, read off the model's own answer
    the WHOLE SPEC       what require() does with it, refusal codes included

Conflating them would let a refusal on an unrelated field read as the taxonomy
failing, or the reverse. On 8 Sep 2026 that distinction was the whole result:
5/5 classified correctly, 5/5 specs refused — on the metric and the path.

READ-ONLY. It writes nothing into the repo; --json writes a file only where you
point it.

    venv\\Scripts\\python.exe experiments/self_improve/taxonomy_n5.py -n 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.self_improve import requirer as R      # noqa: E402

JOURNAL_DAY = "2026-09-06"


def journal_problem(day: str = JOURNAL_DAY) -> dict:
    """The problem the brief names, built from the record rather than retyped."""
    doc = json.loads((REPO / "memory" / "development_journal.json")
                     .read_text(encoding="utf-8"))
    rec = doc[day]["problem_assessment"]
    return {
        "problem": (f"ESCALATION: LLM returns invalid JSON 3 times in a row "
                    f"(journal {day}: {rec['assessment']})"),
        "root_cause": "the model's reply is not parsed as JSON and there is no retry",
        "component": "self_observer",
        # Carried because the record carries it. It is NOT used as an allowlist:
        # this list holds 21 of the 24 world axes, and a near-universal list is
        # not evidence of relevance.
        "critical_axes": rec.get("critical_axes") or [],
    }


def one_run(problem: dict) -> dict:
    """One ask, both layers. consensus=1 on purpose: N runs should be N
    independent samples of what the model says, not one report of a vote."""
    seen = {}

    def _spy(prompt, max_tokens=700):
        raw = R._local_brain(prompt, max_tokens)
        seen["raw"] = raw
        return raw

    row = {}
    try:
        spec = R.require(problem, brain=_spy, consensus=1)
        row.update(spec_verdict="ACCEPTED", domain=spec.get("domain"),
                   categories=spec.get("categories"),
                   paths=spec.get("allowed_paths"),
                   metric=spec.get("success_metric"))
    except R.SpecInvalid as exc:
        row.update(spec_verdict="REFUSED",
                   refused=getattr(type(exc), "code", "SPEC_INVALID"),
                   why=str(exc)[:200])
    except Exception as exc:                                     # noqa: BLE001
        row.update(spec_verdict="ERROR", error=f"{type(exc).__name__}: {exc}")

    raw = seen.get("raw") or ""
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        doc = json.loads(m.group(0)) if m else {}
    except Exception:                                            # noqa: BLE001
        doc = {}
    row["said_domain"] = doc.get("domain")
    row["said_categories"] = doc.get("categories")
    row["said_fields"] = sorted(doc)
    return row


def summarise(rows: list) -> dict:
    world = R.real_axes()
    internal = set(R.internal_axes())
    domains = [r.get("said_domain") for r in rows]
    cats = [c for r in rows for c in (r.get("said_categories") or [])]
    return {
        "runs": len(rows),
        "domain_per_run": domains,
        "internal_every_time": all(d == "internal" for d in domains),
        "categories_seen": sorted(set(cats)),
        "all_from_the_internal_set": set(cats) <= internal,
        "world_axes_among_them": sorted(set(cats) & world),
        "plausible_present": sorted(set(cats) & {"reliability", "correctness"}),
        "spec_verdicts": [r.get("spec_verdict") for r in rows],
        "refusal_codes": [r.get("refused") for r in rows if r.get("refused")],
        "runs_missing_allowed_paths": [
            i + 1 for i, r in enumerate(rows)
            if "allowed_paths" not in (r.get("said_fields") or [])],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-n", "--runs", type=int, default=5)
    ap.add_argument("--day", default=JOURNAL_DAY)
    ap.add_argument("--json", help="write the rows to this path")
    args = ap.parse_args(argv)

    problem = journal_problem(args.day)
    print(f"PROBLEM ({args.day}): {problem['problem'][:110]}")
    print()

    rows = []
    for i in range(1, args.runs + 1):
        row = one_run(problem)
        row["run"] = i
        rows.append(row)
        print(f"  run {i}: domain={row.get('said_domain')!r} "
              f"categories={row.get('said_categories')} "
              f"spec={row.get('spec_verdict')}"
              + (f" [{row.get('refused')}]" if row.get("refused") else ""),
              flush=True)

    s = summarise(rows)
    print()
    for k, v in s.items():
        print(f"  {k:<28} {v}")

    # THE BAR, stated as a check rather than left to the reader.
    passed = (s["internal_every_time"] and s["all_from_the_internal_set"]
              and not s["world_axes_among_them"] and s["plausible_present"])
    print()
    print(f"  CLASSIFICATION BAR: {'MET' if passed else 'NOT MET'}")
    print("  (the bar is where the answer lands, not whether the answers are "
          "identical; the whole-spec verdicts above are a separate question)")

    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows, "summary": s}, ensure_ascii=False,
                       indent=2), encoding="utf-8")
        print(f"  saved -> {args.json}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
