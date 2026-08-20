#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_axis_feed.py — PROSE DOES NOT CROSS THE DMZ.

WHY THE TYPE IS THE CONTRACT
-----------------------------
docs/OPENCLAW_INTEGRATION_DESIGN.md: "Неизвестното = изисква одобрение." What
leaves CORTEX is constrained by type, not by intention.

The failure this prevents is already in production elsewhere in this repo: 0 of
173 weight is backed by measurement, while every axis reports a confident level
word. A sentence and a number look the same in JSON once a model has written
both. So an axis feed carries a NUMBER bound to (axis, key), and anything else
is rejected by name.

THE NEGATIVE CONTROL
---------------------
test_a_text_value_is_rejected feeds "HIGH" — the exact shape of a level word a
model would produce — and demands RejectedFeed. Remove the isinstance check in
check_number and it passes silently, which is the whole defect.

    venv\\Scripts\\python.exe -m pytest test/test_axis_feed.py -v
"""
from __future__ import annotations

import json
import math
import pathlib

import pytest

from agents.axis.axis_feed import (ABSENT, PRESENT, RejectedFeed, axes_from_config,
                                   axis_agent, check_number, collect, make_absent,
                                   make_feed, write)

REPO = pathlib.Path(__file__).resolve().parents[1]

GOAL_SCORE_FIXTURE = {
    "metric_details": {
        "co2_ppm_mauna_loa": {
            "axis": "CLIMATE_GLOBAL_RISK_REVIEW", "current": 427.59,
            "target": 350.0, "unit": "ppm", "direction": "lower_better",
            "score": 0.8185, "measured": True, "weight": 10.0,
        },
        "renewable_energy_pct": {
            "axis": "ENERGY_REVIEW", "current": 27.8357, "target": 80.0,
            "unit": "percent", "direction": "higher_better",
            "score": 0.3479, "measured": True, "weight": 8.0,
        },
        "empty_one": {
            "axis": "COSMIC_RESOURCES_REVIEW", "current": None,
            "measured": False, "weight": 3.0,
        },
    }
}


# ---------------------------------------------------------------------------
# (a) THE NEGATIVE CONTROL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["HIGH", "LOW", "427.59 ppm", "n/a",
                                  "CO2 е над прага", ""])
def test_a_text_value_is_rejected(text):
    """A level word is the shape a model emits when asked for a measurement."""
    with pytest.raises(RejectedFeed) as caught:
        check_number("CLIMATE_GLOBAL_RISK_REVIEW", "co2_ppm_mauna_loa", text)

    message = str(caught.value)
    assert "CLIMATE_GLOBAL_RISK_REVIEW" in message, "the rejection does not name the axis"
    assert "co2_ppm_mauna_loa" in message, "the rejection does not name the key"


def test_make_feed_refuses_to_build_a_row_from_text():
    """The rejection must happen at construction, not at read time — otherwise a
    text row exists on disk and something downstream will eventually trust it."""
    with pytest.raises(RejectedFeed):
        make_feed("CLIMATE_GLOBAL_RISK_REVIEW", "co2_ppm_mauna_loa", "HIGH")


@pytest.mark.parametrize("bad", [None, [1], {"v": 1}, (1,), object()])
def test_non_numeric_types_are_rejected(bad):
    with pytest.raises(RejectedFeed):
        check_number("AX", "k", bad)


def test_a_bool_is_not_a_measurement():
    """bool is a subclass of int in Python. True would pass a naive isinstance
    check and become the number 1.0 — a measurement nobody took."""
    with pytest.raises(RejectedFeed):
        check_number("AX", "k", True)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(bad):
    with pytest.raises(RejectedFeed):
        check_number("AX", "k", bad)


@pytest.mark.parametrize("good", [0, 1, -3, 427.59, 0.8185, 1e-9])
def test_real_numbers_are_accepted(good):
    """POSITIVE CONTROL — a gate that rejects everything is not a gate."""
    assert check_number("AX", "k", good) == float(good)


# ---------------------------------------------------------------------------
# (b) ABSENT is a row, not a gap
# ---------------------------------------------------------------------------

def test_an_axis_with_no_number_emits_an_absent_row():
    """A missing axis and an axis nobody looked at must not look alike."""
    spec = {"primary_metric": None, "weight": 3.0}
    row = axis_agent("COSMIC_RESOURCES_REVIEW", spec, {})

    assert row["status"] == ABSENT
    assert row["value"] is None
    assert row["weight"] == 3.0
    assert "no metric_details row" in row["why"]


def test_a_metric_present_but_valueless_is_absent_with_its_own_reason():
    details = {"COSMIC_RESOURCES_REVIEW": {
        "axis": "COSMIC_RESOURCES_REVIEW", "current": None, "key": "empty_one"}}
    row = axis_agent("COSMIC_RESOURCES_REVIEW", {"weight": 3.0}, details)

    assert row["status"] == ABSENT
    assert "carries no current value" in row["why"], (
        "the two ways of being absent must be distinguishable — one means the "
        "axis is unwired, the other means the fetch came back empty"
    )


def test_every_axis_in_the_config_produces_exactly_one_row(tmp_path):
    """No axis silently disappears between config and queue."""
    goal = tmp_path / "goal.json"
    goal.write_text(json.dumps(GOAL_SCORE_FIXTURE), encoding="utf-8")

    batch = collect(goal_score_path=goal)
    axes = axes_from_config()

    assert len(batch["feeds"]) == len(axes) == batch["axes_in_config"]
    assert batch["present"] + batch["absent"] == len(axes)
    assert {f["axis"] for f in batch["feeds"]} == set(axes)


def test_a_present_row_carries_the_number_and_its_provenance(tmp_path):
    goal = tmp_path / "goal.json"
    goal.write_text(json.dumps(GOAL_SCORE_FIXTURE), encoding="utf-8")

    batch = collect(goal_score_path=goal)
    climate = next(f for f in batch["feeds"]
                   if f["axis"] == "CLIMATE_GLOBAL_RISK_REVIEW")

    assert climate["status"] == PRESENT
    assert climate["value"] == 427.59
    assert climate["key"] == "co2_ppm_mauna_loa"
    assert climate["unit"] == "ppm"
    assert climate["measured"] is True
    assert climate["source"] == "goal_score_latest.metric_details"
    assert isinstance(climate["value"], float), "the value must be a number, not a string"


# ---------------------------------------------------------------------------
# (c) Writing
# ---------------------------------------------------------------------------

def test_it_writes_both_the_log_and_the_latest(tmp_path):
    goal = tmp_path / "goal.json"
    goal.write_text(json.dumps(GOAL_SCORE_FIXTURE), encoding="utf-8")
    batch = collect(goal_score_path=goal)

    paths = write(batch, tmp_path / "openclaw_queue")
    log = pathlib.Path(paths["log"])
    latest = pathlib.Path(paths["latest"])

    assert log.name == "axis_feeds.jsonl"
    assert latest.name == "axis_feeds_latest.json"
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == len(batch["feeds"])
    assert json.loads(latest.read_text(encoding="utf-8"))["axes_in_config"] > 0


def test_the_log_appends_rather_than_replaces(tmp_path):
    goal = tmp_path / "goal.json"
    goal.write_text(json.dumps(GOAL_SCORE_FIXTURE), encoding="utf-8")
    batch = collect(goal_score_path=goal)
    q = tmp_path / "openclaw_queue"

    write(batch, q)
    first = len((q / "axis_feeds.jsonl").read_text(encoding="utf-8").splitlines())
    write(batch, q)
    second = len((q / "axis_feeds.jsonl").read_text(encoding="utf-8").splitlines())

    assert second == first * 2, "the queue is a ledger; it must not overwrite itself"


def test_no_row_ever_carries_a_non_numeric_value(tmp_path):
    """The invariant the whole file exists for, asserted over a real batch."""
    batch = collect()
    for row in batch["feeds"]:
        if row["status"] == PRESENT:
            assert isinstance(row["value"], (int, float)), row
            assert not isinstance(row["value"], bool), row
            assert math.isfinite(row["value"]), row
        else:
            assert row["value"] is None, row


# ---------------------------------------------------------------------------
# (d) Wiring
# ---------------------------------------------------------------------------

def test_the_runner_calls_it_as_step_12_68():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert '"axis_feed", "12.68"' in src, (
        "axis_feed is not wired into the cycle — a feed nobody produces is a "
        "contract nobody keeps"
    )
    assert "agents.axis.axis_feed" in src
