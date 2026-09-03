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

    # gt_axes is explicit so this unit test does not depend on the live
    # config/axis_source_map.json: here NO axis has a configured ground-truth
    # series, which is what makes llm_level a legitimate ASSERTED rather than a
    # forfeit. The forfeit rule has its own test below.
    a = assess(scores, sources, TARGETS, gt_axes=frozenset())

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

    a = assess(scores, sources, TARGETS, gt_axes=frozenset())
    named = {x["axis"] for x in a.asserted_axes}
    assert named == {"FOOD_REVIEW", "GOAL_PROGRESS_REVIEW"}
    assert all("source" in x for x in a.asserted_axes)


def test_the_honest_number_excludes_assertions_and_todays_number_does_not():
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 60.0, "GOAL_PROGRESS_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level",
               "GOAL_PROGRESS_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS, gt_axes=frozenset())

    assert a.honest.value == pytest.approx(20.0)          # само измереното
    assert a.honest.coverage == pytest.approx(9 / TOTAL)
    assert a.todays_number.value == pytest.approx(
        (20.0 * 9 + 60.0 * 9 + 60.0 * 8) / TOTAL)          # днешният, надут
    assert a.todays_number.value > a.honest.value


# --------------------------------------------------------------------------- #
# A CONFIGURED AXIS MAY NOT FALL BACK TO AN OPINION (3 сеп 2026)
# --------------------------------------------------------------------------- #

def test_a_ground_truth_axis_that_arrives_as_an_opinion_is_absent_not_asserted():
    """If somebody wrote down which number decides an axis and where to fetch it,
    a failed fetch is an ABSENCE. Degrading to llm_level keeps the axis's weight in
    the composite while dropping the evidence under it — which is precisely
    'opinion dressed as measurement'."""
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level"}

    a = assess(scores, sources, TARGETS, gt_axes=frozenset({"FOOD_REVIEW"}))

    assert a.by_axis["FOOD_REVIEW"]["kind"] == ABSENT
    assert a.by_axis["FOOD_REVIEW"]["ground_truth_forfeited"] is True
    assert "does not fall back" in a.by_axis["FOOD_REVIEW"]["forfeit_why"]
    # it is NOT in the asserted list — it forfeited, it did not assert
    assert "FOOD_REVIEW" not in {x["axis"] for x in a.asserted_axes}
    assert "FOOD_REVIEW" in {x["axis"] for x in a.absent_axes}


def test_the_forfeited_weight_leaves_todays_number_it_does_not_inflate_it():
    """The whole point: the weight is FORFEITED. An axis that failed its fetch must
    not keep voting with an opinion."""
    scores = {"WATER_REVIEW": 20.0, "FOOD_REVIEW": 60.0}
    sources = {"WATER_REVIEW": "measured", "FOOD_REVIEW": "llm_level"}

    kept = assess(scores, sources, TARGETS, gt_axes=frozenset())
    lost = assess(scores, sources, TARGETS, gt_axes=frozenset({"FOOD_REVIEW"}))

    # todays_number is the weighted MEAN over the axes that contributed, so the
    # denominator is their own weight, not TOTAL.
    assert kept.todays_number.value == pytest.approx((20.0 * 9 + 60.0 * 9) / 18.0)
    assert lost.todays_number.value == pytest.approx(20.0)   # WATER alone
    # and the forfeit shows up as coverage lost, not as a number quietly moving
    assert lost.todays_number.basis_weight == 9.0
    assert kept.todays_number.basis_weight == 18.0
    assert lost.todays_number.value < kept.todays_number.value
    # the honest number never contained it either way
    assert lost.honest.value == kept.honest.value == pytest.approx(20.0)


def test_a_ground_truth_axis_that_really_measured_is_untouched():
    """The rule may only ever DEMOTE. A measured axis is not its business."""
    scores = {"FOOD_REVIEW": 60.0}
    sources = {"FOOD_REVIEW": "measured"}

    a = assess(scores, sources, TARGETS, gt_axes=frozenset({"FOOD_REVIEW"}))

    assert a.by_axis["FOOD_REVIEW"]["kind"] == MEASURED
    assert "ground_truth_forfeited" not in a.by_axis["FOOD_REVIEW"]


def test_an_unreadable_axis_source_map_forfeits_nothing():
    """FAIL-OPEN. A config that cannot be read must not be able to demote an axis —
    that would turn a missing file into a silent drop in the composite."""
    from core.measurement_honesty import ground_truth_axes
    assert ground_truth_axes(BASE / "does" / "not" / "exist.json") == frozenset()


def test_the_live_map_names_the_axes_that_actually_have_ground_truth():
    """Guard the premise against a config edit: these are the axes the rule polices."""
    from core.measurement_honesty import ground_truth_axes
    live = ground_truth_axes()
    assert {"WATER_REVIEW", "FOOD_REVIEW", "CLIMATE_GLOBAL_RISK_REVIEW"} <= live
    # MATERIALS_WASTE has primary_metric=null, so its llm_level is legitimate and
    # the rule must NOT touch it. If that changes, this test should be revisited
    # rather than the rule quietly widened.
    assert "MATERIALS_WASTE_REVIEW" not in live


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
