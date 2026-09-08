#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_stale_input_is_named.py — A GATE SHUT BY AN OLD FILE MUST SAY WHICH.

THE DEFECT THIS GUARDS
-----------------------
core/notary._age_state() reduces the OLDEST declared input of a step to one
number, which then joins four others in own = min(...). One dead file can hold a
gate shut for months while reading, from outside, as ordinary caution.

It did. Measured on this repo, 2026-09-08:

    memory/self_awareness.json    last written 2026-03-11, 180.7 days
    NO WRITER ANYWHERE — grep over every .py found three readers and nothing
    that produces it; memory/existence_latest.json:17 still carries the scar
    that records its loss.
    with it     age = MINIMAL(1) -> own = 1 -> below IRREVERSIBLE_MIN(2)
    without it  age = FULL(3)

And what was read from it was never used: it went into `sa`, a parameter of
_build_context() with zero loads in the body. A file with no writer, whose
contents were discarded, was the entire age dimension of the step that modifies
this system.

THE FORBIDDEN FALLBACK
-----------------------
Do NOT touch the file to make it young, do NOT widen stale_days, and do NOT
declare a fresh file the step does not actually read. Any of those would be
faking provenance to lift a vector. What is done instead is the removal of a
declaration that was FALSE — the step no longer reads it, so it must no longer
claim to. test_the_fix_was_removal_not_a_fresh_timestamp and
test_the_thresholds_were_not_widened pin both.

    venv\\Scripts\\python.exe -m pytest test/test_stale_input_is_named.py -v
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import time

import pytest

from core import notary as N
from core import stale_inputs as SI

REPO = pathlib.Path(__file__).resolve().parents[1]
DEAD = "memory/self_awareness.json"


# ---------------------------------------------------------------------------
# (a) the dead declaration is gone, and gone for the right reason
# ---------------------------------------------------------------------------

def test_the_step_no_longer_declares_a_file_nothing_writes():
    declared, _src = N._inputs_for("self_modifier")
    assert DEAD not in declared, (
        f"{DEAD} is declared as an input of self_modifier again. Nothing in "
        f"this repo writes it; declaring it hands the age dimension to a file "
        f"that can only ever get older.")
    assert declared, "self_modifier now declares nothing, which reads as UNKNOWN"


def test_the_step_no_longer_reads_it_either():
    """The declaration and the code must agree. Removing the declaration while
    the code still read the file would be the same lie pointing the other way."""
    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "self_awareness.json", (
                "self_modifier.py still builds a path to self_awareness.json")


def test_the_parameter_that_discarded_it_is_gone():
    """`sa` was passed to _build_context and never read — 0 loads. A parameter
    that looks like an input and is not is how a dead file stayed declared."""
    tree = ast.parse((REPO / "agents" / "core" / "self_modifier.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_build_context")
    params = [a.arg for a in fn.args.args]
    assert "sa" not in params, "_build_context still takes the unused sa"
    for p in params:
        loads = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Name) and n.id == p
                 and isinstance(n.ctx, ast.Load)]
        assert loads, (
            f"_build_context still takes {p!r} and never reads it; an unused "
            f"parameter is what let a dead file look like an input")


# ---------------------------------------------------------------------------
# (b) THE FORBIDDEN FALLBACK
# ---------------------------------------------------------------------------

def test_the_fix_was_removal_not_a_fresh_timestamp():
    """The dead file must NOT have been touched. If it is young now, somebody
    lifted the vector by writing to it, which is faking provenance."""
    path = REPO / DEAD
    if not path.exists():
        return                      # deleting it is also an honest answer
    age_days = (time.time() - path.stat().st_mtime) / 86400.0
    assert age_days > 30, (
        f"{DEAD} is only {age_days:.1f} days old. Nothing in this repo writes "
        f"it, so a fresh mtime means somebody touched it to lift the age "
        f"dimension. That is faking provenance.")


def test_the_thresholds_were_not_widened():
    """Moving stale_days would lift every step at once and hide the problem
    instead of removing it."""
    from core.passage_rules import RULES
    assert RULES["stale_days"] == (2, 30, 365)
    assert N.IRREVERSIBLE_MIN == 2
    assert N.MAX_LEVEL.get("execute_patches") == N.MINIMAL, (
        "the ceiling moved; nothing in this commit may raise it")


def test_no_replacement_input_was_declared_that_the_step_does_not_read():
    """The live self-model is memory/self_profile.json. Declaring it WITHOUT
    wiring the read would be the same defect with a younger file."""
    declared, _ = N._inputs_for("self_modifier")
    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    for rel in declared:
        leaf = rel.split("/")[-1]
        assert leaf in src, (
            f"self_modifier declares {rel} but its source never names {leaf}; "
            f"a declared input the step does not read is provenance theatre")


# ---------------------------------------------------------------------------
# (c) THE NET — mutation: remove the flag and a stale input goes unnamed
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic(monkeypatch, tmp_path):
    """One ancient input, one fresh, one missing — built by hand.

    Not read off the live cycle: the live answer changes the moment a file is
    written, and a test that moves with the repo cannot pin a mechanism.
    """
    (tmp_path / "memory").mkdir()
    old = tmp_path / "memory" / "ancient.json"
    old.write_text("{}", encoding="utf-8")
    t = time.time() - 200 * 86400
    os.utime(old, (t, t))
    fresh = tmp_path / "memory" / "fresh.json"
    fresh.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(N, "BASE", tmp_path)
    monkeypatch.setattr(
        N, "_inputs_for",
        lambda step: (["memory/ancient.json", "memory/fresh.json",
                       "memory/absent.json"], "written")
        if step == "gated_step" else ([], "scanner"))
    return tmp_path


