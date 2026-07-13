#!/usr/bin/env python3
r"""
llm_json.py — shared, robust JSON extraction from LLM output
=============================================================
Replaces three divergent local implementations that each handled a
different subset of the failure modes:

  * agents/core/self_observer.py    _extract_json / _extract_json_array
  * core/cortex_llm_resource.py     _extract_json_object
  * agents/internet/internet_agent.py  _parse_llm_json
  * core/data_scout.py              (inline fence-stripping)

FAILURE MODES THIS HANDLES
--------------------------
1. Reasoning preambles. Cerebras gpt-oss-120b is a reasoning model:
   the answer lives in message["content"], the chain-of-thought in
   message["reasoning"]. groq_backend._call_cerebras falls back to
   `content or reasoning` when content is empty (which is exactly what
   happens when max_tokens truncates before the model finishes thinking).
   The parser then receives raw reasoning prose — "The user asks: ...",
   "We need to produce JSON ...", often ending in "done thinking."
   with no JSON at all, or with a half-written JSON sketch.

2. <think> / <thinking> blocks (qwen3, deepseek-r1, some OpenRouter models),
   including UNCLOSED ones when the response was cut mid-thought.

3. Markdown fences (```json ... ```).

4. Decoy braces in the prose before the real JSON: a naive
   `text.find("{")` + balance counter locks onto `{}` inside an English
   sentence and then fails. A naive `re.search(r'\{.*\}', DOTALL)` grabs
   from the first brace to the last, swallowing trailing prose.

5. Braces inside JSON strings — `{"note": "}"}` breaks any hand-rolled
   balance counter. json.JSONDecoder.raw_decode is string-aware, so we
   build on it instead of counting characters ourselves.

6. TRUNCATION (item 3b). A response cut off by max_tokens leaves an
   unclosed structure. Previously this surfaced as a generic parse error
   indistinguishable from "model returned garbage", so nobody retried.
   Now it is detected explicitly (finish_reason == "length" where the
   backend reports it, plus structural unclosed-bracket detection) and
   is either retried once with a larger budget or marked TRUNCATED.

STRATEGY
--------
Rather than trusting the first '{' we see, we raw_decode at EVERY
candidate offset, keep every value that decodes AND matches the expected
type, and return the one spanning the most characters — the outermost /
real payload, not a decoy from the preamble.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMJSONError(ValueError):
    """LLM output contained no valid JSON of the expected shape.

    Always carries the backend name (when known) and a raw snippet, so a
    failure is never a bare, contextless message. Subclasses ValueError so
    existing `except ValueError` / `except Exception` clauses keep working.
    """

    def __init__(
        self,
        raw: str,
        reason: str,
        backend: Optional[str] = None,
        truncated: bool = False,
    ):
        self.raw = raw or ""
        self.raw_snippet = self.raw[:300]
        self.reason = reason
        self.backend = backend or "unknown"
        self.truncated = truncated
        super().__init__(
            f"[llm_json] backend={self.backend} truncated={self.truncated} "
            f"reason={reason} | raw[:300]={self.raw_snippet!r}"
        )


class TruncatedJSONError(LLMJSONError):
    """The output is valid JSON as far as it goes, but it was cut off."""

    def __init__(self, raw: str, reason: str, backend: Optional[str] = None):
        super().__init__(raw, reason, backend=backend, truncated=True)


# ---------------------------------------------------------------------------
# Reasoning / wrapper stripping
# ---------------------------------------------------------------------------

# Closed reasoning blocks, any of the tag spellings we have seen in the wild.
_THINK_BLOCK_RE = re.compile(
    r"<(think|thinking|reasoning)>.*?</\1>", re.DOTALL | re.IGNORECASE
)
# An UNCLOSED opening tag: response was cut mid-thought, so everything from
# the tag onward is reasoning. Only meaningful if no closing tag survives.
_THINK_OPEN_RE = re.compile(r"<(think|thinking|reasoning)>", re.IGNORECASE)
# A dangling close tag with no open tag: everything BEFORE it is reasoning.
_THINK_CLOSE_RE = re.compile(r"</(think|thinking|reasoning)>", re.IGNORECASE)

# Cerebras gpt-oss end-of-reasoning marker. Already special-cased in
# internet_agent.py before this module existed.
_DONE_THINKING_RE = re.compile(r"done thinking\.?", re.IGNORECASE)

# Fingerprints of leaked chain-of-thought. When the output contains these AND
# no JSON at all, the model never got as far as emitting a payload — i.e. it
# was cut mid-thought. That is retryable, and must NOT be confused with a model
# that answered in prose (a refusal), which retrying will not fix.
_REASONING_LEAK_RE = re.compile(
    r"\b(the user (asks|wants)|we need to|let me (think|recall|work out)|"
    r"i should (probably )?start|done thinking)\b",
    re.IGNORECASE,
)


def strip_reasoning(raw: str) -> str:
    """Remove reasoning wrappers. Never guesses JSON boundaries — that is
    extract_json's job. Safe to call on text with no wrappers at all."""
    if not raw:
        return ""

    text = raw

    # 1. Whole <think>...</think> blocks.
    text = _THINK_BLOCK_RE.sub("", text)

    # 2. A surviving close tag means the open tag was lost (or the block was
    #    malformed): the payload is whatever follows the LAST close tag.
    if _THINK_CLOSE_RE.search(text):
        text = _THINK_CLOSE_RE.split(text)[-1]

    # 3. A surviving OPEN tag with no close means the model was cut off mid
    #    -thought: everything from the tag on is reasoning, not payload.
    open_match = _THINK_OPEN_RE.search(text)
    if open_match:
        text = text[: open_match.start()]

    # 4. Cerebras "done thinking." — payload follows the last occurrence.
    if _DONE_THINKING_RE.search(text):
        text = _DONE_THINKING_RE.split(text)[-1]

    # 5. Markdown fences. Keep fence *bodies* only; a ```json body is the
    #    payload and any prose outside the fences is commentary.
    if "```" in text:
        parts = text.split("```")
        # Odd indices are fence bodies when the fences are balanced; when
        # they are not (truncated output), the tail is still a body.
        bodies = [p for i, p in enumerate(parts) if i % 2 == 1]
        candidates = []
        for body in bodies:
            body = body.strip()
            # Strip an optional language tag on the first line.
            if body.lower().startswith("json"):
                body = body[4:].strip()
            if body:
                candidates.append(body)
        if candidates:
            # The real payload is the largest fenced body.
            text = max(candidates, key=len)

    return text.strip()


