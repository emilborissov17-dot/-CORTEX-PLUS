"""
Тестове за core/measurement_honesty.py.

Всеки тест тук пази едно свойство, което вече е било нарушено на живо.
Негативните контроли са пуснати и доказано падат — виж коментарите.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from core.measurement_honesty import (  # noqa: E402
    ABSENT, ASSERTED, CARRIED, MEASURED, Reading, assess, classify,
)

TARGETS = {
    "_meta": {"branches": {}},
    "SUSTAINABLE_RESOURCES": {
        "WATER_REVIEW": {"primary_metric": "w", "weight": 9},
        "FOOD_REVIEW": {"primary_metric": "f", "weight": 9},
    },
    "SAFETY": {
        "GOAL_PROGRESS_REVIEW": {"primary_metric": "g", "weight": 8},
    },
}
TOTAL = 26.0


# --------------------------------------------------------------------------- #
# класификация — fail-closed
# --------------------------------------------------------------------------- #

def test_measured_is_measured():
    assert classify("measured") == MEASURED


def test_llm_level_is_an_assertion_not_a_measurement():
    assert classify("llm_level") == ASSERTED
    assert classify("llm_level(risk-inverted)") == ASSERTED


def test_carried_forward_is_its_own_kind():
    assert classify("carried") == CARRIED


def test_missing_source_is_absent():
    assert classify(None) == ABSENT
    assert classify("") == ABSENT


def test_an_unknown_source_is_treated_as_an_assertion():
    """
    FAIL-CLOSED. Ако утре някой добави източник и забрави да го впише в белия
    списък, системата трябва да ПОДЦЕНИ себе си, не да се самозавиши.
    Обратното поведение е точно начинът, по който llm_level се промъкна в
    композита като равноправно измерване.
    """
    for unknown in ("satellite_v2", "some_new_scorer", "???", "TRUST_ME"):
        assert classify(unknown) == ASSERTED, unknown


# --------------------------------------------------------------------------- #
# числото не се чете само
# --------------------------------------------------------------------------- #

def test_a_reading_refuses_to_be_a_bare_float():
    """
    E5 дефектът стана възможен, защото композитът беше просто float и всеки
    можеше да го прочете без покритието му. Тук това е невъзможно по тип.
    """
    r = Reading(value=0.68, coverage=0.6, asserted_share=0.4,
                basis_weight=15.0, total_weight=26.0)
    with pytest.raises(TypeError, match="не се чете сам"):
        float(r)


def test_a_reading_says_its_coverage_in_text():
    r = Reading(value=0.68, coverage=0.6, asserted_share=0.4,
                basis_weight=15.0, total_weight=26.0)
    assert "60%" in r.as_text() and "0.68" in r.as_text()


# --------------------------------------------------------------------------- #
# оценката
# --------------------------------------------------------------------------- #

def test_all_asserted_gives_no_honest_number():
    """Живото състояние на 20 август: 10 оси, 10 llm_level, 0 measured."""
    scores = {"WATER_REVIEW": 60.0, "FOOD_REVIEW": 60.0, "GOAL_PROGRESS_REVIEW": 60.0}
    sources = {k: "llm_level" for k in scores}

    a = assess(scores, sources, TARGETS)

    assert a.honest.value is None
    assert a.honest.coverage == 0.0
    assert a.honest.asserted_share == 1.0
    assert "НЯМА ИЗМЕРВАНЕ" in a.verdict
    # днешното число обаче съществува и изглежда напълно уверено — това е дефектът
    assert a.todays_number.value == pytest.approx(60.0)


def test_asserted_axes_are_named_not_just_counted():
    """Число без имена не може да бъде поправено от човек."""
    scores = {"WATER_REVIEW": 42.0, "FOOD_REVIEW": 60.0, "GOAL_PROGRESS_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level",
               "GOAL_PROGRESS_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS)
    named = {x["axis"] for x in a.asserted_axes}
    assert named == {"FOOD_REVIEW", "GOAL_PROGRESS_REVIEW"}
    assert all("source" in x for x in a.asserted_axes)


def test_the_honest_number_excludes_assertions_and_todays_number_does_not():
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 60.0, "GOAL_PROGRESS_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level",
               "GOAL_PROGRESS_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS)

    assert a.honest.value == pytest.approx(20.0)          # само измереното
    assert a.honest.coverage == pytest.approx(9 / TOTAL)
    assert a.todays_number.value == pytest.approx(
        (20.0 * 9 + 60.0 * 9 + 60.0 * 8) / TOTAL)          # днешният, надут
    assert a.todays_number.value > a.honest.value


def test_silencing_a_bad_measured_axis_lowers_coverage_it_does_not_raise_the_number():
    """
    E5, приложен тук. UNHCR замлъкна -> композитът се качи 0.628 -> ~0.680, а
    sensors_ok остана True. След този модул: числото може да се качи, но
    ПОКРИТИЕТО пада заедно с него и пътува в същия обект.
    """
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 80.0, "GOAL_PROGRESS_REVIEW": 60.0}
    sources = {k: "measured" for k in scores}
    before = assess(scores, sources, TARGETS).honest

    silenced_scores = {k: v for k, v in scores.items() if k != "WATER_REVIEW"}
    silenced_sources = {k: v for k, v in sources.items() if k != "WATER_REVIEW"}
    after = assess(silenced_scores, silenced_sources, TARGETS).honest

    assert after.value > before.value          # числото наистина се качва
    assert after.coverage < before.coverage    # но покритието пада ЗАЕДНО с него
    assert "17" in after.as_text() or "65" in after.as_text()  # покритието се вижда


def test_a_branch_with_no_measurement_is_visible_per_branch():
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 30.0, "GOAL_PROGRESS_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "measured",
               "GOAL_PROGRESS_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS)
    assert a.by_branch["SUSTAINABLE_RESOURCES"]["measured_share_of_branch"] == 1.0
    assert a.by_branch["SAFETY"]["measured_share_of_branch"] == 0.0
    assert a.by_branch["SAFETY"]["asserted_weight"] == 8


def test_an_axis_with_no_score_at_all_is_absent_not_asserted():
    scores = {"WATER_REVIEW": 20.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS)
    kinds = {ax: v["kind"] for ax, v in a.by_axis.items()}
    assert kinds["FOOD_REVIEW"] == ABSENT      # има източник, но няма число
    assert kinds["GOAL_PROGRESS_REVIEW"] == ABSENT
    assert {x["axis"] for x in a.absent_axes} == {"FOOD_REVIEW", "GOAL_PROGRESS_REVIEW"}


def test_weights_are_conserved():
    """Нито едно тегло не изчезва между категориите."""
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS)
    for b in a.by_branch.values():
        assert (b["measured_weight"] + b["asserted_weight"] + b["absent_weight"]
                == pytest.approx(b["weight"]))
    assert sum(b["weight"] for b in a.by_branch.values()) == pytest.approx(TOTAL)
