# -*- coding: utf-8 -*-
"""test/test_feature_proposals.py — E3 (11 Sep 2026): the brain chooses what to look at; the exam decides.

Worlds with a known answer:
  A — random walk; B — its DIRECTION follows A's move of yesterday (sign), plus noise;
  C — random walk unrelated to anything.
Pinned:
  * the grammar refuses what it does not know, by name
  * proposing x_move:A for target B is ACCEPTED (it really helps) and joins the registry
  * proposing x_move:C for target B is REJECTED (it does not help), nothing joins
  * a silent brain records SILENT and NO code proposes in its place
  * the learner abstains (UNCONFIDENT_TO_CHOOSE) only after it has a record, and every decision names its reasons
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import direction_learner as DL  # noqa: E402
from core import feature_proposals as FP  # noqa: E402


def _world(seed=3, n=260):
    rng = random.Random(seed)
    ds = [(date(2025, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    a, b, c = [100.0], [50.0], [10.0]
    for i in range(1, n):
        a.append(a[-1] + rng.gauss(0, 1))
        c.append(c[-1] + rng.gauss(0, 1))
        push = 1.0 if (i >= 2 and a[i - 1] > a[i - 2]) else -1.0
        b.append(b[-1] + 0.8 * push + rng.gauss(0, 0.6))
    return {"A": list(zip(ds, a)), "B": list(zip(ds, b)), "C": list(zip(ds, c))}


def test_the_grammar_refuses_by_name():
    assert DL.valid_feature("vol_20")[0] and DL.valid_feature("x_ret_5:A", ["A"])[0]
    assert DL.valid_feature("vol_200")[1] == "not in the feature grammar"
    assert DL.valid_feature("x_move:Z", ["A"])[1] == "unknown series 'Z'"
    assert not DL.valid_feature("__import__('os')")[0]


def test_a_real_input_is_accepted_and_a_useless_one_rejected(tmp_path):
    w = _world()
    out = FP.run(all_series=w, proposals=[{"target": "B", "feature": "x_move:A", "why": "B follows A"},
                                          {"target": "B", "feature": "x_move:C", "why": "maybe C"}],
                 reg_path=tmp_path / "reg.json", log_path=tmp_path / "log.jsonl", report=False)
    v = {p["feature"]: p for p in out["proposals"]}
    assert v["x_move:A"]["verdict"] == "ACCEPTED" and v["x_move:A"]["accuracy_with"] > v["x_move:A"]["accuracy_without"]
    assert v["x_move:C"]["verdict"] == "REJECTED"
    reg = json.loads((tmp_path / "reg.json").read_text(encoding="utf-8"))
    assert reg["B"]["accepted"] == ["x_move:A"]
    assert out["models"]["B"]["features"] == ["own_lag1", "own_lag2", "own_lag3", "x_move:A"]
    assert len((tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_a_silent_brain_is_recorded_and_code_does_not_propose_for_it(tmp_path):
    out = FP.run(all_series=_world(), proposer=lambda *a: ([], "SILENT"),
                 reg_path=tmp_path / "reg.json", log_path=tmp_path / "log.jsonl", report=False)
    assert out["status"] == "SILENT" and out["proposals"] == []
    assert not (tmp_path / "reg.json").exists()


def test_the_brain_sees_its_own_record_and_the_catalogue(tmp_path):
    seen = {}

    def proposer(table, cat, past):
        seen.update(table=table, cat=cat, past=past)
        return [{"target": "B", "feature": "vol_300", "why": "x"}], "OK:qwen3:8b"
    out = FP.run(all_series=_world(), proposer=proposer, reg_path=tmp_path / "r.json", log_path=tmp_path / "l.jsonl", report=False)
    assert "x_move:<series>" in seen["cat"] and "B:" in seen["table"]
    assert out["proposals"][0]["verdict"] == "REFUSED" and out["proposals"][0]["source"] == "brain"


def test_decisions_carry_reasons_and_abstention_is_learned():
    r = DL.walk(_world(), "B", ["own_lag1", "x_move:A"])
    assert r["n"] > 100 and all(len(x["why"]) >= 1 for x in r["records"])
    assert r["records"][0]["band"] == 0.0                                  # no record yet -> no abstention
    assert {x["decision"] for x in r["records"]} <= {"UP", "DOWN", DL.UNCONFIDENT}
    assert r["records"][-1]["why"][0][0] == "x_move:A"                     # the reason is the real driver
    assert r["accuracy_forced"] > 0.75 and r["z_vs_baseline"] >= 2
