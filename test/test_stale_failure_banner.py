#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_stale_failure_banner.py — A HUMAN MUST BE ABLE TO SEE THAT THE SYSTEM
IS CURRENTLY FINE.

state["failure"] was written once and never unwritten, and `--status` printed it
as a bare sentence: no cycle_id, no date, no age. A failure from a cycle that
died last Tuesday rendered identically to one from an hour ago. There was no way
to tell, from the one command a human runs, whether the thing was over.

That is not cosmetic. core/survival_mode.derived_from_disk treats a failure block
dated today as grounds for the reduced profile, so a stale block does not merely
mislead a reader — it quietly starves a healthy system of its own steps.

STALE HAS ONE DEFINITION HERE: a cycle FINISHED after the failure was recorded.
Not "a cycle started", not "a day has passed". Finishing is the only evidence
that the thing the failure describes is over.

    venv\\Scripts\\python.exe -m pytest test/test_stale_failure_banner.py -v
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import supervisor  # noqa: E402


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _state(at_hours_ago=5.0, **kw):
    f = {"date": "2026-08-22", "cycle_id": "cyc-dead",
         "at_utc": _iso(at_hours_ago), "reason": "wedged on internet_intelligence",
         "wedged_step": "internet_intelligence", "restarts_used": 2}
    f.update(kw)
    return {"failure": f}


@pytest.fixture
def no_finished(monkeypatch):
    monkeypatch.setattr(supervisor, "_last_finished_cycle", lambda: (None, None))


@pytest.fixture
def finished_after(monkeypatch):
    monkeypatch.setattr(supervisor, "_last_finished_cycle",
                        lambda: ("cyc-good", _iso(1.0)))


@pytest.fixture
def finished_before(monkeypatch):
    monkeypatch.setattr(supervisor, "_last_finished_cycle",
                        lambda: ("cyc-older", _iso(9.0)))


# ---------------------------------------------------------------------------
# What "stale" means
# ---------------------------------------------------------------------------

def test_no_failure_is_reported_as_absent():
    assert supervisor.failure_status({})["present"] is False


def test_a_failure_with_no_later_finished_cycle_is_current(no_finished):
    st = supervisor.failure_status(_state())
    assert st["present"] is True and st["stale"] is False


def test_a_failure_answered_by_a_later_finished_cycle_is_stale(finished_after):
    st = supervisor.failure_status(_state(at_hours_ago=5.0))
    assert st["stale"] is True
    assert st["superseded_by"] == "cyc-good"


def test_a_cycle_that_finished_BEFORE_the_failure_does_not_clear_it(finished_before):
    st = supervisor.failure_status(_state(at_hours_ago=5.0))
    assert st["stale"] is False, (
        "an older successful cycle was read as answering a newer failure; the "
        "order is the whole question")


def test_an_unparseable_timestamp_is_not_treated_as_stale(finished_after):
    st = supervisor.failure_status(_state(at_utc="not a date", date="not a date"))
    assert st["stale"] is False, (
        "clearing a failure on a guess is the more expensive mistake")


# ---------------------------------------------------------------------------
# The banner carries cycle_id and age
# ---------------------------------------------------------------------------

def test_the_status_banner_names_the_cycle_and_the_age(capsys, monkeypatch,
                                                       no_finished):
    monkeypatch.setattr(supervisor, "load_state", lambda: _state(at_hours_ago=6.0))
    monkeypatch.setattr(supervisor, "tick",
                        lambda **k: supervisor.Action(supervisor.NOTHING,
                                                      reason="unit"))
    supervisor.cmd_status()
    out = capsys.readouterr().out
    assert "cyc-dead" in out, "the banner does not say WHICH cycle failed"
    assert "6.0h old" in out, "the banner does not say HOW OLD the failure is"
    assert "FAILURE (current" in out


def test_the_status_banner_says_resolved_when_a_later_cycle_finished(
        capsys, monkeypatch, finished_after):
    monkeypatch.setattr(supervisor, "load_state", lambda: _state(at_hours_ago=6.0))
    monkeypatch.setattr(supervisor, "tick",
                        lambda **k: supervisor.Action(supervisor.NOTHING,
                                                      reason="unit"))
    supervisor.cmd_status()
    out = capsys.readouterr().out
    assert "RESOLVED" in out
    assert "cyc-good" in out
    assert "!!! FAILURE (current" not in out, (
        "a resolved failure still shouted as current; the point of this whole "
        "change is that a human can tell the system is fine")


def test_the_banner_reports_survival_mode(capsys, monkeypatch, no_finished):
    monkeypatch.setattr(supervisor, "load_state", lambda: {})
    monkeypatch.setattr(supervisor, "tick",
                        lambda **k: supervisor.Action(supervisor.NOTHING,
                                                      reason="unit"))
    supervisor.cmd_status()
    out = capsys.readouterr().out
    assert "survival mode" in out, (
        "survival mode changes which steps run tonight; a status that does not "
        "mention it cannot be used to understand the next cycle")


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------

def test_a_stale_block_is_cleared_and_kept_in_history(finished_after):
    state = _state(at_hours_ago=5.0)
    assert supervisor._clear_stale_failure(state) is True
    assert state["failure"] is None
    assert state["failure_history"], "the failure was erased instead of archived"
    assert state["failure_history"][-1]["superseded_by"] == "cyc-good"


def test_a_current_block_is_not_cleared(no_finished):
    state = _state()
    assert supervisor._clear_stale_failure(state) is False
    assert state["failure"] is not None


def test_clearing_matters_because_survival_reads_the_block():
    """Not a style point: survival_mode.derived_from_disk treats a failure block
    dated today as grounds for the reduced profile."""
    from core.survival_mode import derived_from_disk
    today = "2026-08-22"
    cfg = {"max_restarts_per_day": 2}
    with_block = {"restarts": {}, "failure": {"date": today, "wedged_step": "x"}}
    assert derived_from_disk(with_block, cfg, today)[0] is True
    assert derived_from_disk({"restarts": {}, "failure": None}, cfg, today)[0] is False


def test_a_dry_run_status_does_not_write_state(monkeypatch, finished_after):
    """--status must be readable without changing anything."""
    import inspect
    src = inspect.getsource(supervisor.tick)
    assert "if not dry_run and _clear_stale_failure(state)" in src, (
        "the stale-failure clear is not gated on dry_run; `--status` would "
        "mutate the state it is reporting on")
