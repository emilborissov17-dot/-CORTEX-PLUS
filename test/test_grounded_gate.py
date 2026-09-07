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
                              normalise, parse_completion, parse_signal_indices,
                              render_evidence, segment_snippets, segment_text,
                              signal_dated_after, signal_grounded)

DEADLINE = "2026-09-08"
FACT = "CPI rose 0.3% in August, the Bureau of Labor Statistics said on Friday"

# The default fixture segments to exactly two: [1] the title, [2] the sentence.
TITLE_SEG, FACT_SEG = 1, 2


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


def _c(direction="UP", signal=FACT_SEG, driver="MACRO",
       logic="higher yields weigh on equities", deadline=DEADLINE):
    return (f"DIRECTION: {direction}\nDEADLINE: {deadline}\n"
            f"RATIONALE: DRIVER {driver} | SIGNAL {signal} | LOGIC {logic}")


def _g(*comps, snippets=(Sn(),), deadline=DEADLINE):
    return grounded_gate([parse_completion(c) for c in comps], "SPY", deadline,
                         list(snippets))


# ── R49/8. an in-range INDEX is ADMITTED and carries the exact sentence ─────
def test_an_in_range_index_is_admitted_with_the_exact_sentence_text():
    r = _g(_c(signal=FACT_SEG))[0]
    assert r["verdict"] == "ADMITTED", r.get("refusal")
    assert r["parsed"]["signal_indices"] == [FACT_SEG]
    assert r["parsed"]["signal_text"] == FACT
    assert r["evidence"]["segment_text"] == FACT


def test_the_selected_text_is_verbatim_by_construction_not_by_the_model():
    """The point of the whole piece. The model wrote the character '2' and nothing
    else; every word of the citation came out of the segment table."""
    r = _g(_c(signal="2"))[0]
    assert "2" in r["raw"]
    assert FACT not in r["raw"]
    assert r["evidence"]["segment_text"] == FACT


def test_the_title_is_a_selectable_segment_like_any_other():
    r = _g(_c(signal=TITLE_SEG))[0]
    assert r["verdict"] == "ADMITTED"
    assert r["evidence"]["segment_text"] == "US inflation ticks up"
    assert r["evidence"]["sources"][0]["field"] == "title"


def test_bracketed_and_multiple_indices_are_accepted():
    r = _g(_c(signal="[1] and [2]"))[0]
    assert r["verdict"] == "ADMITTED", r.get("refusal")
    assert r["parsed"]["signal_indices"] == [1, 2]
    assert r["parsed"]["signal_text"] == f"US inflation ticks up {FACT}"
    assert r["evidence"]["spans_multiple_sources"] is False


def test_indices_from_two_documents_are_flagged_as_spanning():
    other = Sn(snippet="Gold steadied as the dollar eased on Friday.",
               title="Gold steadies", url="https://apnews.com/g", host="apnews.com")
    r = _g(_c(signal="2, 3"), snippets=(Sn(), other))[0]
    assert r["verdict"] == "ADMITTED", r.get("refusal")
    assert r["evidence"]["spans_multiple_sources"] is True
    assert {s["host"] for s in r["evidence"]["sources"]} == {"reuters.com", "apnews.com"}


# ── R49/9. an OUT-OF-RANGE index is refused ─────────────────────────────────
def test_an_out_of_range_index_is_refused():
    """A number nobody printed is an invented citation with a shorter spelling."""
    for bad in (0, 3, 99):
        r = _g(_c(signal=bad))[0]
        assert r["verdict"] == "REFUSED", bad
        assert "signal_index" in r["missing"]
        assert "out of range" in r["refusal"]


def test_a_sign_or_a_range_is_refused_rather_than_guessed():
    """'-1' had its minus dropped and read as segment 1, and '1-3' would be read as
    1 and 3 rather than the range meant. Silently deciding what the model meant is the
    habit this gate exists to break, so both refuse."""
    for bad in ("-1", "1-2", "1 to 2"):
        r = _g(_c(signal=bad))[0]
        assert r["verdict"] == "REFUSED", bad
        assert "signal_index" in r["missing"]


def test_an_empty_index_is_refused():
    r = _g(_c(signal="   "))[0]
    assert r["verdict"] == "REFUSED"
    assert "signal_index" in r["missing"]


def test_free_text_in_the_signal_field_is_refused_even_when_it_is_a_true_quote():
    """THE CONTRACT CHANGE. Under R48 this exact string was ADMITTED. It is a real
    sentence from a real document — and it is still refused, because the field now
    carries a number and text in it cannot be trusted to be verbatim."""
    r = _g(_c(signal=FACT))[0]
    assert r["verdict"] == "REFUSED"
    assert "signal_index" in r["missing"]
    assert "prose, not a segment number" in r["refusal"]


