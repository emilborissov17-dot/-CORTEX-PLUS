#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_reaper_records_its_own_death.py — THE WATCHER MUST LEAVE A MARK TOO.

WHAT WENT WRONG (measured 20 August 2026)
------------------------------------------
There is a memory/cycle_exit.json for the 17:05 cycle and NONE for the 17:59
one. Both had a reaper; the supervisor logged it starting:

    [14:59:34] reaper 66488 watching cycle pid 66320

The 17:59 reaper never wrote anything. Everything in reap() used to happen
AFTER wait_for_exit() returned, so a reaper that died during the wait wrote
nothing at all — and its silence was indistinguishable from a reaper that was
never started. Two processes died together and the surviving evidence said only
that one of them had been alive at some point.

THE FIX AND WHY IT IS SHAPED THIS WAY
--------------------------------------
The record is opened at the START in state WATCHING and closed at the end in
state RECORDED. A reaper cannot be relied upon to report its own death — a
process killed outright runs no handler — so the evidence has to be on disk
BEFORE the death, not written in response to it. A WATCHING record left behind
is then itself the finding: the watcher did not outlive the watched.

Two weaker signals ride alongside, and neither is load-bearing:
  * an atexit line, which catches an orderly exit but not a kill;
  * the NEXT reaper noticing an orphaned WATCHING record for another cycle.

THE NEGATIVE CONTROL
---------------------
test_a_reaper_killed_mid_wait_leaves_its_watching_record kills the reaper while
it waits. Move the provisional write back to after wait_for_exit() — where it
used to be — and the file is absent, exactly as it was for the 17:59 cycle.

Everything here writes to tmp_path via --exit-record and --night-log. Nothing
touches memory/cycle_exit.json or memory/night_events.jsonl, which is the point
of those flags existing (see the 16 Aug 2026 incident note in cycle_reaper.py).

    venv\\Scripts\\python.exe -m pytest test/test_reaper_records_its_own_death.py -v
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _spawn_victim(seconds: int = 120) -> subprocess.Popen:
    """A process for the reaper to watch."""
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, cwd=str(REPO),
    )


