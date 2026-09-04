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

# The debt as measured on 2026-09-05. This set is a LEDGER, not permission:
# test_every_verifier_declares_what_it_reads still fails for every name in it.
# Its only job is to let a NEWLY added landmine be told apart from the four
# already known, so the second failure is not lost in the first.
KNOWN_UNDECLARED = {
    "browser_scout",
    "global_indicators",
    "internet_intelligence",
    "sensorium_ingest",
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


def test_a_declared_verifier_scores_above_unknown():
    """The counter-example, so the test above is not vacuously true of every
    step. web_intelligence is the one verifier whose inputs were declared, on
    2026-08-31, and it is the reason publishing resumed."""
    inputs, source = _inputs_for("web_intelligence")
    level, why = _age_state(inputs, source)
    assert inputs, "web_intelligence lost its declaration"
    assert level > 0, f"declared but still UNKNOWN: {why}"
