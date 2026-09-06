# -*- coding: utf-8 -*-
"""
A number that parses is not yet a number that could happen. 3b, 6 Sep 2026.

proposal_intake admitted WATER_REVIEW +1.2 because "1.2" is a float. On an
indicator measured in percent of the world's population that is either a routine
week or an absurdity, and nothing could say which: no history of the indicator
existed until axis_history started writing one.

THE SCALE IS A NAMED UNKNOWN. Below MIN_SCALE_OBS the proposal is ADMITTED and
carries "unverified: N observations, need 7" - in its own record and in the
summary line. Inventing a range to judge against would be the gate telling itself
what it wants to hear, and for the first week after 6 Sep every proposal is
genuinely unverified and must say so instead of looking checked.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import proposal_intake as pi       # noqa: E402

TODAY = date(2026, 9, 6)


def _resolves(axis, metric=None):
    return 1.0, "test resolver"


def _any_cadence(indicator, deadline):
    return None


def _proposal(delta):
    return {"component": "X", "problem": "p", "solution": "s" * 20,
            "indicator": "WATER_REVIEW", "expected_delta": delta,
            "deadline": "2026-10-01"}


def _history(tmp_path, values, day0=6):
    """One observation per DAY, so daily_range counts them as separate days."""
    out = tmp_path / "axis_observations.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for i, v in enumerate(values):
            fh.write(json.dumps({
                "utc": f"2026-09-{day0 + i:02d}T01:00:00+00:00",
                "indicator": "WATER_REVIEW", "value": float(v),
                "unit": "percent of population", "source_step": "t",
                "cycle_id": None}) + "\n")
    return out


def _check_with(tmp_path, values):
    """A scale check bound to a synthetic history file."""
    from core.axis_history import daily_range
    path = _history(tmp_path, values)

    def check(indicator, delta):
        r = daily_range(indicator, path=path)
        n = r.get("n") or 0
        if n < pi.MIN_SCALE_OBS:
            return (None, f"unverified: {n} observations, need {pi.MIN_SCALE_OBS}")
        rng = r.get("range")
        if rng == 0:
            return (f"no_scale: {indicator} flat over {n} days "
                    f"(every observation {r.get('min')})", None)
        if abs(float(delta)) > pi.SCALE_MULTIPLE * rng:
            return (f"scale: delta {delta} exceeds {pi.SCALE_MULTIPLE:g}x the "
                    f"{n}-day range {rng:.6g}", None)
        return (None, f"verified against {n} observations, range {rng:.6g}")
    return check


# ── too little history: ADMITTED, and it says so ────────────────────────────

def test_zero_observations_admits_with_the_unverified_mark(tmp_path):
    v = pi.judge(_proposal(1.2), today=TODAY, resolver=_resolves,
                 cadence_check=_any_cadence,
                 scale_check=_check_with(tmp_path, []))
    assert v["verdict"] == "ADMITTED", v
    assert v["scale_check"] == "unverified: 0 observations, need 7"


def test_six_observations_is_still_unverified(tmp_path):
    v = pi.judge(_proposal(1.2), today=TODAY, resolver=_resolves,
                 cadence_check=_any_cadence,
                 scale_check=_check_with(tmp_path, [70, 71, 72, 73, 74, 75]))
    assert v["verdict"] == "ADMITTED"
    assert v["scale_check"].startswith("unverified: 6 observations")


def test_the_mark_travels_with_the_proposal_and_into_the_summary(tmp_path):
    """A reader of improvement_proposals.json must be able to see that a delta
    was admitted without its scale ever being checked."""
    props = [_proposal(1.2)]
    adm, ref = pi.admit(props, "test", today=TODAY, resolver=_resolves,
                        cadence_check=_any_cadence,
                        scale_check=_check_with(tmp_path, []),
                        refusals_path=tmp_path / "r.jsonl")
    assert len(adm) == 1 and not ref
    assert adm[0]["scale_check"].startswith("unverified: 0 observations")
    line = pi.summary_line("test", adm, ref)
    assert "UNVERIFIED" in line, line


# ── enough history: the two refusals ────────────────────────────────────────

def test_seven_flat_observations_refuse_with_no_scale(tmp_path):
    v = pi.judge(_proposal(1.2), today=TODAY, resolver=_resolves,
                 cadence_check=_any_cadence,
                 scale_check=_check_with(tmp_path, [73.6] * 7))
    assert v["verdict"] == "REFUSED", v
    assert "expected_delta" in v["missing"]
    assert "no_scale:" in v["why"] and "flat over 7 days" in v["why"]


def test_a_delta_beyond_twice_the_range_is_refused(tmp_path):
    """Range 0.5 over seven days; a delta of 1.2 is 2.4x it."""
    v = pi.judge(_proposal(1.2), today=TODAY, resolver=_resolves,
                 cadence_check=_any_cadence,
                 scale_check=_check_with(tmp_path,
                                         [73.0, 73.1, 73.2, 73.3, 73.4, 73.5, 73.5]))
    assert v["verdict"] == "REFUSED", v
    assert "scale:" in v["why"] and "exceeds 2x" in v["why"]


def test_a_delta_inside_the_range_is_admitted_and_says_it_was_checked(tmp_path):
    v = pi.judge(_proposal(0.3), today=TODAY, resolver=_resolves,
                 cadence_check=_any_cadence,
                 scale_check=_check_with(tmp_path,
                                         [73.0, 73.1, 73.2, 73.3, 73.4, 73.5, 73.5]))
    assert v["verdict"] == "ADMITTED", v
    assert v["scale_check"].startswith("verified against 7 observations")


# ── it must never wave a proposal through on silence ────────────────────────

def test_a_broken_scale_check_refuses_rather_than_staying_quiet():
    def boom(indicator, delta):
        raise RuntimeError("no history module")
    v = pi.judge(_proposal(1.2), today=TODAY, resolver=_resolves,
                 cadence_check=_any_cadence, scale_check=boom)
    assert v["verdict"] == "REFUSED"
    assert "check unavailable" in v["why"]


def test_scale_is_not_checked_when_the_delta_was_already_refused(tmp_path):
    """One root cause, named once. A non-numeric delta is refused as a delta;
    adding "and its scale is unknown" buries the real reason."""
    bad = {**_proposal("not a number")}
    v = pi.judge(bad, today=TODAY, resolver=_resolves, cadence_check=_any_cadence,
                 scale_check=_check_with(tmp_path, []))
    assert v["missing"] == ["expected_delta"], v
    assert v["why"].count("expected_delta") <= 1


def test_the_thresholds_are_pinned():
    assert pi.MIN_SCALE_OBS == 7
    assert pi.SCALE_MULTIPLE == 2.0
