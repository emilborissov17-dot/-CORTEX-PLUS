#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_declared_provenance.py — THE NOTARY REFUSED FOR IGNORANCE, NOT FOR FAULT.

WHAT WAS WRONG
---------------
core/notary.py grades each step on the age of its inputs. It gets that list
from the static scanner, which reads literal paths out of the step's region and
one layer of imports. For self_modifier and execute_patches the scanner
returned [] — and [] means UNKNOWN, so the gate refused. Not because anything
was stale, but because nothing had said what the steps read.

Both are now declared in config/step_inputs.json, line by line out of the
source:

    self_modifier    improvement_proposals, development_journal,
                     auto_levels, self_awareness          (4 required)
    execute_patches  development_journal                  (1 required)

THE PHANTOM
------------
The scanner and core/metta_check._IGNORE both name memory/last_attempt.txt.
NOTHING WRITES IT. There is no such file, and the only producer-shaped
reference in the repo is fast_cycle_runner's LAST_ATTEMPT, which points at
memory/last_attempted_cycle_id.txt — a different name. So it is not declared:
declaring a phantom as required would make the notary refuse forever on a file
that can never arrive, and declaring it optional would enshrine a typo.

THE NEGATIVE CONTROL
---------------------
test_a_declared_input_that_is_missing_still_refuses points a declaration at a
file that does not exist. If the gate passes that, the declarations have not
made it smarter, they have blindfolded it.

    venv\\Scripts\\python.exe -m pytest test/test_declared_provenance.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import notary
from core.declared_inputs import for_step

REPO = pathlib.Path(__file__).resolve().parents[1]
DECLARATIONS = REPO / "config" / "step_inputs.json"

DECLARED_NOW = ("github_publish", "self_modifier", "execute_patches")


def _decl() -> dict:
    return json.loads(DECLARATIONS.read_text(encoding="utf-8"))["steps"]


# ---------------------------------------------------------------------------
# (a) The two steps now have provenance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", ["self_modifier", "execute_patches"])
def test_the_step_is_declared(step):
    assert step in _decl(), f"{step} has no declaration"
    assert for_step(step), f"{step} declares an empty input list"


@pytest.mark.parametrize("step", ["self_modifier", "execute_patches"])
def test_the_notary_no_longer_refuses_for_ignorance(step):
    inputs, source = notary._inputs_for(step)
    state, why = notary._age_state(inputs, source)

    assert inputs, f"{step} still resolves to no inputs"
    assert state != 0, (
        f"\n  THE NOTARY STILL DOES NOT KNOW WHAT {step} READS.\n"
        f"  state=0 is UNKNOWN — the gate refusing because nobody said, not\n"
        f"  because anything is wrong. why: {why}\n"
    )
    assert "no declared inputs" not in why


@pytest.mark.parametrize("step", ["self_modifier", "execute_patches"])
def test_the_declaration_is_the_source_the_notary_used(step):
    """A declaration nobody reads is a comment."""
    from core.declared_inputs import SOURCE_WRITTEN
    _, source = notary._inputs_for(step)
    assert source == SOURCE_WRITTEN


@pytest.mark.parametrize("step", ["self_modifier", "execute_patches"])
def test_every_required_input_exists_on_disk(step):
    """A required input that is absent must be a real finding, not a typo of
    mine. This is what makes the negative control below meaningful."""
    missing = [f for f in for_step(step) if not (REPO / f).exists()]
    assert not missing, f"{step} declares files that are not there: {missing}"


# ---------------------------------------------------------------------------
# (b) THE NEGATIVE CONTROL
# ---------------------------------------------------------------------------

def test_a_declared_input_that_is_missing_still_refuses(monkeypatch):
    """Declaring inputs must not become a way of silencing the gate."""
    from core.declared_inputs import SOURCE_WRITTEN

    monkeypatch.setattr(notary, "_inputs_for",
                        lambda step: (["memory/this_file_does_not_exist.json"],
                                      SOURCE_WRITTEN))
    inputs, source = notary._inputs_for("self_modifier")
    state, why = notary._age_state(inputs, source)

    assert state == 0, (
        f"\n  A REQUIRED INPUT IS ABSENT AND THE GATE PASSED IT.\n"
        f"  state={state}, why={why}\n"
        f"  Declarations are supposed to tell the notary WHAT to check, not to\n"
        f"  excuse it from checking.\n"
    )


def test_a_partially_missing_declaration_still_refuses(monkeypatch):
    """Three real files and one absent one is still a broken contract."""
    from core.declared_inputs import SOURCE_WRITTEN
    monkeypatch.setattr(notary, "_inputs_for", lambda step: (
        ["memory/auto_levels.json", "memory/gone.json"], SOURCE_WRITTEN))
    state, _ = notary._age_state(*notary._inputs_for("self_modifier"))
    assert state == 0


# ---------------------------------------------------------------------------
# (c) The phantom stays undeclared
# ---------------------------------------------------------------------------

def test_the_phantom_input_is_not_declared():
    """memory/last_attempt.txt is named by the scanner and by metta_check's
    ignore list, and written by nothing."""
    assert not (REPO / "memory" / "last_attempt.txt").exists(), (
        "the phantom now exists — if something started writing it, declare it"
    )
    for step in DECLARED_NOW:
        assert "memory/last_attempt.txt" not in (for_step(step) or []), (
            f"{step} declares a file nothing produces; the notary would refuse "
            f"forever on an input that can never arrive"
        )


def test_the_phantom_is_explained_where_someone_will_look():
    """A reader who greps last_attempt.txt must find the answer, not a silence."""
    note = _decl()["execute_patches"].get("_the_phantom_input", "")
    assert "last_attempt.txt" in note
    assert "NOTHING WRITES IT" in note


# ---------------------------------------------------------------------------
# (d) Optional inputs are separated from required ones
# ---------------------------------------------------------------------------

def test_a_conditional_read_is_not_a_required_input():
    """self_modifier reads web_intelligence/latest.json inside a branch. Its
    age must not gate a step that runs fine without it."""
    decl = _decl()["self_modifier"]
    assert "memory/web_intelligence/latest.json" in decl["also_reads"]
    assert "memory/web_intelligence/latest.json" not in decl["inputs"]
    assert "_also_reads_why" in decl


def test_the_patch_glob_is_not_a_required_input():
    """An empty patches/ is the normal state and must not read as a missing
    dependency."""
    decl = _decl()["execute_patches"]
    assert any("patches" in a for a in decl["also_reads"])
    assert not any("patches" in i for i in decl["inputs"])


# ---------------------------------------------------------------------------
# (e) Every declaration says where it came from
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step", DECLARED_NOW)
def test_each_declaration_carries_its_entry_point_and_reasons(step):
    decl = _decl()[step]
    assert decl.get("entry_point"), f"{step} does not say what actually runs"
    for f in decl["inputs"]:
        assert f in decl.get("_inputs_why", {}), (
            f"{step} declares {f} without saying which line reads it"
        )


def test_a_step_nobody_declared_is_untouched():
    """The asymmetry is the whole guarantee: the file speaks only for the steps
    it names."""
    inputs, source = notary._inputs_for("scoring_engine")
    from core.declared_inputs import SOURCE_WRITTEN
    assert source != SOURCE_WRITTEN
    assert for_step("scoring_engine") is None
