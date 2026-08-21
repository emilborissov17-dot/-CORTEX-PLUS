#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_checkpoint.py — WHICH STEPS ACTUALLY FINISHED, WRITTEN DOWN AS THEY FINISH.

THE GAP THIS FILLS
------------------
Nothing in this repo records a step COMPLETING.

  * memory/existence_ledger.py records cycle-scoped events only — CYCLE_STARTED,
    CYCLE_FINISHED, CYCLE_KILLED, CYCLE_DIED and friends. A step name enters the
    ledger exactly once: as the forensic field `wedged_step` on record_kill() /
    record_death(). A step that finishes normally leaves NO ledger trace.
  * memory/heartbeat.json holds the step CURRENTLY running and is overwritten in
    place (tmp + os.replace). It is a position, not a history.

So after a crash there is no artifact that answers "which of the 55 steps had
already completed?". heartbeat._last_step_in_log() approximates it by grepping
`[STEP]` lines out of the newest cycle log — a text scan over a log that may have
been truncated by the very kill we are recovering from.

This module records completions, append-only, so the answer is a read instead of
a reconstruction. It is ADDITIVE: it does not replace, wrap or write to the
existence ledger, and the ledger stays the sole authority on cycle-level truth.

WHY memory/cycle_resume.json AND NOT memory/cycle_checkpoint.json
-----------------------------------------------------------------
memory/web_intelligence/cycle_checkpoint.json already exists and means something
ELSE: which axes the web_intelligence step has got through, INSIDE one step. Two
files one directory apart, same name, different scope, is a trap for whoever reads
them next — so the cycle-level one is named for what it is FOR.

RESUME IS OFF UNTIL SOMEONE TYPES --resume
-------------------------------------------
decide_resume() defaults `enabled=False` and returns start_index 0. Resuming is a
claim that earlier steps left their work behind, and that claim can be false in a
way that is worse than re-running: scoring reads yesterday's snapshots and stamps
them with today's date. core/phase_resume.py already checks EXISTS + BELONGS per
declared artifact, at phase granularity, and refuses by name. This module does NOT
duplicate that check — it takes it as an injected `artifact_check` hook, so the two
compose instead of disagreeing.

    venv\\Scripts\\python.exe core/cycle_checkpoint.py --selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

LOG_NAME = "cycle_resume.jsonl"      # append-only, every completion
LATEST_NAME = "cycle_resume.json"    # pointer to the newest completion


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(base: Optional[pathlib.Path]) -> tuple:
    root = (base or BASE) / "memory"
    return root / LOG_NAME, root / LATEST_NAME


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def record_step_complete(cycle_id: str, step: str, step_index,
                         base: Optional[pathlib.Path] = None) -> dict:
    """Called AFTER a step returns without raising. Appends, then repoints latest.

    Order matters and is not arbitrary. The append happens first and is fsynced
    before the pointer moves, so a power cut between the two leaves a log that is
    AHEAD of the pointer — recoverable, and wrong in the safe direction (we resume
    from an earlier step than we could have). The reverse order would leave a
    pointer naming a completion with no record behind it.
    """
    log_path, latest_path = _paths(base)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "cycle_id": cycle_id,
        "last_completed_step": step,
        "step_index": str(step_index),
        "ts": _now(),
    }

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    _write_latest_atomic(latest_path, record)
    return record


