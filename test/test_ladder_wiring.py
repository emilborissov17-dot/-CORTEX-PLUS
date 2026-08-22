#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_ladder_wiring.py — A SILENT DEGRADED IS A LIE.

core/step_budget.py's ladder is tested on its own in test_step_budget_ladder.py.
What is tested here is what happens once it is the thing standing between the
cycle and a dead provider — the part that decides whether a human can tell, in
the morning, that the night ran on a weaker footing.

The three claims:

  * A CLOUD THAT NEVER ANSWERS COSTS B, NOT THE CYCLE. The old chain had no
    caller-controlled timeout: a provider that accepts the connection and then
    says nothing blocked until its own socket gave up, the step stopped beating,
    and the watchdog killed the cycle. All six internet_intelligence kills in
    the ledger have that shape.

  * THE VERDICT SURVIVES _run()'s except. _run prints one line and carries on,
    so a step that degraded used to look exactly like a step that worked. The
    degradation is recorded on the contract BEFORE the exception is raised.

  * ONE BUDGET PER STEP, NOT PER CALL. daily_analysis made 24 model calls in a
    single run. Each getting B would be a budget of 24xB.

Every test here uses a fake clock or a sub-second budget. A test that needs real
minutes to prove a timeout is a test nobody runs.

    venv\\Scripts\\python.exe -m pytest test/test_ladder_wiring.py -v
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import core.step_budget as sb  # noqa: E402
import core.step_contract as sc  # noqa: E402


@pytest.fixture(autouse=True)
def _no_open_step():
    sb._open_step = None
    sc._CURRENT = None
    yield
    sb._open_step = None
    sc._CURRENT = None


@pytest.fixture
def contract(tmp_path):
    """A real StepContract writing into tmp_path, registered as current."""
    c = sc.StepContract("unit_step", base=tmp_path,
                        baseline_path=tmp_path / "baseline.json",
                        report_path=tmp_path / "report.json",
                        callmap_path=tmp_path / "callmap.json",
                        announce=lambda *a, **k: None)
    c.__enter__()
    return c


# ---------------------------------------------------------------------------
# The step account
# ---------------------------------------------------------------------------

def test_every_call_in_a_step_draws_from_one_budget(monkeypatch):
    monkeypatch.setattr(sb, "budget_for",
                        lambda s, b=None, c=None, factor=1.5: sb.Budget(s, 3.0, "unit", 0))
    sb.begin_step("unit_step", sb.NORMAL)

    for _ in range(3):
        sb.run_call(cloud=lambda: (time.sleep(0.6), "x")[1])

    spent = sb.end_step()
    assert spent["calls"] == 3
    assert spent["spent"] > 0, "three calls spent nothing; the account is not charged"


def test_once_the_budget_is_gone_further_calls_degrade_without_waiting(monkeypatch):
    """Note the shape: one call cannot drain the account.

    A hanging cloud is abandoned at its slice, B/3, so with no local tier
    configured each call spends a third and it takes three to empty the budget.
    That is the ladder working as designed, not a leak — it is written down here
    because the first version of this test assumed one call would do it.
    """
    monkeypatch.setattr(sb, "budget_for",
                        lambda s, b=None, c=None, factor=1.5: sb.Budget(s, 9.0, "unit", 0))
    sb.begin_step("unit_step", sb.NORMAL)
    for _ in range(4):
        sb.run_call(cloud=lambda: time.sleep(30.0))

    assert sb.remaining_sec() / 3.0 < sb.MIN_TIER_SEC, (
        f"four abandoned calls left {sb.remaining_sec():.2f}s, still enough for a "
        f"tier slice; the account decays by a third each time and never reaches "
        f"zero, which is why emptiness is defined by MIN_TIER_SEC")

    called = []
    t0 = time.monotonic()
    res = sb.run_call(cloud=lambda: called.append("ran"))
    took = time.monotonic() - t0

    assert res.outcome == sb.DEGRADED
    assert called == [], "the cloud was called after the step's budget was spent"
    assert took < 0.3, f"an exhausted budget still waited {took:.2f}s"
    assert "already spent" in res.reason
    assert any("budget exhausted" in (a.error or "") for a in res.attempts), (
        "the attempt record must say WHY nothing was tried")


def test_a_call_may_not_exceed_what_the_step_has_left(monkeypatch):
    """The regression that the first run of this code produced: '10s of B=6s'.

    A MIN_BUDGET_SEC floor applied per CALL granted 30s out of an account holding
    6. The floor belongs to the step's budget, not to each call against it.
    """
    monkeypatch.setattr(sb, "budget_for",
                        lambda s, b=None, c=None, factor=1.5: sb.Budget(s, 1.0, "unit", 0))
    sb.begin_step("unit_step", sb.NORMAL)
    t0 = time.monotonic()
    sb.run_call(cloud=lambda: time.sleep(30))
    took = time.monotonic() - t0
    assert took < sb.MIN_BUDGET_SEC, (
        f"one call took {took:.1f}s from a step budget of 1.0s; a budget a call "
        f"may exceed is a suggestion, not a budget")