def test_a_paraphrase_is_refused_as_prose():
    """The 7 Sep failure mode, now unreachable a step earlier: a paraphrase never gets
    as far as the substring check, because it is not a number."""
    for para in ("CPI increased 0.3 percent in August",
                 "August inflation came in at 0.3%",
                 "the BLS reported a 0.3% August CPI rise"):
        r = _g(_c(signal=para))[0]
        assert r["verdict"] == "REFUSED", para
        assert "signal_index" in r["missing"]


def test_a_signal_that_names_a_number_and_prose_is_refused():
    """The live spill: the model wrote 'SIGNAL <text> LOGIC: <text>' with no pipe. Half
    a contract is not the contract."""
    r = _g(_c(signal="2 LOGIC: the index will rise"))[0]
    assert r["verdict"] == "REFUSED"
    assert "signal_index" in r["missing"]


def test_the_index_parser_reports_range_and_prose_separately():
    assert parse_signal_indices("2", 2) == ([2], None)
    assert parse_signal_indices("segments 1 and 2", 2) == ([1, 2], None)
    assert parse_signal_indices("2 2 1", 2) == ([2, 1], None)   # duplicates dropped
    assert parse_signal_indices("7", 2)[0] is None
    assert parse_signal_indices("CPI rose", 2)[0] is None


def test_the_substring_check_survives_underneath():
    """Belt and suspenders. Selection makes the text verbatim; this would still catch a
    segmentation bug that rewrote a character."""
    assert signal_grounded(FACT, [Sn()])[0] is True
    assert signal_grounded("CPI increased 0.3 percent in August", [Sn()])[0] is False


def test_a_too_short_signal_cannot_ground_itself_on_a_common_word():
    """A three-character 'signal' is a substring of almost anything."""
    assert signal_grounded("CPI", [Sn()])[0] is False
    assert signal_grounded("in August", [Sn()])[0] is False


# ── R49 PIECE 2: normalisation before any string comparison ─────────────────
def test_a_punctuation_only_difference_now_matches():
    """Under R48 this was a REFUSAL that read 'not an exact substring' — true of the
    bytes and false of the sentence. Not one word differs; the publisher used a curly
    apostrophe and an em dash, and the retyped version used ASCII."""
    published = "The Fed’s stance — unchanged — held yields steady"
    retyped = "The Fed's stance - unchanged - held yields steady"
    assert normalise(published) == normalise(retyped)
    assert signal_grounded(retyped, [Sn(snippet=published)])[0] is True


def test_nfkc_folds_the_invisible_differences():
    """A non-breaking space and a single ellipsis character are not visible in a page
    and are absolutely visible to ==."""
    assert normalise("gold steadied on… Friday") == \
        normalise("gold steadied on... Friday")
    assert normalise("co­ing") == normalise("coing")   # soft hyphen


def test_every_dash_and_quote_variant_folds_to_one():
    for dash in "‐‑‒–—―−":
        assert normalise(f"a{dash}b") == "a-b", dash
    for q in "‘’‚‛′":
        assert normalise(f"a{q}b") == "a'b", q
    for q in "“”„‟«»":
        assert normalise(f"a{q}b") == 'a"b', q
    # NFKC decomposes DOUBLE PRIME into two PRIMEs before the table runs, so it folds
    # to two apostrophes rather than a double quote. Consistent, and stated rather
    # than papered over with a table entry that never fires.
    assert normalise("a″b") == "a''b"


def test_normalisation_still_refuses_a_paraphrase():
    """Folding a glyph is spelling. Deciding two different sentences are close enough
    is meaning, and that is the thing being refused."""
    assert normalise("CPI rose 0.3%") != normalise("CPI increased 0.3 percent")
    assert signal_grounded("CPI increased 0.3 percent in August", [Sn()])[0] is False


def test_case_and_whitespace_folding_survived_the_rewrite():
    assert normalise("  A   b ") == "a b"
    assert signal_grounded("cpi   ROSE 0.3%   in august", [Sn()])[0] is True


# ── R49 segmentation ────────────────────────────────────────────────────────
def test_every_segment_is_a_contiguous_slice_of_its_source():
    """THE INVARIANT THE PIECE RESTS ON. Strip at the edges, never in the middle — the
    moment a segment stops being a literal slice, 'verbatim by construction' is a
    claim rather than a fact."""
    blob = ("## Key Points\n"
            "The S&P 500 advanced 13%. But the next downturn is only a matter of "
            "time. [...] \n"
            "  Following the first rate hike, the index usually falls into correction.")
    hay = normalise(blob)
    segs = segment_text(blob)
    assert len(segs) >= 3
    for s in segs:
        assert normalise(s) in hay, s


