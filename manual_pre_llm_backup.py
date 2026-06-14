#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hypercortex_runner.py
Главен оркестратор на CORTEX++_QWEN.
Пуска всички snapshot агенти и генерира финален GOAL_PROGRESS_REVIEW.
"""
from __future__ import annotations
import json, pathlib, subprocess, sys
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from agents.actions.hypercortex_actions_agent import run_actions as run_actions_agent

AGENTS = [
    "agents.planet.planet_snapshots_agent_qwen",
    "agents.human.human_snapshots_agent_qwen",
    "agents.civilization.civilization_snapshots_agent_qwen",
    "agents.cosmos.cosmos_snapshots_agent_qwen",
]

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _run_agent(module: str) -> bool:
    print(f"\n[HYPERCORTEX] running {module}...")
    result = subprocess.run(
        [sys.executable, "-m", module],
        cwd=str(BASE_DIR),
        capture_output=False,
        timeout=600,
    )
    ok = result.returncode == 0
    print(f"[HYPERCORTEX] {module} -> {'OK' if ok else 'FAILED'}")
    return ok

def _collect_snapshots() -> dict:
    snapshots = {}
    snap_dir = BASE_DIR / "snapshots"
    for json_file in sorted(snap_dir.rglob("*_snapshot_latest.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            axis = data.get("axis", json_file.stem)
            snapshots[axis] = data
        except Exception:
            pass
    return snapshots

def _write_master_report(snapshots: dict) -> pathlib.Path:
    out_dir = BASE_DIR / "snapshots" / "master"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "master_snapshot_latest.json"
    report = {
        "report_type": "MASTER_CIVILIZATION_SNAPSHOT",
        "timestamp": _utc_now(),
        "axes_count": len(snapshots),
        "axes": list(snapshots.keys()),
        "snapshots": snapshots,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

def main():
    print("=" * 60)
    print("[HYPERCORTEX] CORTEX++_QWEN — FULL CIVILIZATION SNAPSHOT")
    print(f"[HYPERCORTEX] started at {_utc_now()}")
    print("=" * 60)

    results = {}
    for agent in AGENTS:
        try:
            results[agent] = _run_agent(agent)
        except Exception as e:
            print(f"[HYPERCORTEX] ERROR running {agent}: {e}")
            results[agent] = False

    print("\n[HYPERCORTEX] collecting all snapshots...")
    snapshots = _collect_snapshots()

    print(f"[HYPERCORTEX] {len(snapshots)} axis snapshots collected.")
    out_path = _write_master_report(snapshots)
    print(f"[HYPERCORTEX] master report -> {out_path}")

    print("\n[HYPERCORTEX] SUMMARY:")
    for agent, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {agent}")
    print(f"\n[HYPERCORTEX] master snapshot ready. Running actions plan...")

    # НОВ ЕТАП: действия (run_script / modify_config / llm_refactor)
    try:
        run_actions_agent()
        print("[HYPERCORTEX] actions agent -> OK")
    except Exception as e:
        print(f"[HYPERCORTEX] actions agent -> ERROR: {e}")

    print(f"\n[HYPERCORTEX] done at {_utc_now()}")
    print("=" * 60)

if __name__ == "__main__":
    main()
