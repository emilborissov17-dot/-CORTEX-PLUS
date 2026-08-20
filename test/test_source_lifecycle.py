#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_source_lifecycle.py — BELIEF IS EARNED, LOGGED, AND REVOCABLE.

WHY THE ALLOWLIST HAD TO GO
----------------------------
The DMZ worker used to fetch four hand-written URLs and nothing else. Safe, and
a dead end: data_scout has been finding sources since June, and 44 active JSON
candidates sat unused in memory/discovered_data_sources.json — four of them
NASA-EONET, found 31 July — because nothing decided whether to believe them.

A hand-written list cannot grow. A process for earning trust can:

    CANDIDATE --5 clean, stable observations--> TRUSTED --3 contradictions--> DEMOTED

MEASURED ON THE MACHINE, five consecutive live runs of 33 sources:

    #1  0 trusted / 21 shadow / 12 refused   (32 CANDIDATE)
    #5 21 trusted /  0 shadow / 12 refused   (20 TRUSTED, 12 CANDIDATE)

The twelve that never promote are exactly the twelve that refuse — UN SDG
returning a list where a number was asked for, Open-Meteo returning a daily
array, one entry whose url is 'local://'. They answer, but never with a number.

    venv\\Scripts\\python.exe -m pytest test/test_source_lifecycle.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import source_lifecycle as life

REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def ledger(tmp_path):
    """Every test writes its evidence to tmp_path, never memory/."""
    return tmp_path / "ledger.jsonl"


def _feed(state, sid, values, ledger, axis="AX", peer=None):
    for v in values:
        life.observe(sid, axis=axis, ok=True, value=v, peer=peer,
                     state=state, ledger=ledger)
    return state


def _rows(ledger) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines()
            if l.strip()]


# 1 ---------------------------------------------------------------------------

def test_a_new_source_starts_as_a_candidate_and_is_not_believed(ledger):
    state = {}
    life.observe("new", axis="AX", ok=True, value=42.0, state=state, ledger=ledger)

    assert life.state_of("new", state) == life.CANDIDATE
    assert life.is_trusted("new", state) is False, (
        "a source seen once has earned nothing"
    )


# 2 ---------------------------------------------------------------------------

def test_a_steady_source_promotes_after_the_required_streak(ledger):
    """POSITIVE CONTROL — a lifecycle that can only refuse is not a lifecycle.
    This is the defect that shipped in the first draft: contradictions were
    judged against the axis's primary metric, a different quantity entirely, so
    every discovered source contradicted on sight and none could ever promote."""
    state = _feed({}, "steady", [100, 101, 99, 100, 102], ledger)

    assert life.state_of("steady", state) == life.TRUSTED
    assert state["steady"]["clean_streak"] >= life.PROMOTE_AFTER


def test_it_does_not_promote_one_observation_early(ledger):
    state = _feed({}, "almost", [100] * (life.PROMOTE_AFTER - 1), ledger)
    assert life.state_of("almost", state) == life.CANDIDATE


# 3 ---------------------------------------------------------------------------

def test_a_chaotic_source_never_promotes(ledger):
    """THE REQUIRED PROOF. It answers every single time — and its readings swing
    so wildly that the next one tells you nothing."""
    state = _feed({}, "chaotic", [1, 900, 3, 700, 2, 850, 4, 990, 1, 760], ledger)

    assert life.state_of("chaotic", state) == life.CANDIDATE, (
        f"\n  A CHAOTIC SOURCE WAS PROMOTED.\n"
        f"  It never missed a fetch, so the clean streak is "
        f"{state['chaotic']['clean_streak']} — well past {life.PROMOTE_AFTER}.\n"
        f"  Answering reliably is not the same as being worth believing.\n"
        f"  cv={state['chaotic']['cv']}, threshold {life.CHAOS_CV}\n"
    )
    assert state["chaotic"]["clean_streak"] >= life.PROMOTE_AFTER, (
        "the fixture is wrong: it must be chaotic, not merely failing"
    )
    assert state["chaotic"]["chaotic"] is True


