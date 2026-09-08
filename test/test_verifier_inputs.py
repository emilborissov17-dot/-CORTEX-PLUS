# -*- coding: utf-8 -*-
"""
core.notary.VERIFIERS vs config/step_inputs.json — the landmine, as a test.

THE DEFECT THIS EXISTS TO MAKE IMPOSSIBLE (written 5 Sep 2026)
--------------------------------------------------------------
A step in VERIFIERS is one the notary lets BREAK inherited provenance: it
verifies against a live external source, so it may wash a low level clean. That
is a privilege. The privilege is granted by NAME, in a set literal, and nothing
has ever checked that the named step can actually say what it reads.

A step whose inputs resolve to [] gets `_age_state([]) -> UNKNOWN(0)`
(core/notary.py:301-312, "no declared inputs - provenance unknown"). Its own
level becomes min(..., 0) = 0, that level is stamped on the artifacts it
produces, and every irreversible step that declares those artifacts as inputs
inherits level_0 and is refused by the gate — every night, until a human
declares the inputs by hand.

That is not a hypothesis. It has now happened twice, measured:

  * `web_intelligence` was in VERIFIERS with no declared inputs. From
    2026-08-17 the notary refused `github_publish` on **15 consecutive nights**
    with "level_0 (неизвестен произход) — слабо звено: no declared inputs".
    Publishing to the public repo stopped for 13 nights. Fixed on 2026-08-31
    (commit 467bcf6) by declaring one step's inputs.

  * `self_modifier` has been refused on **19 consecutive nights** and is still
    refusing as of 2026-09-04, for the same reason one level down.

Both remedies were per-step and manual. A per-step manual remedy is not a fix;
it is the same defect waiting for the next name added to the set. This test is
the structural version: **you may not join VERIFIERS without declaring what you
read.**

WHY THIS TEST IS RED TODAY, ON PURPOSE
--------------------------------------
Four of the five current verifiers cannot say what they read. They are named in
KNOWN_UNDECLARED below with the date the debt was recorded. The red clears when
each is declared in config/step_inputs.json — following that file's own
`_how_to_add_a_step` rule: read the module the step actually calls, list what it
opens on THAT path, and record `derived_from`. Do not copy the scanner's output
and do not guess from the step name.

An xfail here would be the exact defect the whole file is about: a failure
rendered as something plausible. So it fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.declared_inputs import for_step          # noqa: E402
from core.notary import VERIFIERS, _age_state, _inputs_for   # noqa: E402

# The debt, measured 2026-09-05 and REDUCED 2026-09-08 from four names to two.
# This set is a LEDGER, not permission: test_every_verifier_declares_what_it_reads
# still fails for every name in it. Its only job is to let a NEWLY added landmine
# be told apart from the ones already known, so the second failure is not lost in
# the first.
#
# PAID OFF 2026-09-08, by reading each module on the path the cycle calls:
#   global_indicators -> data/ucdp
#       _resolve_ucdp_csv/_fetch_ucdp_local_csv (global_indicators.py:377-406).
#       Its one local input, and its age is a real fact: the active-conflict
#       count is exactly as old as that CSV. Now scores MINIMAL(1) — lower than
#       anyone would like, and TRUE, where before it scored UNKNOWN(0).
#   sensorium_ingest -> memory/sensorium, memory/penumbra
#       ingest() and verify() re-hash both merkle chains; the drop paths come out
#       of the leaf records at runtime, so the trees are declared. Now REDUCED(2).
#
# WHY THE REMAINING TWO ARE A DIFFERENT PROBLEM, AND ARE NOT DECLARED HERE.
# Neither reads any local file whose age means anything:
#   browser_scout          AST census of experiments/browser_scout/scout.py: one
#                          write_text (its own output) and one read_text behind
#                          sys.argv, which the cycle never takes. Its SOURCES
#                          table of URLs is a literal in the module. It reads
#                          NOTHING locally on the cycle path.
#   internet_intelligence  agents/internet/internet_agent.py reads only its own
#                          outputs and caches — memory/youtube_adaptive_memory.json
#                          (896, written at 904) and memory/transcript_cache —
#                          plus .env for a key. Declaring a step's own cache as
#                          its input makes it grade itself; declaring a secrets
#                          file ties the gate to a credential's mtime. Neither is
#                          a provenance statement.
#
# So the honest declaration for both is EMPTY, and an empty declaration is
# UNKNOWN by design (core/notary._age_state fails closed). Their real input is a
# live URL, and the notary's age model has no category for that. Inventing a file
# to declare would be faking provenance — the one thing this whole subsystem
# exists to refuse.
#
# THE DECISION IS EMIL'S, and REMEDY below already states both acceptable
# answers: give them a real local input (e.g. move the URL tables into a config
# file that IS declared and IS aged), or take them out of VERIFIERS, since a step
# with no local provenance cannot honestly hold the right to BREAK inherited
# provenance. Not decided here.
KNOWN_UNDECLARED = {
    "browser_scout",
    "internet_intelligence",
}

REMEDY = (
    "Declare its inputs in config/step_inputs.json under 'steps', following that "
    "file's _how_to_add_a_step: read the module the step actually calls, list what "
    "it opens on THAT path, and fill in 'derived_from'. If the step does not belong "
    "in VERIFIERS, remove it from core/notary.VERIFIERS instead — either answer is "
    "acceptable; leaving it undeclared is not."
)


def _undeclared() -> list[str]:
    """Verifiers that cannot say what they read.

    for_step() returns None for 'nobody wrote a declaration' and [] for 'a
    declaration exists and is empty or broken' (core/declared_inputs.py:113-120).
    Both produce UNKNOWN provenance, so both fail here.
    """
    return sorted(s for s in VERIFIERS if not (for_step(s) or []))


# ── the requirement ──────────────────────────────────────────────────────────

def test_every_verifier_declares_what_it_reads():
    """A step may not hold the right to break inherited provenance while being
    unable to state its own. Fails until every name in VERIFIERS is declared."""
    missing = _undeclared()
    assert not missing, (
        "these steps are in core.notary.VERIFIERS with NO declared inputs in "
        "config/step_inputs.json:\n  "
        + "\n  ".join(missing)
        + "\n\nEach resolves to _age_state([]) -> UNKNOWN(0), which stamps level_0 "
          "on everything it produces and refuses every irreversible step that "
          "inherits from it. This is what cost 15 nights of github_publish and 19 "
          "of self_modifier.\n\n" + REMEDY
    )


# ── the ratchet: a NEW landmine must be distinguishable from the old four ────

def test_no_verifier_becomes_undeclared_that_was_not_already():
    """The structural guard. Adding a name to VERIFIERS without declaring its
    inputs fails HERE, separately from the four legacy debts, so it cannot hide
    inside an already-red test."""
    new = sorted(set(_undeclared()) - KNOWN_UNDECLARED)
    assert not new, (
        "NEW undeclared verifier(s): " + ", ".join(new)
        + "\nThis is the landmine being laid again. " + REMEDY
    )


def test_the_ledger_does_not_outlive_the_debt():
    """When a legacy debt is paid, its name must leave KNOWN_UNDECLARED. A stale
    ledger entry silently re-permits the same step if it regresses later."""
    paid = sorted(KNOWN_UNDECLARED - set(_undeclared()))
    assert not paid, (
        "these steps now declare their inputs and must be removed from "
        "KNOWN_UNDECLARED in this file: " + ", ".join(paid)
    )


def test_every_name_in_the_ledger_is_still_a_verifier():
    """A step removed from VERIFIERS is no longer a debt. Keeping it listed makes
    the ledger describe a system that no longer exists."""
    gone = sorted(KNOWN_UNDECLARED - set(VERIFIERS))
    assert not gone, (
        "no longer in core.notary.VERIFIERS, so remove from KNOWN_UNDECLARED: "
        + ", ".join(gone)
    )


# ── the mechanism, so the requirement above cannot be argued with ────────────

@pytest.mark.parametrize("step", sorted(KNOWN_UNDECLARED))
def test_an_undeclared_verifier_really_does_score_unknown(step):
    """Not an assumption: the four named steps are asked, right now, through the
    notary's own code path, and each answers UNKNOWN(0)."""
    if for_step(step):
        pytest.skip(f"{step} now has a declaration — see the ledger test")
    inputs, source = _inputs_for(step)
    level, why = _age_state(inputs, source)
    assert level == 0, f"{step} scored {level}: {why}"
    assert "no declared inputs" in why, why


