"""
core/llm_parse.py — the one way from a model's words to a value a gate may use
(task #29, 25 Sep 2026).

Rule: a validator accepts model words (LLMText, or a plain str) ONLY if the whole
answer is exactly one well-formed value of the requested kind, and what comes back
is a plain Python value - float, datetime.date, or a member of the caller's closed
set; anything else is LLMParseError naming the field (test_llm_text: test_parse_*). There is no default, no
"best guess", no partial match: "about 3" is not a number, "next Tuesday" is not a
date, and "notary " is not the step "notary" unless the caller's set says so after
strip.

This module imports core.llm_text only. It must never import core.llm_door:
test/test_llm_text.py checks it.
"""
from __future__ import annotations

import re
from datetime import date

from core.llm_text import LLMText  # noqa: F401 - the type this module accepts

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INDICATOR = re.compile(r"[A-Z][A-Z0-9_]*(?:__[a-z0-9_]+)?")


class LLMParseError(ValueError):
    """The model's words are not exactly one value of the requested kind."""


def _text(t, field: str) -> str:
    if not isinstance(t, str):
        raise LLMParseError(f"{field}: expected model words (str), got {type(t).__name__}")
    return str.__str__(t).strip()


def number(t, field: str, lo: float | None = None, hi: float | None = None) -> float:
    s = _text(t, field)
    if not _NUMBER.fullmatch(s):
        raise LLMParseError(f"{field}: not exactly one number: {s[:60]!r}")
    v = float(s)
    if v != v or v in (float("inf"), float("-inf")):
        raise LLMParseError(f"{field}: not a finite number: {s[:60]!r}")
    if lo is not None and v < lo:
        raise LLMParseError(f"{field}: {v} is below {lo}")
    if hi is not None and v > hi:
        raise LLMParseError(f"{field}: {v} is above {hi}")
    return v


def iso_date(t, field: str) -> date:
    s = _text(t, field)
    if not _ISO_DATE.fullmatch(s):
        raise LLMParseError(f"{field}: not an ISO date YYYY-MM-DD: {s[:60]!r}")
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise LLMParseError(f"{field}: {e}") from e


def enum(t, field: str, allowed) -> str:
    """The member of `allowed` the words name exactly (after strip). Returns the
    caller's own member object, never the model's string."""
    s = _text(t, field)
    for a in allowed:
        if str(a) == s:
            return a
    raise LLMParseError(f"{field}: {s[:60]!r} is not one of {sorted(map(str, allowed))[:12]}")


def indicator(t, field: str = "indicator") -> str:
    """AXIS or AXIS__metric, the shape core.proposal_intake grades."""
    s = _text(t, field)
    if not _INDICATOR.fullmatch(s):
        raise LLMParseError(f"{field}: not AXIS or AXIS__metric: {s[:60]!r}")
    return "".join(s)


def proposal_fields(p: dict) -> dict:
    """A proposal's INDICATOR / EXPECTED_DELTA / DEADLINE, parsed; the rest of the
    dict is returned as it was. Raises LLMParseError naming the first bad field."""
    if not isinstance(p, dict):
        raise LLMParseError("proposal: not a dict")
    out = dict(p)
    out["indicator"] = indicator(p.get("indicator"), "indicator")
    d = p.get("expected_delta")
    out["expected_delta"] = (number(d, "expected_delta") if isinstance(d, str)
                             else _plain_number(d, "expected_delta"))
    out["deadline"] = iso_date(p.get("deadline"), "deadline").isoformat()
    return out


def _plain_number(v, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise LLMParseError(f"{field}: not a number: {v!r}")
    return float(v)
