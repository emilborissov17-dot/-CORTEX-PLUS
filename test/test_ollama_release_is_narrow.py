#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_ollama_release_is_narrow.py — a cure, not hygiene.

`keep_alive: 0` through ollama's own API is a request, not a kill: we asked it to
load the model. But the measurement that made this small is worth keeping in front
of whoever reads it next — on 13 Sep 2026 the resident model was 2208 MB of VRAM
and `psutil.virtual_memory()`, which the survival gate reads, cannot see VRAM at
all. What comes back is bounded by the 872 MB the ollama server held in its own
RSS, and in practice less.

So it is allowed in exactly one place and under exactly two conditions, and each
of the tests below fails if one of them is removed:

  * only from cure_refusal, i.e. only when the gate is ALREADY refusing;
  * only while core/model_window.is_open() is False, because that window was a
    measured decision and a cleanup must not quietly reverse it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import aggressive_cleanup as ac        # noqa: E402


def test_an_open_model_window_stops_it(monkeypatch):
    """core/model_window exists because unload/reload around every step was
    measured to be the wrong trade. fast_cycle_runner._free_ollama already
    respects this; so does this."""
    import core.model_window as mw
    monkeypatch.setattr(mw, "is_open", lambda: True)
    rec = ac.release_ollama(apply=True)
    assert rec["released"] == []
    assert "window is open" in rec["skipped"]


def test_an_unreadable_window_stops_it_too(monkeypatch):
    """Not knowing whether the window is open is not permission to act."""
    import core.model_window as mw
    def _boom():
        raise RuntimeError("no window")
    monkeypatch.setattr(mw, "is_open", _boom)
    rec = ac.release_ollama(apply=True)
    assert rec["released"] == []
    assert "not acting" in rec["skipped"]


def test_a_dry_run_releases_nothing(monkeypatch):
    import core.model_window as mw
    monkeypatch.setattr(mw, "is_open", lambda: False)
    rec = ac.release_ollama(apply=False)
    assert rec["applied"] is False
    assert rec["released"] == []


def test_a_gate_that_is_not_refusing_never_reaches_ollama(monkeypatch):
    """THE NARROWNESS. cure_refusal returns before any cleaning when the gate
    allows; if ollama were touched there it would be hygiene, not a cure."""
    called = []
    monkeypatch.setattr(ac, "release_ollama", lambda **k: called.append(k) or {})
    rec = ac.cure_refusal(check=lambda: {"allowed": True}, apply=True)
    assert called == [], "ollama was asked to unload while the gate was allowing"
    assert rec["cured"] is None
    assert "ollama" not in rec


def test_a_refusing_gate_does_reach_ollama_and_records_it(monkeypatch, tmp_path):
    """The other direction, so the guard cannot pass by never acting at all."""
    called = []
    monkeypatch.setattr(ac, "release_ollama",
                        lambda **k: called.append(k) or {"released": ["m"],
                                                         "ram_freed_mb": 12.5})
    monkeypatch.setattr(ac, "cleanup", lambda **k: {"applied": k.get("apply")})
    rec = ac.cure_refusal(check=lambda: {"allowed": False, "reasons": ["ram"]},
                          apply=True, log_path=tmp_path / "sweep.jsonl")
    assert called, "the gate was refusing and ollama was never asked"
    assert rec["ollama"]["released"] == ["m"]
    assert rec["ollama"]["ram_freed_mb"] == 12.5, (
        "the before/after number is not recorded; a cleanup nobody can check is "
        "one that survives long after it stopped working")


def test_the_record_carries_before_and_after(monkeypatch):
    import core.model_window as mw
    monkeypatch.setattr(mw, "is_open", lambda: False)
    rec = ac.release_ollama(apply=False)
    assert "ram_free_mb_before" in rec and "ram_free_mb_after" in rec
