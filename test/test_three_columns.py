#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_three_columns.py — THREE WITNESSES, AND NO AVERAGE TO HIDE BEHIND.

The load-bearing claim of this module is negative: there are things it REFUSES
to produce. A weighted average always produces a number, and that is its defect —
three sources that flatly contradict each other yield a confident figure sitting
in a gap where no witness placed the value. Most of the tests below check that
no number appears where none is warranted.

  * a HARD_FAULT has NO consensus value. Not a fallback, not the nearest
    witness, not a mean of the three. None.
  * a qualitative claim NEVER gets a consensus, at any level of agreement. There
    is no midpoint between "free" and "stolen".
  * MUST_UNPACK is enforceable, so a consumer can ask before summarising.
  * a demoted source that turns out to be right EMITS A SIGNAL rather than
    quietly staying excluded — otherwise demotion is a one-way door.
  * every row carries a url, at construction AND at write time.

    venv\\Scripts\\python.exe -m pytest test/test_three_columns.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import three_columns as tc  # noqa: E402


def E(source, col, ctype=tc.RATE, est=None, err=0.0, text="", url=None):
    return tc.Entry(source, url or f"https://{source}.example/1", col, ctype,
                    estimate=est, error=err, text=text)


def THREE(a, b, c, err=1.0):
    return [E("Stat", tc.SELF_REPORTED, est=a, err=err),
            E("Sat", tc.INDEPENDENT, est=b, err=err),
            E("Watch", tc.ADVERSARIAL, est=c, err=err)]


# ---------------------------------------------------------------------------
# The columns are the repo's own taxonomy
# ---------------------------------------------------------------------------

def test_the_columns_are_exactly_the_placeable_independence_classes():
    cfg = json.loads((REPO / "config" / "reporter_independence.json")
                     .read_text(encoding="utf-8"))
    classes = set(cfg["_classes"])
    assert set(tc.COLUMNS) | {tc.UNKNOWN_CLASS} == classes, (
        "this module's columns drifted from config/reporter_independence.json. "
        "CLAUDE.md: there are exactly four classes and no fifth may be invented")
    assert tc.UNKNOWN_CLASS not in tc.COLUMNS, (
        "`unknown` means 'never inferred to be independent' — it cannot be a column")


def test_an_invented_column_is_refused():
    with pytest.raises(ValueError, match="forbids a fifth"):
        tc.Entry("x", "https://a", "semi_independent", tc.RATE, 1.0)


def test_an_unknown_claim_type_is_refused():
    with pytest.raises(ValueError, match="unknown claim type"):
        tc.Entry("x", "https://a", tc.INDEPENDENT, "vibe", 1.0)


# ---------------------------------------------------------------------------
# Intersection edge cases
# ---------------------------------------------------------------------------

def test_overlapping_intervals_give_the_midpoint_of_the_overlap():
    r = tc.compare("c", "AX", THREE(5.0, 5.5, 6.0), track={})
    assert r["intersection"] == [5.0, 6.0]
    assert r["consensus"] == 5.5


def test_the_consensus_is_the_midpoint_and_not_a_weighted_average():
    """Two witnesses near 10 and one near 12 that still overlap. A mean would be
    pulled toward the crowd; the midpoint of the shared region is not."""
    ents = [E("a", tc.SELF_REPORTED, est=10.0, err=2.0),
            E("b", tc.INDEPENDENT, est=10.0, err=2.0),
            E("c", tc.ADVERSARIAL, est=12.0, err=2.0)]
    r = tc.compare("c", "AX", ents, track={})
    assert r["intersection"] == [10.0, 12.0]
    assert r["consensus"] == 11.0, (
        "the consensus moved toward the two agreeing witnesses; that is a "
        "weighted average wearing a midpoint's name")


def test_non_overlapping_intervals_are_a_hard_fault_with_no_consensus():
    r = tc.compare("c", "AX", THREE(2.0, 9.0, 20.0, err=0.1), track={})
    assert tc.HARD_FAULT in [f["kind"] for f in r["faults"]]
    assert r["consensus"] is None, (
        "a number was produced from three witnesses who agree on nothing")
    assert r["intersection"] is None


