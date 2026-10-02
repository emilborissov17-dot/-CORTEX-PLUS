# -*- coding: utf-8 -*-
"""test/test_small_truths.py — C-GW-1 Step 3: the ledger no longer says there is no
searcher, and two atoms with the same LABEL question are ONE need listing both.
Everything under tmp_path."""
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
from core import space as sp  # noqa: E402


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
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: {"SAFETY"})
    (tmp_path / "grounded.json").write_text(json.dumps({"ranking": []}), encoding="utf-8")
    return {"needs": tmp_path / "needs.json", "refused": tmp_path / "refused.jsonl", "log": tmp_path / "log.jsonl",
            "ledger": tmp_path / "ledger.jsonl", "briefings": tmp_path / "briefings.jsonl",
            "grounded": tmp_path / "grounded.json", "forward_glob": str(tmp_path / "none" / "F-*.json"),
            "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms"}


def ledger(p):
    return [json.loads(l) for l in p["ledger"].read_text(encoding="utf-8").splitlines()]


A1 = ["need-derived", "VERIFY", "unverified", "Kp index", "none", "none", "a-1"]
A2 = ["need-derived", "VERIFY", "unverified", "Kp index", "none", "none", "a-2"]


def test_a_new_need_is_emitted_with_no_no_searcher_row(p):
    b = bn.briefing(p, [])
    bn.emit(b, None, p, sp.needs_from([A1]))
    assert [r["event"] for r in ledger(p)] == ["EMITTED"]
    assert not hasattr(bn, "NO_SEARCHER")


def test_two_atoms_with_the_same_label_question_are_one_need_listing_both(p):
    b = bn.briefing(p, [])
    bn.emit(b, None, p, sp.needs_from([A1, A2]))
    ns = [n for n in bn.load_needs(p)["needs"] if n["status"] == "OPEN"]
    assert len(ns) == 1 and ns[0]["kind"] == "LABEL"
    assert ns[0]["premises"] == ["a-1", "a-2"] and len(ns[0]["expressions"]) == 2


def test_the_merged_need_stays_open_while_either_derivation_fires(p):
    b = bn.briefing(p, [])
    bn.emit(b, None, p, sp.needs_from([A1, A2]))
    bn.emit(b, None, p, sp.needs_from([A2]))
    assert [n["status"] for n in bn.load_needs(p)["needs"]] == ["OPEN"]
    bn.emit(b, None, p, sp.needs_from([]))
    assert [n["status"] for n in bn.load_needs(p)["needs"]] == ["ENGINE_RESOLVED"]


def test_an_old_need_reworded_into_a_held_question_is_merged_not_duplicated(p):
    b = bn.briefing(p, [])
    n1, n2 = sp.needs_from([A1, A2])
    bn.emit(b, None, p, [n1, {**n2, "question": "Verify Kp index for none, period none (old wording)"}])
    bn.emit(b, None, p, sp.needs_from([A1, A2]))
    open_ = [n for n in bn.load_needs(p)["needs"] if n["status"] == "OPEN"]
    merged = [n for n in bn.load_needs(p)["needs"] if n["status"] == "MERGED"]
    assert len(open_) == 1 and set(open_[0]["premises"]) == {"a-1", "a-2"}
    assert len(merged) == 1 and merged[0]["merged_into"] == open_[0]["id"]


def test_mutation_without_the_merge_the_second_atom_is_lost(p, monkeypatch):
    monkeypatch.setattr(bn, "_merge_engine", lambda keep, other: None)
    b = bn.briefing(p, [])
    bn.emit(b, None, p, sp.needs_from([A1, A2]))
    ns = bn.load_needs(p)["needs"]
    assert len(ns) == 1 and ns[0]["premises"] == ["a-1"]
