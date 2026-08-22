#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_survival_wiring.py — BUDGET EXHAUSTED MEANS "SURVIVE ON LESS", NOT "STOP".

core/survival_mode.py is tested on its own. This holds the three joins that make
it real:

  * the supervisor LATCHES the flag when the restart budget runs out, instead of
    only failing loudly. It still does not spawn another cycle — a system that can
    restart itself indefinitely has no restart budget, and that limit is the point.
    What changes is what the NEXT cycle inherits.
  * the runner READS the latch before its first step. This is the join that
    matters most, because the 03:00 cycle is started by the Windows scheduler and
    has no parent to inherit anything from. The persisted flag is the only thing
    that crosses that gap.
  * the ceiling the WATCHDOG uses drops to p50 under survival, and may only ever
    tighten — config/scheduler.json stays the single source of truth.

    venv\\Scripts\\python.exe -m pytest test/test_survival_wiring.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import core.survival_mode as sm  # noqa: E402
import fast_cycle_runner as r  # noqa: E402
import supervisor  # noqa: E402


# ---------------------------------------------------------------------------
# The runner reads the latch
# ---------------------------------------------------------------------------

def test_the_runner_runs_only_critical_steps_when_the_flag_is_latched(monkeypatch):
    monkeypatch.setattr(sm, "resolve",
                        lambda today, **k: (True, "budget exhausted", False))
    d = r._decide_survival()
    assert d["active"] is True
    assert d["skip"], "survival mode active but no step is skipped"

    from core.cycle_map import STEPS
    names = [s[0] for s in STEPS]
    table = sm.load_priorities()
    for step in d["skip"]:
        assert table.get(step, sm.NORMAL) != sm.CRITICAL, (
            f"{step} is CRITICAL and was skipped under survival mode")
    assert set(d["skip"]) <= set(names)


def test_nothing_is_skipped_when_the_flag_is_down(monkeypatch):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (False, "healthy", False))
    d = r._decide_survival()
    assert d["active"] is False
    assert d["skip"] == frozenset()


def test_a_plan_that_would_run_nothing_is_refused(monkeypatch):
    """No priority table means no step is CRITICAL, so survival would run zero
    steps. A night that measures nothing is worse than one that costs too much."""
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "budget", False))
    monkeypatch.setattr(sm, "load_priorities", lambda base=None: {})
    d = r._decide_survival()
    assert d["active"] is False
    assert "empty" in d["reason"]


def test_a_broken_survival_check_runs_the_full_cycle(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("state unreadable")

    monkeypatch.setattr(sm, "resolve", _boom)
    d = r._decide_survival()
    assert d["active"] is False, "an unreadable flag must not silently reduce the night"
    assert "failed" in d["reason"]


def test_run_skips_a_normal_step_under_survival(monkeypatch):
    import core.step_contract as sc

    class _NoContract:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def note_swallowed(self, *a, **k):
            pass

        def finish(self):
            pass

    monkeypatch.setattr(sc, "StepContract", _NoContract)
    # _run also drives the model window, which persists memory/model_window.json.
    # Live state, which test/conftest.py rightly fails on.
    import core.model_window as mw
    monkeypatch.setattr(mw, "on_step", lambda *a, **k: {"changed": False})
    monkeypatch.setattr(r, "_SURVIVAL", {"active": True, "reason": "unit",
                                         "skip": frozenset({"data_scout"}),
                                         "ceilings": {}})
    called = []
    r._run("data_scout", lambda: called.append("ran"))
    assert called == [], "a NORMAL step ran while the system was surviving on less"


# ---------------------------------------------------------------------------
# The ceiling the watchdog uses
# ---------------------------------------------------------------------------

CFG = {"step_ceilings_sec": {"_default": 900, "daily_analysis": 1500}}


def test_the_ceiling_is_untouched_when_survival_is_off(monkeypatch):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (False, "healthy", False))
    assert supervisor.ceiling_for("daily_analysis", CFG) == 1500


def test_the_ceiling_drops_to_p50_under_survival(monkeypatch):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "budget", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (400.0, "p50 of 5 runs"))
    assert supervisor.ceiling_for("daily_analysis", CFG) == 400


def test_survival_may_only_tighten_a_ceiling_never_widen_it(monkeypatch):
    """config/scheduler.json's README: a system that can widen its own limits
    has no limits. p50 above the human ceiling must not raise it."""
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "budget", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (9999.0, "p50"))
    assert supervisor.ceiling_for("daily_analysis", CFG) == 1500


def test_a_step_with_no_p50_keeps_its_configured_ceiling(monkeypatch):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (True, "budget", False))
    monkeypatch.setattr(sm, "p50_ceiling",
                        lambda step, baseline=None, ceilings=None: (1500, "ceiling (no p50)"))
    assert supervisor.ceiling_for("daily_analysis", CFG) == 1500


