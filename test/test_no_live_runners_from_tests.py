"""
test/test_no_live_runners_from_tests.py — no test may start a real runner.

25 Sep 2026: supervisor.tick() under test reached COLLECTORS_START and started the
real collectors runner twice against the live repo. Decision: two nets - the
conftest fixture refusing any subprocess that names a runner, and the collectors
runner refusing a start without --run-id - each asserted below.

Rule: these tests must fail if either net is removed, and must be harmless when
one is: every subprocess below is `python -c pass <name>`, which runs nothing.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import collectors_runner as cr
import supervisor as sup


@pytest.mark.parametrize("name", ["collectors_runner.py", "edges_runner.py",
                                  "fast_cycle_runner.py"])
def test_a_subprocess_naming_a_runner_raises(name):
    with pytest.raises(RuntimeError, match="live runner"):
        subprocess.Popen([sys.executable, "-c", "pass", name])


def test_the_refusing_resume_gate_still_passes_the_net():
    p = subprocess.Popen([sys.executable, "-c", "pass", "fast_cycle_runner.py", "--from", "X"])
    assert p.wait(timeout=30) == 0


def test_collectors_runner_without_a_run_id_refuses(monkeypatch):
    ran = []
    monkeypatch.setattr(cr, "run", lambda *a, **k: ran.append(a) or {"collectors": {}})
    assert cr.main([]) == 2 and ran == []
    assert cr.main(["--run-id"]) == 2 and ran == []
    assert cr.main(["--run-id", "r1"]) == 0 and ran == [("r1",)]


def test_a_tick_that_owes_the_collectors_starts_no_process(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "STATE_PATH", tmp_path / "scheduler_state.json")
    monkeypatch.setattr(sup, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "_witness_available", lambda: True)
    monkeypatch.setattr(sup, "_warm_core_preflight", lambda: "test")
    act = sup._spawn_collectors(sup.Action(sup.COLLECTORS_START, reason="test"),
                                {}, sup.datetime.now().astimezone())
    assert act.kind == sup.COLLECTORS_START
    assert sup.load_state()["collectors"]["pid"] is None, "a real collectors process started"
