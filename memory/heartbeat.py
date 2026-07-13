#!/usr/bin/env python3
"""
memory/heartbeat.py — the cycle's proof of life.

WHY A FILE, NOT STDOUT
----------------------
The 2026-07-11 lesson: PowerShell buffers a child process's stdout, so "no
output for 15 minutes" is indistinguishable from "hung". A watchdog reading
stdout would kill healthy cycles. A file write is observable immediately by an
unrelated process, with no buffering in between.

WHY EVERY STEP MUST BEAT
------------------------
fast_cycle_runner has two kinds of step: those that go through _run(label, fn),
and roughly a dozen that use inline try/except (body_scan, homeostasis,
global_indicators, web_intelligence_agent, scoring_engine, auto_levels,
goal_score_calculator, the Merkle commit, ...). If only _run() beat, the cycle
would look FROZEN during exactly the steps that legitimately take longest —
global_indicators hits 20 live HTTP APIs, web_intelligence can run for the best
part of an hour — and the watchdog would kill perfectly healthy cycles.

So beat() is called explicitly at every step boundary, and
test_heartbeat_coverage.py asserts that no step is left uninstrumented. That
test is the thing that keeps this true as the cycle grows.

WRITES ARE ATOMIC
-----------------
temp file + os.replace(). The supervisor reads this file from another process at
any moment; a half-written heartbeat that failed to parse would look like a dead
cycle and trigger a kill.

This module is deliberately dependency-free and cheap: a beat is a few hundred
bytes and happens ~25 times per cycle.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = BASE / "memory" / "heartbeat.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def beat(step: str, step_index: Optional[int] = None, cycle_id: Optional[str] = None) -> None:
    """Record that the cycle is alive and has entered `step`.

    Never raises: a failure to write the heartbeat must not kill the cycle. The
    worst case of a failed write is that the supervisor eventually sees a stale
    heartbeat and restarts us — which is the correct conservative behaviour, and
    far better than crashing a healthy cycle over a transient file lock.
    """
    try:
        prev = read() or {}
        # Preserve the cycle_id across beats; only the first beat sets it.
        cid = cycle_id or prev.get("cycle_id") or _utc_now()

        now = _utc_now()
        payload = {
            "pid":              os.getpid(),
            "cycle_id":         cid,
            "step":             step,
            "step_index":       step_index,
            "step_started_utc": now,
            "updated_utc":      now,
        }
        _write_atomic(payload)
    except Exception:
        pass  # never let the heartbeat kill the cycle


def _write_atomic(payload: dict) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(HEARTBEAT_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, HEARTBEAT_PATH)   # atomic on Windows and POSIX
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def read() -> Optional[dict]:
    """The current heartbeat, or None if absent/unreadable.

    A torn or missing heartbeat returns None. The supervisor treats None as "no
    proof of life", which is the safe reading.
    """
    if not HEARTBEAT_PATH.exists():
        return None
    try:
        return json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def age_seconds(now: Optional[datetime] = None) -> Optional[float]:
    """Seconds since the last beat, or None if there is no readable heartbeat."""
    hb = read()
    if not hb or not hb.get("updated_utc"):
        return None
    try:
        updated = datetime.fromisoformat(hb["updated_utc"])
    except Exception:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - updated).total_seconds()


def clear() -> None:
    """Remove the heartbeat — called when a cycle ends cleanly, so a finished
    cycle is never mistaken for a hung one."""
    try:
        HEARTBEAT_PATH.unlink(missing_ok=True)
    except Exception:
        pass
