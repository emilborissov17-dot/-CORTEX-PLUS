# -*- coding: utf-8 -*-
"""test/test_turn.py — the baton (C-TURN-1 Part 2). Witness rows, alarm, cycle
and body are injected; turn.json and the log are under tmp_path."""
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


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture
def p(tmp_path):
    return {"state": tmp_path / "turn.json", "log": tmp_path / "log.jsonl", "alarms": []}


def _hand(p, to, rows, cause=None, cid="T1"):
    return turn.hand_over(to, "summary", cid, cause=cause, path=p["state"], log_path=p["log"],
                          witness=lambda c: rows.get(c), alarm=lambda s, d, k: p["alarms"].append((s, k)) or "deferred")


def _log(p):
    return [json.loads(l) for l in p["log"].read_text(encoding="utf-8").splitlines()]


def test_a_clean_turn_hands_over(p):
    turn.take("BRAIN", p["state"])
    r = _hand(p, "AGENTS", {"T1": {"exit_code": 0}})
    s = turn.state(p["state"])
    assert r["handed"] and s["holder"] == "AGENTS" and s["seq"] == 1 and s["last_summary"] == "summary"


def test_an_explained_failure_hands_over(p):
    turn.take("BRAIN", p["state"])
    r = _hand(p, "AGENTS", {"T1": {"exit_code": 1}}, cause="hyperon did not run: sidecar missing")
    assert r["handed"] and "hyperon" in turn.state(p["state"])["why"]


def test_an_unexplained_failure_does_not_hand_over(p):
    turn.take("BRAIN", p["state"])
    r = _hand(p, "AGENTS", {"T1": {"exit_code": 1, "meaning": "taskkill /F or uncaught exception"}})
    assert not r["handed"] and turn.state(p["state"])["holder"] == "BRAIN"
    assert p["alarms"] == [("TURN_STUCK", "TURN_STUCK:0")]
    assert _log(p)[-1]["event"] == "TURN_STUCK"


def test_no_exit_row_does_not_hand_over(p):
    turn.take("BRAIN", p["state"])
    r = _hand(p, "AGENTS", {})
    assert not r["handed"] and "no witness exit row" in r["stuck"]


def test_mutation_handing_over_without_the_witness_row(p, monkeypatch):
    turn.take("BRAIN", p["state"])
    r = turn.hand_over("AGENTS", "s", "T1", path=p["state"], log_path=p["log"],
                       witness=lambda c: {"exit_code": 0}, alarm=lambda *a: None)     # a witness that always says clean
    assert r["handed"], "the guard is the witness row: fake it and the baton moves"


def test_a_double_take_is_refused(p):
    turn.take("BRAIN", p["state"])
    with pytest.raises(turn.TurnRefused):
        turn.take("AGENTS", p["state"])
    assert turn.take("BRAIN", p["state"])["holder"] == "BRAIN"


def test_mutation_without_the_holder_check_both_could_run(p, monkeypatch):
    turn.take("BRAIN", p["state"])
    monkeypatch.setattr(turn, "state", lambda path=None: {"holder": None, "seq": 0})
    assert turn.take("AGENTS", p["state"])["holder"] == "AGENTS"


def test_the_nightly_cycle_blocks_both_turns(p):
    why = turn.blocked(cycle=lambda: "the big cycle is running (pid=1)", body=lambda: None, log_path=p["log"])
    assert why == "the big cycle is running (pid=1)" and _log(p)[-1]["event"] == "WAIT"


def test_the_body_blocks_a_turn_with_its_own_reason(p):
    why = turn.blocked(cycle=lambda: None, body=lambda: "body: RAM 95% (0.6GB free)", log_path=p["log"])
    assert why.startswith("body: RAM 95%")


def test_mutation_a_blocked_that_ignores_the_cycle_would_let_a_turn_start(p):
    ignoring = lambda: None
    assert turn.blocked(cycle=ignoring, body=lambda: None, log_path=p["log"]) is None


def test_the_alarm_is_used_once_per_stuck_seq(p):
    turn.take("BRAIN", p["state"])
    _hand(p, "AGENTS", {})
    _hand(p, "AGENTS", {})
    assert [k for _, k in p["alarms"]] == ["TURN_STUCK:0", "TURN_STUCK:0"]   # same dedup key: alarm_human suppresses the second