def test_segmentation_drops_labels_and_keeps_sentences():
    segs = segment_text("## Key Points\nNKE\n-0.95%\nThe dollar index slipped 0.2%.")
    assert segs == ["The dollar index slipped 0.2%."]


def test_numbering_is_dense_so_every_printed_number_is_selectable():
    """Holes in the list would turn a formatting accident into an out-of-range
    refusal that reads like a fabrication."""
    segs = segment_snippets([Sn(), Sn(snippet="Gold steadied as the dollar eased.",
                                      title="Gold steadies now")])
    assert [t["index"] for t in segs] == list(range(1, len(segs) + 1))


def test_the_rendered_block_prints_the_same_numbers_the_gate_reads():
    """If the prompt's [4] and the gate's [4] ever differ, index selection quietly
    stops being verbatim."""
    snippets = [Sn(), Sn(snippet="Gold steadied as the dollar eased.",
                         title="Gold steadies now", host="apnews.com")]
    segs = segment_snippets(snippets)
    block = render_evidence(snippets, segs)
    for t in segs:
        assert f"[{t['index']}] {t['text']}" in block


# ── 10. plausible but absent — the 7 Sep failure, re-run ────────────────────
def test_a_plausible_signal_that_appears_in_no_snippet_is_refused():
    r = _g(_c(signal="Nonfarm payrolls +150k, BLS 5 Sep"))[0]
    assert r["verdict"] == "REFUSED"
    assert "signal_index" in r["missing"]


# ── 11. dated after the graded session ──────────────────────────────────────
def test_a_signal_dated_after_the_graded_session_is_refused():
    """THE JACKSON HOLE CASE. On 7 Sep this was ADMITTED.

    Now checked against the RECONSTRUCTED text: selecting a real sentence that names a
    future event is still refused, because a fact that has not happened cannot have
    driven the price — being genuinely printed does not make it a driver."""
    sig = "Fed releases the Jackson Hole Symposium transcript on Sept 21."
    assert signal_dated_after(sig, DEADLINE) is True
    snippets = [Sn(snippet=sig, title="Fed calendar update")]
    segs = segment_snippets(snippets)
    idx = [t["index"] for t in segs if t["text"] == sig][0]
    r = grounded_gate([parse_completion(_c(signal=idx))], "SPY", DEADLINE, snippets)[0]
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
    r = _g(_c(signal=FACT_SEG))[0]
    assert r["evidence"]["url"].startswith("https://www.reuters.com/")
    assert r["evidence"]["published_utc"] == "2026-09-05T12:30:00+00:00"
    assert r["evidence"]["host"] == "reuters.com"
    assert r["evidence"]["segment_indices"] == [FACT_SEG]
    assert r["evidence"]["segments_available"] == 2


def test_a_refused_candidate_carries_no_evidence():
    r = _g(_c(signal="something absent entirely from the snippet"))[0]
    assert "evidence" not in r


# ── 12. no snippets at all ──────────────────────────────────────────────────
def test_with_no_snippets_every_candidate_is_refused():
    """An asset with no fact gets no bet, and there is no fallback."""
    recs = _g(_c(), _c("DOWN"), snippets=())
    assert [r["verdict"] for r in recs] == ["REFUSED", "REFUSED"]
    # With no snippets there are no segments, so EVERY number is out of range 1..0.
    assert all("out of range" in r["refusal"] for r in recs)
    assert all("1..0" in r["refusal"] for r in recs)


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
    # Under R49 they die a step EARLIER than they did under R48: every one of them is
    # free text, and the SIGNAL field now carries a number. The invented facts never
    # reach the substring check at all.
    assert all("signal_index" in (why or "") for _, _, why in refused)


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


# ── the undated-evidence crash the R48 dry run found ────────────────────────
def test_an_undated_snippet_can_carry_the_evidence_without_crashing():
    """`getattr(sn, 'published_utc') or sn.get(...)` looked harmless and was not: an
    undated snippet has published_utc == "", which is FALSY, so the fallback fired on a
    dataclass that has no .get and the whole run died. Only the asset staged with
    undated evidence reached it."""
    undated = Sn(published_utc="", dated=False, host="fool.com",
                 source_class="adversarial", source_kind="advisory with positions")
    r = grounded_gate([parse_completion(_c(signal=FACT_SEG))],
                      "SPY", DEADLINE, [undated])[0]
    assert r["verdict"] == "ADMITTED"
    assert r["evidence"]["published_utc"] is None
    assert r["evidence"]["dated"] is False
    assert r["evidence"]["source_class"] == "adversarial"


def test_a_dated_snippet_reports_dated_true():
    r = _g(_c(signal=FACT_SEG))[0]
    assert r["evidence"]["dated"] is True
    assert r["evidence"]["published_utc"] == "2026-09-05T12:30:00+00:00"
