# -*- coding: utf-8 -*-
"""
A deadline is only meaningful if an observation can land inside it.
Written 6 Sep 2026 (Kimi R35), failing before the fix.

MEASURED: proposal_intake admitted `WATER_REVIEW +1.2 by 2026-09-10`.
WATER_REVIEW is the World Bank safe-water series, percent of population, LAST
OBSERVED IN 2024. Nothing could arrive by 10 September to settle "+1.2" either
way. The prediction is not wrong — it is unsettleable, and a ledger that scores
it scores noise.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import cadence as cd               # noqa: E402
from core import proposal_intake as pi       # noqa: E402

TODAY = date(2026, 9, 6)


# ── no default, anywhere ─────────────────────────────────────────────────────

def test_a_source_without_cadence_fails_at_load_and_is_named(tmp_path):
    bad = tmp_path / "specs.json"
    bad.write_text(json.dumps({
        "AXIS_A": {"portfolio": {"anchor": {"sources": [
            {"id": "declared_one", "org": "World Bank", "cadence": "annual"},
            {"id": "naked_one", "org": "Nobody"},
        ]}}}}), encoding="utf-8")
    with pytest.raises(cd.CadenceError) as exc:
        cd.load_specs(bad)
    # (First version named these src_with / src_without and the second
    # assertion always failed: "src_without" contains "src_with". The test
    # was wrong, not the loader.)
    assert "naked_one" in str(exc.value), str(exc.value)
    assert "declared_one" not in str(exc.value)


def test_every_source_in_the_real_specs_declares_a_cadence():
    rep = cd.audit_specs()
    assert not rep["missing"], (
        f"{len(rep['missing'])} of {rep['total']} sources declare no cadence: "
        + ", ".join(rep["missing"][:6]))
    assert rep["total"] == rep["with_cadence"] > 0


def test_an_undeclared_indicator_is_an_error_not_a_daily_one(tmp_path):
    decl = tmp_path / "cad.json"
    decl.write_text(json.dumps({"indicators": {}}), encoding="utf-8")
    with pytest.raises(cd.CadenceError) as exc:
        cd.for_indicator("SOMETHING_NOBODY_DECLARED", path=decl)
    assert "SOMETHING_NOBODY_DECLARED" in str(exc.value)


def test_a_cadence_outside_the_five_words_fails_by_name(tmp_path):
    decl = tmp_path / "cad.json"
    decl.write_text(json.dumps({"indicators": {
        "GOOD": {"cadence": "annual"}, "BAD": {"cadence": "occasionally"}}}),
        encoding="utf-8")
    with pytest.raises(cd.CadenceError) as exc:
        cd.declared(decl)
    assert "BAD" in str(exc.value) and "GOOD" not in str(exc.value)


# ── the overdue rule ─────────────────────────────────────────────────────────

def test_an_overdue_annual_series_rolls_forward_from_today():
    """WATER_REVIEW last observed 2024 means last+1y = 2026-01-01, already past.
    Saying "next expected January" would wave through a September deadline on a
    series that has not moved in two years."""
    last = date(2024, 12, 31)
    assert cd.is_overdue(last, "annual", TODAY) is True
    nxt = cd.next_expected(last, "annual", TODAY)
    assert nxt > TODAY, nxt


def test_a_series_that_is_not_overdue_keeps_its_natural_due_date():
    last = date(2026, 8, 30)
    assert cd.is_overdue(last, "annual", TODAY) is False
    assert cd.next_expected(last, "annual", TODAY) == date(2027, 8, 31)


def test_an_unknown_last_observation_is_a_named_unknown_not_today():
    assert cd.next_expected(None, "annual", TODAY) is None


# ── the refusals the gate must produce ───────────────────────────────────────

def test_water_review_with_a_four_day_deadline_is_refused_by_name():
    """THE CASE THAT PROMPTED THIS. Admitted last night; refused now."""
    reason = cd.deadline_refusal("WATER_REVIEW", date(2026, 9, 10))
    assert reason, "WATER_REVIEW +1.2 by 2026-09-10 is still admitted"
    assert reason.startswith("cadence:")
    assert "WATER_REVIEW" in reason and "annual" in reason
    assert "2024" in reason, "the last observation date must be named"
    assert "before any new observation" in reason


def test_a_daily_indicator_passes_the_cadence_check():
    assert cd.deadline_refusal("CLIMATE_GLOBAL_RISK_REVIEW", date(2026, 9, 10)) is None


def test_an_indicator_with_no_last_observation_is_refused_not_waved_through():
    reason = cd.deadline_refusal("GOVERNANCE_INSTITUTIONS_REVIEW", date(2027, 12, 1))
    assert reason and "last observation date is unknown" in reason


# ── through judge(), which is what actually decides ──────────────────────────

def _proposal(indicator, delta, deadline):
    return {"component": "X", "problem": "p", "solution": "s" * 20,
            "indicator": indicator, "expected_delta": delta, "deadline": deadline}


def test_judge_refuses_the_slow_indicator_deadline():
    v = pi.judge(_proposal("WATER_REVIEW", 1.2, "2026-09-10"), today=TODAY)
    assert v["verdict"] == "REFUSED", v
    assert "deadline" in v["missing"]
    assert any("cadence:" in w for w in
               (v["why"] if isinstance(v["why"], list) else [v["why"]])), v["why"]


def test_judge_lets_a_daily_indicator_through_on_the_same_deadline():
    v = pi.judge(_proposal("CLIMATE_GLOBAL_RISK_REVIEW", 0.5, "2026-09-10"), today=TODAY)
    why = v["why"] if isinstance(v["why"], list) else [str(v["why"])]
    assert not any("cadence:" in w for w in why), v


def test_the_cadence_check_never_waves_a_proposal_through_on_silence(monkeypatch):
    """If the cadence layer cannot answer it must SAY so, not stay quiet — the
    failure mode this whole week has been about."""
    import core.cadence as broken
    monkeypatch.setattr(broken, "deadline_refusal",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    # Inside MAX_HORIZON_DAYS, or judge refuses on horizon before the
    # cadence branch is ever reached - which is what the first version of
    # this test did, and it proved nothing.
    v = pi.judge(_proposal("WATER_REVIEW", 1.2, "2026-12-01"), today=TODAY)
    why = v["why"] if isinstance(v["why"], list) else [str(v["why"])]
    assert any("check unavailable" in w for w in why), why


# ── the prompt shows both groups ─────────────────────────────────────────────

def test_the_prompt_shows_both_tiers_with_next_expected_on_slow_lines():
    from core.gate_contract import indicator_block
    block = indicator_block()
    assert "DAILY-TIER" in block and "SLOW-TIER" in block
    slow = block.split("SLOW-TIER", 1)[1]
    for line in [l for l in slow.splitlines() if l.startswith("  ")]:
        assert "next expected" in line, line
        assert "DEADLINE MUST BE ON OR AFTER" in line, line


def test_the_prompt_still_says_none_when_nothing_resolved():
    from core.gate_contract import indicator_block
    assert "none resolved this cycle" in indicator_block({})


# ── the two rules collide, and that is a finding, not a bug ─────────────────

def test_the_horizon_and_the_cadence_rule_together_lock_out_most_indicators():
    """MEASURED 6 Sep 2026, recorded so nobody has to rediscover it.

    MAX_HORIZON_DAYS is 365. An OVERDUE annual series rolls forward to
    today + 366, so its earliest settleable deadline is ONE DAY beyond the
    furthest deadline the gate will accept. Eleven of the thirteen indicators
    are therefore unusable for any proposal at all: too slow to settle inside a
    year, and a year is the most the gate allows.

    This test does not assert that the situation is correct. It pins the numbers
    so that changing either constant is a deliberate act with a visible diff,
    rather than a quiet tune that makes proposals start passing again.
    """
    from datetime import timedelta
    step = cd._STEP_DAYS["annual"]
    assert step == 366, "annual step changed; re-read the collision note"
    assert pi.MAX_HORIZON_DAYS == 365, "horizon changed; re-read the collision note"
    overdue_next = TODAY + timedelta(days=step)
    furthest_allowed = TODAY + timedelta(days=pi.MAX_HORIZON_DAYS)
    assert overdue_next > furthest_allowed, (
        "the collision is gone - an overdue annual series can now be predicted "
        "inside the horizon. Update the report before relying on it.")
