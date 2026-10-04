# -*- coding: utf-8 -*-
"""test/test_engine_guard.py — the pre-flight around the symbolic engine (C-GUARD-4, Kimi round 77 B1/B2).

Decided: before the engine runs, the plain-Python witness predicts every derived form; the histogram
(program forms + predicted forms, head/arity) is checked against the budget of each form's own
arity from config/engine_guard.json. hyperon stays 0.2.10.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import space as sp  # noqa: E402
from core import space_witness as W  # noqa: E402

ALL_OPEN = {str(a): 390 for a in range(1, 9)}


def _cfg(tmp_path, budgets=None, probed=None):
    cfg = tmp_path / "engine_guard.json"
    cfg.write_text(json.dumps({"budgets": budgets or ALL_OPEN, "probed": probed or {}}), encoding="utf-8")
    return cfg


def _obs(n, head="obs", src="src"):
    return "\n".join(f'({head} "a-{i}" "C1" "k{i}" "WLD" "2023" {i}.0 "n" "{src}")' for i in range(n)) + "\n"


def _derive(tmp_path, base, budgets=None, probed=None, engine=None, proposed=""):
    d = tmp_path / "space"
    d.mkdir(exist_ok=True)
    (d / "base.metta").write_text(base, encoding="utf-8")
    (tmp_path / "rules.metta").write_text("", encoding="utf-8")
    (tmp_path / "prop.metta").write_text(proposed, encoding="utf-8")
    truth = lambda prog: [sp.render(x) for x in W.witness(prog)]
    return sp.derive({"dir": d, "rules": tmp_path / "rules.metta", "proposed": tmp_path / "prop.metta"},
                     engine=engine or truth, guard_config=_cfg(tmp_path, budgets, probed))


def _log(tmp_path):
    return [json.loads(l) for l in (tmp_path / "space" / "guard_log.jsonl").read_text(encoding="utf-8").splitlines()]


# ── the counter ─────────────────────────────────────────────────────────────
def test_shape_is_head_and_arity_and_commands_are_not_atoms():
    prog = _obs(3) + '(obs "x" 1)\n(subcategory "s" "c")\n; (obs "comment" 1)\n!(match &self (obs $a $b) $a)\n'
    assert sp.shape_counts(prog) == {"obs/8": 3, "obs/2": 1, "subcategory/2": 1}


def test_a_nested_expression_is_one_atom_of_its_outer_shape():
    assert sp.shape_counts('(proposed "id" "m" (says "a (b)" "c"))\n') == {"proposed/3": 1}


def test_the_predicted_forms_are_the_distinct_witness_expressions():
    xs = [["contradiction", "k", "p", "t", "a", "b"], ["contradiction", "k", "p", "t", "b", "a"], ["stale", "a"]]
    assert sp.predicted_forms(xs) == {"contradiction/5": 1, "stale/1": 1}


# ── the budget of each form's own arity ─────────────────────────────────────
@pytest.mark.parametrize("arity,budget", [(2, 250), (4, 300), (8, 300)])
def test_budget_minus_one_passes_budget_and_over_refuse(arity, budget):
    cfg = {"budgets": {arity: budget}, "probed": {}}
    form = f"f/{arity}"
    assert sp.preflight({form: budget - 1}, cfg) == []
    for n in (budget, budget + 1):
        (r,) = sp.preflight({form: n}, cfg)
        assert (r["cause"], r["form"], r["count"], r["budget"]) == ("ENGINE_BUDGET", form, n, budget)


def test_an_unprobed_arity_is_refused():
    (r,) = sp.preflight({"this-year/1": 1}, {"budgets": {1: 0}, "probed": {}})
    assert r["cause"] == "UNPROBED_ARITY"


def test_a_forbidden_arity_is_refused():
    (r,) = sp.preflight({"x/7": 1}, {"budgets": {7: 0}, "probed": {7: {"budget": "forbidden"}}})
    assert r["cause"] == "FORBIDDEN_ARITY"


def test_a_form_with_count_zero_is_not_judged():
    assert sp.preflight({"x/7": 0}, {"budgets": {7: 0}, "probed": {}}) == []


def test_the_predicted_count_refuses_before_the_engine(tmp_path):
    base = _obs(3, src="wb") + '(source-class "wb" "self_reported")\n'   # 3 unverified/4 predicted
    ran = []
    budgets = {**ALL_OPEN, "4": 3}
    with pytest.raises(sp.SpaceEngineFailed, match="unverified/4") as exc:
        _derive(tmp_path, base, budgets=budgets, engine=lambda prog: ran.append(1) or [])
    assert exc.value.cause == "ENGINE_BUDGET" and ran == []
    row = _log(tmp_path)[-1]
    assert row["state"] == "RED" and {"form": "unverified/4", "count": 3, "budget": 3,
                                      "cause": "ENGINE_BUDGET"} in row["refusals"]
    assert not (tmp_path / "space" / "derived.metta").exists()


def test_every_form_and_prediction_reaches_the_log(tmp_path):
    base = _obs(3, src="wb") + '(source-class "wb" "self_reported")\n'
    _derive(tmp_path, base)
    row = _log(tmp_path)[-1]
    assert row["forms"]["obs/8"] == 3 and row["predicted"]["unverified/4"] == 3


def test_the_config_keys_are_required(tmp_path):
    cfg = tmp_path / "g.json"
    cfg.write_text(json.dumps({"budgets": {}}), encoding="utf-8")
    with pytest.raises(KeyError):
        sp.guard_config(cfg)
    real = json.loads((REPO / "config" / "engine_guard.json").read_text(encoding="utf-8"))
    assert "threshold" not in real and set(real["budgets"]) == {str(a) for a in range(1, 9)}


# ── the witness fails, a statement slips in ─────────────────────────────────
def test_a_witness_exception_is_red_and_writes_nothing(tmp_path, monkeypatch):
    def boom(text):
        raise ValueError("bad text")
    monkeypatch.setattr(W, "witness", boom)
    with pytest.raises(sp.SpaceEngineFailed) as exc:
        _derive(tmp_path, _obs(2))
    assert exc.value.cause == "WITNESS_FAILED"
    assert not (tmp_path / "space" / "derived.metta").exists()


def test_a_statement_in_the_engine_program_is_refused_and_the_check_is_a_row(tmp_path):
    _derive(tmp_path, _obs(2))
    assert any(r.get("check") == "STATEMENT_ROWS" and r["statement_rows"] == 0 for r in _log(tmp_path))
    ran = []
    with pytest.raises(sp.SpaceEngineFailed) as exc:
        _derive(tmp_path, _obs(2), proposed='(statement "s1" "A1.1" "who.int")\n',
                engine=lambda prog: ran.append(1) or [])
    assert exc.value.cause == "STATEMENT_IN_ENGINE_PROGRAM" and ran == []


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_budget_off_by_one_would_let_the_budget_through():
    assert sp.preflight({"f/8": 300}, {"budgets": {8: 300}, "probed": {}})
    assert [f for f, n in {"f/8": 300}.items() if n > 300] == [], "a strict comparison passes 300"


def test_mutation_the_check_after_the_engine_would_have_run_it(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(sp, "preflight", lambda hist, cfg: [])
    _derive(tmp_path, _obs(3), budgets={**ALL_OPEN, "8": 3}, engine=lambda prog: ran.append(1) or
            [sp.render(x) for x in W.witness(prog)])
    assert ran == [1], "without the pre-flight the engine runs on a refused program"


def test_mutation_reading_the_program_count_would_miss_a_derived_form():
    program_only = sp.shape_counts(_obs(3, src="wb") + '(source-class "wb" "self_reported")\n')
    assert "unverified/4" not in program_only, "the program holds no derived form: only the witness can count it"


def test_mutation_without_the_statement_check_the_statement_reaches_the_engine(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(sp, "statement_rows", lambda counts: 0)
    _derive(tmp_path, _obs(2), proposed='(statement "s1" "A1.1" "who.int")\n',
            engine=lambda prog: sent.append(prog) or [sp.render(x) for x in W.witness(prog)])
    assert "(statement " in sent[0]
