#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/scorer_self_check.py — standing facade self-check for the axis scoring layer.

WHY
---
A scorer that reads metric keys the provider does not emit silently defaults to
its base score and publishes a constant as if it were measured. This is the bug
class the 2026-07-21 audit found across the scoring layer:

  - CLIMATE_GLOBAL_RISK read `forecast_forecast_max_temp_7d` (double-prefix bug)
  - EDUCATION_CULTURE  read `adult_literacy_rate` while the provider emits
    `literacy_rate_adult_pct` — 0 of its keys present → pinned at 0.50 forever
  - GOVERNANCE_INSTITUTIONS scored an empty `{}` snapshot → pinned at 0.45

Nothing warned. A dead computation published a `VERIFIED` score for an unknown
number of cycles, and the divergence engine never fired on itself. This module
turns that failure LOUD: after scoring, it verifies each real scorer actually
consumed real data from the snapshot it scored.

WHAT IT CHECKS
--------------
For each axis with a real scorer, it extracts the metric keys the scorer reads
(literal `metrics.get("KEY")` calls) and checks how many are present-and-non-None
in that axis's snapshot:

  DEAD      read > 0 and NONE of the read keys EXIST in the payload → the
            scorer's key contract is broken (naming drift or empty snapshot);
            it demonstrably scored from defaults (LOUD alarm)
  DEGRADED  some read keys never appear in the payload → partial wiring, likely
            a naming bug on those keys, or a benign fallback chain `a or b`
  STALE     all read keys exist but are None this cycle → wiring is fine, the
            data source returned nothing (transient outage, NOT a bug)
  LIVE      every read key exists and is non-None
  NO_KEYS   read == 0 → scorer reads via a non-literal pattern; can't judge
  NO_SNAPSHOT → scorer exists but no snapshot to score

The DEAD verdict is deliberately keyed on whether the read keys EXIST (not on
their value), so a transient all-None cycle from a data outage reads as STALE,
never as a bug. Only DEAD is a hard alarm; DEGRADED/STALE are advisory.

SCOPE
-----
Covers the authoritative per-axis scorers in `cortex_scoring_engine.AXIS_SCORERS`
(the layer feeding the goal composite). The planet *normalizer* layer
(`planet_normalization.py`, which sets the snapshot `level` the LLM synthesis
reads) is a separate surface with the same failure mode; `audit()` is generic
enough to be pointed at it later by passing a different reader→metrics mapping.

Pure functions. No writes here — the caller persists the report.
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Callable, Dict, List

# Matches literal   metrics.get("key")   /   metrics.get('key', default)
_KEY_RE = re.compile(r'metrics\.get\(\s*["\']([^"\']+)["\']')

DEAD = "DEAD"
DEGRADED = "DEGRADED"
STALE = "STALE"
LIVE = "LIVE"
NO_KEYS = "NO_KEYS_DETECTED"
NO_SNAPSHOT = "NO_SNAPSHOT"


def keys_read(scorer: Callable) -> set:
    """The set of metric keys a scorer reads via literal metrics.get("...")."""
    try:
        src = inspect.getsource(scorer)
    except (OSError, TypeError):
        return set()
    return set(_KEY_RE.findall(src))


def _unwrap(metrics: Any) -> Dict[str, Any]:
    """Mirror cortex_scoring_engine._unwrap_metrics for nested snapshots."""
    while isinstance(metrics, dict) and isinstance(metrics.get("metrics"), dict):
        metrics = metrics["metrics"]
    return metrics if isinstance(metrics, dict) else {}


def classify(read: set, metrics: Any) -> Dict[str, Any]:
    """Pure verdict from a read-key set and the metrics dict. Offline-testable.

    Keyed on whether read keys EXIST (not their value), so a transient all-None
    cycle reads as STALE, not DEAD.
    """
    m = _unwrap(metrics)
    exists = {k for k in read if k in m}                     # wiring: key appears at all
    present = {k for k in read if m.get(k) is not None}      # data: non-None this cycle

    if not read:
        verdict = NO_KEYS
    elif not exists:
        verdict = DEAD          # contract broken — none of the read keys exist
    elif exists < read:
        verdict = DEGRADED      # some read keys never appear (naming drift or fallback)
    elif not present:
        verdict = STALE         # wired, but all None this cycle (data outage, not a bug)
    else:
        verdict = LIVE

    return {
        "verdict": verdict,
        "n_read": len(read),
        "n_exist": len(exists),
        "n_present": len(present),
        "keys_present": sorted(present),
        "keys_never_appear": sorted(read - exists),
    }


