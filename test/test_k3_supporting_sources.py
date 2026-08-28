# -*- coding: utf-8 -*-
"""ITEM 7.2 — K3: how many claims have two or more sources behind them.

THE SHAPE IS THE STORY. memory/knowledge_base.json is keyed by AXIS and a claim
is a BARE STRING inside key_insights, so there is no object to add a field to.
Three readers consume those strings — core/hypothesis_search.py:recent_claims,
continuous_learner.get_system_knowledge, agents/core/self_observer.py:178 — and
turning the list into objects would break all three for a counter. The count
therefore rides beside the claims, keyed by the hash the file already stores,
never by list position: an index alignment nobody can see is exactly how ITEM
7.1's metric_details collision hid nine weight for months.

The properties held here:
  1. every claim carries the field, and key_insights is still a list of strings;
  2. null is not zero — "nobody recorded it" and "there were none" stay apart,
     and only integers >= 2 can ever raise K3;
  3. the count is of DISTINCT sources;
  4. the map cannot grow orphans as claims age out of the [-10:] window;
  5. the backfill is dry by default.

Nothing here touches live state; the last test proves it.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import types

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from memory import continuous_learner as cl  # noqa: E402

KB = BASE / "memory" / "knowledge_base.json"


def _digest(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


_LIVE_BEFORE = {p.as_posix(): _digest(p) for p in (
    KB,
    BASE / "memory" / "problem_solution_db.json",
    BASE / "memory" / "cycle_knowledge_log.json",
)}


def _entry(hashes, counts=None):
    e = {"cycle_count": 1,
         "key_insights": [f"claim for {h}" for h in hashes],
         "insight_hashes": list(hashes)}
    if counts is not None:
        e["supporting_source_count"] = dict(counts)
    return e


# ── the field, and what it is allowed to say ───────────────────────────────

def test_every_claim_gets_the_field_and_it_defaults_to_null():
    e = cl._sync_counts(_entry(["aaa", "bbb"]))
    assert set(e["supporting_source_count"]) == {"aaa", "bbb"}
    assert all(v is None for v in e["supporting_source_count"].values()), (
        "a claim whose sources were never recorded must be null, not 0 — "
        "0 is a measurement nobody made")


def test_null_is_not_zero_and_only_integers_can_raise_k3():
    kb = {"AX": _entry(["a", "b", "c", "d"],
                       {"a": None, "b": 0, "c": 1, "d": 2})}
    r = cl.k3(kb=kb)
    assert r == {"k3": 1, "claims": 4, "with_a_number": 3,
                 "null_not_recoverable": 1}


def test_an_empty_source_list_is_a_real_zero_not_a_null():
    e = cl._sync_counts(_entry(["aaa"]), new_hash="aaa", sources=[])
    assert e["supporting_source_count"]["aaa"] == 0, (
        "the caller asked and found none — that is knowledge, and it is not "
        "the same as never having looked")


def test_the_count_is_of_distinct_sources():
    e = cl._sync_counts(_entry(["aaa"]), new_hash="aaa",
                        sources=["NOAA", "NOAA", "WORLD_BANK"])
    assert e["supporting_source_count"]["aaa"] == 2


def test_a_claim_that_aged_out_does_not_leave_an_orphan_behind():
    """key_insights and insight_hashes are both cut to [-10:]. The map has to
    follow, or it accumulates counts for claims that no longer exist."""
    e = _entry(["new1", "new2"], {"gone": 5, "new1": 3})
    cl._sync_counts(e)
    assert set(e["supporting_source_count"]) == {"new1", "new2"}
    assert e["supporting_source_count"]["new1"] == 3, "a live count was lost"
    assert e["supporting_source_count"]["new2"] is None


def test_k3_is_one_pass_over_whatever_it_is_handed():
    kb = {f"AX{i}": _entry([f"h{i}"], {f"h{i}": 2}) for i in range(5)}
    assert cl.k3(kb=kb)["k3"] == 5


# ── the readers must survive it ────────────────────────────────────────────

def test_key_insights_is_still_a_list_of_plain_strings():
    e = cl._sync_counts(_entry(["aaa", "bbb"]), new_hash="aaa", sources=["X"])
    assert all(isinstance(s, str) for s in e["key_insights"]), (
        "converting claims to objects would break three readers for a counter")


def test_hypothesis_search_still_reads_a_kb_carrying_the_new_field():
    from core import hypothesis_search as hs
    kb = {"ENERGY_REVIEW": _entry(["aaa"], {"aaa": 2})}
    rows = hs.recent_claims("ENERGY_REVIEW", kb=kb)
    assert rows and rows[0]["claim"].startswith("claim for aaa")


# ── the writer ─────────────────────────────────────────────────────────────

def test_after_llm_call_records_the_sources_it_was_given(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "KNOWLEDGE_BASE", tmp_path / "kb.json")
    # after_llm_call imports semantic_memory inside the call and that writes a
    # real store; stub it so the fixture cannot reach live memory.
    stub = types.ModuleType("memory.semantic_memory")
    stub.remember = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "memory.semantic_memory", stub)

    cl.after_llm_call(axis="ENERGY_REVIEW",
                      llm_output="a claim long enough to be accepted by the guard",
                      sources=["NOAA", "WORLD_BANK", "NOAA"])
    kb = json.loads((tmp_path / "kb.json").read_text(encoding="utf-8"))
    counts = kb["ENERGY_REVIEW"]["supporting_source_count"]
    assert list(counts.values()) == [2]
    assert cl.k3(kb=kb)["k3"] == 1


def test_a_caller_that_names_no_sources_leaves_null_not_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "KNOWLEDGE_BASE", tmp_path / "kb.json")
    stub = types.ModuleType("memory.semantic_memory")
    stub.remember = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "memory.semantic_memory", stub)

    cl.after_llm_call(axis="ENERGY_REVIEW",
                      llm_output="a claim long enough to be accepted by the guard")
    kb = json.loads((tmp_path / "kb.json").read_text(encoding="utf-8"))
    assert list(kb["ENERGY_REVIEW"]["supporting_source_count"].values()) == [None]


# ── the backfill ───────────────────────────────────────────────────────────

def test_the_backfill_is_dry_by_default(tmp_path):
    p = tmp_path / "kb.json"
    original = {"AX": _entry(["aaa", "bbb"])}
    p.write_text(json.dumps(original), encoding="utf-8")
    before = p.read_bytes()

    rep = cl.backfill_supporting_source_count(write=False, path=p)
    assert rep["written"] is False
    assert rep["claims_with_field"] == 2
    assert p.read_bytes() == before, "a dry run wrote to disk"

    rep = cl.backfill_supporting_source_count(write=True, path=p)
    assert rep["written"] is True
    after = json.loads(p.read_text(encoding="utf-8"))
    assert after["AX"]["supporting_source_count"] == {"aaa": None, "bbb": None}


def test_the_backfill_changes_no_existing_key(tmp_path):
    p = tmp_path / "kb.json"
    original = {"AX": {"cycle_count": 7, "key_insights": ["one"],
                       "insight_hashes": ["aaa"], "scores": [{"date": "d", "score": 1}],
                       "trend": "FLAT", "last_score": 1.0, "last_updated": "2026-06-21"}}
    p.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    cl.backfill_supporting_source_count(write=True, path=p)
    after = json.loads(p.read_text(encoding="utf-8"))["AX"]
    for k, v in original["AX"].items():
        assert after[k] == v, f"{k} was modified; the field must be purely additive"
    assert after["supporting_source_count"] == {"aaa": None}


def test_the_backfill_is_idempotent(tmp_path):
    p = tmp_path / "kb.json"
    p.write_text(json.dumps({"AX": _entry(["aaa"], {"aaa": 3})}), encoding="utf-8")
    cl.backfill_supporting_source_count(write=True, path=p)
    once = p.read_bytes()
    rep = cl.backfill_supporting_source_count(write=True, path=p)
    assert p.read_bytes() == once
    assert rep["added"] == 0 and rep["orphans_dropped"] == 0
    assert json.loads(once)["AX"]["supporting_source_count"]["aaa"] == 3, (
        "a real count must survive a backfill — it only fills gaps")


# ── live state ─────────────────────────────────────────────────────────────

def test_the_real_knowledge_base_was_not_touched():
    for path, before in _LIVE_BEFORE.items():
        after = _digest(pathlib.Path(path))
        assert after == before, f"{path} MOVED during the test run"
