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
                "interval_nominal": INTERVAL_NOMINAL,
                "interval_basis": INTERVAL_BASIS,
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

# ── BORN GRADEABLE, OR NOT BORN (4 Sep 2026, H2) ─────────────────────────────
# The seven-week freeze was a metric-name mismatch: a hypothesis registered under
# "co2_ppm" while the grader knew the reading as "co2_ppm_mauna_loa". Third
# instance of this defect class. The fix is not a synonym dictionary — it is to
# resolve the key against the live store AT CREATION, using the same resolver the
# grader will use, and refuse to write a prediction that cannot be graded. A
# prediction must never be born ungradeable and discover it 49 days later.
#
# PERSISTENCE_EPS: a prediction equal to its own anchor is not a prediction, it is
# a restatement, and it cannot be wrong. Measured 4 Sep: 13 of 14 live pendings
# had |predicted - anchor| EXACTLY 0 on axes that have not moved in 30 cycles.
PERSISTENCE_EPS = 1e-6

# EVERY INTERVAL DECLARES ITS NOMINAL LEVEL (4 Sep 2026, H3). Without this field
# neither an interval score nor coverage is computable later — the same defect
# class as axis_observations having no observation date: the number that makes
# the record checkable simply does not exist, so nobody can tell it is missing.
#
# DECLARED, NOT CALIBRATED, and the record says so. The half-width is 2x the mean
# absolute step of the series (_spread), which is a plausible ~80% band for a
# random walk and is NOT a measured quantile. Whether the intervals actually
# cover 80% is unknown and stays unknown until there are enough real resolutions
# on an axis to measure it. Writing 0.80 here is a claim we can later be caught
# out on; writing nothing is how we would never be.
INTERVAL_NOMINAL = 0.80
INTERVAL_BASIS = ("declared, not calibrated: half-width is 2x the series mean "
                  "absolute step; coverage is UNKNOWN until enough resolutions "
                  "exist on this axis to measure it")


def _resolves(axis: str, metric: str | None):
    """(value, why_not) from the grader's own resolver, so creation and grading
    cannot disagree about what a key means."""
    try:
        import evaluator as _ev
        v, trail = _ev.ground_truth(axis, metric)
    except Exception as exc:
        return None, f"ground truth lookup failed: {type(exc).__name__}: {exc}"
    if v is None:
        return None, "; ".join(trail)
    return v, None


