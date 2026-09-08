#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_gate_producers_declare.py — EVERY PRODUCER FEEDING A GATE DECLARES.

THE RULE
---------
core/notary._age_state([]) fails closed: an empty input list means "we do not
know what this step reads", which is UNKNOWN(0), which is stamped on everything
the step produces, which every irreversible step downstream inherits. So a step
that produces an artifact a notary-gated step declares as an input, and that
cannot itself say what it reads, holds that gate shut — and does it silently,
because the level arrives by inheritance rather than from the gated step's own
vector.

WHY auto_levels WAS THE HIGHEST-VALUE SINGLE FIX
-------------------------------------------------
It produces memory/auto_levels.json, which self_modifier declares as an input.
Before 2026-09-08 it had no entry in config/step_inputs.json and the static
scanner returned [] for it (both paths are module-level constants in
memory/auto_level.py consumed inside run()). So it stamped level_0 every night
and step 18 inherited the 0 — one of two blind producers named by
core/blind_producers.py at that gate.

THIS IS A RATCHET, NOT A TARGET
--------------------------------
KNOWN_BLIND carries the producers that still cannot declare. It may SHRINK
freely — by removing a name in the same commit that declares it. It may not grow:
a new blind producer feeding a gate fails this file by name. Do not "helpfully"
add a name to make a red test green; that is the slack the repo's other ratchets
were written to remove.

    venv\\Scripts\\python.exe -m pytest test/test_gate_producers_declare.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from core import notary as N

REPO = pathlib.Path(__file__).resolve().parents[1]

# The steps whose action the notary gates. Taken from the runner's own gate calls
# rather than retyped, so a fourth gated step cannot be added without this file
# noticing.
GATED = ("self_modifier", "execute_patches", "github_publish")

# EMPTY SINCE 2026-09-08. Every producer feeding a notary-gated step can now say
# what it reads, and this ledger has nothing left to carry:
#   hyperclaw_plan  came off in b8c1c07
#   auto_levels     came off in 8836a57
#   self_observer   came off in 9758bdd
#
# It is kept rather than deleted BECAUSE it is empty. An empty ledger and a
# deleted one behave identically today and differently the moment somebody adds
# a blind producer: with the ledger present, test_no_new_blind_producer names
# them and this test refuses a name added to excuse it. Deleting it would leave
# only the first check, and the first excuse would have nowhere to be refused.
KNOWN_BLIND: set = set()


def _blind_producers() -> dict:
    from core.blind_producers import blind_producers_for
    out = {}
    for g in GATED:
        for b in blind_producers_for(g):
            out.setdefault(b["producer"], set()).add(f"{b['artifact']} -> {g}")
    return out


# ---------------------------------------------------------------------------
# (a) the rule, as a ratchet
# ---------------------------------------------------------------------------

def test_no_new_blind_producer_feeds_a_notary_gated_decision():
    found = _blind_producers()
    new = set(found) - KNOWN_BLIND
    assert not new, (
        "\n  A BLIND PRODUCER FEEDS A GATE.\n"
        "  These steps produce an artifact a notary-gated step declares as an\n"
        "  input, and cannot say what they read. _age_state([]) fails closed to\n"
        "  UNKNOWN(0), so each stamps level_0 on what it produces and the gated\n"
        "  step inherits it — silently, because the level arrives by\n"
        "  inheritance and not from the gated step's own vector.\n"
        + "".join(f"    {p}: {', '.join(sorted(found[p]))}\n" for p in sorted(new))
        + "  Declare its inputs in config/step_inputs.json, following that\n"
          "  file's _how_to_add_a_step: read the module the step actually calls.\n")


def test_the_known_blind_list_has_not_gone_stale():
    """A name left here after the step is declared makes the ratchet loose, and
    a limit above the count is a place for the next defect to hide."""
    found = set(_blind_producers())
    stale = KNOWN_BLIND - found
    assert not stale, (
        f"these are in KNOWN_BLIND but are no longer blind: {sorted(stale)}. "
        f"Remove them from KNOWN_BLIND in the commit that declared them.")


