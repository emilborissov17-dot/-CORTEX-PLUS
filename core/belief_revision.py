#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/belief_revision.py — C7, THE SPINE (3 Sep 2026).

The loop this closes. Step 20.06 pre-registers a prediction per measured axis with an
interval. Step 20.05 grades whatever came due. Until now nothing happened next: the
system could be wrong every night for a year and predict the same way on the last
night as on the first. Being wrong has to COST something, or measurement is theatre.

WHAT CHANGES WHEN A PREDICTION MISSES

  1. METHOD WEIGHTS, per axis. Four ways to predict a number — persistence
     (tomorrow = today), trend (linear), mean_reversion (pull to the window mean),
     anchored (consolidation's slow-drift fit). A method that missed on this axis
     loses weight on THIS axis and the others gain it. This is per-axis on purpose:
     persistence is excellent for a World Bank annual figure and useless for a
     refugee count, and one global ranking would average that distinction away.

  2. SOURCE TRUST, as a delta handed to core/source_lifecycle.py. If the reading a
     prediction was graded against came from a source, that source's record moves
     with the outcome. Written as a delta rather than applied here: source
     promotion and demotion is that module's decision, and two writers to one
     judgement is how a system ends up disagreeing with itself.

  3. llm_vs_data TRUST, per axis. The one number this system most needs and least
     has: when an axis has been both asserted by a model and measured, which was
     closer? Accumulated here so that a later question — "may this axis be scored by
     an llm_level at all?" — can be answered from a record instead of a preference.

SURPRISE, NOT ERROR (C11). The update is proportional to |error| / interval_width,
not to |error|. An interval is a claim about confidence: being 5 units out when you
said +/-1 is a different event from being 5 units out when you said +/-50, and only
the ratio can tell them apart. Without this, a method could buy immunity by
predicting a huge interval — the wider the interval, the smaller the surprise, but
also the smaller the credit for a hit. Bounded to MAX_SHIFT so one strange night
cannot flip an axis, and weights are renormalised so they stay a distribution.

EVERY REVISION IS APPENDED, NEVER SUMMARISED. memory/revision_ledger.jsonl carries
hypothesis id, error, the weight before, the weight after, and why — because a state
file alone cannot answer "when did this axis stop trusting trend, and what happened
that night". The ledger rides into the Merkle leaves through the cycle's normal
results[] anchoring, so the record of how the system changed its mind is sealed with
everything else.

REAL READER: core/hypothesis_intake._best_method() selects tonight's method from
these weights. That is what stops this being another producer nobody reads — a
revision here changes what gets predicted tomorrow.

  venv\\Scripts\\python.exe -m core.belief_revision --selftest
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "memory" / "belief_state.json"
LEDGER = REPO / "memory" / "revision_ledger.jsonl"
RESOLVED = REPO / "cortex_memory" / "hypotheses" / "resolved.json"

METHODS = ("persistence", "trend", "mean_reversion", "anchored")
MAX_SHIFT = 0.15          # one night may move a weight by at most this
MIN_WEIGHT = 0.02         # never let a method die completely — it may come back
HIT = 1.0                 # surprise at or below this counts as a hit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path | None = None) -> dict:
    try:
        d = json.loads((path or STATE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _blank_axis() -> dict:
    even = round(1.0 / len(METHODS), 6)
    return {"method_weights": {m: even for m in METHODS},
            "llm_vs_data": {"llm_closer": 0, "data_closer": 0},
            "resolutions": 0}


def surprise(error: float, lo, hi) -> float | None:
    """|error| / interval width. None when there is no interval to divide by.

    A prediction without an interval cannot be surprising in the C11 sense — it made
    no claim about its own confidence — so it is counted and skipped rather than
    folded in at some invented width.
    """
    try:
        width = float(hi) - float(lo)
    except (TypeError, ValueError):
        return None
    if width <= 0:
        return None
    return abs(float(error)) / width


def _renormalise(w: dict) -> dict:
    for m in METHODS:
        w[m] = max(MIN_WEIGHT, float(w.get(m, 0.0)))
    total = sum(w[m] for m in METHODS)
    return {m: round(w[m] / total, 6) for m in METHODS}


def revise_one(axis_state: dict, method: str, skill: float) -> tuple:
    """Move weight for one resolved hypothesis, on SKILL. Returns (before, after, shift).

    skill > 0 means the method beat persistence on this axis and gains weight; skill
    <= 0 means it did not and loses it. The size is the skill itself, clamped, so a
    method that wins by a hair moves the weights by a hair.
    """
    w = dict(axis_state["method_weights"])
    before = w.get(method, 1.0 / len(METHODS))
    if skill > 0:
        shift = min(MAX_SHIFT, MAX_SHIFT * min(float(skill), 1.0))
    else:
        shift = -min(MAX_SHIFT, MAX_SHIFT * min(abs(float(skill)), 1.0))
    w[method] = before + shift
    axis_state["method_weights"] = _renormalise(w)
    return before, axis_state["method_weights"][method], shift


def is_unscoreable(axis: str, archive: Path | None = None,
                   limit: int = 30, eps: float = 1e-9) -> bool:
    """True when the axis's observed series has ~no spread over the window.

    ADDED 4 Sep 2026 (H3). Measured that day: 9 of the 12 World-Bank-backed axes
    carry EXACTLY ONE distinct value across 30 consecutive sealed cycles. On such a
    series every method is exactly right, so a resolution cannot separate a forecast
    from a restatement — and a weight moved on it is noise wearing evidence's coat.
    """
    root = archive or (REPO / "cortex_memory" / "archive")
    if not root.is_dir():
        return False              # cannot tell -> do not refuse on a guess
    vals = []
    for d in sorted(root.glob("cycle_*"))[-limit:]:
        f = d / "signals.json"
        if not f.is_file():
            continue
        try:
            sigs = json.loads(f.read_text(encoding="utf-8")).get("signals") or []
        except Exception:
            continue
        for sig in sigs:
            if isinstance(sig, dict) and sig.get("domain") == axis                     and isinstance(sig.get("value"), (int, float)):
                vals.append(float(sig["value"]))
                break
    if len(vals) < 2:
        return False              # no window -> not a claim about the axis
    return (max(vals) - min(vals)) <= eps



def newly_resolved(since_ts: str | None, resolved: Path | None = None) -> list:
    """Hypotheses the evaluator moved to resolved.json after `since_ts`."""
    try:
        rows = json.loads((resolved or RESOLVED).read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        when = str(r.get("evaluated_at") or "")
        if since_ts and when <= since_ts:
            continue
        out.append(r)
    return out


def run(write: bool = True, state_path: Path | None = None,
        ledger_path: Path | None = None, resolved_path: Path | None = None,
        archive: Path | None = None) -> dict:
    sp = state_path or STATE
    state = load_state(sp)
    state.setdefault("axes", {})
    state.setdefault("source_trust_delta", {})
    since = state.get("last_seen_evaluated_at")

    rows = newly_resolved(since, resolved_path)
    refusals: list = []
    revisions, skipped = [], {"no_interval": 0, "unknown_method": 0, "no_error": 0,
                          "unresolvable": 0, "no_skill": 0,
                          "unscoreable_axis": 0}
    newest = since

    for r in rows:
        when = str(r.get("evaluated_at") or "")
        if newest is None or when > newest:
            newest = when
        # AN UNGRADEABLE PREDICTION TEACHES NOTHING (4 Sep 2026, Q0). The evaluator
        # now moves a past-due hypothesis with no ground truth into resolved.json
        # marked "unresolvable" so it stops rotting in pending. It carries no actual
        # value, so it must never move a weight: counted here by name rather than
        # falling through the no_error branch, which would report the same number
        # for "the reading was missing" and "the record was malformed".
        if r.get("status") == "unresolvable":
            skipped["unresolvable"] += 1
            continue
        axis = r.get("axis")
        method = r.get("method")
        if not axis:
            continue
        if method not in METHODS:
            skipped["unknown_method"] += 1
            continue
        actual, predicted = r.get("actual_value"), r.get("predicted_value")
        if not isinstance(actual, (int, float)) or                 not isinstance(predicted, (int, float)):
            skipped["no_error"] += 1
            continue

        # SKILL IS WHAT MOVES A WEIGHT (4 Sep 2026, H1). Until today the update
        # rode on surprise = |error| / interval_width, which says how confident the
        # interval was but nothing about whether the model beat doing nothing. On a
        # series that has not moved in 30 cycles, a persistence prediction is exact,
        # surprise is ~0, and the method that could not lose is rewarded every
        # night. The evaluator now computes skill against a named naive baseline and
        # refuses to grade what it cannot score; this consumes that decision rather
        # than second-guessing it.
        skill = r.get("skill")
        if not isinstance(skill, (int, float)):
            skipped["no_skill"] += 1
            refusals.append({"hypothesis_id": r.get("id"), "axis": axis,
                             "why": (r.get("unresolvable_reason")
                                     or "no skill score on the resolved record")})
            continue

        # AN UNSCOREABLE AXIS TEACHES NOTHING (H3). A series whose spread over the
        # window is ~0 cannot separate a good forecast from a restatement, whatever
        # number the grader produced. Refused by name rather than folded in small.
        if is_unscoreable(axis, archive):
            skipped["unscoreable_axis"] += 1
            refusals.append({"hypothesis_id": r.get("id"), "axis": axis,
                             "why": (f"axis {axis} is UNSCOREABLE: its observed "
                                     f"spread over the archive window is ~0, so no "
                                     f"resolution on it can carry signal")})
            continue

        error = float(actual) - float(predicted)
        s = surprise(error, r.get("lo"), r.get("hi"))   # recorded, no longer decisive


        ax = state["axes"].setdefault(axis, _blank_axis())
        before, after, shift = revise_one(ax, method, float(skill))
        ax["resolutions"] = int(ax.get("resolutions", 0)) + 1

        # source trust: a delta for source_lifecycle to apply, never applied here
        src = (r.get("measured_by") or {}).get("source_id") or r.get("source_id")
        if src:
            d = state["source_trust_delta"].setdefault(
                src, {"delta": 0.0, "n": 0})
            d["delta"] = round(d["delta"] + (shift / MAX_SHIFT) * 0.05, 6)
            d["n"] += 1

        rev = {
            "ts": _now(),
            "hypothesis_id": r.get("id"),
            "axis": axis,
            "method": method,
            "predicted": predicted,
            "actual": actual,
            "error": round(error, 6),
            "lo": r.get("lo"),
            "hi": r.get("hi"),
            "surprise": (round(s, 6) if isinstance(s, (int, float)) else None),
            "skill": round(float(skill), 6),
            "baseline_error": r.get("baseline_error"),
            "model_error": r.get("model_error"),
            "verdict": "beat_persistence" if skill > 0 else "lost_to_persistence",
            "weight_before": round(before, 6),
            "weight_after": round(after, 6),
            "shift": round(shift, 6),
            "source_id": src,
            "why": (f"skill {skill:+.4f} = 1 - model_error {r.get('model_error')} / "
                    f"persistence_error {r.get('baseline_error')}; "
                    f"{'beat' if skill > 0 else 'did not beat'} doing nothing, "
                    f"so weight on {method} for {axis} moved {shift:+.4f}"),
        }
        revisions.append(rev)

    state["last_seen_evaluated_at"] = newest
    state["updated"] = _now()
    state["revisions_total"] = int(state.get("revisions_total", 0)) + len(revisions)

    rec = {
        "ts": _now(),
        "resolved_seen": len(rows),
        "revisions": len(revisions),
        "skipped": skipped,
        "refusals": refusals,
        "axes_touched": sorted({r["axis"] for r in revisions}),
        "hits": sum(1 for r in revisions if r["verdict"] == "beat_persistence"),
        "misses": sum(1 for r in revisions if r["verdict"] == "lost_to_persistence"),
        "state_path": str(sp),
    }

    if write:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        if revisions:
            lp = ledger_path or LEDGER
            lp.parent.mkdir(parents=True, exist_ok=True)
            with lp.open("a", encoding="utf-8") as fh:
                for rev in revisions:
                    fh.write(json.dumps(rev, ensure_ascii=False) + "\n")
    rec["state"] = state
    rec["revision_records"] = revisions
    return rec


def summary_line(rec: dict) -> str:
    if not rec["revisions"]:
        why = ", ".join(f"{k}={v}" for k, v in sorted(rec["skipped"].items()) if v)
        return (f"[FAST_CYCLE] belief_revision -> 0 revisions "
                f"({rec['resolved_seen']} resolved seen; refused: {why or 'nothing due'})")
    return (f"[FAST_CYCLE] belief_revision -> {rec['revisions']} revisions "
            f"({rec['hits']} beat persistence / {rec['misses']} lost to it) across "
            f"{len(rec['axes_touched'])} axes; "
            f"{rec['revisions']} appended to memory/revision_ledger.jsonl")


def _selftest() -> int:
    print("core/belief_revision --selftest")
    for label, p in (("belief_state", STATE), ("revision_ledger", LEDGER),
                     ("resolved.json", RESOLVED)):
        print(f"  {label:18s}: {'LIVE ' if p.is_file() else 'INERT '}{p}")
    for rel, needle in (("core/hypothesis_intake.py", "belief_revision"),
                        ("fast_cycle_runner.py", "belief_revision"),
                        ("core/cycle_map.py", "belief_revision")):
        p = REPO / rel
        wired = p.is_file() and needle in p.read_text(encoding="utf-8", errors="ignore")
        print(f"  reader {rel:28s}: {'LIVE' if wired else 'INERT'}")
    rec = run(write=False)
    print("  dry run -> " + summary_line(rec).replace("[FAST_CYCLE] ", ""))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    rec = run(write="--dry-run" not in sys.argv)
    print(summary_line(rec))
