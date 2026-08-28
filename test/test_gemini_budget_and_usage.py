"""Gemini's floor, and the token accounting that was read and thrown away.

WHAT WAS MEASURED (cycle 2026-08-28T08:05:00)
---------------------------------------------
gemini-3.5-flash counts thinking INSIDE maxOutputTokens. With the floor at 1500
it cut 14 of 19 answers. The truncated replies, in characters, matched from
memory/llm_provenance.jsonl by prompt_head and timestamp:

    77 171 174 182 191 193 239 256 258 271 293 519 1348 1382    median 247.5

Eleven of fourteen under 300 characters — the budget went entirely on thinking.
The two COMPLETE answers at the same call site were 1711 and 1764 characters,
about 430-440 output tokens, so thinking cost ~1060-1070 of the 1500 there.

TWO PROPERTIES, AND THE SECOND IS THE ONE THAT LASTS
-----------------------------------------------------
The floor is 4000, in code and not in .env, so git and the next reader can see
it. And usageMetadata — thoughtsTokenCount / candidatesTokenCount, the provider
telling us the split directly — is carried into memory/llm_provenance.jsonl
instead of being discarded. The audit above had to ESTIMATE that split from
reply length because these fields were read and dropped on the floor. Whoever
asks next reads the number.

    venv/Scripts/python.exe -m pytest test/test_gemini_budget_and_usage.py -v
"""
import json
import hashlib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import groq_backend as gb          # noqa: E402

PROVENANCE = REPO / "memory" / "llm_provenance.jsonl"


def _digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


# NO DIGEST GUARD HERE, AND THE REASON IS THE POINT.
#
# The first version of this file hashed memory/llm_provenance.jsonl at import and
# asserted it unchanged at the end. On 2026-08-28 it went red — correctly seeing a
# change, wrongly blaming this module: a scheduled cycle had started four minutes
# into the suite and appended 25 rows of real LLM provenance.
#
# That is not a new lesson. test/conftest.py:175-213 records the same guard being
# tried first, firing on its first live run against memory/collector_runs.log
# written by the CORTEX_Collector task, and being deliberately DEMOTED to a warning:
#
#     "A filesystem-only canary CANNOT tell 'a test wrote this' from 'another
#      process wrote this while the suite happened to be running'. Left as a hard
#      failure it would go red at random, and a guard that cries wolf gets switched
#      off — which is a worse outcome than not having written it."
#
# So the claim is delegated to the guard that can actually prove it.
# conftest.py::_no_live_writes is autouse, intercepts the write primitives INSIDE
# this process, covers _GUARDED_TREES = ("memory", "config") — which includes
# memory/llm_provenance.jsonl — and FAILS, with no false positives by construction.
# Re-implementing the rejected design beside it would only add a way to be wrong.


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


# A real-shaped Gemini reply, including the usageMetadata block that the code
# used to drop. The numbers are the measured proportions from the cycle above:
# thinking ate most of the budget, the answer got the remainder.
GEMINI_WITH_USAGE = {
    "candidates": [
        {"content": {"parts": [{"text": '{"urgency": "LOW"}'}]},
         "finishReason": "MAX_TOKENS"}
    ],
    "usageMetadata": {
        "promptTokenCount": 812,
        "thoughtsTokenCount": 1437,
        "candidatesTokenCount": 63,
        "totalTokenCount": 2312,
    },
}

GEMINI_NO_USAGE = {
    "candidates": [
        {"content": {"parts": [{"text": '{"urgency": "LOW"}'}]},
         "finishReason": "STOP"}
    ]
}


@pytest.fixture(autouse=True)
def _no_keys_no_sleep(monkeypatch):
    monkeypatch.setattr(gb, "_load_key", lambda name: "test-key")
    monkeypatch.setattr(gb, "_SLEEP_SECS", 0)
    monkeypatch.setattr(gb.time, "sleep", lambda *_: None)
    monkeypatch.setattr(gb, "_cooldowns", {})
    monkeypatch.setattr(gb, "_cooldown_hits", {})


@pytest.fixture
def sent(monkeypatch):
    bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        bodies.append((url, json))
        return _FakeResponse(GEMINI_WITH_USAGE)

    monkeypatch.setattr(gb.requests, "post", fake_post)
    return bodies


# ── the floor ──────────────────────────────────────────────────────────────

