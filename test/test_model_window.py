#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_model_window.py — THE 8b WINDOW IS ONE WINDOW, NOT A HABIT.

What this holds, and why each one was worth a test:

  * a want_big caller OUTSIDE the window is served the small model, and the
    downgrade is RECORDED. An unrecorded downgrade is the same defect as a
    silent DEGRADED: the record says the big model answered when it did not.
  * the window opens ONCE across a full walk of the real 55-step cycle. The
    first version of this module opened it three times, because `body_scan`
    appears at index 1 AND index 35 and names.index() always returned 1 — so
    the window shut mid-tail and reopened one step later, paying exactly the
    8b reload the module exists to remove. That regression is pinned below.
  * a missing config CLOSES the window rather than opening it. The fail-safe
    direction costs capability, never the cycle.

Every test here runs with touch_ollama=False: this is about the DECISION, and a
test that needs a GPU to say whether a decision is right is not a test of the
decision. The residency calls themselves are exercised by --selftest against the
live daemon.

    venv\\Scripts\\python.exe -m pytest test/test_model_window.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import model_window as mw  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_module_state(tmp_path, monkeypatch):
    """Each test starts with a closed window, an unwalked cursor, and a STATE path
    inside tmp_path.

    The redirect is not tidiness. _persist() writes on every downgrade, and
    test/conftest.py fails any test that touches live state — on 16 Aug 2026 that
    class of leak sent the human a fabricated alarm. The module's real record file
    is memory/model_window.json and a test has no business writing it.
    """
    monkeypatch.setattr(mw, "STATE", tmp_path / "model_window.json")
    mw._open = False
    mw._open_reason = ""
    mw._downgrades.clear()
    mw._transitions.clear()
    mw.reset_cursor()
    yield
    mw._open = False
    mw.reset_cursor()


def _step_names():
    from core.cycle_map import STEPS
    return [s[0] for s in STEPS]


# ---------------------------------------------------------------------------
# The downgrade is served AND recorded
# ---------------------------------------------------------------------------

def test_outside_the_window_a_big_request_is_served_the_small_model():
    assert not mw.is_open()
    got = mw.local_model(want_big=True, purpose="unit")
    assert got == mw.small_model(), (
        f"outside the window a want_big caller got {got!r}; the whole point is "
        f"that it gets {mw.small_model()!r} instead")


def test_the_downgrade_is_recorded_with_the_purpose_that_asked():
    mw.local_model(want_big=True, purpose="unit:internet_intelligence")
    recorded = [d for d in mw.downgrades() if d["purpose"] == "unit:internet_intelligence"]
    assert recorded, (
        "the downgrade left no record — a caller that silently gets a weaker "
        "model is indistinguishable from one that got what it asked for")
    assert recorded[0]["asked"] == mw.big_model()
    assert recorded[0]["served"] == mw.small_model()


def test_inside_the_window_the_big_model_is_served_and_nothing_is_recorded():
    mw.open_window("unit", touch_ollama=False)
    got = mw.local_model(want_big=True, purpose="unit")
    assert got == mw.big_model()
    assert not mw.downgrades(), "serving what was asked for is not a downgrade"


def test_a_caller_that_does_not_ask_for_big_never_gets_big():
    mw.open_window("unit", touch_ollama=False)
    assert mw.local_model(want_big=False, purpose="unit") == mw.small_model(), (
        "an open window is permission for callers that want 8b, not a promotion "
        "for callers that never asked")


# ---------------------------------------------------------------------------
# ONE window per cycle — the body_scan regression
# ---------------------------------------------------------------------------

def test_a_full_walk_of_the_real_cycle_opens_the_window_exactly_once():
    names = _step_names()
    changes = []
    for step in names:
        res = mw.on_step(step, touch_ollama=False)
        if res.get("changed"):
            changes.append((step, res.get("open")))
    opens = [c for c in changes if c[1] is True]
    assert len(opens) == 1, (
        f"the window changed state {len(changes)} times over {len(names)} steps "
        f"({changes}); it is supposed to open once. More than one open means the "
        f"cycle pays more than one 8b load.")


