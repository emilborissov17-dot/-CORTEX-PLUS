"""The cycle's output must survive the cycle.

THE BUG (2026-07-14)
--------------------
spawn_cycle() ran the cycle with stdout=DEVNULL, stderr=DEVNULL. A 70-minute run
that hit dozens of LLM calls left NO record of any of it: no traceback if it
died, no backend fallback lines, no "finish_reason=length — ОТРЯЗАН отговор"
warnings. The only evidence was whatever the cycle happened to write to disk as
data.

That is what made a Cerebras truncation fix unfalsifiable: the prediction was
"tomorrow's cycle shows near-zero truncation lines", and the lines were being
thrown away at the moment they were produced. A prediction you cannot check is
not a prediction.

It is also why a cycle that FINISHED CLEANLY was misread as a crash: with no log,
the only signals left were a dead pid and an abandoned lock.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import supervisor as sup


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    # spawn_cycle also starts a detached reaper, which writes the child's exit
    # code to CYCLE_EXIT_PATH and appends to NIGHT_LOG. Both are handed to it on
    # the command line precisely so this line can keep it out of live memory/ —
    # without it these tests would append a fabricated CYCLE_EXIT to the real
    # night log, which is the 16 Aug 2026 accident all over again.
    monkeypatch.setattr(sup, "CYCLE_EXIT_PATH", tmp_path / "cycle_exit.json")
    monkeypatch.setattr(sup, "CYCLE_EXIT_LOG", tmp_path / "cycle_exits.jsonl")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    return tmp_path / "cycle_logs"


# ---------------------------------------------------------------------------
# The property that matters: output actually lands in the file
# ---------------------------------------------------------------------------

def test_a_spawned_process_output_reaches_the_log_file(log_dir, monkeypatch, tmp_path):
    """End-to-end, with a REAL child process — not a mock. A mocked Popen would
    happily 'capture' output through a file handle that never gets written to.

    Both streams must land: the truncation warnings we want to count are printed
    to stdout, but a traceback goes to stderr.
    """
    child = tmp_path / "noisy.py"
    child.write_text(
        "import sys\n"
        "print('[LLM] Cerebras OK')\n"
        "print('boom', file=sys.stderr)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sup, "RUNNER", child)

    pid = sup.spawn_cycle("test-cycle")
    assert pid

    # The child is detached; wait for it rather than racing it.
    subprocess.run([str(sup.PYTHON if sup.PYTHON.exists() else sys.executable),
                    "-c", "import time; time.sleep(0)"], check=False)
    for _ in range(200):
        logs = list(log_dir.glob("cycle_*.log"))
        if logs and "boom" in logs[0].read_text(encoding="utf-8", errors="replace"):
            break
        import time as _t
        _t.sleep(0.05)

    logs = list(log_dir.glob("cycle_*.log"))
    assert len(logs) == 1, f"expected exactly one cycle log, got {logs}"

    body = logs[0].read_text(encoding="utf-8", errors="replace")
    assert "[LLM] Cerebras OK" in body, "stdout was not captured"
    assert "boom" in body, "stderr was not captured (stderr=STDOUT missing?)"


def test_a_failure_after_popen_still_returns_the_pid(log_dir, monkeypatch, tmp_path):
    """THE dangerous one, found by the test above failing.

    The "cycle output -> ..." log line originally called log_file.relative_to(BASE)
    INSIDE the try that wraps Popen. With the log dir outside BASE that raises —
    so spawn_cycle caught it and returned None AFTER the cycle had already
    started. The supervisor would then believe the spawn failed, write no lock,
    and the next tick would start a SECOND cycle on top of the running one.

    Nothing after Popen may cost us the pid.
    """
    child = tmp_path / "quiet.py"
    child.write_text("print('ran')\n", encoding="utf-8")
    monkeypatch.setattr(sup, "RUNNER", child)

    def _boom(_msg):
        raise ValueError("anything at all")

    monkeypatch.setattr(sup, "log", _boom)

    pid = sup.spawn_cycle("test-cycle")
    assert pid, "a live cycle was started but spawn_cycle reported failure"


def test_log_is_named_for_when_the_cycle_started(log_dir):
    p = sup.cycle_log_path(datetime(2026, 7, 15, 3, 0, 12))
    assert p.name == "cycle_2026-07-15_030012.log"
    assert p.parent == log_dir


# ---------------------------------------------------------------------------
# Pruning — an observability fix must not become a disk-full outage at 03:00
# ---------------------------------------------------------------------------

def test_prune_keeps_only_the_newest_n(log_dir):
    log_dir.mkdir(parents=True)
    for d in range(1, 21):
        (log_dir / f"cycle_2026-06-{d:02d}_030000.log").write_text("x", encoding="utf-8")

    deleted = sup.prune_cycle_logs(keep=14)

    remaining = sorted(p.name for p in log_dir.glob("cycle_*.log"))
    assert deleted == 6
    assert len(remaining) == 14
    assert remaining[0] == "cycle_2026-06-07_030000.log", "pruned the wrong end"
    assert remaining[-1] == "cycle_2026-06-20_030000.log"


def test_prune_is_a_no_op_when_under_the_limit(log_dir):
    log_dir.mkdir(parents=True)
    (log_dir / "cycle_2026-07-14_030000.log").write_text("x", encoding="utf-8")

    assert sup.prune_cycle_logs(keep=14) == 0
    assert len(list(log_dir.glob("cycle_*.log"))) == 1


def test_prune_survives_a_missing_directory(log_dir):
    assert sup.prune_cycle_logs() == 0      # must not raise


# ---------------------------------------------------------------------------
# Losing the log must never cost us the cycle
# ---------------------------------------------------------------------------

def test_cycle_still_spawns_if_the_log_cannot_be_opened(log_dir, monkeypatch, tmp_path):
    """Observability is worth a lot, but not the run itself. If the log cannot be
    opened we fall back to DEVNULL, say so loudly, and still start the cycle."""
    child = tmp_path / "quiet.py"
    child.write_text("print('ran')\n", encoding="utf-8")
    monkeypatch.setattr(sup, "RUNNER", child)

    def _boom(*a, **kw):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "mkdir", _boom)

    said = []
    monkeypatch.setattr(sup, "log", lambda m: said.append(m))

    pid = sup.spawn_cycle("test-cycle")

    assert pid, "a broken log must not stop the cycle from running"
    assert any("output discarded" in m for m in said), "the fallback must be loud"


# ---------------------------------------------------------------------------
# The stale-lock diagnosis no longer guesses
# ---------------------------------------------------------------------------

def test_stale_lock_reason_is_neutral():
    """It used to say "machine likely lost power mid-cycle" — a diagnosis the
    supervisor cannot make. Before that fix, the most common cause of a stale lock
    was a cycle finishing PERFECTLY, and the message called that power loss.

    A stale lock with no CYCLE_FINISHED now reads as a DEATH (the honest fact: the
    cycle did not finish) and is retried — but the wording still refuses to guess
    the CAUSE. It names the dead pid; it never claims power loss over a crash.
    """
    now = datetime.now().astimezone()
    lock = {"pid": 3688, "cycle_id": "c1", "started_utc": now.isoformat()}
    cfg = {"daily_hour": 3, "grace_hours": 20, "max_restarts_per_day": 2}

    action = sup.decide(now, {"last_run_date": None}, None, lock, cfg,
                        lock_pid_alive=False, lock_cycle_finished=False)

    assert action.kind == sup.DEAD_LOCK_RETRY
    assert "lost power" not in action.reason
    assert "DIED without finishing" in action.reason
    assert "3688" in action.reason
