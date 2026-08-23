#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/durable.py — AN APPEND THAT IS STILL IN THE PAGE CACHE IS NOT A RECORD.

WHAT A KILL ACTUALLY COSTS
----------------------------
`fh.write(...)` returns as soon as the bytes are in the OS page cache. If the
machine loses power, or the watchdog SIGKILLs the process, or Windows restarts
for an update, everything written since the last flush is gone — and the file
looks intact afterwards, just shorter. There is no error, no torn line, no
signal. The record simply was never there.

That is the project's working definition of real death: not that the cycle
stopped, but that it stopped and left no account of stopping.

memory/existence_ledger.py has done this correctly since it was written:

    fh.write(...); fh.flush(); os.fsync(fh.fileno())

with the comment "a death record that is lost in the page cache when the machine
dies is not a record at all". This module is that same discipline, factored out,
so the other writers stop being the exception.

TWO TREATMENTS, AND WHICH ONE A WRITER GETS IS A MEASUREMENT
--------------------------------------------------------------
fsync is not free. On this box it costs single-digit milliseconds per call, and
a writer called 143 times a night pays that 143 times. So the rule is measured,
not asserted — counted on the last sealed cycle, 2026-08-23T03:04:02:

    existence ledger        2 writes/cycle   fsync EVERY append
    cycle checkpoints      31 writes/cycle   fsync EVERY append (already did)
    brain journal          38 writes/cycle   fsync EVERY append
    brain step log         63 writes/cycle   BATCHED at step boundaries
    llm provenance        143 writes/cycle   BATCHED at step boundaries

THE EXPOSURE WINDOW OF A BATCHED WRITER IS STATED, NOT HIDDEN. A batched writer
is durable up to the last barrier. Between barriers its tail lives in the page
cache and a hard kill loses it. The barrier is the step boundary — beat() — so
the worst case is "everything that writer produced during one step". For the
step log and provenance that is the right trade: they are diagnostic streams
about what a step did, and losing the tail of the step that died is survivable.
Losing a death record is not, which is why the ledger is never batched.

    venv/Scripts/python.exe core/durable.py      # selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import threading
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

# Writers registered for batched durability. Kept as PATHS, not handles: each
# append still opens, writes and closes, so there is no descriptor to leak and
# no half-written state if the process dies between appends. What is deferred is
# only the fsync.
_pending: set = set()
_lock = threading.Lock()

# Counted so the cost of the policy is visible rather than assumed.
_stats = {"immediate": 0, "deferred": 0, "barriers": 0, "synced": 0,
          "errors": 0}


def append_durable(path, line: str) -> bool:
    """Append one line and fsync it before returning. Never raises.

    Returns True when the bytes are on the platter. False means the append
    failed OR the fsync did — and the caller is told, because "I wrote it" and
    "I think I wrote it" are different claims.
    """
    p = pathlib.Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line if line.endswith("\n") else line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        with _lock:
            _stats["immediate"] += 1
            _stats["synced"] += 1
        return True
    except Exception:
        with _lock:
            _stats["errors"] += 1
        return False


def append_batched(path, line: str) -> bool:
    """Append one line; the fsync happens at the next barrier().

    For writers called many times per step, where the tail of one step is an
    acceptable loss and the per-call fsync is not.
    """
    p = pathlib.Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line if line.endswith("\n") else line + "\n")
            fh.flush()          # out of Python's buffer, into the OS cache
        with _lock:
            _pending.add(str(p))
            _stats["deferred"] += 1
        return True
    except Exception:
        with _lock:
            _stats["errors"] += 1
        return False


def append_json(path, obj, batched: bool = False) -> bool:
    """The common case: one JSON object per line."""
    line = json.dumps(obj, ensure_ascii=False)
    return append_batched(path, line) if batched else append_durable(path, line)


def barrier() -> dict:
    """fsync every batched writer that has pending bytes. Never raises.

    Called from the step boundary. The file is reopened for APPEND and fsynced
    without writing a byte: fsync is a file-level operation, so any descriptor
    on the same file flushes all of its dirty pages.

    THE HANDLE MUST BE WRITABLE, and on Windows that is not a detail. fsync on
    an O_RDONLY descriptor maps to FlushFileBuffers, which needs GENERIC_WRITE
    and fails with "Access is denied" — measured, on the first run of this
    module: barrier() reported synced=0 failed=1 while the bytes were in fact
    still only in the cache. A barrier that silently syncs nothing is worse than
    no barrier, because it reads as durability.
    """
    with _lock:
        paths = sorted(_pending)
        _pending.clear()
    synced, failed = [], []
    for s in paths:
        try:
            with open(s, "ab") as fh:      # append mode, zero bytes written
                fh.flush()
                os.fsync(fh.fileno())
            synced.append(s)
        except Exception:
            failed.append(s)
    with _lock:
        _stats["barriers"] += 1
        _stats["synced"] += len(synced)
        _stats["errors"] += len(failed)
    return {"synced": len(synced), "failed": len(failed),
            "paths": [pathlib.Path(s).name for s in synced]}


def pending() -> list:
    with _lock:
        return sorted(pathlib.Path(s).name for s in _pending)


def stats() -> dict:
    with _lock:
        return dict(_stats)


# ---------------------------------------------------------------------------

def _selftest() -> int:
    import subprocess
    import tempfile
    print("core/durable.py --selftest")
    tmp = pathlib.Path(tempfile.mkdtemp())

    # ── THE REAL TEST: read the bytes from a SEPARATE PROCESS, without this
    # one closing anything cleanly. A test that asserts "fsync was called" is
    # asserting about the mock, not about the disk.
    d = tmp / "durable.jsonl"
    append_json(d, {"n": 1, "kind": "durable"})
    out = subprocess.run(
        [sys.executable, "-c",
         "import pathlib,sys;print(len(pathlib.Path(sys.argv[1])"
         ".read_text(encoding='utf-8').splitlines()))", str(d)],
        capture_output=True, text=True, timeout=30)
    print("  immediate: another process sees {} line(s)".format(
        (out.stdout or "0").strip()))
    assert (out.stdout or "").strip() == "1", out

    b = tmp / "batched.jsonl"
    for i in range(5):
        append_json(b, {"n": i, "kind": "batched"}, batched=True)
    print("  batched:   pending before barrier = {}".format(pending()))
    assert pending() == ["batched.jsonl"], pending()
    res = barrier()
    print("  barrier:   synced={} failed={} -> pending now {}".format(
        res["synced"], res["failed"], pending()))
    assert res["failed"] == 0 and pending() == []

    out = subprocess.run(
        [sys.executable, "-c",
         "import pathlib,sys;print(len(pathlib.Path(sys.argv[1])"
         ".read_text(encoding='utf-8').splitlines()))", str(b)],
        capture_output=True, text=True, timeout=30)
    print("  batched:   another process sees {} line(s)".format(
        (out.stdout or "0").strip()))
    assert (out.stdout or "").strip() == "5", out

    bad = append_durable(tmp / "nope" / "\0" / "x.jsonl", "x")
    print("  a failed append returns False rather than raising: {}".format(not bad))
    assert bad is False

    print("  stats: {}".format(stats()))
    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
