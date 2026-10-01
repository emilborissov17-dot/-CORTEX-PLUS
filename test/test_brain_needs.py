# -*- coding: utf-8 -*-
"""test/test_brain_needs.py — a briefing in, well-formed needs out (C-NEED-1 Part 2).
The model is injected; every path is under tmp_path; the forward row and the
grounded ranking are fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import brain_needs as bn  # noqa: E402
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_reads(monkeypatch):
    """test/_live_net.py: a read of memory/, snapshots/ or cortex_memory/ raises and is recorded."""
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)

FIVE = ["CIVILIZATIONAL_STABILITY", "HEALTHY_ENVIRONMENTS", "KNOWLEDGE_UNDERSTANDING", "SAFETY", "SUSTAINABLE_RESOURCES"]
GROUNDED = {"ranking": [{"axis": "SOCIAL_RELATIONS_REVIEW", "key": "refugee_population", "value": 29429000.0,
                         "unit": "persons", "score": 0.034, "need": 7.728, "measured": True}]}
FORWARD = {"id": "F-001", "condition": {"dyad_name": "Government of DR Congo (Zaire) - AFC",
                                        "adm_1": ["Nord Kivu province"], "metric": "sum(best)", "kept_if": "< 25",
                                        "date_start_from": "2026-10-01", "date_start_to": "2026-10-31",
                                        "source": "UCDP GED"},
           "resolution": {"provisional": {"resolve_by": "release date + 14 days", "expected": "2026-11-20"}}}
GOOD = {"needs": [{"question": "How many refugees returned to Syria in 2026?", "why_subgoal": "SAFETY",
                   "about": {"place": "Syria", "actor": None, "period": "2026"}, "kind": "FIND",
                   "would_change": "I would lower the refugee threat"}]}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    from core import card_intake as ci
    from core import taxonomy as tx
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(tx, "subgoal_names", lambda target_path=None: set(FIVE))
    (tmp_path / "grounded.json").write_text(json.dumps(GROUNDED), encoding="utf-8")
    fw = tmp_path / "forward"; fw.mkdir()
    (fw / "F-001.json").write_text(json.dumps(FORWARD), encoding="utf-8")
    return {"needs": tmp_path / "needs.json", "refused": tmp_path / "refused.jsonl", "log": tmp_path / "log.jsonl",
            "ledger": tmp_path / "ledger.jsonl",
            "briefings": tmp_path / "briefings.jsonl", "grounded": tmp_path / "grounded.json",
            "forward_glob": str(fw / "F-[0-9]*.json"), "obs_log": tmp_path / "obs.jsonl",
            "atoms_root": tmp_path / "atoms"}


def _model(reply):
    return lambda q, ev: {"text": reply if isinstance(reply, str) else json.dumps(reply), "model": "stub", "sec": 0.1}


DERIVED = [["lacks-evidence", "F-001", "Nord Kivu province"],
           ["need-derived", "FIND", "lacks-evidence", "F-001", "Nord Kivu province"]]


def _run(paths, reply, derived=DERIVED):
    return bn.run(think=_model(reply), paths=paths, busy=lambda: None, space_run=lambda: derived)


def test_the_briefing_carries_every_fact_and_its_sha(paths):
    b = bn.briefing(paths)
    for s in ("SAFETY", "refugee_population", "7.728", "F-001", "Nord Kivu"):
        assert s in b["text"]
    assert '(forward "F-001"' in b["metta"] and len(b["sha256"]) == 64


def test_a_well_formed_reply_becomes_a_brain_need_before_engine_needs(paths):
    r = _run(paths, GOOD)
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    assert [n["origin"] for n in doc["needs"]] == ["brain", "engine"]
    n = doc["needs"][0]
    assert n["question"] == GOOD["needs"][0]["question"] and n["status"] == "OPEN"
    assert n["briefing_sha256"] == r["briefing"]["sha256"]
    assert doc["needs"][1]["kind"] == "FIND" and "F-001" in doc["needs"][1]["question"]
    assert doc["needs"][1]["premises"] == ["F-001"] and doc["needs"][1]["rule"] == "lacks-evidence"


def test_garbage_is_silence_with_the_raw_reply_and_no_need_is_invented(paths):
    r = _run(paths, "I think the system is fine and nothing is needed")
    assert r["silence"]["raw"] == "I think the system is fine and nothing is needed"
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    assert [n["origin"] for n in doc["needs"]] == ["engine"], "a brain need was invented from silence"


def test_an_empty_reply_is_silence(paths):
    r = bn.run(think=lambda q, ev: None, paths=paths, busy=lambda: None, space_run=lambda: DERIVED)
    assert r["silence"]["why"] == "empty reply"


def test_mutation_a_default_need_on_silence_would_be_caught(paths, monkeypatch):
    monkeypatch.setattr(bn, "parse_reply", lambda raw: [{"question": "What should I know?", "why_subgoal": "SAFETY"}])
    _run(paths, "garbage")
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    assert any(n["origin"] == "brain" for n in doc["needs"]), "the mutation did not invent a need"


def test_a_need_naming_no_subgoal_is_refused_by_name(paths):
    bad = {"needs": [{**GOOD["needs"][0], "why_subgoal": "WORLD_PEACE"}]}
    r = _run(paths, bad)
    assert r["refused"][0]["reason"] == "why_subgoal 'WORLD_PEACE' is not one of the five sub-goals"
    assert json.loads(paths["refused"].read_text(encoding="utf-8").splitlines()[0])["need"]["why_subgoal"] == "WORLD_PEACE"


def test_mutation_without_the_subgoal_check_it_would_be_accepted(paths, monkeypatch):
    real = bn.check_form
    monkeypatch.setattr(bn, "check_form", lambda n, t, s, five: real(n, t, s, five + [n.get("why_subgoal")]))
    r = _run(paths, {"needs": [{**GOOD["needs"][0], "why_subgoal": "WORLD_PEACE"}]})
    assert r["accepted"] and r["accepted"][0]["origin"] == "brain"


def test_a_copy_of_the_briefing_is_refused(paths):
    b = bn.briefing(paths)
    line = [l for l in b["text"].splitlines() if "refugee_population" in l][0].lstrip("- ")
    r = _run(paths, {"needs": [{**GOOD["needs"][0], "question": line}]})
    assert r["refused"][0]["reason"] == "question is a copy of the briefing"


def test_an_empty_question_is_refused(paths):
    r = _run(paths, {"needs": [{**GOOD["needs"][0], "question": "  "}]})
    assert r["refused"][0]["reason"] == "question is empty"


def test_identical_to_a_satisfied_need_is_refused(paths):
    _run(paths, GOOD)
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    doc["needs"][0]["status"] = "SATISFIED"
    paths["needs"].write_text(json.dumps(doc), encoding="utf-8")
    r = _run(paths, GOOD)
    assert r["refused"][0]["reason"] == "identical to a need already SATISFIED"


def test_more_than_five_are_refused_beyond_the_fifth(paths):
    many = {"needs": [{**GOOD["needs"][0], "question": f"Question number {i} about refugees?"} for i in range(7)]}
    r = _run(paths, many)
    assert len([a for a in r["accepted"] if a["origin"] == "brain"]) == 5
    assert [x["reason"] for x in r["refused"]] == ["over the limit of 5 needs"] * 2


def test_value_is_never_judged_an_odd_but_well_formed_need_is_kept(paths):
    odd = {"needs": [{"question": "Why do clouds look like sheep?", "why_subgoal": "KNOWLEDGE_UNDERSTANDING"}]}
    r = _run(paths, odd)
    assert [a["question"] for a in r["accepted"] if a["origin"] == "brain"] == ["Why do clouds look like sheep?"]


def test_the_model_step_is_skipped_and_logged_when_busy(paths):
    called = []
    r = bn.run(think=lambda q, ev: called.append(1), paths=paths, busy=lambda: "the big cycle is running",
               space_run=lambda: DERIVED)
    assert called == [] and r["skipped"] == "the big cycle is running"
    log = [json.loads(l) for l in paths["log"].read_text(encoding="utf-8").splitlines()]
    assert log[0]["event"] == "MODEL_SKIPPED"


def test_an_open_need_is_not_duplicated_by_a_second_pass(paths):
    _run(paths, GOOD)
    _run(paths, GOOD)
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    assert sum(1 for n in doc["needs"] if n["origin"] == "brain") == 1


def test_restating_an_open_need_is_not_a_copy_of_the_briefing(paths):
    _run(paths, GOOD)
    r = _run(paths, GOOD)
    assert not r["refused"], "the brain's own previous question was refused as a copy of the briefing"


def test_the_forward_glob_reads_rows_not_seals(paths):
    fw = Path(paths["forward_glob"]).parent
    (fw / "F-001.seal.json").write_text(json.dumps({"id": "F-001", "seal": "x"}), encoding="utf-8")
    assert [f["row"] for f in bn.forward_rows(paths)] == ["F-001"]


def test_a_paths_dict_missing_a_key_raises_instead_of_writing_live(paths):
    partial = {k: v for k, v in paths.items() if k != "ledger"}
    with pytest.raises(bn.PathMissing):
        _run(partial, GOOD)


def test_mutation_a_lenient_lookup_would_fall_back_to_the_live_path(monkeypatch):
    lenient = lambda paths, k: (paths or {}).get(k, bn.PATHS[k])
    assert lenient({"needs": "x"}, "ledger") == bn.PATHS["ledger"]


def test_mutation_the_net_catches_a_write_to_the_live_ledger(_no_live_reads):
    with pytest.raises(AssertionError, match="read live data"):
        bn._append(bn.PATHS["ledger"], {"event": "x"})
    _no_live_reads.clear()


def test_a_derived_contradiction_becomes_a_verify_need_with_its_premises(paths):
    derived = [["contradiction", "quakes", "WLD", "2026-10-01", "a-1", "a-2"],
               ["need-derived", "VERIFY", "contradiction", "quakes", "WLD", "2026-10-01", "a-1", "a-2"]]
    _run(paths, GOOD, derived)
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    v = [n for n in doc["needs"] if n["kind"] == "VERIFY"][0]
    assert v["origin"] == "engine" and v["premises"] == ["a-1", "a-2"] and "independent of both" in v["question"]


def test_the_briefing_carries_what_the_space_derived(paths):
    b = bn.briefing(paths, [["unverified", "a-1", "forest", "WLD", "2023"]])
    assert '(unverified "a-1" "forest" "WLD" "2023")' in b["text"] and "(unverified" in b["metta"]


def test_mutation_no_engine_list_no_engine_needs(paths):
    _run(paths, GOOD, derived=[])
    doc = json.loads(paths["needs"].read_text(encoding="utf-8"))
    assert [n["origin"] for n in doc["needs"]] == ["brain"], "an engine need appeared without the space"
