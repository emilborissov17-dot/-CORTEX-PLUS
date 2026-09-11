# -*- coding: utf-8 -*-
"""test/test_world_forecast.py — the world loop (10 Sep 2026). Failure paths first."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROPHECY = REPO / "experiments" / "prophecy"
sys.path.insert(0, str(PROPHECY))
sys.path.insert(0, str(REPO))
import prophecy_ledger as pl  # noqa: E402

spec = importlib.util.spec_from_file_location("world_forecast", PROPHECY / "world_forecast.py")
wf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wf)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(wf, "LEARNER_STATE", tmp_path / "learner_state.json")
    return tmp_path


def _series(n=20, step=1.0):
    return {"AX::m": [(f"2026-08-{i+1:02d}", 100.0 + step * i) for i in range(n)]}


def test_frozen_indicators_are_excluded(tmp_path):
    h = {"AX": [{"date": f"2026-08-{i+1:02d}", "metrics": {"flat": 5.0, "moves": float(i % 3)}} for i in range(20)]}
    p = tmp_path / "axis_history.json"; p.write_text(json.dumps(h), encoding="utf-8")
    s = wf.load_series(p, tier_path=tmp_path / "no_tier.jsonl")
    assert "AX::moves" in s and "AX::flat" not in s


def test_own_output_axes_are_not_the_world(tmp_path):
    h = {"STRATEGIST_SOLUTIONS": [{"date": f"2026-08-{i+1:02d}", "metrics": {"x": float(i)}} for i in range(20)]}
    p = tmp_path / "axis_history.json"; p.write_text(json.dumps(h), encoding="utf-8")
    assert wf.load_series(p, tier_path=tmp_path / "no_tier.jsonl") == {}


def test_the_daily_tier_joins_the_world_under_its_own_prefix(tmp_path):
    """AGI-5: the kept nightly fetch is a second source, same moving rule, and a
    missing tier is not a refusal."""
    tier = tmp_path / "tier.jsonl"
    rows = [{"date": f"2026-08-{i+1:02d}", "indicator": "quakes.quake_m45_count", "value": float(10 + i % 4)} for i in range(20)]
    rows += [{"date": f"2026-08-{i+1:02d}", "indicator": "nuclear.nuclear_warheads_total", "value": 12000.0} for i in range(20)]
    tier.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    s = wf.load_series(tmp_path / "no_axis_history.json", tier_path=tier)
    assert set(s) == {"DAILY::quakes.quake_m45_count"}
    assert len(s["DAILY::quakes.quake_m45_count"]) == 20
    assert wf.load_series(tmp_path / "no_axis_history.json", tier_path=tmp_path / "absent.jsonl") == {}


def test_predict_refuses_when_nothing_moves(ledger):
    with pytest.raises(wf.Refused):
        wf.cmd_predict({})
    assert not pl.LEDGER_PATH.exists()


def test_score_waits_for_a_value_dated_after_the_seal(ledger):
    s = _series()
    wf.cmd_predict(s)
    assert wf.cmd_score(s) == 0                       # no newer observation yet
    s2 = {"AX::m": s["AX::m"] + [("2026-08-21", 121.0)]}
    assert wf.cmd_score(s2) == 1
    assert wf.cmd_score(s2) == 0                      # never twice
    state = json.loads(wf.LEARNER_STATE.read_text(encoding="utf-8"))
    assert "AX::m" in state and state["AX::m"]["alpha"] in wf.ALPHAS, "the error must have changed the stored learner"


def test_mutation_the_learning_step_is_load_bearing(ledger, monkeypatch):
    """If fit_alpha stopped looking at the data, every indicator would get the same alpha."""
    monkeypatch.setattr(wf, "fit_alpha", lambda vals: 0.5)
    b = wf.bench({"A::up": _series(20, 1.0)["AX::m"], "B::noise": [(f"2026-08-{i+1:02d}", float(i % 2)) for i in range(20)]})
    assert {r["alpha"] for r in b["rows"]} == {0.5}, "with learning removed the alphas collapse — proving fit_alpha was doing the choosing"


def test_bench_reports_transfer_separately_from_fit():
    b = wf.bench({"A::up": _series(20, 1.0)["AX::m"], "B::noise": [(f"2026-08-{i+1:02d}", float(i % 2)) for i in range(20)]})
    for r in b["rows"]:
        assert r["ewma_transfer"] is not None and r["ewma_fitted"] is not None
    assert "ewma_TRANSFER_beats_persistence" in b["verdict"]
