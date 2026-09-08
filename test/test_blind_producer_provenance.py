#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_blind_producer_provenance.py

NO STEP FEEDS A DECISION BLIND.

THE MECHANISM, MEASURED BEFORE ANY OF THIS WAS CHANGED (2026-09-08)
--------------------------------------------------------------------
Provenance is stamped by core.notary.attest(), called from beat() through
memory/heartbeat.py:191 — NOT by _run()/blackbox, which is the crash-trace layer
and carries no level. hyperclaw_plan was therefore always attested (37 records;
2026-09-08T01:26:56 with products ["memory/improvement_proposals.json"]).

It stamped level_0 anyway, and the live record says exactly why:

    vector {witness:3, human:3, thought:3, age:0, promise:0}  own=0
    age     "no declared inputs - provenance unknown"
    promise "hyperclaw: НЕ ЗНАЕМ"

Two independent causes, neither of them a missing blackbox record:
  1. hyperclaw_plan was absent from config/step_inputs.json and the static
     scanner returns [] for it, so notary._age_state([]) fails closed to
     UNKNOWN(0) — "an empty list does not mean the step reads nothing, it means
     we do not know what it reads".
  2. its predecessor `hyperclaw` carried an EMPTY produces list in cycle_map, so
     cycle_map.kept_promise() answered "НЕ ЗНАЕМ" -> UNKNOWN(0).

self_modifier then inherited that 0 from memory/improvement_proposals.json.

THE FORBIDDEN FALLBACK
-----------------------
Do NOT hardcode a "trusted" or human provenance to force the gate open, and do
NOT raise MAX_LEVEL. A mechanism that grants itself trust is the K1 defect in its
purest form. The stamp must reflect the REAL producer, which means declaring what
the step really reads and what its predecessor really writes — and living with
the number that comes out. test_the_ceiling_and_the_trust_levels_were_not_touched
pins both.

AND IT DOES NOT OPEN THE GATE, WHICH IS THE POINT
--------------------------------------------------
self_modifier's own vector is {witness:3, human:3, thought:3, age:1, promise:1}.
age=1 because its oldest declared input, memory/self_awareness.json, is 180.7
days old. own=1 is already below IRREVERSIBLE_MIN(2), so level = min(own,
inherited) stays 1 and the step stays refused however clean its inputs' stamps
become. What changes is the REASON: from "blind step hyperclaw_plan" to the true
binding constraint. A gate that refuses for the right reason is the deliverable.

    venv\\Scripts\\python.exe -m pytest test/test_blind_producer_provenance.py -v
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import time

import pytest

from core import notary as N

REPO = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = "memory/improvement_proposals.json"
STEP = "hyperclaw_plan"


# ---------------------------------------------------------------------------
# (a) THE STAMP — mutation: remove the declaration and the origin is UNKNOWN
# ---------------------------------------------------------------------------