def audit_axis(axis: str, scorer: Callable, metrics: Any) -> Dict[str, Any]:
    """Verdict for one axis given its scorer and the metrics it was scored on."""
    row = classify(keys_read(scorer), metrics)
    row["axis"] = axis
    return row


def audit(scorers: Dict[str, Callable],
          snapshots: Dict[str, Any]) -> Dict[str, Any]:
    """Audit a mapping of axis→scorer against a mapping of axis→metrics.

    Pure and offline-testable. `snapshots[axis]` is the metrics dict the scorer
    was (or would be) called with.
    """
    rows: List[Dict[str, Any]] = []
    for axis, scorer in sorted(scorers.items()):
        if axis not in snapshots:
            rows.append({"axis": axis, "verdict": NO_SNAPSHOT,
                         "n_read": len(keys_read(scorer)), "n_exist": 0,
                         "n_present": 0, "keys_present": [], "keys_never_appear": []})
            continue
        rows.append(audit_axis(axis, scorer, snapshots[axis]))

    summary: Dict[str, int] = {}
    for r in rows:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1

    return {
        "axes": rows,
        "summary": summary,
        "dead": [r["axis"] for r in rows if r["verdict"] == DEAD],
        "degraded": [r["axis"] for r in rows if r["verdict"] == DEGRADED],
        "stale": [r["axis"] for r in rows if r["verdict"] == STALE],
        "no_snapshot": [r["axis"] for r in rows if r["verdict"] == NO_SNAPSHOT],
    }


def run_from_snapshots() -> Dict[str, Any]:
    """Load AXIS_SCORERS + the latest snapshots and audit them.

    Mirrors the scoring engine's newest-wins dedup so a stale/empty duplicate
    snapshot cannot mask a good one.
    """
    from cortex_scoring_engine import (  # lazy import to avoid a cycle
        AXIS_SCORERS, SNAPSHOTS_DIR, _load_snapshot, _snapshot_timestamp,
    )

    resolved: Dict[str, Any] = {}
    chosen_ts: Dict[str, Any] = {}
    for f in sorted(SNAPSHOTS_DIR.rglob("*_snapshot_latest.json")):
        snap = _load_snapshot(f)
        if not snap:
            continue
        axis = snap.get("axis")
        if not axis:
            continue
        ts = _snapshot_timestamp(snap, f)
        if axis in chosen_ts and ts <= chosen_ts[axis]:
            continue
        chosen_ts[axis] = ts
        resolved[axis] = snap.get("metrics") or (snap.get("raw") or {}).get("metrics", {}) or {}

    return audit(AXIS_SCORERS, resolved)


def format_report(report: Dict[str, Any]) -> List[str]:
    """Human-readable lines; DEAD axes first and loud."""
    lines: List[str] = []
    dead, degraded, stale = report["dead"], report["degraded"], report.get("stale", [])
    s = report["summary"]
    live = s.get(LIVE, 0)
    total = sum(s.values())

    if dead:
        lines.append(f"🚨 FACADE SELF-CHECK: {len(dead)} scorer(s) with a BROKEN key contract "
                     f"(publishing a constant from defaults):")
        for r in report["axes"]:
            if r["verdict"] == DEAD:
                lines.append(f"   🚨 DEAD  {r['axis']} — reads {r['n_read']} keys, none exist in the "
                             f"payload (e.g. {r['keys_never_appear'][:4]})")
    else:
        lines.append("✅ FACADE SELF-CHECK: no dead scorers (every real scorer's key contract holds).")

    if degraded:
        lines.append(f"   ⚠️  {len(degraded)} degraded (some read keys never appear — naming/fallback): "
                     f"{', '.join(degraded)}")
    if stale:
        lines.append(f"   ⓘ  {len(stale)} stale (wired, but all inputs None this cycle — data outage): "
                     f"{', '.join(stale)}")
    lines.append(f"   summary: {live}/{total} LIVE | {len(degraded)} degraded | "
                 f"{len(stale)} stale | {len(dead)} DEAD")
    return lines


def main() -> int:
    report = run_from_snapshots()
    for line in format_report(report):
        print(line)
    # Non-zero exit if any dead scorer, so this is usable as a CI/manual gate.
    return 1 if report["dead"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
