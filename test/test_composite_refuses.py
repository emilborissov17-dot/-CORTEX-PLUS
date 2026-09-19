# -*- coding: utf-8 -*-
"""test/test_composite_refuses.py — losing data must never improve the score.

THE DEFECT, measured 19 September 2026. wellbeing_globe.py run without
--governance-only nulls governance_computed_at, and load_governance_globals then
returns {}. Four comments in goal_score_calculator claimed the two governance
axes would "fall back to 0.5" — stale prose describing behaviour removed on
15 Aug 2026. What actually happened was worse and quieter:

    with governance present : composite_score 0.6251, coverage_of_goal 0.6826
    with governance missing : composite_score 0.6508, coverage_of_goal 0.5988

THE COMPOSITE WENT UP. Both governance axes score below average (0.45, 0.43), so
dropping them removes their weight from the numerator AND from the denominator,
and the average of what is left is higher. Losing two axes made the world look
better.

That is the same failure as the 0.5 default this file removed in August, one
level up: a number that answers when it should refuse. composite_valid was
already False in BOTH cases, so the flag could not tell them apart, and every
consumer except core/cycle_report.py read the number without the flag.

So composite_score is None unless coverage_of_goal >= COVERAGE_MIN. The computed
value survives as composite_score_withheld — a name a consumer cannot reach for
by accident and a reader of the JSON cannot miss.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import goal_score_calculator as g   # noqa: E402


def test_a_missing_governance_score_is_none_and_never_one_half():
    """The four stale comments said 0.5. This pins what the code actually does."""
    original = g.load_governance_globals
    g.load_governance_globals = lambda: {}
    try:
        res = g.compute_goal_score()
    finally:
        g.load_governance_globals = original
    for axis in ("GOVERNANCE_INSTITUTIONS_REVIEW", "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL"):
        assert res["axis_scores"].get(axis) is None, (
            "%s scored %r with no governance data — a fabricated middle"
            % (axis, res["axis_scores"].get(axis)))
        assert res["axis_scores"].get(axis) != 0.5
        assert axis not in res["axis_observations"], (
            "%s claims an observation it does not have" % axis)


def test_the_composite_refuses_below_the_coverage_threshold():
    """When it refuses, composite_score is None — not a number, not a zero."""
    res = g.compute_goal_score()
    if res["composite_valid"]:
        pytest.skip("coverage is above the threshold today; the refusal path is not live")
    assert res["composite_score"] is None, (
        "composite_valid is False and composite_score is still %r"
        % res["composite_score"])
    assert res["composite_score_withheld"] is not None, (
        "the computed value vanished instead of being withheld")
    assert res["insufficient_data"], "a refusal with no reason is a silence"


def test_the_withheld_value_is_the_one_that_would_have_been_published():
    """The refusal must not also lose the number. A reader who wants it can have
    it — by typing a word that says it is withheld."""
    res = g.compute_goal_score()
    if res["composite_valid"]:
        pytest.skip("coverage is above the threshold today")
    w = res["composite_score_withheld"]
    assert isinstance(w, float) and 0.0 <= w <= 1.0, w


def test_dropping_axes_must_not_be_able_to_raise_a_published_score():
    """THE ONE THAT MATTERS.

    Compute twice — with and without governance — and assert that no PUBLISHED
    composite improves by losing data. Under the refusal both are None, so the
    perverse incentive cannot exist. If the threshold is ever lowered enough for
    both to publish, this test starts comparing real numbers and will catch the
    same defect again.
    """
    with_gov = g.compute_goal_score()
    original = g.load_governance_globals
    g.load_governance_globals = lambda: {}
    try:
        without_gov = g.compute_goal_score()
    finally:
        g.load_governance_globals = original

    assert without_gov["coverage_of_goal"] < with_gov["coverage_of_goal"], (
        "removing two axes did not reduce coverage — the fixture is not testing "
        "what it claims")

    a, b = with_gov["composite_score"], without_gov["composite_score"]
    if a is None or b is None:
        assert b is None, (
            "the version with LESS data published a composite while the fuller "
            "one refused")
        return
    assert b <= a, (
        "losing the two governance axes RAISED the published composite "
        "%.4f -> %.4f" % (a, b))


def test_the_withheld_value_still_shows_the_perverse_direction():
    """The defect does not disappear because we stopped publishing it.

    withheld goes UP when data is lost, and that is exactly why the published
    field had to become None. Pinned so nobody 'fixes' the withheld value by
    making it behave, which would hide the thing worth seeing.
    """
    with_gov = g.compute_goal_score()
    original = g.load_governance_globals
    g.load_governance_globals = lambda: {}
    try:
        without_gov = g.compute_goal_score()
    finally:
        g.load_governance_globals = original
    a = with_gov["composite_score_withheld"]
    b = without_gov["composite_score_withheld"]
    if a is None or b is None:
        pytest.skip("nothing withheld today")
    assert b > a, (
        "expected the withheld composite to rise when data is lost (%.4f -> %.4f); "
        "if it no longer does, the weighting changed and this comment is stale"
        % (a, b))


def test_no_source_comment_still_promises_a_zero_point_five_fallback():
    """Four comments described a fallback removed in August. A reader who
    believes them would 'restore' a default into the one place this repo has
    spent months taking defaults out of."""
    text = (REPO / "goal_score_calculator.py").read_text(encoding="utf-8")
    for bad in ("fall back to qualitative 0.5", "falling back to 0.5",
                "dead axes stay 0.5"):
        assert bad not in text, "stale claim still in the source: %r" % bad