def test_the_declaration_is_written_by_a_human_not_produced_by_the_scanner():
    """config/step_inputs.json beats the scanner, and the source is reported so
    the gate can say what it trusted."""
    from core.declared_inputs import SOURCE_WRITTEN

    inputs, source = N._inputs_for(STEP)
    assert inputs, (
        f"{STEP} still declares no inputs; notary._age_state([]) fails closed to "
        f"UNKNOWN(0) and every irreversible step downstream inherits it")
    assert source == SOURCE_WRITTEN, (
        f"the list came from {source!r}, not from the written declaration")
    assert "plans" in inputs, "the plan it actually parses is not declared"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A repo-shaped tmp tree, so age is measured against files this test made.

    notary.BASE is module-level and every path is resolved through it, so
    redirecting it keeps the real repo out of the measurement entirely — the age
    of the live plans/ directory must not decide whether this test passes.
    """
    monkeypatch.setattr(N, "BASE", tmp_path)
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan-2026-09-08.md").write_text("x", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "improvement_proposals.json").write_text(
        "{}", encoding="utf-8")
    return tmp_path


def test_with_the_declaration_the_origin_is_KNOWN(sandbox):
    """>= MINIMAL, and for fresh inputs FULL. Never UNKNOWN."""
    inputs, source = N._inputs_for(STEP)
    level, why = N._age_state(inputs, source)
    assert level > N.UNKNOWN, (
        "\n  THE ORIGIN IS STILL UNKNOWN.\n"
        f"  {STEP} produces {ARTIFACT}, which gates self_modifier and\n"
        "  execute_patches. An UNKNOWN origin stamps level_0 on it and every\n"
        "  irreversible step downstream inherits that 0.\n"
        f"  age said: {why}\n")
    assert level >= N.MINIMAL
    assert level == N.FULL, why          # the sandbox files were made just now
    assert "no declared inputs" not in why


def test_MUTATION_removing_the_declaration_returns_the_origin_to_UNKNOWN(
        sandbox, monkeypatch):
    """THE MUTATION TEST. Delete the config/step_inputs.json entry — simulated
    here by making the written lookup answer None, which is exactly what
    _inputs_for sees when the entry is gone — and the step falls back to the
    static scanner, which returns [] for it, and the origin is UNKNOWN again.

    If this still reads KNOWN, the declaration is not what made the fix.
    """
    from core import declared_inputs

    monkeypatch.setattr(declared_inputs, "for_step", lambda step: None)
    inputs, source = N._inputs_for(STEP)
    assert inputs == [], (
        "the static scanner resolved inputs for this step after all; the "
        "declaration is not what supplies them")
    level, why = N._age_state(inputs, source)
    assert level == N.UNKNOWN
    assert "no declared inputs" in why


def test_the_predecessors_promise_is_no_longer_НЕ_ЗНАЕМ(monkeypatch, tmp_path):
    """The second cause. cycle_map.kept_promise() answers 'НЕ ЗНАЕМ' -> UNKNOWN
    for any step with an empty produces list, and `hyperclaw` had one."""
    import core.cycle_map as cm

    assert cm.produces("hyperclaw"), (
        "hyperclaw still promises nothing, so kept_promise() returns 'НЕ ЗНАЕМ' "
        "and the promise dimension of hyperclaw_plan stays UNKNOWN(0)")

    monkeypatch.setattr(cm, "BASE", tmp_path)
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "plan-2026-09-08.md").write_text("x", encoding="utf-8")
    verdict, detail = cm.kept_promise("hyperclaw", time.time() - 60)
    assert verdict == "ОБНОВИ", (verdict, detail)


def test_the_declared_product_is_the_one_the_code_unconditionally_writes():
    """agents/hyperclaw/hyperclaw_orchestrator.py writes plans/plan-<today>.md at
    the end of main(). The snapshot it writes at line ~335 is on the
    AllBackendsFailedError path ONLY, so promising it would mark a healthy night
    as a broken promise. Asserted against the code, not a comment."""
    src = (REPO / "agents" / "hyperclaw" / "hyperclaw_orchestrator.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    assert any(isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "PLAN_DIR"
               for n in tree.body), "PLAN_DIR is gone; the declaration is stale"

    import core.cycle_map as cm
    assert cm.produces("hyperclaw") == ["plans"]
    assert "hyperclaw_snapshot_latest.json" not in cm.produces("hyperclaw")


# ---------------------------------------------------------------------------
# (b) THE NET — mutation: remove the flag and a blind producer goes unnamed
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_blind(monkeypatch):
    """One blind producer and one that declares, built by hand.

    Not read off the live cycle: the live answer changes the moment somebody
    declares another step, and a test that moves with the repo cannot pin a
    mechanism.
    """
    def fake_inputs_for(step):
        return {"gated_step": (["memory/thing.json"], "written"),
                "declaring_producer": (["memory/other.json"], "written"),
                "blind_producer": ([], "scanner")}.get(step, ([], "scanner"))

    def fake_producers_of(artifact):
        return ["blind_producer", "declaring_producer"] \
            if artifact == "memory/thing.json" else []

    monkeypatch.setattr(N, "_inputs_for", fake_inputs_for)
    monkeypatch.setattr(N, "_producers_of", fake_producers_of)


def test_a_blind_producer_feeding_a_gate_is_found_and_named(synthetic_blind):
    from core.blind_producers import blind_producers_for, describe

    blind = blind_producers_for("gated_step")
    assert blind == [{"artifact": "memory/thing.json",
                      "producer": "blind_producer"}], blind

    text = describe("gated_step", blind)
    assert "blind_producer" in text, "the step is not named"
    assert "memory/thing.json" in text, "the artifact is not named"
    assert "config/step_inputs.json" in text, "the fix is not named"


def test_a_producer_that_declares_its_inputs_is_not_flagged(synthetic_blind):
    """THE NEGATIVE CONTROL. Flag everything and the flag means nothing."""
    from core.blind_producers import blind_producers_for

    assert all(b["producer"] != "declaring_producer"
               for b in blind_producers_for("gated_step"))


def test_MUTATION_the_flag_is_written_as_an_event_on_every_gate_crossing(
        synthetic_blind, monkeypatch):
    """Delete the _flag_blind_producers call from _witness_or_refuse, or its
    _gate_event write, and this goes red: a blind producer feeding a gate would
    again exist only inside a refusal sentence, on the nights the gate happened
    to refuse for that reason."""
    import fast_cycle_runner as runner

    events = []
    monkeypatch.setattr(runner, "_gate_event",
                        lambda step, outcome, gate, why, extra=None:
                            events.append((step, outcome, gate, why, extra)))

    blind = runner._flag_blind_producers("gated_step")
    assert blind, "the census found nothing where a blind producer exists"
    assert events, (
        "a blind producer fed a gate and NOTHING was written; the fact would "
        "again live only in a refusal string")

    step, outcome, gate, why, extra = events[-1]
    assert step == "gated_step"
    assert gate == "blind_producers"
    assert "blind_producer" in why and "memory/thing.json" in why
    assert extra["blind_count"] == 1
    assert extra["blind_producers"][0]["producer"] == "blind_producer"


def test_the_census_failing_is_not_reported_as_a_clean_gate(monkeypatch):
    """SILENCE IS NOT SUCCESS. If the census cannot run, that must be written as
    its own outcome — never as an empty result that reads like 'no blind
    producers here'."""
    import fast_cycle_runner as runner
    import core.blind_producers as bp

    def _boom(step):
        raise RuntimeError("cycle_map unreadable")

    monkeypatch.setattr(bp, "blind_producers_for", _boom)
    events = []
    monkeypatch.setattr(runner, "_gate_event",
                        lambda step, outcome, gate, why, extra=None:
                            events.append((outcome, why)))

    assert runner._flag_blind_producers("self_modifier") == []
    assert events, "the census failed and wrote nothing"
    outcome, why = events[-1]
    assert "NOT evidence" in why, why


