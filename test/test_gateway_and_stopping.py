# -*- coding: utf-8 -*-
"""test/test_gateway_and_stopping.py — C-GW-1 Step 1: a dead gateway is restarted
once; a loop that learns nothing stops; the brain's 3B is asked unless two agents'
turns in a row gained nothing (C-BRAIN-ASK-1, 8 Oct 2026, replacing C-GW-1 1c).
Gateway, browsers, turns and the model are injected; every path is under tmp_path.

A REFUSAL here: a gateway that is still dead after its one restart ends the turn
GATEWAY_DEAD (never a second restart, never "no results"); three agents' turns with
the same cause and nothing served stop the loop with one alarm; two empty agents'
turns in a row and the brain turn calls no model.
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


class Browser:
    def __init__(self, profile, log, alive):
        self.profile, self.log, self._alive = profile, log, alive

    def alive(self):
        return self._alive["v"]

    def start(self):
        self.log.append(("start", self.profile))

    def stop(self):
        self.log.append(("stop", self.profile))

    def search(self, query):
        self.log.append(("search", query))
        return {"page": {"title": "r", "text": "r"}, "links": [{"url": DDG + "https://site.example/a"}], "raw": {}}

    def read(self, url):
        return {"page": {"title": "t", "text": "A page. Two.", "url": url}, "raw": {"ok": True}}


class Gateway:
    def __init__(self, health, alive, log, revive=True):
        self.health, self._alive, self.log, self.revive = list(health), alive, log, revive
        self.restarts = 0

    def healthy(self):
        self.log.append(("health",))
        return self.health.pop(0) if len(self.health) > 1 else self.health[0]

    def restart(self):
        self.restarts += 1
        self.log.append(("restart",))
        if self.revive:
            self.health = [True]
            self._alive["v"] = True


@pytest.fixture
def t(tmp_path, monkeypatch):
    from core import turn
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    por = tmp_path / "portion.json"
    por.write_text(json.dumps({k: {"value": v, "why": "t"} for k, v in (
        ("verify_per_turn", 10), ("maintenance_cells_per_turn", 1), ("embed_min_free_gb", 1.5),
        ("extractor_min_free_gb", 2.0))}), encoding="utf-8")
    needs = [{"id": f"EN-{i}", "origin": "engine", "kind": "FIND", "status": "OPEN", "question": f"q{i}",
              "created_utc": "2026-10-01T00:00:00Z"} for i in range(3)]
    (tmp_path / "needs.json").write_text(json.dumps({"needs": needs}), encoding="utf-8")
    prof = tmp_path / "agents"
    ap.generate(prof)
    log, alive = [], {"v": False}
    paths = {k: tmp_path / f"{k}.x" for k in ("refused", "log", "briefings", "grounded", "obs_log", "shown")}
    paths.update({"needs": tmp_path / "needs.json", "ledger": tmp_path / "ledger.jsonl",
                  "forward_glob": str(tmp_path / "none" / "*.json"), "atoms_root": tmp_path / "atoms"})

    def go(gw):
        from scripts import turn_agents as ta
        return ta.run(browser_for=lambda p: Browser(p, log, alive), ingest=lambda *a, **k: {"added": 2},
                      bn_paths=paths, ledger_path=tmp_path / "ledger.jsonl", result_path=tmp_path / "result.json",
                      turns_log=tmp_path / "turns_log.jsonl",
                      profiles_dir=prof, learned_dir=tmp_path / "learned", atom_sub={},
                      feeds=lambda: {}, restore=lambda: {}, maintenance=lambda n, s: {"worked": 0, "rows": []},
                      pages_dir=tmp_path / "pages", records_dir=tmp_path / "records", portion_path=por,
                      store_read=lambda q: [], gateway=gw)

    def ledger():
        return [json.loads(l) for l in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    return {"go": go, "log": log, "alive": alive, "ledger": ledger}


# ── 1a ──────────────────────────────────────────────────────────────────────
def test_a_dead_gateway_is_restarted_once_and_the_turn_goes_on(t):
    gw = Gateway([False], t["alive"], t["log"])
    r = t["go"](gw)
    assert gw.restarts == 1 and r["cause"] is None and len(r["per_need"]) == 3
    row = [x for x in t["ledger"]() if x["event"] == "GATEWAY_RESTARTED"][0]
    assert isinstance(row["seconds"], float)


def test_still_dead_after_the_restart_ends_the_turn_gateway_dead(t):
    gw = Gateway([False], t["alive"], t["log"], revive=False)
    r = t["go"](gw)
    assert gw.restarts == 1 and r["exit"] == 2 and r["cause"].startswith("GATEWAY_DEAD")
    assert not r["cause"].startswith("SEARCHER_DEAD") and r["per_need"] == []


def test_the_gateway_is_restarted_at_most_once_per_turn(t):
    gw = Gateway([False], t["alive"], t["log"])
    real_restart = gw.restart

    def restart_then_die_again():
        real_restart()
        gw.health, t["alive"]["v"] = [True, False], False    # alive for one need, then gone again
    gw.restart = restart_then_die_again
    r = t["go"](gw)
    assert gw.restarts == 1 and r["cause"].startswith("GATEWAY_DEAD")


def test_mutation_without_the_once_guard_it_would_restart_again(t, monkeypatch):
    from scripts import turn_agents as ta
    monkeypatch.setattr(ta, "MAX_GATEWAY_RESTARTS", 99)
    gw = Gateway([False], t["alive"], t["log"])
    real_restart = gw.restart

    def restart_then_die_again():
        real_restart()
        gw.health, t["alive"]["v"] = [True, False], False
    gw.restart = restart_then_die_again
    t["go"](gw)
    assert gw.restarts > 1


def test_a_healthy_gateway_with_a_dead_browser_is_still_searcher_dead(t):
    gw = Gateway([True], t["alive"], t["log"])
    r = t["go"](gw)
    assert gw.restarts == 0 and r["cause"].startswith("SEARCHER_DEAD")


def test_the_gateway_health_parses_ok_true_only():
    from scripts import openclaw_search as oc
    assert oc.Gateway.parse_health('{"ok": true, "ts": 1}') is True
    assert oc.Gateway.parse_health('{"ok": false}') is False
    assert oc.Gateway.parse_health("gateway timeout after 30000ms") is False


# ── 1b ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def lp(tmp_path, monkeypatch):
    from core import turn
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    turn._save({"holder": "AGENTS", "seq": 1}, tmp_path / "turn.json")
    return tmp_path


def _loop(lp, results, health=lambda cause: None, alarms=None, max_turns=20):
    from core import turn
    from scripts import turns_loop as tl
    seq = iter(results)

    def run_turn(holder, cycle_id):
        r = next(seq) if holder == "AGENTS" else {"summary": "brain", "cause": None, "per_need": []}
        (lp / "result.json").write_text(json.dumps({"utc": tl._now(), **r}), encoding="utf-8")
        return 0

    def hand(to, summary, cycle_id, cause=None, path=None, log_path=None):
        s = turn.state(path)
        turn._save({"holder": to, "seq": int(s.get("seq") or 0) + 1}, path)
        return {"handed": True}
    return tl.loop(max_turns=max_turns, run_turn=run_turn, blocked=lambda: None, sleep=lambda s: None,
                   turn_path=lp / "turn.json", result_path=lp / "result.json", stop_path=lp / "stop",
                   hand=hand, log_path=lp / "log.jsonl", health=health,
                   alarm=lambda *a: (alarms.append(a) if alarms is not None else None) or "sent")


DEAD = {"summary": "a", "cause": "GATEWAY_DEAD: x", "per_need": []}


def test_three_agents_turns_with_the_same_cause_and_nothing_served_stop_the_loop(lp):
    alarms = []
    r = _loop(lp, [DEAD] * 5, alarms=alarms)
    assert r["stopped"] == "same cause" and sum(1 for x in r["turns"] if x["holder"] == "AGENTS") == 3
    rows = [json.loads(l) for l in (lp / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x for x in rows if x["event"] == "LOOP_STOPPED_SAME_CAUSE"][0]["cause"] == "GATEWAY_DEAD: x"
    assert len(alarms) == 1


def test_a_turn_that_served_something_breaks_the_run(lp):
    ok = {"summary": "a", "cause": "GATEWAY_DEAD: x", "per_need": [{"need_id": "EN-1"}]}
    r = _loop(lp, [DEAD, DEAD, ok, DEAD, DEAD, DEAD], max_turns=8)
    assert r.get("stopped") is None


def test_different_causes_do_not_stop_it(lp):
    other = {"summary": "a", "cause": "SEARCHER_DEAD: y", "per_need": []}
    r = _loop(lp, [DEAD, other, DEAD, other], max_turns=8)
    assert r.get("stopped") is None


def test_the_loop_resumes_when_the_health_check_of_that_cause_passes(lp):
    checks = iter([False, True])
    ok = {"summary": "a", "cause": None, "per_need": [{"need_id": "EN-1"}]}
    r = _loop(lp, [DEAD] * 3 + [ok] * 3, health=lambda cause: next(checks), max_turns=10)
    rows = [json.loads(l)["event"] for l in (lp / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "LOOP_STOPPED_SAME_CAUSE" in rows and "LOOP_RESUMED" in rows and r.get("stopped") is None


def test_mutation_without_the_same_cause_rule_the_loop_spins(lp, monkeypatch):
    from scripts import turns_loop as tl
    monkeypatch.setattr(tl, "SAME_CAUSE_TURNS", 99)
    r = _loop(lp, [DEAD] * 10, max_turns=12)
    assert r.get("stopped") is None and len(r["turns"]) == 12


# ── 1c ──────────────────────────────────────────────────────────────────────
FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]


@pytest.fixture
def bt(tmp_path, monkeypatch):
    from core import card_intake as ci
    from core import space as sp
    from core import taxonomy as tx
    from core import turn
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: set(FIVE))
    monkeypatch.setattr(turn, "STATE", tmp_path / "turn.json")
    (tmp_path / "grounded.json").write_text(json.dumps({"ranking": []}), encoding="utf-8")
    (tmp_path / "tc.json").write_text(json.dumps({"SAFETY": {"SOCIAL": {}}}), encoding="utf-8")
    (tmp_path / "needs.json").write_text(json.dumps({"needs": [
        {"id": "BN-1", "origin": "brain", "role": "parent", "status": "OPEN", "question": "What is safe?",
         "why_subgoal": "SAFETY", "searched": 1, "gained_statements": 4}]}), encoding="utf-8")
    v = tmp_path / "vocab.json"
    v.write_text(json.dumps({"suggested_heads": ["says"]}), encoding="utf-8")
    bn_paths = {"needs": tmp_path / "needs.json", "refused": tmp_path / "nrefused.jsonl", "log": tmp_path / "nlog.jsonl",
                "ledger": tmp_path / "ledger.jsonl", "briefings": tmp_path / "briefings.jsonl",
            "shown": tmp_path / "shown_to_brain.jsonl",
                "grounded": tmp_path / "grounded.json", "forward_glob": str(tmp_path / "none" / "F-*.json"),
                "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms"}
    space_paths = {"dir": tmp_path / "space", "rules": sp.PATHS["rules"], "atoms_root": tmp_path / "atoms",
                   "obs_log": tmp_path / "obs.jsonl", "grounded": tmp_path / "grounded.json",
                   "forward_glob": str(tmp_path / "none" / "F-*.json"), "witness_glob": str(tmp_path / "none" / "*.json"),
                   "needs": tmp_path / "needs.json", "labels": tmp_path / "labels.json", "store": tmp_path / "s.jsonl",
                   "target_config": tmp_path / "tc.json", "proposed": tmp_path / "proposed.metta"}
    sym = {"proposed": tmp_path / "proposed.metta", "refused": tmp_path / "srefused.jsonl",
           "new_relations": tmp_path / "new.jsonl", "log": tmp_path / "slog.jsonl", "vocabulary": v,
           "ledger": tmp_path / "ledger.jsonl"}
    calls = []

    def think(q, ev, schema):
        calls.append(q[:30])
        d = {"verdict": "STILL_OPEN", "narrower_question": None, "why": "w"}
        return {"data": d, "raw": json.dumps(d), "sec": 0.1}

    def go():
        from scripts import turn_brain as tb
        return tb.run(think=think, engine=lambda prog: [], busy=lambda: None, bn_paths=bn_paths,
                      space_paths=space_paths, sym_paths=sym, read=lambda q, k: [], linked={},
                      result_path=tmp_path / "result.json", expect_path=tmp_path / "expect.jsonl",
                      records_dir=tmp_path / "records", gained_path=tmp_path / "gained.json",
                      turns_log=tmp_path / "turns_log.jsonl", filled_path=tmp_path / "needs_filled.jsonl")

    def gain(n):
        d = json.loads((tmp_path / "needs.json").read_text(encoding="utf-8"))
        d["needs"][0]["gained_statements"] += n
        (tmp_path / "needs.json").write_text(json.dumps(d), encoding="utf-8")

    def ledger():
        p = tmp_path / "ledger.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []

    counter = {"n": 0}

    def agents_turns(gains):
        """C-BRAIN-ASK-1: one agents' turn per entry in `gains` (statements the turn's GAINED
        row carries; 0 = a turn that gained nothing), written as the loop's log and the
        vertical ledger write them."""
        tl = tmp_path / "turns_log.jsonl"
        lg = tmp_path / "ledger.jsonl"
        with tl.open("a", encoding="utf-8") as ft, lg.open("a", encoding="utf-8") as fl:
            for g in gains:
                i = counter["n"]
                counter["n"] += 1
                t0 = f"2026-10-08T10:{i:02d}:00Z"
                ft.write(json.dumps({"ts": t0, "event": "TURN_START", "holder": "AGENTS", "seq": 100 + i}) + "\n")
                fl.write(json.dumps({"ts": f"2026-10-08T10:{i:02d}:20Z", "event": "TAKEN", "need_id": "BN-1",
                                     "origin": "brain"}) + "\n")
                fl.write(json.dumps({"ts": f"2026-10-08T10:{i:02d}:30Z", "event": "GAINED", "need_id": "BN-1",
                                     "statements": g, "pages": 1}) + "\n")
                ft.write(json.dumps({"ts": f"2026-10-08T10:{i:02d}:59Z", "event": "HANDED_OVER", "from": "AGENTS",
                                     "to": "BRAIN", "seq": 101 + i}) + "\n")
    return {"go": go, "calls": calls, "gain": gain, "ledger": ledger, "agents_turns": agents_turns,
            "filled": tmp_path / "needs_filled.jsonl"}


def test_the_brain_is_asked_with_no_agents_turn_on_record_and_again_after_a_gain(bt):
    """C-BRAIN-ASK-1 (Perplexity 81F Q1, formulation A): asked by default; the one-turn
    rule of C-GW-1 1c (the brain's own counters) is gone — a second brain turn with the
    counters unchanged still asks."""
    r = bt["go"]()
    first = len(bt["calls"])
    assert first > 0 and r["ask_model"]["asked"] is True
    r = bt["go"]()
    assert len(bt["calls"]) == 2 * first and r["ask_model"]["asked"] is True
    assert not any(x["event"] in ("BRAIN_NOTHING_NEW", "BRAIN_NOT_ASKED") for x in bt["ledger"]())


def test_two_empty_agents_turns_in_a_row_skip_the_model_and_one_gain_asks_again(bt):
    bt["agents_turns"]([5, 0, 0])
    r = bt["go"]()
    assert r["ask_model"]["asked"] is False and len(bt["calls"]) == 0 and r["exit"] == 0
    assert any(x["event"] == "BRAIN_NOT_ASKED" for x in bt["ledger"]())
    bt["agents_turns"]([3])
    r = bt["go"]()
    assert r["ask_model"]["asked"] is True and len(bt["calls"]) > 0


def test_every_brain_turn_writes_one_needs_filled_row_with_the_stale_marker(bt):
    bt["go"]()
    bt["gain"](3)
    bt["go"]()
    rows = [json.loads(l) for l in bt["filled"].read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and [r["asked"] for r in rows] == [True, True]
    first, second = rows[0]["needs"][0], rows[1]["needs"][0]
    assert first["id"] == "BN-1" and first["gained_since_last_brain_turn"] == 4 and first["stale"] is False
    assert second["gained_since_last_brain_turn"] == 3 and second["stale"] is False
    assert "would_change" in second
    # C-SHOWN-1 (82B): this fixture's need has no linked statements and the store read is empty,
    # so the 3B is not asked about it and the row says so, with the counts
    assert second["reviewed_no_new_context"] is True and second["review_verdict"] is None
    assert (second["linked_count"], second["context_count"], second["shown_ids"]) == (0, 0, [])
    assert second["search_attempts"] == 1
    bt["go"]()
    third = [json.loads(l) for l in bt["filled"].read_text(encoding="utf-8").splitlines()][2]["needs"][0]
    assert third["gained_since_last_brain_turn"] == 0 and third["stale"] is True


def test_mutation_without_the_two_turn_check_the_model_is_asked_after_two_empty_turns(bt, monkeypatch):
    from core import needs_gain as ng
    monkeypatch.setattr(ng, "ask_model", lambda turns: (True, "mutated"))
    bt["agents_turns"]([0, 0])
    bt["go"]()
    assert len(bt["calls"]) > 0


def test_the_net_stops_a_test_that_reaches_the_live_openclaw_cli(_no_live):
    from scripts import openclaw_search as oc
    with pytest.raises(AssertionError, match="live OpenClaw CLI"):
        oc.Gateway().healthy()
    _no_live.clear()
