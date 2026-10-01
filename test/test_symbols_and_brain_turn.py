# -*- coding: utf-8 -*-
"""test/test_symbols_and_brain_turn.py — symbols for what the brain was shown, and
the brain's turn in order (C-TURN-1 Part 3). Model and engine are injected; every
path is under tmp_path."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import space as sp  # noqa: E402
from core import symbols  # noqa: E402

SENT = "UNHCR says 1.2 million refugees returned to Syria in 2026."
ITEMS = [{"id": "s-1", "text": SENT}]


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture
def sp_paths(tmp_path):
    v = tmp_path / "vocab.json"
    v.write_text(json.dumps({"suggested_heads": ["event", "says", "located-in"]}), encoding="utf-8")
    return {"proposed": tmp_path / "proposed.metta", "refused": tmp_path / "refused.jsonl",
            "new_relations": tmp_path / "new.jsonl", "log": tmp_path / "log.jsonl", "vocabulary": v}


def _ok_engine(program):
    return ["ok"]


def _propose(sp_paths, proposals, engine=_ok_engine, raw=None):
    text = raw if raw is not None else json.dumps({"proposals": proposals})
    return symbols.propose(ITEMS, think=lambda q, ev: {"text": text, "sec": 0.1}, engine=engine, paths=sp_paths)


def _jsonl(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()] if Path(p).exists() else []


# ── 3e ──────────────────────────────────────────────────────────────────────
def test_a_well_formed_proposal_is_accepted_and_labelled(sp_paths):
    r = _propose(sp_paths, [{"statement": "s-1", "expression": '(says "UNHCR" "1.2 million refugees returned to Syria")'}])
    assert r["accepted"] and not r["refused"]
    text = sp_paths["proposed"].read_text(encoding="utf-8")
    assert '(proposed "s-1" "cortex-l1b-3b" (says "UNHCR" "1.2 million refugees returned to Syria"))' in text


def test_an_argument_not_in_the_sentence_is_refused_by_name(sp_paths):
    r = _propose(sp_paths, [{"statement": "s-1", "expression": '(located-in "Damascus" "Syria")'}])
    assert r["refused"][0]["reason"] == "argument 'Damascus' is not a span of the sentence"
    assert _jsonl(sp_paths["refused"])[0]["reason"].startswith("argument 'Damascus'")


def test_a_number_must_appear_in_the_sentence(sp_paths):
    assert _propose(sp_paths, [{"statement": "s-1", "expression": '(event "returned" 2026)'}])["accepted"]
    r = _propose(sp_paths, [{"statement": "s-1", "expression": '(event "returned" 2027)'}])
    assert r["refused"][0]["reason"] == "the number 2027 is not in the sentence"


def test_mutation_without_the_span_check_an_invented_argument_is_accepted(sp_paths, monkeypatch):
    monkeypatch.setattr(symbols, "span_problem", lambda expr, sentence: None)
    r = _propose(sp_paths, [{"statement": "s-1", "expression": '(located-in "Damascus" "Syria")'}])
    assert r["accepted"]


def test_an_unknown_head_is_accepted_and_counted(sp_paths):
    _propose(sp_paths, [{"statement": "s-1", "expression": '(returns-to "refugees" "Syria")'}])
    r = _propose(sp_paths, [{"statement": "s-1", "expression": '(returns-to "UNHCR" "Syria")'}])
    assert r["accepted"] and r["new_heads"] == {"returns-to": 2}
    assert [x["count"] for x in _jsonl(sp_paths["new_relations"])] == [1, 2]


def test_an_unparseable_expression_is_refused(sp_paths):
    r = _propose(sp_paths, [{"statement": "s-1", "expression": 'says "UNHCR"'}])
    assert r["refused"][0]["reason"] == "the expression is not (head ...)"


def test_an_expression_the_engine_cannot_parse_is_refused(sp_paths):
    def picky(program):
        raise sp.SpaceEngineFailed("Parse error")
    r = _propose(sp_paths, [{"statement": "s-1", "expression": '(says "UNHCR")'}], engine=picky)
    assert r["refused"][0]["reason"].startswith("the engine did not parse it")


def test_silence_stays_silence(sp_paths):
    r = _propose(sp_paths, [], raw="I see refugees.")
    assert r["silence"]["raw"] == "I see refugees." and not r["accepted"]
    assert not sp_paths["proposed"].exists(), "an expression was invented from silence"


def test_a_statement_not_shown_is_refused(sp_paths):
    r = _propose(sp_paths, [{"statement": "s-99", "expression": '(says "UNHCR")'}])
    assert r["refused"][0]["reason"] == "statement 's-99' was not one of those shown"


# ── the turn in order ───────────────────────────────────────────────────────
FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]


@pytest.fixture
def turn_paths(tmp_path, monkeypatch, sp_paths):
    from core import card_intake as ci
    from core import taxonomy as tx
    from core import turn
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: set(FIVE))
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    (tmp_path / "grounded.json").write_text(json.dumps({"ranking": [{"axis": "SOCIAL", "key": "refugees", "value": 1,
                                                                      "unit": "p", "score": 0.1, "need": 7.0,
                                                                      "measured": True}]}), encoding="utf-8")
    (tmp_path / "tc.json").write_text(json.dumps({"SAFETY": {"SOCIAL": {}}}), encoding="utf-8")
    bn_paths = {"needs": tmp_path / "needs.json", "refused": tmp_path / "nrefused.jsonl", "log": tmp_path / "nlog.jsonl",
                "ledger": tmp_path / "ledger.jsonl", "briefings": tmp_path / "briefings.jsonl",
                "grounded": tmp_path / "grounded.json", "forward_glob": str(tmp_path / "none" / "F-*.json"),
                "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms"}
    space_paths = {"dir": tmp_path / "space", "rules": sp.PATHS["rules"], "atoms_root": tmp_path / "atoms",
                   "obs_log": tmp_path / "obs.jsonl", "grounded": tmp_path / "grounded.json",
                   "forward_glob": str(tmp_path / "none" / "F-*.json"), "witness_glob": str(tmp_path / "none" / "*.json"),
                   "needs": tmp_path / "needs.json", "labels": tmp_path / "labels.json", "store": tmp_path / "s.jsonl",
                   "target_config": tmp_path / "tc.json", "proposed": sp_paths["proposed"]}
    return {"bn": bn_paths, "space": space_paths, "sym": sp_paths, "result": tmp_path / "result.json",
            "expect": tmp_path / "expect.jsonl", "turn": tmp_path / "turn.json"}


def _model(calls):
    def think(q, ev):
        calls.append(q[:40])
        if "What do YOU need" in q:
            return {"text": json.dumps({"needs": [{"question": "How many refugees returned to Syria in 2026?",
                                                    "why_subgoal": "SAFETY", "from_line": "L1",
                                                    "expects": "a UNHCR count for 2026"}]}), "sec": 0.1}
        return {"text": "{}", "sec": 0.1}
    return think


def test_the_brain_turn_runs_in_order_and_writes_its_result(turn_paths):
    from scripts import turn_brain as tb
    calls = []
    r = tb.run(think=_model(calls), engine=lambda prog: [], busy=lambda: None, bn_paths=turn_paths["bn"],
               space_paths=turn_paths["space"], sym_paths=turn_paths["sym"], read=lambda q, k: [], linked={},
               result_path=turn_paths["result"], expect_path=turn_paths["expect"])
    assert r["exit"] == 0 and r["open_needs"] == 1 and r["space"]["base"] > 0
    assert calls[0].startswith("Read the briefing"), "the needs were not asked first"
    need = json.loads(turn_paths["bn"]["needs"].read_text(encoding="utf-8"))["needs"][0]
    assert need["from_line"] == "L1" and need["expects"] == "a UNHCR count for 2026"
    assert _jsonl(turn_paths["expect"])[0]["expects"] == "a UNHCR count for 2026"
    assert json.loads(turn_paths["result"].read_text(encoding="utf-8"))["open_needs"] == 1


def test_a_failed_engine_stops_the_turn_with_a_named_cause(turn_paths):
    from scripts import turn_brain as tb

    def broken(program):
        raise sp.SpaceEngineFailed("hyperon exit 1")
    r = tb.run(think=_model([]), engine=broken, busy=lambda: None, bn_paths=turn_paths["bn"],
               space_paths=turn_paths["space"], sym_paths=turn_paths["sym"], result_path=turn_paths["result"],
               expect_path=turn_paths["expect"])
    assert r["exit"] == 2 and "hyperon" in json.loads(turn_paths["result"].read_text(encoding="utf-8"))["cause"]


def test_an_unknown_from_line_is_kept_as_given_and_none_is_none():
    from core import brain_needs as bn
    assert bn._anchor("[L3]", {"L3": "x"}) == "L3"
    assert bn._anchor(None, {"L3": "x"}) == "none"
    assert bn._anchor("L99", {"L3": "x"}) == "unknown:L99"


def test_the_briefing_numbers_its_fact_lines():
    from core import brain_needs as bn
    lines, ids = bn.number_lines(["HEADING:", "- a fact", "    (expr)", "other"])
    assert lines == ["HEADING:", "[L1] - a fact", "    [L2] (expr)", "other"] and ids == {"L1": "- a fact", "L2": "(expr)"}
