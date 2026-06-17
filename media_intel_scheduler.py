#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
media_intel_scheduler.py
Standalone daily scheduler for media_intel_worker.py.

Design:
  - Runs once per day at SCHEDULE_HOUR (default 02:00 local time)
  - Processes MAX_AXES_PER_RUN axes per run, rotating through all 25
  - Axes are ordered by weight (highest priority first) from target_config.json
  - YouTube API quota budget: 5 axes × 3 phrases × 2 searches = 30 calls = 3000 units/day
  - Lock file prevents concurrent instances; stale locks (>6h) are cleared
  - State persists which axes were processed last, for rotation

Usage:
  python media_intel_scheduler.py              # start blocking daily loop
  python media_intel_scheduler.py --run-now    # run one batch immediately and exit
  python media_intel_scheduler.py --axis CLIMATE_GLOBAL_RISK_REVIEW  # single axis, exit
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

LOCK_FILE     = BASE / "cortex_memory" / "media_scheduler.lock"
STATE_FILE    = BASE / "cortex_memory" / "media_scheduler_state.json"
LOG_FILE      = BASE / "cortex_memory" / "media_scheduler.log"
TARGET_CONFIG = BASE / "config" / "target_config.json"

SCHEDULE_HOUR    = 2      # 02:00 local time
MAX_AXES_PER_RUN = 5      # axes per daily run (YouTube quota management)
INTER_AXIS_SLEEP = 30     # seconds between axes (rate limiting)
MAX_LOCK_AGE_SEC = 6 * 3600  # stale lock threshold: 6 hours


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    line = f"[{_utc_now()}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------

def _acquire_lock() -> bool:
    if LOCK_FILE.exists():
        age = time.time() - LOCK_FILE.stat().st_mtime
        if age < MAX_LOCK_AGE_SEC:
            return False  # fresh lock → another instance is likely running
        _log(f"Stale lock found ({age/3600:.1f}h old) — clearing")
        LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_run_utc": None, "next_axis_index": 0, "total_runs": 0}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Axis list
# ---------------------------------------------------------------------------

def _load_all_axes() -> list[str]:
    """All 25 axes from target_config.json, sorted by weight descending."""
    config = json.loads(TARGET_CONFIG.read_text(encoding="utf-8"))
    axes: list[tuple[str, int]] = []
    for domain_block in config.values():
        if not isinstance(domain_block, dict):
            continue
        for axis_name, axis_cfg in domain_block.items():
            if isinstance(axis_cfg, dict):
                axes.append((axis_name, axis_cfg.get("weight", 5)))
    axes.sort(key=lambda x: x[1], reverse=True)
    return [a for a, _ in axes]


def _next_batch(all_axes: list[str], state: dict) -> tuple[list[str], int]:
    """Return (batch_of_axes, new_next_index). Wraps around."""
    n   = len(all_axes)
    idx = state.get("next_axis_index", 0) % n
    end = idx + MAX_AXES_PER_RUN

    if end <= n:
        batch = all_axes[idx:end]
        new_idx = end % n
    else:
        # Wrap: take tail + head
        batch   = all_axes[idx:] + all_axes[:end - n]
        new_idx = end - n

    return batch, new_idx


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_batch(axes: list[str]) -> dict:
    """Run process_axis() for each axis in the list. Returns per-axis results."""
    from media_intel_worker import process_axis

    results = {}
    for i, axis in enumerate(axes):
        _log(f"[{i+1}/{len(axes)}] Starting axis: {axis}")
        try:
            summary    = process_axis(axis, max_videos_per_phrase=2)
            n_done     = sum(1 for r in summary["results"] if r.get("action") == "transcribed")
            n_skipped  = sum(1 for r in summary["results"] if r.get("action") == "skipped_pre")
            results[axis] = {"status": "ok", "transcribed": n_done, "skipped_pre": n_skipped}
            _log(f"  {axis} -> transcribed={n_done}  skipped_pre={n_skipped}")
        except Exception as e:
            results[axis] = {"status": "error", "error": str(e)}
            _log(f"  {axis} -> ERROR: {e}")

        if i < len(axes) - 1:
            _log(f"  Sleeping {INTER_AXIS_SLEEP}s before next axis...")
            time.sleep(INTER_AXIS_SLEEP)

    return results


def run_now(single_axis: str | None = None) -> None:
    """Acquire lock, run one batch, release lock."""
    if not _acquire_lock():
        _log("Another scheduler instance is running (fresh lock exists). Exiting.")
        return

    try:
        all_axes = _load_all_axes()
        state    = _load_state()

        if single_axis:
            if single_axis not in all_axes:
                _log(f"Unknown axis: {single_axis}")
                return
            batch   = [single_axis]
            new_idx = state.get("next_axis_index", 0)  # don't advance rotation
        else:
            batch, new_idx = _next_batch(all_axes, state)

        _log(f"Batch ({len(batch)} axes): {batch}")
        results = run_batch(batch)

        state.update({
            "last_run_utc":   _utc_now(),
            "next_axis_index": new_idx,
            "total_runs":     state.get("total_runs", 0) + 1,
            "last_batch":     batch,
            "last_results":   results,
        })
        _save_state(state)
        _log(f"Batch complete. Rotation index now at {new_idx}/{len(all_axes)}. "
             f"Total runs: {state['total_runs']}")
    finally:
        _release_lock()


# ---------------------------------------------------------------------------
# Scheduling loop
# ---------------------------------------------------------------------------

def _seconds_until_next(hour: int, minute: int = 0) -> float:
    now    = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def main_loop() -> None:
    """Blocking daily loop. Runs indefinitely; interrupt with Ctrl-C."""
    _log(
        f"Media Intel Scheduler started. "
        f"Schedule: daily at {SCHEDULE_HOUR:02d}:00, "
        f"{MAX_AXES_PER_RUN} axes/run."
    )
    all_axes = _load_all_axes()
    _log(f"Total axes in rotation: {len(all_axes)}")
    _log(f"Full cycle completes in {len(all_axes) // MAX_AXES_PER_RUN + 1} days")

    while True:
        wait   = _seconds_until_next(SCHEDULE_HOUR)
        wake   = datetime.now() + timedelta(seconds=wait)
        _log(f"Next run at {wake.strftime('%Y-%m-%d %H:%M')} (in {wait/3600:.1f}h)")
        time.sleep(wait)

        _log("Scheduled run starting...")
        run_now()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--run-now" in sys.argv:
        _log("--run-now flag: running immediately")
        run_now()
    elif "--axis" in sys.argv:
        idx = sys.argv.index("--axis")
        ax  = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if ax:
            _log(f"--axis flag: single axis {ax}")
            run_now(single_axis=ax)
        else:
            print("Usage: --axis <AXIS_NAME>")
    else:
        main_loop()
