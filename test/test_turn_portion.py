# -*- coding: utf-8 -*-
"""test/test_turn_portion.py — a turn of the agents is a portion; the rest waits
in rotation (C-BRAIN-1 Part 5). Browser, ingest, maintenance, feeds, restore and
the store are injected; every path is under tmp_path.

A REFUSAL here: a portion file without a number raises (no default); a browser
that is dead after one start ends the turn with SEARCHER_DEAD, the cause named,
so the baton passes; a None argument never reaches the OpenClaw CLI.
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
from core import agent_profiles as ap  # noqa: E402

DDG = "https://duckduckgo.com/l/?uddg="


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


class FakeBrowser:
    def __init__(self, profile, log, alive=(True,)):
        self.profile, self.log, self._alive = profile, log, list(alive)

    def alive(self):
        self.log.append(("alive", self.profile))
        return self._alive.pop(0) if len(self._alive) > 1 else self._alive[0]

    def start(self):
        self.log.append(("start", self.profile))

    def stop(self):
        self.log.append(("stop", self.profile))

    def search(self, query):
        self.log.append(("search", query))
        return {"page": {"title": "r", "text": "r"}, "links": [{"url": DDG + "https://site.example/a"}], "raw": {}}

    def read(self, url):
        return {"page": {"title": "t", "text": "A page about it. Second sentence.", "url": url}, "raw": {"ok": True}}


class HealthyGateway:
    def healthy(self):
        return True

    def restart(self):
        raise AssertionError("a healthy gateway was restarted")


def _need(i, origin, kind, created, status="OPEN", **kw):
    return {"id": f"{origin[0].upper()}N-{i}", "origin": origin, "kind": kind, "status": status,
            "question": f"question {i}", "created_utc": created, **kw}


@pytest.fixture
def t(tmp_path, monkeypatch):
    from core import turn
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    por = tmp_path / "portion.json"
    por.write_text(json.dumps({k: {"value": v, "why": "test"} for k, v in (
        ("verify_per_turn", 2), ("maintenance_cells_per_turn", 3), ("embed_min_free_gb", 1.5),
        ("extractor_min_free_gb", 2.0))}), encoding="utf-8")
    needs = [_need(1, "brain", "FIND", "2026-10-01T10:00:00Z", role="parent"),
             _need(2, "brain", "FIND", "2026-10-01T11:00:00Z", role="child"),
             _need(3, "engine", "FIND", "2026-10-01T09:00:00Z"),
             _need(4, "engine", "VERIFY", "2026-10-01T08:00:00Z"),
             _need(5, "engine", "VERIFY", "2026-10-01T07:00:00Z"),
             _need(6, "engine", "VERIFY", "2026-10-01T06:00:00Z", last_served_utc="2026-10-01T12:00:00Z"),
             _need(7, "engine", "LABEL", "2026-10-01T06:00:00Z")]
    (tmp_path / "needs.json").write_text(json.dumps({"needs": needs}), encoding="utf-8")
    prof = tmp_path / "agents"
    ap.generate(prof)
    b1 = json.loads((prof / "B1.json").read_text(encoding="utf-8"))
    b1["browser_profile"] = "b1-peace-and-war"
    (prof / "B1.json").write_text(json.dumps(b1), encoding="utf-8")
    log, cells, alive = [], [], {"v": (True,)}
    paths = {k: tmp_path / f"{k}.x" for k in ("refused", "log", "briefings", "grounded", "obs_log", "shown")}
    paths.update({"needs": tmp_path / "needs.json", "ledger": tmp_path / "ledger.jsonl",
                  "forward_glob": str(tmp_path / "none" / "*.json"), "atoms_root": tmp_path / "atoms"})

    def go(**kw):
        from scripts import turn_agents as ta
        return ta.run(browser_for=lambda p: FakeBrowser(p, log, alive["v"]), ingest=lambda *a, **k: {"added": 2},
                      bn_paths=paths, ledger_path=tmp_path / "ledger.jsonl", result_path=tmp_path / "result.json",
                      turns_log=tmp_path / "turns_log.jsonl",
                      profiles_dir=prof, learned_dir=tmp_path / "learned", atom_sub={},
                      feeds=lambda: {"worker": {"rc": 0}}, restore=lambda: {"reloaded": False, "seconds": 0.0},
                      maintenance=lambda n, s: (cells.append(n) or {"worked": n, "rows": []}),
                      pages_dir=tmp_path / "pages", records_dir=tmp_path / "records", portion_path=por,
                      store_read=lambda q: [{"id": "s1"}, {"id": "s2"}], gateway=HealthyGateway(), **kw)

    def ledger():
        return [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    return {"go": go, "log": log, "cells": cells, "tmp": tmp_path, "alive": alive, "ledger": ledger, "por": por}


# ── 5a / 5b ─────────────────────────────────────────────────────────────────
def test_the_portion_order_and_the_verify_cap_longest_waiting_first(t):
    r = t["go"]()
    assert [p["need_id"] for p in r["per_need"]] == ["BN-2", "EN-3", "EN-5", "EN-4", "EN-7"]
    assert r["waited"] == 1 and "1 waited" in r["summary"]
    assert [x["need_id"] for x in t["ledger"]() if x["event"] == "WAITED"] == ["EN-6"]


def test_a_served_verify_goes_to_the_back_of_the_rotation(t):
    t["go"]()
    t["log"].clear()
    r = t["go"]()
    taken = [p["need_id"] for p in r["per_need"] if p["kind"] == "VERIFY"]
    assert taken[0] == "EN-6" and len(taken) == 2, "the need that waited longest did not come first"


def test_mutation_without_the_cap_every_verify_is_taken(t, monkeypatch):
    from scripts import turn_agents as ta
    real = ta.portion_of
    monkeypatch.setattr(ta, "portion_of", lambda needs, n, origins=None: real(needs, 99, origins))
    r = t["go"]()
    assert sum(1 for p in r["per_need"] if p["kind"] == "VERIFY") == 3


def test_the_maintenance_portion_comes_from_the_config(t):
    t["go"]()
    assert t["cells"] == [3]


def test_a_portion_file_without_a_number_raises(t):
    from core import turn
    t["por"].write_text(json.dumps({"verify_per_turn": {"value": 10}}), encoding="utf-8")
    with pytest.raises(turn.PortionMissing):
        turn.portion(t["por"])


def test_the_live_portion_file_carries_every_number_with_its_reason():
    doc = json.loads((REPO / "config" / "turn_portion.json").read_text(encoding="utf-8"))
    from core import turn
    for k in turn.PORTION_KEYS:
        assert isinstance(doc[k]["value"], (int, float)) and len(doc[k]["why"]) > 40
    assert doc["verify_per_turn"]["value"] == 10 and doc["maintenance_cells_per_turn"]["value"] == 5


def test_seconds_per_need_are_reported(t):
    r = t["go"]()
    assert all("seconds" in p for p in r["per_need"]) and r["seconds_per_need"] is not None


# ── 5e ──────────────────────────────────────────────────────────────────────
def test_a_label_need_is_served_from_the_store_without_a_browser(t):
    r = t["go"]()
    lab = [p for p in r["per_need"] if p["need_id"] == "EN-7"][0]
    assert lab["store_items"] == 2 and lab["query"] is None
    assert ("search", "question 7") not in t["log"]
    assert [x["items"] for x in t["ledger"]() if x["event"] == "LABEL_FROM_STORE"] == [["s1", "s2"]]


def test_no_query_carries_none():
    from scripts import turn_agents as ta
    q = ta.clean_query("Verify Access to electricity for none, period none, from an independent source")
    assert q == "Verify Access to electricity, from an independent source"
    assert ta.query_for({"question": "Floods in None?", "about": {"place": "None", "period": None}}) == "Floods?"


def test_mutation_without_the_query_net_none_is_searched(monkeypatch):
    from scripts import turn_agents as ta
    monkeypatch.setattr(ta, "clean_query", lambda q: q)
    assert "none" in ta.query_for({"question": "Find reports for commitment F-001 in none", "about": {}})


def test_engine_questions_carry_no_none_and_a_placeless_periodless_atom_is_a_label_need():
    from core import space as sp
    ns = sp.needs_from([["need-derived", "VERIFY", "unverified", "Access to electricity", "none", "none", "a-1"],
                        ["need-derived", "VERIFY", "unverified", "Broadband", "BGR", "none", "a-2"],
                        ["need-derived", "VERIFY", "contradiction", "quakes", "WLD", "2026", "a-3", "a-4"]])
    assert ns[0]["kind"] == "LABEL" and "none" not in ns[0]["question"].lower()
    assert ns[1]["kind"] == "VERIFY" and ns[1]["question"].startswith("Verify Broadband for BGR, from")
    assert "none" not in ns[1]["question"].lower() and ns[2]["kind"] == "VERIFY"


# ── 5d ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def bp(tmp_path, monkeypatch):
    from core import card_intake as ci
    from core import taxonomy as tx
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: {"SAFETY"})
    (tmp_path / "grounded.json").write_text(json.dumps({"ranking": []}), encoding="utf-8")
    return {"needs": tmp_path / "needs.json", "refused": tmp_path / "refused.jsonl", "log": tmp_path / "log.jsonl",
            "ledger": tmp_path / "ledger.jsonl", "briefings": tmp_path / "briefings.jsonl",
            "shown": tmp_path / "shown_to_brain.jsonl",
            "grounded": tmp_path / "grounded.json", "forward_glob": str(tmp_path / "none" / "F-*.json"),
            "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms"}


V = ["need-derived", "VERIFY", "contradiction", "quakes", "WLD", "2026", "a-1", "a-2"]


def test_an_engine_need_closes_when_its_derivation_no_longer_fires(bp):
    from core import brain_needs as bn
    from core import space as sp
    b = bn.briefing(bp, [])
    bn.emit(b, None, bp, sp.needs_from([V]))
    bn.emit(b, None, bp, sp.needs_from([]))
    n = bn.load_needs(bp)["needs"][0]
    assert n["status"] == "ENGINE_RESOLVED"
    rows = [json.loads(l) for l in bp["ledger"].read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["event"] == "ENGINE_RESOLVED" and rows[-1]["need_id"] == n["id"]


def test_an_engine_need_that_still_fires_stays_open(bp):
    from core import brain_needs as bn
    from core import space as sp
    b = bn.briefing(bp, [])
    bn.emit(b, None, bp, sp.needs_from([V]))
    bn.emit(b, None, bp, sp.needs_from([V]))
    assert [n["status"] for n in bn.load_needs(bp)["needs"]] == ["OPEN"]


def test_mutation_without_resolution_a_stale_engine_need_stays_open(bp, monkeypatch):
    from core import brain_needs as bn
    from core import space as sp
    monkeypatch.setattr(bn, "resolve_engine", lambda doc, engine, paths=None: [])
    b = bn.briefing(bp, [])
    bn.emit(b, None, bp, sp.needs_from([V]))
    bn.emit(b, None, bp, sp.needs_from([]))
    assert bn.load_needs(bp)["needs"][0]["status"] == "OPEN"


def test_a_requestioned_engine_need_is_not_duplicated(bp):
    from core import brain_needs as bn
    from core import space as sp
    b = bn.briefing(bp, [])
    old = sp.needs_from([V])[0]
    bn.emit(b, None, bp, [{**old, "question": "an older rendering of the same expression"}])
    bn.emit(b, None, bp, sp.needs_from([V]))
    ns = bn.load_needs(bp)["needs"]
    assert len(ns) == 1 and ns[0]["question"] == old["question"] and ns[0]["status"] == "OPEN"


# ── 5f ──────────────────────────────────────────────────────────────────────
def test_both_browser_profiles_are_stopped_at_the_end(t):
    r = t["go"]()
    assert {p for e, p in t["log"] if e == "stop"} == {"openclaw", "b1-peace-and-war"}
    assert set(r["browsers_stopped"].values()) == {"stopped"}


def test_a_dead_browser_is_started_once_and_the_turn_goes_on(t):
    t["alive"]["v"] = (False, False, True)       # dead; dead after the gateway check; alive after start
    r = t["go"]()
    assert r["cause"] is None and ("start", "openclaw") in t["log"]


def test_dead_after_one_start_ends_the_turn_searcher_dead_and_names_the_cause(t):
    t["alive"]["v"] = (False,)
    r = t["go"]()
    assert r["exit"] == 2 and r["cause"].startswith("SEARCHER_DEAD") and r["per_need"] == []
    assert t["log"].count(("start", "openclaw")) == 1 and t["cells"] == [] and r["feeds"] is None
    assert json.loads((t["tmp"] / "result.json").read_text(encoding="utf-8"))["cause"].startswith("SEARCHER_DEAD")
    assert {p for e, p in t["log"] if e == "stop"} == {"openclaw", "b1-peace-and-war"}


def test_mutation_without_the_liveness_check_a_dead_browser_is_searched(t, monkeypatch):
    t["alive"]["v"] = (False,)
    monkeypatch.setattr(FakeBrowser, "alive", lambda self: True)
    r = t["go"]()
    assert r["cause"] is None and any(e == "search" for e, _ in t["log"])


def test_a_none_argument_never_reaches_the_openclaw_cli(monkeypatch):
    from scripts import openclaw_search as oc
    ran = []
    monkeypatch.setattr(oc.subprocess, "run", lambda *a, **k: ran.append(a))
    b = oc.OpenClawBrowser()
    with pytest.raises(oc.OpenClawFailed, match="a None argument"):
        b._call("navigate", "https://x", "--target-id", None)
    assert ran == []


def test_open_without_a_tab_id_is_a_failure_not_a_none_tab(monkeypatch):
    from scripts import openclaw_search as oc
    b = oc.OpenClawBrowser()
    monkeypatch.setattr(b, "_call", lambda *a: {} if a[0] in ("start", "open") else {"ok": True})
    with pytest.raises(oc.OpenClawFailed, match="no tab id"):
        b._goto("https://x")


def test_the_embedding_pass_waits_and_embeds_brain_need_statements_first(tmp_path):
    from core import knowledge as kn
    store = tmp_path / "s.jsonl"
    store.write_text("\n".join(json.dumps(r) for r in [
        {"id": "a", "sentence": "plain"}, {"id": "b", "sentence": "engine", "need_id": "EN-1"},
        {"id": "c", "sentence": "brain", "need_id": "BN-1"}]) + "\n", encoding="utf-8")
    order, waits = [], []
    kn.embed_pending(embed=lambda xs: (order.extend(xs) or [[1.0, 0.0]] * len(xs)), store=store,
                     vec_path=tmp_path / "v.npy", ids_path=tmp_path / "ids.json",
                     wait=lambda: waits.append(1))
    assert order[0] == "brain" and waits == [1]


def test_should_wait_while_agents_hold_the_baton_or_memory_is_low(tmp_path):
    from core import knowledge as kn
    assert kn.embed_should_wait(holder="AGENTS", free=8.0, floor=1.5)
    assert kn.embed_should_wait(holder="BRAIN", free=1.0, floor=1.5)
    assert kn.embed_should_wait(holder="BRAIN", free=8.0, floor=1.5) is None


def test_engine_only_takes_no_brain_need(t):
    r = t["go"](origins=("engine",))
    assert r["per_need"] and all(p["origin"] == "engine" for p in r["per_need"])


def test_mutation_without_the_origin_filter_a_brain_need_is_taken(t, monkeypatch):
    from scripts import turn_agents as ta
    real = ta.portion_of
    monkeypatch.setattr(ta, "portion_of", lambda needs, n, origins=None: real(needs, n))
    r = t["go"](origins=("engine",))
    assert any(p["origin"] == "brain" for p in r["per_need"])
