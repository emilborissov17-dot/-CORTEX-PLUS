"""The cycle's exit code must survive the cycle.

THE GAP (17 August 2026)
------------------------
A manually started cycle died three minutes in. The log ended mid-step with no
traceback, the heartbeat froze, and twelve minutes later the lock was cleared as
a "death". Four explanations survived the autopsy — an outside TerminateProcess
(exit 1), an access violation (0xC0000005), a SystemExit from a signal handler,
and a clean exit that failed to seal its record (0) — and NOTHING on disk could
separate them, because `spawn_cycle()` never waited on the child. Popen's handle,
the only object from which the number could ever be read, went out of scope when
the five-millisecond tick exited.

The cause turned out to be the first one: the PowerShell window that ran
`supervisor.py --run-now` was closed, the inherited console sent CTRL_CLOSE_EVENT,
and the cycle was terminated with no handler and no output. Both halves of that
are pinned here:

  * the cycle is spawned with DETACHED_PROCESS, so there is no console whose
    closing can kill a 90-minute run, and
  * a reaper records the exit code beside the heartbeat and in the night log,
    so the next time this happens the autopsy starts from an integer instead of
    from four hypotheses.

WHY THE POSITIVE CONTROL IS NOT OPTIONAL
----------------------------------------
"A non-zero exit leaves its code in the record" is satisfied perfectly by a
recorder that writes the constant 1 and never looks at the process. So the same
mechanism is shown producing 0 for a clean exit and 3 for a process that chose 3.
A record that cannot be wrong about the number is not evidence of anything.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import supervisor as sup
from memory import cycle_reaper as reaper
from memory import heartbeat as hb

PY = str(sup.PYTHON) if sup.PYTHON.exists() else sys.executable


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Every path the reaper or the supervisor could write, inside tmp_path.

    The reaper's own module constants are redirected too. In production it is a
    DETACHED process that no fixture can reach, which is exactly why the
    supervisor hands it these paths on the command line — but these tests call
    reap() in-process, where the constants are what it falls back to.
    """
    monkeypatch.setattr(reaper, "EXIT_RECORD", tmp_path / "cycle_exit.json")
    monkeypatch.setattr(reaper, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    monkeypatch.setattr(sup, "CYCLE_EXIT_PATH", tmp_path / "cycle_exit.json")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    return tmp_path


def _spawn_exiting(code: int, sleep: float = 0.2) -> subprocess.Popen:
    """A REAL process that really exits with `code`. Not a mock.

    A mocked process cannot tell us whether GetExitCodeProcess was called with a
    truncated handle, which is the mistake this module is one ctypes declaration
    away from making.
    """
    return subprocess.Popen(
        [PY, "-c", f"import sys,time; time.sleep({sleep}); sys.exit({code})"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)


def _night_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in
            path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# THE REQUIREMENT: a non-zero exit leaves its code in the record
# ---------------------------------------------------------------------------

def test_a_nonzero_exit_leaves_its_code_in_both_records(sandbox):
    """The whole point. A process that exits 3 must be findable as a 3."""
    proc = _spawn_exiting(3)
    try:
        rec = reaper.reap(proc.pid, cycle_id="exit-3", settle_sec=0.5)
    finally:
        proc.wait(timeout=30)

    assert rec["exit_code"] == 3, (
        f"the reaper lost the exit code: {rec}. This is the number that would "
        f"have ended the 17 Aug autopsy in one line.")
    assert rec["exit_code_hex"] == "0x00000003"

    # Sink 1 — beside the heartbeat.
    on_disk = json.loads((sandbox / "cycle_exit.json").read_text(encoding="utf-8"))
    assert on_disk["exit_code"] == 3
    assert on_disk["cycle_id"] == "exit-3"

    # Sink 2 — the night log, in the shape core/cycle_report.py reads.
    lines = _night_lines(sandbox / "night_events.jsonl")
    assert len(lines) == 1, f"expected exactly one night event, got {lines}"
    ev = lines[0]
    assert {"ts", "subject", "detail"} <= set(ev), (
        "core/cycle_report.py reads ts/subject/detail — a record it cannot "
        "render is a record the human never sees")
    assert ev["exit_code"] == 3
    assert "3" in ev["detail"]


def test_a_clean_exit_is_recorded_as_zero_and_not_as_a_death(sandbox):
    """POSITIVE CONTROL for the test above.

    A recorder that hardcoded a non-zero value, or that reported every ending as
    a death, would pass `test_a_nonzero_exit_leaves_its_code_in_both_records`
    without ever reading the process. Feed it a process that exits 0 and the
    record must change in BOTH fields — the number and the verdict.
    """
    proc = _spawn_exiting(0)
    try:
        rec = reaper.reap(proc.pid, cycle_id="exit-0", settle_sec=0.5)
    finally:
        proc.wait(timeout=30)

    assert rec["exit_code"] == 0, f"a clean exit was not recorded as 0: {rec}"
    assert rec["ended_by"] == "clean", (
        f"a cycle that exited 0 was filed as {rec['ended_by']!r}; the verdict "
        f"does not track the process")


def test_the_recorded_code_is_the_one_the_process_chose(sandbox):
    """Second positive control, on the number itself.

    Two processes, two different non-zero codes, one recorder. If the field were
    a constant — or the launcher stub swallowed the child's code and substituted
    its own — these two would come back the same.
    """
    seen = []
    for code in (3, 9):
        proc = _spawn_exiting(code)
        try:
            seen.append(reaper.reap(proc.pid, cycle_id=f"exit-{code}",
                                    settle_sec=0.5)["exit_code"])
        finally:
            proc.wait(timeout=30)
    assert seen == [3, 9], f"the recorder does not track the process: {seen}"


# ---------------------------------------------------------------------------
# THE SECOND REQUIREMENT: a kill and a death are different events
# ---------------------------------------------------------------------------

def _plant_heartbeat(step: str, cycle_id: str) -> None:
    """Write a heartbeat directly, without beat().

    beat() also calls core.brain.attend(), which makes a real HTTP call to a
    local model. This test is about process bookkeeping and has no business
    waiting on an LLM — and a test that quietly calls one is how the suite got
    to five minutes and stopped being run.
    """
    hb._write_atomic({"pid": 1234, "cycle_id": cycle_id, "step": step,
                      "step_index": "12", "step_started_utc": "2026-08-17T00:00:00+00:00",
                      "updated_utc": "2026-08-17T00:00:00+00:00"})


def test_a_watchdog_kill_is_not_recorded_as_a_death(sandbox):
    """Both end the process. They are opposite facts about the system.

    Until now the morning report spelled them the same way — "the cycle died" —
    so it could not be used to tell whether the watchdog was working at all. The
    kill is only distinguishable because the watchdog SIGNS the heartbeat; the
    reaper reads that signature after the process is gone.
    """
    _plant_heartbeat("web_intelligence", "killed-1")
    proc = _spawn_exiting(0, sleep=30)          # would exit 0 if left alone
    proc.kill()                                  # TerminateProcess — the watchdog's way
    hb.retire("wedged past its ceiling", by="supervisor:watchdog_kill",
              ended_cycle_id="killed-1", killed_by_watchdog=True, kill_landed=True)
    try:
        rec = reaper.reap(proc.pid, cycle_id="killed-1", settle_sec=2.0)
    finally:
        proc.wait(timeout=30)

    assert rec["ended_by"] == "watchdog_kill", (
        f"a kill was filed as {rec['ended_by']!r} — a kill and a death are not "
        f"the same event, and a ledger that cannot tell them apart cannot show "
        f"whether the watchdog is doing its job")
    assert rec["exit_code"] is not None, (
        "the code must be recorded even when we killed it ourselves — "
        "'we killed it' is not a reason to record less")
    assert rec["last_step"] == "web_intelligence", (
        "the exit record and the heartbeat are meant to be read together: the "
        "code says how it ended, the step says where")
    assert _night_lines(sandbox / "night_events.jsonl")[0]["subject"].endswith(
        "watchdog_kill")


def test_an_unsigned_death_is_not_promoted_to_a_kill(sandbox):
    """POSITIVE CONTROL for the classifier.

    A classifier that returned "watchdog_kill" whenever a heartbeat happened to
    be lying around would pass the test above. Same heartbeat, same non-zero
    exit, no signature — the verdict must fall back to the honest word.
    """
    _plant_heartbeat("web_intelligence", "unsigned-1")
    proc = _spawn_exiting(0, sleep=30)
    proc.kill()
    try:
        rec = reaper.reap(proc.pid, cycle_id="unsigned-1", settle_sec=0.5)
    finally:
        proc.wait(timeout=30)

    assert rec["ended_by"] == "death", (
        f"an unexplained ending was filed as {rec['ended_by']!r}; only a killer "
        f"that signs may be named, everything else is a death")


def test_a_heartbeat_from_another_cycle_does_not_explain_this_one(sandbox):
    """The signature must belong to THIS cycle.

    A stale retired heartbeat from yesterday's kill sitting on disk must not
    make today's unexplained death look accounted for.
    """
    _plant_heartbeat("scoring_engine", "yesterday")
    hb.retire("wedged", by="supervisor:watchdog_kill",
              ended_cycle_id="yesterday", killed_by_watchdog=True)
    proc = _spawn_exiting(0, sleep=30)
    proc.kill()
    try:
        rec = reaper.reap(proc.pid, cycle_id="today", settle_sec=0.5)
    finally:
        proc.wait(timeout=30)

    assert rec["ended_by"] == "death", (
        f"another cycle's kill was used to explain this one: {rec}")


# ---------------------------------------------------------------------------
# THE WIRING: the supervisor must actually start one, and the cycle must have
# no console to be killed through
# ---------------------------------------------------------------------------

def test_the_cycle_is_spawned_with_no_console_and_with_a_reaper(sandbox, monkeypatch):
    """What spawn_cycle actually passes to CreateProcess.

    CREATE_NEW_PROCESS_GROUP alone was NOT detachment: it stops Ctrl+C, but the
    child still inherited the launching console, and closing that window
    terminated a 90-minute run with no handler and no output. This asserts on the
    real call arguments rather than on the source text, because the comment
    explaining the flag and the flag itself are two different things.
    """
    calls = []

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))
            self.pid = 4242

    monkeypatch.setattr(sup.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(sup, "RUNNER", sandbox / "runner.py")

    assert sup.spawn_cycle("wiring-test") == 4242
    assert len(calls) == 2, (
        f"expected two spawns — the cycle and its reaper — got {len(calls)}")

    (_cycle_argv,), cycle_kw = calls[0]
    assert cycle_kw["stdin"] is subprocess.DEVNULL, (
        "a process with no console must not inherit a console's stdin")
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    if detached:
        assert cycle_kw["creationflags"] & detached, (
            "the cycle is still attached to the console that started it — "
            "closing that window kills it, which is the 17 Aug 2026 death")
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if detached and no_window:
        assert not (cycle_kw["creationflags"] & no_window), (
            "DETACHED_PROCESS and CREATE_NO_WINDOW are mutually exclusive — "
            "CreateProcess fails outright if both are set")

    (reaper_argv,), _ = calls[1]
    assert "memory.cycle_reaper" in reaper_argv
    assert "4242" in reaper_argv, "the reaper was not told which pid to watch"
    assert str(sandbox / "cycle_exit.json") in reaper_argv, (
        "the reaper was not handed the caller's exit-record path, so a "
        "sandboxed test cannot keep it out of live memory/")


@pytest.mark.skipif(os.name != "nt",
                    reason="the reaper waits on a non-child by handle, which is "
                           "a Windows capability; POSIX records it unavailable")
def test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk(sandbox, monkeypatch):
    """The whole chain, with real processes: supervisor -> detached reaper -> file.

    The unit tests above call reap() directly, so they would still pass if
    spawn_cycle never started a reaper, or started one that could not import
    itself, or handed it the wrong pid. This is the one that fails if the wiring
    is wrong.
    """
    runner = sandbox / "runner.py"
    runner.write_text("import sys, time\ntime.sleep(0.3)\nsys.exit(5)\n",
                      encoding="utf-8")
    monkeypatch.setattr(sup, "RUNNER", runner)
    monkeypatch.setattr(sup, "REAPER_SETTLE_SEC", 0.5)

    pid = sup.spawn_cycle("e2e-test")
    assert pid, "the cycle failed to spawn"

    record = sandbox / "cycle_exit.json"
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        if record.exists():
            break
        time.sleep(0.1)
    assert record.exists(), (
        "no exit record appeared — spawn_cycle did not start a working reaper")

    rec = json.loads(record.read_text(encoding="utf-8"))
    assert rec["exit_code"] == 5, (
        f"the chain recorded the wrong code: {rec}. The launcher stub is "
        f"supposed to forward its child's exit code; if this is 0 or 1 it did "
        f"not, and the reaper is watching the wrong process.")
    assert rec["cycle_id"] == "e2e-test"
    assert _night_lines(sandbox / "night_events.jsonl"), \
        "the night log got nothing, so the morning report will not mention it"
