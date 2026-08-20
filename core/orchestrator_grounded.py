#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/orchestrator_grounded.py — THE RANKING IS ARITHMETIC. THE PROSE IS A NOTE.

WHY THIS EXISTS
----------------
cognitive_orchestrator (step 12.7) decides which axes matter most this cycle.
Until now that judgement came from a model reading prose, which means the
priority order was an opinion that could not be checked, reproduced, or
disagreed with. A system whose composite is 0/173 measured cannot also have its
attention allocated by assertion.

So the order is computed here, from numbers, before any model is asked
anything:

    penalty = 1 - score          how far this axis is from its own target
    need    = weight x penalty   how much of the goal is being lost there

weight comes from target_config (what the goal says this axis is worth) and
score from goal_score_latest (how close it is). Neither is a model's view.

THE LLM MAY ANNOTATE. IT MAY NOT REORDER.
------------------------------------------
Step 12.7 reads this file as its INPUT and may attach prose to any row. The
ranking, the threat/opportunity split and the action vocabulary are fixed
before it runs. That is the whole point: a note that says "watch CLIMATE" next
to rank 7 is a comment; a model that moves CLIMATE to rank 1 is an unaudited
decision.

THREAT AND OPPORTUNITY ARE DISJOINT BY CONSTRUCTION
----------------------------------------------------
An axis cannot be both. THREAT = measured and far from target (the loss is
real and known). OPPORTUNITY = has weight but no measurement (the loss is
unknown, and knowing it is cheap). Anything else is WATCH. Built as set
operations, not by two independent thresholds that could overlap.

THE ACTION VOCABULARY IS CLOSED
--------------------------------
Actions are drawn from a fixed set, and every action that touches anything
outside this repo is REPORT_TO_HUMAN. Not because the others are dangerous,
but because "the model chose an action" and "the model chose an action from a
list a human wrote" are different kinds of system. Per
docs/OPENCLAW_INTEGRATION_DESIGN.md: the unknown requires approval.

    venv\\Scripts\\python.exe core/orchestrator_grounded.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
FEEDS = BASE / "openclaw_queue" / "axis_feeds_latest.json"
GOAL_SCORE = BASE / "snapshots" / "master" / "goal_score_latest.json"
OUT = BASE / "memory" / "orchestration_grounded_latest.json"

# Closed vocabulary. INTERNAL actions stay inside this repo. WORLD actions
# reach anything outside it, and there is exactly one of those.
INTERNAL_ACTIONS = ("RECOMPUTE", "WIRE_A_SOURCE", "WATCH", "NO_ACTION")
WORLD_ACTIONS = ("REPORT_TO_HUMAN",)
ACTIONS = INTERNAL_ACTIONS + WORLD_ACTIONS

THREAT, OPPORTUNITY, WATCH = "THREAT", "OPPORTUNITY", "WATCH"

# An axis is far from target when it has lost more than this share of its own
# scale. 0.5 is deliberately blunt: a threshold nobody can justify precisely
# should at least be one nobody can mistake for precision.
FAR_FROM_TARGET = 0.5


class RefusedToOrchestrate(RuntimeError):
    """No feeds, or no feed carries a number.

    Raised rather than returning an empty ranking: an orchestration built on
    nothing looks exactly like an orchestration built on everything being fine.
    """


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_feeds(path: pathlib.Path | None = None) -> list[dict]:
    try:
        return json.loads((path or FEEDS).read_text(encoding="utf-8"))["feeds"]
    except Exception:
        return []


