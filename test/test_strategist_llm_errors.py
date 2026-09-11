# -*- coding: utf-8 -*-
"""
test/test_strategist_llm_errors.py — STEP 6a/6b of the 10 Sep 2026 handover.

THE DEFECT, FROM THE LOG RATHER THAN FROM A GUESS. On the night of 10 Sep
memory/cycle_logs/cycle_2026-09-10_030402.log printed, at lines 1133-1143:

    [LLM] Groq failed (413 Client Error: Payload Too Large) -- next...
    [STRATEGIST] JSON parse failed: Expecting value: line 1 column 1 (char 0)
    [STRATEGIST] raw LLM output: "We need to analyze the system and output JSON
                                  with required fields."
    [STRATEGIST] LLM error: All LLM backends failed

The last line was false. memory/llm_provenance.jsonl has OpenRouter
(nvidia/nemotron-3-super-120b) answering `ok` at 00:25:50, 36 seconds after the
413 — the fallback chain worked exactly as designed. What broke was the agent's
own hand-rolled parser meeting a reasoning model's preamble, and the report of
that break borrowed the vocabulary of an infrastructure outage.

WHAT A REFUSAL LOOKS LIKE HERE, AND THE FORBIDDEN FALLBACK. The refusal is
`{"error": ...}` naming WHICH of the two things happened. The forbidden
fallback is any single sentence that covers both — most of all the string
"All LLM backends failed" on a path where a backend answered. These tests fail
if it returns.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

import agents.cortex_strategist.cortex_strategist_agent as S  # noqa: E402
from core import llm_json as LJ  # noqa: E402
from core.groq_backend import AllBackendsFailedError  # noqa: E402


# --------------------------------------------------------------------------- #
# the two outcomes are told apart
# --------------------------------------------------------------------------- #

def test_a_reasoning_preamble_now_parses_instead_of_being_called_an_outage(monkeypatch):
    """THE 10 SEP REGRESSION, verbatim. nemotron's real reply shape: prose
    first, JSON after. The old parser split on fences, found none, hit char 0
    and returned None -> "All LLM backends failed"."""
    reply = ('We need to analyze the system and output JSON with required '
             'fields. Let me think about the gaps.\n'
             '{"system_health": "FAIR", "mission_alignment_pct": 55, '
             '"critical_gaps": [], "immediate_actions": []}')
    monkeypatch.setattr(LJ, "call_llm_json",
                        lambda p, **k: LJ.extract_json(reply, expect=dict))
    out = S._groq("anything")
    assert "error" not in out, f"a parseable reply was reported as an error: {out}"
    assert out["system_health"] == "FAIR"


def test_a_backend_that_answered_is_never_reported_as_no_backend(monkeypatch):
    """A parse failure must say a backend ANSWERED. The forbidden sentence is
    named here so it cannot come back by accident."""
    def boom(prompt, **kw):
        raise LJ.LLMJSONError("We need to analyze the system and output JSON",
                              "no JSON object found", backend="OpenRouter")
    monkeypatch.setattr(LJ, "call_llm_json", boom)
    out = S._groq("anything")
    assert "error" in out
    assert "did not parse" in out["error"]
    assert "All LLM backends failed" not in out["error"], (
        "a parse error is again wearing the name of an outage")


def test_no_backend_answering_says_exactly_that(monkeypatch):
    """The other half: when the chain really is exhausted, that must be
    distinguishable from a parse failure — otherwise telling them apart in the
    log is impossible and this whole fix is cosmetic."""
    def boom(prompt, **kw):
        raise AllBackendsFailedError("All LLM backends failed (Groq/OpenRouter"
                                     "/Gemini + local). Last error: timeout")
    monkeypatch.setattr(LJ, "call_llm_json", boom)
    out = S._groq("anything")
    assert "error" in out
    assert "no backend answered" in out["error"]
    assert "did not parse" not in out["error"]


def test_the_two_reasons_are_not_the_same_string(monkeypatch):
    """MUTATION NET. Collapse the two except-branches into one message and this
    fails: the whole point of STEP 6b is that these two facts stop sharing a
    sentence."""
    def parse_fail(prompt, **kw):
        raise LJ.LLMJSONError("prose only", "no JSON object found")

    def chain_fail(prompt, **kw):
        raise AllBackendsFailedError("nothing answered")
    monkeypatch.setattr(LJ, "call_llm_json", parse_fail)
    a = S._groq("x")["error"]
    monkeypatch.setattr(LJ, "call_llm_json", chain_fail)
    b = S._groq("x")["error"]
    assert a != b, "a parse failure and an exhausted chain report the same thing"


def test_synthesize_never_invents_a_reason_it_was_not_given(monkeypatch):
    """The generic sentence used to be added at the CALL SITE, discarding
    whatever _groq had said. Whatever reason arrives must survive to the
    caller."""
    monkeypatch.setattr(S, "_groq", lambda p: {"error": "reply did not parse as JSON: prose only"})
    monkeypatch.setattr(S, "scan_project", lambda: {
        "goals": "", "agents": [], "memory_modules": [], "snapshots_summary": {},
        "predictions": [], "self_modifier_patches": [], "missing_integrations": [],
        "cycle_structure": "", "goal_score": {}})
    out = S.synthesize(S.scan_project())
    assert "did not parse" in out["error"], (
        f"the call site replaced the reason with its own: {out['error']!r}")
    assert "All LLM backends failed" not in out["error"]


# --------------------------------------------------------------------------- #
# the prompt cap is named, not silent
# --------------------------------------------------------------------------- #

def test_a_prompt_under_the_cap_is_untouched():
    p = "x" * 100
    assert S._cap(p, cap=1000) == p, "a prompt inside the cap must pass through byte-identical"


def test_an_oversized_prompt_is_marked_not_silently_shortened():
    """The forbidden version of this fix is a silent slice: a brief that lost
    40k chars of evidence must not read like a complete one."""
    p = "y" * 5000
    out = S._cap(p, cap=1000)
    assert len(out) < len(p)
    assert "TRUNCATED BY cortex_strategist_agent._cap" in out
    assert "4000 chars" in out, "the marker must say HOW MUCH was dropped"
    assert "INCOMPLETE" in out


def test_the_cap_marker_names_the_module_that_cut_it():
    """A marker that does not name its author sends the next reader hunting."""
    out = S._cap("z" * 3000, cap=500)
    assert "cortex_strategist_agent" in out


# --------------------------------------------------------------------------- #
# provenance can now answer "how big was it"
# --------------------------------------------------------------------------- #

def test_provenance_records_the_prompt_size(tmp_path, monkeypatch):
    """A 413 is ABOUT a length, and until today no row carried one: five 413s
    between 2 and 10 Sep are unattributable because prompt_sha1 identifies a
    prompt and prompt_head shows 80 chars of it, and neither is a size."""
    from core import groq_backend as G
    rows = []

    import core.durable as D
    monkeypatch.setattr(D, "append_json",
                        lambda path, row, batched=False: rows.append(row))

    prompt = "Анализирай" * 500          # Cyrillic: chars != bytes
    fn = _find_log_provenance(G)
    fn("Groq", prompt, "reply", {"finish_reason": "stop"})
    assert rows, "nothing was logged"
    row = rows[-1]
    assert row["prompt_chars"] == len(prompt)
    assert row["prompt_bytes"] == len(prompt.encode("utf-8"))
    assert row["prompt_bytes"] > row["prompt_chars"], (
        "Cyrillic must show a byte/char gap — otherwise one number would do")


def _find_log_provenance(G):
    """_log_provenance is nested inside call_groq_meta, so it is reached the
    only way a closure can be: rebuild it from its code object, supplying its
    one free variable (_model_for, also nested) as a stub. Driving the whole of
    call_groq_meta instead would need the budget ladder, the backend policy and
    the model window, and would test those rather than this row."""
    import types
    for const in G.call_groq_meta.__code__.co_consts:
        if isinstance(const, types.CodeType) and const.co_name == "_log_provenance":
            assert const.co_freevars == ("_model_for",), (
                f"the closure's free variables changed: {const.co_freevars}")
            cell = (types.CellType(lambda label: "test-model"),)
            return types.FunctionType(const, G.__dict__, "_log_provenance",
                                      None, cell)
    pytest.skip("_log_provenance is no longer a nested function")
