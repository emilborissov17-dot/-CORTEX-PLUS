#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_cycle_profile.py — THE HOUR DECIDES WHAT THE CYCLE MAY SPEND.

Most of this file is boundaries, because a wrapping window is the one place this
logic can be wrong in a way that looks right: 22:00-06:00 is not a range, it is
the complement of one, and getting it backwards silently gives every hour the
day profile — including 03:00, the only cycle that runs unattended.

Also held:
  * work is DEFERRED, never dropped. A night that quietly does less each time is
    the failure that shows up months later as "why does it not notice things".
  * the backlog is drained ONCE, so two cycles racing cannot both run it.
  * the priority filter is a no-op today, and the module SAYS so. A filter that
    excludes nothing reads in a log exactly like a filter that is working.

    venv\\Scripts\\python.exe -m pytest test/test_cycle_profile.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import cycle_profile as cp  # noqa: E402


def at(hour, minute=0):
    return datetime(2026, 8, 22, hour, minute, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hour,expected", [
    (0, cp.NIGHT), (1, cp.NIGHT), (3, cp.NIGHT), (5, cp.NIGHT),
    (6, cp.DAY), (7, cp.DAY), (12, cp.DAY), (21, cp.DAY),
    (22, cp.NIGHT), (23, cp.NIGHT),
])
def test_every_hour_lands_in_the_right_profile(hour, expected):
    assert cp.profile_name_for(at(hour)) == expected


def test_the_boundaries_are_half_open():
    assert cp.profile_name_for(at(6, 0)) == cp.DAY, "06:00 is day"
    assert cp.profile_name_for(at(5, 59)) == cp.NIGHT
    assert cp.profile_name_for(at(22, 0)) == cp.NIGHT, "22:00 is night"
    assert cp.profile_name_for(at(21, 59)) == cp.DAY


def test_the_nightly_cycle_hour_is_night():
    """03:00 is when the unattended cycle runs. If this ever reads DAY, the
    whole night policy is inert on the only run it exists for."""
    assert cp.profile_name_for(at(3)) == cp.NIGHT


def test_in_window_handles_a_wrapping_range():
    assert cp.in_window(23, 22, 6) is True
    assert cp.in_window(2, 22, 6) is True
    assert cp.in_window(12, 22, 6) is False


def test_in_window_handles_an_ordinary_range():
    assert cp.in_window(12, 6, 22) is True
    assert cp.in_window(3, 6, 22) is False


def test_a_window_whose_ends_meet_is_the_whole_day():
    assert all(cp.in_window(h, 0, 0) for h in range(24))


def test_every_hour_of_the_day_resolves_to_exactly_one_profile():
    for h in range(24):
        assert cp.profile_name_for(at(h)) in (cp.DAY, cp.NIGHT)


# ---------------------------------------------------------------------------
# What each profile allows
# ---------------------------------------------------------------------------

def test_the_big_model_is_allowed_by_day_and_forbidden_by_night():
    assert cp.resolve(at(12)).big_model_allowed is True
    assert cp.resolve(at(3)).big_model_allowed is False


def test_a_missing_config_falls_back_to_the_cautious_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "CONFIG", tmp_path / "nope.json")
    p = cp.resolve(at(12))
    assert p.big_model_allowed is False, (
        "an unreadable config allowed the expensive model on an unattended run; "
        "the cautious answer costs capability, the other costs a reload storm")
    assert p.name == cp.NIGHT


def test_disabling_profiles_restricts_nothing(monkeypatch, tmp_path):
    cfg = json.loads((REPO / "config" / "cycle_profiles.json").read_text(encoding="utf-8"))
    cfg["enabled"] = False
    assert cp.resolve(at(3), config=cfg).big_model_allowed is True


# ---------------------------------------------------------------------------
# The priority filter is a no-op today, and says so
# ---------------------------------------------------------------------------

def test_the_priority_filter_currently_excludes_nothing():
    p = cp.resolve(at(3))
    assert p.skip == [], (
        "if this ever starts skipping steps, the night profile changed shape and "
        "the config README needs updating with it")
    assert p.run


def test_the_module_says_out_loud_that_the_filter_is_a_no_op():
    p = cp.resolve(at(3))
    assert any("excludes none" in n for n in p.notes), (
        "a filter that excludes nothing reads in a log exactly like a filter that "
        "is working; it has to announce itself")


