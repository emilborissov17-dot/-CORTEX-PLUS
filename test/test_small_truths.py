#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_small_truths.py — THE THREE SMALL ONES FROM COMMAND 23 ITEM 6.

  a  the pulse band ignored direction: wifi_signal_pct at 85% rendered
     "amber -> red" while the same line's own `band` field said "green".
  b  "N unread" was a label with no click handler, and /api/expression/seen —
     wired, tested, append-only — was never called by anything.
  c  the checklist computed a weaker `passed` state and the page rendered only
     done/current/todo, so the inference never reached the reader.

    venv/Scripts/python.exe -m pytest test/test_small_truths.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import pulse as pls        # noqa: E402
from cockpit import somatic as som      # noqa: E402

PAGE = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
    encoding="utf-8")


# ── (a) direction ───────────────────────────────────────────────────────────

def _row(key, value, unit="%", available=True):
    return {"key": key, "value": value, "unit": unit, "available": available,
            "disabled": False, "reason": ""}


def test_a_high_wifi_signal_is_not_red():
    assert pls.band_of(85.0, "%", "wifi_signal_pct") == "green"
    assert pls.band_of(20.0, "%", "wifi_signal_pct") == "red"


def test_a_high_cpu_percent_still_is():
    assert pls.band_of(90.0, "%", "cpu_percent") == "red"
    assert pls.band_of(10.0, "%", "cpu_percent") == "green"


def test_the_line_and_its_own_band_field_agree():
    """The bug in one assertion: the text said one thing, the field another."""
    p = pls.PulseProducer()
    p.emit({"groups": {"NETWORK": [_row("wifi_signal_pct", 40.0)]}}, now=0)
    lines = p.emit({"groups": {"NETWORK": [_row("wifi_signal_pct", 85.0)]}},
                   now=1)
    assert lines
    line = lines[0]
    field = som.band_for("wifi_signal_pct", 85.0)
    if "band " in line["text"]:
        assert "-> {}".format(field) in line["text"], (
            "the rendered band contradicts the structured band on the same line")


def test_pulse_and_the_panel_use_ONE_band_table():
    for key, value in (("wifi_signal_pct", 85.0), ("battery_percent", 97.0),
                       ("ram_percent", 84.4), ("gpu_temp_c", 90.0),
                       ("gateway_ping_ms", 600.0)):
        assert pls.band_of(value, "", key) == som.band_for(key, value)


def test_a_metric_nobody_has_judged_gets_no_band_rather_than_green():
    assert pls.band_of(4000.0, "MHz", "cpu_freq_mhz") is None
    assert pls.band_of(85.0, "%") is None, "a band guessed from the unit is the bug"


# ── (b) the unread pull ─────────────────────────────────────────────────────

def test_the_unread_count_is_a_control_with_a_handler():
    assert 'id="unread"' in PAGE
    assert "<button class=\"unread" in PAGE, "still a label nobody can click"
    assert "$('#unread').onclick = markSeen;" in PAGE
    assert "'/api/expression/seen'" in PAGE, (
        "the endpoint is still never called by the page")


def test_marking_seen_sends_only_the_lines_on_screen():
    """Never 'mark everything': that swallows lines written since the poll."""
    body = PAGE.split("async function markSeen(")[1].split("\n}")[0]
    assert "l.depth === 'expression'" in body
    assert "JSON.stringify({ts})" in body


def test_the_seen_endpoint_actually_moves_the_count(tmp_path, monkeypatch):
    from cockpit import expression as ex
    from cockpit import server as srv
    stream = tmp_path / "stream.jsonl"
    pending = tmp_path / "pending.json"
    for i in range(3):
        ex.append_line(ex.make_line(ex.MODEL, ex.EXPRESSION,
                                    "QUERY x{}".format(i),
                                    ts="2026-08-23T10:0{}:00+00:00".format(i)),
                       path=stream)
    monkeypatch.setattr(srv, "STREAM_PATH", stream)
    monkeypatch.setattr(srv, "PENDING_PATH", pending)
    client = srv.app.test_client()
    assert client.get("/api/expression").get_json()["unread"] == 3
    seen = client.post("/api/expression/seen",
                       json={"ts": ["2026-08-23T10:00:00+00:00",
                                    "2026-08-23T10:01:00+00:00"]}).get_json()
    assert seen["ok"] and seen["unread"] == 1
    assert client.get("/api/expression").get_json()["unread"] == 1


# ── (c) the weaker class reaches the page ───────────────────────────────────

def test_the_page_renders_the_passed_state():
    assert ".step.passed{" in PAGE, "passed is computed and still invisible"
    assert "passed (inferred)" in PAGE


def test_passed_does_not_look_like_done():
    passed = PAGE.split(".step.passed{")[1].split("}")[0]
    done = PAGE.split(".step.done{")[1].split("}")[0]
    assert passed != done
    assert "transparent" in passed, (
        "a square that means 'we assume so' must not be filled like one that "
        "means 'it is on record'")


def test_the_checklist_still_distinguishes_the_two():
    from cockpit import server as srv
    blob = srv.app.test_client().get("/api/cycles").get_json()
    states = {c["state"] for c in blob["checklist"]}
    assert states <= {"done", "passed", "current", "todo"}
    for c in blob["checklist"]:
        if c["state"] == "done":
            assert "checkpoint" in c["evidence"]
        if c["state"] == "passed":
            assert "inferred" in c["evidence"]


def test_a_step_that_runs_twice_lights_only_the_square_it_finished(monkeypatch):
    """body_scan is at index 0 and index 13; one checkpoint is not two."""
    from cockpit import server as srv
    blob = srv.app.test_client().get("/api/cycles").get_json()
    squares = [c for c in blob["checklist"] if c["step"] == "body_scan"]
    assert len(squares) == 2, "the map no longer runs body_scan twice"
    assert blob["counts"]["done"] == len(
        {(c["step"], c["index"]) for c in blob["checklist"]
         if c["state"] == "done"})


def test_a_substep_checkpoint_is_named_as_one_not_as_unmapped():
    from cockpit import server as srv
    blob = srv.app.test_client().get("/api/cycles").get_json()
    assert "substep_checkpoints" in blob
    assert not blob["unmapped_checkpoints"], (
        "unmapped should now mean genuinely unknown: {}".format(
            blob["unmapped_checkpoints"]))
