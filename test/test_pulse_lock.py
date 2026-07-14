"""The pulse daemon must be single-instance.

Two daemons appending to one stream interleave samples from two pids. analyze.py
can DETECT that (it counts writers) but cannot repair it, and a sensory stream you
cannot trust is not evidence — it is decoration. The obvious way to end up with
two is a scheduled task plus a manual run in a terminal someone forgot about, so
the daemon takes a PID lock and a second instance refuses to start.

Note what these tests do NOT do: they never touch supervisor.py or memory/. The
pulse experiment MIRRORS the supervisor's lock pattern; it does not import it and
does not write outside experiments/pulse/. That isolation is the point — day-0
experimental code does not get to reach into constitutional machinery.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "pulse"))

import pulse_daemon as pd


@pytest.fixture(autouse=True)
def _isolated_lock(tmp_path, monkeypatch):
    """Never let a test touch the real experiments/pulse/pulse.lock."""
    monkeypatch.setattr(pd, "LOCK_FILE", tmp_path / "pulse.lock")
    return tmp_path / "pulse.lock"


# A pid that is alive AND is a python process: our own test runner.
LIVE_PYTHON_PID = os.getpid()
# A pid that is not alive. 2^22 is above Windows' range and safely unused.
DEAD_PID = 4_194_303


# ---------------------------------------------------------------------------
# Liveness probe
# ---------------------------------------------------------------------------

def test_pid_alive_true_for_a_live_python():
    assert pd._pid_alive(LIVE_PYTHON_PID) is True


def test_pid_alive_false_for_a_dead_pid():
    assert pd._pid_alive(DEAD_PID) is False


def test_pid_alive_false_for_none():
    assert pd._pid_alive(None) is False


def test_pid_alive_false_for_a_live_non_python_process():
    """A recycled pid landing on some unrelated process must not block a start.

    Without the process-name check, the OS handing a dead daemon's pid to
    notepad.exe would wedge the pulse permanently.
    """
    class _FakeProc:
        def name(self):
            return "notepad.exe"

    import psutil
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(psutil, "Process", lambda pid: _FakeProc())
        assert pd._pid_alive(12345) is False


# ---------------------------------------------------------------------------
# Acquire / release
# ---------------------------------------------------------------------------

def test_acquire_on_a_clean_slate_writes_our_pid(_isolated_lock):
    assert pd.acquire_lock() is True

    lock = json.loads(_isolated_lock.read_text(encoding="utf-8"))
    assert lock["pid"] == os.getpid()
    assert lock["started_utc"]


def test_second_instance_refuses_while_a_live_daemon_holds_the_lock(_isolated_lock, capsys):
    """THE test. A scheduled task firing while a manual run is alive must not
    produce a second writer."""
    _isolated_lock.write_text(json.dumps({
        "pid": LIVE_PYTHON_PID,          # alive, and a python process
        "started_utc": "2026-07-14T05:00:00+00:00",
    }), encoding="utf-8")

    assert pd.acquire_lock() is False
    assert "refusing to start a second one" in capsys.readouterr().out

    # And it did NOT steal the lock.
    still = json.loads(_isolated_lock.read_text(encoding="utf-8"))
    assert still["pid"] == LIVE_PYTHON_PID


def test_stale_lock_from_a_killed_daemon_is_reclaimed(_isolated_lock, capsys):
    """taskkill /F leaves the lock behind — the next start must take over, not
    wedge forever."""
    _isolated_lock.write_text(json.dumps({
        "pid": DEAD_PID,
        "started_utc": "2026-07-13T15:00:00+00:00",
    }), encoding="utf-8")

    assert pd.acquire_lock() is True
    assert "clearing stale lock" in capsys.readouterr().out
    assert json.loads(_isolated_lock.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_corrupt_lock_is_treated_as_stale_not_fatal(_isolated_lock):
    """A half-written lock is a lock we cannot trust. Same instinct as the
    torn-line tolerance in the stream: skip it, do not crash on it."""
    _isolated_lock.write_text('{"pid": 123, "started', encoding="utf-8")

    assert pd.read_lock() == {"pid": None, "corrupt": True}
    assert pd.acquire_lock() is True
    assert json.loads(_isolated_lock.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_release_removes_our_own_lock(_isolated_lock):
    pd.acquire_lock()
    pd.release_lock()
    assert not _isolated_lock.exists()


def test_release_does_not_remove_someone_elses_lock(_isolated_lock):
    """If we were killed and a new daemon took over, our dying breath must not
    delete the live daemon's lock."""
    _isolated_lock.write_text(json.dumps({
        "pid": LIVE_PYTHON_PID + 1,      # not us
        "started_utc": "2026-07-14T06:00:00+00:00",
    }), encoding="utf-8")

    pd.release_lock()
    assert _isolated_lock.exists(), "released a lock we did not hold"


def test_release_on_a_missing_lock_is_a_no_op(_isolated_lock):
    pd.release_lock()      # must not raise


# ---------------------------------------------------------------------------
# Isolation + install convention
# ---------------------------------------------------------------------------

def test_lock_lives_under_experiments_pulse():
    """The daemon writes ONLY under experiments/pulse/. The lock is no exception."""
    import importlib
    fresh = importlib.reload(pd)
    assert fresh.LOCK_FILE.parent == (REPO / "experiments" / "pulse")


def test_install_prints_and_never_executes(capsys, monkeypatch):
    """--install prints the schtasks line for a human to run. Registering a
    scheduled task is an autonomy grant, and those are human. Same convention as
    supervisor --install."""
    import subprocess

    def _boom(*a, **kw):
        raise AssertionError("--install must never execute a command")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    pd.cmd_install()

    out = capsys.readouterr().out
    assert 'schtasks /Create /TN "CORTEX_Pulse"' in out
    assert "/SC ONLOGON" in out
    assert "pulse_daemon.py" in out
    assert 'schtasks /Delete /TN "CORTEX_Pulse" /F' in out


def test_pulse_does_not_touch_the_supervisor():
    """A wrong-but-plausible fix would have been to hang the pulse off the
    supervisor's task or its lock. supervisor.py is protected constitutional
    machinery; the experiment gets its own task, or none.

    Checked at the AST level, not by substring: the module's PROSE discusses the
    supervisor at length (deliberately — the isolation is the design), and a
    grep-shaped test would flag its own rationale.
    """
    import ast

    src = (REPO / "experiments" / "pulse" / "pulse_daemon.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any("supervisor" in m for m in imported), f"pulse imports {imported}"

    # And it must not register itself under the supervisor's task name. Strings
    # only — comments are not code, and the docstring says CORTEX_Supervisor for
    # a reason.
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    code_strings = [s for s in literals if s not in ast.get_docstring(tree)]
    assert not any("CORTEX_Supervisor" in s for s in code_strings)
