# -*- coding: utf-8 -*-
"""
Market bet gate. PREDICTION ONLY — nothing here trades.

The gate's job is to refuse a bet that cannot be diagnosed later: no direction, no
reason, a made-up driver bucket, or a SIGNAL that is opinion dressed as evidence.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (BUCKETS, US_MARKET_HOLIDAYS_2026, choose,  # noqa: E402
                              gate_all, next_session, parse_completion, split_rationale,
                              signal_is_external_fact)

D = "2026-09-08"
GOOD = "DRIVER MACRO | SIGNAL CPI surprise +0.3, BLS 12 Sep | LOGIC hotter print lifts yields"


def _c(direction="UP", rationale=GOOD, deadline=D):
    lines = []
    if direction is not None:
        lines.append(f"DIRECTION: {direction}")
    lines.append(f"DEADLINE: {deadline}")
    if rationale is not None:
        lines.append(f"RATIONALE: {rationale}")
    return "\n".join(lines)


def _g(*comps, deadline=D):
    return gate_all([parse_completion(c) for c in comps], "SPY", deadline)


# ── the holiday trap the dry run caught ─────────────────────────────────────
def test_the_next_session_skips_labor_day():
    """THE DRY RUN CAUGHT THIS. Friday 2026-09-04 plus one weekday is 2026-09-07 —
    Labor Day, no session. A bet whose deadline lands on a closed market cannot be
    graded, and a missing bar looks exactly like a bar that has not arrived yet."""
    assert next_session(date(2026, 9, 4)) == date(2026, 9, 8)
    assert "2026-09-07" in US_MARKET_HOLIDAYS_2026


def test_the_next_session_skips_weekends():
    assert next_session(date(2026, 9, 3)) == date(2026, 9, 4)   # Thu -> Fri
    assert next_session(date(2026, 9, 11)) == date(2026, 9, 14)  # Fri -> Mon


def test_it_refuses_rather_than_guessing_past_the_holiday_table():
    with pytest.raises(ValueError, match="holiday table only covers"):
        next_session(date(2026, 12, 31))


# ── the four refusals ───────────────────────────────────────────────────────
def test_a_non_directional_answer_is_refused():
    r = _g(_c(direction="MAYBE"))[0]
    assert r["verdict"] == "REFUSED" and "direction" in r["missing"]
    assert "UP or DOWN" in r["refusal"]


def test_a_missing_direction_is_refused():
    assert _g(_c(direction=None))[0]["verdict"] == "REFUSED"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_an_empty_rationale_is_refused(blank):
    r = _g(_c(rationale=blank))[0]
    assert r["verdict"] == "REFUSED" and "rationale" in r["missing"]


def test_a_driver_outside_the_four_buckets_is_refused():
    r = _g(_c(rationale="DRIVER VIBES | SIGNAL ISM print 2 Sep | LOGIC contraction"))[0]
    assert r["verdict"] == "REFUSED" and "driver" in r["missing"]
    assert all(b in r["refusal"] for b in BUCKETS)


def test_a_signal_that_is_interpretation_is_refused():
    """THE ONE THAT MATTERS. 'Sentiment feels weak' is an opinion about the price the
    model was just shown — it names nothing anybody could look up."""
    for bad in ("sentiment feels weak", "momentum is negative", "looks toppy",
                "the chart is bearish"):
        r = _g(_c(rationale=f"DRIVER MACRO | SIGNAL {bad} | LOGIC x"))[0]
        assert r["verdict"] == "REFUSED", bad
        assert "signal" in r["missing"]
        assert "interpretation" in r["refusal"]


def test_a_signal_with_a_date_or_a_named_source_passes():
    for good in ("CPI surprise +0.3, BLS 12 Sep", "FOMC minutes 2026-08-20",
                 "OPEC+ output decision 7 Sep", "ISM 48.1 printed 2 Sep",
                 "Reuters report on month-end flows"):
        assert signal_is_external_fact(good), good


def test_the_signal_check_is_declared_weak_and_only_filters_shape():
    """It cannot verify a fact is TRUE, only that it is the kind of thing that could be
    checked. Saying so in the docstring is part of the contract."""
    import tools.market_bet as mb
    doc = mb.signal_is_external_fact.__doc__
    assert "cannot verify" in doc and "not lies" in doc
    # a fabricated but well-shaped signal still passes — by design, and stated
    assert signal_is_external_fact("CPI surprise +9.9, BLS 12 Sep") is True


def test_a_deadline_that_is_not_the_graded_session_is_refused():
    r = _g(_c(deadline="2026-09-30"))[0]
    assert r["verdict"] == "REFUSED" and "deadline" in r["missing"]


def test_a_clean_candidate_is_admitted():
    r = _g(_c())[0]
    assert r["verdict"] == "ADMITTED" and r["refusal"] is None


# ── the choice ──────────────────────────────────────────────────────────────
def test_the_majority_direction_is_sealed_not_the_best_prose():
    """Prose must not choose the bet. Two UP against one DOWN seals UP regardless of
    how the rationales read."""
    recs = _g(_c("UP"), _c("DOWN", rationale=GOOD + " and this one is beautifully argued"),
              _c("UP"))
    idx, reason, win = choose(recs)
    assert win == "UP" and "majority" in reason
    assert recs[idx]["parsed"]["direction"] == "UP"


def test_no_passing_candidate_seals_nothing():
    idx, reason, win = choose(_g(_c(direction="MAYBE")))
    assert idx is None and win is None and "no candidate passed" in reason


def test_every_candidate_keeps_its_raw_text_and_a_verdict():
    recs = _g(_c("UP"), _c(direction="MAYBE"), _c(rationale=None))
    assert len(recs) == 3
    for r in recs:
        assert r["raw"] and r["verdict"] in ("ADMITTED", "REFUSED")
        if r["verdict"] == "REFUSED":
            assert r["refusal"]


def test_nothing_here_trades():
    """Identifiers, not prose. 'broker' now appears in an explanation of why a broker's
    commentary is classed self_reported, and 'api_key' is Tavily's own request field."""
    import ast

    class _Blank(ast.NodeTransformer):
        def visit_Constant(self, node):
            return ast.copy_location(
                ast.Constant(value="" if isinstance(node.value, str) else node.value),
                node)

    code = ast.unparse(_Blank().visit(ast.parse(
        (REPO / "tools" / "market_bet.py").read_text(encoding="utf-8")))).lower()
    for word in ("place_order", "submit_order", "create_order", "alpaca",
                 "ib_insync", "portfolio", "position_size"):
        assert word not in code, f"{word!r} in a prediction-only module"