def load_scores(path: pathlib.Path | None = None) -> dict[str, float]:
    """{axis: score} from goal_score_latest.metric_details."""
    try:
        goal = json.loads((path or GOAL_SCORE).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for detail in (goal.get("metric_details") or {}).values():
        axis, score = detail.get("axis"), detail.get("score")
        if axis and isinstance(score, (int, float)) and not isinstance(score, bool):
            out[axis] = float(score)
    return out


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def rank(feeds: list[dict], scores: dict[str, float]) -> list[dict]:
    """need = weight x penalty, descending. No model involved."""
    rows = []
    for feed in feeds:
        axis = feed.get("axis")
        weight = feed.get("weight")
        if not axis or not isinstance(weight, (int, float)) or isinstance(weight, bool):
            continue
        measured = feed.get("status") == "PRESENT"
        score = scores.get(axis)
        # An unmeasured axis is treated as maximum penalty, not as zero. Not
        # knowing is not the same as being fine, and the old scorer defaulting
        # to 0.5 is how 8 axes came to sit at exactly 60.0.
        penalty = 1.0 - float(score) if isinstance(score, (int, float)) else 1.0
        rows.append({
            "axis": axis,
            "weight": float(weight),
            "score": float(score) if isinstance(score, (int, float)) else None,
            "penalty": round(penalty, 4),
            "need": round(float(weight) * penalty, 4),
            "measured": measured,
            "value": feed.get("value"),
            "key": feed.get("key"),
            "unit": feed.get("unit"),
        })
    rows.sort(key=lambda r: (-r["need"], r["axis"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def classify(rows: list[dict]) -> dict[str, list[str]]:
    """THREAT / OPPORTUNITY / WATCH as disjoint sets, by construction."""
    all_axes = {r["axis"] for r in rows}
    threat = {r["axis"] for r in rows
              if r["measured"] and r["penalty"] > FAR_FROM_TARGET}
    # set difference, so an axis cannot land in both
    opportunity = {r["axis"] for r in rows if not r["measured"]} - threat
    watch = all_axes - threat - opportunity
    return {THREAT: sorted(threat), OPPORTUNITY: sorted(opportunity),
            WATCH: sorted(watch)}


def action_for(row: dict, bucket: str) -> str:
    """Closed vocabulary. Anything reaching outside this repo is one action."""
    if bucket == OPPORTUNITY:
        return "WIRE_A_SOURCE"
    if bucket == THREAT:
        # A threat is the one case a human is told about. Every world-facing
        # path collapses to this single action on purpose.
        return "REPORT_TO_HUMAN"
    return "WATCH" if row["need"] > 0 else "NO_ACTION"


def orchestrate(feeds_path=None, goal_score_path=None) -> dict:
    feeds = load_feeds(feeds_path)
    if not feeds:
        raise RefusedToOrchestrate(
            "no axis feeds — run step 12.68 (agents.axis.axis_feed) first. An "
            "orchestration built on nothing is indistinguishable from one built "
            "on everything being fine.")

    scores = load_scores(goal_score_path)
    rows = rank(feeds, scores)
    if not rows:
        raise RefusedToOrchestrate(
            f"{len(feeds)} feed(s) but none carries a usable weight — nothing "
            f"can be ranked, so nothing is asserted.")

    buckets = classify(rows)
    where = {axis: b for b, axes in buckets.items() for axis in axes}
    for r in rows:
        r["bucket"] = where.get(r["axis"], WATCH)
        r["action"] = action_for(r, r["bucket"])

    return {
        "ts": _now(),
        "_ranking_is_arithmetic": (
            "need = weight x penalty, penalty = 1 - score. Computed before any "
            "model is asked anything. Step 12.7 may ANNOTATE a row and may NOT "
            "reorder, re-bucket or invent an action."),
        "_action_vocabulary": {"internal": list(INTERNAL_ACTIONS),
                               "world": list(WORLD_ACTIONS)},
        "far_from_target": FAR_FROM_TARGET,
        "axes_ranked": len(rows),
        "measured": sum(1 for r in rows if r["measured"]),
        "buckets": {k: len(v) for k, v in buckets.items()},
        "sets": buckets,
        "ranking": rows,
    }


def write(result: dict, out: pathlib.Path | None = None) -> str:
    path = out or OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return str(path)


def run() -> dict:
    result = orchestrate()
    path = write(result)
    top = result["ranking"][:3]
    print(f"[ORCH_GROUNDED] {result['axes_ranked']} axes | "
          f"threat {result['buckets'][THREAT]} / "
          f"opportunity {result['buckets'][OPPORTUNITY]} / "
          f"watch {result['buckets'][WATCH]}")
    for r in top:
        print(f"[ORCH_GROUNDED]  #{r['rank']} {r['axis']:<34} "
              f"need={r['need']:<8} w={r['weight']} penalty={r['penalty']} "
              f"{r['bucket']}/{r['action']}")
    print(f"[ORCH_GROUNDED] -> {path}")
    return result


def _selftest() -> int:
    import tempfile
    print("core/orchestrator_grounded.py --selftest")
    ok = True

    try:
        orchestrate(feeds_path=pathlib.Path("does-not-exist.json"))
        print("  FAIL  empty feeds -> allowed")
        ok = False
    except RefusedToOrchestrate as exc:
        print(f"  OK    empty feeds -> refused ({str(exc)[:50]}...)")

    try:
        result = orchestrate()
        buckets = result["sets"]
        overlap = (set(buckets[THREAT]) & set(buckets[OPPORTUNITY])
                   | set(buckets[THREAT]) & set(buckets[WATCH])
                   | set(buckets[OPPORTUNITY]) & set(buckets[WATCH]))
        checks = [
            ("buckets are disjoint", not overlap),
            ("every bucket member is ranked",
             sum(len(v) for v in buckets.values()) == result["axes_ranked"]),
            ("every action is in the closed vocabulary",
             all(r["action"] in ACTIONS for r in result["ranking"])),
            ("only REPORT_TO_HUMAN reaches the world",
             all(r["action"] in INTERNAL_ACTIONS
                 for r in result["ranking"] if r["bucket"] != THREAT)),
            ("ranking is sorted by need",
             [r["need"] for r in result["ranking"]]
             == sorted((r["need"] for r in result["ranking"]), reverse=True)),
        ]
        for name, passed in checks:
            print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
            ok = ok and passed
        print(f"  live: {result['axes_ranked']} axes, "
              f"threat={result['buckets'][THREAT]} "
              f"opportunity={result['buckets'][OPPORTUNITY]} "
              f"watch={result['buckets'][WATCH]}")
        for r in result["ranking"][:3]:
            print(f"        #{r['rank']} {r['axis']} need={r['need']} {r['bucket']}")
        with tempfile.TemporaryDirectory() as tmp:
            write(result, pathlib.Path(tmp) / "o.json")
    except RefusedToOrchestrate as exc:
        print(f"  live orchestration refused: {exc}")
        ok = False

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else (run() and 0))