# ── the refusal must not present blindness as a verdict ──────────────────────
# A refusal caused by a step that never declared what it reads used to come back
# as "level_0 (неизвестен произход)" plus the name of an input — which reads as a
# judgement about the QUALITY of that input. It is not: nothing was measured and
# found wanting, nothing was measured at all. The two want different responses,
# and nineteen nights of self_modifier were spent on the wrong one.

def test_a_blind_step_is_named_as_blind_not_scored_as_poor():
    """The step's own blindness, in words, ahead of the level number."""
    step = sorted(KNOWN_UNDECLARED)[0]
    if for_step(step):
        pytest.skip(f"{step} now has a declaration")
    from core.notary import _blindness
    said = _blindness(step, {})
    assert "never declared what it reads" in said, said
    assert repr(step) in said, said


def test_the_blind_step_named_is_the_UPSTREAM_one_not_the_consumer(monkeypatch):
    """THE CASE THAT WAS INVISIBLE. A step can declare every one of its own
    inputs and still be refused, because the step that PRODUCED one of them
    declares none. The refusal must name that upstream step, not blame the
    artifact or the consumer.

    HERMETIC SINCE 8 SEP 2026, AND THAT IS THE POINT. This test used the live
    pair self_modifier <- hyperclaw_plan <- memory/improvement_proposals.json,
    which was true every night until hyperclaw_plan was declared in
    config/step_inputs.json. The assertion then pinned a fact that had stopped
    being true and failed for a reason that had nothing to do with the mechanism
    under test — the same defect this file's own _how_to_add_a_step warns about
    for hardcoded copies of declared lists. The pair is now built here, so the
    test survives every future declaration and still goes red if _blindness()
    stops naming the upstream step.
    """
    from core import notary as _N
    from core.notary import _blindness

    monkeypatch.setattr(_N, "_inputs_for",
                        lambda step: (["memory/thing.json"], "written")
                        if step == "consumer" else ([], "scanner"))
    monkeypatch.setattr(_N, "_producers_of",
                        lambda art: ["upstream_blind"]
                        if art == "memory/thing.json" else [])

    rec = {"inherited_from": "memory/thing.json", "inherited": 0, "own": 1}
    said = _blindness("consumer", rec)
    assert "upstream_blind" in said, said
    assert "consumer" not in said, ("the consumer is being blamed for its "
                                    "producer's blindness: " + said)
    assert "never declared what it reads" in said, said
    assert "memory/thing.json" in said, said