def test_two_that_overlap_and_one_that_does_not_is_still_a_hard_fault():
    """The intersection is of ALL THREE. A majority is not a consensus."""
    r = tc.compare("c", "AX", THREE(5.0, 5.2, 40.0, err=0.5), track={})
    assert tc.HARD_FAULT in [f["kind"] for f in r["faults"]]
    assert r["consensus"] is None


def test_intervals_touching_at_exactly_one_point_do_intersect():
    """Zero WIDTH is not zero overlap — they agree on exactly one value."""
    ents = [E("a", tc.SELF_REPORTED, est=1.0, err=1.0),    # [0, 2]
            E("b", tc.INDEPENDENT, est=3.0, err=1.0)]      # [2, 4]
    r = tc.compare("c", "AX", ents, track={})
    assert r["intersection"] == [2.0, 2.0]
    assert r["consensus"] == 2.0


def test_identical_point_estimates_with_no_error_agree_completely():
    ents = [E("a", tc.SELF_REPORTED, est=7.0, err=0.0),
            E("b", tc.INDEPENDENT, est=7.0, err=0.0)]
    r = tc.compare("c", "AX", ents, track={})
    assert r["consensus"] == 7.0
    assert r["epistemic_tension"] == 0.0
    assert r["band"] == "green"


def test_a_single_witness_is_not_a_comparison():
    r = tc.compare("c", "AX", [E("a", tc.INDEPENDENT, est=1.0, err=1.0)], track={})
    assert "INSUFFICIENT_WITNESSES" in [f["kind"] for f in r["faults"]]
    assert r["consensus"] is None


def test_intersect_handles_an_empty_list():
    assert tc.intersect([]) is None
    assert tc.intersect([None, None]) is None


def test_a_negative_error_bar_is_treated_as_a_width():
    e = tc.Entry("a", "https://a", tc.INDEPENDENT, tc.RATE, 5.0, -2.0)
    assert e.interval == (3.0, 7.0), "a sign error must not invert an interval"


# ---------------------------------------------------------------------------
# ET bounds
# ---------------------------------------------------------------------------

def test_quantitative_tension_is_zero_when_they_agree_exactly():
    assert tc.epistemic_tension_quantitative([(0.0, 10.0), (0.0, 10.0)]) == 0.0


def test_quantitative_tension_is_one_when_they_do_not_overlap():
    assert tc.epistemic_tension_quantitative([(0.0, 1.0), (5.0, 6.0)]) == 1.0


@pytest.mark.parametrize("intervals", [
    [(0.0, 10.0), (0.0, 10.0), (0.0, 10.0)],
    [(0.0, 1.0), (0.5, 1.5)],
    [(0.0, 1.0), (0.99, 2.0)],
    [(-5.0, 5.0), (-1.0, 1.0)],
    [(0.0, 0.0), (0.0, 0.0)],
    [(1e9, 2e9), (1.5e9, 1.6e9)],
])
def test_quantitative_tension_always_lands_in_the_unit_interval(intervals):
    et = tc.epistemic_tension_quantitative(intervals)
    assert 0.0 <= et <= 1.0, f"{intervals} -> {et}"


def test_one_interval_has_no_tension():
    assert tc.epistemic_tension_quantitative([(0.0, 1.0)]) == 0.0


def test_zero_width_agreeing_intervals_do_not_divide_by_zero():
    assert tc.epistemic_tension_quantitative([(3.0, 3.0), (3.0, 3.0)]) == 0.0


def test_qualitative_tension_is_zero_for_identical_accounts():
    assert tc.epistemic_tension_qualitative(["the river flooded", "the river flooded"]) == 0.0


def test_qualitative_tension_is_high_for_unrelated_accounts():
    et = tc.epistemic_tension_qualitative(
        ["the election was free and fair", "ballot stuffing at many stations"])
    assert et > tc.RED_ABOVE


def test_qualitative_tension_bounds():
    for texts in (["a"], ["a", "b"], ["", ""], ["x y z", "x y z", "q"]):
        assert 0.0 <= tc.epistemic_tension_qualitative(texts) <= 1.0