# ---------------------------------------------------------------------------
# Truncation detection
# ---------------------------------------------------------------------------


def looks_truncated(text: str) -> bool:
    """True if `text` has an unterminated JSON string or an unclosed
    { / [ — i.e. it stops mid-structure, the signature of a max_tokens cut.

    String-aware: braces and brackets inside JSON strings are ignored, and
    a backslash escapes the next character.
    """
    if not text:
        return False

    depth = 0
    in_string = False
    escaped = False
    seen_open = False

    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
            seen_open = True
        elif ch in "}]":
            depth -= 1

    # Unterminated string, or brackets still open at EOF.
    if in_string:
        return True
    return seen_open and depth > 0


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

_DECODER = json.JSONDecoder()


def extract_json(
    raw: str,
    *,
    expect: Optional[type] = None,
    backend: Optional[str] = None,
    finish_reason: Optional[str] = None,
    used_reasoning_fallback: bool = False,
) -> Any:
    """Extract the outermost JSON value from an LLM response.

    expect        — dict, list, or None (accept either).
    backend       — name of the LLM backend, echoed in errors so a failure is
                    always attributable ("which model gave us this garbage?").
    finish_reason — from the API when available; "length" means the provider
                    itself told us the response was cut short.
    used_reasoning_fallback — True when groq_backend had to fall back to the
                    Cerebras "reasoning" field because "content" was empty.
                    That is definitive proof the model never emitted a payload,
                    so a parse failure here is truncation, not garbage.

    Raises TruncatedJSONError when the output was cut short, and LLMJSONError
    otherwise. Both carry backend + raw snippet. The distinction matters:
    truncation is retryable, garbage is not.
    """
    if raw is None or not str(raw).strip():
        raise LLMJSONError(raw or "", "empty response", backend=backend)

    cleaned = strip_reasoning(raw)

    if not cleaned:
        # Everything was reasoning; the model never emitted a payload. That is
        # the classic truncated-gpt-oss case (content empty -> reasoning used).
        raise TruncatedJSONError(
            raw, "response was entirely reasoning, no JSON payload", backend=backend
        )

    # Try to decode at every plausible start offset, keeping the widest match
    # of the expected type. This defeats decoy braces in the preamble.
    best: Any = None
    best_span = -1
    found_any = False
    last_err: Optional[Exception] = None

    for i, ch in enumerate(cleaned):
        if ch not in "{[":
            continue
        try:
            value, end = _DECODER.raw_decode(cleaned, i)
        except json.JSONDecodeError as e:
            last_err = e
            continue

        found_any = True
        if expect is not None and not isinstance(value, expect):
            continue

        span = end - i
        if span > best_span:
            best, best_span = value, span

    if best_span >= 0:
        return best

    # Nothing usable. Decide whether this is truncation or plain garbage —
    # the caller reacts very differently to the two (retry vs. give up).
    provider_says_cut = (finish_reason or "").lower() == "length"
    structurally_cut = looks_truncated(cleaned)
    # No JSON at all + visible chain-of-thought = the model was still thinking
    # when it ran out of budget. Distinct from a prose refusal, which has no
    # reasoning fingerprints and is not worth retrying.
    reasoning_leaked = not found_any and bool(_REASONING_LEAK_RE.search(cleaned))

    if provider_says_cut or structurally_cut or used_reasoning_fallback or reasoning_leaked:
        if provider_says_cut:
            why = "provider reported finish_reason=length"
        elif structurally_cut:
            why = "unclosed JSON structure at end of output"
        elif used_reasoning_fallback:
            why = "backend returned empty content and fell back to reasoning"
        else:
            why = "output is leaked chain-of-thought with no JSON payload"
        raise TruncatedJSONError(raw, why, backend=backend)

    if found_any and expect is not None:
        raise LLMJSONError(
            raw,
            f"found JSON but not of expected type {expect.__name__}",
            backend=backend,
        )

    raise LLMJSONError(
        raw,
        f"no valid JSON found ({last_err or 'no { or [ in output'})",
        backend=backend,
    )


