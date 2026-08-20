#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_metta_parallel.py — THE SECOND COLUMN MUST BE ABLE TO OBJECT.

THE LIVE FACT THIS IS BUILT ON
-------------------------------
20 August 2026, the same axis on the same night:

    memory/auto_levels.json         CLIMATE_GLOBAL_RISK_REVIEW -> level "LOW"
    snapshots/master/goal_score_latest.json  ->  score 0.8185

A level of LOW beside a score of 81.85/100 is two parts of one system saying
opposite things. Nothing in the cycle noticed, because nothing was comparing
them. R3 is the rule that compares them.

THE NEGATIVE CONTROL
---------------------
test_r3_fires_on_the_live_climate_contradiction runs against the REAL repo
files. Widen LEVEL_GAP past the contradiction and it goes red — the rule stops
seeing a disagreement that is still there.

THE SECOND NEGATIVE CONTROL, and the more interesting one:
test_an_empty_hyperon_result_does_not_erase_the_reference. The first version of
this module trusted hyperon whenever it returned without error. It returned an
EMPTY result on a malformed program, and the module reported 0 firings on data
where the reference found 31 — the exact defect the module exists to catch,
reproduced inside the module.

    venv\\Scripts\\python.exe -m pytest test/test_metta_parallel.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import metta_parallel as mp

REPO = pathlib.Path(__file__).resolve().parents[1]

CLIMATE = "CLIMATE_GLOBAL_RISK_REVIEW"


def _fact(axis, **kw):
    base = {"axis": axis, "measured": True, "value": 1.0, "weight": 10.0,
            "score": 0.5, "target": 1.0, "direction": "higher_better",
            "unit": "u", "level": None}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# (a) THE LIVE PROOF
# ---------------------------------------------------------------------------

def test_the_live_climate_fact_is_what_we_think_it_is():
    """Guard the premise. If auto_levels or goal_score changes shape, the proof
    below would pass or fail for reasons unrelated to the rule."""
    facts = mp.gather_facts()
    climate = next((f for f in facts if f["axis"] == CLIMATE), None)

    assert climate is not None, "CLIMATE_GLOBAL_RISK_REVIEW is not in the feeds"
    assert climate["level"] == "LOW", f"auto_levels no longer says LOW: {climate['level']}"
    assert climate["score"] == pytest.approx(0.8185), climate["score"]
    assert climate["measured"] is True


def test_r3_fires_on_the_live_climate_contradiction():
    """THE REQUIRED PROOF, on real data, not a fixture."""
    facts = mp.gather_facts()
    fired = mp.evaluate_python(facts)

    assert CLIMATE in fired["R3_LEVEL_CONTRADICTS_SCORE"], (
        f"\n  R3 DID NOT FIRE ON THE LIVE CONTRADICTION.\n"
        f"  auto_levels says LOW, goal_score says 81.85/100, same axis, same\n"
        f"  night. If the rule cannot see that, it cannot see anything.\n"
        f"  R3 fired on: {fired['R3_LEVEL_CONTRADICTS_SCORE']}\n"
    )


def test_the_disagreement_states_both_readings():
    """An operator must not have to open two files to see the contradiction."""
    facts = mp.gather_facts()
    fired = mp.evaluate_python(facts)
    entry = next(d for d in mp.disagreements(facts, fired) if d["axis"] == CLIMATE)

    assert entry["level"] == "LOW"
    assert entry["score_pct"] == pytest.approx(81.85)
    assert "LOW" in entry["says"] and "81.85" in entry["says"]


def test_hyperon_and_the_reference_agree_on_live_data():
    """If the sidecar is present, the MeTTa program must derive what the
    reference derives. A second engine that quietly differs is worse than none."""
    if mp.sidecar_python() is None:
        pytest.skip("venv312_metta not present — python-reference only")

    facts = mp.gather_facts()
    fired, err = mp.evaluate_hyperon(mp.metta_program(facts))

    assert err == "", f"hyperon failed: {err}"
    assert fired == mp.evaluate_python(facts), (
        "the MeTTa program and the Python reference disagree on live data"
    )
    assert CLIMATE in fired["R3_LEVEL_CONTRADICTS_SCORE"], (
        "the real engine did not derive the contradiction"
    )


# ---------------------------------------------------------------------------
# (b) An empty second opinion must not erase a firing first one
# ---------------------------------------------------------------------------

def test_an_empty_hyperon_result_does_not_erase_the_reference(monkeypatch):
    """THE SECOND NEGATIVE CONTROL. hyperon returns nothing; the reference
    fires. The output must keep the firings and say the engines disagreed."""
    empty = {r: [] for r in mp.RULES}
    monkeypatch.setattr(mp, "evaluate_hyperon", lambda program, timeout=60: (empty, ""))

    result = mp.assess()

    assert result["engines_agree"] is False
    assert result["engine"] == mp.ENGINE_PYTHON, (
        "an engine that returned nothing was recorded as the one that decided"
    )
    assert sum(result["fired_counts"].values()) > 0, (
        "\n  AN EMPTY ENGINE RESULT ERASED THE FIRINGS.\n"
        "  hyperon returned 0 rules fired; the reference found real ones. The\n"
        "  module reported the empty answer, which is indistinguishable from\n"
        "  'nothing is wrong' — the exact defect this file exists to catch.\n"
    )
    assert CLIMATE in result["fired"]["R3_LEVEL_CONTRADICTS_SCORE"]
    assert "disagreed" in (result["engine_error"] or "")


