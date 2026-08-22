#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_one_ceiling.py — A BUDGET THAT OUTLIVES ITS CEILING IS NOT A BUDGET.

Two independent readers of config/scheduler.json used to disagree in production.
Measured 22 Aug 2026 with survival mode latched:

    internet_intelligence   watchdog 2397s   step budget 3600s

The step was authorised to spend 1203s longer than the watchdog would tolerate,
so the budget could never be the binding limit and the kill was guaranteed to
arrive first.

The rule, written into that config's README and enforced here:

    config/scheduler.json step_ceilings_sec is the SOURCE OF TRUTH.
    core/step_budget.effective_ceiling is the ONE function that applies it.
    Every derived number may only TIGHTEN it, never widen it.

    venv\\Scripts\\python.exe -m pytest test/test_one_ceiling.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import core.step_budget as sb  # noqa: E402
import core.survival_mode as sm  # noqa: E402
import supervisor  # noqa: E402
from core.cycle_map import STEPS  # noqa: E402

CFG = json.loads((REPO / "config" / "scheduler.json").read_text(encoding="utf-8"))
STEP_NAMES = list(dict.fromkeys(s[0] for s in STEPS))


# ---------------------------------------------------------------------------
# They agree — on every step, in both modes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("survival", [False, True])
def test_no_step_budget_exceeds_the_watchdog_ceiling(monkeypatch, survival):
    monkeypatch.setattr(sm, "resolve",
                        lambda today, **k: (survival, "unit", False))
    over = []
    for step in STEP_NAMES:
        ceiling = supervisor.ceiling_for(step, CFG)
        budget = sb.budget_for(step).seconds
        if budget > ceiling:
            over.append((step, ceiling, budget))
    assert not over, (
        f"survival={survival}: {len(over)} step(s) may spend longer than the "
        f"watchdog tolerates: {over[:5]}")


def test_the_watchdog_and_the_budget_read_the_same_function():
    """Delegation, not duplication — duplication is what caused the drift."""
    import inspect
    src = inspect.getsource(supervisor.ceiling_for)
    assert "effective_ceiling" in src, (
        "supervisor.ceiling_for computes its own ceiling again; two readers of "
        "one config is exactly the defect this file pins")


# ---------------------------------------------------------------------------
# Tighten only
# ---------------------------------------------------------------------------

def test_survival_may_not_widen_a_ceiling(monkeypatch):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "unit", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (99_999.0, "p50"))
    ceilings = CFG["step_ceilings_sec"]
    for step in ("daily_analysis", "web_intelligence"):
        assert sb.effective_ceiling(step, ceilings) == float(int(ceilings[step])), (
            "a p50 above the human ceiling raised it; config/scheduler.json's "
            "README forbids a system widening its own limit")


def test_a_learned_budget_may_not_widen_a_ceiling():
    """internet_intelligence has only a few runs, so its p95 IS its maximum and
    p95 x 1.5 came out at 3766s against a 3600s ceiling."""
    b = sb.budget_for("internet_intelligence")
    assert b.seconds <= sb.effective_ceiling("internet_intelligence")


# ---------------------------------------------------------------------------
# The degenerate p50
# ---------------------------------------------------------------------------

def test_a_tiny_p50_cannot_produce_an_absurd_ceiling(monkeypatch):
    """Measured before the floor: data_scout's p50 gave a ceiling of ONE SECOND,
    against a budget of 471s. A step that usually no-ops has a tiny median and
    would be declared overrun before it finished importing."""
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "unit", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (0.4, "p50"))
    got = sb.effective_ceiling("data_scout", CFG["step_ceilings_sec"])
    assert got >= sb.MIN_SURVIVAL_CEILING_SEC, (
        f"survival ceiling for data_scout came out at {got}s")


def test_the_floor_never_widens_a_ceiling_that_is_already_lower(monkeypatch):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "unit", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (0.4, "p50"))
    tight = {"_default": 30, "data_scout": 30}
    assert sb.effective_ceiling("data_scout", tight) == 30.0, (
        "the survival floor raised a human ceiling that was deliberately lower")


# ---------------------------------------------------------------------------
# Whole seconds
# ---------------------------------------------------------------------------

def test_the_ceiling_is_always_whole_seconds(monkeypatch):
    """The watchdog compares an int. A fractional ceiling meant one reader
    truncated 2397.5 to 2397 while the other kept 2397.5, and the budget ended up
    one second longer than the ceiling clamping it."""
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "unit", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (2397.5, "p50"))
    got = sb.effective_ceiling("internet_intelligence", CFG["step_ceilings_sec"])
    assert got == float(int(got)), f"{got} is not a whole number of seconds"


# ---------------------------------------------------------------------------
# The config still says so
# ---------------------------------------------------------------------------

def test_the_config_documents_which_file_wins():
    readme = " ".join(CFG.get("_README", []))
    assert "effective_ceiling" in readme, (
        "config/scheduler.json no longer names the one function that applies it; "
        "the next person to add a duration table will not know this rule exists")
    assert "SOURCE OF TRUTH" in readme.upper()


def test_a_broken_survival_lookup_falls_back_to_the_human_number(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(sm, "resolve", _boom)
    ceilings = CFG["step_ceilings_sec"]
    assert sb.effective_ceiling("daily_analysis", ceilings) == \
        float(int(ceilings["daily_analysis"]))
