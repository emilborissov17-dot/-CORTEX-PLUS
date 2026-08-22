#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_flow_score.py — ONE SLOW STEP IS NOT A VERDICT ON THE NIGHT.

FS = (steps_FULL / steps_total) x (60 / median_step_time_sec)

The median is the whole measurement, and the live numbers say why: 26 steps with
a median of 18.4s and a mean of 156.0s, because daily_analysis took 764s. A mean
turns one slow LLM step into a judgement on the entire cycle — the same
confusion that had the watchdog killing nights for one step's unavailable model.

Also held:
  * UNKNOWN is NOT a failure. It means "no baseline yet", which is a fact about
    the history, not about this run. 15 of the 26 steps on record are UNKNOWN;
    counting them as failures would score every new step's first three nights as
    broken.
  * the survival hook needs THREE consecutive bad cycles, and is PURE — it
    cannot latch anything, because only supervisor.py may.

    venv\\Scripts\\python.exe -m pytest test/test_flow_score.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import flow_score as fsm  # noqa: E402


def S(step="s", seconds=60.0, verdict="OK", error=None, why=""):
    return {"step": step, "seconds": seconds, "verdict": verdict,
            "error": error, "why": why}


# ---------------------------------------------------------------------------
# The formula
# ---------------------------------------------------------------------------

def test_everything_full_at_a_minute_a_step_scores_one():
    fs = fsm.compute([S(seconds=60.0) for _ in range(10)])
    assert fs.flow_score == pytest.approx(1.0)
    assert fs.band == fsm.LABOURED


def test_twice_as_fast_scores_twice_as_high():
    fs = fsm.compute([S(seconds=30.0) for _ in range(10)])
    assert fs.flow_score == pytest.approx(2.0)


def test_half_the_steps_failing_halves_the_score():
    steps = [S(seconds=60.0) for _ in range(5)] + \
            [S(seconds=60.0, verdict="DEGRADED") for _ in range(5)]
    fs = fsm.compute(steps)
    assert fs.flow_score == pytest.approx(0.5)
    assert fs.steps_full == 5 and fs.steps_total == 10


def test_the_score_is_the_product_of_both_factors():
    steps = [S(seconds=15.0) for _ in range(8)] + \
            [S(seconds=15.0, verdict="RAISED") for _ in range(2)]
    fs = fsm.compute(steps)
    assert fs.flow_score == pytest.approx(0.8 * 4.0)


# ---------------------------------------------------------------------------
# Median, not mean — the point of the whole module
# ---------------------------------------------------------------------------

def test_one_enormous_step_does_not_sink_the_night():
    """The live shape: many quick steps and one 764s LLM step."""
    steps = [S(seconds=18.0) for _ in range(25)] + [S(seconds=764.0)]
    fs = fsm.compute(steps)
    assert fs.median_step_sec == pytest.approx(18.0)
    assert fs.flow_score > 3.0, (
        "a mean would have scored this night as grinding on the strength of one "
        "step — the exact confusion that had the watchdog killing cycles")


def test_the_median_ignores_an_outlier_in_both_directions():
    assert fsm.compute([S(seconds=10.0), S(seconds=10.0),
                        S(seconds=10_000.0)]).median_step_sec == 10.0
    assert fsm.compute([S(seconds=0.001), S(seconds=10.0),
                        S(seconds=10.0)]).median_step_sec == 10.0


def test_a_genuinely_slow_night_still_scores_low():
    """The median must not launder real slowness either."""
    fs = fsm.compute([S(seconds=600.0) for _ in range(20)])
    assert fs.flow_score < 1.0 and fs.band == fsm.GRINDING


# ---------------------------------------------------------------------------
# Which steps count as FULL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("verdict", ["DEGRADED", "NO_EFFECT", "RAISED", "SLOW", "MISSING"])
def test_a_step_that_did_not_deliver_is_not_full(verdict):
    assert fsm.is_full(S(verdict=verdict)) is False


def test_unknown_is_not_counted_as_a_failure():
    """UNKNOWN means 'no baseline yet' — a fact about the history, not this run.
    15 of the 26 steps on the live record are UNKNOWN."""
    assert fsm.is_full(S(verdict="UNKNOWN")) is True, (
        "warming-up steps counted as failures would score every new step's "
        "first three nights as broken")


def test_ok_is_full():
    assert fsm.is_full(S(verdict="OK")) is True


def test_a_timeout_in_the_error_text_is_not_full_whatever_the_verdict_says():
    assert fsm.is_full(S(verdict="OK", error="TimeoutError: timed out")) is False


def test_thrash_in_the_reason_is_not_full():
    assert fsm.is_full(S(verdict="OK", why="thrash detected, retried 40 times")) is False


def test_the_steps_that_were_not_full_are_named():
    steps = [S(step="good"), S(step="bad", verdict="DEGRADED")]
    fs = fsm.compute(steps)
    assert [n["step"] for n in fs.not_full] == ["bad"]
    assert fs.not_full[0]["verdict"] == "DEGRADED"


# ---------------------------------------------------------------------------
# Degenerate cycles
# ---------------------------------------------------------------------------

def test_a_cycle_with_no_steps_is_grinding_not_an_error():
    fs = fsm.compute([])
    assert fs.flow_score == 0.0 and fs.band == fsm.GRINDING
    assert fs.steps_total == 0


def test_a_zero_median_does_not_make_the_score_infinite():
    """Every step taking no time is not a fast night, it is a night that did not
    happen."""
    fs = fsm.compute([S(seconds=0.0) for _ in range(5)])
    assert fs.flow_score == 0.0


