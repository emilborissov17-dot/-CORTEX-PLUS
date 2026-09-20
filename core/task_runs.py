#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_runs.py — two rows per run, so a job that dies halfway is visible.

WHY (20 September 2026)
-----------------------
scripts/openclaw_axis_worker.py grew a start/finish log when it was first
scheduled, because a worker that simply stops is invisible in a log that only
records successes. Ten minutes later core/card_intake.py needed the same thing,
and the repo's own rule is to look before writing a second one. So the
implementation moved here and both callers import it; the worker keeps its old
names as thin wrappers, which is what lets its existing tests go on asking the
same questions.

WHAT MAKES A RUN "UNFINISHED"
-----------------------------
A start row with no finish row for the SAME (task, run_id). A process killed by
a reboot, an OOM or a closed lid writes the first and never the second, and the
absent row is the whole signal.

THE PAIR IS (task, run_id), NOT run_id ALONE, and that is not tidiness. A chain
gives its steps ONE run_id on purpose — tools/openclaw_chain.bat exports
CORTEX_RUN_ID so the fetch and the judge can be read as one event. Keyed on
run_id alone, a chain whose worker finished and whose judge died would show a
start and a finish for that id and read as complete: the half-dead chain, hidden
by the very field meant to make it legible.

FAIL-OPEN ON WRITE, FAIL-CLOSED ON READ. A log that cannot be written must not
cost the run it describes, so row() swallows OSError. unfinished() skips a torn
final line rather than giving up on the file — a half-written line is exactly
what a killed process leaves, and losing the file at that moment would lose the
one run worth seeing.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
LOG = BASE / "memory" / "task_runs.jsonl"

# The chain sets this so its steps share one id. A step run on its own does not
# see it and mints its own, which is correct: it IS its own event then.
RUN_ID_ENV = "CORTEX_RUN_ID"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id(task: str) -> str:
    """The id for this run: the chain's, if we are in one, else a fresh one."""
    shared = os.environ.get(RUN_ID_ENV, "").strip()
    if shared:
        return shared[:64]
    return hashlib.sha256(
        f"{task}|{_now()}|{os.getpid()}".encode("utf-8")).hexdigest()[:12]


def row(task: str, event: str, rid: str, path: Path | None = None, **extra) -> None:
    """Append one row. Never raises."""
    rec = {"task": task, "event": event, "run_id": rid, "ts": _now(),
           "pid": os.getpid()}
    rec.update(extra)
    try:
        p = path or LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def unfinished(task: str | None = None, path: Path | None = None) -> list:
    """Start rows with no matching finish, oldest first.

    `task=None` asks about every task in the file, which is what a reader
    wanting "did anything die last night" needs.
    """
    p = path or LOG
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    started: dict = {}
    finished: set = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue                  # a torn final line is not a lost run
        t = rec.get("task")
        if task is not None and t != task:
            continue
        key = (t, rec.get("run_id"))
        if rec.get("event") == "start":
            started.setdefault(key, rec)
        elif rec.get("event") == "finish":
            finished.add(key)
    return [r for k, r in started.items() if k not in finished]


def announce(task: str, path: Path | None = None) -> list:
    """Print any run that never came back, and return them.

    Called at the top of a run, so the FIRST thing a job says is whether the
    last one finished.
    """
    stale = unfinished(task, path)
    for s in stale:
        print(f"[{task}] PREVIOUS RUN NEVER FINISHED: started {s.get('ts')} "
              f"(run_id {s.get('run_id')}) — killed, rebooted or crashed before "
              f"it could write a finish row")
    return stale


# ── SELFTEST ────────────────────────────────────────────────────────────────

def selftest() -> dict:
    rep = {"log": str(LOG.relative_to(BASE)), "exists": LOG.exists(),
           "integrations": {}}
    for mod, rel in (("scripts.openclaw_axis_worker",
                      "scripts/openclaw_axis_worker.py"),
                     ("core.card_intake", "core/card_intake.py")):
        try:
            src = (BASE / rel).read_text(encoding="utf-8")
            rep["integrations"][mod] = ("LIVE - writes run rows"
                                        if "task_runs" in src else
                                        "INERT - does not use this module")
        except OSError as exc:
            rep["integrations"][mod] = f"INERT - {exc}"
    rep["unfinished_now"] = unfinished()
    return rep


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"unfinished": unfinished()}, ensure_ascii=False, indent=1))
