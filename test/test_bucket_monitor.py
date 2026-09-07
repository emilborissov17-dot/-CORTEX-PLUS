# -*- coding: utf-8 -*-
"""
R52 — the bucket-direction MONITOR. PREDICTION ONLY (§VI); nothing here trades.

R51 asserted the four DRIVER buckets were direction-neutral. The only evidence was that
the four WORDS are neutral in our own polarity lexicon — a fact about vocabulary, not
about the model. This measures the thing that was asserted, and refuses nothing on it.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (BUCKETS, MIN_BUCKET_N,  # noqa: E402
                              bucket_direction_table)


def _rows(*pairs):
    return [{"driver": d, "direction": x} for d, x in pairs]


def test_it_reports_p_up_per_bucket():
    t = bucket_direction_table(_rows(("MACRO", "UP"), ("MACRO", "DOWN"),
                                     ("FLOW", "UP"), ("FLOW", "UP")))
    assert t["MACRO"]["n"] == 2 and t["MACRO"]["p_up"] == 0.5
    assert t["FLOW"]["n"] == 2 and t["FLOW"]["p_up"] == 1.0
    assert t["GEOPOL"]["n"] == 0 and t["GEOPOL"]["p_up"] is None


def test_a_bucket_written_with_a_qualifier_still_counts():
    """'MACRO (rates)' is the bucket MACRO with a note attached — the gate reads the
    first word, and so must the monitor, or the two disagree about the same answer."""
    t = bucket_direction_table(_rows(("MACRO (rates)", "UP"), ("macro", "DOWN")))
    assert t["MACRO"]["n"] == 2


def test_a_small_sample_is_marked_as_noise_rather_than_reported_as_a_rate():
    """THE HONEST PART. Two of two is '100%' and means nothing. n is printed beside
    every rate precisely so it cannot be read as a result."""
    t = bucket_direction_table(_rows(("MACRO", "UP"), ("MACRO", "UP")))
    assert t["MACRO"]["p_up"] == 1.0
    assert t["MACRO"]["enough_to_read"] is False
    assert t["_summary"]["skewed"] == []          # too small to call skewed


def test_a_real_skew_is_reported_as_a_finding_and_refuses_nothing():
    t = bucket_direction_table(_rows(*[("FLOW", "UP")] * MIN_BUCKET_N))
    assert t["FLOW"]["enough_to_read"] is True
    assert t["FLOW"]["p_up"] == 1.0
    assert "FLOW" in t["_summary"]["skewed"]
    assert "FINDING" in t["_summary"]["_finding"] or "finding" in t["_summary"]["_finding"]
    # and the finding says both readings, because at this n they are indistinguishable
    assert "leaks a direction" in t["_summary"]["_finding"]
    assert "really" in t["_summary"]["_finding"]


def test_a_balanced_bucket_is_not_flagged():
    t = bucket_direction_table(_rows(("MACRO", "UP"), ("MACRO", "DOWN"),
                                     ("MACRO", "UP"), ("MACRO", "DOWN")))
    assert t["MACRO"]["enough_to_read"] is True
    assert t["_summary"]["skewed"] == []


def test_it_is_a_monitor_and_says_so():
    """Structural: nothing in the function refuses, and it declares itself.

    IDENTIFIERS, NOT PROSE. The docstring says "Nothing is refused on this number",
    which is the opposite of a refusal and would fail a text grep — the same trap that
    made three earlier tests in this repo push the code around to satisfy them.
    """
    import ast
    import inspect

    import tools.market_bet as mb

    class _Blank(ast.NodeTransformer):
        def visit_Constant(self, node):
            return ast.copy_location(
                ast.Constant(value="" if isinstance(node.value, str) else node.value),
                node)

    tree = _Blank().visit(ast.parse(inspect.getsource(mb.bucket_direction_table)))
    src = ast.unparse(tree).lower()
    for forbidden in ("verdict", "refusal", "raise "):
        assert forbidden not in src, forbidden
    declared = bucket_direction_table([])["_summary"]["_not_a_gate"].lower()
    assert "nothing is refused" in declared


def test_every_bucket_appears_even_when_unused():
    t = bucket_direction_table([])
    for b in BUCKETS:
        assert b in t and t[b]["n"] == 0
    assert t["_summary"]["buckets_used"] == 0