def _write_latest_atomic(path: pathlib.Path, payload: dict) -> None:
    """tmp + fsync + os.replace — atomic on Windows and POSIX alike.

    HONEST LIMIT: the DIRECTORY entry is not fsynced. On Windows there is no
    portable way to do it (a directory cannot be opened as a file descriptor), so
    a power cut can in principle lose the rename even with the bytes on disk. The
    append-before-pointer ordering above is what makes that survivable — it is not
    a claim that it cannot happen.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def latest(base: Optional[pathlib.Path] = None) -> Optional[dict]:
    """The newest completion, from the pointer; falls back to the log's tail.

    The fallback is the other half of the write ordering. If the pointer is
    missing or corrupt but the log is intact, the log wins: a checkpoint system
    that gives up because its convenience file is unreadable has thrown away the
    record it actually kept.
    """
    log_path, latest_path = _paths(base)
    try:
        data = json.loads(latest_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("last_completed_step"):
            return data
    except Exception:
        pass
    return _tail_of_log(log_path)


def _tail_of_log(log_path: pathlib.Path) -> Optional[dict]:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue          # a torn last line is skipped, not fatal
        if isinstance(data, dict) and data.get("last_completed_step"):
            return data
    return None


def completed_steps(cycle_id: str, base: Optional[pathlib.Path] = None) -> list:
    """Every step this cycle_id recorded as complete, in the order recorded."""
    log_path, _ = _paths(base)
    out: list = []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get("cycle_id") == cycle_id and data.get("last_completed_step"):
            out.append(data["last_completed_step"])
    return out


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

@dataclass
class ResumeDecision:
    resume: bool
    start_index: int
    reason: str
    completed_through: Optional[str] = None
    skipped_steps: tuple = ()

    def as_dict(self) -> dict:
        return asdict(self)


def decide_resume(cycle_id: str,
                  steps: list,
                  checkpoint: Optional[dict],
                  cycle_finished: bool,
                  enabled: bool = False,
                  artifact_check: Optional[Callable] = None) -> ResumeDecision:
    """Pure. Given a checkpoint and whether that cycle sealed, where do we start?

    `steps` is the ordered list of step NAMES (core.cycle_map.STEPS names).
    `cycle_finished` is the caller's answer from existence_ledger.has_finished(),
    passed in rather than probed so this stays pure and the ledger keeps one reader.
    `artifact_check(step) -> str | None` returns a refusal REASON when the artifacts
    the completed prefix promised are not on disk; core/phase_resume.py is the
    intended implementation. None means "no objection".

    Every declining path returns start_index 0. Declining always means "run the
    whole cycle", never "run some of it and hope".
    """
    if not enabled:
        return ResumeDecision(False, 0,
                              "resume not requested (--resume is OFF by default)")

    if not checkpoint:
        return ResumeDecision(False, 0, "no checkpoint on disk")

    ck_cycle = checkpoint.get("cycle_id")
    if ck_cycle != cycle_id:
        return ResumeDecision(
            False, 0,
            "checkpoint belongs to another cycle "
            "({!r}, not {!r})".format(ck_cycle, cycle_id))

    if cycle_finished:
        return ResumeDecision(
            False, 0,
            "that cycle already recorded CYCLE_FINISHED — there is nothing to resume")

    step = checkpoint.get("last_completed_step")
    if step not in steps:
        return ResumeDecision(
            False, 0,
            "checkpoint names step {!r}, which is not in this cycle's "
            "step list".format(step))

    idx = steps.index(step)

    if artifact_check is not None:
        refusal = artifact_check(step)
        if refusal:
            return ResumeDecision(False, 0,
                                  "artifact check refused: {}".format(refusal))

    start = idx + 1
    if start >= len(steps):
        return ResumeDecision(
            True, len(steps),
            "every step completed but the cycle never sealed — nothing left to run",
            completed_through=step, skipped_steps=tuple(steps))

    return ResumeDecision(
        True, start,
        "resuming at step {} ({!r}); {} step(s) already completed "
        "in this cycle".format(start, steps[start], start),
        completed_through=step, skipped_steps=tuple(steps[:start]))


# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Reports which integrations are LIVE and which are INERT in THIS repo."""
    print("core/cycle_checkpoint.py --selftest")
    print("  repo base            {}".format(BASE))

    log_path, latest_path = _paths(None)
    print("  log                  {}  exists={}".format(log_path, log_path.exists()))
    print("  latest               {}  exists={}".format(latest_path,
                                                        latest_path.exists()))
    ok = True

    try:
        from core.cycle_map import STEPS
        print("  cycle_map            LIVE ({} steps declared)".format(len(STEPS)))
    except Exception as e:
        print("  cycle_map            INERT ({}: {})".format(type(e).__name__, e))
        ok = False

    try:
        from memory.existence_ledger import has_finished  # noqa: F401
        print("  existence_ledger     LIVE (has_finished available)")
    except Exception as e:
        print("  existence_ledger     INERT ({}: {})".format(type(e).__name__, e))
        ok = False

    try:
        from core.phase_resume import verify_or_refuse  # noqa: F401
        print("  phase_resume         LIVE (artifact_check hook available)")
    except Exception as e:
        print("  phase_resume         INERT ({}: {})".format(type(e).__name__, e))

    # The integration that matters most, and the one that is honestly not done.
    try:
        runner = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                           errors="replace")
        wired = "cycle_checkpoint" in runner
    except OSError:
        wired = False
    if wired:
        print("  fast_cycle_runner    WIRED")
    else:
        print("  fast_cycle_runner    NOT WIRED — nothing calls "
              "record_step_complete(); this module records nothing yet")

    steps = ["a", "b", "c"]
    ck = {"cycle_id": "c1", "last_completed_step": "b"}
    d = decide_resume("c1", steps, ck, cycle_finished=False, enabled=True)
    assert d.resume and d.start_index == 2, d
    d = decide_resume("c1", steps, ck, cycle_finished=False, enabled=False)
    assert not d.resume and d.start_index == 0, d
    print("  pure-decision smoke  OK")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
