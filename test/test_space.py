# -*- coding: utf-8 -*-
"""test/test_space.py — the space and its rules (C-TURN-1 Part 1).

Rules run in the repo's REAL hyperon (venv312_metta); each rule has one test and
one mutation that deletes the rule from config/space_rules.metta and shows its
derivation disappears. The base is handcrafted per test; nothing live is read.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import space as sp  # noqa: E402

RULES = (REPO / "config" / "space_rules.metta").read_text(encoding="utf-8")
pytestmark = pytest.mark.skipif(not sp.SIDECAR_PY.exists(), reason="venv312_metta not present")


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


def _without(rule_marker: str) -> str:
    """The rules text with the block that follows `; ── <marker>` removed (up to the next block)."""
    blocks = re.split(r"(?m)^(?=; ── )", RULES)
    kept = [b for b in blocks if not b.startswith(f"; ── {rule_marker}")]
    assert len(kept) == len(blocks) - 1, f"no rule block {rule_marker!r}"
    return "".join(kept)


def _derive(tmp_path, base: str, rules: str = RULES) -> list:
    d = tmp_path / "space"
    d.mkdir(exist_ok=True)
    (d / "base.metta").write_text(base, encoding="utf-8")
    (tmp_path / "rules.metta").write_text(rules, encoding="utf-8")
    paths = {"dir": d, "rules": tmp_path / "rules.metta", "proposed": tmp_path / "none.metta"}
    return sp.derive(paths)["expressions"]


def _heads(xs, head):
    return [x for x in xs if x[0] == head]


TWO_SOURCES = '''
(obs "a-1" "C5.1" "quakes" "WLD" "2026-10-01" 14.0 "n" "usgs")
(obs "a-2" "C5.1" "quakes" "WLD" "2026-10-01" 15.0 "n" "emsc")
(source-class "usgs" "independent") (independent-src "usgs")
(source-class "emsc" "independent") (independent-src "emsc")
'''


def test_contradiction_two_sources_different_values(tmp_path):
    c = _heads(_derive(tmp_path, TWO_SOURCES), "contradiction")
    assert len(c) == 1 and c[0][1:4] == ["quakes", "WLD", "2026-10-01"]
    assert sorted(c[0][4:]) == ["a-1", "a-2"]
    nd = [x for x in _derive(tmp_path, TWO_SOURCES) if x[0] == "need-derived" and x[2] == "contradiction"]
    assert nd and nd[0][1] == "VERIFY"


def test_one_source_moving_is_not_a_contradiction(tmp_path):
    base = TWO_SOURCES.replace('"emsc")', '"usgs")', 1)
    assert not _heads(_derive(tmp_path, base), "contradiction")


def test_mutation_without_the_contradiction_rule(tmp_path):
    assert not _heads(_derive(tmp_path, TWO_SOURCES, _without("contradiction")), "contradiction")


SELF = '''
(obs "a-1" "C2.1" "forest" "WLD" "2023" 31.0 "pct" "wb")
(source-class "wb" "self_reported")
'''


def test_unverified_self_reported_alone(tmp_path):
    u = _heads(_derive(tmp_path, SELF), "unverified")
    assert u == [["unverified", "a-1", "forest", "WLD", "2023"]]


def test_an_independent_reading_beside_it_clears_unverified(tmp_path):
    base = SELF + '(obs "a-2" "C2.1" "forest" "WLD" "2023" 31.0 "pct" "fao") (source-class "fao" "independent") (independent-src "fao")'
    assert not _heads(_derive(tmp_path, base), "unverified")


def test_mutation_without_the_unverified_rule(tmp_path):
    assert not _heads(_derive(tmp_path, SELF, _without("unverified")), "unverified")


STALE = '''
(obs "a-1" "C5.1" "k" "WLD" "2026-07-01" 1.0 "n" "s") (period-age "a-1" "day" 92)
(obs "a-2" "C5.1" "k" "WLD" "2026-09-30" 1.0 "n" "s") (period-age "a-2" "day" 1)
(obs "a-3" "C2.1" "f" "WLD" "2019" 1.0 "n" "s") (period-year "a-3" 2019) (this-year 2026)
(obs "a-4" "C2.1" "f" "WLD" "2024" 1.0 "n" "s") (period-year "a-4" 2024)
'''


def test_stale_by_granularity(tmp_path):
    s = sorted(x[1] for x in _heads(_derive(tmp_path, STALE), "stale"))
    assert s == ["a-1", "a-3"]
    assert not [x for x in _derive(tmp_path, STALE) if x[0] == "need-derived" and "stale" in x], \
        "stale became a brain need; it goes to maintenance"


def test_mutation_without_the_stale_rule(tmp_path):
    assert not _heads(_derive(tmp_path, STALE, _without("stale")), "stale")


UNCOVERED = '''
(axis-serves "WATER_REVIEW" "SUSTAINABLE_RESOURCES") (gap "WATER_REVIEW" 5.0 0.2)
(serves "A3" "SUSTAINABLE_RESOURCES") (subcategory "A3.1" "A3")
(axis-serves "FOREST" "HEALTHY_ENVIRONMENTS") (gap "FOREST" 3.0 0.5)
(serves "C2" "HEALTHY_ENVIRONMENTS") (subcategory "C2.1" "C2")
(obs "a-1" "C2.1" "forest" "WLD" "2023" 31.0 "pct" "wb")
'''


def test_uncovered_subgoal(tmp_path):
    u = _heads(_derive(tmp_path, UNCOVERED), "uncovered")
    assert u == [["uncovered", "SUSTAINABLE_RESOURCES"]]


def test_mutation_without_the_uncovered_rule(tmp_path):
    assert not _heads(_derive(tmp_path, UNCOVERED, _without("uncovered")), "uncovered")


COMMIT = '''
(commitment "F-001" "Gov - AFC" "2026-10-01" "2026-10-31" "sum(best)" "< 25")
(commitment-place "F-001" "Nord Kivu province")
(commitment "F-009" "X - Y" "2026-10-01" "2026-10-31" "sum(best)" "< 25")
(commitment-place "F-009" "Somewhere")
(obs "a-9" "B1.1" "deaths" "Somewhere" "2026-10-01" 3.0 "n" "ucdp") (period-age "a-9" "day" 0)
'''


def test_lacks_evidence_for_a_commitment_with_no_current_obs(tmp_path):
    le = _heads(_derive(tmp_path, COMMIT), "lacks-evidence")
    assert le == [["lacks-evidence", "F-001", "Nord Kivu province"]]


def test_mutation_without_the_commitment_rule(tmp_path):
    assert not _heads(_derive(tmp_path, COMMIT, _without("commitment-evidence")), "lacks-evidence")


def test_derived_needs_carry_their_premises(tmp_path):
    needs = sp.needs_from(_derive(tmp_path, TWO_SOURCES + COMMIT))
    by_rule = {n["rule"]: n for n in needs}
    assert sorted(by_rule["contradiction"]["premises"]) == ["a-1", "a-2"]
    assert by_rule["lacks-evidence"]["premises"] == ["F-001"] and by_rule["lacks-evidence"]["kind"] == "FIND"


def test_a_failing_engine_raises_and_there_is_no_fallback(tmp_path):
    d = tmp_path / "space"
    d.mkdir()
    (d / "base.metta").write_text("", encoding="utf-8")
    (tmp_path / "r.metta").write_text("", encoding="utf-8")

    def broken(program):
        raise sp.SpaceEngineFailed("hyperon exit 1")
    with pytest.raises(sp.SpaceEngineFailed):
        sp.derive({"dir": d, "rules": tmp_path / "r.metta", "proposed": tmp_path / "n.metta"}, engine=broken)


def test_mutation_a_swallowing_engine_would_hide_the_failure(tmp_path):
    d = tmp_path / "space"
    d.mkdir()
    (d / "base.metta").write_text("", encoding="utf-8")
    (tmp_path / "r.metta").write_text("", encoding="utf-8")
    r = sp.derive({"dir": d, "rules": tmp_path / "r.metta", "proposed": tmp_path / "n.metta"}, engine=lambda p: [])
    assert r["derived"] == 0, "a swallowing engine returns nothing — which is why derive() must not catch"


def test_build_writes_every_family_with_provenance(tmp_path, monkeypatch):
    import json
    from core import atoms as at
    monkeypatch.setattr(at, "read", lambda root=None, subcategory=None: iter([
        {"card_key": "abcdef1234567890", "subcategory": "C2.1", "key": "forest", "place": "WLD", "period": "2023",
         "value": 31.0, "unit": "pct", "source_id": "wb", "source_class": "self_reported", "times_seen": 2,
         "last_seen_utc": "2026-10-01T00:00:00Z"}]))
    (tmp_path / "tc.json").write_text(json.dumps({"SAFETY": {"SOCIAL_REVIEW": {}}}), encoding="utf-8")
    (tmp_path / "obs.jsonl").write_text(json.dumps({"verdict": "UNCHANGED", "identity": ["wb", "forest", "WLD", "2023", 31.0],
                                                    "since": "2026-09-30T00:00:00Z"}) + "\n", encoding="utf-8")
    (tmp_path / "g.json").write_text(json.dumps({"ranking": [{"axis": "SOCIAL_REVIEW", "need": 7.7, "score": 0.03}]}),
                                     encoding="utf-8")
    fw = tmp_path / "fw"; fw.mkdir()
    (fw / "F-001.json").write_text(json.dumps({"id": "F-001", "condition": {"dyad_name": "A - B", "adm_1": ["X"]}}),
                                   encoding="utf-8")
    (fw / "F-001.seal.json").write_text(json.dumps({"id": "F-001"}), encoding="utf-8")
    (tmp_path / "needs.json").write_text(json.dumps({"needs": [{"id": "BN-1", "origin": "brain", "kind": "FIND",
                                                                "why_subgoal": "SAFETY", "status": "OPEN"}]}), encoding="utf-8")
    paths = {"dir": tmp_path / "space", "atoms_root": None, "obs_log": tmp_path / "obs.jsonl", "grounded": tmp_path / "g.json",
             "forward_glob": str(fw / "F-*.json"), "witness_glob": str(tmp_path / "none" / "*.json"),
             "needs": tmp_path / "needs.json", "labels": tmp_path / "labels.json", "store": tmp_path / "s.jsonl",
             "target_config": tmp_path / "tc.json"}
    r = sp.build(paths)
    text = (tmp_path / "space" / "base.metta").read_text(encoding="utf-8")
    for head in ("(subgoal ", "(axis-serves ", "(domain ", "(category ", "(subcategory ", "(serves ", "(obs ",
                 "(source-class ", "(seen ", "(period-year ", "(unchanged ", "(gap ", "(commitment ",
                 "(commitment-place ", "(need "):
        assert head in text, head
    assert text.count("(commitment ") == 1, "a seal file was read as a commitment"
    lines = text.splitlines()
    assert all(lines[i - 1].startswith("; from ") for i, l in enumerate(lines) if l.startswith("("))
    assert r["expressions"] == sum(1 for l in lines if l.startswith("("))


def test_stale_sources_are_handed_to_maintenance(tmp_path):
    import json
    _derive(tmp_path, STALE)
    h = json.loads((tmp_path / "space" / "stale_for_maintenance.json").read_text(encoding="utf-8"))
    assert h == {"atoms": ["a-1", "a-3"], "sources": ["s"]}


def test_statement_lines_stay_in_base_but_are_not_sent_to_the_engine(tmp_path):
    """1 Oct 2026, 18:38: with the statement labels written, base.metta held 132,261
    expressions and hyperon panicked. No rule reads (statement ...); the engine gets
    every other line."""
    sent = []
    d = tmp_path / "space"
    d.mkdir()
    (d / "base.metta").write_text('(statement "s1" "A1.1" "who.int")\n(obs "a-1" "A1.1" "k" "WLD" "2024" 1.0 "u" "s")\n',
                                  encoding="utf-8")
    (tmp_path / "r.metta").write_text("", encoding="utf-8")
    sp.derive({"dir": d, "rules": tmp_path / "r.metta", "proposed": tmp_path / "n.metta"},
              engine=lambda prog: sent.append(prog) or [])
    assert "(obs " in sent[0] and "(statement " not in sent[0]
    assert "(statement " in (d / "base.metta").read_text(encoding="utf-8")


def test_mutation_sending_everything_would_include_the_statements(tmp_path):
    d = tmp_path / "space"
    d.mkdir()
    base = '(statement "s1" "A1.1" "who.int")\n'
    (d / "base.metta").write_text(base, encoding="utf-8")
    assert "(statement " in base and "(statement " not in sp.engine_program(base, "", "")
