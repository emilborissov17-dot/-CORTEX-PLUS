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


def _c(signal=2, driver="MACRO", logic="a hotter print lifts real yields",
       direction="DOWN", deadline=D, event=None):
    """The R51 contract: DRIVER -> SIGNAL -> LOGIC -> DIRECTION, direction LAST.

    `event` is accepted as an alias for `signal` so call sites read unchanged."""
    signal = event if event is not None else signal
    return (f"DEADLINE: {deadline}\nSIGNAL: {signal}\nDRIVER: {driver}\n"
            f"LOGIC: {logic}\nDIRECTION: {direction}")


# ── the contract itself ─────────────────────────────────────────────────────
def test_the_contract_ends_on_direction():
    assert GROUNDED_CONTRACT == ("SIGNAL", "DRIVER", "LOGIC", "DIRECTION")
    assert GROUNDED_CONTRACT[-1] == "DIRECTION"


def test_a_contract_ordered_answer_parses_with_no_problem():
    p = parse_grounded_completion(_c())
    assert p["order_problem"] is None
    assert p["signal"] == "2"
    assert p["direction"] == "DOWN"
    assert p["driver"] == "MACRO" and p["logic"]


def test_direction_is_the_last_field_generated():
    """THE PROPERTY. Not 'direction is present' — direction is LAST."""
    p = parse_grounded_completion(_c())
    assert p["field_order"][-1] == "DIRECTION"
    assert "DIRECTION" not in p["field_order"][:-1]


# ── the refusal this round exists for ───────────────────────────────────────
def test_direction_before_the_reasoning_is_refused_as_the_wrong_contract():
    """The OLD contract, replayed. It must not merely score worse — it must not parse."""
    old = (f"DIRECTION: DOWN\nDEADLINE: {D}\nSIGNAL: 2\n"
           f"DRIVER: MACRO\nLOGIC: y")
    p = parse_grounded_completion(old)
    assert p["order_problem"] is not None
    assert "DIRECTION comes FIRST" in p["order_problem"]
    assert "justification rather than a derivation" in p["order_problem"]


def test_the_previous_rounds_contract_no_longer_parses_at_all():
    """R49's own format — DIRECTION first, then RATIONALE with pipes."""
    p = parse_grounded_completion(
        f"DIRECTION: UP\nDEADLINE: {D}\nRATIONALE: DRIVER MACRO | SIGNAL 2 | LOGIC x")
    assert p["order_problem"] is not None
    assert p["signal"] is None