def test_body_scan_appearing_twice_does_not_reopen_the_window():
    """The exact regression: body_scan at index 1 and index 35.

    Walking with a monotonic cursor, the SECOND body_scan must resolve to 35 —
    inside the window — and therefore not close it.
    """
    names = _step_names()
    assert names.count("body_scan") == 2, (
        "this test pins a duplicate that no longer exists; if body_scan was "
        "de-duplicated in cycle_map, delete the test rather than weakening it")
    second = len(names) - 1 - names[::-1].index("body_scan")
    assert mw.step_is_in_window("body_scan", index=second), (
        "the second body_scan is inside the window by position")
    assert not mw.step_is_in_window("body_scan", index=names.index("body_scan")), (
        "the first body_scan is outside it")

    for step in names[:second + 1]:
        mw.on_step(step, touch_ollama=False)
    assert mw.is_open(), (
        "the window closed on the second body_scan — names.index() resolved it "
        "to the first occurrence again")


def test_the_cursor_never_walks_backwards():
    mw.on_step("cycle_report", touch_ollama=False)
    before = mw._cursor
    mw.on_step("boot", touch_ollama=False)
    assert mw._cursor >= before, (
        "a step name that appears only earlier must not rewind the cursor; the "
        "cycle does not run backwards")


# ---------------------------------------------------------------------------
# Runner labels, not step names
# ---------------------------------------------------------------------------

def test_a_runner_label_resolves_to_its_step_name():
    from core.cycle_map import ALIASES
    if not ALIASES:
        pytest.skip("no aliases declared")
    label, name = next(iter(ALIASES.items()))
    assert mw.resolve_step(label) == name, (
        f"_run() calls this module with labels like {label!r}; unresolved, the "
        f"window would never match one and would stay shut all night")


def test_an_unknown_step_is_outside_the_window():
    assert not mw.step_is_in_window("no_such_step_exists")


# ---------------------------------------------------------------------------
# Fail-safe direction
# ---------------------------------------------------------------------------

def test_a_missing_config_closes_the_window_rather_than_opening_it(monkeypatch):
    monkeypatch.setattr(mw, "CONFIG", REPO / "config" / "does_not_exist.json")
    assert mw.window_bounds() is None
    for step in _step_names():
        assert not mw.step_is_in_window(step), (
            "with no config every step read as inside the window — the fail-safe "
            "direction is closed, because that costs capability, not the cycle")


def test_disabled_means_no_step_gets_the_big_model(tmp_path, monkeypatch):
    cfg = tmp_path / "model_window.json"
    cfg.write_text(json.dumps({"enabled": False,
                               "window_opens_at_step": "brain_reconsider"}),
                   encoding="utf-8")
    monkeypatch.setattr(mw, "CONFIG", cfg)
    assert mw.window_bounds() is None
    assert not mw.step_is_in_window("brain_reconsider")


# ---------------------------------------------------------------------------
# keep_alive
# ---------------------------------------------------------------------------

def test_the_small_model_is_pinned_forever_outside_the_window():
    assert mw.keep_alive_for(mw.small_model()) == mw.FOREVER, (
        "3b outside the window must never expire — an expiring model is a model "
        "that reloads, and the reload is the cost being removed")


def test_the_small_model_is_not_pinned_forever_inside_the_window():
    mw.open_window("unit", touch_ollama=False)
    assert mw.keep_alive_for(mw.small_model()) != mw.FOREVER, (
        "inside the window 8b needs the VRAM; pinning 3b there would deny it")


# ---------------------------------------------------------------------------
# Idempotence
# ---------------------------------------------------------------------------

def test_opening_an_open_window_changes_nothing():
    first = mw.open_window("unit", touch_ollama=False)
    second = mw.open_window("unit again", touch_ollama=False)
    assert first["changed"] is True
    assert second["changed"] is False
    assert mw.is_open()


def test_closing_a_closed_window_changes_nothing():
    assert mw.close_window(touch_ollama=False)["changed"] is False