def _spawn_reaper(pid: int, cycle_id: str, exit_record: pathlib.Path,
                  night_log: pathlib.Path, settle: float = 0.5) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "memory.cycle_reaper",
         "--pid", str(pid), "--cycle-id", cycle_id,
         "--exit-record", str(exit_record), "--night-log", str(night_log),
         "--settle-sec", str(settle)],
        cwd=str(REPO),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def _wait_for_file(path: pathlib.Path, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass  # mid-write; the writer is atomic but the read can race
        time.sleep(0.1)
    raise AssertionError(f"{path} never appeared within {timeout}s")


def _night_lines(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


# ---------------------------------------------------------------------------
# (a) THE NEGATIVE CONTROL
# ---------------------------------------------------------------------------

def test_a_reaper_killed_mid_wait_leaves_its_watching_record(tmp_path):
    """Kill the watcher, not the watched. Something must remain on disk.

    Move the provisional write back to after wait_for_exit() and this fails with
    an empty tmp_path — which is precisely what the 17:59 cycle left behind.
    """
    record = tmp_path / "cycle_exit.json"
    night = tmp_path / "night_events.jsonl"
    victim = _spawn_victim()
    reaper = _spawn_reaper(victim.pid, "CYCLE-A", record, night)

    try:
        opened = _wait_for_file(record)
        assert opened["state"] == "WATCHING", (
            f"\n  THE REAPER WROTE NOTHING BEFORE WAITING.\n"
            f"  A reaper that dies during the wait would leave no trace at all,\n"
            f"  which is exactly what happened to the 17:59 cycle: a reaper was\n"
            f"  logged as started and no cycle_exit.json ever appeared.\n"
            f"  Got: {opened}\n"
        )
        assert opened["pid"] == victim.pid
        assert opened["cycle_id"] == "CYCLE-A"
        # NOT reaper.pid: venv/Scripts/python.exe is a LAUNCHER STUB that
        # re-launches the real interpreter under a different pid (documented in
        # cycle_reaper.py, measured 17 Aug 2026). Popen.pid names the stub; the
        # record carries os.getpid() of the interpreter that actually runs.
        # Asserting they are equal fails for a reason that is not a defect.
        assert isinstance(opened["reaper_pid"], int)
        assert opened["reaper_pid"] != victim.pid
        real_reaper_pid = opened["reaper_pid"]

        reaper.kill()
        reaper.wait(timeout=30)

        left = json.loads(record.read_text(encoding="utf-8"))
        assert left["state"] == "WATCHING", (
            "the reaper was killed mid-wait and the record no longer says so"
        )
        assert left["reaper_pid"] == real_reaper_pid
    finally:
        victim.kill()
        victim.wait(timeout=30)
        if reaper.poll() is None:
            reaper.kill()


def test_a_reaper_that_outlives_the_cycle_closes_the_record(tmp_path):
    """POSITIVE CONTROL. WATCHING must become RECORDED, or the state is noise."""
    record = tmp_path / "cycle_exit.json"
    night = tmp_path / "night_events.jsonl"
    victim = _spawn_victim()
    reaper = _spawn_reaper(victim.pid, "CYCLE-B", record, night)

    try:
        assert _wait_for_file(record)["state"] == "WATCHING"
        victim.kill()
        victim.wait(timeout=30)
        reaper.wait(timeout=60)

        final = json.loads(record.read_text(encoding="utf-8"))
        assert final["state"] == "RECORDED", final
        assert final["cycle_id"] == "CYCLE-B"
        assert final["exit_code"] is not None, "the whole point is the integer"
        assert "ended_by" in final
    finally:
        if victim.poll() is None:
            victim.kill()
        if reaper.poll() is None:
            reaper.kill()


# ---------------------------------------------------------------------------
# (b) A vanished reaper is an event the next one reports
# ---------------------------------------------------------------------------

def test_the_next_reaper_reports_a_predecessor_that_vanished(tmp_path):
    record = tmp_path / "cycle_exit.json"
    night = tmp_path / "night_events.jsonl"

    # A record left WATCHING by a reaper that died, for a different cycle.
    record.write_text(json.dumps({
        "ts": "2026-08-20T14:59:34+00:00", "cycle_id": "CYCLE-DEAD",
        "pid": 66320, "reaper_pid": 66488, "state": "WATCHING",
    }), encoding="utf-8")

    victim = _spawn_victim()
    reaper = _spawn_reaper(victim.pid, "CYCLE-NEXT", record, night)
    try:
        _wait_for_file(record)
        victim.kill(); victim.wait(timeout=30)
        reaper.wait(timeout=60)

        subjects = [l.get("subject", "") for l in _night_lines(night)]
        assert any("PREVIOUS REAPER VANISHED" in s for s in subjects), (
            f"an orphaned WATCHING record for another cycle was not reported. "
            f"night log said: {subjects}"
        )
        orphan = next(l for l in _night_lines(night)
                      if "PREVIOUS REAPER VANISHED" in l.get("subject", ""))
        assert orphan["cycle_id"] == "CYCLE-DEAD"
        assert orphan["reaper_pid"] == 66488
    finally:
        if victim.poll() is None:
            victim.kill()
        if reaper.poll() is None:
            reaper.kill()


def test_a_matching_watching_record_is_not_reported_as_orphaned(tmp_path):
    """A reaper restarted for the SAME cycle is not a vanished predecessor —
    otherwise every retry would cry wolf."""
    record = tmp_path / "cycle_exit.json"
    night = tmp_path / "night_events.jsonl"
    record.write_text(json.dumps({
        "ts": "2026-08-20T14:59:34+00:00", "cycle_id": "CYCLE-SAME",
        "pid": 1, "reaper_pid": 2, "state": "WATCHING",
    }), encoding="utf-8")

    victim = _spawn_victim()
    reaper = _spawn_reaper(victim.pid, "CYCLE-SAME", record, night)
    try:
        _wait_for_file(record)
        victim.kill(); victim.wait(timeout=30)
        reaper.wait(timeout=60)
        subjects = [l.get("subject", "") for l in _night_lines(night)]
        assert not any("PREVIOUS REAPER VANISHED" in s for s in subjects), subjects
    finally:
        if victim.poll() is None:
            victim.kill()
        if reaper.poll() is None:
            reaper.kill()


# ---------------------------------------------------------------------------
# (c) Shape
# ---------------------------------------------------------------------------

def test_the_provisional_record_explains_itself(tmp_path):
    """Whoever finds a WATCHING record at 03:00 should not have to read the
    source to know what it means."""
    record = tmp_path / "cycle_exit.json"
    night = tmp_path / "night_events.jsonl"
    victim = _spawn_victim()
    reaper = _spawn_reaper(victim.pid, "CYCLE-C", record, night)
    try:
        opened = _wait_for_file(record)
        assert "note" in opened
        assert "WATCHING" in opened["note"]
    finally:
        victim.kill(); victim.wait(timeout=30)
        if reaper.poll() is None:
            reaper.kill()