@pytest.mark.parametrize("raw,fragment", [
    (f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: MACRO\nDIRECTION: UP\nLOGIC: y",
     "not SIGNAL -> DRIVER"),
    (f"SIGNAL: 2\nDRIVER: MACRO\nLOGIC: y\nDIRECTION: UP\nDEADLINE: {D}",
     "generated AFTER DIRECTION"),
    (f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: MACRO\nDIRECTION: UP", "names no LOGIC"),
    (f"DEADLINE: {D}\nDRIVER: MACRO\nLOGIC: y\nDIRECTION: UP", "names no SIGNAL"),
    (f"DEADLINE: {D}\nSIGNAL: 2\nLOGIC: y\nDIRECTION: UP", "names no DRIVER"),
    (f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: MACRO\nLOGIC: y\nDIRECTION: UP\n"
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
        ["SIGNAL", "DRIVER", "LOGIC", "DIRECTION", "DEADLINE"]) is not None
    assert check_field_order(
        ["DEADLINE", "SIGNAL", "DRIVER", "LOGIC", "DIRECTION"]) is None


# ── what is deliberately NOT checked ────────────────────────────────────────
def test_case_is_not_reasoning_and_is_not_enforced():
    p = parse_grounded_completion(
        f"deadline: {D}\nsignal: 2\ndriver: MACRO\nlogic: y\ndirection: down")
    assert p["order_problem"] is None
    assert p["direction"] == "DOWN"


def test_a_bulleted_or_starred_line_still_parses():
    """Models decorate. Decoration is not order."""
    p = parse_grounded_completion(
        f"- DEADLINE: {D}\n- SIGNAL: 2\n- DRIVER: MACRO\n- LOGIC: y\n- DIRECTION: UP")
    assert p["order_problem"] is None
    assert p["direction"] == "UP"


def test_prose_between_the_fields_does_not_break_the_order():
    """Only recognised field lines carry order. A stray sentence is ignored, not
    treated as a field out of place."""
    p = parse_grounded_completion(
        f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: MACRO\nLet me think about this.\n"
        f"LOGIC: y\nDIRECTION: UP")
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
    assert spy["contract"] == "SIGNAL -> DRIVER -> LOGIC -> DIRECTION"
    assert spy["direction_generated_last"] is True
    assert spy["sealed_field_order"][-1] == "DIRECTION"
    assert "DIRECTION" not in spy["sealed_field_order"][:-1]
    # and the reasoning that produced it is sealed alongside, in order
    assert spy["sealed_driver"] == "MACRO" and spy["sealed_logic"]
    order = spy["sealed_field_order"]
    assert order.index("SIGNAL") < order.index("DRIVER") < order.index("LOGIC")


def test_every_sealed_candidate_carries_its_own_generation_order(tmp_path):
    bet = _seal(tmp_path, [_c(event=2), _c(event=2, direction="DOWN")])
    for cand in bet["assets"]["SPY"]["candidates"]:
        assert cand["parsed"]["field_order"][-1] == "DIRECTION"


def test_a_direction_first_answer_never_reaches_the_sealed_record(tmp_path):
    """The old contract, run end to end through the real runner."""
    old = (f"DIRECTION: UP\nDEADLINE: {D}\nSIGNAL: 2\n"
           f"DRIVER: MACRO\nLOGIC: y")
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
    assert "SIGNAL -> DRIVER -> LOGIC -> DIRECTION" in bet["gate"]


# ── R51: the field set is MINIMAL, and DRIVER leads without leaking ─────────
def test_the_contract_has_exactly_one_free_text_field():
    """THE R51 CORRECTION TO R50. R50 put DIRECTION last but paid for it with TWO
    free-text fields (RELEVANCE and MECHANISM). Every free-text field a 3B is asked to
    fill is another surface it can confabulate on, so the set is now:

        DRIVER     closed four-word vocabulary   near-zero surface
        SIGNAL     a segment index               zero surface, verbatim by construction
        LOGIC      one sentence                  ONE surface
        DIRECTION  binary, and last              no surface
    """
    from tools.market_bet import BUCKETS
    assert GROUNDED_CONTRACT == ("SIGNAL", "DRIVER", "LOGIC", "DIRECTION")
    assert len(GROUNDED_CONTRACT) == 4
    # DRIVER is closed, SIGNAL is an index, DIRECTION is binary — LOGIC is the only
    # field whose contents the model invents.
    assert len(BUCKETS) == 4


def test_the_bucket_words_are_lexically_neutral_AND_THAT_IS_ALL_IT_PROVES():
    """R51 CLAIMED THE BUCKETS WERE VERIFIED DIRECTION-NEUTRAL. THEY WERE NOT.

    What this checks is that the four bucket WORDS are neutral in OUR OWN polarity
    lexicon and are not in a hand-written list of directional words. That is a claim
    about vocabulary. It says nothing about whether naming MACRO first makes
    macro-flavoured spans look more relevant, or whether P(UP | FLOW) skews in practice
    — neither of which had been measured when R51 asserted neutrality.

    Two things follow, and both are done rather than argued: SIGNAL is now selected
    BEFORE the bucket, so a label cannot frame the choice of span; and the skew is
    MEASURED by bucket_direction_table() rather than assumed away.
    """
    from tools.market_bet import BUCKETS, signal_polarity

    for bucket in BUCKETS:
        assert signal_polarity(bucket)["polarity"] == "NEUTRAL", bucket
    directional = {"UP", "DOWN", "BULL", "BEAR", "RISE", "FALL", "LONG", "SHORT"}
    for bucket in BUCKETS:
        assert bucket.upper() not in directional


def test_the_span_is_selected_before_the_bucket_labels_it():
    """The ordering change R52 makes. DRIVER classifies a sentence already chosen."""
    assert GROUNDED_CONTRACT.index("SIGNAL") < GROUNDED_CONTRACT.index("DRIVER")


def test_a_driver_outside_the_four_buckets_is_refused():
    from dataclasses import dataclass

    from tools.market_bet import grounded_gate

    @dataclass(frozen=True)
    class Sn:
        snippet: str = "CPI rose 0.3% in August, the BLS said on Friday."
        title: str = "US inflation ticks up"
        url: str = "https://www.reuters.com/x"
        published_utc: str = "2026-09-05T12:30:00+00:00"
        host: str = "reuters.com"
        source_class: str = "independent"
        source_kind: str = "wire"
        dated: bool = True

    r = grounded_gate([parse_grounded_completion(_c(driver="VIBES"))], "SPY", D,
                      [Sn()])[0]
    assert r["verdict"] == "REFUSED"
    assert "driver" in r["missing"]
    assert "closed" in r["refusal"]


def test_an_empty_logic_is_refused():
    from dataclasses import dataclass

    from tools.market_bet import grounded_gate

    @dataclass(frozen=True)
    class Sn:
        snippet: str = "CPI rose 0.3% in August, the BLS said on Friday."
        title: str = "US inflation ticks up"
        url: str = "https://www.reuters.com/x"
        published_utc: str = "2026-09-05T12:30:00+00:00"
        host: str = "reuters.com"
        source_class: str = "independent"
        source_kind: str = "wire"
        dated: bool = True

    r = grounded_gate([parse_grounded_completion(_c(logic=""))], "SPY", D, [Sn()])[0]
    assert r["verdict"] == "REFUSED"
    assert "logic" in r["missing"]
    assert "guess with a citation stapled to it" in r["refusal"]