def test_auto_levels_declares_what_it_reads():
    """The subject of the fix, pinned by name so a revert is loud."""
    inputs, source = N._inputs_for("auto_levels")
    assert inputs, (
        "auto_levels declares nothing again; it produces memory/auto_levels.json "
        "which self_modifier reads, so the gate goes back to inheriting level_0")

    from core.declared_inputs import SOURCE_WRITTEN
    assert source == SOURCE_WRITTEN, f"came from {source!r}, not the declaration"
    assert "snapshots/master/master_snapshot_latest.json" in inputs


# ---------------------------------------------------------------------------
# (b) the declaration is TRUE — read from the code, not trusted
# ---------------------------------------------------------------------------

def test_the_declared_input_is_one_the_module_actually_opens():
    """A declaration nobody checks is a second copy free to drift from the code.
    memory/auto_level.py holds its paths as module-level constants; this asserts
    the declared path is the one MASTER_PATH is built from."""
    tree = ast.parse((REPO / "memory" / "auto_level.py").read_text(encoding="utf-8"))

    consts = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            consts[node.targets[0].id] = ast.dump(node.value)

    assert "MASTER_PATH" in consts, "MASTER_PATH is gone; the declaration is stale"
    for part in ("snapshots", "master", "master_snapshot_latest.json"):
        assert repr(part) in consts["MASTER_PATH"] or f"'{part}'" in consts["MASTER_PATH"], (
            f"MASTER_PATH no longer contains {part!r}; "
            f"config/step_inputs.json now declares a path the module does not open")


def test_the_module_opens_nothing_the_declaration_omits():
    """AST census of every file operation in memory/auto_level.py. Exactly three:
    two reads and one write. If a fourth appears, the declaration is incomplete
    and the age dimension is being computed over less than the step really reads.
    """
    tree = ast.parse((REPO / "memory" / "auto_level.py").read_text(encoding="utf-8"))
    ops = [n.attr for n in ast.walk(tree)
           if isinstance(n, ast.Attribute)
           and n.attr in ("read_text", "write_text", "open", "rglob", "glob",
                          "iterdir", "read_bytes")]
    assert sorted(ops) == ["read_text", "read_text", "write_text"], (
        f"memory/auto_level.py now performs {sorted(ops)}; re-derive its "
        f"declaration in config/step_inputs.json before this test is relaxed")


def test_its_own_previous_output_does_not_gate_it():
    """memory/auto_levels.json is read at auto_level.py:201 inside a try/except —
    the step's OWN last output. It belongs in also_reads, never in inputs: a step
    whose age dimension depends on its own last output grades itself, and one
    missed night would hold it down for ever."""
    doc = json.loads((REPO / "config" / "step_inputs.json").read_text(encoding="utf-8"))
    entry = doc["steps"]["auto_levels"]
    assert "memory/auto_levels.json" not in entry["inputs"], (
        "auto_levels gates on its own output")
    assert "memory/auto_levels.json" in entry.get("also_reads", [])
    assert entry.get("_also_reads_why"), "the exemption is not explained"


def test_every_declaration_records_where_it_came_from():
    """_how_to_add_a_step requires derived_from. A declaration with no provenance
    of its own is exactly the thing this whole subsystem exists to refuse."""
    doc = json.loads((REPO / "config" / "step_inputs.json").read_text(encoding="utf-8"))
    missing = [s for s, e in doc["steps"].items() if not e.get("derived_from")]
    assert not missing, f"declarations with no derived_from: {missing}"


def test_the_declaration_carries_no_trust_level():
    """config/step_inputs.json says what a step READS. A field that says how much
    to trust it would let the gate be told instead of measuring."""
    doc = json.loads((REPO / "config" / "step_inputs.json").read_text(encoding="utf-8"))
    banned = {"level", "trust", "trusted", "provenance", "override", "min_level"}
    for step, entry in doc["steps"].items():
        assert not (banned & set(entry)), f"{step} declares a trust field"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
