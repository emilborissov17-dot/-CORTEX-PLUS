#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/axis/axis_feed.py — ONE AGENT PER AXIS. IT MAY EMIT A NUMBER, NOTHING ELSE.

THE DMZ CONTRACT
-----------------
docs/OPENCLAW_INTEGRATION_DESIGN.md draws a line: what crosses out of CORTEX is
constrained by TYPE, not by good intentions. "Всяко действие, което не е изрично
в Ниво 1 или Ниво 2 allowlist-а, автоматично получава Ниво 3. Неизвестното =
изисква одобрение."

Applied here: an axis feed carries a NUMBER bound to (axis, key). Not a
sentence, not a level word, not a model's summary. Prose is where a language
model's opinion smuggles itself across a boundary as if it were a measurement —
and this repo has 0 of 173 weight backed by measurement while every axis reports
a confident level, which is exactly that failure already in production.

So the contract is enforced by rejection, not by convention:

    value is int/float and finite   -> Feed
    anything else                   -> RejectedFeed, recorded, not published

An axis with no number is not silently dropped either. It emits an ABSENT row
naming why. A missing axis and an axis nobody looked at must not look alike.

WHERE THE NUMBERS COME FROM
----------------------------
snapshots/master/goal_score_latest.json -> metric_details. That is the only
place in this repo where an axis already carries a measured value with its unit,
target, direction and weight, produced by goal_score_calculator and not by a
model. Reading anything else would mean inventing a second source of truth.

    venv\\Scripts\\python.exe -m agents.axis.axis_feed --selftest
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

BASE = pathlib.Path(__file__).resolve().parents[2]
TARGET_CONFIG = BASE / "config" / "target_config.json"
GOAL_SCORE = BASE / "snapshots" / "master" / "goal_score_latest.json"
QUEUE_DIR = BASE / "openclaw_queue"
FEED_LOG = QUEUE_DIR / "axis_feeds.jsonl"
FEED_LATEST = QUEUE_DIR / "axis_feeds_latest.json"

PRESENT, ABSENT = "PRESENT", "ABSENT"


