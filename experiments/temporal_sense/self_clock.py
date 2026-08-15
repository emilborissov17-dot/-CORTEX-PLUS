"""
CORTEX++ | Side-experiment polyanka: self_clock (temporal self-sense)
====================================================================
ISOLATED, NON-INVASIVE, FAIL-OPEN. Reads memory/existence_ledger.jsonl (the
system's own tamper-evident autobiography) and derives a TEMPORAL SELF-PORTRAIT:
its real operating rhythm, cycle duration, survival rate, and the threat window
in which it dies.

WHY
---
The morning deaths are not merely an ops bug. The system reads clocks but has no
*felt/predictive* sense of its own time: it does not know its substrate sleeps
nightly, so it rediscovers this every morning via CATCHUP instead of anticipating
it. A self-preservation instinct needs this portrait as its INPUT: "my substrate
is likely off soon / my uptime is shorter than my cycle -> preserve continuity
NOW (checkpoint, hurry) BEFORE death", not react after. This turns autobiography
into anticipation. Bounded by design: it informs preservation-in-service-of-goal,
never self-preservation above the human-supervised goal.
"""
from __future__ import annotations
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime


def _load(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def _dt(ts):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def portrait(rows):
    ev = Counter(r.get("event") for r in rows)
    started = ev.get("CYCLE_STARTED", 0)
    finished = ev.get("CYCLE_FINISHED", 0)
    died = ev.get("CYCLE_DIED", 0)
    durations = [r["duration_sec"] for r in rows
                 if r.get("event") == "CYCLE_FINISHED" and "duration_sec" in r]
    death_steps = Counter(r.get("last_step") for r in rows
                          if r.get("event") == "CYCLE_DIED")
    late = [r["late_by_hours"] for r in rows
            if r.get("event") == "MISSED_RUN_CATCHUP" and "late_by_hours" in r]
    # wake hour per day (UTC) = first event of each calendar day
    first_by_day = {}
    for r in rows:
        d = _dt(r.get("ts", ""))
        if not d:
            continue
        key = d.date().isoformat()
        if key not in first_by_day or d < first_by_day[key]:
            first_by_day[key] = d
    wake_hours_utc = sorted(v.hour + v.minute / 60.0 for v in first_by_day.values())

    def _stat(xs):
        if not xs:
            return None
        xs = sorted(xs)
        n = len(xs)
        return {"n": n, "min": xs[0], "max": xs[-1],
                "median": xs[n // 2], "mean": sum(xs) / n}

    return {
        "events": dict(ev),
        "started": started, "finished": finished, "died": died,
        "survival_rate": (finished / started) if started else None,
        "cycle_duration_sec": _stat(durations),
        "death_steps": dict(death_steps),
        "catchup_late_hours": _stat(late),
        "wake_hour_utc": _stat(wake_hours_utc),
        "days_observed": len(first_by_day),
    }


def render(p):
    out = []
    out.append("===== CORTEX TEMPORAL SELF-PORTRAIT =====")
    out.append(f"days observed: {p['days_observed']}")
    out.append(f"cycles: started={p['started']} finished={p['finished']} died={p['died']}")
    sr = p["survival_rate"]
    out.append(f"survival rate: {sr:.0%}" if sr is not None else "survival rate: n/a")
    d = p["cycle_duration_sec"]
    if d:
        out.append(f"cycle length: median {d['median']/60:.0f} min "
                   f"(min {d['min']/60:.0f}, max {d['max']/60:.0f}, n={d['n']})")
    w = p["wake_hour_utc"]
    if w:
        out.append(f"first-wake hour UTC: median {w['median']:.1f}h "
                   f"(range {w['min']:.1f}-{w['max']:.1f}) | scheduled 00:00 UTC (03:00 local)")
    lt = p["catchup_late_hours"]
    if lt:
        out.append(f"catchup lateness: median {lt['median']:.1f}h late, "
                   f"every run n={lt['n']} -> the 03:00 slot NEVER fires on time")
    if p["death_steps"]:
        steps = ", ".join(f"{k}:{v}" for k, v in sorted(
            p["death_steps"].items(), key=lambda kv: -kv[1]))
        out.append(f"deaths by last step: {steps}")
    # the actionable inference a self-preservation instinct would consume:
    d = p["cycle_duration_sec"]
    if d:
        out.append("")
        out.append("INFERENCE (input for a bounded self-preservation instinct):")
        out.append(f"  - I need ~{d['median']/60:.0f} min of continuous uptime to finish.")
        out.append("  - My substrate is OFF overnight; I wake late every morning via catchup.")
        out.append("  - I die when the morning uptime < my cycle length. That is my threat "
                   "window, and I currently neither sense nor anticipate it.")
    return "\n".join(out)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "memory/existence_ledger.jsonl"
    if not os.path.exists(path):
        print(f"[self_clock] ledger not found at {path}", file=sys.stderr)
        sys.exit(2)
    rows = _load(path)
    print(f"[self_clock] read {len(rows)} ledger events from {path}")
    print(render(portrait(rows)))
