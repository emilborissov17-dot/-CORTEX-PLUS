#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_reasoning_budget.py — A THINKING MODEL MUST BE GIVEN ROOM TO THINK.

WHAT WENT WRONG (measured 20 August 2026)
------------------------------------------
GROQ_MODEL moved from llama-3.3-70b-versatile to openai/gpt-oss-120b, and
GEMINI to gemini-3.5-flash. Both new models REASON: the thinking tokens are
spent out of the same budget as the answer. The call sites were sized for
llama (media_intel_worker passes 80, live_divergence_pilot 200, self_observer
and predictor 300), so the model spent the whole allowance thinking and the
answer came back cut off — or empty.

The 17:05 cycle logged it 29 times:

    [LLM] Groq OK (finish_reason=length — ОТРЯЗАН отговор)     x19
    [LLM] Gemini OK (finish_reason=length — ОТРЯЗАН отговор)   x10
    Cerebras                                                     x0

Cerebras was already correct — it had _effective_budget() with a floor, added
when IT moved to gpt-oss-120b. Groq and Gemini were passing the raw number
straight through. Same model, same defect, two paths that had not been told.

MEASURED, NOT ASSUMED
----------------------
Gemini's accounting was established by experiment against the live API rather
than from documentation, because the docs were not consulted:

    maxOutputTokens=100  -> thoughts=93   candidates=3   MAX_TOKENS
    maxOutputTokens=300  -> thoughts=285  candidates=11  MAX_TOKENS
    maxOutputTokens=1024 -> thoughts=460  candidates=62  STOP

thoughts + candidates <= the cap at every level. The thinking is inside the
budget. Groq reports the same shape: a separate "reasoning" field, with
completion_tokens covering thinking and answer together.

THE NEGATIVE CONTROL
---------------------
test_the_groq_path_asks_for_more_than_the_caller_did asserts the payload's
budget is STRICTLY GREATER than the raw max_tokens. Put the raw value back --
"max_tokens": max_tokens -- and it goes red. Proven both ways before commit.

A test that only checked "a budget key is present" would pass against the
broken version, which is exactly how this survived the model swap.

    venv\\Scripts\\python.exe -m pytest test/test_reasoning_budget.py -v
"""
from __future__ import annotations

import pytest

import core.groq_backend as g

# The budgets real call sites ask for. 80 is media_intel_worker, which is the
# one that cannot survive without the floor.
CALLER_BUDGETS = [80, 150, 200, 300, 400, 1024]


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def captured(monkeypatch):
    """Capture the request body without sending it anywhere."""
    seen: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        seen["url"] = url
        seen["payload"] = json
        if "generativelanguage" in url:
            return _FakeResponse({"candidates": [{
                "content": {"parts": [{"text": "ok"}]},
                "finishReason": "STOP",
            }]})
        return _FakeResponse({"choices": [{
            "message": {"content": "ok"},
            "finish_reason": "stop",
        }]})

    monkeypatch.setattr(g.requests, "post", fake_post)
    monkeypatch.setattr(g, "_load_key", lambda name: "test-key-not-a-real-one")
    monkeypatch.setattr(g, "_system_msg", lambda: "system")
    monkeypatch.setattr(g, "_SLEEP_SECS", 0)
    return seen


def _groq_budget(payload: dict) -> int:
    """The number Groq will actually enforce, whichever field carries it."""
    for field in ("max_completion_tokens", "max_tokens"):
        if field in payload:
            return payload[field]
    raise AssertionError(f"the Groq payload carries no token budget at all: {payload}")


# ---------------------------------------------------------------------------
# (a) The Groq path — the one the task named
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asked", CALLER_BUDGETS)
def test_the_groq_path_asks_for_more_than_the_caller_did(captured, asked):
    """THE NEGATIVE CONTROL LIVES HERE.

    Restore `"max_tokens": max_tokens` in _call_groq and this fails: the sent
    budget equals the asked budget instead of exceeding it.
    """
    g._call_groq("prompt", asked)
    sent = _groq_budget(captured["payload"])

    assert sent > asked, (
        f"\n"
        f"  GROQ GOT NO ROOM TO THINK: caller asked {asked}, payload sent {sent}.\n"
        f"  {g.GROQ_MODEL} is a reasoning model — the thinking is spent out of\n"
        f"  this same budget, so passing the raw number back means the answer is\n"
        f"  truncated (finish_reason=length) or empty. The 17:05 cycle logged 19\n"
        f"  of those. Apply _reasoning_budget() as _call_cerebras does.\n"
    )


@pytest.mark.parametrize("asked", CALLER_BUDGETS)
def test_the_groq_budget_never_falls_under_the_floor(captured, asked):
    """3 x 80 = 240 still is not enough to finish thinking. The floor, not the
    multiplier, is what makes the small call sites survive."""
    g._call_groq("prompt", asked)
    assert _groq_budget(captured["payload"]) >= g.GROQ_BUDGET_FLOOR


def test_the_groq_budget_is_capped(captured):
    """The cap keeps us under the free tier ceiling however large the ask."""
    g._call_groq("prompt", 999_999)
    assert _groq_budget(captured["payload"]) == g.GROQ_BUDGET_CAP


# ---------------------------------------------------------------------------
# (b) Gemini — same model behaviour, measured, so the same floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asked", CALLER_BUDGETS)
def test_the_gemini_path_asks_for_more_than_the_caller_did(captured, asked):
    g._call_gemini("prompt", asked)
    sent = captured["payload"]["generationConfig"]["maxOutputTokens"]

    assert sent > asked, (
        f"\n"
        f"  GEMINI GOT NO ROOM TO THINK: caller asked {asked}, payload sent {sent}.\n"
        f"  Measured against the live API: at maxOutputTokens=100 the model spent\n"
        f"  93 on thoughts and 3 on the answer and returned MAX_TOKENS. The 17:05\n"
        f"  cycle logged 10 truncations on this path.\n"
    )


# ---------------------------------------------------------------------------
# (c) The three reasoning paths agree
# ---------------------------------------------------------------------------

def test_cerebras_still_gets_its_original_budget():
    """The refactor moved Cerebras onto the shared helper. Its numbers must not
    have moved with it — it was the one path that was already right."""
    for asked in CALLER_BUDGETS:
        expected = min(g.CEREBRAS_BUDGET_CAP,
                       max(g.CEREBRAS_BUDGET_FLOOR, int(asked * g.CEREBRAS_BUDGET_MULT)))
        assert g._effective_budget(asked) == expected


def test_every_reasoning_backend_uses_the_same_transform():
    """Groq, Gemini and Cerebras run the same model family. A future change that
    fixes one path and forgets another is the defect this file is about."""
    for asked in CALLER_BUDGETS:
        groq = g._reasoning_budget(asked, g.GROQ_BUDGET_MULT,
                                   g.GROQ_BUDGET_FLOOR, g.GROQ_BUDGET_CAP)
        gemini = g._reasoning_budget(asked, g.GEMINI_BUDGET_MULT,
                                     g.GEMINI_BUDGET_FLOOR, g.GEMINI_BUDGET_CAP)
        assert groq == gemini == g._effective_budget(asked), (
            f"the three reasoning paths disagree at max_tokens={asked}: "
            f"groq={groq} gemini={gemini} cerebras={g._effective_budget(asked)}"
        )
