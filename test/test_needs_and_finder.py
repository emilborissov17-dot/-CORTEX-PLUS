# -*- coding: utf-8 -*-
"""test/test_needs_and_finder.py — the finder serves the brain first, and the brain
is told what came back (C-NEED-1 Part 3). REWRITTEN 1 Oct 2026: the C-OC-3 ranking
(core/needs.py, emptiest cell first) was deleted on Emil's R29.

Model, search and getter are injected; every path is under tmp_path; the net in
test/_live_net.py raises on any touch of memory/, snapshots/ or cortex_memory/.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import brain_needs as bn  # noqa: E402
from scripts import openclaw_finder as fin  # noqa: E402

FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]
NEED = {"question": "How many refugees returned to Syria in 2026?", "why_subgoal": "SAFETY",
        "about": {"place": "Syria", "actor": "UNHCR", "period": "2026"}, "kind": "FIND",
        "would_change": "I would lower the refugee threat"}
PAGE = "<html><body><p>UNHCR says 1.2 million refugees returned to Syria in 2026.</p><p>Many lack housing.</p></body></html>"


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
            "obs_log": tmp_path / "obs.jsonl", "atoms_root": tmp_path / "atoms",
            "store": tmp_path / "statements.jsonl", "seen": tmp_path / "seen.json", "park": tmp_path / "park.json"}


def _bn_paths(p):
    return {k: p[k] for k in bn.PATHS}


def _emit(p, needs):
    reply = json.dumps({"needs": needs})
    return bn.run(think=lambda q, ev: {"text": reply, "model": "stub", "sec": 0.1}, paths=_bn_paths(p),
                  busy=lambda: None, read=lambda q, k: [])


def _find(p, search, getter, n=5):
    return fin.run(n=n, per_need=3, search=search, getter=getter, ledger=p["ledger"], store=p["store"],
                   seen_path=p["seen"], needs_path=p["needs"], parking=p["park"])


def _ledger(p):
    return [json.loads(l) for l in p["ledger"].read_text(encoding="utf-8").splitlines()]


def _needs(p):
    return json.loads(p["needs"].read_text(encoding="utf-8"))["needs"]


# ── 3a: brain first, and the query IS the brain's question ──────────────────
def test_brain_needs_are_served_before_engine_needs(p):
    _emit(p, [NEED])
    doc = json.loads(p["needs"].read_text(encoding="utf-8"))
    doc["needs"].append({"id": "EN-x", "origin": "engine", "status": "OPEN", "question": "Verify k"})
    doc["needs"].insert(0, doc["needs"].pop())                    # engine first on disk
    p["needs"].write_text(json.dumps(doc), encoding="utf-8")
    r = _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    assert [t["origin"] for t in r["taken"]] == ["brain", "engine"]


def test_the_query_is_the_brains_own_question_plus_its_place_actor_period():
    q = fin.query_for({**NEED, "id": "BN-1"})
    assert q == "How many refugees returned to Syria in 2026? UNHCR"


def test_mutation_a_template_query_would_lose_the_question():
    template = lambda need: f"{(need.get('about') or {}).get('place')} latest data"
    assert NEED["question"] not in template(NEED)
    assert NEED["question"] in fin.query_for({**NEED, "id": "BN-1"})


# ── 3b, 3d: ingest linked to the need; the ledger row per step ──────────────
def test_the_whole_loop_ledger_and_link(p):
    _emit(p, [NEED])
    nid = _needs(p)[0]["id"]
    _find(p, lambda q, k: [{"url": "https://unhcr.example/returns"}], lambda u, t: (200, None, None, PAGE))
    from core import knowledge as kn
    linked = [s for s in kn.statements(p["store"]) if s.get("need_id") == nid]
    assert linked and any("1.2 million" in s["sentence"] for s in linked)
    reply = json.dumps({"verdicts": [{"id": nid, "verdict": "SATISFIED", "question": None, "why": "it answers it"}]})
    rv = bn.review(think=lambda q, ev: {"text": reply, "sec": 0.1}, paths=_bn_paths(p),
                   read=lambda q, k: [{"type": "statement", "text": s["sentence"]} for s in linked][:k])
    assert rv["verdicts"] == [{"id": nid, "verdict": "SATISFIED", "recorded": True}]
    assert "1.2 million" in rv["shown_text"]
    ev = [r["event"] for r in _ledger(p) if r.get("need_id") == nid]
    assert ev == ["EMITTED", "TAKEN", "SEARCHED", "FETCHED", "GAINED", "SHOWN", "SATISFIED"]
    assert _needs(p)[0]["status"] == "SATISFIED"


def test_no_results_leaves_the_need_open_and_the_pass_continues(p):
    _emit(p, [NEED, {**NEED, "question": "What is the flow of returnees per month?"}])
    r = _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    assert len(r["taken"]) == 2, "the pass stopped at the first empty search"
    assert all(n["status"] == "OPEN" for n in _needs(p) if n["origin"] == "brain")
    assert [x["event"] for x in _ledger(p)].count("NO_RESULTS") == 2


def test_a_search_that_raises_is_no_results_with_the_reason(p):
    _emit(p, [NEED])

    def boom(q, k):
        raise TimeoutError("ddg slow")
    _find(p, boom, lambda u, t: (200, None, None, PAGE))
    nr = [x for x in _ledger(p) if x["event"] == "NO_RESULTS"][0]
    assert "TimeoutError" in nr["why"]


# ── 3c: the verdict is the brain's; code records it and never overrules ─────
def _served(p):
    _emit(p, [NEED])
    _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    return _needs(p)[0]["id"]


def test_still_open_keeps_the_need_with_the_reformulated_question(p):
    nid = _served(p)
    reply = json.dumps({"verdicts": [{"id": nid, "verdict": "STILL_OPEN", "question": "Returns to Syria from Turkey, 2026?",
                                      "why": "nothing came back"}]})
    bn.review(think=lambda q, ev: {"text": reply}, paths=_bn_paths(p), read=lambda q, k: [])
    n = _needs(p)[0]
    assert n["status"] == "STILL_OPEN" and n["question"] == "Returns to Syria from Turkey, 2026?"
    assert n["questions"][0] == NEED["question"]


def test_wrong_question_closes_it(p):
    nid = _served(p)
    reply = json.dumps({"verdicts": [{"id": nid, "verdict": "WRONG_QUESTION", "why": "the axis counts stock"}]})
    bn.review(think=lambda q, ev: {"text": reply}, paths=_bn_paths(p), read=lambda q, k: [])
    assert _needs(p)[0]["status"] == "WRONG_QUESTION"
    r = _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    assert not any(t["origin"] == "brain" for t in r["taken"]), "a closed need was searched again"


def test_a_garbled_review_changes_nothing_and_is_recorded(p):
    nid = _served(p)
    rv = bn.review(think=lambda q, ev: {"text": "looks fine to me"}, paths=_bn_paths(p), read=lambda q, k: [])
    assert rv["silence"]["raw"] == "looks fine to me"
    assert _needs(p)[0]["status"] == "OPEN"


def test_a_verdict_outside_the_three_is_not_recorded(p):
    nid = _served(p)
    reply = json.dumps({"verdicts": [{"id": nid, "verdict": "PROBABLY", "why": "?"}]})
    rv = bn.review(think=lambda q, ev: {"text": reply}, paths=_bn_paths(p), read=lambda q, k: [])
    assert rv["verdicts"][0]["recorded"] is False and _needs(p)[0]["status"] == "OPEN"


def test_mutation_a_code_that_expired_needs_by_time_would_close_it(p, monkeypatch):
    nid = _served(p)
    doc = json.loads(p["needs"].read_text(encoding="utf-8"))
    for n in doc["needs"]:
        n["created_utc"] = "2020-01-01T00:00:00Z"                 # very old
    p["needs"].write_text(json.dumps(doc), encoding="utf-8")
    r = _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    assert any(t["need_id"] == nid for t in r["taken"]), "an old need was dropped by time"


# ── unpark, fetch standard, chain, no model in the finder ───────────────────
def test_a_verify_need_naming_a_parked_source_unparks_it(p):
    from core import fetch_standard as fs
    for _ in range(3):
        fs.record("usgs:x", ok=False, err="x", path=p["park"])
    p["needs"].write_text(json.dumps({"needs": [{"id": "EN-1", "origin": "engine", "status": "OPEN",
                                                 "question": "Verify k", "source_ids": ["usgs:x"]}]}), encoding="utf-8")
    _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    assert not fs.is_parked("usgs:x", p["park"])


def test_mutation_without_unpark_the_source_stays_parked(p, monkeypatch):
    from core import fetch_standard as fs
    for _ in range(3):
        fs.record("usgs:x", ok=False, err="x", path=p["park"])
    p["needs"].write_text(json.dumps({"needs": [{"id": "EN-1", "origin": "engine", "status": "OPEN",
                                                 "question": "Verify k", "source_ids": ["usgs:x"]}]}), encoding="utf-8")
    monkeypatch.setattr(fs, "unpark", lambda *a, **k: None)
    _find(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE))
    assert fs.is_parked("usgs:x", p["park"])


def test_the_default_fetch_goes_through_the_fetch_standard(monkeypatch):
    from core import fetch_standard as fs
    calls = []
    monkeypatch.setattr(fs, "get", lambda url, **kw: calls.append(url) or (_ for _ in ()).throw(fs.FetchRefused("lan")))
    r = fin._fetch("http://192.168.0.1/")
    assert calls == ["http://192.168.0.1/"] and "REFUSED_BY_FETCH_STANDARD" in r["err"]


def test_no_model_is_imported_by_the_finder():
    banned = {"ollama", "openai", "anthropic", "core.brain", "core.llm_door", "core.data_scout"}
    tree = ast.parse((REPO / "scripts" / "openclaw_finder.py").read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & banned


def test_mutation_a_chain_without_the_finder_is_seen(tmp_path):
    bat = tmp_path / "c.bat"
    lines = ["rem openclaw_finder.py in a comment", r"%PY% scripts\openclaw_axis_worker.py", r"%PY% core\card_intake.py"]
    bat.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    assert fin.chain_steps(bat) == ["openclaw_axis_worker.py", "card_intake.py"]


def test_re_asking_a_wrong_question_reopens_it_and_keeps_its_history(p):
    nid = _served(p)
    reply = json.dumps({"verdicts": [{"id": nid, "verdict": "WRONG_QUESTION", "why": "too general"}]})
    bn.review(think=lambda q, ev: {"text": reply}, paths=_bn_paths(p), read=lambda q, k: [])
    _emit(p, [NEED])                                   # the brain asks the very same question again
    n = [x for x in _needs(p) if x["id"] == nid][0]
    assert n["status"] == "OPEN"
    assert [v["verdict"] for v in n["verdicts"]] == ["WRONG_QUESTION"], "the verdict history was erased"
    assert len(n["reopened"]) == 1 and n["searched"] == 1
    ev = [r["event"] for r in _ledger(p) if r.get("need_id") == nid]
    assert ev[-1] == "REOPENED"
