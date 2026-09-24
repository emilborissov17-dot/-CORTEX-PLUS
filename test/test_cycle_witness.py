"""
test/test_cycle_witness.py — the witness says HOW a cycle ended, and the supervisor
starts every cycle through it.

Why (24 Sep 2026): six catch-up cycles died on 23-24 Sep with no traceback, no exit
code and the reaper gone with them (claude/reports/STEP_AUDIT_2026-09-24.md, Parts
3-5). tools/cycle_witness.ps1 is the cycle's parent and writes a start row and an
exit row to a witness log. These tests run the REAL witness against REAL child
processes, in a tmp dir — never against memory/.

What a failure looks like, named before the happy path:
  * an exit row that says "clean exit" for a process that was killed — the
    launcher-kill case below exists because killing the venv launcher makes the
    interpreter report 0 (measured on this machine, 24 Sep);
  * taskkill /F recorded as a python error — it yields exit code 1, the same code
    as an uncaught exception, so the two are split by the traceback in the log;
  * a start row without the pids a later reader needs;
  * spawn_cycle still starting memory.cycle_reaper, or dropping the breakaway flag.

The exit codes asserted here are the MEASURED ones: taskkill /F gives 1 (not -1);
Stop-Process gives -1.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import supervisor as sup  # noqa: E402

PS1 = REPO / "tools" / "cycle_witness.ps1"
PY = str(sup.PYTHON if sup.PYTHON.exists() else sys.executable)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the witness is Windows-only")


def _start_witness(tmp_path: Path, code: str, cycle_id: str):
    wl = tmp_path / "witness.jsonl"
    log = tmp_path / f"{cycle_id}.log"
    b64 = base64.b64encode(json.dumps(["-c", code]).encode()).decode()
    proc = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(PS1), "-Exe", PY, "-ArgsB64", b64, "-Log", str(log),
         "-WitnessLog", str(wl), "-CycleId", cycle_id, "-WorkDir", str(tmp_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc, wl, log


def _rows(wl: Path) -> list:
    if not wl.exists():
        return []
    return [json.loads(x) for x in wl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _wait_row(wl: Path, event: str, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for r in _rows(wl):
            if r.get("event") == event:
                return r
        time.sleep(0.2)
    raise AssertionError(f"no {event!r} row in {wl} within {timeout}s; rows={_rows(wl)}")


def _kill(pid: int, how: str) -> None:
    if how == "taskkill":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                        f"Stop-Process -Id {pid} -Force"], capture_output=True)


# ---------------------------------------------------------------------------
# The witness itself, against real processes
# ---------------------------------------------------------------------------

def test_a_clean_exit_is_recorded_as_clean(tmp_path):
    proc, wl, _ = _start_witness(tmp_path, "import sys; sys.exit(0)", "clean")
    ex = _wait_row(wl, "exit")
    proc.wait(timeout=30)
    assert ex["exit_code"] == 0
    assert ex["exit_code_hex"] == "0x00000000"
    assert ex["meaning"] == "clean exit"
    st = _wait_row(wl, "start")
    for k in ("witness_pid", "witness_parent_pid", "cmd_pid"):
        assert isinstance(st[k], int) and st[k] > 0, f"start row lacks {k}: {st}"


def test_the_start_row_carries_every_pid(tmp_path):
    """A child that lives long enough to be seen: all three pids, and the cycle
    pid is the REAL interpreter, distinct from the venv launcher."""
    proc, wl, _ = _start_witness(tmp_path, "import time,sys; time.sleep(3); sys.exit(0)", "pids")
    st = _wait_row(wl, "start")
    for k in ("witness_pid", "witness_parent_pid", "cmd_pid", "launcher_pid", "cycle_pid"):
        assert isinstance(st[k], int) and st[k] > 0, f"start row lacks {k}: {st}"
    assert st["cycle_pid_source"] == "interpreter"
    assert st["cycle_pid"] != st["launcher_pid"]
    assert st["cycle_id"] == "pids" and st["cmdline"]
    _wait_row(wl, "exit")
    proc.wait(timeout=30)


def test_taskkill_f_is_recorded_as_killed(tmp_path):
    """taskkill /F -> exit code 1 (measured), and NO traceback -> 'killed'."""
    proc, wl, _ = _start_witness(tmp_path, "import time; time.sleep(30)", "tk")
    st = _wait_row(wl, "start")
    _kill(st["cycle_pid"], "taskkill")
    ex = _wait_row(wl, "exit")
    proc.wait(timeout=30)
    assert ex["exit_code"] == 1, ex
    assert ex["meaning"].startswith("killed"), ex


def test_stop_process_is_recorded_as_killed_minus_one(tmp_path):
    proc, wl, _ = _start_witness(tmp_path, "import time; time.sleep(30)", "sp")
    st = _wait_row(wl, "start")
    _kill(st["cycle_pid"], "stop-process")
    ex = _wait_row(wl, "exit")
    proc.wait(timeout=30)
    assert ex["exit_code"] == -1 and ex["exit_code_hex"] == "0xFFFFFFFF", ex
    assert ex["meaning"] == "killed (taskkill /F or TerminateProcess)"


def test_systemexit_3_is_a_python_error(tmp_path):
    proc, wl, _ = _start_witness(tmp_path, "raise SystemExit(3)", "se3")
    ex = _wait_row(wl, "exit")
    proc.wait(timeout=30)
    assert ex["exit_code"] == 3
    assert ex["meaning"] == "python error, see log"


def test_an_uncaught_exception_is_not_mistaken_for_a_kill(tmp_path):
    """Exit code 1 twice over: here it is a traceback, so 'python error'."""
    proc, wl, log = _start_witness(tmp_path, "raise ValueError('boom')", "uncaught")
    ex = _wait_row(wl, "exit")
    proc.wait(timeout=30)
    assert ex["exit_code"] == 1
    assert ex["meaning"] == "python error, see log", ex
    assert "ValueError" in log.read_text(encoding="utf-8", errors="replace")


def test_a_launcher_kill_is_not_recorded_as_a_clean_exit(tmp_path):
    """The trap: kill the venv LAUNCHER and the interpreter dies reporting 0."""
    proc, wl, _ = _start_witness(tmp_path, "import time; time.sleep(30)", "lk")
    st = _wait_row(wl, "start")
    if st["cycle_pid_source"] != "interpreter":
        pytest.skip("no separate launcher on this interpreter")
    _kill(st["launcher_pid"], "taskkill")
    ex = _wait_row(wl, "exit")
    proc.wait(timeout=30)
    assert ex["exit_code"] == 0 and ex["launcher_exit_code"] == 1, ex
    assert ex["meaning"] != "clean exit"
    assert ex["meaning"].startswith("killed through its launcher")


# ---------------------------------------------------------------------------
# supervisor.spawn_cycle: through the witness, outside the job, no reaper
# ---------------------------------------------------------------------------

class _FakePopen:
    calls: list = []
    refuse_breakaway = False

    def __init__(self, argv, **kw):
        flags = kw.get("creationflags", 0)
        if _FakePopen.refuse_breakaway and flags & sup.CREATE_BREAKAWAY_FROM_JOB:
            err = OSError(22, "Access is denied")
            err.winerror = 5
            _FakePopen.calls.append((argv, kw, "refused"))
            raise err
        _FakePopen.calls.append((argv, kw, "ok"))
        self.pid = 5151


@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "RUNNER", tmp_path / "runner.py")
    monkeypatch.setattr(sup.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(sup, "_witness_available", lambda: True)
    monkeypatch.setattr(sup, "_wait_witness_start",
                        lambda cid, t: {"event": "start", "cycle_id": cid, "cycle_pid": 7777,
                                        "launcher_pid": 6666, "cycle_pid_source": "interpreter"})
    logged = []
    monkeypatch.setattr(sup, "log", lambda m: logged.append(m))
    _FakePopen.calls = []
    _FakePopen.refuse_breakaway = False
    return logged


def test_spawn_cycle_goes_through_the_witness_and_starts_no_reaper(wired, tmp_path):
    assert sup.witness_log_path() == tmp_path / "witness.jsonl", \
        "the witness log must follow CYCLE_LOG_DIR so sandboxed tests stay out of memory/"
    pid = sup.spawn_cycle("wiring")
    assert pid == 7777, "the lock must get the real interpreter's pid from the start row"
    assert len(_FakePopen.calls) == 1, f"expected ONE spawn (the witness), got {_FakePopen.calls}"
    argv, kw, _ = _FakePopen.calls[0]
    joined = " ".join(map(str, argv))
    assert "cycle_witness.ps1" in joined
    assert "memory.cycle_reaper" not in joined
    flags = kw["creationflags"]
    assert flags & sup.CREATE_BREAKAWAY_FROM_JOB, "the witness must leave the tick's job"
    assert flags & getattr(subprocess, "DETACHED_PROCESS", 0)
    assert flags & getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    args = json.loads(base64.b64decode(argv[argv.index("-ArgsB64") + 1]))
    assert args[0] == "-u" and args[1].endswith("runner.py")
    assert argv[argv.index("-WitnessLog") + 1] == str(tmp_path / "witness.jsonl")


def test_a_refused_breakaway_is_retried_without_it_and_logged(wired):
    _FakePopen.refuse_breakaway = True
    pid = sup.spawn_cycle("refused")
    assert pid == 7777
    outcomes = [c[2] for c in _FakePopen.calls]
    assert outcomes == ["refused", "ok"], outcomes
    _, kw, _ = _FakePopen.calls[1]
    assert not (kw["creationflags"] & sup.CREATE_BREAKAWAY_FROM_JOB)
    assert kw["creationflags"] & getattr(subprocess, "DETACHED_PROCESS", 0)
    assert any("WITNESS: breakaway refused" in m for m in wired), wired
