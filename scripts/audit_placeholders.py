#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/audit_placeholders.py

Diagnostic only — changes nothing.

Loads snapshots/master/master_snapshot_latest.json, recursively finds every
numeric value == 0.5 (candidate placeholder score) with its full JSON path,
cross-references each axis name against target_config.json (domain mapping),
and prints a tight per-axis report:

    AXIS | DOMAIN | source_type | placeholder(0.5 hits)
"""
from __future__ import annotations
import json
import pathlib

BASE_DIR = pathlib.Path(__file__).resolve().parents[1]
MASTER_PATH = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"


def find_target_config() -> pathlib.Path | None:
    candidates = list(BASE_DIR.rglob("target_config.json"))
    return candidates[0] if candidates else None


def walk_for_half(obj, path=""):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits += walk_for_half(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += walk_for_half(v, f"{path}[{i}]")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if obj == 0.5:
            hits.append(path)
    return hits


def main():
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    snapshots = master.get("snapshots", {})

    tc_path = find_target_config()
    axis_domain = {}
    if tc_path:
        tc = json.loads(tc_path.read_text(encoding="utf-8"))
        # target_config.json is expected to map axis -> config incl. domain
        if isinstance(tc, dict):
            for axis, cfg in tc.items():
                if isinstance(cfg, dict):
                    axis_domain[axis] = cfg.get("domain", cfg.get("category", "?"))

    rows = []
    for axis, snap in snapshots.items():
        source_type = snap.get("source_type", "?") if isinstance(snap, dict) else "?"
        hits = walk_for_half(snap, axis)
        domain = axis_domain.get(axis, "?")
        rows.append((axis, domain, source_type, hits))

    print(f"master_snapshot: {MASTER_PATH}")
    print(f"target_config:   {tc_path if tc_path else 'NOT FOUND'}")
    print(f"timestamp:       {master.get('timestamp')}")
    print(f"axes_count:      {master.get('axes_count')} (snapshots={len(snapshots)})")
    print("-" * 100)
    print(f"{'AXIS':<38} {'DOMAIN':<14} {'SOURCE_TYPE':<20} PLACEHOLDER(0.5)")
    print("-" * 100)

    placeholder_axes = []
    for axis, domain, source_type, hits in rows:
        flag = f"YES ({len(hits)} hits)" if hits else "no"
        if hits:
            placeholder_axes.append((axis, hits))
        print(f"{axis:<38} {domain:<14} {source_type:<20} {flag}")

    print("-" * 100)
    if placeholder_axes:
        print(f"TOTAL AXES WITH 0.5 PLACEHOLDER VALUES: {len(placeholder_axes)}")
        for axis, hits in placeholder_axes:
            for h in hits:
                print(f"  {axis}: {h}")
    else:
        print("TOTAL AXES WITH 0.5 PLACEHOLDER VALUES: 0")


if __name__ == "__main__":
    main()
