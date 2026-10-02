# -*- coding: utf-8 -*-
"""test/test_turn_by_hand.py — the baton can be moved by hand, and says so (C-DOOR-2 Step 4).

Until 2 Oct the only way to move the baton outside a turn was core.turn.hand_over with a
witness row written by hand (six such rows, seq 69-74). THE RULE: `python -m core.turn
--by-hand <HOLDER> --why "<text>"` moves it and appends {"event": "BY_HAND", "from", "to",
"why", "seq"} to the turns log; no witness row is invented; it refuses (TurnRefused, named)
while a turn process or the turns loop is alive, and when called from anywhere but that
command line. Live processes are injected; every path is under tmp_path.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import turn  # noqa: E402


@pytest.fixture
def p(tmp_path):
    state, log = tmp_path / "turn.json", tmp_path / "log.jsonl"
    state.write_text(json.dumps({"holder": "BRAIN", "seq": 74, "since_utc": "x", "why": "w"}), encoding="utf-8")
    return {"state": state, "log": log}


def rows(p):
    return [json.loads(l) for l in p["log"].read_text(encoding="utf-8").splitlines()] if p["log"].exists() else []


def cli(p, *argv, live=()):
    return turn.main(["--by-hand", *argv], path=p["state"], log_path=p["log"], live=lambda: list(live))


def test_by_hand_moves_the_baton_and_logs_it(p):
    assert cli(p, "AGENTS", "--why", "C-DOOR-2: proof") == 0
    s = turn.state(p["state"])
    assert s["holder"] == "AGENTS" and s["seq"] == 75 and "BY_HAND" in s["why"]
    assert rows(p)[-1] == {**rows(p)[-1], "event": "BY_HAND", "from": "BRAIN", "to": "AGENTS",
                           "why": "C-DOOR-2: proof", "seq": 75}


def test_no_witness_row_is_invented(p, monkeypatch):
    monkeypatch.setattr(turn, "hand_over", lambda *a, **k: pytest.fail("by-hand went through hand_over"))
    assert cli(p, "AGENTS", "--why", "x") == 0
    assert all(r["event"] == "BY_HAND" for r in rows(p))


def test_it_refuses_while_a_turn_or_the_loop_is_alive(p):
    rc = cli(p, "AGENTS", "--why", "x", live=[(4242, "scripts/turns_loop.py")])
    assert rc != 0 and turn.state(p["state"])["holder"] == "BRAIN" and rows(p) == []


def test_the_refusal_names_the_live_process(p):
    with pytest.raises(turn.TurnRefused, match="4242.*turns_loop"):
        turn.by_hand("AGENTS", "x", path=p["state"], log_path=p["log"], live=lambda: [(4242, "scripts/turns_loop.py")],
                     _from_cli=True)


def test_it_refuses_without_a_reason_or_to_the_holder_it_already_has(p):
    assert cli(p, "AGENTS") != 0
    assert cli(p, "BRAIN", "--why", "x") != 0
    assert turn.state(p["state"])["holder"] == "BRAIN"


def test_a_loop_cannot_call_it(p):
    with pytest.raises(turn.TurnRefused, match="command line"):
        turn.by_hand("AGENTS", "x", path=p["state"], log_path=p["log"], live=lambda: [])


def test_no_code_but_core_turn_calls_by_hand():
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True,
                           check=True).stdout.split()
    callers = []
    for f in files:
        if f.startswith("test/") or f == "core/turn.py" or not (REPO / f).exists():
            continue
        tree = ast.parse((REPO / f).read_text(encoding="utf-8-sig", errors="replace"))
        callers += [f for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "by_hand"]
        callers += [f for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "core.turn"
                    and any(a.name == "by_hand" for a in n.names)]
    assert callers == []


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_without_the_live_check_the_baton_moves_under_a_live_loop(p, monkeypatch):
    monkeypatch.setattr(turn, "_live_turn_processes", lambda: [])
    turn.main(["--by-hand", "AGENTS", "--why", "x"], path=p["state"], log_path=p["log"])
    assert turn.state(p["state"])["holder"] == "AGENTS"


def test_the_live_check_sees_a_turns_loop_command_line():
    class P:
        def __init__(self, pid, cmd):
            self.info = {"pid": pid, "cmdline": cmd}
    procs = [P(1, ["python.exe", "scripts\\turns_loop.py"]), P(2, ["python.exe", "-m", "pytest"]),
             P(3, ["python.exe", "scripts/turn_agents.py"])]
    assert [pid for pid, _ in turn._live_turn_processes(procs)] == [1, 3]
