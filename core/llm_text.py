"""
core/llm_text.py — the type of a model's words (task #29, 25 Sep 2026).

core.llm_door marks every model answer it hands back as LLMText: a str that also
carries which backend and model said it, when, and in which cycle step. The
consumers that decide or publish - the notary's gate, the goal score, the GitHub
publisher, the Merkle archive, the proposal intake - refuse an LLMText by type
(LLMTextRefused, naming the field). Rule: the only way through is core.llm_parse -
typed plain values (a number, a date, a member of a closed set) or a refusal.

This module imports nothing from the repo, so a consumer can hold the guard
without holding a path to the door.

WHAT THE TYPE CANNOT DO, stated so nobody relies on it: the mark survives the str
methods overridden below (strip, slicing, replace, split, +, ...), and it does NOT
survive str(x), f-strings, "".join(...), or json.loads(x) - those return plain
values. test/test_llm_text.py keeps the structural net for that: no consumer
reaches core.llm_door except through core.llm_parse.
"""
from __future__ import annotations

from datetime import datetime, timezone


class LLMTextRefused(TypeError):
    """A model's words reached a field that takes only checked values."""


class LLMText(str):
    """A model answer. str-compatible; carries backend, model, ts, step."""

    def __new__(cls, text="", backend=None, model=None, step=None, ts=None):
        obj = super().__new__(cls, text)
        obj.backend = backend
        obj.model = model
        obj.step = step
        obj.ts = ts or datetime.now(timezone.utc).isoformat()
        return obj

    def __getnewargs__(self):
        return (str.__str__(self), self.backend, self.model, self.step, self.ts)

    def _same(self, s):
        return LLMText(s, self.backend, self.model, self.step, self.ts)

    def origin(self) -> str:
        return f"{self.backend}:{self.model} step={self.step} ts={self.ts}"

    def __repr__(self):
        return f"LLMText({str.__repr__(self)}, {self.origin()})"

    # the mark survives the operations a caller does to clean an answer up
    def strip(self, *a): return self._same(str.strip(self, *a))
    def lstrip(self, *a): return self._same(str.lstrip(self, *a))
    def rstrip(self, *a): return self._same(str.rstrip(self, *a))
    def lower(self): return self._same(str.lower(self))
    def upper(self): return self._same(str.upper(self))
    def casefold(self): return self._same(str.casefold(self))
    def title(self): return self._same(str.title(self))
    def capitalize(self): return self._same(str.capitalize(self))
    def replace(self, *a): return self._same(str.replace(self, *a))
    def removeprefix(self, p): return self._same(str.removeprefix(self, p))
    def removesuffix(self, p): return self._same(str.removesuffix(self, p))
    def expandtabs(self, *a): return self._same(str.expandtabs(self, *a))
    def center(self, *a): return self._same(str.center(self, *a))
    def ljust(self, *a): return self._same(str.ljust(self, *a))
    def rjust(self, *a): return self._same(str.rjust(self, *a))
    def zfill(self, *a): return self._same(str.zfill(self, *a))
    def __getitem__(self, k): return self._same(str.__getitem__(self, k))
    def __add__(self, o): return self._same(str.__add__(self, o))
    def __radd__(self, o): return self._same(str(o) + str.__str__(self))
    def __mul__(self, n): return self._same(str.__mul__(self, n))
    def __mod__(self, a): return self._same(str.__mod__(self, a))
    def split(self, *a, **k): return [self._same(s) for s in str.split(self, *a, **k)]
    def rsplit(self, *a, **k): return [self._same(s) for s in str.rsplit(self, *a, **k)]
    def splitlines(self, *a): return [self._same(s) for s in str.splitlines(self, *a)]
    def partition(self, sep): return tuple(self._same(s) for s in str.partition(self, sep))
    def rpartition(self, sep): return tuple(self._same(s) for s in str.rpartition(self, sep))


def find_llm_text(value, _depth: int = 0):
    """The first LLMText inside value (str, dict keys/values, list, tuple, set),
    or None."""
    if isinstance(value, LLMText):
        return value
    if _depth > 50:
        return None
    if isinstance(value, dict):
        for k, v in value.items():
            hit = find_llm_text(k, _depth + 1) or find_llm_text(v, _depth + 1)
            if hit is not None:
                return hit
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            hit = find_llm_text(v, _depth + 1)
            if hit is not None:
                return hit
    return None


def refuse_llm_text(value, field: str) -> None:
    """Raise LLMTextRefused, naming the field, if value is or holds an LLMText."""
    hit = find_llm_text(value)
    if hit is not None:
        raise LLMTextRefused(
            f"{field}: refused - model words ({hit.origin()}) reached a field that "
            f"takes only checked values; parse them with core.llm_parse first "
            f"(got {str.__repr__(hit)[:80]})")
