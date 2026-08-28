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
    """No reasoning path may skip the transform. THE SHAPE is shared; the FLOOR
    is per backend and must be justified by that backend's own measurement.

    AMENDED 28 Aug 2026, and the amendment is the point.
    ------------------------------------------------------
    This test used to assert the three budgets were EQUAL at every call size.
    That held while all three floors were 1500, and its stated purpose — "a
    future change that fixes one path and forgets another" — is still exactly
    right. But equality was the wrong way to hold it, for a reason the original
    docstring already contains without drawing the conclusion:

        Groq     openai/gpt-oss-120b
        Cerebras gpt-oss-120b          <- same model as Groq
        Gemini   gemini-3.5-flash      <- a DIFFERENT model, different thinker

    Two of the three are the same model; the third is not, and it is not
    entitled to the same number just because it sits in the same list. On
    2026-08-28T08:05:00 Gemini cut 14 of 19 answers at floor 1500 while Groq
    truncated zero times in the same cycle. Forcing one floor would mean either
    leaving Gemini broken to keep the symmetry, or moving Groq and Cerebras on
    evidence collected about neither. Both are worse than an asymmetry with a
    reason attached.

    So what is pinned now is what actually prevents the original defect:
      1. every reasoning path goes through _reasoning_budget (structural);
      2. no floor is below 1500, the level that was measured safe in August;
      3. a floor above it names its measurement, right here, in this list.
    """
    # floor -> the evidence that set it. A floor with no entry here fails (3).
    JUSTIFIED_FLOORS = {
        "groq": (g.GROQ_BUDGET_FLOOR, 1500,
                 "20 Aug 2026: gpt-oss-120b, 19 truncations at the raw caller "
                 "budget; 1500 stopped them and no Groq truncation has been "
                 "observed since, including the 2026-08-28T08:05 cycle"),
        "cerebras": (g.CEREBRAS_BUDGET_FLOOR, 1500,
                     "same model as Groq; the floor originated here and this "
                     "path never truncated once across 440 calls 15-18 Aug"),
        "gemini": (g.GEMINI_BUDGET_FLOOR, 4000,
                   "2026-08-28T08:05: 14 of 19 answers cut at 1500; truncated "
                   "replies 77..1382 chars, median 247.5, while the two "
                   "complete answers ran 1711/1764 chars (~430-440 output "
                   "tokens) - thinking took ~1060-1070 of 1500 even when it "
                   "succeeded, and all of it when it did not"),
    }

    for name, (actual, expected, why) in JUSTIFIED_FLOORS.items():
        assert actual == expected, (
            f"{name} floor is {actual}, and the justification recorded here is "
            f"for {expected}. Change the floor and the evidence together, or "
            f"not at all: {why}")
        assert actual >= 1500, (
            f"{name} floor {actual} is under the August measurement of 1500")

    # (1) the structural half: all three transform, none passes the raw number.
    for asked in CALLER_BUDGETS:
        groq = g._reasoning_budget(asked, g.GROQ_BUDGET_MULT,
                                   g.GROQ_BUDGET_FLOOR, g.GROQ_BUDGET_CAP)
        gemini = g._reasoning_budget(asked, g.GEMINI_BUDGET_MULT,
                                     g.GEMINI_BUDGET_FLOOR, g.GEMINI_BUDGET_CAP)
        cerebras = g._effective_budget(asked)
        for name, got in (("groq", groq), ("gemini", gemini),
                          ("cerebras", cerebras)):
            assert got > asked, (
                f"{name} passed the caller's raw {asked} straight through — "
                f"this is the defect the file exists to catch")
        # Groq and Cerebras ARE the same model and must not drift apart.
        assert groq == cerebras, (
            f"groq and cerebras run the same model (gpt-oss-120b) and disagree "
            f"at max_tokens={asked}: groq={groq} cerebras={cerebras}")