def test_no_blindness_is_claimed_when_the_producer_IS_declared():
    """The clause must be earned. web_intelligence declares its inputs, so a low
    level inherited from it is a real verdict and must not be excused as
    blindness."""
    from core.notary import _blindness
    rec = {"inherited_from": "memory/web_intelligence", "inherited": 0, "own": 2}
    assert _blindness("github_publish", rec) == ""


def test_the_blindness_clause_survives_the_refusal_reader_truncation(monkeypatch):
    """tools/read_the_refusals.py prints reason[:150]. The name of the blind step
    must fall inside that, or the streak report shows the boilerplate and hides
    the one word a human needs.

    Hermetic for the same reason as the test above, and with a deliberately long
    artifact path: if the name were placed after the path, a realistic path would
    push it past the truncation and the report would again show only boilerplate.
    """
    from core import notary as _N
    from core.notary import _blindness

    art = "memory/a_realistically_long_artifact_name_latest.json"
    monkeypatch.setattr(_N, "_inputs_for",
                        lambda step: ([art], "written")
                        if step == "consumer" else ([], "scanner"))
    monkeypatch.setattr(_N, "_producers_of",
                        lambda a: ["upstream_blind"] if a == art else [])

    rec = {"inherited_from": art, "inherited": 0, "own": 1}
    assert "upstream_blind" in _blindness("consumer", rec)[:150]


def test_the_explanation_can_never_change_the_decision():
    """_blindness is called inside may_act's refusal path only, and its failure is
    recorded rather than swallowed. Asserted structurally: the call is wrapped and
    the except branch produces text, never a `pass` and never a re-raise."""
    src = (REPO / "core" / "notary.py").read_text(encoding="utf-8")
    i = src.index("blind = _blindness(step, rec)")
    tail = src[i:i + 400]
    assert "except Exception" in tail, tail
    assert "blindness check failed" in tail, (
        "the blindness check swallows its own failure silently")
    assert "return False" in tail, "the refusal must still be returned"


