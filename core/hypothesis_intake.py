#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/hypothesis_intake.py — PREDICTIONS THAT CAN FAIL, EVERY NIGHT (3 Sep 2026).

C5 + C11. Until tonight this system produced exactly two hypotheses, both in June,
and graded neither. A system that never states what it expects cannot be wrong, and
something that cannot be wrong is not measuring anything. This is the generator: it
pre-registers, every night, a falsifiable claim per MEASURED axis, and it does so
BEFORE the outcome is known.

WHAT MAY BE PREDICTED. Only axes that core.measurement_honesty classifies as
MEASURED this cycle — the axis was resolved by a named external observation. An
ASSERTED axis is an opinion and a prediction about it would grade an opinion against
itself; an ABSENT axis has no number at all. This is the same gate K1 uses, read
from the same place, so "what may be predicted" and "what counts as measured" can
never drift apart.

C11, THE INTERVAL. Every hypothesis carries lo/hi, not just a point. A point
prediction can always be called "close"; an interval either contains the outcome or
it does not. The width also carries information the point does not: a method that is
right but only because it predicted everything is visible as an interval nobody
could miss, and core/belief_revision.py divides by that width for exactly that
reason (surprise = |error| / interval width).

THE METHODS, and why more than one. persistence (tomorrow = today), trend (linear
over the axis's recent readings), mean_reversion (pull toward the window mean) and
anchored (the consolidation module's slow-drift fit, when it has one). Each night
every eligible axis gets ONE hypothesis, from the method that belief_state currently
weights highest for that axis. That is what makes belief revision have teeth: a
method that keeps missing loses the axis to a method that does not, and the change
is visible the next night in what gets predicted.

TWO GUARDS, both structural:
  * GENERATION IS NOT RESOLUTION. This module writes pending.json and NEVER
    resolved.json; core/hypothesis_resolution.py writes neither — it calls the
    evaluator, which owns both. They are separate steps (20.06 and 20.05) and the
    test asserts each stays out of the other's file.
  * NOTHING IS PREDICTED TWICE. One hypothesis per (axis, method, due date). A
    generator run twice in a night must not double the queue.

  venv\\Scripts\\python.exe -m core.hypothesis_intake --selftest
  venv\\Scripts\\python.exe -m core.hypothesis_intake --dry-run
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PENDING = REPO / "cortex_memory" / "hypotheses" / "pending.json"
CONSOLIDATION_QUEUE = REPO / "memory" / "consolidation_queue.json"
LATEST = REPO / "memory" / "hypothesis_intake_latest.json"
ARCHIVE = REPO / "cortex_memory" / "archive"

DEFAULT_HORIZON = 7
METHODS = ("persistence", "trend", "mean_reversion", "anchored")
MIN_HISTORY = 3


# ── what may be predicted ─────────────────────────────────────────────────────

def measured_axes() -> dict:
    """axis -> observed_value, for axes MEASURED this cycle. Same gate as K1."""
    try:
        import contextlib
        import io as _io
        from core.measurement_honesty import run as _mh
        # measurement_honesty prints its full human report on every call. Step 20.1
        # already puts that in the cycle log; a second copy here would say the same
        # thing twice and bury this step's own line.
        with contextlib.redirect_stdout(_io.StringIO()):
            rec = _mh(write=False)
    except Exception:
        return {}
    out = {}
    for axis, v in (rec.get("by_axis") or {}).items():
        if v.get("kind") != "MEASURED":
            continue
        obs = (v.get("measured_by") or {}).get("observed_value")
        if isinstance(obs, (int, float)):
            out[axis] = float(obs)
    return out


def axis_history(axis: str, metric: str | None = None, limit: int = 30) -> list:
    """Recent readings for an axis, oldest first, from the sealed archive."""
    vals = []
    if not ARCHIVE.is_dir():
        return vals
    for d in sorted(ARCHIVE.glob("cycle_*"))[-limit:]:
        f = d / "signals.json"
        if not f.is_file():
            continue
        try:
            sigs = json.loads(f.read_text(encoding="utf-8")).get("signals") or []
        except Exception:
            continue
        for s in sigs:
            if not isinstance(s, dict) or s.get("domain") != axis:
                continue
            if metric and s.get("metric") != metric:
                continue
            if isinstance(s.get("value"), (int, float)):
                vals.append(float(s["value"]))
                break
    return vals


# ── the methods ───────────────────────────────────────────────────────────────

def _predict(method: str, current: float, history: list) -> tuple | None:
    """(predicted, half_width) or None when the method cannot speak here."""
    h = [v for v in history if isinstance(v, (int, float))]
    if method == "persistence":
        spread = _spread(h)
        return current, max(spread, abs(current) * 0.01, 1e-9)
    if method == "trend":
        if len(h) < MIN_HISTORY:
            return None
        n = len(h)
        xs = list(range(n))
        mx, my = sum(xs) / n, sum(h) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx == 0:
            return None
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, h)) / sxx
        return current + slope, max(_spread(h) * 1.5, abs(current) * 0.01, 1e-9)
    if method == "mean_reversion":
        if len(h) < MIN_HISTORY:
            return None
        mean = sum(h) / len(h)
        return current + 0.25 * (mean - current), \
            max(_spread(h), abs(current) * 0.01, 1e-9)
    return None


