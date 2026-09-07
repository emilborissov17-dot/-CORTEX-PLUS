# -*- coding: utf-8 -*-
"""
R50 — DIRECTION is generated LAST, so it is conditioned on the reasoning.

PREDICTION ONLY (§VI). Nothing here trades.

The old grounded contract put DIRECTION on the FIRST line. A model writes left to right,
so every reasoning token was conditioned on a direction it had already committed to, and
the rationale could only ever be post-hoc. These tests hold the new order in place.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (GROUNDED_CONTRACT, check_field_order,  # noqa: E402
                              parse_grounded_completion)

D = "2026-09-08"


def _c(event=2, relevance="a broad US equity fund reprices on a national print",
       mechanism="a hotter print lifts real yields", direction="DOWN", deadline=D):
    return (f"DEADLINE: {deadline}\nEVENT: {event}\nRELEVANCE: {relevance}\n"
            f"MECHANISM: {mechanism}\nDIRECTION: {direction}")


# ── the contract itself ─────────────────────────────────────────────────────
def test_the_contract_ends_on_direction():
    assert GROUNDED_CONTRACT == ("EVENT", "RELEVANCE", "MECHANISM", "DIRECTION")
    assert GROUNDED_CONTRACT[-1] == "DIRECTION"


def test_a_contract_ordered_answer_parses_with_no_problem():
    p = parse_grounded_completion(_c())
    assert p["order_problem"] is None
    assert p["event"] == "2"
    assert p["direction"] == "DOWN"
    assert p["relevance"] and p["mechanism"]


def test_direction_is_the_last_field_generated():
    """THE PROPERTY. Not 'direction is present' — direction is LAST."""
    p = parse_grounded_completion(_c())
    assert p["field_order"][-1] == "DIRECTION"
    assert "DIRECTION" not in p["field_order"][:-1]


# ── the refusal this round exists for ───────────────────────────────────────
def test_direction_before_the_reasoning_is_refused_as_the_wrong_contract():
    """The OLD contract, replayed. It must not merely score worse — it must not parse."""
    old = (f"DIRECTION: DOWN\nDEADLINE: {D}\nEVENT: 2\n"
           f"RELEVANCE: x\nMECHANISM: y")
    p = parse_grounded_completion(old)
    assert p["order_problem"] is not None
    assert "DIRECTION comes FIRST" in p["order_problem"]
    assert "justification rather than a derivation" in p["order_problem"]


def test_the_previous_rounds_contract_no_longer_parses_at_all():
    """R49's own format — DIRECTION first, then RATIONALE with pipes."""
    p = parse_grounded_completion(
        f"DIRECTION: UP\nDEADLINE: {D}\nRATIONALE: DRIVER MACRO | SIGNAL 2 | LOGIC x")
    assert p["order_problem"] is not None
    assert p["event"] is None


@pytest.mark.parametrize("raw,fragment", [
    (f"DEADLINE: {D}\nEVENT: 2\nDIRECTION: UP\nRELEVANCE: x\nMECHANISM: y",
     "not EVENT -> RELEVANCE"),
    (f"EVENT: 2\nRELEVANCE: x\nMECHANISM: y\nDIRECTION: UP\nDEADLINE: {D}",
     "generated AFTER DIRECTION"),
    (f"DEADLINE: {D}\nEVENT: 2\nRELEVANCE: x\nDIRECTION: UP", "names no MECHANISM"),
    (f"DEADLINE: {D}\nEVENT: 2\nMECHANISM: y\nDIRECTION: UP", "names no RELEVANCE"),
    (f"DEADLINE: {D}\nRELEVANCE: x\nMECHANISM: y\nDIRECTION: UP", "names no EVENT"),
    (f"DEADLINE: {D}\nEVENT: 2\nRELEVANCE: x\nMECHANISM: y\nDIRECTION: UP\n"
     f"DIRECTION: DOWN", "more than once"),
    ("the market will simply go up", "names none of the contract"),
])
def test_every_wrong_shape_is_a_named_problem_not_a_silent_pass(raw, fragment):
    p = parse_grounded_completion(raw)
    assert p["order_problem"] and fragment in p["order_problem"], p["order_problem"]


def test_nothing_may_follow_direction():
    """DIRECTION last is the entire mechanism. A trailing DEADLINE is harmless in
    content and fatal in principle: it means the model was still writing after it
    answered, so the answer was not the end of the reasoning."""
    assert check_field_order(
        ["EVENT", "RELEVANCE", "MECHANISM", "DIRECTION", "DEADLINE"]) is not None
    assert check_field_order(
        ["DEADLINE", "EVENT", "RELEVANCE", "MECHANISM", "DIRECTION"]) is None


