"""Cerebras is a reasoning backend — its token budget is not the caller's budget.

gpt-oss-120b counts reasoning tokens INSIDE max_completion_tokens (Cerebras docs:
"the maximum number of tokens that can be generated in the completion, including
reasoning tokens").  Every call site in this repo is sized for llama-3.3-70b
(80..4096 tokens), so the model spent the whole budget thinking and got cut off
before writing the payload — finish_reason=length on nearly every Cerebras call
in the 2026-07-13 cycle, dozens of truncated snapshots, and a global synthesis
that found 0 axes.

The fix lives in core/groq_backend.py alone: a per-backend transform
(mult/floor/cap) plus reasoning_effort, so no call site changes.  The FLOOR is
the load-bearing part — 3x80 is still 240, which is still hopeless.

These tests pin the wire format: Cerebras gets max_completion_tokens +
reasoning_effort at the transformed value; the other three backends keep sending
a plain, unscaled max_tokens.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import groq_backend as gb


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


_OPENAI_SHAPED = {
    "choices": [
        {"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}
    ]
}

_GEMINI_SHAPED = {
    "candidates": [
        {"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}
    ]
}


@pytest.fixture(autouse=True)
def _no_keys_no_sleep(monkeypatch):
    """Every backend gets a key, nobody sleeps, nobody is in cooldown."""
    monkeypatch.setattr(gb, "_load_key", lambda name: "test-key")
    monkeypatch.setattr(gb, "_SLEEP_SECS", 0)
    monkeypatch.setattr(gb.time, "sleep", lambda *_: None)
    monkeypatch.setattr(gb, "_cooldowns", {})
    monkeypatch.setattr(gb, "_cooldown_hits", {})


@pytest.fixture
def sent(monkeypatch):
    """Captures the JSON body of every outgoing request."""
    bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        bodies.append((url, json))
        if url == gb.GEMINI_API_URL or url.startswith(gb.GEMINI_API_URL):
            return _FakeResponse(_GEMINI_SHAPED)
        return _FakeResponse(_OPENAI_SHAPED)

    monkeypatch.setattr(gb.requests, "post", fake_post)
    return bodies


# ---------------------------------------------------------------------------
# The transform itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "requested, expected, why",
    [
        (80,    1500, "media_intel: 3x80=240, floor saves it"),
        (600,   1800, "data_scout: 3x600 clears the floor"),
        (1024,  3072, "the chain-wide default"),
        (4096,  8192, "hypercortex_actions: 3x4096=12288, capped"),
    ],
)
def test_effective_budget(requested, expected, why):
    assert gb._effective_budget(requested) == expected, why


def test_floor_is_what_saves_the_small_call_sites():
    """The multiplier alone is not enough — this is the whole point of the fix."""
    scaled_only = int(80 * gb.CEREBRAS_BUDGET_MULT)
    assert scaled_only < gb.CEREBRAS_BUDGET_FLOOR
    assert gb._effective_budget(80) == gb.CEREBRAS_BUDGET_FLOOR


def test_budget_never_exceeds_cap():
    # Free-tier ceiling for gpt-oss-120b is 32k; the cap keeps us well under.
    assert gb._effective_budget(999_999) == gb.CEREBRAS_BUDGET_CAP
    assert gb.CEREBRAS_BUDGET_CAP <= 32_000


# ---------------------------------------------------------------------------
# What actually goes on the wire
# ---------------------------------------------------------------------------

def test_cerebras_payload_uses_max_completion_tokens_and_reasoning_effort(sent):
    gb._call_cerebras("prompt", 600)

    url, body = sent[0]
    assert url == gb.CEREBRAS_API_URL
    assert body["max_completion_tokens"] == 1800
    assert body["reasoning_effort"] == gb.CEREBRAS_REASONING_EFFORT
    # max_tokens is only a legacy alias at Cerebras, and sending both is asking
    # for one of them to silently win.
    assert "max_tokens" not in body


def test_transform_logs_when_it_kicks_in_meaningfully(sent, capsys):
    """Tomorrow's cycle log must show the fix working without archaeology."""
    gb._call_cerebras("prompt", 80)
    assert "budget 80->1500 (floor)" in capsys.readouterr().out


def test_no_log_when_transform_is_a_no_op(sent, capsys):
    """A budget already big enough must not add noise (8192 cap on a 4096 ask
    is exactly 2x, so use a request whose scaled value stays under 2x)."""
    gb._call_cerebras("prompt", 8192)  # capped back to 8192 — nothing to say
    assert "budget" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "fn, url_attr",
    [
        (gb._call_groq,       "GROQ_API_URL"),
        (gb._call_openrouter, "OPENROUTER_API_URL"),
    ],
)
def test_other_openai_backends_still_send_plain_max_tokens(sent, fn, url_attr):
    """The transform is Cerebras-only. Groq/OpenRouter are not reasoning models
    and their payloads must not change."""
    fn("prompt", 600)

    url, body = sent[0]
    assert url == getattr(gb, url_attr)
    assert body["max_tokens"] == 600
    assert "max_completion_tokens" not in body
    assert "reasoning_effort" not in body


def test_gemini_still_sends_plain_max_output_tokens(sent):
    gb._call_gemini("prompt", 600)

    _url, body = sent[0]
    assert body["generationConfig"]["maxOutputTokens"] == 600
    assert "reasoning_effort" not in body
