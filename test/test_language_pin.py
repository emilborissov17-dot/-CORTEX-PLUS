#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_language_pin.py — THE PIN REACHES THE PROMPT, NOT JUST THE SOURCE FILE.

A grep for LANGUAGE_PIN in core/brain.py is not a test. The constant can exist,
be beautifully worded, and never be concatenated into anything — that is exactly
the class of defect this repo keeps finding, and it is why this file captures
the ACTUAL string handed to the HTTP layer instead of reading the source.

NO MODEL IS CONTACTED. `requests` is replaced in sys.modules by a recorder whose
post() stores the request body and then raises, so think() falls through its own
retry loop and returns None. What it returns is not what is under test; what it
SENT is.

    venv/Scripts/python.exe -m pytest test/test_language_pin.py -v
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import brain  # noqa: E402

# CAPTURED AT IMPORT, BEFORE ANY FIXTURE RUNS. test/conftest.py neutralises
# core.brain.attend for the whole suite with an autouse fixture — rightly, since
# a heartbeat must not talk to a model in a test. But attend() is half of what
# this file exists to check, so the real function is held here and called
# directly, with its own disk write stubbed below.
_REAL_ATTEND = brain.attend


class _Recorder:
    """Stands in for `requests`. Records every prompt, contacts nothing."""

    def __init__(self):
        self.prompts = []

    def post(self, url, timeout=None, json=None):
        body = json or {}
        for msg in body.get("messages", []):
            self.prompts.append(msg.get("content", ""))
        raise RuntimeError("no model is contacted in this test")


@pytest.fixture
def captured(monkeypatch):
    rec = _Recorder()
    monkeypatch.setitem(sys.modules, "requests", rec)
    # _pick_model()/models() would reach the local Ollama over HTTP for its tag
    # list. Not a generation, but still a live dependency a test must not have.
    monkeypatch.setattr(brain, "models", lambda: ["qwen2.5:3b"])
    monkeypatch.setattr(brain, "_pick_model", lambda: ("qwen2.5:3b",
                                                       "http://127.0.0.1:11434"))
    monkeypatch.setattr(brain, "_fast_model", lambda: "qwen2.5:3b")
    monkeypatch.setattr(brain, "_smaller", lambda m: None)
    return rec


def _prompt_from(rec):
    assert rec.prompts, "think() never built a prompt"
    return rec.prompts[0]


def test_the_pin_is_in_the_prompt_think_actually_sends(captured):
    brain.think(role="tester", question="does the pin reach the wire?",
                remember_it=False)
    assert brain.LANGUAGE_PIN in _prompt_from(captured)


def test_the_pin_comes_after_the_memory_block(captured):
    """Whatever the exemplars just demonstrated, the pin is read after them."""
    brain.think(role="tester", question="ordering", remember_it=False)
    prompt = _prompt_from(captured)
    memory_at = prompt.index("ПАМЕТ")
    pin_at = prompt.index(brain.LANGUAGE_PIN)
    assert pin_at > memory_at, (
        "the pin is read BEFORE the exemplars that contradict it")


def test_the_pin_comes_immediately_before_the_question(captured):
    brain.think(role="tester", question="MARKER_QUESTION", remember_it=False)
    prompt = _prompt_from(captured)
    after_pin = prompt[prompt.index(brain.LANGUAGE_PIN)
                       + len(brain.LANGUAGE_PIN):]
    assert after_pin.lstrip().startswith("ВЪПРОС:"), (
        "something was inserted between the pin and the question: "
        + repr(after_pin[:80]))


def test_the_pin_is_there_with_evidence_and_a_schema_too(captured):
    """The schema path builds a different tail; the pin must survive it."""
    brain.think(role="tester", question="q", evidence="some material",
                schema={"verdict": "what you conclude"}, remember_it=False)
    assert brain.LANGUAGE_PIN in _prompt_from(captured)


