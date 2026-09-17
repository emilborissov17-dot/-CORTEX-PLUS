# -*- coding: utf-8 -*-
"""test/test_self_read_probe.py — does the brain read, or know, its own wrapper (12 Sep 2026).

Pins: every expected answer comes from the blocks by code, never from a model; the same
question is asked open-book and closed-book; a trap has no answer in the blocks and only
UNCONFIDENT_TO_CHOOSE passes it; a fallback to another model is not an answer; and a run
during which the machine rewrote its own state blocks is marked INVALID.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import self_read_probe as SR  # noqa: E402

BLOCKS = {"body": "cpu_percent=1.8; ram_percent=69.6; disk_free_gb=601.8; "
                  "gpu={'available': True, 'name': 'NVIDIA GeForce GTX 1650', 'vram_total_mb': 4096}; "
                  "local models=qwen2.5:3b,qwen3:8b",
          "self_state": "FALSE_ALARMS: unknown\nOPEN_PROPOSALS: 25 (20 overdue), oldest 43.8 days\n"
                        "LAST_CYCLE: FINISHED\nFREE_MEMORY: RAM 251.3 MB (98.2% used)\nRESTARTS_TODAY: 0/2, 2 left",
          "spirit": "LAW:\n1. The brain is everywhere.\n4. The walls guard the ACTION, not the THOUGHT.",
          "memory": "(no memories of this kind)"}


def test_the_exam_is_built_from_the_blocks_not_invented():
    qs = {q["key"]: q for q in SR.exam(BLOCKS)}
    assert qs["ram_percent"]["expected"] == 69.6 and qs["open_proposals"]["expected"] == 25
    assert qs["last_cycle"]["expected"] == "FINISHED" and qs["vram_total_mb"]["expected"] == 4096
    assert qs["ram_percent"]["check"]("about 69.5 percent") and not qs["ram_percent"]["check"]("12")
    assert qs["last_cycle"]["check"]("it finished") and not qs["last_cycle"]["check"]("it was killed")


def test_a_block_without_a_value_yields_no_question():
    thin = dict(BLOCKS, body="(no body_scan)")
    keys = {q["key"] for q in SR.exam(thin)}
    assert "ram_percent" not in keys and "gpu_name" not in keys
    assert {"law_money", "trap_row"} <= keys          # the law and the traps do not need the body


def test_only_unconfident_passes_a_trap():
    traps = [q for q in SR.exam(BLOCKS) if q["kind"] == "trap"]
    assert len(traps) == 3
    for t in traps:
        assert t["check"](f"{SR.UNSURE} — the material does not say")
        assert not t["check"]("8 cores") and not t["check"]("article 7")


@pytest.fixture(autouse=True)
def _probe_writes_into_tmp(tmp_path, monkeypatch):
    """SR.run() persists its result, so every test here writes.

    Until 17 Sep 2026 these tests redirected the module's two paths to
    memory/_test_self_read_latest.json and memory/_test_self_read.jsonl and
    unlinked them afterwards. That is still LIVE STATE: the directory the cycle
    reads, written by a test, and cleaned up only if the test reaches its last
    line. conftest's _no_live_writes caught it and said what to do — "Fix the
    FIXTURE — redirect the path into tmp_path" — which is this.

    autouse, because the next test added to this file writes too, and a guard you
    have to remember to apply is one you will forget. monkeypatch, because it
    restores the real paths even when a test fails partway.
    """
    monkeypatch.setattr(SR, "LATEST", tmp_path / "self_read_probe_latest.json")
    monkeypatch.setattr(SR, "LOG", tmp_path / "self_read_probe.jsonl")


def test_each_question_is_asked_open_book_and_closed_book():
    seen = []

    def fake(model, question, lean):
        seen.append(lean)
        return f"{SR.UNSURE}", None

    qs = SR.exam(BLOCKS)
    out = SR.run(["m"], questions=qs, asker=fake)
    assert seen.count(False) == seen.count(True) == len(qs)
    per = out["by_model"]["m"]
    assert per["trap_open_invented"] == 0 and per["trap_closed_invented"] == 0
    assert per[SR.OPEN]["asked"] == len([q for q in qs if q["kind"] != "trap"])


def test_a_fallback_or_silence_is_not_scored_as_an_answer():
    qs = SR.exam(BLOCKS)[:2]
    out = SR.run(["m"], questions=qs, asker=lambda m, q, lean: (None, "fallback to qwen3:8b"))
    per = out["by_model"]["m"]
    assert per["fallback"] == 2 * len(qs) and per[SR.OPEN]["asked"] == 0 and per[SR.OPEN]["rate"] is None