# 4 ---------------------------------------------------------------------------

def test_a_promoted_source_demotes_after_three_contradictions(ledger):
    """THE SECOND REQUIRED PROOF."""
    state = _feed({}, "faller", [100] * life.PROMOTE_AFTER, ledger)
    assert life.state_of("faller", state) == life.TRUSTED, "it never promoted"

    for i in range(life.DEMOTE_AFTER):
        life.observe("faller", axis="AX", ok=True, value=500.0, peer=100.0,
                     state=state, ledger=ledger)
        expected = life.DEMOTED if i == life.DEMOTE_AFTER - 1 else life.TRUSTED
        assert life.state_of("faller", state) == expected, (
            f"after {i + 1} contradiction(s) the state should be {expected}"
        )


def test_two_contradictions_are_not_enough(ledger):
    """One disagreement is as likely to be the incumbent being wrong as the
    challenger. Three is the point at which that stops being plausible."""
    state = _feed({}, "wobbly", [100] * life.PROMOTE_AFTER, ledger)
    for _ in range(life.DEMOTE_AFTER - 1):
        life.observe("wobbly", axis="AX", ok=True, value=500.0, peer=100.0,
                     state=state, ledger=ledger)
    assert life.state_of("wobbly", state) == life.TRUSTED


# 5 ---------------------------------------------------------------------------

def test_a_refusal_breaks_the_streak_but_is_not_a_contradiction(ledger):
    """An endpoint that is down is not an endpoint that is lying. Conflating
    them would demote every source behind a flaky network."""
    state = _feed({}, "flaky", [100] * (life.PROMOTE_AFTER - 1), ledger)
    life.observe("flaky", axis="AX", ok=False, reason="HTTP 503",
                 state=state, ledger=ledger)

    rec = state["flaky"]
    assert rec["clean_streak"] == 0
    assert rec["contradictions"] == 0
    assert rec["refusals"] == 1
    assert life.state_of("flaky", state) == life.CANDIDATE


def test_a_source_that_only_refuses_never_promotes(ledger):
    """The twelve on this machine that answer but never with a number."""
    state = {}
    for _ in range(life.PROMOTE_AFTER * 3):
        life.observe("liar", axis="AX", ok=False,
                     reason="at 'data': expected a number, got list",
                     state=state, ledger=ledger)
    assert life.state_of("liar", state) == life.CANDIDATE
    assert state["liar"]["refusals"] == life.PROMOTE_AFTER * 3


# 6 ---------------------------------------------------------------------------

def test_no_peer_means_no_contradiction_is_possible(ledger):
    """Until a trusted source exists for the same quantity, there is no
    incumbent to disagree with. This is the bug the first draft shipped."""
    state = _feed({}, "lonely", [113.0] * life.PROMOTE_AFTER, ledger, peer=None)

    assert state["lonely"]["contradictions"] == 0
    assert life.state_of("lonely", state) == life.TRUSTED


def test_a_value_close_to_its_peer_does_not_contradict():
    assert life.contradicts(100.0, 105.0) is False
    assert life.contradicts(100.0, 500.0) is True


# 7 ---------------------------------------------------------------------------

def test_demotion_is_terminal_without_a_human(ledger):
    """A source that lied three times does not walk back in by behaving for a
    week. Re-instating it is a human act, not an emergent one."""
    state = _feed({}, "burned", [100] * life.PROMOTE_AFTER, ledger)
    for _ in range(life.DEMOTE_AFTER):
        life.observe("burned", axis="AX", ok=True, value=500.0, peer=100.0,
                     state=state, ledger=ledger)
    assert life.state_of("burned", state) == life.DEMOTED

    for _ in range(life.PROMOTE_AFTER * 2):
        life.observe("burned", axis="AX", ok=True, value=100.0, peer=100.0,
                     state=state, ledger=ledger)
    assert life.state_of("burned", state) == life.DEMOTED, (
        "a demoted source promoted itself back by behaving"
    )


# 8 ---------------------------------------------------------------------------

