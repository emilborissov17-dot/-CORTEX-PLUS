# -*- coding: utf-8 -*-
"""
Tests 8–16 of claude/SPEC_7SEP_R43_GROUNDED_BET.md §4.

The one that matters is test 15: every candidate the 7 Sep gate ADMITTED is replayed
through the grounded gate, and all 22 must be refused. If that ever passes fewer than
22, the gate has stopped doing the only thing it was built for.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (dates_in, disagreement, grounded_gate,  # noqa: E402
                              normalise, parse_completion, signal_dated_after,
                              signal_grounded)

DEADLINE = "2026-09-08"
FACT = "CPI rose 0.3% in August, the Bureau of Labor Statistics said on Friday"


@dataclass(frozen=True)
class Sn:
    snippet: str = FACT
    title: str = "US inflation ticks up"
    url: str = "https://www.reuters.com/markets/us/cpi-2026-09-05"
    published_utc: str = "2026-09-05T12:30:00+00:00"
    host: str = "reuters.com"
    source_class: str = "independent"
    source_kind: str = "wire"
    dated: bool = True


def _c(direction="UP", signal=FACT, driver="MACRO", logic="higher yields weigh on equities",
       deadline=DEADLINE):
    return (f"DIRECTION: {direction}\nDEADLINE: {deadline}\n"
            f"RATIONALE: DRIVER {driver} | SIGNAL {signal} | LOGIC {logic}")


def _g(*comps, snippets=(Sn(),), deadline=DEADLINE):
    return grounded_gate([parse_completion(c) for c in comps], "SPY", deadline,
                         list(snippets))


# ── 8. exact substring is ADMITTED ──────────────────────────────────────────
def test_an_exact_substring_of_a_snippet_is_admitted():
    r = _g(_c(signal="CPI rose 0.3% in August"))[0]
    assert r["verdict"] == "ADMITTED", r.get("refusal")


def test_matching_ignores_case_and_whitespace_only():
    r = _g(_c(signal="cpi   ROSE 0.3%   in august"))[0]
    assert r["verdict"] == "ADMITTED"
    assert normalise("  A   b ") == "a b"


def test_a_title_match_also_counts():
    assert _g(_c(signal="US inflation ticks up"))[0]["verdict"] == "ADMITTED"


# ── 9. a PARAPHRASE is refused ──────────────────────────────────────────────
def test_a_paraphrase_of_a_snippet_is_refused():
    """The whole property being bought. 'Similar to' is what produced the 7 Sep
    fabrications; only a quote proves the document was read."""
    for para in ("CPI increased 0.3 percent in August",
                 "August inflation came in at 0.3%",
                 "the BLS reported a 0.3% August CPI rise"):
        r = _g(_c(signal=para))[0]
        assert r["verdict"] == "REFUSED", para
        assert "grounding" in r["missing"]
        assert "exact substring" in r["refusal"]


def test_a_too_short_signal_cannot_ground_itself_on_a_common_word():
    """A three-character 'signal' is a substring of almost anything."""
    assert signal_grounded("CPI", [Sn()])[0] is False
    assert signal_grounded("in August", [Sn()])[0] is False


# ── 10. plausible but absent — the 7 Sep failure, re-run ────────────────────
def test_a_plausible_signal_that_appears_in_no_snippet_is_refused():
    r = _g(_c(signal="Nonfarm payrolls +150k, BLS 5 Sep"))[0]
    assert r["verdict"] == "REFUSED"
    assert "grounding" in r["missing"]


# ── 11. dated after the graded session ──────────────────────────────────────
def test_a_signal_dated_after_the_graded_session_is_refused():
    """THE JACKSON HOLE CASE. On 7 Sep this was ADMITTED."""
    sig = "Fed releases September Jackson Hole Symposium transcript, Sept 21"
    assert signal_dated_after(sig, DEADLINE) is True
    r = grounded_gate([parse_completion(_c(signal=sig))], "SPY", DEADLINE,
                      [Sn(snippet=f"x {sig} y")])[0]
    assert r["verdict"] == "REFUSED"
    assert "signal_date" in r["missing"]
    assert "cannot have driven" in r["refusal"]


def test_a_signal_dated_before_the_session_is_fine():
    assert signal_dated_after("CPI surprise +0.3, BLS 5 Sep", DEADLINE) is False
    assert signal_dated_after("FOMC minutes 2026-08-20", DEADLINE) is False


def test_the_date_parser_actually_matches_something():
    """A regex that silently matches nothing is indistinguishable from a document with
    no dates in it — which is exactly what the first version of dates_in() did."""
    assert dates_in("Sept 21", 2026) == [(2026, 9, 21)]
    assert dates_in("12 Sep", 2026) == [(2026, 9, 12)]
    assert dates_in("2026-08-20", 2026) == [(2026, 8, 20)]


# ── 13. NO_DISAGREEMENT ─────────────────────────────────────────────────────
def test_when_every_passing_candidate_agrees_it_is_named_not_dressed_as_a_majority():
    """All 24 said UP on 7 Sep and the record called it a majority. Best-of-N over a
    constant selected nothing."""
    assert disagreement(_g(_c("UP"), _c("UP"), _c("UP"))) == "NO_DISAGREEMENT"
    assert disagreement(_g(_c("UP"), _c("DOWN"))) == "DISAGREEMENT"
    assert disagreement(_g(_c(direction="MAYBE"))) == "NO_PASSING_CANDIDATE"


# ── 14. the sealed bet carries the evidence ─────────────────────────────────
def test_an_admitted_candidate_carries_the_matched_snippets_url_and_date():
    r = _g(_c(signal="CPI rose 0.3% in August"))[0]
    assert r["evidence"]["url"].startswith("https://www.reuters.com/")
    assert r["evidence"]["published_utc"] == "2026-09-05T12:30:00+00:00"
    assert r["evidence"]["host"] == "reuters.com"


def test_a_refused_candidate_carries_no_evidence():
    r = _g(_c(signal="something absent entirely from the snippet"))[0]
    assert "evidence" not in r


# ── 12. no snippets at all ──────────────────────────────────────────────────
def test_with_no_snippets_every_candidate_is_refused():
    """An asset with no fact gets no bet, and there is no fallback."""
    recs = _g(_c(), _c("DOWN"), snippets=())
    assert [r["verdict"] for r in recs] == ["REFUSED", "REFUSED"]
    assert all("0 available" in r["refusal"] for r in recs)


# ── 15. THE REPLAY — all 22 fabrications must be refused ────────────────────
def test_every_candidate_the_7_sep_gate_admitted_is_refused_by_the_grounded_gate():
    """THE TEST THIS WHOLE PIECE EXISTS FOR.

    f41a7fd sealed three bets and admitted 22 of 24 candidates, every cited fact
    invented. Replayed here against a REAL snippet set that does not contain any of
    them, all 22 must now be refused.
    """
    fab = json.loads((REPO / "test" / "fixtures_f41a7fd_admitted.json")
                     .read_text(encoding="utf-8"))
    assert len(fab) == 22, f"the fixture holds {len(fab)}, not the 22 that were admitted"

    snippets = [Sn(),
                Sn(snippet="Gold steadied as the dollar eased.",
                   title="Gold steadies", url="https://www.reuters.com/markets/gold"),
                Sn(snippet="The dollar index slipped 0.2% on the session.",
                   title="Dollar slips", url="https://apnews.com/dollar", host="apnews.com")]

    refused, admitted = [], []
    for f in fab:
        comp = (f"DIRECTION: {f['direction']}\nDEADLINE: {f['deadline']}\n"
                f"RATIONALE: {f['rationale']}")
        r = grounded_gate([parse_completion(comp)], f["asset"], f["deadline"], snippets)[0]
        (refused if r["verdict"] == "REFUSED" else admitted).append(
            (f["asset"], f["signal"], r.get("refusal")))

    assert not admitted, (
        f"{len(admitted)} of the 7 Sep fabrications still pass:\n  "
        + "\n  ".join(f"{a}: {s}" for a, s, _ in admitted))
    assert len(refused) == 22
    reasons = {("signal_date" if "signal_date" in (why or "") else "grounding")
               for _, _, why in refused}
    assert "grounding" in reasons


# ── 16. prediction only ─────────────────────────────────────────────────────
def test_prediction_only_no_order_path():
    """Identifiers, not prose. 'broker' now appears in an explanation of why a broker's
    commentary is self_reported, and a text grep fails on the explanation."""
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
        assert word not in code, word


def test_matching_is_substring_only_and_not_fuzzy():
    """No stemming, no synonyms, no edit distance — each would turn 'quoted the
    document' back into 'said something like it'."""
    import ast
    import inspect

    import tools.market_bet as mb
    code = ast.unparse(ast.parse(inspect.getsource(mb.signal_grounded))).lower()
    for forbidden in ("difflib", "ratio", "fuzz", "levenshtein", "stem", "token_set"):
        assert forbidden not in code