def test_a_narrower_allow_list_would_actually_cut_steps():
    """Proves the machinery is real and merely unused, not decorative."""
    cfg = json.loads((REPO / "config" / "cycle_profiles.json").read_text(encoding="utf-8"))
    cfg["profiles"]["night"]["allowed_priorities"] = ["CRITICAL"]
    p = cp.resolve(at(3), config=cfg)
    assert p.skip, "restricting to CRITICAL cut nothing — the filter is decoration"
    assert len(p.run) == 16, len(p.run)


def test_the_priority_table_is_read_through_survival_mode():
    """config/step_priority.json is {"CRITICAL": [...]}, not a flat map. A second
    reader here returned 0 entries where survival_mode returned 16."""
    from core.survival_mode import load_priorities as theirs
    assert cp.load_priorities() == theirs()
    assert len(cp.load_priorities()) == 16


def test_an_unlisted_step_is_treated_as_normal():
    p = cp.resolve(at(3), steps=["not_in_any_table"], priorities={})
    assert p.run == ["not_in_any_table"]


# ---------------------------------------------------------------------------
# Deferral
# ---------------------------------------------------------------------------

@pytest.fixture
def dp(tmp_path):
    return tmp_path / "deferred_batch.json"


def test_a_deferred_task_is_kept(dp):
    cp.defer({"key": "summarise", "axis": "ENERGY_REVIEW"}, path=dp)
    tasks = cp.deferred(path=dp)
    assert len(tasks) == 1 and tasks[0]["axis"] == "ENERGY_REVIEW"
    assert tasks[0]["deferred_at"]


def test_the_same_task_deferred_nightly_is_one_entry_with_a_count(dp):
    """Seven nights must not produce seven entries — the day cycle would wake to
    a backlog that grows with the number of nights, not the amount of work."""
    for _ in range(7):
        cp.defer({"key": "summarise", "axis": "ENERGY_REVIEW"}, path=dp)
    tasks = cp.deferred(path=dp)
    assert len(tasks) == 1
    assert tasks[0]["deferred_count"] == 7


def test_tasks_without_a_key_are_not_merged(dp):
    cp.defer({"note": "one"}, path=dp)
    cp.defer({"note": "two"}, path=dp)
    assert len(cp.deferred(path=dp)) == 2


def test_draining_returns_the_tasks_and_empties_the_file(dp):
    cp.defer({"key": "a"}, path=dp)
    cp.defer({"key": "b"}, path=dp)
    got = cp.take_deferred(path=dp)
    assert len(got) == 2
    assert cp.deferred(path=dp) == [], "the backlog survived being drained"


def test_a_second_drain_finds_nothing(dp):
    cp.defer({"key": "a"}, path=dp)
    cp.take_deferred(path=dp)
    assert cp.take_deferred(path=dp) == [], (
        "two day cycles racing would both run the same deferred work")


def test_a_corrupt_backlog_file_does_not_lose_new_deferrals(dp):
    dp.write_text("{ this is not json", encoding="utf-8")
    cp.defer({"key": "a"}, path=dp)
    assert len(cp.deferred(path=dp)) == 1


def test_deferring_is_not_dropping():
    """The module must never have a path that discards a task."""
    src = (REPO / "core" / "cycle_profile.py").read_text(encoding="utf-8")
    assert "def defer(" in src and "def take_deferred(" in src
    assert src.count("tasks\"] = []") <= 1, (
        "more than one place empties the backlog; only the drain may")


# ---------------------------------------------------------------------------
# The interaction with the model window
# ---------------------------------------------------------------------------

def test_the_night_profile_would_forbid_the_configured_8b_window():
    """Not a bug — a consequence, and one that belongs in front of a human.

    config/model_window.json opens the 8b window at brain_reconsider. The nightly
    cycle runs at 03:00, which this module calls NIGHT with big_model_allowed
    False. Wired as written, 8b would run only in manual day cycles.
    """
    from core import model_window as mw
    assert mw.config()["enabled"] is True
    assert cp.resolve(at(3)).big_model_allowed is False
    src = (REPO / "core" / "cycle_profile.py").read_text(encoding="utf-8")
    assert "THE INTERACTION THIS MODULE CANNOT RESOLVE BY ITSELF" in src, (
        "the conflict is no longer documented where the next reader will find it")


def test_the_selftest_says_NOT_WIRED(capsys):
    cp._selftest()
    out = capsys.readouterr().out
    assert "NOT WIRED" in out
    assert "THE INTERACTION TO DECIDE BEFORE WIRING" in out
