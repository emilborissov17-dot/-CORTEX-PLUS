# -*- coding: utf-8 -*-
"""
test/test_phase_evidence_swap.py — THE SAME SENTENCE SEVEN TIMES IS NOT SEVEN
DEBRIEFS.

THE EVIDENCE THIS FILE IS BUILT ON is committed beside it, in
test/fixtures/debriefs_2026-08-21_accepted/ — the six debriefs that the number
gate ACCEPTED on 21 Aug 2026. They are one sentence with the phase name
substituted:

    "Фазата <PHASE> завърши с композитен скор 0.6282, като се измериха
     11 метрика."

The gate was not broken. core/phase_tracker._evidence() handed every phase the
same composite, so 0.6282 really was "a number from this phase's data" for all
six. Fix the evidence and the gate starts working; that is what these tests
hold, in both directions:

  * the menus are DIFFERENT (>= 2 numbers each that no other phase has), and
  * a sentence that would pass under another phase's heading is REJECTED, and
  * a sentence citing this phase's own number still passes — a gate that
    refuses everything teaches the operator to stop reading it, which is the
    documented failure of the previous night.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import phase_debrief as pd        # noqa: E402
from core import phase_evidence as pe       # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "debriefs_2026-08-21_accepted"


# --------------------------------------------------------------------------- #
# (a) the menus are phase-specific
# --------------------------------------------------------------------------- #

def test_every_phase_has_a_menu_of_its_own():
    menus = pe.all_menus()
    assert set(menus) == set(pe.PHASES)
    for phase, ev in menus.items():
        assert len(ev) > 3, f"{phase} menu collapsed to {ev}"


@pytest.mark.parametrize("phase", pe.PHASES)
def test_each_menu_carries_at_least_two_numbers_no_other_phase_has(phase):
    """The requirement the swap test stands on. MEASURED against this repo, not
    asserted: if a phase ever drops below two, the gate for that phase quietly
    becomes unsatisfiable and this must go red before that ships."""
    menus = pe.all_menus()
    own = pe.own_numbers(phase, menus)
    assert len(own) >= pe.MIN_OWN_NUMBERS, (
        f"{phase} has only {len(own)} number(s) of its own ({sorted(own)}) — "
        f"the swap test cannot distinguish it from another phase")


def test_the_composite_belongs_to_the_phase_that_computes_it():
    """A_ORIENT runs before the scorer. Handing it the composite meant handing
    it YESTERDAY'S composite and calling it this phase's own data."""
    menus = pe.all_menus()
    holders = [p for p in pe.PHASES if "composite_score" in menus[p]]
    assert holders == ["D_SCORE"], (
        f"composite_score is in {holders}; it is D_SCORE's number and nobody "
        f"else's")


def test_a_menu_never_raises_even_against_an_empty_repo(tmp_path):
    """Fail-open per fact, not per menu: an empty tree must yield a labelled
    menu, not an exception and not a menu of nulls."""
    for phase in pe.PHASES:
        ev = pe.menu(phase, base=tmp_path)
        assert ev["phase"] == phase
        assert None not in ev.values(), f"{phase} menu carries a null: {ev}"


# --------------------------------------------------------------------------- #
# (b) the swap test as a validator rule
# --------------------------------------------------------------------------- #

GOOD = {"verdict": "OK", "risk": "none", "do": "nothing"}


def test_a_sentence_that_survives_a_phase_swap_is_rejected():
    evidence = {"phase": "B_SENSE", "web_total_sources": 284,
                "composite_score": 0.6282}
    own = {"284"}
    accepted, reasons = pd.validate(
        {**GOOD, "what": "Фазата B_SENSE завърши с композитен скор 0.6282."},
        evidence, own)
    assert accepted is False
    assert any(pd.SWAP_GENERIC in r for r in reasons), reasons


def test_the_same_sentence_citing_this_phases_own_number_is_accepted():
    """The other half. A gate that refuses everything is the failure this
    replaces, not the one it repeats."""
    evidence = {"phase": "B_SENSE", "web_total_sources": 284,
                "composite_score": 0.6282}
    accepted, reasons = pd.validate(
        {**GOOD, "what": "B_SENSE събра 284 източника."}, evidence, {"284"})
    assert accepted is True, reasons


def test_the_rejection_names_both_halves_of_the_counterexample():
    """The reason string is the retry prompt's raw material, so it must carry
    what was cited AND what should have been."""
    accepted, reasons = pd.validate(
        {**GOOD, "what": "композитен скор 0.6282"},
        {"phase": "F_SELF", "mirror_false_alarms": 17, "composite_score": 0.6282},
        {"17"})
    assert not accepted
    swap = [r for r in reasons if pd.SWAP_GENERIC in r][0]
    assert "0.6282" in swap, "the reason does not say what was wrongly cited"
    assert "17" in swap, "the reason does not say what should have been cited"
    assert "F_SELF" in swap


def test_no_own_numbers_means_the_rule_is_skipped_not_failed():
    """Silently turning 'I had nothing to check against' into 'you failed' is
    the same class of lie as the generic debrief itself."""
    evidence = {"phase": "X", "steps": 7}
    accepted, reasons = pd.validate({**GOOD, "what": "7 steps ran."},
                                    evidence, set())
    assert accepted is True, reasons
    accepted2, _ = pd.validate({**GOOD, "what": "7 steps ran."}, evidence, None)
    assert accepted2 is True


def test_the_older_rules_still_bite_underneath_the_new_one():
    evidence = {"phase": "D_SCORE", "composite_score": 0.6282}
    for bad, needle in (
        ({**GOOD, "what": "The phase completed successfully."}, "no number"),
        ({**GOOD, "what": "已评分25个轴 0.6282"}, "CJK"),
        ({**GOOD, "verdict": "FINE", "what": "0.6282"}, "not one of"),
    ):
        accepted, reasons = pd.validate(bad, evidence, {"0.6282"})
        assert not accepted
        assert any(needle in r for r in reasons), (needle, reasons)


# --------------------------------------------------------------------------- #
# (c) the validator feeds the prompt
# --------------------------------------------------------------------------- #

def test_the_retry_prompt_carries_the_reason_and_the_answer_key():
    text = pd.PROMPT_SHARP.format(
        phase="F_SELF", evidence="{}",
        why=f"{pd.SWAP_GENERIC}: 'what' cites ['0.6282']",
        numbers="17, 21, 0.6282", own="17, 21")
    assert pd.SWAP_GENERIC in text, "the rejection reason is not fed back"
    assert "17, 21" in text, "the numbers unique to the phase are not fed back"
    assert "0.6282" in text, "the counterexample is not stated"


def test_the_second_attempt_is_given_the_answer_key(tmp_path):
    """The loop closes only if own_numbers reaches ask(). An asker that declares
    `own` must receive it; the sharpened retry exists to answer the objection,
    and it cannot answer one it was not told."""
    seen = []

    def asker(phase, evidence, why=None, own=None):
        seen.append({"why": why, "own": own})
        if why is None:
            return {**GOOD, "what": "композитен скор 0.6282"}
        return {**GOOD, "what": f"F_SELF: {sorted(own)[0]} фалшиви тревоги."}

    rec = pd.debrief_phase(
        "F_SELF", "replay-test",
        # composite_score is IN the evidence on purpose: without it the first
        # answer trips the older "foreign number" rule and never reaches the
        # swap test. This is the case the swap test exists for — a number that
        # IS in the menu and is in every other phase's menu too.
        {"phase": "F_SELF", "mirror_false_alarms": 17, "composite_score": 0.6282},
        base=tmp_path, asker=asker, own_numbers={"17"})
    assert len(seen) == 2, seen
    assert seen[1]["own"] == {"17"}, "the retry was not handed the answer key"
    assert pd.SWAP_GENERIC in (seen[1]["why"] or "")
    assert rec["accepted"] is True, rec["rejected_because"]
    assert rec["attempts"] == 2


def test_the_record_keeps_the_evidence_it_judged_against(tmp_path):
    """A verdict whose evidence is gone cannot be replayed. The six records of
    21 Aug do not have it, which is why scripts/replay_debriefs.py has to
    rebuild the menu and say so."""
    rec = pd.debrief_phase(
        "F_SELF", "replay-test-2", {"phase": "F_SELF", "mirror_false_alarms": 17},
        base=tmp_path,
        asker=lambda p, e: {**GOOD, "what": "17 фалшиви тревоги."},
        own_numbers={"17"})
    assert rec["evidence"] == {"phase": "F_SELF", "mirror_false_alarms": 17}
    assert rec["own_numbers"] == ["17"]
    assert rec["swap_test"] == "applied"


# --------------------------------------------------------------------------- #
# (d) the replay — the six of 21 Aug 2026, committed as fixtures
# --------------------------------------------------------------------------- #

def test_the_fixtures_are_the_six_accepted_debriefs_of_21_august():
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) == 6, f"expected six fixtures, found {[f.name for f in files]}"
    for f in files:
        rec = json.loads(f.read_text(encoding="utf-8"))
        assert rec["accepted"] is True, f"{f.name} was not an accepted debrief"
        assert "0.6282" in rec["debrief"]["what"], f.name


def test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test():
    """The measured result, kept as a test so a later loosening of the gate is
    visible as a change in this number rather than as nothing at all.

    D_SCORE survives, and correctly: the composite IS D_SCORE's own number. The
    other five borrowed it. That the gate lets exactly one through is the point
    — a rule that rejected all six would be indistinguishable from a rule that
    rejects everything, which is what the previous night's gate did.
    """
    menus = pe.all_menus()
    survived, rejected = [], []
    for f in sorted(FIXTURES.glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        phase = rec["phase"]
        ok, _ = pd.validate(rec["debrief"], menus[phase],
                            pe.own_numbers(phase, menus))
        (survived if ok else rejected).append(phase)

    assert survived == ["D_SCORE"], (
        f"survived={survived} rejected={rejected} — expected D_SCORE alone")
    assert len(rejected) == 5


def test_the_replay_script_reports_the_same_number():
    """The script is the thing a human runs; if it and the library disagree, the
    human is reading a different gate from the one that runs."""
    from scripts.replay_debriefs import replay
    out = replay(FIXTURES)
    was = [r for r in out["rows"] if r["was"]]
    now = [r for r in was if r["now"]]
    assert len(was) == 6
    assert len(now) == 1
    assert now[0]["phase"] == "D_SCORE"
