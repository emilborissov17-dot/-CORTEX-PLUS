# -*- coding: utf-8 -*-
"""test/test_space_witness.py — every derivation is confirmed by a second witness in plain Python,
in both directions (C-GUARD-1 Step 4, Kimi round 74 K1).

Decided: UNCONFIRMED (the engine derived what Python cannot) is not written to derived.metta and
goes to derivation_refused.jsonl; MISSING (Python derives what the engine did not) stops the run
with ENGINE_MISSED_DERIVATION. Fixtures only; the engine is injected.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import space as sp  # noqa: E402
from core import space_witness as W  # noqa: E402

TWO_SOURCES = '''
(obs "a-1" "C5.1" "quakes" "WLD" "2026-10-01" 14.0 "n" "usgs")
(obs "a-2" "C5.1" "quakes" "WLD" "2026-10-01" 15.0 "n" "emsc")
(source-class "usgs" "independent") (independent-src "usgs")
(source-class "emsc" "independent") (independent-src "emsc")
'''
SELF = '''
(obs "a-1" "C2.1" "forest" "WLD" "2023" 31.0 "pct" "wb")
(source-class "wb" "self_reported")
'''
STALE = '''
(obs "a-1" "C5.1" "k" "WLD" "2026-07-01" 1.0 "n" "s") (period-age "a-1" "day" 92)
(obs "a-2" "C5.1" "k" "WLD" "2026-09-30" 1.0 "n" "s") (period-age "a-2" "day" 1)
(obs "a-5" "C5.1" "k" "WLD" "2026-01" 1.0 "n" "s") (period-age "a-5" "month" 200)
(obs "a-3" "C2.1" "f" "WLD" "2019" 1.0 "n" "s") (period-year "a-3" 2019) (this-year 2026)
(obs "a-4" "C2.1" "f" "WLD" "2024" 1.0 "n" "s") (period-year "a-4" 2024)
'''
UNCOVERED = '''
(axis-serves "WATER_REVIEW" "SUSTAINABLE_RESOURCES") (gap "WATER_REVIEW" 5.0 0.2)
(serves "A3" "SUSTAINABLE_RESOURCES") (subcategory "A3.1" "A3")
(axis-serves "FOREST" "HEALTHY_ENVIRONMENTS") (gap "FOREST" 3.0 0.5)
(serves "C2" "HEALTHY_ENVIRONMENTS") (subcategory "C2.1" "C2")
(obs "a-1" "C2.1" "forest" "WLD" "2023" 31.0 "pct" "wb")
'''
COMMIT = '''
(commitment-place "F-001" "Nord Kivu province")
(commitment-place "F-009" "Somewhere")
(obs "a-9" "B1.1" "deaths" "Somewhere" "2026-10-01" 3.0 "n" "ucdp") (period-age "a-9" "day" 0)
'''


def keys(xs):
    return {sp._canon(x) for x in xs}


# ── one test per rule ───────────────────────────────────────────────────────
def test_contradiction():
    got = W.contradiction(W.index(TWO_SOURCES))
    assert keys(got) == {sp._canon(["contradiction", "quakes", "WLD", "2026-10-01", "a-1", "a-2"])}


def test_unverified():
    assert keys(W.unverified(W.index(SELF))) == {sp._canon(["unverified", "a-1", "forest", "WLD", "2023"])}
    assert W.unverified(W.index(SELF + '(obs "a-2" "C2.1" "forest" "WLD" "2023" 30.0 "pct" "fao")\n'
                                       '(independent-src "fao")\n')) == []


def test_stale():
    assert sorted(x[1] for x in W.stale(W.index(STALE))) == ["a-1", "a-3", "a-5"]


def test_uncovered():
    assert keys(W.uncovered(W.index(UNCOVERED))) == {("uncovered", "SUSTAINABLE_RESOURCES")}


def test_lacks_evidence():
    ix = W.index(COMMIT)
    assert keys(W.lacks_evidence(ix, W.stale(ix))) == {("lacks-evidence", "F-001", "Nord Kivu province")}


def test_need_from():
    ix = W.index(TWO_SOURCES + SELF + UNCOVERED + COMMIT)
    nd = W.need_from(W.contradiction(ix), W.unverified(ix), W.uncovered(ix), W.lacks_evidence(ix, W.stale(ix)))
    assert sorted({x[2] for x in nd}) == ["contradiction", "lacks-evidence", "uncovered", "unverified"]


def test_the_witness_imports_no_hyperon():
    tree = ast.parse((REPO / "core" / "space_witness.py").read_text(encoding="utf-8"))
    mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names] + \
           [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in mods if "hyperon" in m or m.startswith("core")], mods


# ── both directions, inside derive() ────────────────────────────────────────
def _derive(tmp_path, base, engine_out):
    d = tmp_path / "space"
    d.mkdir(exist_ok=True)
    (d / "base.metta").write_text(base, encoding="utf-8")
    (tmp_path / "r.metta").write_text("", encoding="utf-8")
    cfg = tmp_path / "g.json"
    cfg.write_text(json.dumps({"threshold": 400}), encoding="utf-8")
    return sp.derive({"dir": d, "rules": tmp_path / "r.metta", "proposed": tmp_path / "n.metta"},
                     engine=lambda prog: engine_out, guard_config=cfg)


def _true(base):
    return [sp.render(x) for x in W.witness(base)]


def test_an_agreeing_engine_is_confirmed_whole(tmp_path):
    r = _derive(tmp_path, TWO_SOURCES, _true(TWO_SOURCES))
    assert r["witness"] == {"derived": 2, "confirmed": 2, "unconfirmed": 0, "missing": 0}


def test_a_derivation_whose_premise_lacks_its_key_is_unconfirmed_and_not_written(tmp_path):
    fake = '(unverified "a-1" "quakes" "WLD" "2026-10-01")'   # a-1's source is independent: no such key
    r = _derive(tmp_path, TWO_SOURCES, _true(TWO_SOURCES) + [fake])
    assert r["witness"]["unconfirmed"] == 1
    assert fake not in (tmp_path / "space" / "derived.metta").read_text(encoding="utf-8")
    row = json.loads((tmp_path / "space" / "derivation_refused.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["rule"] == "unverified" and row["premises"] == ["a-1"] and row["reason"]


def test_a_deleted_derivation_is_missing_and_stops_the_run(tmp_path):
    with pytest.raises(sp.SpaceEngineFailed) as exc:
        _derive(tmp_path, TWO_SOURCES, [e for e in _true(TWO_SOURCES) if not e.startswith("(contradiction")])
    assert exc.value.cause == "ENGINE_MISSED_DERIVATION"
    assert not (tmp_path / "space" / "derived.metta").exists()


def test_the_counts_reach_the_guard_log(tmp_path):
    _derive(tmp_path, SELF, _true(SELF))
    row = json.loads((tmp_path / "space" / "guard_log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["witness"]["confirmed"] == 2 and row["state"] not in ("GREEN", "TRUSTED")


# ── one mutation per rule: a witness rule that derives nothing makes the engine's true answer UNCONFIRMED
@pytest.mark.parametrize("rule,base", [("contradiction", TWO_SOURCES), ("unverified", SELF), ("stale", STALE),
                                       ("uncovered", UNCOVERED), ("lacks_evidence", COMMIT),
                                       ("need_from", SELF)])
def test_mutation_an_empty_witness_rule_is_caught(tmp_path, monkeypatch, rule, base):
    truth = _true(base)
    monkeypatch.setattr(W, rule, lambda *a, **k: [])
    r = _derive(tmp_path, base, truth)
    assert r["witness"]["unconfirmed"] > 0, f"the {rule} witness is not load-bearing"
