# -*- coding: utf-8 -*-
"""test/test_brain_ask_model.py — C-BRAIN-ASK-1 (8 Oct 2026): when the brain's 3B is asked,
and the one alarm for a stall. Perplexity 81E/81F/81I under Emil R73.

What 81F Q2 asked the test to check, and where each is below:
  1. the old one-turn rule is ABSENT from scripts/turn_brain.py — by AST, not by prose:
     no name `nothing_new`, no `BRAIN_NOTHING_NEW` row;
  2. the new two-turn condition is PRESENT — turn_brain calls core.needs_gain.ask_model and
     turn_agents calls core.needs_gain.stalled (AST), and the constants are 2 and 5;
  3. with 0, 1 and 2 empty agents' turns the answer is ask, ask, do not ask — on the real
     files (a turns log and a vertical ledger written the way the loop and the searcher
     write them), counting (i) only: a GAINED row with statements > 0.
Then the alarm: 4 empty turns are no alarm, 5 are one alarm with cls "alarm" and a dedup
key per seq; the alarm's failure never fails the turn.
Failure paths first: a missing file means ask and no alarm — never a guessed turn.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import needs_gain as ng  # noqa: E402


# --------------------------------------------------------------------------- #
# the two files, written as the loop and the searcher write them
# --------------------------------------------------------------------------- #

def _write_turns(tmp_path, gains, *, close_last=True, cell_gain=None):
    """One agents' turn per entry: the statements its GAINED row carries (0 = a row with
    statements 0, as a page that yielded nothing writes; None = no GAINED row at all, as a
    dead searcher leaves). Each turn TAKES need N-1 first, as turn_agents writes. cell_gain
    adds to every turn a maintenance cell's GAINED row (need_id "sub:…", no TAKEN row), as
    the turn's maintenance by age writes it. A BRAIN turn sits between agents' turns."""
    tl = tmp_path / "turns_log.jsonl"
    lg = tmp_path / "ledger.jsonl"
    with tl.open("w", encoding="utf-8") as ft, lg.open("w", encoding="utf-8") as fl:
        for i, g in enumerate(gains):
            h = 10 + i
            ft.write(json.dumps({"ts": f"2026-10-08T{h:02d}:00:00Z", "event": "TURN_START", "holder": "BRAIN",
                                 "seq": 2 * i, "cycle_id": f"turn-brain-{2 * i}"}) + "\n")
            ft.write(json.dumps({"ts": f"2026-10-08T{h:02d}:20:00Z", "event": "HANDED_OVER", "from": "BRAIN",
                                 "to": "AGENTS", "seq": 2 * i + 1}) + "\n")
            ft.write(json.dumps({"ts": f"2026-10-08T{h:02d}:21:00Z", "event": "TURN_START", "holder": "AGENTS",
                                 "seq": 2 * i + 1, "cycle_id": f"turn-agents-{2 * i + 1}"}) + "\n")
            fl.write(json.dumps({"ts": f"2026-10-08T{h:02d}:22:00Z", "event": "TAKEN", "need_id": "N-1"}) + "\n")
            if cell_gain is not None:
                fl.write(json.dumps({"ts": f"2026-10-08T{h:02d}:25:00Z", "event": "GAINED", "need_id": "sub:energy/x",
                                     "statements": cell_gain, "pages": 1}) + "\n")
            if g is None:
                fl.write(json.dumps({"ts": f"2026-10-08T{h:02d}:23:00Z", "event": "SEARCHER_DEAD",
                                     "why": "gateway", "served": 0}) + "\n")
            else:
                fl.write(json.dumps({"ts": f"2026-10-08T{h:02d}:23:00Z", "event": "GAINED", "need_id": "N-1",
                                     "statements": g, "pages": 1}) + "\n")
            if close_last or i < len(gains) - 1:
                ft.write(json.dumps({"ts": f"2026-10-08T{h:02d}:40:00Z", "event": "HANDED_OVER", "from": "AGENTS",
                                     "to": "BRAIN", "seq": 2 * i + 2}) + "\n")
    return tl, lg


def _turns(tmp_path, gains, n=5, **kw):
    tl, lg = _write_turns(tmp_path, gains, **kw)
    return ng.last_turns(n, tl, lg)


# --------------------------------------------------------------------------- #
# 3. zero, one, two empty turns
# --------------------------------------------------------------------------- #

def test_zero_empty_turns_the_model_is_asked(tmp_path):
    ask, why = ng.ask_model(_turns(tmp_path, [4, 7]))
    assert ask is True and "gained" in why


def test_one_empty_turn_the_model_is_asked_whichever_of_the_two_it_is(tmp_path):
    assert ng.ask_model(_turns(tmp_path, [4, 0]))[0] is True
    assert ng.ask_model(_turns(tmp_path, [0, 4]))[0] is True


def test_two_empty_turns_in_a_row_the_model_is_not_asked(tmp_path):
    ask, why = ng.ask_model(_turns(tmp_path, [9, 0, 0]))
    assert ask is False and "2 agents' turns" in why


def test_counting_i_a_dead_searcher_is_an_empty_turn_and_the_cause_is_named(tmp_path):
    turns = _turns(tmp_path, [9, None, None])
    ask, why = ng.ask_model(turns)
    assert ask is False and "SEARCHER_DEAD" in why and turns[-1]["causes"] == ["SEARCHER_DEAD"]


def test_counting_i_is_per_need_a_maintenance_cells_gain_does_not_make_the_turn_non_empty(tmp_path):
    """81F Q3: 'no NEED has a GAINED row with statements > 0'. The turn's maintenance by age
    searches cells (sub:…, src:…) with the same searcher and writes GAINED rows for them;
    they are not needs and must not mask a stall."""
    turns = _turns(tmp_path, [0, 0], cell_gain=3)
    assert [t["empty"] for t in turns] == [True, True] and [t["cell_rows"] for t in turns] == [1, 1]
    assert [t["needs_taken"] for t in turns] == [1, 1]
    assert ng.ask_model(turns)[0] is False
    assert ng.stalled(_turns(tmp_path, [0, 0, 0, 0, 0], cell_gain=9)) is not None


def test_a_gained_row_counts_only_for_the_turn_whose_window_holds_it(tmp_path):
    turns = _turns(tmp_path, [9, 0, 0])
    assert [t["gained_rows"] for t in turns] == [1, 0, 0] and [t["statements"] for t in turns] == [9, 0, 0]
    assert [t["seq"] for t in turns] == [1, 3, 5]
    # a LATER turn's gain does not leak into an earlier, closed turn (the window's end)
    turns = _turns(tmp_path, [0, 0, 6])
    assert [t["gained_rows"] for t in turns] == [0, 0, 1] and [t["empty"] for t in turns] == [True, True, False]


def test_the_turn_running_now_has_no_closing_row_and_still_counts(tmp_path):
    turns = _turns(tmp_path, [0, 0, 6], close_last=False)
    assert turns[-1]["end"] is None and turns[-1]["empty"] is False
    assert ng.ask_model(turns)[0] is True


def test_fewer_than_two_turns_on_record_means_ask_and_no_alarm(tmp_path):
    turns = _turns(tmp_path, [0])
    assert ng.ask_model(turns)[0] is True and ng.stalled(turns) is None


def test_missing_or_unreadable_files_mean_ask_and_no_alarm_never_a_guessed_turn(tmp_path):
    assert ng.last_turns(5, tmp_path / "none.jsonl", tmp_path / "none2.jsonl") == []
    assert ng.ask_model([]) == (True, "0 agents' turn(s) on record (fewer than 2): asked")
    assert ng.stalled([]) is None
    (tmp_path / "bad.jsonl").write_text("{not json\n\n[1,2]\n", encoding="utf-8")
    assert ng.last_turns(5, tmp_path / "bad.jsonl", tmp_path / "bad.jsonl") == []


# --------------------------------------------------------------------------- #
# the one alarm: five empty turns, not four; dedup per seq
# --------------------------------------------------------------------------- #

def test_four_empty_turns_are_no_alarm_and_five_are(tmp_path):
    assert ng.stalled(_turns(tmp_path, [8, 0, 0, 0, 0])) is None
    st = ng.stalled(_turns(tmp_path, [8, 0, 0, 0, 0, 0], n=ng.STALL_LOOKBACK))
    assert st["turns"] == 5 and st["seqs"] == [3, 5, 7, 9, 11] and st["causes"] == []
    assert st["run_length"] == 5 and st["run_start_seq"] == 3


def test_a_stall_that_goes_on_keeps_the_seq_where_it_began_as_its_key(tmp_path):
    """D1: the dedup key must not move with every agents' turn, or the phone gets the same
    stall every turn; it is the first empty turn of the run."""
    st = ng.stalled(_turns(tmp_path, [8, 0, 0, 0, 0, 0, 0, 0], n=ng.STALL_LOOKBACK))
    assert st["run_length"] == 7 and st["run_start_seq"] == 3 and st["seqs"] == [7, 9, 11, 13, 15]
    st2 = ng.stalled(_turns(tmp_path, [0, 0, 0, 2, 0, 0, 0, 0, 0], n=ng.STALL_LOOKBACK))
    assert st2["run_length"] == 5 and st2["run_start_seq"] == 9


def test_the_agents_turn_sends_one_alarm_with_cls_alarm_and_a_dedup_key_per_seq(tmp_path):
    from scripts import turn_agents as ta
    tl, lg = _write_turns(tmp_path, [0, 0, 0, 0, 0])
    sent = []
    out = ta._stall_alarm(tl, lg, lambda subject, detail, key: sent.append((subject, detail, key)) or "delivered")
    assert out["sent"] == "delivered" and out["seqs"][-1] == 9 and out["run_start_seq"] == 1
    assert sent[0][0] == "NEEDS_STALLED_5_TURNS" and sent[0][2] == "NEEDS_STALLED:1" and "5 agents' turns" in sent[0][1]
    # one more empty turn: the stall goes on, the key stays the one of its first turn
    tl, lg = _write_turns(tmp_path, [0, 0, 0, 0, 0, 0])
    out = ta._stall_alarm(tl, lg, lambda subject, detail, key: sent.append((subject, detail, key)) or "delivered")
    assert out["seqs"][-1] == 11 and sent[1][2] == "NEEDS_STALLED:1"
    assert ta._stall_alarm(tl, _write_turns(tmp_path, [0, 0, 0, 0, 3])[1], lambda *a: sent.append(a)) is None
    assert len(sent) == 2


def test_a_stall_longer_than_the_lookback_keeps_its_first_seq_as_the_key(tmp_path, monkeypatch):
    """D1b: with only the last STALL_LOOKBACK turns read, a run longer than that would key on
    the oldest turn in the window, which moves every turn. The run reaching the edge makes
    the agents' turn read every turn on record."""
    from scripts import turn_agents as ta
    monkeypatch.setattr(ng, "STALL_LOOKBACK", 6)
    keys = []
    for n in (7, 8, 9):
        tl, lg = _write_turns(tmp_path, [4] + [0] * n)
        out = ta._stall_alarm(tl, lg, lambda subject, detail, key: keys.append(key) or "delivered")
        assert out["run_length"] == n
    assert keys == ["NEEDS_STALLED:3"] * 3


