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

def test_an_overdue_annual_series_has_NO_known_next_date():
    """Emil, 6 Sep 2026. The first version rolled an overdue series forward to
    today + 366 so a comparison could be made. That was a DEFAULT STANDING IN FOR
    A MISSING VALUE: nobody knows when the World Bank will publish, and inventing
    a date to judge against is the defect this file exists to remove. The honest
    answer is None, and the caller refuses by name."""
    last = date(2024, 12, 31)
    assert cd.is_overdue(last, "annual", TODAY) is True
    assert cd.next_expected(last, "annual", TODAY) is None


def test_a_series_that_is_not_overdue_keeps_its_natural_due_date():
    last = date(2026, 8, 30)
    assert cd.is_overdue(last, "annual", TODAY) is False
    assert cd.next_expected(last, "annual", TODAY) == date(2027, 8, 31)


def test_an_unknown_last_observation_is_a_named_unknown_not_today():
    assert cd.next_expected(None, "annual", TODAY) is None


# ── the refusals the gate must produce ───────────────────────────────────────

def test_water_review_with_a_four_day_deadline_is_refused_by_name():
    """THE CASE THAT PROMPTED THIS. Admitted last night; refused now.

    The reason changed on 6 Sep from "cadence: ... before any new observation" to
    "overdue: ... next publication date unknown". WATER_REVIEW's 2025 figure has
    not arrived, so there IS no next date to compare a deadline against, and the
    earlier wording implied one existed."""
    reason = cd.deadline_refusal("WATER_REVIEW", date(2026, 9, 10), today=TODAY)
    assert reason, "WATER_REVIEW +1.2 by 2026-09-10 is still admitted"
    assert reason.startswith("overdue:")
    assert "WATER_REVIEW" in reason and "annual" in reason
    assert "2024-12-31" in reason, "the last observation date must be named"
    assert "next publication date unknown" in reason


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
    why = v["why"] if isinstance(v["why"], list) else [v["why"]]
    assert any("overdue:" in w for w in why), why


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


# ── the five horizons, pinned ───────────────────────────────────────────────
# There is no global maximum. How far a prediction may reach is a property of how
# often the thing is measured. Pinned so a change is a deliberate act with a
# visible diff, not a quiet loosening that makes proposals start passing.

def test_the_five_horizons_are_exactly_these():
    assert cd.HORIZON_DAYS == {"daily": 30, "weekly": 60,
                               "monthly": 90, "quarterly": 180}
    assert cd.ANNUAL_GRACE_DAYS == 90


def test_there_is_no_global_horizon_left_in_judge():
    src = (REPO / "core" / "proposal_intake.py").read_text(encoding="utf-8")
    body = src.split("def judge(", 1)[1].split(chr(10) + "def ", 1)[0]
    assert "MAX_HORIZON_DAYS" not in body, (
        "judge still applies a global cap; the horizon is the cadence's business")


@pytest.mark.parametrize("cadence,ok_days,too_far", [
    ("daily", 30, 31), ("weekly", 60, 61),
    ("monthly", 90, 91), ("quarterly", 180, 181),
])
def test_each_tier_reaches_exactly_its_horizon(tmp_path, cadence, ok_days, too_far):
    from datetime import timedelta
    decl = tmp_path / "cad.json"
    decl.write_text(json.dumps({"indicators": {"X": {
        "cadence": cadence, "last_observed_from": "d.when"}}}), encoding="utf-8")
    snap = tmp_path / "snap.json"
    # last observed today, so the series is never overdue in this test
    snap.write_text(json.dumps({"d": {"when": TODAY.isoformat()}}), encoding="utf-8")
    at = cd.deadline_refusal("X", TODAY + timedelta(days=ok_days), snap, decl, TODAY)
    beyond = cd.deadline_refusal("X", TODAY + timedelta(days=too_far), snap, decl, TODAY)
    assert at is None, f"{cadence} should reach {ok_days} days: {at}"
    assert beyond and beyond.startswith("horizon:"), (cadence, beyond)


def test_annual_reaches_next_expected_plus_the_grace(tmp_path):
    from datetime import timedelta
    decl = tmp_path / "cad.json"
    decl.write_text(json.dumps({"indicators": {"X": {
        "cadence": "annual", "last_observed_from": "d.when"}}}), encoding="utf-8")
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"d": {"when": "2025-12-31"}}), encoding="utf-8")
    nxt = date(2027, 1, 1)          # 2025-12-31 + 366
    assert cd.deadline_refusal("X", nxt - timedelta(days=1), snap, decl, TODAY), \
        "a deadline BEFORE the next observation must still be refused"
    assert cd.deadline_refusal("X", nxt, snap, decl, TODAY) is None
    assert cd.deadline_refusal(
        "X", nxt + timedelta(days=cd.ANNUAL_GRACE_DAYS), snap, decl, TODAY) is None
    beyond = cd.deadline_refusal(
        "X", nxt + timedelta(days=cd.ANNUAL_GRACE_DAYS + 1), snap, decl, TODAY)
    assert beyond and beyond.startswith("horizon:"), beyond


def test_an_overdue_series_is_refused_by_name_at_any_deadline(tmp_path):
    from datetime import timedelta
    for days in (10, 200, 400, 1000):
        r = cd.deadline_refusal("WATER_REVIEW", TODAY + timedelta(days=days),
                                today=TODAY)
        assert r and r.startswith("overdue:"), (days, r)
        assert "next publication date unknown" in r
        assert "2024-12-31" in r


def test_how_many_of_the_thirteen_are_usable_tonight():
    """THE TRUE STATE, recorded. Two: CO2 (daily) and PLANETARY_POTENTIAL, whose
    2025 figure means its next is genuinely still ahead. The other eleven are
    overdue or have no observation date at all. This is not a regression and the
    fix is a monthly tier, not a looser gate."""
    from datetime import timedelta
    from core.gate_contract import gradeable_indicators
    usable = []
    for k in gradeable_indicators():
        info = cd.for_indicator(k, today=TODAY)
        if info["tier"] == "DAILY-TIER":
            probe = TODAY + timedelta(days=7)
        elif info["next_expected"]:
            probe = date.fromisoformat(info["next_expected"]) + timedelta(days=1)
        else:
            probe = TODAY + timedelta(days=30)
        if cd.deadline_refusal(k, probe, today=TODAY) is None:
            usable.append(k)
    assert sorted(usable) == ["CLIMATE_GLOBAL_RISK_REVIEW",
                              "PLANETARY_POTENTIAL_REVIEW"], sorted(usable)
