# -*- coding: utf-8 -*-
"""
R52 item 4 — ONE correction turn for a wrong-order answer, then refuse.

PREDICTION ONLY (§VI); nothing here trades, and no test here reaches a model: the
correction function is injected.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (GROUNDED_CONTRACT, correction_prompt,  # noqa: E402
                              parse_grounded_completion, retry_wrong_order)

D = "2026-09-08"
GOOD = (f"DEADLINE: {D}\nSIGNAL: 2\nDRIVER: MACRO\n"
        f"LOGIC: yields reprice the basket\nDIRECTION: UP")
WRONG = f"DIRECTION: UP\nDEADLINE: {D}\nSIGNAL: 2\nDRIVER: MACRO\nLOGIC: y"


def _parsed(*raws):
    return [parse_grounded_completion(r) for r in raws]


def test_a_wrong_order_answer_gets_one_correction_and_is_fixed():
    out, log = retry_wrong_order(_parsed(WRONG), D, lambda i, c: GOOD)
    assert out[0]["order_problem"] is None
    assert out[0]["retried"] is True
    assert log == [{"candidate": 0, "problem": log[0]["problem"], "outcome": "FIXED",
                    "second_field_order": out[0]["field_order"]}]


def test_a_correct_answer_is_never_retried():
    calls = []
    out, log = retry_wrong_order(_parsed(GOOD), D,
                                 lambda i, c: calls.append(i) or GOOD)
    assert calls == [] and log == []
    assert "retried" not in out[0]


def test_exactly_one_correction_is_issued_never_a_loop():
    """A retry LOOP would keep asking until the model stumbled into the right shape,
    which selects for persistence rather than reasoning and turns the gate into a
    formatter."""
    calls = []

    def once(i, c):
        calls.append(i)
        return WRONG                      # never fixes it

    out, log = retry_wrong_order(_parsed(WRONG), D, once)
    assert calls == [0], "more than one correction turn was issued"
    assert log[0]["outcome"].startswith("STILL_WRONG")


def test_a_second_wrong_answer_leaves_the_first_in_place():
    """The retry can never make a candidate worse, and it cannot launder the record:
    what the model did FIRST is what stays."""
    out, log = retry_wrong_order(_parsed(WRONG), D, lambda i, c: WRONG)
    assert out[0]["raw"] == WRONG
    assert out[0]["order_problem"] is not None
    assert "retried" not in out[0]


def test_an_empty_or_failing_retry_is_logged_and_refuses():
    out, log = retry_wrong_order(_parsed(WRONG), D, lambda i, c: "")
    assert log[0]["outcome"] == "RETRY_EMPTY"
    assert out[0]["order_problem"] is not None

    def boom(i, c):
        raise RuntimeError("model unreachable")

    out, log = retry_wrong_order(_parsed(WRONG), D, boom)
    assert log[0]["outcome"].startswith("RETRY_FAILED")
    assert "model unreachable" in log[0]["outcome"]
    assert out[0]["order_problem"] is not None


def test_no_retry_function_means_no_retry():
    out, log = retry_wrong_order(_parsed(WRONG), D, None)
    assert log == [] and out[0]["order_problem"] is not None


def test_the_correction_names_the_order_and_nothing_about_the_answer():
    """THE CONSTRAINT THAT MATTERS. A correction that hinted at a direction, or echoed
    the model's own first attempt back at it, would re-prime the very verdict the
    ordering exists to stop being generated first."""
    c = correction_prompt(D)
    for field in GROUNDED_CONTRACT:
        assert field in c, field
    assert "LAST" in c
    # it must not name a direction, nor carry any evidence or prior attempt
    body = c.replace("DIRECTION: UP or DOWN", "").replace("DIRECTION", "")
    for leak in ("UP", "DOWN", "SEGMENT 2", "CPI"):
        assert leak not in body.upper(), leak


def test_the_retry_keeps_a_pointer_to_what_was_replaced():
    out, _ = retry_wrong_order(_parsed(WRONG), D, lambda i, c: GOOD)
    assert out[0]["retry_of"] == WRONG


def test_only_the_wrong_ones_are_retried_in_a_mixed_batch():
    seen = []
    out, log = retry_wrong_order(_parsed(GOOD, WRONG, GOOD), D,
                                 lambda i, c: seen.append(i) or GOOD)
    assert seen == [1]
    assert [e["candidate"] for e in log] == [1]
    assert out[1]["order_problem"] is None