def test_the_live_alarm_names_cls_alarm_and_an_alarm_failure_never_fails_the_turn(tmp_path, monkeypatch):
    import supervisor as sup
    from scripts import turn_agents as ta
    seen = {}
    monkeypatch.setattr(sup, "alarm_human", lambda s, d, dedup_key=None, trigger=None, level=None, cls=None:
                        seen.update(cls=cls, key=dedup_key, level=level) or "delivered")
    assert ta._live_alarm("S", "D", "K") == "delivered" and seen == {"cls": "alarm", "key": "K", "level": sup.ALARM}
    tl, lg = _write_turns(tmp_path, [0, 0, 0, 0, 0])

    def boom(*a):
        raise RuntimeError("phone down")
    out = ta._stall_alarm(tl, lg, boom)
    assert out["sent"].startswith("failed: RuntimeError")


# --------------------------------------------------------------------------- #
# 1 + 2. the old rule absent, the new one present — by AST
# --------------------------------------------------------------------------- #

def _names_and_calls(path):
    tree = ast.parse((REPO / path).read_text(encoding="utf-8-sig"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    consts = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    return names, attrs, consts, defs


def test_the_old_one_turn_rule_is_gone_from_the_brain_turn():
    names, attrs, consts, defs = _names_and_calls("scripts/turn_brain.py")
    assert "nothing_new" not in names and "nothing_new" not in defs and "nothing_new" not in attrs
    assert "BRAIN_NOTHING_NEW" not in consts


def test_the_two_turn_condition_is_what_the_brain_turn_reads():
    names, attrs, consts, defs = _names_and_calls("scripts/turn_brain.py")
    assert "ask_model" in attrs and "last_turns" in attrs and "SKIP_AFTER_EMPTY_TURNS" in attrs
    assert "BRAIN_NOT_ASKED" in consts
    assert ng.SKIP_AFTER_EMPTY_TURNS == 2 and ng.ALARM_AFTER_EMPTY_TURNS == 5


def test_the_five_turn_alarm_is_what_the_agents_turn_reads():
    names, attrs, consts, defs = _names_and_calls("scripts/turn_agents.py")
    assert "stalled" in attrs and "STALL_LOOKBACK" in attrs and "_stall_alarm" in defs
    assert "NEEDS_STALLED_5_TURNS" in consts


def test_the_selftest_reports_its_two_files_and_reads_nothing_live(tmp_path, monkeypatch):
    monkeypatch.setattr(ng, "TURNS_LOG", tmp_path / "turns_log.jsonl")
    monkeypatch.setattr(ng, "LEDGER", tmp_path / "ledger.jsonl")
    r = ng.selftest()
    assert r["integrations"] == {"memory/turns_log.jsonl": "INERT (no file)", "memory/vertical_ledger.jsonl": "INERT (no file)"}
    assert r["ask_model"] is True and r["stalled"] is None and r["ok"] is True
    _write_turns(tmp_path, [0, 0, 0, 0, 0])
    r = ng.selftest()
    assert r["ask_model"] is False and r["stalled"]["seqs"] == [1, 3, 5, 7, 9]