def _spread(h: list) -> float:
    """Half-width from the series' own step size — never a hand-picked constant."""
    if len(h) < 2:
        return 0.0
    steps = [abs(h[i] - h[i - 1]) for i in range(1, len(h))]
    return 2.0 * (sum(steps) / len(steps))


def _best_method(axis: str, beliefs: dict) -> str:
    """The method belief_state currently trusts most for this axis.

    THE READER (WIRE_FIRST): this is what makes core/belief_revision.py more than
    another unread producer. If belief_state says trend has been missing on this
    axis, tonight's prediction stops coming from trend.
    """
    w = ((beliefs.get("axes") or {}).get(axis) or {}).get("method_weights") or {}
    if not w:
        return "persistence"
    return max(w.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _load_beliefs() -> dict:
    try:
        from core.belief_revision import load_state
        return load_state()
    except Exception:
        return {}


# ── intake from consolidation ─────────────────────────────────────────────────

def consolidation_hypotheses(path: Path | None = None, today: date | None = None) -> list:
    """The slow-drift claims core/consolidation.py wrote in the quiet hour.

    They already carry lo/hi and a due date; they are translated into the pending
    schema rather than regenerated, so the claim that is graded is the claim that
    was made.
    """
    p = path or CONSOLIDATION_QUEUE
    today = today or datetime.now(timezone.utc).date()
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for h in (d.get("hypotheses") or []):
        try:
            out.append({
                "id": f"{h['axis']}__{h['metric']}__anchored__{h['due_on']}",
                "axis": h["axis"],
                "metric": h.get("metric"),
                "method": "anchored",
                "predicted_value": float(h["predicted"]),
                "lo": float(h["lo"]),
                "hi": float(h["hi"]),
                "prediction_date": h["due_on"],
                "horizon_days": int(h["horizon_days"]),
                "hypothesis_text": (
                    f"{h['axis']}/{h['metric']} drifts {h['direction']} to "
                    f"{h['predicted']} by {h['due_on']} "
                    f"(interval [{h['lo']}, {h['hi']}], r2={h.get('r2')})"),
                "origin": "core/consolidation.py",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
            })
        except Exception:
            continue
    return out


# ── the run ───────────────────────────────────────────────────────────────────

def run(write: bool = True, today: date | None = None,
        pending: Path | None = None, queue: Path | None = None,
        latest: Path | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    pending_p = pending or PENDING

    try:
        existing = json.loads(pending_p.read_text(encoding="utf-8"))
        existing = existing if isinstance(existing, list) else []
    except Exception:
        existing = []
    seen = {h.get("id") for h in existing}

    beliefs = _load_beliefs()
    axes = measured_axes()
    new, skipped = [], {"already_registered": 0, "method_declined": 0}

    for axis, current in sorted(axes.items()):
        method = _best_method(axis, beliefs)
        hist = axis_history(axis)
        got = _predict(method, current, hist)
        if got is None:
            got = _predict("persistence", current, hist)
            method = "persistence"
        if got is None:
            skipped["method_declined"] += 1
            continue
        predicted, half = got
        due = today + timedelta(days=DEFAULT_HORIZON)
        hid = f"{axis}__{method}__{due.isoformat()}"
        if hid in seen:
            skipped["already_registered"] += 1
            continue
        new.append({
            "id": hid,
            "axis": axis,
            "method": method,
            "predicted_value": round(predicted, 6),
            "lo": round(predicted - half, 6),
            "hi": round(predicted + half, 6),
            "interval_width": round(2 * half, 6),
            "prediction_date": due.isoformat(),
            "horizon_days": DEFAULT_HORIZON,
            "value_at_registration": round(current, 6),
            "n_history": len(hist),
            "hypothesis_text": (
                f"{axis} reads {round(predicted, 4)} on {due.isoformat()} "
                f"(interval [{round(predicted - half, 4)}, "
                f"{round(predicted + half, 4)}], method={method}, "
                f"from {round(current, 4)} today)"),
            "origin": "core/hypothesis_intake.py",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        })
        seen.add(hid)

    for h in consolidation_hypotheses(queue, today):
        if h["id"] in seen:
            skipped["already_registered"] += 1
            continue
        new.append(h)
        seen.add(h["id"])

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "made_on": today.isoformat(),
        "measured_axes": len(axes),
        "registered": len(new),
        "from_consolidation": sum(1 for h in new
                                  if h.get("origin") == "core/consolidation.py"),
        "skipped": skipped,
        "pending_before": len(existing),
        "pending_after": len(existing) + len(new),
        "methods_used": sorted({h.get("method") for h in new if h.get("method")}),
        "every_hypothesis_has_an_interval": all(
            ("lo" in h and "hi" in h) for h in new),
        "writes_resolved_json": False,
    }

    if write and new:
        pending_p.parent.mkdir(parents=True, exist_ok=True)
        pending_p.write_text(json.dumps(existing + new, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    if write:
        (latest or LATEST).write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    rec["hypotheses"] = new
    return rec


def summary_line(rec: dict) -> str:
    if not rec["measured_axes"]:
        return ("[FAST_CYCLE] hypothesis_intake -> 0 MEASURED axes; nothing may be "
                "predicted tonight (an opinion is not a prediction)")
    if not rec["registered"]:
        return (f"[FAST_CYCLE] hypothesis_intake -> 0 new "
                f"({rec['skipped']['already_registered']} already registered for "
                f"their due date); {rec['pending_after']} pending")
    return (f"[FAST_CYCLE] hypothesis_intake -> {rec['registered']} pre-registered "
            f"from {rec['measured_axes']} MEASURED axes "
            f"({rec['from_consolidation']} from consolidation), methods="
            f"{','.join(rec['methods_used'])}; pending "
            f"{rec['pending_before']} -> {rec['pending_after']}")


def _selftest() -> int:
    print("core/hypothesis_intake --selftest")
    for label, p in (("pending", PENDING), ("consolidation queue", CONSOLIDATION_QUEUE)):
        print(f"  {label:22s}: {'LIVE ' if p.is_file() else 'INERT '}{p}")
    for rel, needle in (("fast_cycle_runner.py", "hypothesis_intake"),
                        ("core/cycle_map.py", "hypothesis_intake"),
                        ("config/cycle_phases.json", "hypothesis_intake")):
        p = REPO / rel
        wired = p.is_file() and needle in p.read_text(encoding="utf-8", errors="ignore")
        print(f"  consumer {rel:26s}: {'LIVE' if wired else 'INERT'}")
    rec = run(write=False)
    print("  dry run -> " + summary_line(rec).replace("[FAST_CYCLE] ", ""))
    for h in rec["hypotheses"][:3]:
        print(f"      {h['id']}: {h['predicted_value']} [{h['lo']}, {h['hi']}]")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    rec = run(write="--dry-run" not in sys.argv)
    print(summary_line(rec))