def test_the_floor_is_four_thousand():
    assert gb.GEMINI_BUDGET_FLOOR == 4000


def test_the_floor_is_the_default_in_code_not_only_in_env(monkeypatch):
    """A threshold that lives only in .env is invisible to git."""
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    assert 'os.environ.get("GEMINI_BUDGET_FLOOR", "4000")' in src


@pytest.mark.parametrize(
    "requested, expected, why",
    [
        (400,  4000, "internet_agent: 3x400=1200, the floor is what saves it"),
        (80,   4000, "the smallest call site in the repo"),
        (1400, 4200, "3x1400 clears the floor"),
        (4096, 8192, "capped, well under any provider ceiling"),
    ],
)
def test_gemini_budget(requested, expected, why):
    got = gb._reasoning_budget(requested, gb.GEMINI_BUDGET_MULT,
                               gb.GEMINI_BUDGET_FLOOR, gb.GEMINI_BUDGET_CAP)
    assert got == expected, why


def test_the_call_site_that_truncated_now_gets_room(sent):
    """internet_agent asks for 400. Under the old floor that bought 1500."""
    gb._call_gemini("prompt", 400)
    _url, body = sent[0]
    assert body["generationConfig"]["maxOutputTokens"] == 4000
    # The two complete answers measured ~430-440 output tokens; the worst
    # observed thinking took the whole 1500. 4000 covers both with margin.
    assert body["generationConfig"]["maxOutputTokens"] >= 1500 + 440


# ── the accounting that was being discarded ────────────────────────────────

def test_usage_metadata_reaches_the_meta_dict(sent):
    _text, meta = gb._call_gemini("prompt", 400)
    assert meta["thoughts_tokens"] == 1437
    assert meta["answer_tokens"] == 63
    assert meta["prompt_tokens"] == 812
    assert meta["total_tokens"] == 2312
    assert meta["budget"] == 4000
    assert meta["finish_reason"] == "length", "MAX_TOKENS normalises to length"


def test_the_split_is_now_readable_without_estimating_it(sent):
    """The question Item 4(d) could not answer from the ledger."""
    _text, meta = gb._call_gemini("prompt", 400)
    assert meta["thoughts_tokens"] + meta["answer_tokens"] <= meta["budget"]
    share = meta["thoughts_tokens"] / (meta["thoughts_tokens"] + meta["answer_tokens"])
    assert share > 0.9, "this fixture is the shape that truncated"


def test_absent_usage_metadata_yields_absent_keys_not_zeros(monkeypatch):
    """An absent key is honest; a zero would be a measurement nobody made."""
    monkeypatch.setattr(gb.requests, "post",
                        lambda *a, **k: _FakeResponse(GEMINI_NO_USAGE))
    _text, meta = gb._call_gemini("prompt", 400)
    for k in ("thoughts_tokens", "answer_tokens", "prompt_tokens",
              "total_tokens", "budget"):
        assert k not in meta
    assert meta["finish_reason"] == "stop"


def test_provenance_row_carries_the_token_fields():
    """_log_provenance is nested inside call_groq_meta; assert on the source."""
    src = (REPO / "core" / "groq_backend.py").read_text(encoding="utf-8")
    assert "def _log_provenance(backend_label: str, prompt_text: str, content_text: str,\n" \
           "                        meta: dict | None = None):" in src
    assert "_log_provenance(label, prompt, result, meta)" in src
    for field in ("thoughts_tokens", "answer_tokens", "prompt_tokens",
                  "total_tokens", "budget", "finish_reason"):
        assert f'"{field}"' in src, f"{field} must be written to provenance"


def test_a_call_without_the_stub_would_be_caught(monkeypatch):
    """The positive form of "live state was not touched", and provable here.

    No provenance row can exist without an HTTP call, so the property to hold is
    that this module never makes one. Asserted by making the real transport
    explode: any test that reached it would fail loudly rather than quietly
    appending to the ledger. (Asserting the ledger FILE is unchanged is not this
    module's to assert — other processes write it. See the note at the top.)
    """
    def _forbidden(*a, **k):
        raise AssertionError("a test reached the real network")

    monkeypatch.setattr(gb.requests, "post", _forbidden)
    with pytest.raises(AssertionError, match="reached the real network"):
        gb._call_gemini("prompt", 400)
