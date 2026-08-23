#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/alarm_bands.py — A RED LINE RINGS THE MOMENT IT IS CROSSED.

WHAT THIS IS
-------------
One number per axis: the value past which a person should be told at once, not
in the morning digest. Crossing it sends immediately and bypasses quiet hours,
because a red line that waits until 08:00 is a report, not an alarm.

    lower_better    alarms when the value goes ABOVE the line
    higher_better   alarms when the value goes BELOW it
    stable_better   alarms on either side of the target by the band's width

Under Emil's polarity ruling of 21 August the direction is unambiguous on all
25 axes, so this needs no per-axis special-casing.

EVERY THRESHOLD STARTS null AND STAYS null UNTIL A HUMAN SIGNS IT
------------------------------------------------------------------
A null threshold never alarms. That is not a gap to be filled by a default: a
red line nobody chose is a number the system invented and then measured itself
against. The count of unset bands is reported as AWAITING_HUMAN_VALUES so the
emptiness stays a standing question rather than a quiet zero.

scripts/propose_alarm_thresholds.py derives a SUGGESTED value per axis from
target_config's own rationale and reference_worst, and files them as proposals.
Suggestions are proposals, never defaults.

A MISSING DIRECTION IS AN ERROR, NOT A SKIP
--------------------------------------------
If an axis has a threshold but no usable direction, the sweep cannot know which
side of the line is bad. It reports CONFIG_ERROR. Skipping would mean a red
line that is set, looks armed, and silently checks nothing.

    venv\\Scripts\\python.exe core/alarm_bands.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "target_config.json"
GOAL_SCORE = BASE / "snapshots" / "master" / "goal_score_latest.json"
LOG = BASE / "memory" / "alarm_bands_latest.json"

OK, ALARM, UNSET, NO_VALUE, CONFIG_ERROR = (
    "OK", "ALARM", "UNSET", "NO_VALUE", "CONFIG_ERROR")