# ── what is deliberately NOT checked ────────────────────────────────────────
def test_case_is_not_reasoning_and_is_not_enforced():
    p = parse_grounded_completion(
        f"deadline: {D}\nevent: 2\nrelevance: x\nmechanism: y\ndirection: down")
    assert p["order_problem"] is None
    assert p["direction"] == "DOWN"


def test_a_bulleted_or_starred_line_still_parses():
    """Models decorate. Decoration is not order."""
    p = parse_grounded_completion(
        f"- DEADLINE: {D}\n- EVENT: 2\n- RELEVANCE: x\n- MECHANISM: y\n- DIRECTION: UP")
    assert p["order_problem"] is None
    assert p["direction"] == "UP"


def test_prose_between_the_fields_does_not_break_the_order():
    """Only recognised field lines carry order. A stray sentence is ignored, not
    treated as a field out of place."""
    p = parse_grounded_completion(
        f"DEADLINE: {D}\nEVENT: 2\nLet me think about this.\n"
        f"RELEVANCE: x\nMECHANISM: y\nDIRECTION: UP")
    assert p["order_problem"] is None


# ── the sealed record ───────────────────────────────────────────────────────
def _seal(tmp_path, completions):
    """Run the grounded path through the dry-run door and return the sealed record.

    Nothing here reaches the network or a model: the snippets and the completions are
    both staged, which is what --dry-run is for.
    """
    import json
    import subprocess

    fact = "CPI rose 0.3% in August, the BLS said on Friday."
    snip = {"title": "US inflation ticks up", "url": "https://www.reuters.com/x",
            "host": "reuters.com", "published_utc": "2026-09-05T12:30:00+00:00",
            "snippet": fact, "retrieved_utc": "2026-09-05T13:00:00+00:00",
            "source_class": "independent", "source_kind": "wire", "dated": True}
    dry = tmp_path / "dry.json"
    dry.write_text(json.dumps({
        "snippets": {"SPY": [snip], "GLD": [], "UUP": []},
        "completions": {"SPY": completions, "GLD": [], "UUP": []}}), encoding="utf-8")
    out = tmp_path / "bet.json"
    r = subprocess.run(
        [sys.executable, str(REPO / "tools" / "market_bet.py"), "--grounded",
         "--dry-run", str(dry), "--out", str(out), "--allow-overwrite"],
        capture_output=True, text=True, cwd=str(REPO),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert out.exists(), r.stdout + r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def test_the_sealed_record_shows_direction_as_the_last_generated_field(tmp_path):
    """THE TEST THE ROUND EXISTS FOR. Not 'the record has a direction' — the record
    shows WHERE in the generation the direction came, and it came last."""
    bet = _seal(tmp_path, [_c(event=2, direction="DOWN"), _c(event=2, direction="DOWN")])
    spy = bet["assets"]["SPY"]
    assert spy["sealed_direction"] == "DOWN"
    assert spy["contract"] == "EVENT -> RELEVANCE -> MECHANISM -> DIRECTION"
    assert spy["direction_generated_last"] is True
    assert spy["sealed_field_order"][-1] == "DIRECTION"
    assert "DIRECTION" not in spy["sealed_field_order"][:-1]
    # and the reasoning that produced it is sealed alongside, in order
    assert spy["sealed_relevance"] and spy["sealed_mechanism"]
    order = spy["sealed_field_order"]
    assert order.index("EVENT") < order.index("RELEVANCE") < order.index("MECHANISM")


def test_every_sealed_candidate_carries_its_own_generation_order(tmp_path):
    bet = _seal(tmp_path, [_c(event=2), _c(event=2, direction="DOWN")])
    for cand in bet["assets"]["SPY"]["candidates"]:
        assert cand["parsed"]["field_order"][-1] == "DIRECTION"


def test_a_direction_first_answer_never_reaches_the_sealed_record(tmp_path):
    """The old contract, run end to end through the real runner."""
    old = (f"DIRECTION: UP\nDEADLINE: {D}\nEVENT: 2\n"
           f"RELEVANCE: x\nMECHANISM: y")
    bet = _seal(tmp_path, [old, old])
    spy = bet["assets"]["SPY"]
    assert spy["sealed_direction"] is None
    assert spy["outcome"] == "REFUSED_NO_GROUNDED_CANDIDATE"
    assert all(c["verdict"] == "REFUSED" for c in spy["candidates"])
    assert all("field_order" in c["missing"] for c in spy["candidates"])


def test_the_sealed_gate_description_states_the_order(tmp_path):
    """A record whose own description does not name the contract cannot be audited by
    somebody who was not here."""
    bet = _seal(tmp_path, [_c(event=2)])
    assert "DIRECTION GENERATED LAST" in bet["gate"]
    assert "EVENT -> RELEVANCE -> MECHANISM -> DIRECTION" in bet["gate"]
