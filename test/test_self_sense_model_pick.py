"""Model selection must prefer the model that FITS VRAM, not the biggest one.

THE BUG (2026-07-14)
--------------------
PREFERRED_MODELS was ordered by capability — qwen2.5:7b first — with qwen2.5:3b
and qwen3:1.7b annotated "not installed". Then qwen2.5:3b WAS pulled, and the
list was never revisited.

pick_model() walks that list in order and returns the first INSTALLED match, so
it kept choosing the 7b. On the real machine `--check` listed all three models,
selected qwen2.5:7b, correctly failed its own C4 (system RAM 92.3% — the 7b does
not fit the GTX 1650's ~3.9 GB of free VRAM and spills ~1.9 GB into system RAM),
and then advised "pull qwen2.5:3b" — which was already on disk. The check was
right about everything except the one thing it actually controlled.

WHY FIT BEATS CAPABILITY HERE
-----------------------------
A model that fits entirely in VRAM costs ~0 system RAM. One that does not spills
into system RAM — and system RAM is what BODY's 70% caution threshold protects.
Above it, BODY cuts the live cycle's workers from 3 to 2, so the experiment would
be DEGRADING the live system: exactly what its isolation rules forbid. A smaller
model that fits beats a bigger one that spills, every time.

These tests mock the model list rather than touching Ollama, so they pin the
ORDERING — the thing that was actually wrong — and keep working with the server
down.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "pulse"))

import self_sense as ss


def _models(*names) -> list[dict]:
    """The shape ollama_models() returns."""
    sizes = {
        "qwen2.5:3b": 1.93,
        "qwen3:1.7b": 1.4,
        "qwen2.5:7b": 4.68,
        "qwen3:8b": 5.23,
    }
    return [{"name": n, "size_gb": sizes.get(n, 1.0)} for n in names]


# ---------------------------------------------------------------------------
# THE regression: the exact list on the real machine
# ---------------------------------------------------------------------------

def test_picks_the_model_that_fits_when_all_three_are_installed():
    """The real machine's inventory on 2026-07-14. It chose qwen2.5:7b."""
    available = _models("qwen2.5:7b", "qwen3:8b", "qwen2.5:3b")

    assert ss.pick_model(available) == "qwen2.5:3b"


def test_list_order_does_not_influence_the_choice():
    """pick_model must rank by PREFERRED_MODELS, not by whatever order the Ollama
    API happens to return."""
    for order in [
        ("qwen2.5:7b", "qwen3:8b", "qwen2.5:3b"),
        ("qwen2.5:3b", "qwen2.5:7b", "qwen3:8b"),
        ("qwen3:8b", "qwen2.5:3b", "qwen2.5:7b"),
    ]:
        assert ss.pick_model(_models(*order)) == "qwen2.5:3b", f"order {order} changed the pick"


# ---------------------------------------------------------------------------
# The ranking itself
# ---------------------------------------------------------------------------

def test_fitting_models_outrank_spilling_ones_in_the_list():
    """The invariant behind the fix, checked against the list rather than a
    scenario: every model that fits must come before every model that spills. If
    someone adds a big model at the top again, this fails."""
    idx = {m: i for i, m in enumerate(ss.PREFERRED_MODELS)}
    fitting = [m for m in ss.PREFERRED_MODELS if not m.startswith(ss.SPILLS_INTO_RAM)]
    spilling = [m for m in ss.PREFERRED_MODELS if m.startswith(ss.SPILLS_INTO_RAM)]

    assert fitting and spilling, "the list should contain both kinds"
    assert max(idx[m] for m in fitting) < min(idx[m] for m in spilling)


def test_among_fitting_models_plain_instruct_beats_reasoning():
    """qwen3:1.7b fits too, but it is a reasoning model: <think> blocks cost
    latency on every tick. A reflex, not a deliberation."""
    assert ss.pick_model(_models("qwen3:1.7b", "qwen2.5:3b")) == "qwen2.5:3b"


def test_falls_back_to_a_spilling_model_only_when_nothing_fits():
    """The 7b is not forbidden — it is a fallback. If nothing that fits is
    installed, a spilling model beats no model at all."""
    assert ss.pick_model(_models("qwen2.5:7b", "qwen3:8b")) == "qwen2.5:7b"


def test_prefers_the_smaller_spiller_when_only_spillers_exist():
    assert ss.pick_model(_models("qwen3:8b", "qwen2.5:7b")) == "qwen2.5:7b"


# ---------------------------------------------------------------------------
# Pre-existing behaviour that must not regress
# ---------------------------------------------------------------------------

def test_matches_a_quantised_tag_variant():
    """'qwen2.5:3b' must also match 'qwen2.5:3b-instruct-q4_K_M'."""
    assert ss.pick_model(_models("qwen2.5:3b-instruct-q4_K_M")) == "qwen2.5:3b-instruct-q4_K_M"


def test_unknown_model_is_better_than_nothing():
    assert ss.pick_model(_models("llama3:8b")) == "llama3:8b"


def test_no_models_at_all():
    assert ss.pick_model([]) is None