def test_every_observation_and_transition_is_in_the_ledger(ledger):
    """A promotion nobody can audit is a promotion nobody should trust."""
    state = _feed({}, "audited", [100] * life.PROMOTE_AFTER, ledger)
    rows = _rows(ledger)

    assert len(rows) == life.PROMOTE_AFTER
    assert all(r["source_id"] == "audited" for r in rows)
    assert all("ts" in r and "event" in r for r in rows)

    transitions = [r for r in rows if r.get("transition")]
    assert len(transitions) == 1
    assert transitions[0]["transition"] == "CANDIDATE -> TRUSTED"
    assert "clean observations" in transitions[0]["why"], (
        "the transition must carry the evidence that caused it"
    )


def test_the_ledger_records_why_a_demotion_happened(ledger):
    state = _feed({}, "d", [100] * life.PROMOTE_AFTER, ledger)
    for _ in range(life.DEMOTE_AFTER):
        life.observe("d", axis="AX", ok=True, value=999.0, peer=100.0,
                     state=state, ledger=ledger)

    demotion = [r for r in _rows(ledger)
                if r.get("transition") == "TRUSTED -> DEMOTED"]
    assert len(demotion) == 1
    assert "contradictions" in demotion[0]["why"]
    assert demotion[0]["peer"] == 100.0 and demotion[0]["value"] == 999.0


# 9 ---------------------------------------------------------------------------

def test_only_trusted_sources_are_measured(ledger):
    """The rule the composite depends on, asserted at the boundary."""
    state = {}
    life.observe("young", axis="AX", ok=True, value=1.0, state=state, ledger=ledger)
    _feed(state, "grown", [50] * life.PROMOTE_AFTER, ledger)

    assert life.is_trusted("grown", state) is True
    assert life.is_trusted("young", state) is False
    assert life.summary(state) == {life.CANDIDATE: 1, life.TRUSTED: 1,
                                   life.DEMOTED: 0}


# 10 --------------------------------------------------------------------------

def test_the_eonet_candidate_from_31_july_is_reachable_and_shadow_fetching():
    """THE THIRD REQUIRED PROOF, against the real discovery file.

    Four NASA-EONET sources were found on 2026-07-31 and never used. They must
    now appear in what the worker fetches, as candidates.
    """
    from scripts.openclaw_axis_worker import all_sources

    sources, _ = all_sources()
    eonet = [s for s in sources if "eonet" in (s.get("url") or "").lower()]

    assert eonet, (
        "the EONET candidates from 31 July are still not being fetched — the "
        "worker is not reading memory/discovered_data_sources.json"
    )
    assert all(s["origin"] == "data_scout" for s in eonet)
    assert any(s.get("discovered_at", "").startswith("2026-07-31") for s in eonet)
    assert all(s["path"].endswith("#len") for s in eonet), (
        "EONET reports an event LIST; the number is its length"
    )


def test_the_discovered_sources_outnumber_the_seed():
    """The point of deleting the allowlist. If this ever inverts, discovery has
    stopped feeding the worker and it is a hand-written list again."""
    from scripts.openclaw_axis_worker import all_sources, load_sources

    sources, _ = all_sources()
    seed, _ = load_sources()
    scout = [s for s in sources if s.get("origin") == "data_scout"]

    assert len(scout) > len(seed), f"{len(scout)} discovered vs {len(seed)} seed"


# 11 --------------------------------------------------------------------------

def test_the_thresholds_are_what_was_specified():
    """PINNED, not derived.

    Every test above reads life.DEMOTE_AFTER rather than the literal 3, which
    keeps them from being brittle — and means none of them notices if the
    constant itself moves. A negative control proved it: setting DEMOTE_AFTER
    to 99 left all sixteen tests green while demotion was, in practice, off.

    The numbers are part of the specification, so one test states them.
    """
    assert life.DEMOTE_AFTER == 3, "three contradictions end trust"
    assert life.PROMOTE_AFTER == 5, "five clean observations earn it"
    assert 0 < life.CONTRADICTION_TOLERANCE < 1
    assert 0 < life.CHAOS_CV < 1
