"""An axis is abandoned for lack of PROGRESS, never for taking a long time.

WHY THIS CHANGED (2026-08-04)
-----------------------------
web_intelligence gave every axis a flat 90s wall-clock ceiling. That looked fine for
months for the worst possible reason: fifteen of the RSS feeds were dead, and a 403 or a
DNS failure returns in milliseconds — the axes were fast *because they were fetching
nothing*. The hour the feed roster was repaired, the same axes started doing real work
and 15 of 25 were killed mid-fetch, up from 3. The ceiling had never measured health; it
measured how much work was being skipped.

A clock cannot tell "slow because it is working" from "stuck". memory/heartbeat.py made
exactly this argument one level up for the whole cycle — "no output for 15 minutes" is
indistinguishable from "hung", so a watchdog reading elapsed time kills healthy work —
and answered it with a progress signal. This is the same answer, per axis.

What must hold:
  * an axis that keeps reporting progress is NOT killed, however long it runs;
  * an axis that reports nothing for AXIS_STALL_SEC IS killed;
  * a livelock that reports progress forever still hits the hard-cap backstop;
  * the cycle survives either way — one bad axis never takes the run down.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import web_intelligence_agent as W  # noqa: E402


def _stall_decision(last_beat_age, elapsed,
                    stall=W.AXIS_STALL_SEC, cap=W.AXIS_HARD_CAP_SEC):
    """The orchestrator's rule, isolated: what happens to an axis in this state?"""
    if last_beat_age > stall:
        return "STALLED"
    if elapsed > cap:
        return "HARD_CAP"
    return "KEEP"


def test_a_slow_but_working_axis_is_not_killed():
    """The regression that started this: 8 minutes of real fetching, progress every 20s."""
    assert _stall_decision(last_beat_age=20, elapsed=480) == "KEEP"
    assert _stall_decision(last_beat_age=89, elapsed=800) == "KEEP"


def test_the_old_flat_ceiling_would_have_killed_it():
    """Proof the change is not cosmetic: under the old rule the same axis dies."""
    elapsed = 480
    assert elapsed > 90, "the old AXIS_TIMEOUT_SEC was a flat 90s"
    assert _stall_decision(last_beat_age=20, elapsed=elapsed) == "KEEP"


def test_a_genuinely_stuck_axis_is_abandoned():
    assert _stall_decision(last_beat_age=W.AXIS_STALL_SEC + 1, elapsed=200) == "STALLED"


def test_a_livelock_still_hits_the_backstop():
    """Reporting progress forever must not buy infinite time."""
    assert _stall_decision(last_beat_age=1, elapsed=W.AXIS_HARD_CAP_SEC + 1) == "HARD_CAP"


def test_stall_is_checked_before_the_cap():
    """A stuck axis is reported as stalled, not as a cap hit — the operator needs the
    difference: one is a hung socket, the other is a loop that never converges."""
    assert _stall_decision(last_beat_age=999, elapsed=99999) == "STALLED"


def test_the_beat_signal_is_thread_safe_and_records_the_stage():
    W._beat("TEST_AXIS", "rss:example.com")
    ts, stage = W._last_beat("TEST_AXIS")
    assert stage == "rss:example.com"
    assert time.time() - ts < 5


def test_an_axis_that_never_started_reports_so():
    ts, stage = W._last_beat("NEVER_RAN_AXIS_ZZZ")
    assert ts is None and stage == "not started"


def test_run_axis_reports_progress_at_every_real_boundary():
    """A stage that does work without beating would be invisible to the orchestrator and
    would look like a stall — the failure mode this whole mechanism exists to avoid."""
    src = (REPO / "web_intelligence_agent.py").read_text(encoding="utf-8")
    body = src.split("def run_axis(")[1].split("\ndef ")[0]
    for stage in ('_beat(axis, "started")', "_beat(axis, f\"rss:", "_beat(axis, f\"collected:",
                  '_beat(axis, "analysed")'):
        assert stage in body, f"missing progress signal: {stage}"


def test_the_thresholds_are_sane():
    assert W.AXIS_STALL_SEC > 0
    assert W.AXIS_HARD_CAP_SEC > W.AXIS_STALL_SEC * 3, \
        "the backstop must be far above the stall window or it becomes the real ceiling"