def test_the_stance_prompt_is_pinned_too(captured, monkeypatch):
    """attend() is the second builder and the stream that drifted furthest."""
    monkeypatch.setattr(brain, "_AVAILABLE", True)
    monkeypatch.setattr(brain, "_prev_step_output", lambda: (None, None))
    monkeypatch.setattr(brain, "current_plan", lambda: {})
    # attend() records its own silence to memory/brain_step_log.jsonl when the
    # call fails, and the recorder above makes it fail on purpose.
    silences = []
    monkeypatch.setattr(brain, "_record_silence",
                        lambda *a, **k: silences.append(a))
    _REAL_ATTEND("scoring_engine")
    assert silences, "attend() did not reach its request at all"
    prompt = _prompt_from(captured)
    assert brain.LANGUAGE_PIN in prompt
    assert prompt.index(brain.LANGUAGE_PIN) > prompt.index("ПАМЕТ"), (
        "the pin is read before the exemplar block in attend() too")


def test_the_pin_cannot_be_switched_off_by_a_parameter():
    """A language rule with an off switch is off on the night it matters."""
    import inspect
    sig = inspect.signature(brain.think)
    for name in sig.parameters:
        assert "lang" not in name.lower(), (
            "think() grew a language parameter: {}".format(name))
    src = inspect.getsource(brain)
    assert "LANGUAGE_PIN = (" in src, "the pin stopped being a module constant"
    assert 'get("LANGUAGE_PIN"' not in src and "getenv" not in src.split(
        "LANGUAGE_PIN = (")[1][:400], "the pin became configurable"


def test_the_spirit_carries_the_english_law_not_the_bulgarian_one():
    spirit = brain._spirit()
    # The label was "LAW (English summary section; the full law is BG-only
    # pending approval):" for exactly one day. Emil approved the full
    # translation, so the caveat is gone and the label is just "LAW:".
    assert spirit.startswith("LAW:")
    assert "summary" not in spirit.split("CANON")[0]
    law = (REPO / "LAW_OF_THE_BRAIN.md").read_text(encoding="utf-8")
    bg_only = law.split("## BG", 1)[-1].split("## EN", 1)[0]
    # A sentence that exists only in the BG section must no longer be in the
    # prompt. Picking a distinctive one rather than counting Cyrillic, because
    # the canon is still Cyrillic and would mask the check.
    marker = "Мозъкът е навсякъде"
    assert marker in bg_only
    assert marker not in spirit


def test_the_law_block_carries_all_seven_clauses():
    """A summary is not a law. Seven in the BG section, seven in the prompt."""
    import re
    law_block = brain._spirit().split("CANON")[0]
    assert len(re.findall(r"^\d+\. \*\*", law_block, re.M)) == 7, law_block[:400]
    source = (REPO / "LAW_OF_THE_BRAIN.md").read_text(encoding="utf-8")
    bg = source.split("## BG", 1)[-1].split("## EN", 1)[0]
    assert len(re.findall(r"^\d+\. \*\*", bg, re.M)) == 7, (
        "the BG law changed clause count; the EN translation must follow it")
    assert not any(0x0400 <= ord(c) <= 0x052F for c in law_block)


def test_the_bulgarian_law_is_still_there_untouched():
    """The translation is an ADDITION. Emil's clauses stay where they were."""
    source = (REPO / "LAW_OF_THE_BRAIN.md").read_text(encoding="utf-8")
    bg = source.split("## BG", 1)[-1].split("## EN", 1)[0]
    assert "Мозъкът е навсякъде" in bg
    assert "Автономията се печели" in bg
    assert len(bg) > 1700, "the BG section shrank"


def test_the_warning_strings_are_english(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "LAW_FILE", tmp_path / "no_such_law.md")
    monkeypatch.setattr(brain, "BASE", tmp_path)
    spirit = brain._spirit()
    assert "[WARNING:" in spirit
    assert "ВНИМАНИЕ" not in spirit
    long_text = "x" * 100
    cut = brain._tail_budget(long_text, 10, "the law")
    assert cut.startswith("[WARNING:")
    assert "ВНИМАНИЕ" not in cut
