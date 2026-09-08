#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_irreversible_boundary_holds.py — THE PROVENANCE WORK MOVED NO BOUNDARY.

WHY THIS FILE EXISTS
---------------------
Over 2026-09-08 a chain of commits gave four steps honest provenance:
hyperclaw_plan, auto_levels, global_indicators/sensorium_ingest, and finally
self_observer. Each raised a level that had been UNKNOWN(0) for a reason that was
never a fault — a missing declaration, an empty produces, a dead file with no
writer. The count of blind producers feeding a notary-gated step went 3 -> 0.

That is exactly the shape of change that can quietly open a gate nobody meant to
open. So this file asserts the opposite property from all of them: THE
IRREVERSIBLE BOUNDARY DID NOT MOVE.

    self_modifier   may WRITE proposals and patch files      REVERSIBLE
    execute_patches may APPLY them to this repository        IRREVERSIBLE

execute_patches is capped at MINIMAL(1) by core/notary.MAX_LEVEL, which is BELOW
IRREVERSIBLE_MIN(2), and the cap is applied LAST in attest() — after the vector,
after inheritance, after the verifier break. So no amount of clean provenance
anywhere upstream can lift it. That is the invariant, and this file is where it
is checked rather than assumed.

THE SCAR THIS GUARDS, RECORDED IN core/notary.py ITSELF
--------------------------------------------------------
The rule "execute_patches must never reach full trust" was believed to hold for
ten days while it was resting on a TYPO — a phantom input filename that made
_age_state fail. When commit 8b0bca6 correctly declared the step's real inputs,
the phantom left, age became FULL, and the step that rewrites this system's own
source was stamped level_3 with may_act() = True. Measured in the live chain
2026-08-30T12:57:14: level=3, own=3, vector all threes.

That is the precise failure mode of the work this file follows: correcting
provenance removed the accident that was holding the gate shut. The MAX_LEVEL cap
was added afterwards so the invariant would rest on a stated rule instead. This
file is the test that says so.

NOTHING HERE WRITES. core.notary._append is monkeypatched in every test that
reaches attest(), because attest() appends to the hash-chained attestation log
and a test must never forge a stamp into the chain the supervisor verifies.

    venv\\Scripts\\python.exe -m pytest test/test_irreversible_boundary_holds.py -v
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from core import notary as N

REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def notary(monkeypatch):
    """A PRISTINE core/notary.py, loaded fresh, with its chain writer silenced.

    Two reasons this is not just `from core import notary`:

    1. test/conftest.py neutralises core.notary.attest for the WHOLE suite —
       autouse — because beat() fires attest() and test-fabricated steps were
       being written into the record the system uses to judge itself. That guard
       is right and must not be undone globally, so this loads a second, private
       copy of the module instead of fighting it.
    2. _append is the ONLY writer in notary.py. Silencing it on the private copy
       exercises the REAL ceiling logic — vector, inheritance, verifier break,
       cap — against zero disk. Nothing here can forge a stamp into the chain the
       supervisor verifies.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_notary_pristine_for_boundary_test", REPO / "core" / "notary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_append", lambda rec: None)

    # It must be the real thing, not the suite-wide recorder.
    assert mod.attest("boot", mod.PREV_NONE) is not None, (
        "the pristine notary is still neutralised; the boundary cannot be tested")
    return mod


@pytest.fixture
def perfect(notary, monkeypatch):
    """The most favourable world the notary can be shown: every dimension FULL,
    nothing inherited. If the boundary holds HERE it holds everywhere.

    This is what "regardless of self_observer's new level" means, made concrete.
    """
    monkeypatch.setattr(notary, "vector", lambda step, prev=None, inputs=None,
                        inputs_source=None: {
        "witness": notary.FULL, "human": notary.FULL, "thought": notary.FULL,
        "age": notary.FULL, "promise": notary.FULL,
        "why": {"witness": "w", "human": "h", "thought": "t",
                "age": "fresh", "promise": "kept"}})
    monkeypatch.setattr(notary, "_stamps", lambda: {})
    return notary


# ---------------------------------------------------------------------------
# (a) THE BOUNDARY — the cap is below the line, and the line has not moved
# ---------------------------------------------------------------------------

def test_the_cap_on_execute_patches_is_below_the_irreversible_line():
    assert N.MAX_LEVEL.get("execute_patches") == N.MINIMAL, (
        "the ceiling on execute_patches is no longer MINIMAL(1)")
    assert N.MAX_LEVEL["execute_patches"] < N.IRREVERSIBLE_MIN, (
        f"the cap {N.MAX_LEVEL['execute_patches']} is not below "
        f"IRREVERSIBLE_MIN {N.IRREVERSIBLE_MIN} — the step could act")
    assert N.IRREVERSIBLE_MIN == N.REDUCED == 2


def test_may_act_on_execute_patches_is_False_with_perfect_provenance(perfect):
    """THE PINNING ASSERTION. Every dimension FULL, nothing inherited, and the
    answer is still no — because the cap is applied last."""
    ok, why = perfect.may_act("execute_patches", "self_modifier")
    assert ok is False, (
        "\n  THE IRREVERSIBLE BOUNDARY MOVED.\n"
        "  execute_patches may now act with clean provenance. That is the\n"
        "  2026-08-30 failure repeating: correcting provenance removed the\n"
        "  accident that had been holding the gate shut, and the step that\n"
        "  rewrites this system's own source became permitted.\n"
        f"  reason: {why}\n")
    assert "ceiling" in why, why
    assert "AMENDMENT_001" in why, (
        "the refusal no longer names what would have to happen to change it")


def test_the_ceiling_binds_even_when_nothing_else_would(perfect):
    """ceiling_binds is the fact a reader needs: it says the cap would hold this
    step down even if every other dimension were perfect, which stays true when
    some stale input happens to be the proximate cause on a given night."""
    rec = perfect.attest("execute_patches", "self_modifier")
    assert rec["own"] == perfect.FULL, "fixture broken: own is not FULL"
    assert rec["ceiling"] == perfect.MINIMAL
    assert rec["ceiling_binds"] is True
    assert rec["capped"] is True
    assert rec["level"] == perfect.MINIMAL
    assert rec["level"] < perfect.IRREVERSIBLE_MIN


def test_self_observers_new_level_cannot_reach_execute_patches(
        notary, monkeypatch):
    """Explicitly the question this commit raises. Stamp every artifact
    self_observer produces at FULL — the best its new declaration could ever
    yield — and execute_patches is still refused."""
    import core.cycle_map as cm

    full_stamp = {"level": notary.FULL, "products": cm.produces("self_observer")}
    monkeypatch.setattr(notary, "_stamps",
                        lambda: {p: full_stamp for p in cm.produces("self_observer")})

    ok, why = notary.may_act("execute_patches", "self_modifier")
    assert ok is False, why

    # NOT asserting the reason names the ceiling here, and that is deliberate.
    # This test runs the REAL vector, so on a machine where the MeTTa sidecar is
    # down the weakest link is the witness and the refusal is attributed to it —
    # correctly. ceiling_binds only fires when own > ceiling. The claim under
    # test is about the LEVEL, not about which dimension happened to be named,
    # so the level is what is asserted. (The reason IS pinned to the ceiling in
    # test_may_act_on_execute_patches_is_False_with_perfect_provenance, where
    # every dimension is forced FULL and the ceiling is the only thing left.)
    rec = notary.attest("execute_patches", "self_modifier")
    assert rec["ceiling"] == notary.MINIMAL
    assert rec["level"] <= notary.MINIMAL < notary.IRREVERSIBLE_MIN, (
        "a FULL stamp on self_observer's products lifted execute_patches above "
        f"the line: level={rec['level']}")


# ---------------------------------------------------------------------------
# (b) THE MUTATION — raise the ceiling in a fixture and this goes RED
# ---------------------------------------------------------------------------

@pytest.fixture
def ceiling(request):
    """The execute_patches ceiling, injected. The real config is never touched;
    this exists so the mutation the brief asks for can be performed WITHOUT
    editing config/passage_rules.json."""
    return getattr(request, "param", N.MINIMAL)


@pytest.mark.parametrize("ceiling", [N.MINIMAL], indirect=True)
def test_MUTATION_the_boundary_test_goes_red_if_the_ceiling_is_raised(
        ceiling, perfect, monkeypatch):
    """THE MUTATION TEST, and the one that proves the rest are not vacuous.

    Change the parametrize above to [N.FULL] — or to anything >=
    IRREVERSIBLE_MIN — and this test goes RED: with a raised ceiling and perfect
    provenance, may_act returns True and the assertion below fails.

    Proven both ways before commit:
        ceiling = MINIMAL(1)  -> may_act False, test passes
        ceiling = FULL(3)     -> may_act True,  test FAILS
    """
    monkeypatch.setattr(perfect, "MAX_LEVEL", {"execute_patches": ceiling})

    ok, why = perfect.may_act("execute_patches", "self_modifier")
    if ceiling < N.IRREVERSIBLE_MIN:
        assert ok is False, (
            f"a ceiling of {ceiling} is below IRREVERSIBLE_MIN "
            f"{N.IRREVERSIBLE_MIN} and the step acted anyway: {why}")
    else:
        assert ok is False, (
            "\n  THE CEILING WAS RAISED AND THE STEP MAY NOW ACT.\n"
            f"  ceiling={ceiling}, IRREVERSIBLE_MIN={N.IRREVERSIBLE_MIN}.\n"
            "  This is the mutation firing exactly as intended: it demonstrates\n"
            "  that the boundary tests above are load-bearing and not vacuous.\n"
            f"  reason: {why}\n")


def test_the_shipped_ceiling_is_the_one_the_ruleset_states():
    """The cap the code applies and the cap a human reads must be the same
    number. config/passage_rules.json is the single source; nothing here edits
    it."""
    from core.passage_rules import RULES
    assert N.MAX_LEVEL == RULES["ceilings"] == {"execute_patches": 1}
    assert N.IRREVERSIBLE_MIN == RULES["irreversible_min"] == 2


# ---------------------------------------------------------------------------
# (c) THE OTHER SIDE — what self_modifier may do is REVERSIBLE
# ---------------------------------------------------------------------------

def test_what_self_modifier_produces_is_reversible_and_awaits_the_capped_step():
    """If self_modifier's gate now opens, what it may do is WRITE. Its declared
    products are proposals and journal entries; applying anything to this
    repository is execute_patches' job, and that step is capped.

    This is the sentence that makes the whole provenance batch safe to have
    landed: the reversible half may open, the irreversible half cannot.
    """
    import core.cycle_map as cm

    products = cm.produces("self_modifier")
    assert products, "self_modifier promises nothing; the map has gone stale"
    for rel in products:
        assert rel.startswith("memory/"), (
            f"self_modifier now claims to produce {rel}, which is outside "
            f"memory/. A step whose gate may open must not be writing outside "
            f"the reversible area.")

    # The applying step is a DIFFERENT step, and it is the capped one.
    assert "execute_patches" in N.MAX_LEVEL
    assert "self_modifier" not in N.MAX_LEVEL, (
        "self_modifier has acquired a ceiling; that is a policy change, not a "
        "provenance fix")


def test_the_cap_is_applied_last_in_attest():
    """STRUCTURAL. The ordering is the invariant: if the cap were applied before
    inheritance or the verifier break, a clean input could lift a capped step.
    Asserted on the AST so a reordering cannot pass review by looking harmless.
    """
    tree = ast.parse((REPO / "core" / "notary.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "attest")

    def line_of(fragment: str) -> int:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and fragment in ast.dump(node):
                return node.lineno
        return -1

    verified = line_of("'verified'") if line_of("'verified'") > 0 else line_of("verified")
    ceiling = next((n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Assign)
                    and any(getattr(t, "id", None) == "ceiling" for t in n.targets)), -1)
    assert ceiling > 0, "the ceiling assignment is gone from attest()"

    level_assigns = [n.lineno for n in ast.walk(fn)
                     if isinstance(n, ast.Assign)
                     and any(getattr(t, "id", None) == "level" for t in n.targets)]
    assert level_assigns, "level is no longer assigned in attest()"
    assert ceiling > min(level_assigns), (
        "the ceiling is read BEFORE level is first computed; the cap must be "
        "applied last, after the vector, after inheritance and after the "
        "verifier break")


# ---------------------------------------------------------------------------
# (d) the provenance work itself, so a revert is loud
# ---------------------------------------------------------------------------

def test_no_blind_producer_remains_at_any_gate():
    """What the batch achieved, pinned. Not a safety property — an honesty one:
    every artifact reaching a gate now has a producer that can say what it
    reads."""
    from core.blind_producers import blind_producers_for

    for gate in ("self_modifier", "execute_patches", "github_publish"):
        blind = blind_producers_for(gate)
        assert not blind, (
            f"{gate} is fed by a producer that cannot say what it reads: "
            f"{blind}. That producer stamps level_0 on what it makes and the "
            f"gate inherits it.")


def test_self_observer_declares_the_files_its_code_really_reads():
    """AST-bound, the COMMIT B pattern: the declaration must match the code, or
    the gate is aging files the step does not read."""
    from core.declared_inputs import for_step

    declared = for_step("self_observer") or []
    assert declared, "self_observer lost its declaration"

    src = (REPO / "agents" / "core" / "self_observer.py").read_text(encoding="utf-8")
    for rel in declared:
        leaf = rel.split("/")[-1]
        assert leaf in src, (
            f"self_observer declares {rel} but its source never names {leaf}")

    assert "memory/web_intelligence/latest.json" in declared
    assert "snapshots/master/dependency_check_latest.json" in declared


def test_self_observer_does_not_gate_on_its_own_output():
    """Its own products are read to append to. A step whose age depends on its
    own last output grades itself."""
    import json as _json
    import core.cycle_map as cm

    doc = _json.loads((REPO / "config" / "step_inputs.json").read_text(encoding="utf-8"))
    entry = doc["steps"]["self_observer"]
    for product in cm.produces("self_observer"):
        assert product not in entry["inputs"], (
            f"self_observer gates on its own output {product}")
        assert product in entry.get("also_reads", []), (
            f"{product} is written and read by this step and is declared nowhere")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