# ── the RATIONALE split: a missing pipe must never lose a field in silence ──
# The old parser split on "|" alone. Measured on the four shapes a model actually
# produces, three of them lost a field and set logic=None — which reads exactly like a
# model that gave no reason at all. Three of the eight live R48 candidates were in the
# second shape below.
def test_a_missing_pipe_no_longer_swallows_the_logic():
    """SHAPE B, the live one: 'SIGNAL <x> LOGIC: <y>' with no pipe between them."""
    p = parse_completion("RATIONALE: DRIVER MACRO | SIGNAL CPI 12 Sep LOGIC: yields lift")
    assert p["signal"] == "CPI 12 Sep"
    assert p["logic"] == "yields lift"
    assert p["rationale_problem"] is None
    assert p["rationale_parsed_by"] == "markers"


def test_a_rationale_with_no_pipes_at_all_is_parsed_field_by_field():
    """SHAPE C, the nastiest. It used to give driver='MACRO SIGNAL 7 LOGIC: ...', whose
    first token is 'MACRO' — A VALID BUCKET — so the driver check PASSED and the run
    then blamed an empty SIGNAL. A correct refusal for the wrong reason is how a real
    bug hides."""
    p = parse_completion("RATIONALE: DRIVER MACRO SIGNAL ISM 2 Sep LOGIC: contraction")
    assert p["driver"] == "MACRO"
    assert p["signal"] == "ISM 2 Sep"
    assert p["logic"] == "contraction"
    assert p["rationale_problem"] is None
    assert _g(_c(rationale="DRIVER MACRO SIGNAL ISM 2 Sep LOGIC: contraction"))[0][
        "verdict"] == "ADMITTED"


