"""Permanent test suite for core/llm_json.py — shared LLM JSON extraction.

FIXTURE PROVENANCE — read this before trusting the samples below.
-----------------------------------------------------------------
These fixtures are RECONSTRUCTED, not captured. At the time this suite was
written no raw Cerebras-era LLM output survived on disk: core/history/ holds
only March qwen3 dumps, logs/ stops at 2026-06-18, and grepping the repo for
"The user asks" returned zero hits. So we do not claim these are verbatim
transcripts of the failing cycle.

They are, however, modelled directly on two things that ARE evidenced in the
code, not guessed:

  1. agents/internet/internet_agent.py already special-cased the literal
     string 'done thinking.' before this module existed — that marker is a
     real Cerebras gpt-oss artifact somebody hit in production.
  2. core/groq_backend._call_cerebras did `msg.get("content") or
     msg.get("reasoning")`. When max_tokens truncates before the model
     finishes reasoning, "content" is empty and the RAW REASONING TEXT is
     what reaches the parser. That is the mechanism that produces
     "The user asks: ..." preambles in a JSON parse path.

If a real sample is ever captured, add it here verbatim and keep these.
"""
import json

import pytest

from core.llm_json import (
    LLMJSONError,
    TruncatedJSONError,
    extract_json,
    looks_truncated,
    strip_reasoning,
)

# ---------------------------------------------------------------------------
# Reconstructed failure samples (see provenance note above)
# ---------------------------------------------------------------------------

# gpt-oss reasoning preamble, then the real answer. This is the common case:
# content was NOT empty, but the model narrated before emitting JSON.
GPT_OSS_PREAMBLE = '''The user asks: analyse the ENERGY axis and return JSON.
We need to produce a JSON object with keys summary, sentiment, urgency.
Let me think about what the sources say. The IEA report suggests growth.
done thinking.
{"summary": "Grid buildout lags demand.", "sentiment": "NEGATIVE", "urgency": "HIGH", "key_developments": ["IEA flags investment gap"]}'''

# The nastier case: max_tokens cut the model mid-reasoning, content was empty,
# groq_backend fell back to `reasoning`, and the parser got pure prose.
GPT_OSS_PURE_REASONING = '''The user asks: suggest 3 free data endpoints for BIODIVERSITY.
We need URLs that require no API key. Let me recall: GBIF has an occurrence API,
IUCN has a red list API but that needs a token, so probably not. Let me think about'''

# Truncated mid-JSON — the classic max_tokens cut inside the payload.
GPT_OSS_TRUNCATED_JSON = '''The user asks for a JSON snapshot.
done thinking.
{"summary": "Renewables scaling but grid constrained", "sentiment": "NEUTRAL",
 "key_developments": ["solar additions up 30%", "transmission queue backlo'''

# A decoy brace inside the reasoning that decodes as valid JSON on its own.
# A naive "find the first {" parser locks onto {} and returns garbage.
DECOY_BRACE = '''We need to return an object like {} with the right keys.
The user asks: score the axis.
{"score": 0.62, "axis": "ENERGY", "confidence": "MEDIUM"}'''

# qwen3-style unclosed <think> (response cut mid-thought).
UNCLOSED_THINK = '''<think>
Okay, the user wants JSON. Let me work out the schema first. I should
probably start with the summary field and then'''


# ---------------------------------------------------------------------------
# strip_reasoning
# ---------------------------------------------------------------------------


def test_strips_done_thinking_marker():
    assert strip_reasoning(GPT_OSS_PREAMBLE).startswith("{")


def test_strips_closed_think_block():
    raw = '<think>internal musings, ignore me</think>\n{"ok": true}'
    assert strip_reasoning(raw) == '{"ok": true}'


def test_strips_thinking_and_reasoning_tag_spellings():
    for tag in ("think", "thinking", "reasoning"):
        raw = f"<{tag}>noise</{tag}>" + '{"ok": 1}'
        assert strip_reasoning(raw) == '{"ok": 1}'


def test_unclosed_think_block_yields_no_payload():
    # Everything after a dangling <think> is reasoning, so nothing survives.
    assert strip_reasoning(UNCLOSED_THINK) == ""


def test_strips_markdown_fence():
    raw = 'Here you go:\n```json\n{"a": 1}\n```\nHope that helps!'
    assert strip_reasoning(raw) == '{"a": 1}'


def test_plain_json_passes_through_untouched():
    assert strip_reasoning('{"a": 1}') == '{"a": 1}'


# ---------------------------------------------------------------------------
# extract_json — the happy paths that used to fail
# ---------------------------------------------------------------------------