def test_a_broken_survival_lookup_leaves_the_ceiling_alone(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(sm, "resolve", _boom)
    assert supervisor.ceiling_for("daily_analysis", CFG) == 1500, (
        "a failure in the survival lookup must not change what the watchdog kills on")


# ---------------------------------------------------------------------------
# Source-level joins
# ---------------------------------------------------------------------------

def test_the_supervisor_latches_instead_of_only_alarming():
    src = (REPO / "supervisor.py").read_text(encoding="utf-8", errors="replace")
    assert "_sm.enter(" in src, (
        "budget exhausted no longer latches survival mode; the next cycle would "
        "start at full fat into the wall that emptied the budget")
    assert "notifier=lambda" in src, (
        "survival_mode.enter must be given the notifier, never import one — on "
        "16 Aug 2026 a module that reached for its own alarm path sent the human "
        "a real emergency about a failure that never happened")


def test_the_supervisor_still_does_not_spawn_another_cycle_on_budget_done():
    """Survival mode is what the NEXT cycle inherits, not permission to retry now."""
    import inspect
    src = inspect.getsource(supervisor.tick)
    after = src.split("KILL_BUDGET_DONE")[-1]
    tail = after[after.rfind("_sm.enter("):] if "_sm.enter(" in after else after
    assert "spawn_cycle(" not in tail, (
        "the budget-exhausted branch spawns a cycle; the restart budget would "
        "mean nothing")


def test_the_flag_is_cleared_only_after_a_cycle_finishes():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8", errors="replace")
    assert "_sm.clear()" in src, "nothing ever lifts the latch"
    assert src.index("_sm.clear()") > src.index("_decide_survival(sys.argv)"), (
        "the flag is cleared before it is read — every cycle would start by "
        "forgetting why it was told to be careful")
    assert "_seal_cycle_record()" in src
    assert src.index("_sm.clear()") < src.rindex("_seal_cycle_record()"), (
        "clearing belongs inside the cycle that earned it")


# ---------------------------------------------------------------------------
# The human's hand outranks a poverty derived from disk
# ---------------------------------------------------------------------------
# resolve() returns (active, reason, is_new). is_new separates the two sources:
#   False -> the persisted LATCH: a decision already taken, binding every origin.
#   True  -> DERIVED this second from the restart budget / failure block.
# The restart budget bounds UNATTENDED restarts, and the failure banner asks for
# human intervention in as many words. A hand-started run IS that intervention.

def _derived(reason="restart budget exhausted for today (2/2)"):
    return lambda today, **k: (True, reason, True)


def _latched(reason="latched yesterday, no cycle has finished since"):
    return lambda today, **k: (True, reason, False)


def test_a_manual_run_under_an_exhausted_budget_runs_the_full_profile(monkeypatch):
    monkeypatch.setattr(sm, "resolve", _derived())
    d = r._decide_survival(argv=[], origin="manual")
    assert d["active"] is False, (
        "a run started BY HAND was reduced by the restart budget — the budget "
        "guards unattended restarts, and this run is the intervention the "
        "failure banner asked for")
    assert d["profile"] == "FULL"
    assert d["skip"] == frozenset()
    assert "manual" in d["reason"]


def test_the_same_derivation_still_reduces_a_scheduled_run(monkeypatch):
    monkeypatch.setattr(sm, "resolve", _derived())
    d = r._decide_survival(argv=[], origin="scheduled")
    assert d["active"] is True, (
        "the exemption leaked to the cycle it was never meant for: an unattended "
        "03:00 run under an exhausted budget must still degrade")
    assert d["skip"]
    assert d["profile"] == "SURVIVAL"


def test_the_latch_binds_a_manual_run_too(monkeypatch):
    """Derived poverty is an inference; the latch is a decision already taken."""
    monkeypatch.setattr(sm, "resolve", _latched())
    d = r._decide_survival(argv=[], origin="manual")
    assert d["active"] is True
    assert d["profile"] == "SURVIVAL"
    assert "latch" in d["profile_why"]


def test_full_overrides_even_the_latch_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(sm, "resolve", _latched())
    d = r._decide_survival(argv=["--full"], origin="manual")
    assert d["active"] is False
    assert d["profile"] == "FULL"
    assert "HUMAN OVERRIDE" in capsys.readouterr().out, (
        "a person overrode a persisted decision and the log does not say so")


def test_a_manual_run_may_opt_in_with_survival(monkeypatch):
    """Nothing on disk says the system is poor; the human says it anyway."""
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (False, "healthy", False))
    d = r._decide_survival(argv=["--survival"], origin="manual")
    assert d["active"] is True
    assert d["skip"]
    assert "--survival" in d["reason"]


def test_both_flags_resolve_to_survival_and_the_conflict_is_printed(monkeypatch, capsys):
    monkeypatch.setattr(sm, "resolve", lambda today, **k: (False, "healthy", False))
    d = r._decide_survival(argv=["--survival", "--full"], origin="manual")
    assert d["active"] is True, "the cheaper night is the recoverable mistake"
    assert "CONFLICT" in capsys.readouterr().out


def test_the_profile_and_the_reason_are_always_recorded(monkeypatch):
    """Every return path carries the one line the cycle log prints."""
    for resolver in (_derived(), _latched(),
                     lambda today, **k: (False, "healthy", False)):
        monkeypatch.setattr(sm, "resolve", resolver)
        for origin in ("manual", "scheduled"):
            d = r._decide_survival(argv=[], origin=origin)
            assert d["profile"] in ("FULL", "SURVIVAL")
            assert d["profile_why"] and d["reason"]


def test_origin_is_read_from_the_env_the_spawner_sets(monkeypatch):
    monkeypatch.delenv("CORTEX_CYCLE_ID", raising=False)
    assert r._cycle_origin() == "manual"
    monkeypatch.setenv("CORTEX_CYCLE_ID", "2026-08-22T03:00:00+03:00")
    assert r._cycle_origin() == "scheduled"
    monkeypatch.setenv("CORTEX_CYCLE_ID", "   ")
    assert r._cycle_origin() == "manual", "a blank env var named nothing"


def test_a_broken_check_is_full_for_everyone(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("state unreadable")

    monkeypatch.setattr(sm, "resolve", _boom)
    for origin in ("manual", "scheduled"):
        d = r._decide_survival(argv=[], origin=origin)
        assert d["active"] is False and d["profile"] == "FULL"


def test_the_cycle_log_carries_the_profile_line():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8", errors="replace")
    assert "PROFILE:" in src, (
        "nothing writes which profile won; the log would show the consequences "
        "of a decision without the decision")
    assert src.index("_decide_survival(sys.argv)") < src.index("PROFILE:")