def test_a_logic_on_its_own_line_is_folded_in_rather_than_dropped():
    """SHAPE D. The continuation line matched no branch at all and vanished."""
    p = parse_completion(f"DIRECTION: UP\nDEADLINE: {D}\n"
                         f"RATIONALE: DRIVER MACRO | SIGNAL CPI 12 Sep\n"
                         f"LOGIC: hotter print lifts yields")
    assert p["logic"] == "hotter print lifts yields"
    assert p["rationale_problem"] is None
    # `raw` still holds exactly what the model emitted; only `rationale` is rebuilt.
    assert "\nLOGIC:" in p["raw"]


@pytest.mark.parametrize("rationale,fragment", [
    ("DRIVER MACRO | SIGNAL CPI 12 Sep", "names no LOGIC"),
    ("SIGNAL CPI 12 Sep | LOGIC yields lift", "names no DRIVER"),
    ("the market will simply go up", "names none of DRIVER, SIGNAL or LOGIC"),
    ("DRIVER MACRO | SIGNAL CPI LOGIC: a | LOGIC b", "more than once"),
])
def test_an_unresolvable_rationale_is_a_named_refusal_not_a_silent_none(
        rationale, fragment):
    """THE CONTRACT OF THIS FIX. Either the field is parsed correctly or the failure is
    NAMED. There is no third outcome where logic comes back None and nobody is told."""
    p = parse_completion(_c(rationale=rationale))
    assert p["rationale_problem"] and fragment in p["rationale_problem"]
    r = _g(_c(rationale=rationale))[0]
    assert r["verdict"] == "REFUSED"
    assert r["missing"] == ["rationale_format"]
    assert fragment in r["refusal"]


def test_a_lowercase_logic_inside_free_text_is_not_a_field_marker():
    """The ungrounded path still puts prose in SIGNAL, so the marker must be a HEADER —
    uppercase, at a boundary — not any occurrence of the word."""
    p = parse_completion(
        "RATIONALE: DRIVER MACRO | SIGNAL the logic of the market 2 Sep | LOGIC yields lift")
    assert p["signal"] == "the logic of the market 2 Sep"
    assert p["logic"] == "yields lift"


def test_a_well_formed_rationale_still_reports_that_it_used_the_pipes():
    """The repair must be visible. A model that followed the format and a model that
    was rescued by the markers must not look identical in the record."""
    assert parse_completion(_c())["rationale_parsed_by"] == "pipes"
    assert parse_completion(
        _c(rationale="DRIVER MACRO SIGNAL CPI 12 Sep LOGIC: x"))["rationale_parsed_by"] \
        == "markers"


def test_no_shape_of_rationale_ever_returns_a_silent_none_logic():
    """The property, stated over every shape at once: if logic is None, a problem is
    named. This is the assertion that would have caught the original bug."""
    shapes = [
        "DRIVER MACRO | SIGNAL CPI 12 Sep | LOGIC yields lift",
        "DRIVER MACRO | SIGNAL CPI 12 Sep LOGIC: yields lift",
        "DRIVER MACRO SIGNAL CPI 12 Sep LOGIC: yields lift",
        "DRIVER MACRO | SIGNAL CPI 12 Sep",
        "DRIVER MACRO | SIGNAL CPI LOGIC: a | LOGIC b",
        "the market will simply go up",
        "",
    ]
    for s in shapes:
        p = parse_completion(_c(rationale=s))
        assert (p["logic"] is not None) != (p["rationale_problem"] is not None), s


def test_split_rationale_returns_the_three_fields_and_how_it_found_them():
    """The seam itself, called directly: fields, how they were found, and the problem
    if there was one. Three return values so a caller can never read a missing field
    without also seeing why it is missing."""
    fields, how, problem = split_rationale(GOOD)
    assert fields == {"driver": "MACRO",
                      "signal": "CPI surprise +0.3, BLS 12 Sep",
                      "logic": "hotter print lifts yields"}
    assert how == "pipes" and problem is None

    fields, how, problem = split_rationale("DRIVER MACRO | SIGNAL CPI LOGIC: x")
    assert fields["logic"] == "x" and how == "markers" and problem is None

    fields, how, problem = split_rationale("DRIVER MACRO | SIGNAL CPI 12 Sep")
    assert "logic" not in fields and problem and "names no LOGIC" in problem
