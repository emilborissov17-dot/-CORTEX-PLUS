# -*- coding: utf-8 -*-
"""
core/brain._smaller() — a function whose name asserts something it never checked.

THE DEFECT (found 5 Sep 2026, fixed the same night). The old body was:

    cands = sorted([m for m in ms if m and m != current], key=_size)
    return cands[0] if cands else None

It sorted the OTHER installed models by size and returned the first. It never
compared against `current`. With qwen2.5:3b, qwen2.5:7b and qwen3:8b installed on
this machine, that meant:

    _smaller("qwen2.5:3b") -> "qwen2.5:7b"

because 7b was merely the smallest model that was not 3b. The caller reaches this on
a TIMEOUT — the (model, COLD_TIMEOUT) / (_smaller(model), WARM_TIMEOUT) loop — so a
slow 3B answer loaded a 7B onto a 4 GB card and pushed host RAM toward the survival
gate that refused the 30 August cycle at RAM 94%.

The property is one line and was never asserted: a fallback must not be bigger than
what it falls back from.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import core.brain as brain      # noqa: E402


# The three models actually installed on this machine, as reported by
# ollama /api/tags on 5 Sep 2026.
INSTALLED = ["qwen2.5:3b", "qwen2.5:7b", "qwen3:8b"]


def _size(name: str) -> float:
    """The same size parse the function under test uses."""
    import re
    m = re.search(r":(\d+(?:\.\d+)?)b", str(name).lower())
    return float(m.group(1)) if m else 99.0


@pytest.fixture
def installed(monkeypatch):
    """models() is the live Ollama call; never let a test reach the network."""
    def _use(names):
        monkeypatch.setattr(brain, "models", lambda: list(names))
    return _use


# ── the three real cases on this machine ─────────────────────────────────────

def test_the_smallest_model_has_nothing_smaller(installed):
    """THE BUG, as a test. 3b is the smallest installed model, so there is nothing
    to fall back to and the honest answer is None — not 7b."""
    installed(INSTALLED)
    assert brain._smaller("qwen2.5:3b") is None


def test_7b_falls_back_to_3b(installed):
    installed(INSTALLED)
    assert brain._smaller("qwen2.5:7b") == "qwen2.5:3b"


def test_8b_falls_back_to_3b(installed):
    """3b, not 7b: the SMALLEST strictly-smaller model, not merely a smaller one."""
    installed(INSTALLED)
    assert brain._smaller("qwen3:8b") == "qwen2.5:3b"


# ── the property, over every installed model ─────────────────────────────────

@pytest.mark.parametrize("current", INSTALLED)
def test_never_returns_a_model_that_is_not_strictly_smaller(installed, current):
    """The invariant the name promises. Checked for every model, not just the one
    that happened to break."""
    installed(INSTALLED)
    got = brain._smaller(current)
    if got is not None:
        assert _size(got) < _size(current), (
            f"_smaller({current}) returned {got} "
            f"({_size(got)}b >= {_size(current)}b) — that is an ESCALATION")


def test_the_property_holds_for_an_arbitrary_zoo(installed):
    """Not tied to this machine's three models: no ordering of any model set may
    produce a fallback at or above the current size."""
    zoo = ["tiny:1b", "small:3b", "mid:7b", "big:8b", "huge:30b", "unsized-model"]
    installed(zoo)
    for cur in zoo:
        got = brain._smaller(cur)
        if got is not None:
            assert _size(got) < _size(cur), f"_smaller({cur}) -> {got} escalates"


# ── edges ────────────────────────────────────────────────────────────────────

def test_no_models_installed_returns_none(installed):
    installed([])
    assert brain._smaller("qwen2.5:3b") is None


def test_only_the_current_model_installed_returns_none(installed):
    installed(["qwen2.5:3b"])
    assert brain._smaller("qwen2.5:3b") is None


def test_an_unsized_name_is_treated_as_huge_not_as_small(installed):
    """_size() returns 99.0 for a name with no ':Nb'. That must make it a poor
    FALLBACK (never selected below a sized model), not a free pass."""
    installed(["qwen2.5:3b", "mystery-model"])
    assert brain._smaller("qwen2.5:3b") is None
    assert brain._smaller("mystery-model") == "qwen2.5:3b"


# ── the caller's contract, which None depends on ─────────────────────────────

def test_the_caller_breaks_on_none_rather_than_crashing():
    """_smaller may now return None far more often than before. The retry loop in
    brain.py must treat that as 'no fallback exists', not as a model name."""
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    i = src.index("(_smaller(model), WARM_TIMEOUT)")
    tail = src[i:i + 200]
    assert "if not mdl:" in tail and "break" in tail, (
        "the retry loop no longer guards against a None from _smaller")
