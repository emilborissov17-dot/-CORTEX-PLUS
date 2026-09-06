# -*- coding: utf-8 -*-
"""ITEM 10 — a suite run that knows whether a cycle touched it.

The item's acceptance, verbatim: "simulate by writing a fake lock mid-run in a
fixture; the runner reports INVALID with both readings, and the fixture proves
memory/cycle.lock is byte-identical afterwards."

The simulation is real: the subprocess the runner launches IS the thing that
writes the fake lock, so the lock appears strictly between the two readings the
runner takes, exactly as a supervisor tick would. Nothing is stubbed except the
paths, which point at tmp_path.

WHY "byte-identical" HAS TO INCLUDE "still absent". Between cycles there is no
memory/cycle.lock at all. A fixture that created one and deleted it would pass a
naive digest check while having briefly told every other process on this machine
that a cycle was running. So the guard records ABSENT as a state and compares
against it.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import pytest
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tools import suite_gate as sg  # noqa: E402


def _state(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


_LIVE_BEFORE = {p.as_posix(): _state(p) for p in (
    sg.LOCK, sg.HEARTBEAT, sg.LAST_SEALED, sg.RUNS)}


def _paths(tmp_path):
    return {"lock": tmp_path / "cycle.lock",
            "heartbeat": tmp_path / "heartbeat.json",
            "last_sealed": tmp_path / "last_cycle_id.txt",
            "runs_path": tmp_path / "suite_runs.jsonl"}


def _writer_command(lock: pathlib.Path, cycle_id: str = "2026-08-29T12:15:20"):
    """A subprocess that plants a lock, the way a supervisor tick would."""
    src = (f"import json,pathlib;"
           f"pathlib.Path(r'{lock}').write_text("
           f"json.dumps({{'pid': 999999, 'cycle_id': '{cycle_id}'}}), "
           f"encoding='utf-8')")
    return [sys.executable, "-c", src]


# ── the acceptance ─────────────────────────────────────────────────────────

def test_a_lock_written_mid_run_makes_the_run_invalid(tmp_path):
    p = _paths(tmp_path)
    entry = sg.run(command=_writer_command(p["lock"]), **p)

    assert entry["outcome"] == sg.INVALID
    assert entry["before"]["lock_present"] is False
    assert entry["after"]["lock_present"] is True
    assert entry["after"]["cycle_id"] == "2026-08-29T12:15:20"
    assert any("started inside the run window" in r for r in entry["reasons"])


def test_both_readings_are_in_the_record_with_the_cycle_id(tmp_path):
    """10.2 — an invalid run must be distinguishable from a clean one afterwards."""
    p = _paths(tmp_path)
    sg.run(command=_writer_command(p["lock"], "CYCLE-XYZ"), **p)

    lines = p["runs_path"].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, "the run was not written down"
    rec = json.loads(lines[0])
    assert rec["outcome"] == sg.INVALID
    assert rec["before"]["ts"] and rec["after"]["ts"], "both readings, timestamped"
    assert rec["before"]["lock_present"] is False
    assert rec["after"]["cycle_id"] == "CYCLE-XYZ"
    assert rec["reasons"], "an invalid run with no stated reason is not a record"


@pytest.mark.live_state
def test_the_real_cycle_lock_is_byte_identical_afterwards():
    """Including the case where byte-identical means 'still does not exist'."""
    for path, before in _LIVE_BEFORE.items():
        after = _state(pathlib.Path(path))
        assert after == before, (
            f"{path} moved during the test run: {before} -> {after}")


# ── the other transitions ──────────────────────────────────────────────────

def test_a_cycle_already_holding_the_lock_refuses_before_running_anything(tmp_path):
    """A LIVE pid, on purpose. The queue's rule is that a cycle is live only when
    cycle.lock exists AND its pid is running, so a lock naming a dead pid is
    stale and must NOT refuse — that case is covered below."""
    import os
    p = _paths(tmp_path)
    p["lock"].write_text(json.dumps({"pid": os.getpid(), "cycle_id": "HELD"}),
                         encoding="utf-8")
    marker = tmp_path / "it_ran.txt"
    entry = sg.run(command=[sys.executable, "-c",
                            f"open(r'{marker}','w').close()"], **p)

    assert entry["outcome"] == sg.REFUSED
    assert not marker.exists(), "REFUSED must mean nothing was executed"
    assert entry["after"] is None
    assert "nothing was executed" in entry["reasons"][0]


def test_a_stale_lock_naming_a_dead_pid_does_not_refuse_but_does_invalidate(tmp_path):
    """The other half of the rule. A lock left behind by a crashed cycle names a
    pid that is gone; refusing on it would wedge the suite until somebody
    noticed. It runs — and because the stale lock is still there at the end, the
    run is reported INVALID rather than quietly clean."""
    p = _paths(tmp_path)
    p["lock"].write_text(json.dumps({"pid": 999999, "cycle_id": "STALE"}),
                         encoding="utf-8")
    marker = tmp_path / "it_ran.txt"
    entry = sg.run(command=[sys.executable, "-c",
                            f"open(r'{marker}','w').close()"], **p)
    assert marker.exists(), "a stale lock must not wedge the suite"
    assert entry["outcome"] == sg.INVALID
    assert any("whole run" in r for r in entry["reasons"])


def test_a_lock_that_disappears_mid_run_is_also_invalid(tmp_path):
    """The run overlapped the TAIL of a cycle. A dead pid lets it start."""
    p = _paths(tmp_path)
    p["lock"].write_text(json.dumps({"pid": 2, "cycle_id": "ENDING"}),
                         encoding="utf-8")
    # pid 2 does not exist on Windows, so the runner does not refuse.
    if sg.read_state(p["lock"], p["heartbeat"], p["last_sealed"])["pid_alive"]:
        import pytest
        pytest.skip("pid 2 unexpectedly exists on this machine")

    entry = sg.run(command=[sys.executable, "-c",
                            f"import pathlib;pathlib.Path(r'{p['lock']}').unlink()"],
                   **p)
    assert entry["outcome"] == sg.INVALID
    assert any("tail of a cycle" in r for r in entry["reasons"])


def test_a_cycle_that_seals_inside_the_window_is_caught_without_any_lock(tmp_path):
    """heartbeat.json is DELETED on seal, so it cannot witness this. The
    surviving witness is memory/last_cycle_id.txt."""
    p = _paths(tmp_path)
    p["last_sealed"].write_text("SEALED-1", encoding="utf-8")
    entry = sg.run(command=[sys.executable, "-c",
                            f"import pathlib;pathlib.Path(r'{p['last_sealed']}')"
                            f".write_text('SEALED-2')"], **p)

    assert entry["before"]["lock_present"] is False
    assert entry["after"]["lock_present"] is False, (
        "no lock was ever visible — this is exactly the blind spot")
    assert entry["outcome"] == sg.INVALID
    assert any("last_cycle_id.txt" in r for r in entry["reasons"])


def test_a_quiet_window_is_valid_and_says_what_valid_does_not_mean(tmp_path):
    p = _paths(tmp_path)
    entry = sg.run(command=[sys.executable, "-c", "pass"], **p)
    assert entry["outcome"] == sg.VALID
    assert entry["reasons"] == []
    text = sg.format_verdict(entry)
    assert "no CYCLE, not no writer" in text, (
        "VALID must not be read as 'nothing wrote to memory/' — Approvals "
        "writes there every minute")


# ── the record, and the refusal to lie by omission ─────────────────────────

def test_an_invalid_run_does_not_exit_zero(tmp_path):
    """A script that shells out must not read INVALID as success."""
    p = _paths(tmp_path)
    entry = sg.run(command=_writer_command(p["lock"]), **p)
    assert entry["returncode"] == 0, "the inner command itself succeeded"
    assert entry["outcome"] == sg.INVALID, (
        "and the run is still invalid — which is why the CLI exits on the "
        "outcome and not on the return code")


def test_an_unreadable_lock_is_still_a_lock(tmp_path):
    p = _paths(tmp_path)
    p["lock"].write_text("{ this is not json", encoding="utf-8")
    st = sg.read_state(p["lock"], p["heartbeat"], p["last_sealed"])
    assert st["lock_present"] is True
    assert "lock_unreadable" in st, "a broken lock must not read as an all-clear"


def test_record_is_dry_by_default(tmp_path):
    out = tmp_path / "runs.jsonl"
    sg.record({"outcome": "VALID"}, path=out)
    assert not out.exists()
    sg.record({"outcome": "VALID"}, write=True, path=out)
    assert out.exists()


# ── the INCOMPLETE branch, after it was narrowed on 6 Sep ───────────────────
# It was narrowed because it had overwritten seven INVALID verdicts with
# INCOMPLETE, using a stub command as evidence that pytest had not finished.
# Narrowing a check is exactly when it must be re-proved against the defect it
# was built for, so all three cases are pinned here.

def test_a_pytest_that_never_ran_is_INCOMPLETE_not_valid(tmp_path):
    """THE DEFECT THE BRANCH EXISTS FOR. A pytest that dies before printing a
    summary must not be recorded as a clean suite with zero failures."""
    p = _paths(tmp_path)
    entry = sg.run(command=[sys.executable, "-m", "pytest", "--no-such-flag"], **p)
    assert entry["summary"] == "", "this command must not produce a summary line"
    assert entry["outcome"] == "INCOMPLETE", entry["outcome"]
    assert any("NOTHING WAS MEASURED" in r for r in entry["reasons"])


def test_a_command_that_is_not_pytest_is_not_called_incomplete(tmp_path):
    """The narrowing itself. `python -c pass` prints no summary because it is not
    pytest, not because it was killed - inferring 'did not finish' from it is a
    claim about a different thing."""
    p = _paths(tmp_path)
    entry = sg.run(command=[sys.executable, "-c", "pass"], **p)
    assert entry["summary"] == ""
    assert entry["outcome"] == sg.VALID
    assert not any("INCOMPLETE" in r for r in entry["reasons"])


def test_incomplete_never_overwrites_invalid_but_is_still_recorded(tmp_path):
    """INVALID says a cycle wrote to memory/ during the window, so the numbers
    cannot be trusted whatever pytest did. That is the stronger claim and it wins
    the OUTCOME - but the incompleteness still has to appear in the record."""
    p = _paths(tmp_path)
    entry = sg.run(command=_writer_command(p["lock"]) + ["pytest"], **p)
    assert entry["summary"] == ""
    assert entry["outcome"] == sg.INVALID, "a cycle in the window outranks a short run"
    assert any("NOTHING WAS MEASURED" in r for r in entry["reasons"]), \
        "the outcome narrows, the record must not"
