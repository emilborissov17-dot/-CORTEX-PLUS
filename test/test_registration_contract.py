#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_registration_contract.py — cadence is DECLARED, never inferred.

PLAN point 1. The defect this guards, measured on 13 Sep 2026: 62 series entered
the daily tier and 49 of them have never once changed, because they are annual
figures given today's date. That is not a quiet nuisance. A flat row passes five
clean observations with CV 0, is promoted to TRUSTED, and then the April revision
lands and the machine reads a correct number as a lie. The input defect is first
rewarded and then punished.

THE FORBIDDEN FALLBACK, and it is the whole file: treating an undeclared cadence
as daily. Inference is worse than useless here — an annual series sampled daily
looks perfectly stable, so any inference concludes "daily, and remarkably steady",
which is the wrong answer delivered with high confidence. Undeclared means
REFUSED, and the refusal names the field.

Each test below fails if the thing it names is removed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import source_registration as sr          # noqa: E402

DAILY = {"axis": "A", "key": "k", "cadence": "daily",
         "primary_source": "USGS", "unit": "events"}


def test_the_four_cadences_and_the_daily_ceiling_are_pinned():
    """Widening either is a decision, not a tidy-up."""
    assert sr.CADENCE == ("daily", "weekly", "monthly", "annual")
    assert sr.DAILY_TIER_MAX_DAYS == 1


def test_an_undeclared_cadence_is_refused_and_not_assumed_daily():
    e = dict(DAILY)
    del e["cadence"]
    ok, why = sr.may_enter_daily_tier(e)
    assert ok is False, "an undeclared cadence was let into the daily tier"
    assert "no cadence declared" in why
    assert sr.rejection_reason(e) == "cadence undeclared"


def test_a_nonsense_cadence_is_refused_rather_than_coerced():
    e = dict(DAILY, cadence="whenever")
    ok, why = sr.may_enter_daily_tier(e)
    assert ok is False and "whenever" in why
    assert any(m.startswith("cadence=") for m in sr.missing_provenance(e))


@pytest.mark.parametrize("cad,expected", [
    ("annual", "annual value stamped daily"),
    ("monthly", "monthly value stamped daily"),
    ("weekly", "weekly value stamped daily"),
])
def test_a_slow_series_is_refused_with_the_input_defect_named(cad, expected):
    """'constant_series' reads as a fact about the world: this did not move.
    'annual value stamped daily' reads as what it is: a defect at the input.
    They are different findings and must not share a name."""
    e = dict(DAILY, cadence=cad)
    ok, _why = sr.may_enter_daily_tier(e)
    assert ok is False
    assert sr.rejection_reason(e) == expected
    assert "constant" not in sr.rejection_reason(e)


def test_a_daily_source_that_carries_the_contract_is_allowed():
    ok, why = sr.may_enter_daily_tier(DAILY)
    assert ok is True, why
    assert sr.missing_provenance(DAILY) == []
    assert sr.rejection_reason(DAILY) is None


@pytest.mark.parametrize("field", sr.PROVENANCE_REQUIRED)
def test_every_required_field_is_actually_required(field):
    """Drop one field at a time; each must be named. A field that can be removed
    without the check noticing is not part of the contract."""
    e = dict(DAILY)
    e.pop(field)
    assert field in sr.missing_provenance(e), f"{field} is declared required and is not checked"


def test_blank_is_missing_not_present():
    assert "unit" in sr.missing_provenance(dict(DAILY, unit="   "))


def test_the_key_field_is_in_the_contract_because_peers_are_matched_by_it():
    """source_lifecycle compares a second witness to the first by (axis, key).
    435 ledger events carry zero contradictions, and one reason is that the same
    quantity is registered under three different names across three registers."""
    assert "key" in sr.PROVENANCE_REQUIRED


def test_the_real_registers_are_measured_and_the_slow_ones_are_seen():
    """Against the live registers, not a fixture: the contract must actually see
    the annual sources that have been feeding the daily tier."""
    rep = sr.contract_report()
    assert rep["total"] > 100, f"only {rep['total']} sources found — a register went missing"
    rows = sr._iter_registered()
    slow = [e for _r, e in rows
            if sr.cadence_days(e) and sr.cadence_days(e) > sr.DAILY_TIER_MAX_DAYS]
    assert len(slow) >= 40, (
        f"only {len(slow)} sources declare a slower-than-daily cadence; on 13 Sep "
        f"2026 there were 56, and 49 series in the daily tier had never moved")
    assert rep["may_enter_daily_tier"] < rep["total"], (
        "every registered source was allowed into the daily tier — the gate is open")