def _is_restatement(predicted, anchor) -> bool:
    """True when the prediction is its own anchor within tolerance."""
    if anchor is None or predicted is None:
        return False
    try:
        return abs(float(predicted) - float(anchor)) <=             PERSISTENCE_EPS * max(1.0, abs(float(anchor)))
    except (TypeError, ValueError):
        return False


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
    new, skipped = [], {"already_registered": 0, "method_declined": 0,
                        "key_unresolvable": 0, "restatement": 0}
    refused: list = []

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
        # A METHOD THAT ONLY RESTATES IS NOT THE METHOD TO USE (4 Sep 2026, H2).
        # persistence predicts exactly the anchor by construction, so with uniform
        # beliefs every axis would be refused as a restatement and the step would
        # be permanently silent. Try the others before giving up: on a series that
        # actually moves, trend or mean_reversion say something falsifiable; on a
        # frozen one they all restate and the refusal below is the true answer.
        if got is not None and _is_restatement(got[0], current):
            for alt in ("trend", "mean_reversion", "anchored"):
                if alt == method:
                    continue
                alt_got = _predict(alt, current, hist)
                if alt_got is not None and not _is_restatement(alt_got[0], current):
                    got, method = alt_got, alt
                    break
        predicted, half = got
        due = today + timedelta(days=DEFAULT_HORIZON)
        hid = f"{axis}__{method}__{due.isoformat()}"
        if hid in seen:
            skipped["already_registered"] += 1
            continue
        ok, why_not = _resolves(axis, None)
        if ok is None:
            # BORN GRADEABLE OR NOT BORN (H2)
            skipped["key_unresolvable"] += 1
            refused.append({"axis": axis, "metric": None, "reason": why_not,
                            "refused": "key does not resolve against the live store"})
            continue
        if _is_restatement(predicted, current):
            # A RESTATEMENT IS NOT A PREDICTION (H2). It cannot be wrong, so it
            # cannot teach, and grading it as a 100% win is how a frozen series
            # convinces C7 that persistence is a good model.
            skipped["restatement"] += 1
            refused.append({"axis": axis, "metric": None,
                            "reason": (f"predicted {predicted!r} equals the "
                                       f"persistence anchor {current!r} within "
                                       f"{PERSISTENCE_EPS}"),
                            "refused": "a restatement of the anchor is not a prediction"})
            continue
        new.append({
            "id": hid,
            "axis": axis,
            "method": method,
            "predicted_value": round(predicted, 6),
            "lo": round(predicted - half, 6),
            "hi": round(predicted + half, 6),
            "interval_width": round(2 * half, 6),
            "interval_nominal": INTERVAL_NOMINAL,
            "interval_basis": INTERVAL_BASIS,
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
        anchor, why_not = _resolves(h.get("axis"), h.get("metric"))
        if anchor is None:
            # THE LIVE INSTANCE: CLIMATE_GLOBAL_RISK_REVIEW__co2_annual_increase
            # predicts the annual INCREASE (0.55) while its axis exposes the LEVEL
            # (426.94). Grading it by axis would score a rate against a level.
            skipped["key_unresolvable"] += 1
            refused.append({"axis": h.get("axis"), "metric": h.get("metric"),
                            "reason": why_not,
                            "refused": "key does not resolve against the live store"})
            continue
        # consolidation records never carried a persistence anchor, so nothing they
        # produced could ever have been scored for skill
        h.setdefault("value_at_registration", round(float(anchor), 6))
        if _is_restatement(h.get("predicted_value"), anchor):
            skipped["restatement"] += 1
            refused.append({"axis": h.get("axis"), "metric": h.get("metric"),
                            "reason": (f"predicted {h.get('predicted_value')!r} equals "
                                       f"the persistence anchor {anchor!r}"),
                            "refused": "a restatement of the anchor is not a prediction"})
            continue
        new.append(h)
        seen.add(h["id"])

    # AN INTERVAL WITHOUT A DECLARED LEVEL NEVER REACHES DISK (H3). Checked here
    # rather than trusted at each construction site, so a future third record shape
    # cannot quietly reintroduce the gap.
    for h in list(new):
        if ("lo" in h or "hi" in h) and h.get("interval_nominal") is None:
            new.remove(h)
            skipped["interval_without_level"] =                 skipped.get("interval_without_level", 0) + 1
            refused.append({"axis": h.get("axis"), "metric": h.get("metric"),
                            "reason": ("the record carries lo/hi but no "
                                       "interval_nominal, so neither an interval "
                                       "score nor coverage can ever be computed"),
                            "refused": "interval without a declared nominal level"})

    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "made_on": today.isoformat(),
        "measured_axes": len(axes),
        "registered": len(new),
        "from_consolidation": sum(1 for h in new
                                  if h.get("origin") == "core/consolidation.py"),
        "skipped": skipped,
        # EVERY REFUSAL, WITH ITS NAMED REASON (H3). A night that registers
        # nothing because everything it could say was a restatement is a
        # RESULT, and it has to be readable as one.
        "refused": refused,
        "refused_count": len(refused),
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
    ref = rec.get("refused_count", 0)
    why = ", ".join(f"{k}={v}" for k, v in sorted(rec.get("skipped", {}).items()) if v)
    if not rec.get("registered"):
        gate = ("nothing may be predicted" if not rec.get("measured_axes")
                else "nothing worth predicting")
        return (f"[FAST_CYCLE] hypothesis_intake -> 0 registered from "
                f"{rec.get('measured_axes', 0)} measured axes ({gate}); {ref} refused "
                f"({why or 'nothing to say'})")
    return (f"[FAST_CYCLE] hypothesis_intake -> {rec['registered']} registered "
            f"({', '.join(rec.get('methods_used') or []) or 'no method'}), "
            f"{ref} refused ({why or 'none'}); "
            f"pending {rec.get('pending_before')} -> {rec.get('pending_after')}")




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