class RejectedFeed(ValueError):
    """An axis agent tried to emit something that is not a number.

    Raised, not swallowed: a feed that cannot cross the DMZ must fail loudly at
    the agent that produced it, so the offending axis is named rather than the
    whole batch silently shrinking by one.
    """


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def axes_from_config(path: pathlib.Path | None = None) -> dict[str, dict]:
    """{axis: config} for every axis in target_config, branch structure ignored."""
    cfg = json.loads((path or TARGET_CONFIG).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for branch, axes in cfg.items():
        if branch.startswith("_") or not isinstance(axes, dict):
            continue
        for axis, spec in axes.items():
            if isinstance(spec, dict):
                out[axis] = {**spec, "branch": branch}
    return out


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------

def check_number(axis: str, key: str, value) -> float:
    """The whole DMZ rule, in one place. Returns the number or raises."""
    if isinstance(value, bool):
        raise RejectedFeed(
            f"{axis}.{key}: bool is not a measurement (got {value!r})")
    if not isinstance(value, (int, float)):
        raise RejectedFeed(
            f"{axis}.{key}: value must be a number, got {type(value).__name__} "
            f"{value!r}. Prose does not cross the DMZ — see the module docstring.")
    if not math.isfinite(float(value)):
        raise RejectedFeed(f"{axis}.{key}: {value!r} is not finite")
    return float(value)


def make_feed(axis: str, key: str, value, *, unit=None, source=None,
              measured=None, weight=None) -> dict:
    """A PRESENT row. Raises RejectedFeed if the value is not a number."""
    return {
        "ts": _now(),
        "axis": axis,
        "key": key,
        "value": check_number(axis, key, value),
        "unit": unit,
        "source": source,
        "measured": bool(measured) if measured is not None else None,
        "weight": weight,
        "status": PRESENT,
    }


def make_absent(axis: str, key: str | None, why: str, weight=None) -> dict:
    """An axis with no number. Named, not dropped."""
    return {
        "ts": _now(),
        "axis": axis,
        "key": key,
        "value": None,
        "unit": None,
        "source": None,
        "measured": False,
        "weight": weight,
        "status": ABSENT,
        "why": why,
    }


# ---------------------------------------------------------------------------
# One agent per axis
# ---------------------------------------------------------------------------

def _details_by_axis(goal_score: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for key, detail in (goal_score.get("metric_details") or {}).items():
        axis = detail.get("axis")
        if axis:
            out[axis] = {**detail, "key": key}
    return out


def axis_agent(axis: str, spec: dict, details: dict[str, dict]) -> dict:
    """THE AGENT. One axis in, one row out. It reads; it does not reason.

    Deliberately not an LLM call. An axis feed is a measurement crossing a
    boundary, and the thing a model is worst at is knowing whether it measured
    something or remembered it.
    """
    weight = spec.get("weight")
    detail = details.get(axis)

    if detail is None:
        return make_absent(axis, spec.get("primary_metric"),
                           "no metric_details row in goal_score_latest.json",
                           weight)
    if detail.get("current") is None:
        return make_absent(axis, detail.get("key"),
                           "metric exists but carries no current value", weight)

    return make_feed(
        axis, detail.get("key") or spec.get("primary_metric") or "unknown",
        detail["current"],
        unit=detail.get("unit"), source="goal_score_latest.metric_details",
        measured=detail.get("measured"), weight=weight)


def collect(config_path=None, goal_score_path=None) -> dict:
    """Run every axis agent. Rejections are recorded, never published."""
    axes = axes_from_config(config_path)
    try:
        goal = json.loads((goal_score_path or GOAL_SCORE).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        goal = {}
        goal_error = f"{type(exc).__name__}: {exc}"
    else:
        goal_error = None
    details = _details_by_axis(goal)

    feeds, rejected = [], []
    for axis in sorted(axes):
        try:
            feeds.append(axis_agent(axis, axes[axis], details))
        except RejectedFeed as exc:
            rejected.append({"ts": _now(), "axis": axis, "reason": str(exc)})

    present = [f for f in feeds if f["status"] == PRESENT]
    absent = [f for f in feeds if f["status"] == ABSENT]
    return {
        "ts": _now(),
        "source": str(goal_score_path or GOAL_SCORE),
        "source_error": goal_error,
        "axes_in_config": len(axes),
        "present": len(present),
        "absent": len(absent),
        "rejected": rejected,
        "feeds": feeds,
    }


def write(batch: dict, queue_dir: pathlib.Path | None = None) -> dict:
    d = queue_dir or QUEUE_DIR
    d.mkdir(parents=True, exist_ok=True)
    log = d / FEED_LOG.name
    latest = d / FEED_LATEST.name
    with open(log, "a", encoding="utf-8") as fh:
        for row in batch["feeds"]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        for row in batch["rejected"]:
            fh.write(json.dumps({**row, "status": "REJECTED"},
                                ensure_ascii=False) + "\n")
    latest.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return {"log": str(log), "latest": str(latest)}


def run() -> dict:
    """Step 12.68 entry point."""
    batch = collect()
    paths = write(batch)
    print(f"[AXIS_FEED] {batch['present']} present / {batch['absent']} absent / "
          f"{len(batch['rejected'])} rejected of {batch['axes_in_config']} axes")
    if batch["rejected"]:
        for r in batch["rejected"]:
            print(f"[AXIS_FEED] REJECTED {r['axis']}: {r['reason']}")
    print(f"[AXIS_FEED] -> {paths['latest']}")
    return batch


def _selftest() -> int:
    import tempfile
    print("agents/axis/axis_feed.py --selftest")
    ok = True

    checks = []
    for bad in ("HIGH", "427.59 ppm", None, [1], {"v": 1}, True, float("nan")):
        try:
            check_number("AX", "k", bad)
            checks.append((f"rejects {bad!r}", False))
        except RejectedFeed:
            checks.append((f"rejects {bad!r}", True))
    for good in (0, 1, -3, 427.59, 0.8185):
        checks.append((f"accepts {good!r}", check_number("AX", "k", good) == float(good)))

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed

    batch = collect()
    print(f"  live: {batch['present']} present / {batch['absent']} absent / "
          f"{len(batch['rejected'])} rejected of {batch['axes_in_config']}")
    live_ok = batch["axes_in_config"] > 0 and (batch["present"] + batch["absent"]
                                               == batch["axes_in_config"])
    print(f"  {'OK  ' if live_ok else 'FAIL'}  every axis produced exactly one row")
    ok = ok and live_ok

    with tempfile.TemporaryDirectory() as tmp:
        paths = write(batch, pathlib.Path(tmp))
        wrote = pathlib.Path(paths["latest"]).exists()
        print(f"  {'OK  ' if wrote else 'FAIL'}  writes to a redirectable queue dir")
        ok = ok and wrote

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else (run() and 0))
