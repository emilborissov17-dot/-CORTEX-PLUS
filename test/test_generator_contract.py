# -*- coding: utf-8 -*-
"""
The other two generators are judged by the same gate, so they must be shown the
same contract. Written 6 Sep 2026, failing before the fix.

MEASURED: `_strategist_to_proposals` and `_growth_to_proposals` in
fast_cycle_runner walk their snapshots to `_inject_proposals` ->
`proposal_intake.admit` — the SAME door hyperclaw goes through. Their prompts
never mentioned INDICATOR / EXPECTED_DELTA / DEADLINE, never listed the gradeable
indicators, and never stated what the machine can and cannot do. They were being
judged against a contract they had never been shown, which is not a gate, it is
a trap: every proposal they produce is refused for a reason they were never told.

Mirrors test_hyperclaw_plan_contract.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import gate_contract as gc          # noqa: E402

STRATEGIST = REPO / "agents" / "cortex_strategist" / "cortex_strategist_agent.py"
GROWTH = REPO / "agents" / "body" / "growth_planner.py"
RUNNER = REPO / "fast_cycle_runner.py"


def _prompt_source(path: Path) -> str:
    """The f-string prompt as written in the file. The prompts are built inline,
    so the source is what is inspected — the same thing the model will see."""
    return path.read_text(encoding="utf-8")


# ── the contract must be IN the prompt ───────────────────────────────────────

@pytest.mark.parametrize("path,name", [(STRATEGIST, "strategist"), (GROWTH, "growth")])
def test_prompt_states_the_capabilities(path, name):
    """The prompt must CARRY the capabilities, and it now does so by
    interpolating the shared block rather than embedding a copy - so this
    checks the interpolation, and test_the_contract_block_carries_all_three_parts
    checks what the block says. (First version grepped the source for the
    literal text, which stopped being true the moment the copy was removed:
    the test was pinning the copy it asked to delete.)"""
    src = _prompt_source(path)
    assert "contract_block" in src, (
        "the " + name + " prompt does not build the contract block")
    assert "{_gate}" in src, (
        "the " + name + " prompt imports the contract but never puts it in the "
        "prompt text - the model would still not be told")


@pytest.mark.parametrize("path,name", [(STRATEGIST, "strategist"), (GROWTH, "growth")])
def test_prompt_lists_the_gradeable_indicators(path, name):
    src = _prompt_source(path)
    assert "GRADEABLE INDICATORS" in src, (
        f"the {name} prompt does not list the indicators that can actually be "
        f"graded, so any indicator it names is a guess")


@pytest.mark.parametrize("path,name", [(STRATEGIST, "strategist"), (GROWTH, "growth")])
@pytest.mark.parametrize("key", gc.REQUIRED_KEYS)
def test_prompt_requires_the_three_keys(path, name, key):
    src = _prompt_source(path)
    assert key in src, (
        f"the {name} prompt never mentions {key}, but proposal_intake refuses "
        f"every proposal that arrives without it")


@pytest.mark.parametrize("path,name", [(STRATEGIST, "strategist"), (GROWTH, "growth")])
def test_prompt_uses_the_shared_contract_not_a_copy(path, name):
    """One block, one module. Three hand-copied blocks drift, and the day they
    drift the gate and the prompt disagree about what is required."""
    src = _prompt_source(path)
    assert "gate_contract" in src, (
        f"the {name} prompt does not import core.gate_contract; a pasted copy "
        f"will drift from the gate it is judged by")


# ── the parsers must carry the triple through to the door ────────────────────

@pytest.mark.parametrize("fn", ["_strategist_to_proposals", "_growth_to_proposals"])
def test_the_runner_carries_the_triple_into_the_proposal(fn):
    """A generator that answers with the three fields must not have them dropped
    on the way to intake.

    The first version of this test grepped each function body for the field
    names. They come from one shared helper instead, so it was asserting the
    wrong shape - the test was wrong, not the code. It now pins the call AND
    the helper."""
    src = RUNNER.read_text(encoding="utf-8")
    body = src.split("def " + fn, 1)[1].split(chr(10) + "def ", 1)[0]
    assert "_triple_from(" in body, (
        fn + " does not carry the model's INDICATOR/EXPECTED_DELTA/DEADLINE "
        "through, so a correct answer is discarded before the gate sees it")


@pytest.mark.parametrize("field", ["indicator", "expected_delta", "deadline"])
def test_the_shared_triple_helper_reads_all_three(field):
    src = RUNNER.read_text(encoding="utf-8")
    helper = src.split("def _triple_from", 1)[1].split(chr(10) + "def ", 1)[0]
    assert field in helper, "_triple_from never produces " + repr(field)


def test_the_triple_helper_never_invents_a_missing_field():
    """A parser that fills a blank is telling the gate what it wants to hear -
    the defect that put a step's numbers onto an objective on 6 Sep."""
    src = RUNNER.read_text(encoding="utf-8")
    helper = src.split("def _triple_from", 1)[1].split(chr(10) + "def ", 1)[0]
    code = [l for l in helper.splitlines() if not l.strip().startswith("#")]
    joined = chr(10).join(code)
    for bad in ("or 0.0", "or 0)", "TODAY", "default="):
        assert bad not in joined, "_triple_from substitutes a value: " + bad


# ── the shared block itself ──────────────────────────────────────────────────

def test_the_indicator_block_says_none_rather_than_inventing_some():
    assert "none resolved this cycle" in gc.indicator_block({})
    assert "WATER_REVIEW" in gc.indicator_block({"WATER_REVIEW": 73.6})


def test_the_contract_block_carries_all_three_parts():
    block = gc.contract_block({"WATER_REVIEW": 73.6})
    assert "CORTEX++ CAN:" in block
    assert "GRADEABLE INDICATORS" in block
    for key in gc.REQUIRED_KEYS:
        assert key in block


def test_expected_delta_is_asked_for_as_a_bare_number():
    """MEASURED 6 Sep: the model answered "0.0 *(snapshot only, ...)*" and the
    parser kept the raw string, so the proposal reached intake with no numeric
    delta at all. The prompt now asks for a bare number and says why."""
    assert "bare number" in gc.REQUIRED_LINES