def test_extracts_json_after_gpt_oss_preamble():
    got = extract_json(GPT_OSS_PREAMBLE, expect=dict, backend="Cerebras")
    assert got["sentiment"] == "NEGATIVE"
    assert got["urgency"] == "HIGH"


def test_ignores_decoy_brace_in_preamble():
    """The bug that motivated this: naive parsers returned the decoy {}."""
    got = extract_json(DECOY_BRACE, expect=dict, backend="Cerebras")
    assert got == {"score": 0.62, "axis": "ENERGY", "confidence": "MEDIUM"}


def test_braces_inside_strings_do_not_break_extraction():
    """A hand-rolled balance counter miscounts this; raw_decode does not."""
    raw = 'prose\n{"note": "a closing brace } inside a string", "n": 2}\nmore prose'
    assert extract_json(raw, expect=dict)["n"] == 2


def test_extracts_array_when_expected():
    raw = 'Here are the proposals:\n[{"id": 1}, {"id": 2}]\nDone.'
    got = extract_json(raw, expect=list)
    assert len(got) == 2


def test_expect_dict_skips_a_leading_array():
    raw = '[1, 2, 3]\n{"real": "payload"}'
    assert extract_json(raw, expect=dict) == {"real": "payload"}


def test_returns_outermost_not_first_nested_object():
    raw = '{"outer": {"inner": 1}, "n": 5}'
    got = extract_json(raw, expect=dict)
    assert got["n"] == 5 and got["outer"] == {"inner": 1}


def test_trailing_prose_after_json_is_ignored():
    raw = '{"a": 1}\n\nLet me know if you want me to expand on any axis!'
    assert extract_json(raw, expect=dict) == {"a": 1}


# ---------------------------------------------------------------------------
# Truncation detection (item 3b)
# ---------------------------------------------------------------------------


def test_looks_truncated_on_unclosed_object():
    assert looks_truncated('{"a": 1, "b": [1, 2')


def test_looks_truncated_on_unterminated_string():
    assert looks_truncated('{"a": "unfinished')


def test_looks_truncated_false_on_complete_json():
    assert not looks_truncated('{"a": 1, "b": [1, 2]}')


def test_looks_truncated_ignores_brackets_inside_strings():
    assert not looks_truncated('{"a": "a [ and a { in a string"}')


def test_truncated_json_raises_truncated_error():
    with pytest.raises(TruncatedJSONError) as ei:
        extract_json(GPT_OSS_TRUNCATED_JSON, expect=dict, backend="Cerebras")
    assert ei.value.truncated is True
    assert ei.value.backend == "Cerebras"


def test_pure_reasoning_is_reported_as_truncated_not_garbage():
    """content was empty -> groq_backend used `reasoning` -> no JSON at all.

    This must be TRUNCATED (retryable), not a generic parse error, otherwise
    nobody retries and the axis silently degrades.
    """
    with pytest.raises(TruncatedJSONError):
        extract_json(GPT_OSS_PURE_REASONING, expect=dict, backend="Cerebras")


def test_provider_finish_reason_length_wins_even_if_text_looks_closed():
    """The provider told us it cut the response; believe it."""
    with pytest.raises(TruncatedJSONError) as ei:
        extract_json(
            "Sure, here is my analysis of the situation",  # no JSON, looks closed
            expect=dict,
            backend="Groq",
            finish_reason="length",
        )
    assert "finish_reason=length" in str(ei.value)


def test_reasoning_fallback_flag_forces_truncated_classification():
    """groq_backend telling us "content was empty, this IS the reasoning" is
    definitive — even for text with no reasoning fingerprints at all."""
    with pytest.raises(TruncatedJSONError) as ei:
        extract_json(
            "some opaque text with no markers",
            expect=dict,
            backend="Cerebras",
            used_reasoning_fallback=True,
        )
    assert "fell back to reasoning" in str(ei.value)


def test_prose_refusal_is_not_mistaken_for_truncation():
    """A refusal has no reasoning fingerprints; retrying it is pointless.
    This is the boundary that keeps the reasoning-leak heuristic honest."""
    with pytest.raises(LLMJSONError) as ei:
        extract_json(
            "I'm sorry, I can't help with that request.",
            expect=dict,
            backend="Groq",
        )
    assert not isinstance(ei.value, TruncatedJSONError)


def test_valid_json_still_parses_even_when_finish_reason_is_length():
    """finish_reason=length only matters when extraction actually failed."""
    got = extract_json('{"a": 1}', expect=dict, finish_reason="length")
    assert got == {"a": 1}


# ---------------------------------------------------------------------------
# Error quality — a failure must never be blank or anonymous
# ---------------------------------------------------------------------------