def test_cosine_is_bounded_and_symmetric():
    a, b = tc.bag_of_words("alpha beta"), tc.bag_of_words("beta gamma")
    assert 0.0 <= tc.cosine(a, b) <= 1.0
    assert tc.cosine(a, b) == tc.cosine(b, a)
    assert tc.cosine({}, a) == 0.0


def test_the_default_vectoriser_is_offline_and_deterministic():
    assert tc.bag_of_words("The RIVER, the river!") == tc.bag_of_words("the river the RIVER")


# ---------------------------------------------------------------------------
# Bands and MUST_UNPACK
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("et,expected", [
    (0.0, "green"), (0.29, "green"), (0.3, "yellow"),
    (0.5, "yellow"), (0.7, "yellow"), (0.71, "red"), (1.0, "red"),
])
def test_the_bands_are_where_the_ruling_put_them(et, expected):
    assert tc.band(et) == expected


def test_a_red_record_is_marked_must_unpack_and_refuses_aggregation():
    r = tc.compare("c", "AX", THREE(2.0, 9.0, 20.0, err=0.1), track={})
    assert tc.MUST_UNPACK in r["signals"]
    assert tc.may_aggregate(r) is False, (
        "an average of witnesses this far apart is not a summary, it is a "
        "fabrication with a small standard error")


def test_a_green_record_may_be_aggregated():
    r = tc.compare("c", "AX", THREE(5.0, 5.0, 5.0, err=1.0), track={})
    assert tc.may_aggregate(r) is True


# ---------------------------------------------------------------------------
# Qualitative is never merged
# ---------------------------------------------------------------------------

def test_a_qualitative_claim_never_gets_a_consensus_even_when_they_agree():
    q = [E("a", tc.SELF_REPORTED, tc.CLAIM, text="the dam held through the storm"),
         E("b", tc.INDEPENDENT, tc.CLAIM, text="the dam held through the storm")]
    r = tc.compare("c", "AX", q, track={})
    assert r["epistemic_tension"] == 0.0
    assert r["consensus"] is None, (
        "agreement is not a licence to merge accounts; there is still no "
        "midpoint between two sentences")


def test_accounts_are_kept_side_by_side_in_their_own_columns():
    q = [E("a", tc.SELF_REPORTED, tc.CLAIM, text="story one"),
         E("b", tc.INDEPENDENT, tc.CLAIM, text="story two")]
    r = tc.compare("c", "AX", q, track={})
    assert len(r["columns"][tc.SELF_REPORTED]) == 1
    assert len(r["columns"][tc.INDEPENDENT]) == 1
    assert r["columns"][tc.SELF_REPORTED][0]["text"] == "story one"


def test_disagreeing_accounts_raise_a_soft_fault():
    q = [E("a", tc.SELF_REPORTED, tc.CLAIM, text="the election was free and fair"),
         E("b", tc.INDEPENDENT, tc.CLAIM, text="ballot stuffing was recorded widely")]
    r = tc.compare("c", "AX", q, track={})
    assert tc.SOFT_FAULT in [f["kind"] for f in r["faults"]]


def test_agreeing_accounts_raise_no_soft_fault():
    q = [E("a", tc.SELF_REPORTED, tc.CLAIM, text="the dam held through the storm"),
         E("b", tc.INDEPENDENT, tc.CLAIM, text="the dam held through the storm")]
    r = tc.compare("c", "AX", q, track={})
    assert tc.SOFT_FAULT not in [f["kind"] for f in r["faults"]]


def test_an_injected_embedder_is_used_instead_of_bag_of_words():
    called = []

    def _embed(text):
        called.append(text)
        return {"same": 1.0}

    q = [E("a", tc.SELF_REPORTED, tc.CLAIM, text="totally different"),
         E("b", tc.INDEPENDENT, tc.CLAIM, text="words entirely")]
    r = tc.compare("c", "AX", q, track={}, embed=_embed)
    assert called, "the injected embedder was ignored"
    assert r["epistemic_tension"] == 0.0


# ---------------------------------------------------------------------------
# Demotion and the way back
# ---------------------------------------------------------------------------

