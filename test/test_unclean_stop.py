#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_unclean_stop.py — ONE RECORD FOR AN UNCLEAN STOP, NONE FOR A CLEAN ONE.

Absence is the signal. A ledger with no RESTART_AFTER_UNCLEAN_STOP between two
cycles is a statement that the first ended properly, and that statement is worth
nothing if the record is ever written speculatively. So the tests that assert
NOTHING is written matter as much as the one that asserts something is.

Every path is a tmp_path. The live ledger is never touched.

    venv/Scripts/python.exe -m pytest test/test_unclean_stop.py -v
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import unclean_stop as us   # noqa: E402

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)
CYCLE = "2026-08-23T06:14:11.681872+00:00"

# A pid that cannot exist. Windows pids are multiples of 4 and bounded; this is
# checked to be dead in the fixture rather than assumed.
DEAD_PID = 999_999_321


@pytest.fixture
def tree(tmp_path):
    hb = tmp_path / "heartbeat.json"
    led = tmp_path / "existence_ledger.jsonl"
    led.write_text("", encoding="utf-8")
    return hb, led


def _heartbeat(path, pid=DEAD_PID, cycle=CYCLE, minutes_ago=295, **extra):
    blob = {
        "pid": pid,
        "cycle_id": cycle,
        "step": "cognitive_orchestrator",
        "step_index": "12.7",
        "step_started_utc": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
        "updated_utc": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
    }
    blob.update(extra)
    path.write_text(json.dumps(blob), encoding="utf-8")
    return blob


def _ledger(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


def _rows(path):
    txt = path.read_text(encoding="utf-8").strip()
    return [json.loads(l) for l in txt.splitlines() if l.strip()] if txt else []


def test_the_fixture_pid_really_is_dead():
    """The whole file rests on this."""
    assert us._pid_alive(DEAD_PID) is False


# ── the headline case ───────────────────────────────────────────────────────

def test_a_dead_pid_with_no_end_record_produces_exactly_one_record(tree):
    hb, led = tree
    _heartbeat(hb)
    ev = us.record(hb, led, now=NOW)
    assert ev is not None
    rows = _rows(led)
    assert len(rows) == 1, rows
    assert rows[0]["event"] == "RESTART_AFTER_UNCLEAN_STOP"


def test_the_record_carries_what_the_kill_cost(tree):
    hb, led = tree
    _heartbeat(hb, minutes_ago=295)
    ev = us.record(hb, led, now=NOW)
    assert ev["cycle_id"] == CYCLE
    assert ev["last_step"] == "cognitive_orchestrator"
    assert ev["last_step_index"] == "12.7"
    assert ev["last_heartbeat_utc"]
    lost = ev["lost_duration_seconds"]
    assert lost == pytest.approx(295 * 60, abs=2), lost


def test_lost_duration_is_plausible_not_negative_and_not_absurd(tree):
    hb, led = tree
    for minutes in (1, 60, 295, 60 * 24):
        led.write_text("", encoding="utf-8")
        _heartbeat(hb, minutes_ago=minutes)
        ev = us.record(hb, led, now=NOW)
        assert 0 <= ev["lost_duration_seconds"] <= 60 * 60 * 25


def test_a_heartbeat_from_the_future_does_not_produce_a_negative_loss(tree):
    """Clock skew is real on this box; a negative duration would be a lie."""
    hb, led = tree
    _heartbeat(hb, minutes_ago=-30)
    ev = us.record(hb, led, now=NOW)
    assert ev["lost_duration_seconds"] == 0.0


# ── absence is the signal ───────────────────────────────────────────────────

def test_a_clean_previous_stop_produces_nothing(tree):
    hb, led = tree
    _heartbeat(hb)
    _ledger(led, [{"seq": 1, "event": "CYCLE_FINISHED", "cycle_id": CYCLE}])
    assert us.record(hb, led, now=NOW) is None
    assert len(_rows(led)) == 1, "a record was written for a clean stop"


@pytest.mark.parametrize("event", ["CYCLE_DIED", "CYCLE_KILLED",
                                   "CYCLE_FAILED_BUDGET_EXHAUSTED"])
def test_an_ending_already_accounted_for_is_not_double_counted(tree, event):
    """The supervisor may already have written the obituary. Two records for
    one stop would inflate every count taken off this ledger."""
    hb, led = tree
    _heartbeat(hb)
    _ledger(led, [{"seq": 1, "event": event, "cycle_id": CYCLE}])
    assert us.record(hb, led, now=NOW) is None
    assert len(_rows(led)) == 1


def test_a_live_pid_produces_nothing(tree):
    """That cycle is not over. Recording its death would be a false entry."""
    hb, led = tree
    _heartbeat(hb, pid=os.getpid())
    assert us.record(hb, led, now=NOW) is None
    assert _rows(led) == []


def test_a_retired_heartbeat_produces_nothing(tree):
    """retire() is the clean handover; it is not a kill."""
    hb, led = tree
    _heartbeat(hb, retired_utc=NOW.isoformat())
    assert us.record(hb, led, now=NOW) is None
    assert _rows(led) == []


def test_no_heartbeat_at_all_produces_nothing(tree):
    hb, led = tree
    assert us.record(hb, led, now=NOW) is None
    assert _rows(led) == []


def test_an_unreadable_heartbeat_produces_nothing(tree):
    hb, led = tree
    hb.write_text("{not json", encoding="utf-8")
    assert us.record(hb, led, now=NOW) is None
    assert _rows(led) == []


def test_running_it_twice_does_not_write_twice(tree):
    """The record IS an end record for that cycle, so the second pass sees it."""
    hb, led = tree
    _heartbeat(hb)
    assert us.record(hb, led, now=NOW) is not None
    assert us.record(hb, led, now=NOW) is None
    assert len(_rows(led)) == 1


# ── it must never cost a boot ───────────────────────────────────────────────

def test_an_unwritable_ledger_does_not_raise(tree, monkeypatch):
    hb, _ = tree
    _heartbeat(hb)
    assert us.record(hb, pathlib.Path("\0bad") / "x.jsonl", now=NOW) is None


def test_a_pid_we_cannot_judge_counts_as_alive(monkeypatch):
    """Unknown must not be read as dead. A false unclean record is worse than
    a missing one in the file that carries the system's own history."""
    import builtins
    real_import = builtins.__import__

    def _no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    monkeypatch.setattr(os, "kill",
                        lambda *a: (_ for _ in ()).throw(OSError("cannot tell")))
    assert us._pid_alive(12345) is True


# ── the wiring ──────────────────────────────────────────────────────────────

def test_the_runner_checks_before_it_overwrites_the_heartbeat():
    """One beat() later and the evidence is gone."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "_record_unclean()" in code, "nothing calls the recorder"
    check_at = code.index("_record_unclean()")
    first_beat = code.index('beat("boot"')
    assert check_at < first_beat, (
        "the check runs after the first beat, by which time heartbeat.json has "
        "already been overwritten with this cycle's own values")


def test_the_report_mode_writes_nothing(tmp_path, capsys):
    """`python core/unclean_stop.py` is a read-only report."""
    import ast
    tree_ = ast.parse((REPO / "core" / "unclean_stop.py").read_text(
        encoding="utf-8"))
    report = next(n for n in ast.walk(tree_)
                  if isinstance(n, ast.FunctionDef) and n.name == "_report")
    body = ast.dump(report)
    assert "'record'" not in body, "_report calls record()"
    assert "write_text" not in body
