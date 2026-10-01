# -*- coding: utf-8 -*-
"""test/test_brain_needs_review.py — the brain is told what came back for its
needs and judges them (C-NEED-1 Part 3c, kept when the Python finder was deleted
on Emil's R34). A need is marked served with core.brain_needs.mark_served — the
call any searcher makes; there is no searcher in these tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import brain_needs as bn  # noqa: E402

FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]
NEED = {"question": "How many refugees returned to Syria in 2026?", "why_subgoal": "SAFETY",
        "about": {"place": "Syria", "actor": "UNHCR", "period": "2026"}, "kind": "FIND",
        "would_change": "I would lower the refugee threat"}


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture
def p(tmp_path, monkeypatch):
    from core import card_intake as ci
    from core import taxonomy as tx
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: set(FIVE))
    (tmp_path / "grounded.json").write_text(json.dumps({"ranking": []}), encoding="utf-8")
    return {"needs": tmp_path / "needs.json", "refused": tmp_path / "refused.jsonl", "log": tmp_path / "log.jsonl",
            "ledger": tmp_path / "ledger.jsonl", "briefings": tmp_path / "briefings.jsonl",
            "grounded": tmp_path / "grounded.json", "forward_glob": str(tmp_path / "none" / "F-*.json"),
            "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms"}


def _ok(d):
    return {"data": d, "raw": json.dumps(d), "model": "stub", "sec": 0.1}


def _verdict(verdict, why="w", nq=None):
    """think(prompt, evidence, schema) answering TEXT C with one verdict."""
    return lambda pr, ev, sc: _ok({"verdict": verdict, "narrower_question": nq, "why": why})


def _emit(p, needs):
    full = [{"from_line": "L1", "expects": "e", **n} for n in needs]
    return bn.run(think=lambda q, ev, sc: _ok({"needs": full}), paths=p,
                  busy=lambda: None, read=lambda q, k: [], space_run=lambda: [], linked={})


def _needs(p):
    return json.loads(p["needs"].read_text(encoding="utf-8"))["needs"]


def _ledger(p):
    return [json.loads(l) for l in p["ledger"].read_text(encoding="utf-8").splitlines()]


def _served(p):
    _emit(p, [NEED])
    nid = _needs(p)[0]["id"]
    bn.mark_served(nid, NEED["question"], 1, 1, 2, p)
    return nid


def test_a_new_need_says_there_is_no_searcher(p):
    _emit(p, [NEED])
    nid = _needs(p)[0]["id"]
    rows = [r for r in _ledger(p) if r.get("need_id") == nid]
    assert [r["event"] for r in rows] == ["EMITTED", "NO_SEARCHER"]
    assert "Python finder was removed" in rows[1]["why"] and _needs(p)[0]["status"] == "OPEN"


def test_mark_served_counts_and_never_changes_the_status(p):
    nid = _served(p)
    n = _needs(p)[0]
    assert (n["searched"], n["gained_statements"], n["status"]) == (1, 2, "OPEN")


def test_satisfied_is_recorded_with_the_items_shown(p):
    nid = _served(p)
    rv = bn.review(think=_verdict("SATISFIED", "it answers it"), paths=p, linked={},
                   read=lambda q, k: [{"type": "statement", "text": "UNHCR: 1.2 million returned in 2026."}])
    assert rv["verdicts"] == [{"id": nid, "verdict": "SATISFIED", "recorded": True}]
    assert "1.2 million" in rv["calls"][0]["shown"] and _needs(p)[0]["status"] == "SATISFIED"
    assert [r["event"] for r in _ledger(p) if r.get("need_id") == nid][-2:] == ["SHOWN", "SATISFIED"]


def test_still_open_with_a_narrower_question_keeps_the_need_and_adds_a_child(p):
    nid = _served(p)
    bn.review(think=_verdict("STILL_OPEN", "nothing came back", "Returns to Syria from Turkey, 2026?"), paths=p,
              read=lambda q, k: [], linked={})
    n = [x for x in _needs(p) if x["id"] == nid][0]
    assert n["status"] == "STILL_OPEN" and n["question"] == NEED["question"]
    assert [x["question"] for x in _needs(p) if x.get("parent") == nid] == ["Returns to Syria from Turkey, 2026?"]


def test_wrong_question_closes_it(p):
    _served(p)
    bn.review(think=_verdict("WRONG_QUESTION", "the axis counts stock"), paths=p, read=lambda q, k: [], linked={})
    assert _needs(p)[0]["status"] == "WRONG_QUESTION"


def test_a_garbled_review_changes_nothing_and_is_recorded(p):
    _served(p)
    rv = bn.review(think=lambda pr, ev, sc: {"unreadable": "not JSON", "raw": "looks fine to me"}, paths=p,
                   read=lambda q, k: [], linked={})
    assert rv["calls"][0]["raw"] == "looks fine to me" and _needs(p)[0]["status"] == "OPEN"


def test_a_verdict_outside_the_three_is_not_recorded(p):
    _served(p)
    rv = bn.review(think=_verdict("PROBABLY", "?"), paths=p, read=lambda q, k: [], linked={})
    assert rv["verdicts"][0]["recorded"] is False and _needs(p)[0]["status"] == "OPEN"
    assert rv["verdicts"][0]["why_not"].startswith("schema-invalid")


def test_an_unserved_need_is_not_shown_for_review(p):
    _emit(p, [NEED])
    rv = bn.review(think=_verdict("SATISFIED"), paths=p, read=lambda q, k: [], linked={})
    assert rv["shown"] == 0


def test_re_asking_a_wrong_question_reopens_it_and_keeps_its_history(p):
    nid = _served(p)
    bn.review(think=_verdict("WRONG_QUESTION", "too general"), paths=p, read=lambda q, k: [], linked={})
    _emit(p, [NEED])
    n = [x for x in _needs(p) if x["id"] == nid][0]
    assert n["status"] == "OPEN" and [v["verdict"] for v in n["verdicts"]] == ["WRONG_QUESTION"]
    assert len(n["reopened"]) == 1 and n["searched"] == 1
    assert [r["event"] for r in _ledger(p) if r.get("need_id") == nid][-1] == "REOPENED"


def test_no_finder_module_exists_and_nothing_imports_one():
    import ast
    gone = "openclaw" + "_finder"                      # the deleted module's name, assembled
    assert not (REPO / "scripts" / f"{gone}.py").exists()
    for f in list((REPO / "core").glob("*.py")) + list((REPO / "scripts").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        names = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        assert gone not in names and not any(gone in m for m in mods), f.name


def test_what_was_fetched_for_the_need_is_shown_first(p):
    nid = _served(p)
    linked = {nid: [{"type": "statement", "text": "FETCHED FOR THIS NEED", "id": "s-own", "linked": True}]}
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked=linked,
                   read=lambda q, k: [{"type": "statement", "text": "an unrelated transcript fragment", "id": "s-x"}])
    assert [i["text"] for i in rv["items"][nid]] == ["FETCHED FOR THIS NEED", "an unrelated transcript fragment"]


def test_mutation_without_the_linked_first_rule_the_fragment_leads(p):
    nid = _served(p)
    rv = bn.review(think=_verdict("STILL_OPEN"), paths=p, linked={},
                   read=lambda q, k: [{"type": "statement", "text": "an unrelated transcript fragment", "id": "s-x"}])
    assert rv["items"][nid][0]["text"] == "an unrelated transcript fragment"


def test_linked_statements_indexes_records_by_need_id(monkeypatch):
    from core import knowledge as kn
    monkeypatch.setattr(kn, "region_index", lambda path=None: {})
    monkeypatch.setattr(kn, "statements", lambda store=None: [
        {"id": "s1", "sentence": "for the need", "need_id": "BN-1"},
        {"id": "s2", "sentence": "for nothing"}])
    assert bn.linked_statements() == {"BN-1": [{"type": "statement", "text": "for the need", "id": "s1", "linked": True,
                                                "region": "unknown"}]}
