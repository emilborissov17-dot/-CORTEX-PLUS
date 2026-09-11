# -*- coding: utf-8 -*-
"""test/test_learner_bridge.py — the brain reads what the learner learned (Emil, 11 Sep 2026).

Pinned:
  * learner_report(): per indicator alpha + ledger outcomes; degenerate rows excluded
  * learner_briefing(): names BEATS / LOSES / unscored; empty when there is nothing
  * the brain's briefing state carries the block when the learner has something to say
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
import world_forecast as wf  # noqa: E402
import prophecy_ledger as pl  # noqa: E402

STATE = {"MARKET_SPY_CLOSE": {"alpha": 0.3, "fitted_on": 60}, "DAILY::usgs.m5_7d": {"alpha": 0.9, "fitted_on": 80}}


def _rec(h, ind, learner, baseline, deg=False):
    return {"event": pl.PREDICTION, "hash": h, "target_kind": wf.KIND, "indicator": ind,
            "learner": learner, "baseline": baseline, "degenerate": deg}


def _out(h, ind, le, be):
    return {"event": pl.OUTCOME, "ref_hash": h, "indicator": ind, "learner_err": le, "baseline_err": be, "learner_wins": le < be}


RECORDS = [_rec("a", "MARKET_SPY_CLOSE", 1.0, 1.1), _out("a", "MARKET_SPY_CLOSE", 0.5, 1.0),
           _rec("b", "MARKET_SPY_CLOSE", 1.0, 1.2), _out("b", "MARKET_SPY_CLOSE", 0.4, 0.9),
           _rec("c", "DAILY::usgs.m5_7d", 30.0, 31.0), _out("c", "DAILY::usgs.m5_7d", 5.0, 2.0),
           _rec("d", "DAILY::usgs.m5_7d", 30.0, 30.0, deg=True), _out("d", "DAILY::usgs.m5_7d", 0.0, 0.0)]


def test_learner_report_counts_per_indicator_and_skips_degenerate():
    r = wf.learner_report(records=RECORDS, state=STATE)
    spy, usgs = r["MARKET_SPY_CLOSE"], r["DAILY::usgs.m5_7d"]
    assert spy["alpha"] == 0.3 and spy["compared"] == 2 and spy["wins"] == 2 and spy["beats_persistence"]
    assert spy["learner_mean_err"] == 0.45 and spy["baseline_mean_err"] == 0.95
    assert usgs["compared"] == 1 and not usgs["beats_persistence"]          # the degenerate one is not counted


def test_learner_briefing_names_what_is_and_is_not_predictable():
    txt = wf.learner_briefing(wf.learner_report(records=RECORDS, state=dict(STATE, X={"alpha": 0.5, "fitted_on": 12})))
    assert "beats persistence on 1, loses on 1, 1 not yet scored" in txt
    assert "MARKET_SPY_CLOSE: alpha=0.3" in txt and "-> BEATS" in txt and "-> LOSES" in txt and "-> unscored" in txt
    assert wf.learner_briefing({}) == "" and wf.learner_briefing(wf.learner_report(records=[], state={})) == ""


def test_the_brain_briefing_carries_the_learner_block(monkeypatch):
    from core import brain
    monkeypatch.setattr(brain, "recent_reviews", lambda n=3: [])
    monkeypatch.setattr(brain, "_learner_briefing", lambda: "learner: 2 indicators ...")
    assert "--- WHAT THE LEARNER HAS LEARNED" in brain._state_for_briefing()
    monkeypatch.setattr(brain, "_learner_briefing", lambda: "")
    assert "WHAT THE LEARNER" not in brain._state_for_briefing()


# ── a tie is not a loss (11 Sep 2026) ────────────────────────────────────────

def _row(le, pe, compared=1, wins=0, beats=False):
    return {"alpha": 0.9, "fitted_on": 94, "compared": compared, "wins": wins,
            "learner_mean_err": le, "baseline_mean_err": pe,
            "beats_persistence": beats}


def test_a_tie_at_zero_is_not_reported_as_a_loss():
    """THE DEFECT, from the first live briefing. Three CO2 indicators read
    `learner_err=0.0 persistence_err=0.0 -> LOSES`, because beats_persistence
    needs a strict `<`. Both predicted exactly — and the brain was then told a
    LOSES indicator is "where a new feature, a new source, or a different model is
    worth proposing", i.e. handed a work order to improve three perfect series."""
    out = wf.learner_briefing({"A::co2_ppm_current": _row(0.0, 0.0)})
    assert "TIED (both exact)" in out
    assert "-> LOSES" not in out
    assert "loses on 0" in out and "ties on 1" in out


def test_a_real_loss_is_still_called_a_loss():
    """NEGATIVE CONTROL: the fix must not turn every failure into a tie."""
    out = wf.learner_briefing({"A::x": _row(0.40, 0.25)})
    assert "-> LOSES" in out
    assert "loses on 1" in out
    assert "ties on" not in out, "nothing tied here, so no tie count should appear"


def test_a_tie_above_zero_is_a_tie_but_not_called_exact():
    """Equal errors that are not zero: still not a loss, but 'both exact' would be
    a lie — there IS error, the two predictors merely share it."""
    out = wf.learner_briefing({"A::x": _row(0.30, 0.30)})
    assert "-> TIED" in out and "both exact" not in out


def test_a_win_is_untouched():
    out = wf.learner_briefing({"A::x": _row(0.21, 0.30, wins=1, beats=True)})
    assert "-> BEATS" in out and "beats persistence on 1" in out


def test_the_tie_note_only_appears_when_something_tied():
    """The explanation is guidance, and guidance with no case to explain is noise."""
    assert "TIED indicator is not one of those" not in wf.learner_briefing({"A::x": _row(0.4, 0.25)})
    assert "TIED indicator is not one of those" in wf.learner_briefing({"A::x": _row(0.0, 0.0)})


def test_unscored_stays_unscored():
    out = wf.learner_briefing({"A::x": _row(None, None, compared=0)})
    assert "-> unscored" in out and "not yet scored" in out