DIRECTIONS = ("lower_better", "higher_better", "stable_better")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def axes(config_path=None) -> dict[str, dict]:
    try:
        cfg = json.loads((config_path or CONFIG).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for branch, group in cfg.items():
        if branch.startswith("_") or not isinstance(group, dict):
            continue
        for axis, spec in group.items():
            if isinstance(spec, dict):
                out[axis] = spec
    return out


def values(goal_path=None) -> dict[str, float]:
    try:
        goal = json.loads((goal_path or GOAL_SCORE).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for detail in (goal.get("metric_details") or {}).values():
        axis, current = detail.get("axis"), _num(detail.get("current"))
        if axis and current is not None:
            out[axis] = current
    return out


def crossed(value: float, threshold: float, direction: str,
            target: float | None = None) -> bool:
    """Is the red line crossed? Direction decides which side is bad."""
    if direction == "lower_better":
        return value > threshold
    if direction == "higher_better":
        return value < threshold
    if direction == "stable_better":
        base = target if target is not None else threshold
        return abs(value - base) > abs(threshold)
    raise ValueError(f"unusable direction {direction!r}")


def sweep(config_path=None, goal_path=None) -> dict:
    """One row per axis. Never raises."""
    spec_by_axis = axes(config_path)
    value_by_axis = values(goal_path)

    rows = []
    for axis in sorted(spec_by_axis):
        spec = spec_by_axis[axis]
        threshold = _num(spec.get("alarm_threshold"))
        value = value_by_axis.get(axis)
        direction = spec.get("direction")

        if threshold is None:
            rows.append({"axis": axis, "verdict": UNSET, "value": value,
                         "threshold": None,
                         "why": "no red line has been set for this axis"})
            continue

        if direction not in DIRECTIONS:
            # NOT a skip. A threshold that is set but uncheckable is worse than
            # no threshold: it looks armed.
            rows.append({
                "axis": axis, "verdict": CONFIG_ERROR, "value": value,
                "threshold": threshold, "direction": direction,
                "why": (f"alarm_threshold={threshold} is set but direction is "
                        f"{direction!r} — the sweep cannot tell which side of "
                        f"the line is bad, so the band is armed and checks "
                        f"nothing"),
            })
            continue

        if value is None:
            rows.append({"axis": axis, "verdict": NO_VALUE, "value": None,
                         "threshold": threshold, "direction": direction,
                         "why": "a red line is set but nothing measured this axis"})
            continue

        try:
            is_over = crossed(value, threshold, direction,
                              _num(spec.get("target_value")))
        except ValueError as exc:
            rows.append({"axis": axis, "verdict": CONFIG_ERROR, "value": value,
                         "threshold": threshold, "direction": direction,
                         "why": str(exc)})
            continue

        rows.append({
            "axis": axis, "verdict": ALARM if is_over else OK,
            "value": value, "threshold": threshold, "direction": direction,
            "unit": spec.get("unit"),
            "why": (f"{value} {spec.get('unit') or ''} against a red line of "
                    f"{threshold} ({direction})") if is_over else None,
        })

    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (OK, ALARM, UNSET, NO_VALUE, CONFIG_ERROR)}
    return {
        "ts": _now(),
        "axes": len(rows),
        "counts": counts,
        "AWAITING_HUMAN_VALUES": counts[UNSET],
        "alarms": [r for r in rows if r["verdict"] == ALARM],
        "config_errors": [r for r in rows if r["verdict"] == CONFIG_ERROR],
        "rows": rows,
    }


def send(result: dict, sender=None) -> int:
    """One message per alarm, immediately, past quiet hours."""
    sent = 0
    for row in result["alarms"]:
        text = (f"🚨 CORTEX++ · ЧЕРВЕНА ЛИНИЯ · {row['axis']}\n"
                f"{row['why']}\n"
                f"Това не е дайджест — прагът е пресечен сега.")
        try:
            if sender is not None:
                sender(row["axis"], text)
            else:
                import supervisor
                supervisor.alarm_human(
                    f"червена линия {row['axis']}", text,
                    dedup_key=f"alarm:{row['axis']}:{row['value']}",
                    trigger="MANUAL",      # MANUAL bypasses the quiet window
                    # ALARM, and one of the three things that earn it: a
                    # threshold the human set has been crossed NOW.
                    level=supervisor.ALARM)
            sent += 1
        except Exception:
            pass
    return sent


def for_cycle_report() -> dict:
    """The counter the report carries: how many red lines nobody has drawn."""
    try:
        result = sweep()
        return {"awaiting_human_values": result["AWAITING_HUMAN_VALUES"],
                "axes": result["axes"], "alarms": len(result["alarms"]),
                "config_errors": len(result["config_errors"])}
    except Exception:
        return {}


def run() -> dict:
    result = sweep()
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    except Exception:
        pass
    sent = send(result)
    c = result["counts"]
    print(f"[ALARM] {result['axes']} axes | ALARM {c[ALARM]} ({sent} sent) | "
          f"OK {c[OK]} | AWAITING_HUMAN_VALUES {c[UNSET]} | "
          f"no value {c[NO_VALUE]} | CONFIG_ERROR {c[CONFIG_ERROR]}")
    for row in result["alarms"]:
        print(f"[ALARM] CROSSED {row['axis']}: {row['why']}")
    for row in result["config_errors"]:
        print(f"[ALARM] CONFIG_ERROR {row['axis']}: {row['why']}")
    return result


def _selftest() -> int:
    print("core/alarm_bands.py --selftest")
    result = sweep()
    ok = True
    checks = [
        ("every axis is swept", result["axes"] == 25),
        ("nothing alarms while every band is null", not result["alarms"]),
        (f"AWAITING_HUMAN_VALUES is 25 ({result['AWAITING_HUMAN_VALUES']})",
         result["AWAITING_HUMAN_VALUES"] == 25),
        ("no config errors", not result["config_errors"]),
        ("lower_better alarms above", crossed(500, 350, "lower_better")),
        ("lower_better is quiet below", not crossed(300, 350, "lower_better")),
        ("higher_better alarms below", crossed(20, 50, "higher_better")),
        ("higher_better is quiet above", not crossed(80, 50, "higher_better")),
    ]
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  counts: {result['counts']}")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else (run() and 0))