def test_an_unknown_class_source_is_demoted_by_definition():
    demoted, why = tc.is_demoted("x", tc.RATE, tc.UNKNOWN_CLASS, {})
    assert demoted and "never inferred to be independent" in why


def test_a_source_with_more_falsifications_than_confirmations_is_demoted():
    track = {}
    tc.note_physical_check(track, "Src", tc.RATE, confirmed=False)
    tc.note_physical_check(track, "Src", tc.RATE, confirmed=False)
    tc.note_physical_check(track, "Src", tc.RATE, confirmed=True)
    assert tc.is_demoted("Src", tc.RATE, tc.INDEPENDENT, track)[0] is True


def test_the_track_record_is_kept_per_type_not_per_source():
    """A statistical office may report population accurately and inflation
    politically. One number for the source lets the first launder the second."""
    track = {}
    tc.note_physical_check(track, "Src", tc.RATE, confirmed=False)
    assert tc.is_demoted("Src", tc.RATE, tc.INDEPENDENT, track)[0] is True
    assert tc.is_demoted("Src", tc.STOCK, tc.INDEPENDENT, track)[0] is False


def test_a_demoted_source_is_excluded_from_the_arithmetic():
    track = {}
    tc.note_physical_check(track, "Liar", tc.RATE, confirmed=False)
    ents = THREE(5.0, 5.5, 6.0) + [E("Liar", tc.INDEPENDENT, est=999.0, err=0.1)]
    r = tc.compare("c", "AX", ents, track=track)
    assert r["intersection"] == [5.0, 6.0], (
        "the demoted witness moved the intersection; exclusion from the "
        "arithmetic is the whole meaning of demotion")
    assert r["consensus"] == 5.5


def test_a_demoted_source_is_still_stored_for_its_own_panel():
    track = {}
    tc.note_physical_check(track, "Liar", tc.RATE, confirmed=False)
    ents = THREE(5.0, 5.5, 6.0) + [E("Liar", tc.INDEPENDENT, est=999.0, err=0.1)]
    r = tc.compare("c", "AX", ents, track=track)
    assert len(r["demoted"]) == 1
    assert r["demoted"][0]["source"] == "Liar"
    assert r["demoted"][0]["demoted_because"]
    assert r["demoted"][0]["url"]


def test_a_demoted_claim_inside_the_trusted_intersection_asks_for_review():
    """The rehabilitation path. Without it, demotion is a one-way door and a
    source that improves can never be noticed."""
    track = {}
    tc.note_physical_check(track, "Old", tc.RATE, confirmed=False)
    ents = THREE(5.0, 5.5, 6.0) + [E("Old", tc.INDEPENDENT, est=5.4, err=0.2)]
    r = tc.compare("c", "AX", ents, track=track)
    assert tc.DEMOTION_REVIEW in r["signals"]
    assert r["demotion_review"][0]["source"] == "Old"
    assert r["demotion_review"][0]["url"]


def test_a_demoted_claim_far_from_the_intersection_asks_for_nothing():
    track = {}
    tc.note_physical_check(track, "Old", tc.RATE, confirmed=False)
    ents = THREE(5.0, 5.5, 6.0) + [E("Old", tc.INDEPENDENT, est=900.0, err=0.2)]
    r = tc.compare("c", "AX", ents, track=track)
    assert tc.DEMOTION_REVIEW not in r["signals"]


def test_a_demoted_qualitative_account_that_agrees_asks_for_review():
    track = {}
    tc.note_physical_check(track, "Old", tc.CLAIM, confirmed=False)
    q = [E("a", tc.SELF_REPORTED, tc.CLAIM, text="the dam held through the storm"),
         E("b", tc.INDEPENDENT, tc.CLAIM, text="the dam held through the storm"),
         E("Old", tc.INDEPENDENT, tc.CLAIM, text="the dam held through the storm")]
    r = tc.compare("c", "AX", q, track=track)
    assert tc.DEMOTION_REVIEW in r["signals"]


# ---------------------------------------------------------------------------
# The link rule
# ---------------------------------------------------------------------------

