# -*- coding: utf-8 -*-
"""test/test_turns_loop.py — turns alternate by baton, not by clock (C-TURN-1 Part 5).
The turn runner, the witness and the clock are injected; files under tmp_path."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import turn  # noqa: E402
from scripts import turns_loop as tl  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture
def p(tmp_path):
    return {"turn": tmp_path / "turn.json", "result": tmp_path / "result.json", "stop": tmp_path / "stop",
            "log": tmp_path / "log.jsonl", "witness": {}}


def _runner(p, codes=None, causes=None):
    codes, causes, ran = list(codes or []), list(causes or []), []

    def run(holder, cycle_id):
        ran.append(holder)
        code = codes.pop(0) if codes else 0
        p["witness"][cycle_id] = {"exit_code": code}
        p["result"].write_text(json.dumps({"utc": "9999-12-31T00:00:00Z", "summary": f"{holder} done",
                                           "cause": causes.pop(0) if causes else None}), encoding="utf-8")
        return code
    return run, ran


def _loop(p, run, **kw):
    hand = lambda to, summary, cid, cause=None, path=None, log_path=None: turn.hand_over(
        to, summary, cid, cause=cause, path=path, log_path=log_path, witness=lambda c: p["witness"].get(c),
        alarm=lambda *a: "deferred")
    return tl.loop(run_turn=run, blocked=kw.pop("blocked", lambda: None), sleep=kw.pop("sleep", lambda s: None),
                   turn_path=p["turn"], result_path=p["result"], stop_path=p["stop"], hand=hand,
                   log_path=p["log"], **kw)


def test_turns_alternate_brain_first(p):
    run, ran = _runner(p)
    r = _loop(p, run, max_turns=4)
    assert ran == ["BRAIN", "AGENTS", "BRAIN", "AGENTS"] and all(t["handed"] for t in r["turns"])
    assert turn.state(p["turn"])["seq"] == 4 and turn.state(p["turn"])["holder"] == "BRAIN"


def test_an_unexplained_failure_stops_the_loop_and_keeps_the_baton(p):
    run, ran = _runner(p, codes=[0, 1])
    r = _loop(p, run, max_turns=4)
    assert ran == ["BRAIN", "AGENTS"] and "no named cause" in r["stuck"]
    assert turn.state(p["turn"])["holder"] == "AGENTS"


def test_an_explained_failure_hands_over_and_the_loop_goes_on(p):
    run, ran = _runner(p, codes=[2, 0], causes=["hyperon did not run: sidecar missing", None])
    r = _loop(p, run, max_turns=2)
    assert ran == ["BRAIN", "AGENTS"] and all(t["handed"] for t in r["turns"])


def test_a_blocked_turn_waits_and_does_not_run(p):
    run, ran = _runner(p)
    waits = iter(["the big cycle is running", None, None])
    slept = []
    _loop(p, run, max_turns=1, blocked=lambda: next(waits), sleep=slept.append)
    assert slept == [tl.WAIT_S] and ran == ["BRAIN"]


def test_the_stop_flag_stops_between_turns(p):
    run, ran = _runner(p)
    p["stop"].write_text("x", encoding="utf-8")
    r = _loop(p, run, max_turns=4)
    assert r["stopped"] == "stop flag" and ran == [] and not p["stop"].exists()


def test_mutation_a_loop_that_ignored_hand_over_would_run_on_after_a_stuck_turn(p):
    run, ran = _runner(p, codes=[1, 0, 0])
    hand_always = lambda *a, **k: {"handed": True}
    tl.loop(run_turn=run, blocked=lambda: None, sleep=lambda s: None, turn_path=p["turn"], result_path=p["result"],
            stop_path=p["stop"], hand=hand_always, log_path=p["log"], max_turns=3)
    assert len(ran) == 3, "only hand_over's refusal is what stops the loop"


def test_main_never_probes_a_pid_with_os_kill():
    import ast
    tree = ast.parse((REPO / "scripts" / "turns_loop.py").read_text(encoding="utf-8"))
    calls = {f"{n.func.value.id}.{n.func.attr}" for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)}
    assert "os.kill" not in calls, "os.kill(pid, 0) terminates the process on Windows"
