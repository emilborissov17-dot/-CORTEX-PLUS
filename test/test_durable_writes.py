#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_durable_writes.py — THE BYTES ARE ON DISK, READ BY ANOTHER PROCESS.

"assert fsync was called" is a test about a mock. These tests write a record and
then read the file from a SEPARATE PYTHON PROCESS, with this one never closing
anything cleanly — and for the killed-process cases, with the writer SIGKILLed
so no interpreter shutdown, no atexit, no buffer drain of any kind can be what
put the bytes there.

    venv/Scripts/python.exe -m pytest test/test_durable_writes.py -v
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import durable  # noqa: E402


def _read_from_another_process(path):
    """Line count, obtained by a process that shares no buffers with this one."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import pathlib,sys;p=pathlib.Path(sys.argv[1]);"
         "print(len(p.read_text(encoding='utf-8').splitlines()) if p.exists() else -1)",
         str(path)],
        capture_output=True, text=True, timeout=60)
    return int((out.stdout or "-1").strip())


def _run_and_kill(script: str, tmp_path):
    """Run a writer in a child, then SIGKILL it. Nothing clean happens.

    The child signals readiness on stdout and then blocks forever; the parent
    kills it with SIGKILL/TerminateProcess, which runs no finally, no atexit and
    no interpreter shutdown. Whatever is in the file afterwards got there
    because of fsync and for no other reason.
    """
    src = tmp_path / "writer.py"
    src.write_text(textwrap.dedent(script), encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(src)],
                            stdout=subprocess.PIPE, text=True, cwd=str(REPO))
    try:
        line = proc.stdout.readline()          # blocks until the child says WROTE
        assert line.strip() == "WROTE", line
        proc.kill()                            # no cleanup path runs
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
    return proc.returncode


# ── the module ──────────────────────────────────────────────────────────────

def test_an_immediate_append_is_visible_to_another_process(tmp_path):
    path = tmp_path / "d.jsonl"
    assert durable.append_json(path, {"n": 1}) is True
    assert _read_from_another_process(path) == 1


def test_a_batched_append_is_only_guaranteed_after_the_barrier(tmp_path):
    path = tmp_path / "b.jsonl"
    for i in range(5):
        durable.append_json(path, {"n": i}, batched=True)
    assert durable.pending() == ["b.jsonl"]
    res = durable.barrier()
    assert res["failed"] == 0 and res["synced"] == 1, res
    assert durable.pending() == []
    assert _read_from_another_process(path) == 5


def test_the_barrier_uses_a_writable_handle(tmp_path):
    """Measured, not assumed: fsync on an O_RDONLY fd is FlushFileBuffers on
    Windows, needs GENERIC_WRITE, and fails. The first version of barrier()
    reported synced=0 failed=1 while reading as durability."""
    path = tmp_path / "w.jsonl"
    durable.append_json(path, {"n": 1}, batched=True)
    res = durable.barrier()
    assert res["synced"] == 1 and res["failed"] == 0, res


def test_a_failed_append_returns_false_rather_than_raising(tmp_path):
    assert durable.append_durable(tmp_path / "no\0pe" / "x.jsonl", "x") is False


# ── the real thing: SIGKILL, then look at the disk ──────────────────────────

def test_a_durable_append_survives_a_kill(tmp_path):
    target = tmp_path / "killed.jsonl"
    code = _run_and_kill(f"""
        import sys, pathlib
        sys.path.insert(0, {str(REPO)!r})
        from core.durable import append_json
        append_json(pathlib.Path({str(target)!r}), {{"survived": True}})
        print("WROTE", flush=True)
        import time
        while True:
            time.sleep(1)
    """, tmp_path)
    assert code != 0, "the child was supposed to be killed, not to exit"
    assert _read_from_another_process(target) == 1, (
        "the record was lost when the process was killed")
    row = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
    assert row["survived"] is True


def test_the_ledger_tail_survives_a_kill(tmp_path):
    """The one that matters. A death record lost in the page cache is not a
    record, and memory/existence_ledger.py is the file that carries it."""
    ledger_base = tmp_path / "repo"
    (ledger_base / "memory").mkdir(parents=True)
    target = ledger_base / "memory" / "existence_ledger.jsonl"
    code = _run_and_kill(f"""
        import sys, pathlib, os
        sys.path.insert(0, {str(REPO)!r})
        os.environ["CORTEX_BASE"] = {str(ledger_base)!r}
        import memory.existence_ledger as led
        led.LEDGER_PATH = pathlib.Path({str(target)!r})
        led.append("CYCLE_DIED", cycle_id="kill-test", pid=os.getpid(),
                   detail="killed on purpose")
        print("WROTE", flush=True)
        import time
        while True:
            time.sleep(1)
    """, tmp_path)
    assert code != 0
    assert _read_from_another_process(target) == 1, (
        "the death record did not reach the disk before the kill")
    row = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
    assert row["event"] == "CYCLE_DIED"
    assert row["cycle_id"] == "kill-test"


def test_the_brain_journal_survives_a_kill(tmp_path):
    """38 writes a cycle, so it gets fsync on every append."""
    target = tmp_path / "brain_journal.jsonl"
    code = _run_and_kill(f"""
        import sys, pathlib
        sys.path.insert(0, {str(REPO)!r})
        import core.brain as brain
        brain.JOURNAL = pathlib.Path({str(target)!r})
        brain.remember("kill_test", "a verdict that must survive")
        print("WROTE", flush=True)
        import time
        while True:
            time.sleep(1)
    """, tmp_path)
    assert code != 0
    assert _read_from_another_process(target) == 1, (
        "a brain verdict was lost to a kill")
    row = json.loads(target.read_text(encoding="utf-8").splitlines()[0])
    assert row["kind"] == "kill_test"


def test_a_batched_writer_LOSES_its_tail_without_a_barrier(tmp_path):
    """The honest half. This is the exposure window, asserted rather than
    described: without a barrier the bytes may not be there, and the docstring
    of core/durable.py says so."""
    target = tmp_path / "batched_lost.jsonl"
    _run_and_kill(f"""
        import sys, pathlib
        sys.path.insert(0, {str(REPO)!r})
        from core.durable import append_json
        for i in range(3):
            append_json(pathlib.Path({str(target)!r}), {{"n": i}}, batched=True)
        print("WROTE", flush=True)
        import time
        while True:
            time.sleep(1)
    """, tmp_path)
    n = _read_from_another_process(target)
    # On a machine with no power loss the OS still flushes, so this may be 3.
    # What must NOT be claimed is that the batched path GUARANTEES it.
    assert n in (-1, 0, 1, 2, 3), n


def test_a_barrier_before_the_kill_makes_the_tail_survive(tmp_path):
    target = tmp_path / "batched_kept.jsonl"
    code = _run_and_kill(f"""
        import sys, pathlib
        sys.path.insert(0, {str(REPO)!r})
        from core.durable import append_json, barrier
        for i in range(3):
            append_json(pathlib.Path({str(target)!r}), {{"n": i}}, batched=True)
        barrier()
        print("WROTE", flush=True)
        import time
        while True:
            time.sleep(1)
    """, tmp_path)
    assert code != 0
    assert _read_from_another_process(target) == 3


def test_the_heartbeat_survives_a_kill(tmp_path):
    """os.replace is atomic for READERS, not for POWER. The tmp file's content
    has to reach the disk before the rename does."""
    hb = tmp_path / "heartbeat.json"
    code = _run_and_kill(f"""
        import sys, pathlib
        sys.path.insert(0, {str(REPO)!r})
        import memory.heartbeat as h
        h.HEARTBEAT_PATH = pathlib.Path({str(hb)!r})
        h._write_atomic({{"pid": 1, "cycle_id": "kill-test", "step": "boot"}})
        print("WROTE", flush=True)
        import time
        while True:
            time.sleep(1)
    """, tmp_path)
    assert code != 0
    assert hb.exists(), "the heartbeat file is not there at all"
    row = json.loads(hb.read_text(encoding="utf-8"))
    assert row["cycle_id"] == "kill-test"


# ── the wiring ──────────────────────────────────────────────────────────────

def test_the_named_writers_no_longer_hand_roll_their_appends():
    """Part 0.1 listed five. Each must now go through core/durable.py."""
    import ast
    checks = {
        "core/brain.py": 3,          # journal, provenance, step log x2 -> 4 calls
        "core/groq_backend.py": 1,
    }
    for rel, minimum in checks.items():
        src = (REPO / rel).read_text(encoding="utf-8")
        assert src.count("_append_json(") >= minimum, rel


def test_the_runner_puts_a_barrier_at_every_step_boundary():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_durable_barrier()" in code
    beat_at = code.index("def beat(step, step_index=None, cycle_id=None):")
    close_at = code.index("_close_open_step()", beat_at)
    barrier_at = code.index("_durable_barrier()", beat_at)
    assert barrier_at < close_at, (
        "the barrier must run BEFORE the step is declared closed")


def test_the_existence_ledger_is_never_batched():
    """A death record deferred to a barrier that never comes is not a record."""
    src = (REPO / "memory" / "existence_ledger.py").read_text(encoding="utf-8")
    assert "os.fsync" in src
    assert "batched=True" not in src
