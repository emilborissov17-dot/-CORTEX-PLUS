# -*- coding: utf-8 -*-
"""
Last night's refusals go back into tonight's prompt — labelled as what they are.
Step 4 of the gate loop, 6 Sep 2026.

WHAT THIS IS, AND WHAT IT IS NOT. Showing a generator the reasons its own
proposals were refused is a HUMAN tightening a prompt by hand between runs. No
weight changes. Nothing is retained. The next model instance starts blank and is
handed the text again. It is prompt refinement, and the section says so in its
own header, because calling it learning would be the same overclaim the rest of
this repo has spent the week unpicking — and because a reader who believes the
system is learning will stop tightening the prompt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import gate_contract as gc          # noqa: E402

ROW = {"ts": "2026-09-06T01:35:34+00:00", "source": "hyperclaw_to_proposals",
       "component": "COSMOS", "solution": "do a thing",
       "missing": ["indicator"], "why": "indicator 'X' does not resolve today"}


def _file(tmp_path, rows):
    p = tmp_path / "refusals.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                 encoding="utf-8")
    return p


# ── present: the section appears, with its lines ────────────────────────────

def test_the_section_appears_with_its_lines(tmp_path):
    block = gc.refusals_block(_file(tmp_path, [ROW]))
    assert gc.REFUSALS_HEADER in block
    assert "hyperclaw_to_proposals" in block
    assert "indicator" in block
    assert "does not resolve today" in block


def test_the_header_says_this_is_not_learning(tmp_path):
    """The label is the point. A reader who believes the machine is learning
    from these will stop tightening the prompt by hand."""
    block = gc.refusals_block(_file(tmp_path, [ROW]))
    head = block.splitlines()[0]
    assert "prompt refinement" in head
    assert "not learning" in head


def test_each_line_names_source_missing_fields_and_why(tmp_path):
    line = gc.refusals_block(_file(tmp_path, [ROW])).splitlines()[1]
    assert line.strip().startswith("hyperclaw_to_proposals:")
    assert "missing [indicator]" in line
    assert "does not resolve today" in line


def test_at_most_ten_lines(tmp_path):
    rows = [{**ROW, "component": f"C{i}"} for i in range(25)]
    body = [l for l in gc.refusals_block(_file(tmp_path, rows)).splitlines()
            if l.startswith("  ")]
    assert len(body) == 10, len(body)


def test_the_ten_shown_are_the_MOST_RECENT(tmp_path):
    rows = [{**ROW, "why": f"reason {i}"} for i in range(25)]
    block = gc.refusals_block(_file(tmp_path, rows))
    assert "reason 24" in block, "the newest refusal is not shown"
    assert "reason 0" not in block, "an old refusal crowded out a new one"


# ── absent: no section, no crash, no invented 'none' ────────────────────────

def test_an_absent_file_yields_no_section_and_does_not_crash(tmp_path):
    assert gc.refusals_block(tmp_path / "nothing.jsonl") == ""


def test_an_empty_file_yields_no_section(tmp_path):
    assert gc.refusals_block(_file(tmp_path, [])) == ""


def test_an_absent_file_does_not_put_a_placeholder_in_the_contract(tmp_path):
    """A section saying "none refused" when the file is merely missing asserts
    something nobody measured."""
    block = gc.contract_block({"WATER_REVIEW": 73.6},
                              refusals=tmp_path / "nothing.jsonl")
    assert gc.REFUSALS_HEADER not in block
    assert "none refused" not in block.lower()


def test_a_malformed_line_is_skipped_not_fatal(tmp_path):
    p = tmp_path / "r.jsonl"
    p.write_text(json.dumps(ROW) + "\n{ this is not json\n"
                 + json.dumps({**ROW, "why": "second"}) + "\n", encoding="utf-8")
    block = gc.refusals_block(p)
    assert "second" in block


# ── it reaches the real contract, and therefore every generator ─────────────

def test_the_contract_block_carries_the_section_when_the_file_exists(tmp_path):
    block = gc.contract_block({"WATER_REVIEW": 73.6},
                              refusals=_file(tmp_path, [ROW]))
    assert gc.REFUSALS_HEADER in block
    assert "CORTEX++ CAN:" in block          # and the rest of the contract survives
    assert "GRADEABLE INDICATORS" in block


def test_tonights_real_refusals_render(tmp_path):
    """Not a fixture: the file the 6 Sep cycle actually wrote."""
    live = gc.REFUSALS_PATH
    if not live.is_file():
        pytest.skip("no refusals recorded yet")
    block = gc.refusals_block()
    assert gc.REFUSALS_HEADER in block
    assert len([l for l in block.splitlines() if l.startswith("  ")]) <= 10