def test_steps_with_no_duration_do_not_break_the_median():
    fs = fsm.compute([S(seconds=None), S(seconds=30.0), S(seconds=30.0)])
    assert fs.median_step_sec == 30.0


def test_a_missing_contract_file_yields_a_grinding_score(tmp_path):
    fs = fsm.compute(contract=tmp_path / "nope.json")
    assert fs.steps_total == 0 and fs.band == fsm.GRINDING


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (10.0, fsm.FLOWING), (4.01, fsm.FLOWING), (4.0, fsm.WORKING),
    (2.0, fsm.WORKING), (1.99, fsm.LABOURED), (1.0, fsm.LABOURED),
    (0.99, fsm.GRINDING), (0.0, fsm.GRINDING),
])
def test_the_bands_are_where_the_command_put_them(score, expected):
    assert fsm.band(score) == expected


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def test_a_score_round_trips_through_the_log(tmp_path):
    log = tmp_path / "flow.jsonl"
    fsm.append(fsm.compute([S()], cycle_id="c1"), path=log)
    fsm.append(fsm.compute([S()], cycle_id="c2"), path=log)
    hist = fsm.history(log)
    assert [h["cycle_id"] for h in hist] == ["c1", "c2"]


def test_a_torn_line_does_not_lose_the_history(tmp_path):
    log = tmp_path / "flow.jsonl"
    fsm.append(fsm.compute([S()], cycle_id="c1"), path=log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"cycle_id": "torn"\n')
    assert len(fsm.history(log)) == 1


def test_a_missing_log_is_an_empty_history(tmp_path):
    assert fsm.history(tmp_path / "nope.jsonl") == []


# ---------------------------------------------------------------------------
# The survival hook — provided, not wired
# ---------------------------------------------------------------------------

def _hist(*scores):
    return [{"cycle_id": str(i), "flow_score": s} for i, s in enumerate(scores)]


def test_three_bad_cycles_in_a_row_ask_for_survival():
    latch, why = fsm.should_latch_survival(_hist(1.9, 1.2, 0.8))
    assert latch is True
    assert "3 consecutive" in why


def test_two_bad_cycles_are_not_enough():
    """One bad night is weather. Two is not a pattern either."""
    latch, _ = fsm.should_latch_survival(_hist(5.0, 1.2, 0.8))
    assert latch is False


def test_a_recovery_breaks_the_streak():
    latch, _ = fsm.should_latch_survival(_hist(0.5, 0.6, 3.0))
    assert latch is False, "the system recovered on the most recent cycle"


def test_exactly_at_the_threshold_is_not_below_it():
    latch, _ = fsm.should_latch_survival(_hist(2.0, 2.0, 2.0))
    assert latch is False


def test_too_short_a_history_never_latches():
    latch, why = fsm.should_latch_survival(_hist(0.1, 0.1))
    assert latch is False and "are needed" in why


def test_an_empty_history_never_latches():
    latch, _ = fsm.should_latch_survival([])
    assert latch is False


def test_only_the_most_recent_cycles_are_considered():
    latch, _ = fsm.should_latch_survival(_hist(0.1, 0.1, 0.1, 9.0, 9.0, 9.0))
    assert latch is False


def test_the_hook_is_pure_and_cannot_latch_anything():
    """The decision to act belongs to supervisor.py, which is not touched today."""
    src = (REPO / "core" / "flow_score.py").read_text(encoding="utf-8")
    assert "survival_mode" not in src, (
        "flow_score imports survival_mode; the hook is meant to be a fact this "
        "module reports, not an action it takes")
    assert "import supervisor" not in src


# ---------------------------------------------------------------------------
# Cycle attribution
# ---------------------------------------------------------------------------

def test_the_cycle_id_comes_from_the_log_name_not_its_mtime(tmp_path):
    """'newest by mtime is not mine' is already a scar in this repo (07266fd).
    A filename carries the cycle's own stamp; an mtime is whatever touched it."""
    (tmp_path / "cycle_2026-08-01_030000.log").write_text("x", encoding="utf-8")
    newer = tmp_path / "cycle_2026-08-20_030000.log"
    newer.write_text("x", encoding="utf-8")
    import os
    import time
    os.utime(tmp_path / "cycle_2026-08-01_030000.log", (time.time(), time.time()))
    assert fsm.cycle_id_from_logs(tmp_path) == "2026-08-20_030000"


def test_no_logs_yields_unknown_rather_than_a_guess(tmp_path):
    assert fsm.cycle_id_from_logs(tmp_path) == "unknown"


# ---------------------------------------------------------------------------
# Against the live record
# ---------------------------------------------------------------------------

def test_the_live_contract_produces_a_plausible_score():
    fs = fsm.compute()
    assert fs.steps_total > 0, "memory/step_contract_latest.json has no steps"
    assert 0.0 <= fs.flow_score < 100.0
    assert fs.band in (fsm.FLOWING, fsm.WORKING, fsm.LABOURED, fsm.GRINDING)


def test_the_live_record_really_is_median_skewed():
    """Pins the number quoted in the module docstring."""
    steps = json.loads((REPO / "memory" / "step_contract_latest.json")
                       .read_text(encoding="utf-8")).get("steps") or []
    vals = [float(s["seconds"]) for s in steps
            if isinstance(s.get("seconds"), (int, float))]
    if len(vals) < 5:
        pytest.skip("not enough recorded steps to show the skew")
    import statistics
    assert statistics.mean(vals) > 2 * statistics.median(vals), (
        "the live record is no longer mean-skewed; the median argument still "
        "holds but the docstring's numbers are stale")


def test_the_selftest_says_NOT_WIRED(capsys):
    fsm._selftest()
    assert "NOT WIRED" in capsys.readouterr().out