def test_a_call_outside_any_step_still_works():
    """Scripts and selftests call the model too, and must not be blocked."""
    res = sb.run_call(cloud=lambda: "an answer")
    assert res.outcome == sb.OK and res.value == "an answer"


# ---------------------------------------------------------------------------
# The verdict reaches the contract
# ---------------------------------------------------------------------------

def test_a_degradation_lands_on_the_running_step(contract):
    assert sc.note_degraded_on_current("the cloud was abandoned") is True
    result = contract.finish()
    assert result["verdict"] == sc.DEGRADED
    assert "abandoned" in result["why"]
    assert result["degraded_calls"] == 1


def test_several_degraded_calls_are_counted_not_overwritten(contract):
    for i in range(4):
        sc.note_degraded_on_current(f"call {i} fell to the local model")
    result = contract.finish()
    assert result["degraded_calls"] == 4
    assert "3 more degraded call(s)" in result["why"], (
        "'one call degraded' and 'four did' are different facts about the night")


def test_degraded_outranks_the_warmup_verdict(contract):
    """UNKNOWN means 'no baseline yet'. DEGRADED is knowable on the first run."""
    sc.note_degraded_on_current("no tier answered")
    result = contract.finish()
    assert result["verdict"] == sc.DEGRADED, (
        "warmup swallowed the degradation; the first three runs of a new step "
        "are exactly when a human is watching")


def test_a_step_that_raised_is_still_RAISED_not_DEGRADED(contract):
    sc.note_degraded_on_current("fell to local")
    contract.note_swallowed("ValueError: boom")
    result = contract.finish()
    assert result["verdict"] == sc.RAISED, (
        "a step that threw is not merely degraded, and RAISED is the louder truth")


def test_a_degradation_with_no_open_step_is_reported_as_not_landing():
    sc._CURRENT = None
    assert sc.note_degraded_on_current("nowhere to go") is False, (
        "returning True would let a caller believe a degradation was recorded "
        "when nothing recorded it")


def test_the_contract_is_cleared_when_the_step_finishes(contract):
    contract.finish()
    assert sc.current() is None, (
        "a degradation noted after the step was judged would land on a contract "
        "that has already been sentenced, or leak into the next step")


# ---------------------------------------------------------------------------
# The 8b tier is gated by the window, not only by priority
# ---------------------------------------------------------------------------

def test_the_8b_tier_is_not_offered_while_the_window_is_shut():
    """Source-level: the callable itself is withheld, not merely skipped.

    Handing step_budget an 8b callable outside the window would evict the pinned
    3b mid-step — the churn core/model_window.py exists to remove — and the
    ladder's own CRITICAL check is about priority, not residency.
    """
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8",
                                                        errors="replace")
    assert "local_8b=_local_tier(_big) if _mw.is_open() else None" in src, (
        "the 8b tier is no longer gated on the model window being open")


def test_a_normal_step_never_reaches_the_8b_tier():
    b = sb.Budget("unit_step", 3.0, "unit", 0)
    res = sb.run_with_ladder("unit_step", sb.NORMAL, b,
                             cloud=lambda: None, local_3b=lambda: None,
                             local_8b=lambda: "the big model answered")
    assert res.outcome == sb.DEGRADED
    assert res.value != "the big model answered"


def test_a_critical_step_may_reach_the_8b_tier():
    b = sb.Budget("unit_step", 3.0, "unit", 0)
    res = sb.run_with_ladder("unit_step", sb.CRITICAL, b,
                             cloud=lambda: None, local_3b=lambda: None,
                             local_8b=lambda: "the big model answered")
    assert res.outcome == sb.OK and res.value == "the big model answered"


# ---------------------------------------------------------------------------
# The step path no longer blocks
# ---------------------------------------------------------------------------

def test_a_hanging_cloud_costs_the_budget_and_not_the_cycle(monkeypatch):
    monkeypatch.setattr(sb, "budget_for",
                        lambda s, b=None, c=None, factor=1.5: sb.Budget(s, 1.2, "unit", 0))
    sb.begin_step("internet_intelligence", sb.NORMAL)

    t0 = time.monotonic()
    res = sb.run_call(cloud=lambda: time.sleep(600))
    took = time.monotonic() - t0

    assert res.outcome == sb.DEGRADED
    assert took < 3.0, (
        f"a cloud that never answers held the step for {took:.1f}s. This is the "
        f"shape of all six internet_intelligence kills in the existence ledger")


def test_the_runner_opens_and_closes_the_account_around_every_step():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8",
                                                    errors="replace")
    assert "_sb.begin_step(" in src, "no step ever opens a budget account"
    assert "_sb.end_step()" in src, "the account is never closed"
    assert src.index("_sb.end_step()") < src.index("_contract.finish()"), (
        "the account must close BEFORE the contract is judged — the verdict "
        "depends on what the account recorded")