# ---------------------------------------------------------------------------
# Call + parse, with one retry on truncation
# ---------------------------------------------------------------------------

# Sentinel returned (instead of raising) when the caller asks us not to raise.
TRUNCATED: dict = {"_status": "TRUNCATED"}


def call_llm_json(
    prompt: str,
    *,
    max_tokens: int = 1024,
    expect: Optional[type] = None,
    label: str = "llm",
    retry_on_truncation: bool = True,
) -> Any:
    """Call the LLM fallback chain and parse its output as JSON.

    On truncation, retries ONCE with double the token budget (that is the
    only lever we have: the chain picks the backend, not us). If the retry
    is also truncated, TruncatedJSONError propagates — callers that prefer a
    marker over an exception should catch it and write _status=TRUNCATED.
    """
    # Local import: avoids an import cycle, and mirrors the dual
    # package/script import style used elsewhere in core/.
    try:
        from core.groq_backend import call_groq_meta
    except ImportError:  # running from inside core/ as a script
        from groq_backend import call_groq_meta

    raw, meta = call_groq_meta(prompt, max_tokens=max_tokens)
    try:
        return extract_json(
            raw,
            expect=expect,
            backend=meta.get("backend"),
            finish_reason=meta.get("finish_reason"),
            used_reasoning_fallback=meta.get("used_reasoning_fallback", False),
        )
    except TruncatedJSONError as first:
        if not retry_on_truncation:
            raise
        bigger = max_tokens * 2
        print(
            f"  [{label}] TRUNCATED from {first.backend} "
            f"(max_tokens={max_tokens}) — retrying once at {bigger}"
        )
        raw2, meta2 = call_groq_meta(prompt, max_tokens=bigger)
        return extract_json(
            raw2,
            expect=expect,
            backend=meta2.get("backend"),
            finish_reason=meta2.get("finish_reason"),
            used_reasoning_fallback=meta2.get("used_reasoning_fallback", False),
        )
