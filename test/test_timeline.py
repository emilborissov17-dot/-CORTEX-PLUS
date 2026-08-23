#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_timeline.py — THE WINDOW RENDERS THE STREAMS; IT DOES NOT PRODUCE THEM.

Everything here runs against a tree built in tmp_path. cockpit/timeline.py has
default paths on purpose — it is a pure READER and the module-level test below
asserts that it opens nothing for writing — but a test that relied on those
defaults would be reading the operator's real desk, so every reader is called
with an explicit path.

    venv/Scripts/python.exe -m pytest test/test_timeline.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import timeline as tl   # noqa: E402


def _write(path: pathlib.Path, rows) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A cycle that ran from 10:00 to 11:00, with something in every stream."""
    ledger = _write(tmp_path / "existence_ledger.jsonl", [
        {"event": "CYCLE_STARTED", "cycle_id": "C1", "ts": "2026-08-23T10:00:00+00:00"},
        {"event": "CYCLE_FINISHED", "cycle_id": "C1", "ts": "2026-08-23T11:00:00+00:00"},
    ])
    stances = _write(tmp_path / "brain_step_log.jsonl", [
        {"ts": "2026-08-23T10:05:00+00:00", "step": "boot", "stance": "следи",
         "expect": "watch the anchor", "prev_step": "", "model": "local:qwen2.5:3b"},
        {"ts": "2026-08-23T09:00:00+00:00", "step": "before", "stance": "x",
         "expect": "yesterday"},          # OUTSIDE the window
    ])
    journal = _write(tmp_path / "brain_journal.jsonl", [
        {"ts": "2026-08-23T10:02:00+00:00", "kind": "cycle_plan",
         "summary": '{"focus": "the NOAA anchor"}'},
        {"ts": "2026-08-23T10:40:00+00:00", "kind": "autopsy",
         "summary": '{"cause": "RESTART_BUDGET_EXHAUSTED"}'},
        {"ts": "2026-08-23T10:41:00+00:00", "kind": "constancy",
         "summary": "not a timeline kind"},
    ])
    pulse = _write(tmp_path / "pulse_stream.jsonl", [
        {"ts": "2026-08-23T10:20:00+00:00",
         "body": {"ram_pct": 51.3, "disk_gb": 670.8, "ollama_alive": True},
         "spirit": {"composite": 0.57}, "necessity": {"score": 5}},
    ])
    debriefs = tmp_path / "phase_debriefs" / "C1"
    debriefs.mkdir(parents=True)
    (debriefs / "A_ORIENT.json").write_text(json.dumps({
        "ts": "2026-08-23T10:30:00+00:00", "phase": "A_ORIENT", "cycle_id": "C1",
        "accepted": True, "model": "qwen3:8b",
        "attempt_log": [{"said": {"what": "six artefacts", "verdict": "OK"}}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(tl, "LEDGER", ledger)
    monkeypatch.setattr(tl, "BRAIN_STEP_LOG", stances)
    monkeypatch.setattr(tl, "BRAIN_JOURNAL", journal)
    monkeypatch.setattr(tl, "AUTONOMIC_PULSE", pulse)
    monkeypatch.setattr(tl, "PHASE_DEBRIEFS", tmp_path / "phase_debriefs")
    monkeypatch.setattr(tl, "EXPRESSION_STREAM", tmp_path / "expression_stream.jsonl")
    monkeypatch.setattr(tl, "RECONSIDER_HISTORY", tmp_path / "reconsider_history.jsonl")
    monkeypatch.setattr(tl, "DREAMS", tmp_path / "dreams")
    monkeypatch.setattr(tl, "SOURCES", (
        ("pulse (autonomic)", pulse, tl.MEASUREMENT, ("pulse",)),
        ("brain_stance", stances, tl.INTERPRETATION, ("brain_stance",)),
        ("phase_debrief", tmp_path / "phase_debriefs", tl.SELF_JUDGEMENT,
         ("phase_debrief",)),
        ("dream", tmp_path / "dreams", tl.INTERPRETATION, ("dream",)),
    ))
    return tmp_path


def test_the_streams_arrive_in_the_order_they_happened(tree):
    blob = tl.collect("C1")
    assert [r["source"] for r in blob["rows"]] == [
        "rationale", "brain_stance", "pulse", "phase_debrief", "autopsy"]
    assert [r["ts"] for r in blob["rows"]] == sorted(
        r["ts"] for r in blob["rows"])


def test_rows_outside_the_cycle_window_are_not_on_its_timeline(tree):
    texts = " ".join(r["text"] for r in tl.collect("C1")["rows"])
    assert "yesterday" not in texts


def test_every_row_carries_its_real_source_and_its_reflexivity(tree):
    by = {r["source"]: r for r in tl.collect("C1")["rows"]}
    assert by["pulse"]["reflexivity"] == tl.MEASUREMENT
    assert by["brain_stance"]["reflexivity"] == tl.INTERPRETATION
    assert by["rationale"]["reflexivity"] == tl.INTERPRETATION
    assert by["phase_debrief"]["reflexivity"] == tl.SELF_JUDGEMENT
    assert by["autopsy"]["reflexivity"] == tl.SELF_JUDGEMENT
    for row in tl.collect("C1")["rows"]:
        assert row["where"], "a row that cannot name its file is a row nobody can check"


def test_a_journal_kind_that_is_not_a_timeline_kind_stays_out(tree):
    assert "not a timeline kind" not in " ".join(
        r["text"] for r in tl.collect("C1")["rows"])


def test_a_silent_source_is_named_rather_than_dropped(tree):
    states = {s["source"]: s for s in tl.collect("C1")["sources"]}
    assert states["dream"]["state"] == "missing"
    assert states["dream"]["why"]
    assert states["phase_debrief"]["state"] == "speaking"


def test_a_present_but_quiet_source_is_neither_missing_nor_speaking(tree, tmp_path):
    (tmp_path / "dreams").mkdir()          # the directory exists; no dream in it
    states = {s["source"]: s for s in tl.collect("C1")["sources"]}
    assert states["dream"]["state"] == "silent", (
        "'no dream last night' and 'the dream reader is broken' must not look "
        "the same")


def test_the_phase_debriefs_of_another_cycle_are_not_borrowed(tree, tmp_path):
    other = tmp_path / "phase_debriefs" / "C2"
    other.mkdir()
    (other / "B_SENSE.json").write_text(json.dumps({
        "ts": "2026-08-23T10:31:00+00:00", "phase": "B_SENSE", "cycle_id": "C2",
        "accepted": True}), encoding="utf-8")
    phases = [r for r in tl.collect("C1")["rows"] if r["source"] == "phase_debrief"]
    assert [p["phase"] for p in phases] == ["A_ORIENT"]


def test_a_truncated_json_summary_is_still_readable(tree):
    """core/brain.remember() stores summary[:600], so long verdicts never parse."""
    torn = '{"opening": "the anchor was reused", "verdict": "DEGRA'
    rendered = tl._text(torn)
    assert "opening: the anchor was reused" in rendered
    assert not rendered.startswith("{")


def test_the_window_still_shows_the_model_line_unchanged(tree, tmp_path):
    _write(tmp_path / "expression_stream.jsonl", [
        {"ts": "2026-08-23T10:45:00+00:00", "source": "model",
         "depth": "expression", "text": "QUERY sensor_id=gpu_temp_c"},
    ])
    rows = [r for r in tl.collect("C1")["rows"] if r["source"] == "expression"]
    assert len(rows) == 1
    assert rows[0]["text"] == "QUERY sensor_id=gpu_temp_c"
    assert rows[0]["reflexivity"] == tl.INTERPRETATION


def test_the_timeline_module_never_writes():
    """A renderer that writes is a producer wearing a renderer's name."""
    src = (REPO / "cockpit" / "timeline.py").read_text(encoding="utf-8")
    tree_ = ast.parse(src)
    banned = {"write_text", "write_bytes", "mkdir", "unlink", "touch",
              "append_line"}
    for node in ast.walk(tree_):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            raise AssertionError("cockpit/timeline.py calls .{}()".format(node.attr))
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id == "open":
                mode = [a for a in node.args[1:2]]
                assert mode and getattr(mode[0], "value", "r").startswith("r"), \
                    "cockpit/timeline.py opens a file for writing"


def test_the_page_renders_the_timeline_and_not_only_the_old_stream():
    page = (REPO / "cockpit" / "templates" / "cockpit.html").read_text(
        encoding="utf-8")
    assert "/api/timeline" in page, "the window is still its own thin channel"
    assert "tlcycle" in page, "no way to ask for another cycle"
    assert ".tl.r2" in page, "reflexivity is not visible on the page"


def test_the_endpoint_answers_for_the_live_repo():
    """Not a fixture: the real memory/, read-only, must not raise."""
    from cockpit import server as srv
    client = srv.app.test_client()
    blob = client.get("/api/timeline?limit=5").get_json()
    assert blob["row_count"] <= 5
    assert isinstance(blob["sources"], list) and blob["sources"]
    assert set(blob["reflexivity_meaning"]) == {0, 1, 2} or \
        set(blob["reflexivity_meaning"]) == {"0", "1", "2"}
