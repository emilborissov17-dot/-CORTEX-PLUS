#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_step_contracts.py — B4 STEP 1: the contract harvested from a trace.

A contract says what a step consumes, what it produces and how long it takes. B4
will one day skip a step whose inputs have not changed, so every one of these
fields is load-bearing: a wrong contract becomes a step that is never run again.

THE FORBIDDEN OUTPUTS, named so they cannot be reached by accident:
  * a contract for a step that does nothing. Its hash would always match and the
    step would be skipped for ever. It gets no contract; it gets removed.
  * "dead" decided on a trace that was not recording reads. A self-check reads
    and prints — no writes, no network — and on such a trace it is
    indistinguishable from a step that does nothing at all. The answer there is
    UNKNOWN, not DEAD.
  * params invented. A date is passed in code, not opened as a file, so a trace
    cannot see it. It stays empty with the reason attached.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import step_contracts as sc        # noqa: E402


def _trace(tmp_path, rows, channels=("pulse", "audit"), name="t.jsonl"):
    head = {"k": "head", "trace_id": "t", "cycle_id": "c1",
            "t0": "2026-09-13T00:00:00Z", "pid": 1, "py": "3.14",
            "channels": list(channels)}
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in [head] + rows) + "\n",
                 encoding="utf-8")
    return p


def _span(sp, name, ms, st="OK", index=None, source="beat"):
    return {"k": "span", "sp": sp, "pa": None, "name": name, "t": 0.0,
            "t_end": ms / 1000.0, "ms": ms, "st": st,
            "attr": {"step": name.split(":", 1)[1], "index": index,
                     "source": source}}


def _ev(sp, name, attr):
    return {"k": "ev", "sp": sp, "name": name, "t": 0.1, "attr": attr}


# ── what a contract contains ─────────────────────────────────────────────────

def test_a_step_gets_its_seconds_its_reads_its_network_and_its_writes(tmp_path):
    p = _trace(tmp_path, [
        _span("a", "stepb:global_indicators", 4200, index="2.5"),
        _ev("a", "read", {"path": "config/axis_source_map.json"}),
        _ev("a", "read", {"path": "config/providers.json"}),
        _ev("a", "connect", {"host": "api.worldbank.org", "port": 443}),
        _ev("a", "touch", {"ev": "open-w", "path": "memory/daily_tier.jsonl"}),
        _ev("a", "touch", {"ev": "open-r", "path": "ignored.json"}),
        _ev("a", "spawn", {"argv": ["nvidia-smi"]}),
    ], channels=("pulse", "audit", "read"))
    c = sc.harvest(p)["steps"]["global_indicators"]

    assert c["measured_seconds"] == 4.2
    assert c["index"] == "2.5"
    assert c["inputs"]["files"] == ["config/axis_source_map.json",
                                    "config/providers.json"]
    assert c["inputs"]["network"] == ["api.worldbank.org:443"]
    assert c["outputs"] == ["memory/daily_tier.jsonl"], (
        "a read-mode open is not an output")
    assert c["spawns"] == ["nvidia-smi"]
    assert c["dead"] is False


def test_params_are_empty_and_the_reason_travels_with_them(tmp_path):
    """A date is the input that makes yesterday's answer wrong, and it is the one
    input a trace cannot see. Empty with a reason beats a plausible guess."""
    p = _trace(tmp_path, [_span("a", "stepb:usgs_quakes", 1000),
                          _ev("a", "connect", {"host": "earthquake.usgs.gov",
                                               "port": 443})],
               channels=("pulse", "audit", "read"))
    c = sc.harvest(p)["steps"]["usgs_quakes"]
    assert c["inputs"]["params"] == []
    assert c["inputs"]["params_why"], "the gap is left without saying why"
    assert "code" in c["inputs"]["params_why"]


def test_the_run_span_wins_the_duration_over_the_beat_span_that_wraps_it(tmp_path):
    """beat() fires before _run(), so the beat span is longer by whatever ran in
    between. The step's own time is the inner one."""
    # IN THE ORDER A REAL TRACE WRITES THEM. A span row is emitted when the span
    # CLOSES, and the inner one closes first — so the wrapper is the last word in
    # the file, and "last one wins" would silently take the wrong number. The
    # first version of this test listed the wrapper first and passed against
    # exactly that mistake.
    p = _trace(tmp_path, [
        _span("inner", "step:daily_tier", 1780, source="_run"),
        _ev("inner", "touch", {"ev": "open-a", "path": "memory/daily_tier.jsonl"}),
        _span("outer", "stepb:daily_tier", 9000, index="2.52"),
    ], channels=("pulse", "audit", "read"))
    c = sc.harvest(p)["steps"]["daily_tier"]
    assert c["measured_seconds"] == 1.78, "the wrapper's seconds were taken"
    assert c["source"] == "both"


# ── the refusals ─────────────────────────────────────────────────────────────

def test_a_step_that_touches_nothing_gets_no_contract(tmp_path):
    p = _trace(tmp_path, [_span("a", "stepb:ghost", 30)],
               channels=("pulse", "audit", "read"))
    c = sc.harvest(p)["steps"]["ghost"]
    assert c["dead"] is True
    assert c["dead_why"]


def test_dead_is_not_decided_when_reads_were_not_being_recorded(tmp_path):
    """THE ONE THAT MATTERS. facade_self_check reads scorers and prints. With the
    read channel off it looks exactly like a step that does nothing, and calling
    it dead puts a live audit on a list headed 'to be removed'."""
    p = _trace(tmp_path, [_span("a", "stepb:facade_self_check", 900)],
               channels=("pulse", "audit"))
    c = sc.harvest(p)["steps"]["facade_self_check"]
    assert c["dead"] is None, "a working audit was declared dead"
    assert "read channel was off" in c["dead_why"]


