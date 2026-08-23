#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unclean_stop.py — WHAT A KILL COST, WRITTEN DOWN BY THE SYSTEM ITSELF.

THE GAP
--------
Right now, on this machine, memory/heartbeat.json says:

    pid 80336, cycle 2026-08-23T06:14:11, step cognitive_orchestrator, 12.7

That pid is dead. That cycle never wrote an end record. The heartbeat is nearly
five hours stale. And NOTHING IN THE REPOSITORY HAS NOTICED — because the one
place that combines "pid is not alive" with "no CYCLE_FINISHED" is
supervisor.py:1529, and it is gated on `if lock` — a stale LOCK file. When the
process dies and the lock is gone or was never taken, the heartbeat is the only
witness left and nobody reads it.

So the system has been losing time it cannot account for. This module is the
accounting.

WHY IT IS A LEDGER RECORD AND NOT A LOG LINE
----------------------------------------------
The existence ledger is the hash-chained history of what this system has been
through. A kill is exactly that kind of fact. A log line is deleted by the next
log rotation; a ledger record is chained, append-only, and survives.

ABSENCE IS THE SIGNAL. If the previous stop WAS clean, nothing is written. A
ledger with no RESTART_AFTER_UNCLEAN_STOP between two cycles is a statement that
the first one ended properly — and that statement is only worth anything if the
record is never written speculatively.

IT RUNS ONCE, AT THE TOP OF BOOT, AND NEVER RAISES.

    venv/Scripts/python.exe core/unclean_stop.py         # report, writes nothing
    venv/Scripts/python.exe core/unclean_stop.py --check # would it record?
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

HEARTBEAT = BASE / "memory" / "heartbeat.json"

EVENT = "RESTART_AFTER_UNCLEAN_STOP"

# Terminal events. Any of these for a cycle_id means that cycle's ending is
# already on the record and this module has nothing to add — including the
# unclean ones, because a CYCLE_DIED written by the supervisor is an account of
# the same stop and a second record would double-count it.
END_EVENTS = ("CYCLE_FINISHED", "CYCLE_DIED", "CYCLE_KILLED",
              "CYCLE_FAILED_BUDGET_EXHAUSTED",
              # A cycle the survival gate refused to start is the cleanest stop
              # there is: it was a decision, not a death. Without this entry
              # tomorrow's boot would report tonight's refusal as a crash and
              # bill it 8 hours of "lost" duration.
              "CYCLE_REFUSED_SURVIVAL_GATE", EVENT)


def _parse(ts) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _pid_alive(pid) -> bool:
    """True only if we can positively establish the process exists.

    UNKNOWN COUNTS AS ALIVE. If psutil is missing and os.kill cannot answer, the
    honest reading is "we cannot say it is dead", and recording an unclean stop
    for a process that is still running would be a false entry in the one file
    that must not carry them.
    """
    try:
        pid = int(pid)
    except Exception:
        return False              # a heartbeat with no readable pid names nobody
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    try:
        import os
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True               # exists, owned by somebody else
    except Exception:
        return True               # cannot tell -> do not claim it is dead


def _read_heartbeat(path: Optional[pathlib.Path] = None) -> Optional[dict]:
    try:
        blob = json.loads(pathlib.Path(path or HEARTBEAT).read_text(
            encoding="utf-8"))
        return blob if isinstance(blob, dict) else None
    except Exception:
        return None


def _cycle_has_end_record(cycle_id, ledger_path=None) -> bool:
    """Did anything already record how this cycle ended?"""
    if not cycle_id:
        return False
    from memory import existence_ledger as led
    path = pathlib.Path(ledger_path or led.LEDGER_PATH)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("cycle_id") == cycle_id and \
                str(row.get("event", "")).upper() in END_EVENTS:
            return True
    return False


def assess(heartbeat_path=None, ledger_path=None, now=None) -> dict:
    """Was the previous stop unclean? Pure — decides, writes nothing."""
    now = now or datetime.now(timezone.utc)
    hb = _read_heartbeat(heartbeat_path)
    out = {"unclean": False, "why": "", "heartbeat": hb}

    if not hb:
        out["why"] = "no heartbeat on disk — nothing claims a cycle was running"
        return out
    if hb.get("retired_utc"):
        out["why"] = "the heartbeat was retired, which is a clean handover"
        return out

    pid = hb.get("pid")
    if _pid_alive(pid):
        out["why"] = "pid {} is alive — that cycle is not over".format(pid)
        return out

    cycle_id = hb.get("cycle_id")
    if _cycle_has_end_record(cycle_id, ledger_path):
        out["why"] = ("cycle {} already has an end record — its ending is "
                      "accounted for".format(cycle_id))
        return out

    last = _parse(hb.get("updated_utc")) or _parse(hb.get("step_started_utc"))
    lost = None if last is None else max(0.0, (now - last).total_seconds())

    out.update({
        "unclean": True,
        "why": ("pid {} is gone and cycle {} has no end record"
                .format(pid, cycle_id)),
        "cycle_id": cycle_id,
        "last_heartbeat_utc": hb.get("updated_utc"),
        "last_step": hb.get("step"),
        "last_step_index": hb.get("step_index"),
        "lost_duration_seconds": None if lost is None else round(lost, 1),
    })
    return out


def record(heartbeat_path=None, ledger_path=None, now=None) -> Optional[dict]:
    """Write ONE ledger record if the previous stop was unclean. Never raises.

    Returns the written event, or None when there was nothing to record — which
    is the ordinary case and is not a failure.
    """
    try:
        verdict = assess(heartbeat_path, ledger_path, now)
        if not verdict["unclean"]:
            return None
        from memory import existence_ledger as led
        if ledger_path is not None:
            led.LEDGER_PATH = pathlib.Path(ledger_path)
        return led.append(
            EVENT,
            cycle_id=verdict.get("cycle_id"),
            last_heartbeat_utc=verdict.get("last_heartbeat_utc"),
            last_step=verdict.get("last_step"),
            last_step_index=verdict.get("last_step_index"),
            lost_duration_seconds=verdict.get("lost_duration_seconds"),
            detail=verdict.get("why"),
            recorded_by="core/unclean_stop.py",
        )
    except Exception as exc:                            # noqa: BLE001
        print("[UNCLEAN_STOP] could not record: {}: {}".format(
            type(exc).__name__, exc))
        return None


# ---------------------------------------------------------------------------

def _report() -> int:
    """Read-only. Says what it WOULD record, and records nothing."""
    print("core/unclean_stop.py — read-only report")
    print("  heartbeat: {}".format(HEARTBEAT))
    v = assess()
    hb = v.get("heartbeat") or {}
    if hb:
        print("    pid           {}  alive={}".format(
            hb.get("pid"), _pid_alive(hb.get("pid"))))
        print("    cycle_id      {}".format(hb.get("cycle_id")))
        print("    step          {} ({})".format(hb.get("step"),
                                                 hb.get("step_index")))
        print("    updated_utc   {}".format(hb.get("updated_utc")))
        print("    end record?   {}".format(
            _cycle_has_end_record(hb.get("cycle_id"))))
    print()
    if v["unclean"]:
        print("  VERDICT: UNCLEAN STOP")
        print("    {}".format(v["why"]))
        print("    lost_duration_seconds = {} ({:.1f} minutes)".format(
            v["lost_duration_seconds"],
            (v["lost_duration_seconds"] or 0) / 60.0))
        print()
        print("  It WOULD append one {} record. Nothing was written by this "
              "report.".format(EVENT))
    else:
        print("  VERDICT: nothing to record")
        print("    {}".format(v["why"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_report())