def test_an_ancient_input_is_found_and_named(synthetic):
    stale = SI.stale_inputs_for("gated_step")
    arts = {s["artifact"] for s in stale}
    assert "memory/ancient.json" in arts
    assert "memory/fresh.json" not in arts, "a fresh input was flagged"

    row = next(s for s in stale if s["artifact"] == "memory/ancient.json")
    assert row["age_days"] > 190
    assert row["missing"] is False

    text = SI.describe("gated_step", stale)
    assert "memory/ancient.json" in text, "the file is not named"
    assert "gated_step" in text, "the step is not named"


def test_a_missing_input_is_not_reported_as_merely_old(synthetic):
    """A missing input and an ancient one need different fixes; collapsing them
    into one number is how the second gets mistaken for the first."""
    stale = SI.stale_inputs_for("gated_step")
    row = next(s for s in stale if s["artifact"] == "memory/absent.json")
    assert row["missing"] is True
    assert row["age_days"] is SI.MISSING
    assert "MISSING" in SI.describe("gated_step", stale)


def test_MUTATION_the_flag_is_written_as_an_event_on_every_gate_crossing(
        synthetic, monkeypatch):
    """Delete the _flag_stale_inputs call from _witness_or_refuse, or its
    _gate_event write, and this goes red: a stale input would again exist only
    inside a refusal string, on the nights age happened to tie for the minimum."""
    import fast_cycle_runner as runner

    events = []
    monkeypatch.setattr(runner, "_gate_event",
                        lambda step, outcome, gate, why, extra=None:
                            events.append((step, outcome, gate, why, extra)))

    stale = runner._flag_stale_inputs("gated_step")
    assert stale, "the census found nothing where an ancient input exists"
    assert events, (
        "a stale input fed a gate and NOTHING was written; a file that decides "
        "whether this system may modify itself has to be countable")

    step, outcome, gate, why, extra = events[-1]
    assert step == "gated_step"
    assert gate == "stale_inputs"
    assert "memory/ancient.json" in why
    assert extra["stale_count"] == len(stale)


def test_the_census_failing_is_not_reported_as_a_clean_gate(monkeypatch):
    """SILENCE IS NOT SUCCESS."""
    import fast_cycle_runner as runner
    import core.stale_inputs as si

    monkeypatch.setattr(si, "stale_inputs_for",
                        lambda step, days=None: (_ for _ in ()).throw(
                            RuntimeError("notary unreadable")))
    events = []
    monkeypatch.setattr(runner, "_gate_event",
                        lambda step, outcome, gate, why, extra=None:
                            events.append((outcome, why)))
    assert runner._flag_stale_inputs("self_modifier") == []
    assert events and "NOT evidence" in events[-1][1]


def test_the_census_runs_before_any_decision_and_on_both_paths():
    """STRUCTURAL. A gate that OPENS on a half-year-old input is the more
    dangerous case, and it must be flagged too."""
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    gate = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_witness_or_refuse")
    calls = [n for n in ast.walk(gate)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_flag_stale_inputs"]
    assert calls, "_witness_or_refuse no longer takes the stale-input census"
    returns = [n.lineno for n in ast.walk(gate) if isinstance(n, ast.Return)]
    assert min(c.lineno for c in calls) < min(returns), (
        "the census runs after the gate can already have returned")

    net = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_flag_stale_inputs")
    named = {n.func.id for n in ast.walk(net)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_gate_event" in named, "the flag is printed but never recorded"


def test_the_threshold_comes_from_the_one_ruleset_not_a_second_number():
    """Inventing a second staleness threshold here is exactly the drift
    config/passage_rules.json exists to end."""
    from core.passage_rules import RULES
    assert SI._threshold_days() == float(RULES["stale_days"][1])

    tree = ast.parse((REPO / "core" / "stale_inputs.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_threshold_days")
    assert "stale_days" in ast.dump(fn), (
        "the threshold is no longer read from the ruleset")


def test_the_census_reads_the_notarys_own_input_lookup():
    """A second copy of _inputs_for would drift and start reporting a staleness
    the gate does not act on."""
    tree = ast.parse((REPO / "core" / "stale_inputs.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module == "core.notary"
                for a in n.names}
    assert "_inputs_for" in imported


# ---------------------------------------------------------------------------
# (d) what the removal actually bought — stated, not implied
# ---------------------------------------------------------------------------

def test_the_age_dimension_no_longer_binds_for_self_modifier():
    """The point of the whole commit. It does NOT mean the step now acts: level
    is min(own, inherited), and inherited still comes from producers that cannot
    say what they read."""
    declared, src = N._inputs_for("self_modifier")
    level, why = N._age_state(declared, src)
    assert level >= N.IRREVERSIBLE_MIN, why
    assert DEAD not in why


def test_execute_patches_is_still_capped_so_nothing_can_be_APPLIED():
    """The blast radius of this commit, pinned. self_modifier WRITES patches;
    execute_patches APPLIES them and stays capped below the line."""
    assert N.MAX_LEVEL["execute_patches"] == N.MINIMAL
    assert N.MINIMAL < N.IRREVERSIBLE_MIN


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