def test_a_declared_verifier_scores_above_unknown():
    """The counter-example, so the test above is not vacuously true of every
    step. web_intelligence is the one verifier whose inputs were declared, on
    2026-08-31, and it is the reason publishing resumed."""
    inputs, source = _inputs_for("web_intelligence")
    level, why = _age_state(inputs, source)
    assert inputs, "web_intelligence lost its declaration"
    assert level > 0, f"declared but still UNKNOWN: {why}"


# ── COMMIT C: a declaration must be BOUND to what the code opens ─────────────
# A verifier trusted to BREAK inherited provenance must declare the source it
# checks, or it cannot itself be trusted. And a declaration nobody verifies is a
# second copy free to drift from the code — the same defect one level up. These
# read the modules.

_DECLARED_VERIFIER_READS = {
    # step -> (module path, the constant that must still resolve to the declared
    #          path, the fragments that must appear in that constant)
    "global_indicators": ("core/global_indicators.py", "UCDP_LOCAL_DIR",
                          ("data", "ucdp")),
}


@pytest.mark.parametrize("step", sorted(_DECLARED_VERIFIER_READS))
def test_a_declared_verifier_input_is_one_its_code_actually_opens(step):
    """Binds config/step_inputs.json to the module's own path constants. If the
    constant is renamed or repointed, the declaration is stale and the gate is
    aging a file the step no longer reads."""
    import ast

    rel, const_name, fragments = _DECLARED_VERIFIER_READS[step]
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    consts = {n.targets[0].id: ast.dump(n.value)
              for n in tree.body
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    assert const_name in consts, (
        f"{rel} no longer defines {const_name}; the declaration in "
        f"config/step_inputs.json for {step} is stale")
    for frag in fragments:
        assert repr(frag) in consts[const_name], (
            f"{const_name} in {rel} no longer contains {frag!r}; "
            f"{step} now declares a path its code does not open")


def test_sensorium_declares_both_chains_because_it_verifies_both():
    """verify() re-derives the verified chain AND the penumbra shadow
    independently — the module's contract is that a corrupted shadow must never
    cast doubt on verified sense. A stale shadow is therefore its own fact and
    must be its own declared input, not folded into the first."""
    declared = for_step("sensorium_ingest") or []
    assert "memory/sensorium" in declared
    assert "memory/penumbra" in declared, (
        "the shadow chain is verified on this step and is not declared, so its "
        "age cannot reach the gate")

    src = (REPO / "experiments" / "sensorium" / "sensorium.py").read_text(
        encoding="utf-8")
    for const in ("PENUMBRA_LEAVES", "PENUMBRA_ROOT", "LEAVES", "ROOT_FILE"):
        assert const in src, f"{const} is gone; re-derive the declaration"


def test_a_declared_verifier_no_longer_scores_unknown():
    """The point of the commit: these two stopped being blind. Their levels are
    LOW and that is honest — data/ucdp really is 57 days old — but low is a
    measurement and UNKNOWN is the absence of one."""
    for step in ("global_indicators", "sensorium_ingest"):
        inputs, source = _inputs_for(step)
        assert inputs, f"{step} lost its declaration"
        level, why = _age_state(inputs, source)
        assert level > 0, f"{step} still scores UNKNOWN: {why}"
        assert "no declared inputs" not in why


def test_no_verifier_declares_its_own_output_as_an_input():
    """A step whose age dimension depends on its own last output grades itself,
    and one missed night would hold it down for ever. This is the trap the two
    remaining undeclared verifiers would fall into if somebody declared their
    caches to make the ledger shrink."""
    import json as _json

    doc = _json.loads((REPO / "config" / "step_inputs.json").read_text(
        encoding="utf-8"))
    own_output = {
        "global_indicators": "snapshots/master/global_indicators_latest.json",
        "sensorium_ingest": None,
    }
    for step, product in own_output.items():
        if not product:
            continue
        entry = doc["steps"][step]
        assert product not in entry["inputs"], (
            f"{step} gates on its own output {product}")
        assert product in entry.get("also_reads", []), (
            f"{product} is read by {step} and is declared nowhere")