def test_garbage_raises_plain_llmjson_error_not_truncated():
    with pytest.raises(LLMJSONError) as ei:
        extract_json("I refuse to answer that.", expect=dict, backend="Gemini")
    assert not isinstance(ei.value, TruncatedJSONError)
    assert ei.value.truncated is False


def test_error_always_names_the_backend():
    with pytest.raises(LLMJSONError) as ei:
        extract_json("no json here", expect=dict, backend="OpenRouter")
    assert "OpenRouter" in str(ei.value)


def test_error_message_is_never_empty():
    """The sibling of the self_awareness bug: str(e) == '' renders blank."""
    with pytest.raises(LLMJSONError) as ei:
        extract_json("", expect=dict, backend="Groq")
    assert str(ei.value).strip()
    assert ei.value.raw_snippet == ""


def test_wrong_type_is_an_error_not_a_silent_coercion():
    with pytest.raises(LLMJSONError):
        extract_json('[1, 2, 3]', expect=dict, backend="Groq")


def test_llmjson_error_is_a_valueerror():
    """Existing `except ValueError`/`except Exception` callers keep working."""
    assert issubclass(LLMJSONError, ValueError)


# ---------------------------------------------------------------------------
# call_llm_json — the retry-once-on-truncation path (item 3b)
# ---------------------------------------------------------------------------


def test_call_llm_json_retries_once_on_truncation_and_doubles_budget(monkeypatch):
    """First call is truncated; the retry must go out with 2x max_tokens
    and its result must be the one returned."""
    import core.groq_backend as gb
    calls = []

    def fake(prompt, max_tokens=1024):
        calls.append(max_tokens)
        if len(calls) == 1:
            return GPT_OSS_TRUNCATED_JSON, {
                "backend": "Cerebras",
                "finish_reason": "length",
            }
        return '{"summary": "complete", "sentiment": "NEUTRAL"}', {
            "backend": "Cerebras",
            "finish_reason": "stop",
        }

    monkeypatch.setattr(gb, "call_groq_meta", fake)

    from core.llm_json import call_llm_json

    got = call_llm_json("prompt", max_tokens=600, expect=dict, label="test")
    assert got["summary"] == "complete"
    assert calls == [600, 1200], "retry must double the token budget"


def test_call_llm_json_does_not_retry_on_plain_garbage(monkeypatch):
    """Garbage is not retryable — one call only, then raise."""
    import core.groq_backend as gb
    calls = []

    def fake(prompt, max_tokens=1024):
        calls.append(max_tokens)
        return "I will not answer.", {"backend": "Groq", "finish_reason": "stop"}

    monkeypatch.setattr(gb, "call_groq_meta", fake)

    from core.llm_json import call_llm_json

    with pytest.raises(LLMJSONError):
        call_llm_json("prompt", max_tokens=600, expect=dict)
    assert len(calls) == 1, "must not retry a non-truncation failure"


def test_call_llm_json_raises_if_retry_also_truncated(monkeypatch):
    """Two strikes: propagate TruncatedJSONError so the caller can mark
    the snapshot TRUNCATED rather than silently writing junk."""
    import core.groq_backend as gb
    calls = []

    def fake(prompt, max_tokens=1024):
        calls.append(max_tokens)
        return GPT_OSS_PURE_REASONING, {
            "backend": "Cerebras",
            "used_reasoning_fallback": True,
        }

    monkeypatch.setattr(gb, "call_groq_meta", fake)

    from core.llm_json import call_llm_json

    with pytest.raises(TruncatedJSONError):
        call_llm_json("prompt", max_tokens=600, expect=dict)
    assert calls == [600, 1200], "exactly one retry, then give up"


# ---------------------------------------------------------------------------
# The three replaced implementations still expose their old contracts
# ---------------------------------------------------------------------------


def test_self_observer_jsonparseerror_alias_still_catches():
    """self_observer has two live `except JSONParseError` clauses."""
    from agents.core.self_observer import JSONParseError, _extract_json

    with pytest.raises(JSONParseError):
        _extract_json("not json at all")


def test_self_observer_extract_json_array_contract():
    from agents.core.self_observer import _extract_json_array

    assert _extract_json_array('prose [{"a": 1}] prose') == [{"a": 1}]


def test_internet_agent_parse_llm_json_contract():
    from agents.internet.internet_agent import _parse_llm_json

    got = _parse_llm_json(GPT_OSS_PREAMBLE)
    assert got["summary"] == "Grid buildout lags demand."


def test_cortex_llm_resource_extract_returns_dict_now():
    """Type change: used to return a str, now returns the parsed dict."""
    from core.cortex_llm_resource import _extract_json_object

    got = _extract_json_object('reasoning...\n{"status": "OK"}')
    assert isinstance(got, dict)
    assert got["status"] == "OK"