def test_the_census_runs_before_any_decision_and_on_both_paths():
    """STRUCTURAL, on the AST. _flag_blind_producers must be called inside
    _witness_or_refuse BEFORE the first return — so a gate that OPENS while
    standing on unknown provenance is flagged too, which is the more dangerous
    of the two cases and the one that used to print nothing."""
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    gate = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_witness_or_refuse")

    calls = [n for n in ast.walk(gate)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_flag_blind_producers"]
    assert calls, "_witness_or_refuse no longer takes the census"

    returns = [n.lineno for n in ast.walk(gate) if isinstance(n, ast.Return)]
    assert min(c.lineno for c in calls) < min(returns), (
        "the census runs after the gate can already have returned; a refusal on "
        "the human channel would skip it entirely")

    net = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_flag_blind_producers")
    named = {n.func.id for n in ast.walk(net)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_gate_event" in named, "the flag is printed but never recorded"


def test_the_census_reads_the_notarys_own_lookups_not_a_second_copy():
    """A reimplemented lookup drifts from the gate's and starts reporting a
    blindness the notary does not act on."""
    tree = ast.parse((REPO / "core" / "blind_producers.py").read_text(encoding="utf-8"))
    imported = {alias.name for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module == "core.notary"
                for alias in n.names}
    assert {"_inputs_for", "_producers_of"} <= imported, (
        "core/blind_producers.py no longer imports the notary's lookups; it is "
        "now measuring something the gate does not use")


# ---------------------------------------------------------------------------
# (c) THE FORBIDDEN FALLBACK
# ---------------------------------------------------------------------------

def test_the_ceiling_and_the_trust_levels_were_not_touched():
    """Forcing the gate open is the failure this whole mechanism exists to
    prevent. execute_patches stays capped; AMENDMENT_001 keeps its cooling-off."""
    assert N.MAX_LEVEL.get("execute_patches") == N.MINIMAL, (
        "the ceiling on execute_patches moved — raising it is AMENDMENT_001's "
        "business, not a side effect of a provenance fix")
    assert N.IRREVERSIBLE_MIN == N.REDUCED
    src = (REPO / "core" / "notary.py").read_text(encoding="utf-8")
    assert "cooling-off ends 19 Oct 2026" in src


def test_the_declaration_carries_no_trust_level_of_its_own():
    """config/step_inputs.json says what a step READS. If it ever grows a field
    that says how much to trust it, the gate stops measuring and starts being
    told — which is a mechanism granting itself trust."""
    doc = json.loads((REPO / "config" / "step_inputs.json").read_text(encoding="utf-8"))
    banned = {"level", "trust", "trusted", "provenance", "human_verified",
              "override", "min_level"}
    for step, entry in doc["steps"].items():
        bad = banned & set(entry)
        assert not bad, f"{step} declares a trust field: {bad}"


def test_the_verifiers_list_did_not_grow():
    """VERIFIERS may BREAK inherited level. Adding a step there is a way to buy
    trust without earning it, so the list is pinned to what it was."""
    assert N.VERIFIERS == {"global_indicators", "sensorium_ingest",
                           "browser_scout", "internet_intelligence",
                           "web_intelligence"}


# ---------------------------------------------------------------------------
# (c) THE PATH TO PASS — the gate is not crippled
# ---------------------------------------------------------------------------
# A gate that can only ever refuse is not a gate, it is a wall, and nobody can
# tell the two apart by watching it refuse. These tests assert the opposite
# property from everything above: that a well-formed, stamped input DOES reach
# the far side of the provenance layer. If the provenance path regresses, these
# go red before anyone has to notice a wall by its silence.


def test_PATH_TO_PASS_a_stamped_step_clears_the_provenance_dimensions(
        sandbox, monkeypatch):
    """The two dimensions provenance actually controls — age and promise — both
    reach FULL for hyperclaw_plan once its inputs are declared and its
    predecessor has kept its promise this cycle.

    That is the whole provenance contract: nothing in age or promise refuses a
    step whose inputs are known and fresh. The other three (witness, human,
    thought) are environmental — MeTTa up, the human channel alive, a route to
    thought — and are not what this commit touched.
    """
    import core.cycle_map as cm

    monkeypatch.setattr(cm, "BASE", sandbox)

    inputs, source = N._inputs_for(STEP)
    age, age_why = N._age_state(inputs, source)
    promise, promise_why = N._promise_state("hyperclaw", STEP)

    assert age >= N.IRREVERSIBLE_MIN, (
        "\n  THE PROVENANCE PATH IS SHUT.\n"
        "  A step with declared, freshly-written inputs still cannot clear the\n"
        "  age dimension, so no proposal can ever reach quality measurement no\n"
        "  matter how well formed it is. That is a wall, not a gate.\n"
        f"  age said: {age_why}\n")
    assert promise >= N.IRREVERSIBLE_MIN, (
        "a predecessor that kept its promise this cycle still does not clear "
        f"the promise dimension: {promise_why}")
    assert min(age, promise) >= N.IRREVERSIBLE_MIN


def test_PATH_TO_PASS_the_gate_opens_when_the_vector_is_clean(monkeypatch):
    """may_act() must be able to return True. Proven on the DECISION, with a
    synthetic all-FULL attestation, so the assertion is about the rule and not
    about tonight's weather.

    attest() is monkeypatched rather than called: the real one APPENDS to the
    hash-chained attestation log, and a test must never write a stamp into the
    chain the supervisor verifies.
    """
    clean = {"level": N.FULL, "level_name": N.LEVEL_NAMES[N.FULL],
             "own": N.FULL, "inherited": N.FULL, "inherited_from": None,
             "vector": {"witness": N.FULL, "human": N.FULL, "thought": N.FULL,
                        "age": N.FULL, "promise": N.FULL},
             "why": {"witness": "w", "human": "h", "thought": "t",
                     "age": "fresh", "promise": "kept"},
             "ceiling": None, "capped": False, "ceiling_binds": False}
    monkeypatch.setattr(N, "attest", lambda step, prev=None: dict(clean))

    ok, why = N.may_act("hyperclaw_plan", "hyperclaw")
    assert ok is True, (
        "\n  THE GATE CANNOT OPEN.\n"
        "  Every dimension is FULL, no ceiling binds, and may_act still refuses.\n"
        "  There would be no path to pass for any actor, however well formed its\n"
        f"  work: {why}\n")
    assert "level_3" in why, why


def test_PATH_TO_PASS_the_refusal_names_a_rule_that_can_be_satisfied(monkeypatch):
    """A refusal must point at something an actor can DO. The age dimension is
    the one this commit put in reach: declare your inputs, keep them fresh."""
    blind = {"level": N.UNKNOWN, "level_name": N.LEVEL_NAMES[N.UNKNOWN],
             "own": N.UNKNOWN, "inherited": N.FULL, "inherited_from": None,
             "vector": {"witness": N.FULL, "human": N.FULL, "thought": N.FULL,
                        "age": N.UNKNOWN, "promise": N.FULL},
             "why": {"witness": "w", "human": "h", "thought": "t",
                     "age": "no declared inputs - provenance unknown",
                     "promise": "kept"},
             "ceiling": None, "capped": False, "ceiling_binds": False}
    monkeypatch.setattr(N, "attest", lambda step, prev=None: dict(blind))

    ok, why = N.may_act("hyperclaw_plan", "hyperclaw")
    assert ok is False
    assert "no declared inputs" in why, (
        "the refusal does not name the rule that was broken, so nothing tells "
        f"the actor what to fix: {why}")


def test_the_step_now_has_a_crash_trace_as_well_as_a_stamp():
    """STRUCTURAL. hyperclaw_plan called _hyperclaw_to_proposals() directly, so
    it was one of the steps core/blackbox.py names as a known blind spot: a hard
    kill inside it left no begin/end record and no failure reached
    phase_tracker.note_failure().

    Separate from the stamp, and deliberately so — the docstring in the runner
    says which layer does which, because conflating them is how a fix gets
    applied to the wrong one.
    """
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_run"
             and n.args and isinstance(n.args[0], ast.Constant)
             and n.args[0].value == "hyperclaw_plan"]
    assert calls, (
        "hyperclaw_plan no longer goes through _run(); it has no blackbox "
        "begin/end record and its failures never reach the phase report")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
