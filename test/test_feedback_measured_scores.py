"""
Едно празно число не бива да заглушава измерването на цялата система.

КАКВО СЕ СЛУЧИ (измерено в цикъла от 2026-08-20 03:04)
------------------------------------------------------
    [FEEDBACK] measured scores unavailable
    (TypeError: float() argument must be a string or a real number, not 'NoneType')
    — using LLM levels only
    [FEEDBACK] axis scores: 0 measured / 10 LLM-level

agents/core/feedback_loop.py:64-65 проверяваше `current`, а викаше float()
върху `score`. Една ос със score=None хвърляше, външният except връщаше {},
и всичките оси падаха на llm_level — мнение на модела вместо измерване.

Резултатът в goal_score_history.json същата нощ: 10 оси, 10 x llm_level,
0 x measured, осем от тях на ТОЧНО 60.0.

Тези тестове пазят три свойства: една счупена ос не сваля останалите,
липсващото се назовава поименно, и системен провал (не липсваща стойност)
все още пада меко към LLM нивата.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))


def _load_feedback(monkeypatch, fake_result=None, raise_on_import=False):
    """Зарежда feedback_loop с подменен goal_score_calculator."""
    import types

    fake = types.ModuleType("goal_score_calculator")

    def compute_goal_score():
        if raise_on_import:
            raise RuntimeError("scoring engine is down")
        return fake_result

    fake.compute_goal_score = compute_goal_score
    monkeypatch.setitem(sys.modules, "goal_score_calculator", fake)

    for mod in list(sys.modules):
        if mod.endswith("feedback_loop"):
            del sys.modules[mod]
    import importlib
    return importlib.import_module("agents.core.feedback_loop")


def _detail(axis, current, score):
    return {"axis": axis, "current": current, "score": score}


# --------------------------------------------------------------------------- #

def test_one_axis_with_a_null_score_does_not_silence_the_others(monkeypatch):
    """Точният снощен случай. Преди поправката резултатът беше {}."""
    res = {"metric_details": {
        "a": _detail("WATER_REVIEW", 73.0, 0.62),
        "b": _detail("CLIMATE_GLOBAL_RISK_REVIEW", 429.0, None),   # <- убиецът
        "c": _detail("FOOD_REVIEW", 91.6, 0.88),
    }}
    fb = _load_feedback(monkeypatch, res)
    measured = fb._measured_axis_scores()

    assert measured == {"WATER_REVIEW": 62.0, "FOOD_REVIEW": 88.0}
    assert "CLIMATE_GLOBAL_RISK_REVIEW" not in measured


def test_a_non_numeric_score_is_skipped_not_fatal(monkeypatch):
    res = {"metric_details": {
        "a": _detail("WATER_REVIEW", 73.0, 0.62),
        "b": _detail("ENERGY_REVIEW", 12.0, "не-число"),
    }}
    fb = _load_feedback(monkeypatch, res)
    assert fb._measured_axis_scores() == {"WATER_REVIEW": 62.0}


def test_the_skipped_axes_are_named_in_the_log(monkeypatch, capsys):
    """Брой без имена не може да бъде поправен от човек."""
    res = {"metric_details": {
        "a": _detail("WATER_REVIEW", 73.0, 0.62),
        "b": _detail("SOCIAL_RELATIONS_REVIEW", None, None),
    }}
    fb = _load_feedback(monkeypatch, res)
    fb._measured_axis_scores()

    out = capsys.readouterr().out
    assert "SOCIAL_RELATIONS_REVIEW" in out
    assert "no measurement for" in out


def test_a_real_system_failure_still_falls_back_softly(monkeypatch, capsys):
    """Липсващ модул или счупен скоринг НЕ бива да събаря цикъла."""
    fb = _load_feedback(monkeypatch, None, raise_on_import=True)
    assert fb._measured_axis_scores() == {}
    assert "measured scores unavailable" in capsys.readouterr().out


def test_every_axis_measured_means_nothing_is_skipped(monkeypatch, capsys):
    res = {"metric_details": {
        "a": _detail("WATER_REVIEW", 73.0, 0.62),
        "b": _detail("FOOD_REVIEW", 91.6, 0.88),
    }}
    fb = _load_feedback(monkeypatch, res)
    measured = fb._measured_axis_scores()

    assert len(measured) == 2
    assert "no measurement for" not in capsys.readouterr().out


def test_entries_without_an_axis_name_are_ignored_quietly(monkeypatch):
    res = {"metric_details": {
        "a": _detail("WATER_REVIEW", 73.0, 0.62),
        "b": {"current": 1.0, "score": 0.5},        # без axis
        "c": "не е речник",
    }}
    fb = _load_feedback(monkeypatch, res)
    assert fb._measured_axis_scores() == {"WATER_REVIEW": 62.0}


def test_a_measurement_outranks_the_llm_bucket(monkeypatch):
    """
    Ако измерването съществува, то бие LLM кофата. Това е правилото, заради
    което функцията изобщо съществува — и то работеше само на хартия, докато
    една None стойност изключваше всички измервания.
    """
    res = {"metric_details": {"a": _detail("WATER_REVIEW", 73.0, 0.20)}}
    fb = _load_feedback(monkeypatch, res)
    measured = fb._measured_axis_scores()
    assert measured["WATER_REVIEW"] == 20.0
    assert measured["WATER_REVIEW"] != 60.0   # не константата на LLM-а