def test_an_unjudged_step_never_reaches_the_dead_list(tmp_path, monkeypatch):
    p = _trace(tmp_path, [_span("a", "stepb:facade_self_check", 900)],
               channels=("pulse", "audit"))
    monkeypatch.setattr(sc, "MEASURED", tmp_path / "measured.json")
    monkeypatch.setattr(sc, "DEAD", tmp_path / "dead.json")
    assert sc.main(["--trace", str(p), "--write"]) == 0
    dead = json.loads((tmp_path / "dead.json").read_text(encoding="utf-8"))
    assert dead["steps"] == {}, f"an unjudged step was filed as dead: {dead['steps']}"


def test_a_dead_step_is_filed_for_removal_and_given_no_contract(tmp_path, monkeypatch):
    """The list is headed 'to be REMOVED, not skipped'. A contract for a step
    that does nothing is a hash that matches every night."""
    monkeypatch.setattr(sc, "MEASURED", tmp_path / "measured.json")
    monkeypatch.setattr(sc, "DEAD", tmp_path / "dead.json")
    p = _trace(tmp_path, [_span("a", "stepb:ghost", 30),
                          _span("b", "stepb:real", 40),
                          _ev("b", "touch", {"ev": "open-w", "path": "out/x"})],
               channels=("pulse", "audit", "read"))
    assert sc.main(["--trace", str(p), "--write"]) == 0
    measured = json.loads((tmp_path / "measured.json").read_text(encoding="utf-8"))
    dead = json.loads((tmp_path / "dead.json").read_text(encoding="utf-8"))
    assert "ghost" in dead["steps"], "a dead step was not filed"
    assert "ghost" not in measured["steps"], "a dead step was given a contract"
    assert "real" in measured["steps"]


def test_an_unjudged_step_gets_no_contract_either(tmp_path, monkeypatch):
    """Not known to be dead is not the same as known to be alive, and a contract
    with unknown inputs matches every night just the same."""
    monkeypatch.setattr(sc, "MEASURED", tmp_path / "measured.json")
    monkeypatch.setattr(sc, "DEAD", tmp_path / "dead.json")
    p = _trace(tmp_path, [_span("a", "stepb:facade_self_check", 900)],
               channels=("pulse", "audit"))
    assert sc.main(["--trace", str(p), "--write"]) == 0
    measured = json.loads((tmp_path / "measured.json").read_text(encoding="utf-8"))
    assert measured["steps"] == {}, (
        f"an unjudged step was contracted: {list(measured['steps'])}")


def test_nothing_is_written_without_write(tmp_path, monkeypatch, capsys):
    """House rule: a module that writes a journal dry-runs unless asked."""
    p = _trace(tmp_path, [_span("a", "stepb:x", 10),
                          _ev("a", "touch", {"ev": "open-w", "path": "out/x"})],
               channels=("pulse", "audit", "read"))
    monkeypatch.setattr(sc, "MEASURED", tmp_path / "measured.json")
    monkeypatch.setattr(sc, "DEAD", tmp_path / "dead.json")
    assert sc.main(["--trace", str(p)]) == 0
    assert not (tmp_path / "measured.json").exists()
    assert "DRY RUN" in capsys.readouterr().out


# ── persistence ──────────────────────────────────────────────────────────────

def test_write_produces_both_files_and_merges_with_what_was_there(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "MEASURED", tmp_path / "measured.json")
    monkeypatch.setattr(sc, "DEAD", tmp_path / "dead.json")
    (tmp_path / "measured.json").write_text(json.dumps(
        {"steps": {"yesterday_only": {"step": "yesterday_only"}}}), encoding="utf-8")

    p = _trace(tmp_path, [_span("a", "stepb:today", 500),
                          _ev("a", "connect", {"host": "h", "port": 1})],
               channels=("pulse", "audit", "read"))
    assert sc.main(["--trace", str(p), "--write"]) == 0
    blob = json.loads((tmp_path / "measured.json").read_text(encoding="utf-8"))
    assert "today" in blob["steps"]
    assert "yesterday_only" in blob["steps"], (
        "a step absent from tonight's trace lost its contract")


def test_the_rows_it_appends_do_not_break_cycle_integrity(tmp_path, monkeypatch):
    """--also-latest writes into a file four other modules read, and
    cycle_integrity.is_full() counts any verdict that is not OK as a failed step.
    A measurement must not be mistaken for a failure."""
    from core import cycle_integrity as ci

    monkeypatch.setattr(sc, "MEASURED", tmp_path / "measured.json")
    monkeypatch.setattr(sc, "DEAD", tmp_path / "dead.json")
    monkeypatch.setattr(sc, "LATEST", tmp_path / "latest.json")
    p = _trace(tmp_path, [_span("a", "stepb:trend_tracker", 800),
                          _ev("a", "touch", {"ev": "open-w",
                                             "path": "memory/trends.json"})],
               channels=("pulse", "audit", "read"))
    assert sc.main(["--trace", str(p), "--write", "--also-latest"]) == 0
    rows = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["steps"]
    assert rows and rows[0]["verdict"] == "OK"
    ok, why = ci.is_full(rows[0])
    assert ok, f"a harvested row reads as a failed step to cycle_integrity: {why}"


def test_it_reads_the_newest_trace_when_not_told_which(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "TRACE_DIR", tmp_path)
    old = _trace(tmp_path, [_span("a", "stepb:old", 10)], name="old.jsonl")
    new = _trace(tmp_path, [_span("b", "stepb:new", 10)], name="new.jsonl")
    import os
    os.utime(old, (1, 1))
    assert sc.newest_trace() == new
