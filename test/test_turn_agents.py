# -*- coding: utf-8 -*-
"""test/test_turn_agents.py — the agents' turn and the category profiles
(C-TURN-1 Part 4e/4f). OpenClaw's browser, ingest, maintenance, feeds and the
model restore are injected; every path is under tmp_path."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import agent_profiles as ap  # noqa: E402

DDG = "https://duckduckgo.com/l/?uddg="


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


class FakeBrowser:
    def __init__(self, profile, seen):
        self.profile, self.seen = profile, seen

    def search(self, query):
        self.seen.append((self.profile, query))
        if "nothing" in query:
            return {"page": {"title": "r", "text": "r"}, "links": [], "raw": {}}
        return {"page": {"title": "r", "text": "r"}, "links": [{"url": DDG + "https://site.example/a"}], "raw": {}}

    def read(self, url):
        p = {"title": "t", "text": "A page about it. Second sentence.", "url": url}
        return {"page": p, "raw": {"ok": True}}


@pytest.fixture
def t(tmp_path, monkeypatch):
    from core import turn
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    needs = {"needs": [
        {"id": "EN-1", "origin": "engine", "status": "OPEN", "question": "Find current reports for commitment F-001 in Nord Kivu province",
         "premises": ["F-001"]},
        {"id": "BN-1", "origin": "brain", "status": "OPEN", "question": "How many refugees returned to Syria in 2026?",
         "about": {"place": "Syria", "actor": "UNHCR", "period": None}},
        {"id": "BN-2", "origin": "brain", "status": "OPEN", "question": "nothing will be found here"},
        {"id": "BN-3", "origin": "brain", "status": "SATISFIED", "question": "closed"}]}
    (tmp_path / "needs.json").write_text(json.dumps(needs), encoding="utf-8")
    prof = tmp_path / "agents"
    ap.generate(prof)
    b1 = json.loads((prof / "B1.json").read_text(encoding="utf-8"))
    b1["browser_profile"] = "b1-peace-and-war"
    (prof / "B1.json").write_text(json.dumps(b1), encoding="utf-8")
    seen, cells = [], []
    paths = {k: tmp_path / f"{k}.x" for k in ("refused", "log", "briefings", "grounded", "obs_log")}
    paths.update({"needs": tmp_path / "needs.json", "ledger": tmp_path / "ledger.jsonl",
                  "forward_glob": str(tmp_path / "none" / "*.json"), "atoms_root": tmp_path / "atoms"})

    def go():
        from scripts import turn_agents as ta
        return ta.run(browser_for=lambda p: FakeBrowser(p, seen), ingest=lambda *a, **k: {"added": 2},
                      bn_paths=paths, ledger_path=tmp_path / "ledger.jsonl", result_path=tmp_path / "result.json",
                      profiles_dir=prof, learned_dir=tmp_path / "learned", atom_sub={},
                      feeds=lambda: {"worker": {"rc": 0}}, restore=lambda: {"reloaded": False, "seconds": 0.0},
                      maintenance=lambda n, s: (cells.append(n) or {"worked": 0, "rows": []}),
                      pages_dir=tmp_path / "pages")
    return {"go": go, "seen": seen, "cells": cells, "tmp": tmp_path}


def test_brain_needs_first_then_engine_no_cap_and_closed_needs_skipped(t):
    r = t["go"]()
    assert [p["need_id"] for p in r["per_need"]] == ["BN-1", "BN-2", "EN-1"]
    assert t["seen"][0][1] == "How many refugees returned to Syria in 2026? UNHCR"


def test_a_b1_need_is_served_under_b1s_own_browser_profile(t):
    t["go"]()
    assert ("b1-peace-and-war", "Find current reports for commitment F-001 in Nord Kivu province") in t["seen"]
    learned = json.loads((t["tmp"] / "learned" / "B1.json").read_text(encoding="utf-8"))
    assert learned["hosts_gained"] == {"site.example": 1} and learned["attempts"] == 1


def test_a_need_with_nothing_found_stays_open_and_the_turn_still_ends(t):
    r = t["go"]()
    needs = {n["id"]: n for n in json.loads((t["tmp"] / "needs.json").read_text(encoding="utf-8"))["needs"]}
    assert needs["BN-2"]["status"] == "OPEN" and needs["BN-2"]["searched"] == 1
    assert r["exit"] == 0 and json.loads((t["tmp"] / "result.json").read_text(encoding="utf-8"))["per_need"]


def test_the_maintenance_portion_and_the_feeds_run_after_the_needs(t):
    r = t["go"]()
    assert t["cells"] == [10] and r["feeds"] == {"worker": {"rc": 0}} and r["core_restore"]["reloaded"] is False


def test_profiles_cover_all_25_categories(tmp_path):
    assert len(ap.generate(tmp_path)) == 25


def test_category_of_cells_engine_and_brain_needs():
    assert ap.category_of({"cell": "sub:C2.1"}) == "C2"
    assert ap.category_of({"premises": ["F-003"]}) == "B1"
    assert ap.category_of({"premises": ["a-1"]}, {"a-1": "A1.2"}) == "A1"
    assert ap.category_of({"question": "anything"}) == "main"


def test_learning_never_blocks_a_search(t):
    t["go"]()
    learned = t["tmp"] / "learned" / "B1.json"
    m = json.loads(learned.read_text(encoding="utf-8"))
    m["hosts_captcha"] = {"site.example": 99}
    learned.write_text(json.dumps(m), encoding="utf-8")
    t["seen"].clear()
    t["go"]()
    assert any(p == "b1-peace-and-war" for p, _ in t["seen"]), "a learned CAPTCHA host stopped the search"
