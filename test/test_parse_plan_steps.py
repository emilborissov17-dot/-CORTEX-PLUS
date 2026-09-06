# -*- coding: utf-8 -*-
"""
parse_plan must see every STEP block. Written 6 Sep 2026, failing before the fix.

MEASURED on the first night the plan contract was live (cycle 2026-09-06T03:04):
plans/plan-2026-09-06.md carries 8 STEP blocks, each with its own INDICATOR /
EXPECTED_DELTA / DEADLINE, and parse_plan returned FOUR proposals — one per axis
section, each an OBJECTIVE line wearing the LAST step's triple.

Two causes, both in the regexes:

  _step_dash_re = r'^-\\s+STEP\\s+\\d+...'   requires the literal "STEP" straight
      after "- ". The model writes "- **STEP 1:**", so the match dies at the
      bold marker and NO step is ever seen.

  Because no STEP line creates a new `current`, every INDICATOR/EXPECTED_DELTA/
      DEADLINE line in a section writes into that section's OBJECTIVE dict. Step
      1 sets it, step 2 overwrites it. The surviving triple is the last step's,
      attached to a proposal that never earned one.

A step that vanishes is worse than a step that is refused: refusal is recorded
by name in proposal_intake_refusals.jsonl and can be read the next morning, while
a step the parser never matched leaves no trace anywhere.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agents.hyperclaw.hyperclaw_orchestrator import parse_plan   # noqa: E402

PLAN = REPO / "plans" / "plan-2026-09-06.md"

# The eight steps as they stand in the file, in file order. Read out of the plan
# on 6 Sep 2026 and pinned here: this is the ground truth the parser is measured
# against, not something derived by the parser itself.
EXPECTED = [
    ("HUMAN",        "HUMAN_WELL_BEING_REVIEW",        2.0,   "2026-09-09"),
    ("HUMAN",        "HUMAN_WELL_BEING_REVIEW",        None,  "2026-09-08"),
    ("PLANET",       "FOOD_REVIEW",                    None,  "2026-09-08"),
    ("PLANET",       "WATER_REVIEW",                   1.2,   "2026-09-10"),
    ("CIVILIZATION", "GOVERNANCE_INSTITUTIONS_REVIEW", None,  "2026-09-07"),
    ("CIVILIZATION", "INEQUALITY_POVERTY_REVIEW",     -0.5,   "2026-09-11"),
    ("COSMOS",       "LONG_TERM_FUTURE_REVIEW",        None,  "2026-09-09"),
    ("COSMOS",       "LONG_TERM_FUTURE_REVIEW",        0.2,   "2026-09-12"),
]


@pytest.fixture(scope="module")
def steps():
    if not PLAN.is_file():
        pytest.skip(f"{PLAN} is not on disk")
    text = PLAN.read_text(encoding="utf-8")
    proposals = parse_plan(text, PLAN.name, "2026-09-06T01:00:00Z")
    # A STEP proposal is the one carrying a triple. Objectives may still be
    # emitted; they simply must not be wearing a step's numbers any more.
    return [p for p in proposals if p.get("indicator")]


def test_every_step_block_becomes_a_proposal(steps):
    """Eight blocks in the file, eight proposals at the gate."""
    assert len(steps) == 8, (
        f"parse_plan produced {len(steps)} proposals carrying a triple, from 8 STEP "
        f"blocks. Steps that never match leave no trace at all — not in "
        f"improvement_proposals.json, not in proposal_intake_refusals.jsonl.\n"
        + "\n".join(f"  {p.get('component')}  {p.get('indicator')}  "
                    f"{p.get('expected_delta')}  {p.get('deadline')}" for p in steps))


def test_the_triples_are_in_file_order_and_belong_to_their_own_step(steps):
    got = [(p.get("component"), p.get("indicator"), p.get("deadline")) for p in steps]
    want = [(c, i, d) for c, i, _, d in EXPECTED]
    assert got == want, (
        "the triples are not the file's, in the file's order:\n"
        f"  got  {got}\n  want {want}")


@pytest.mark.parametrize("i", range(8))
def test_each_numeric_delta_is_a_number_not_a_borrowed_one(steps, i):
    if len(steps) != 8:
        pytest.skip("step count is wrong; the ordering test reports that")
    _, _, delta, _ = EXPECTED[i]
    if delta is None:
        return                      # carries a parenthetical; intake names it
    assert steps[i].get("expected_delta") == pytest.approx(delta), (
        f"step {i + 1}: expected_delta {steps[i].get('expected_delta')!r}, want {delta}")


def test_no_solution_carries_a_markdown_marker(steps):
    """The step text is the proposal. '**STEP 1:**' and a stray leading '**' are
    formatting, and a proposal that begins with '*' has carried the marker into
    the record a human reads."""
    bad = [p["solution"] for p in steps if p["solution"].lstrip().startswith("*")]
    assert not bad, "solutions still start with a markdown marker:\n  " + "\n  ".join(bad)
    for p in steps:
        assert "STEP" not in p["solution"][:12].upper(), (
            f"the step label leaked into the solution: {p['solution'][:40]!r}")
        assert "**" not in p["solution"], f"bold marker inside: {p['solution'][:60]!r}"


def test_every_step_records_its_axis_and_index_in_provenance(steps):
    """Which axis section and which step within it. Without the index two steps
    of one axis are indistinguishable in the ledger."""
    for i, p in enumerate(steps):
        assert p.get("component") == EXPECTED[i][0]
        assert p.get("step_index") is not None, f"no step_index on {p.get('solution')[:40]!r}"
    idx = [(p["component"], p["step_index"]) for p in steps]
    assert idx == [("HUMAN", 1), ("HUMAN", 2), ("PLANET", 1), ("PLANET", 2),
                   ("CIVILIZATION", 1), ("CIVILIZATION", 2),
                   ("COSMOS", 1), ("COSMOS", 2)], idx


def test_an_objective_no_longer_wears_a_step_triple():
    """THE SECOND HALF OF THE DEFECT. The objective is not a step and must not
    inherit the numbers of the step that happened to follow it."""
    if not PLAN.is_file():
        pytest.skip("plan not on disk")
    proposals = parse_plan(PLAN.read_text(encoding="utf-8"), PLAN.name, "t")
    objectives = [p for p in proposals if "axis needs progress" in p.get("problem", "")]
    for o in objectives:
        assert not o.get("indicator"), (
            f"an OBJECTIVE is carrying {o.get('indicator')} / "
            f"{o.get('expected_delta')} — a triple it never had")


def test_the_step_pattern_allows_the_bold_marker_the_model_writes():
    """Pinning the actual cause, so a future rewrite cannot quietly reintroduce
    a pattern that only matches unformatted steps."""
    import agents.hyperclaw.hyperclaw_orchestrator as h
    src = Path(h.__file__).read_text(encoding="utf-8")
    m = re.search(r"_step_dash_re\s*=\s*_?re\.compile\(\s*r'([^']+)'", src)
    assert m, "could not find _step_dash_re"
    assert re.match(m.group(1), "- **STEP 1:** do the thing", re.IGNORECASE), (
        f"the step pattern {m.group(1)!r} still does not match a bold STEP line")