def test_an_entry_without_a_url_is_refused_at_construction():
    with pytest.raises(tc.LinkRequired):
        tc.Entry("x", "", tc.INDEPENDENT, tc.RATE, 1.0)


def test_a_whitespace_url_is_refused():
    with pytest.raises(tc.LinkRequired):
        tc.Entry("x", "   ", tc.INDEPENDENT, tc.RATE, 1.0)


def test_a_record_whose_row_lost_its_url_is_refused_at_write_time(tmp_path):
    r = tc.compare("c", "AX", THREE(5.0, 5.5, 6.0), track={})
    r["columns"][tc.INDEPENDENT][0]["url"] = ""
    with pytest.raises(tc.LinkRequired, match="no url"):
        tc.save_record(r, store=tmp_path)


def test_a_demoted_row_without_a_url_is_refused_too(tmp_path):
    track = {}
    tc.note_physical_check(track, "Liar", tc.RATE, confirmed=False)
    ents = THREE(5.0, 5.5, 6.0) + [E("Liar", tc.INDEPENDENT, est=9.0, err=0.1)]
    r = tc.compare("c", "AX", ents, track=track)
    r["demoted"][0]["url"] = ""
    with pytest.raises(tc.LinkRequired):
        tc.save_record(r, store=tmp_path)


def test_a_good_record_round_trips(tmp_path):
    r = tc.compare("claim/with:odd*chars", "AX", THREE(5.0, 5.5, 6.0), track={})
    p = tc.save_record(r, store=tmp_path)
    assert p.exists()
    back = tc.load_records(store=tmp_path)
    assert len(back) == 1 and back[0]["consensus"] == 5.5


# ---------------------------------------------------------------------------
# Per axis
# ---------------------------------------------------------------------------

def test_axis_tension_is_the_mean_over_active_claims():
    recs = [{"axis": "AX", "epistemic_tension": 0.2, "claim_id": "a"},
            {"axis": "AX", "epistemic_tension": 0.8, "claim_id": "b"}]
    assert tc.axis_tension(recs, "AX")["et_axis"] == pytest.approx(0.5)


def test_the_top_three_are_stored_explicitly_so_the_mean_cannot_hide_them():
    """Forty quiet claims and three contradictions average to a comfortable
    number. The three worst are named, with their ids."""
    recs = [{"axis": "AX", "epistemic_tension": 0.01, "claim_id": f"quiet{i}"}
            for i in range(40)]
    recs += [{"axis": "AX", "epistemic_tension": 0.95, "claim_id": "loud1"},
             {"axis": "AX", "epistemic_tension": 0.92, "claim_id": "loud2"},
             {"axis": "AX", "epistemic_tension": 0.90, "claim_id": "loud3"}]
    out = tc.axis_tension(recs, "AX")
    assert out["band"] == "green", "the mean really is comfortable here"
    assert [t["claim_id"] for t in out["top3"]] == ["loud1", "loud2", "loud3"], (
        "the mean was reported without the claims that make it a lie")


def test_axis_tension_counts_must_unpack_and_hard_faults():
    r1 = tc.compare("a", "AX", THREE(2.0, 9.0, 20.0, err=0.1), track={})
    r2 = tc.compare("b", "AX", THREE(5.0, 5.0, 5.0, err=1.0), track={})
    out = tc.axis_tension([r1, r2], "AX")
    assert out["must_unpack"] == 1 and out["hard_faults"] == 1


def test_an_axis_with_no_claims_is_not_an_error():
    out = tc.axis_tension([], "AX")
    assert out["claims"] == 0 and out["et_axis"] == 0.0 and out["top3"] == []


def test_claims_from_another_axis_are_not_counted():
    recs = [{"axis": "AX", "epistemic_tension": 0.1, "claim_id": "a"},
            {"axis": "OTHER", "epistemic_tension": 0.9, "claim_id": "b"}]
    assert tc.axis_tension(recs, "AX")["claims"] == 1


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------

def test_the_selftest_says_NOT_WIRED(capsys):
    tc._selftest()
    assert "NOT WIRED" in capsys.readouterr().out