def test_when_the_engines_agree_hyperon_is_the_recorded_engine():
    """POSITIVE CONTROL — otherwise the rule above could be satisfied by never
    trusting hyperon at all."""
    if mp.sidecar_python() is None:
        pytest.skip("venv312_metta not present")
    result = mp.assess()
    assert result["engines_agree"] is True
    assert result["engine"] == mp.ENGINE_HYPERON


def test_no_sidecar_falls_back_and_says_so(monkeypatch):
    monkeypatch.setattr(mp, "sidecar_python", lambda: None)
    result = mp.assess()
    assert result["engine"] == mp.ENGINE_PYTHON
    assert "sidecar venv not found" in (result["engine_error"] or "")
    assert sum(result["fired_counts"].values()) > 0, (
        "falling back must still produce the verdict, not an empty one"
    )


# ---------------------------------------------------------------------------
# (c) The rules, individually
# ---------------------------------------------------------------------------

def test_r1_fires_on_weight_without_measurement():
    fired = mp.evaluate_python([_fact("A", measured=False, value=None, weight=5.0)])
    assert fired["R1_UNGROUNDED"] == ["A"]


def test_r2_fires_on_a_value_nobody_scored():
    fired = mp.evaluate_python([_fact("A", value=42.0, score=None)])
    assert fired["R2_INCOMPLETE"] == ["A"]


@pytest.mark.parametrize("level,score,should_fire", [
    ("LOW", 0.8185, True),    # the live CLIMATE case
    ("LOW", 0.20, False),
    ("HIGH", 0.05, True),
    ("HIGH", 0.90, False),
    ("MEDIUM", 0.50, False),
    ("MEDIUM", 0.034, True),  # the live SOCIAL_RELATIONS case
])
def test_r3_only_fires_when_the_two_readings_really_diverge(level, score, should_fire):
    fired = mp.evaluate_python([_fact("A", level=level, score=score)])
    assert (("A" in fired["R3_LEVEL_CONTRADICTS_SCORE"]) is should_fire), (
        f"level={level} score={score}"
    )


@pytest.mark.parametrize("direction,value,target,should_fire", [
    ("lower_better", 427.59, 350.0, True),
    ("lower_better", 300.0, 350.0, False),
    ("higher_better", 27.8, 80.0, True),
    ("higher_better", 90.0, 80.0, False),
])
def test_r4_fires_on_the_wrong_side_of_target(direction, value, target, should_fire):
    fired = mp.evaluate_python([_fact("A", direction=direction, value=value,
                                      target=target)])
    assert (("A" in fired["R4_OFF_TARGET"]) is should_fire)


def test_r5_needs_both_weight_and_loss():
    heavy_lost = mp.evaluate_python([_fact("A", weight=10.0, score=0.2)])
    heavy_fine = mp.evaluate_python([_fact("B", weight=10.0, score=0.9)])
    light_lost = mp.evaluate_python([_fact("C", weight=1.0, score=0.2)])

    assert heavy_lost["R5_CRITICAL_LOSS"] == ["A"]
    assert heavy_fine["R5_CRITICAL_LOSS"] == []
    assert light_lost["R5_CRITICAL_LOSS"] == []


# ---------------------------------------------------------------------------
# (d) The program is real, and the column reaches the phase report
# ---------------------------------------------------------------------------

def test_the_emitted_program_is_metta_not_a_description():
    program = mp.metta_program(mp.gather_facts())
    assert "!(match &self" in program
    assert "(scored " in program
    assert "R3_LEVEL_CONTRADICTS_SCORE" in program
    assert "none" not in program.split(";")[0], (
        "atoms must only be emitted when their fields are numbers"
    )


def test_the_bridge_no_longer_mocks():
    """The mock FUNCTION must be gone, not the word.

    The new bridge's docstring quotes the old echo line while explaining what it
    replaced, so a text search for "MOCK RESPONSE" matches the very file that
    fixed it — the same trap test_approval_server_is_closed documents. Assert on
    the code instead: the function is deleted and the real module is imported.
    """
    import ast
    src = (REPO / "hyperon_bridge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "call_cortex_qwen" not in defined, "the echo mock function is still there"

    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "core.metta_parallel" in imported, (
        "the bridge does not reach the real symbolic column"
    )


def test_d_score_phase_report_carries_the_disagreements(tmp_path):
    from core.phase_report import PhaseReport
    with PhaseReport("D_SCORE", "cid", base_dir=tmp_path) as rep:
        rep.step_ok("scoring_engine")
    report = json.loads(rep.path().read_text(encoding="utf-8"))

    assert "symbolic_disagreements" in report, (
        "D_SCORE is where the composite is born; the objections to it belong here"
    )
    assert any(d["axis"] == CLIMATE for d in report["symbolic_disagreements"])


def test_other_phases_do_not_carry_them(tmp_path):
    from core.phase_report import PhaseReport
    with PhaseReport("B_SENSE", "cid", base_dir=tmp_path) as rep:
        rep.step_ok("web_intelligence")
    assert "symbolic_disagreements" not in json.loads(
        rep.path().read_text(encoding="utf-8"))
