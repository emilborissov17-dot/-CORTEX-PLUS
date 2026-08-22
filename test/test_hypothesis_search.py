#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_hypothesis_search.py — ZERO HYPOTHESES IS FINE. AN INVENTED ONE IS NOT.

Three things are held here, and the canned model outputs below are the shapes a
3b model actually produces rather than the shape a contract wishes it produced:

  * FAIL-CLOSED PARSING. Truncated JSON, prose, a confidence of "high", a
    hypothesis that is a bare string — each is DROPPED with a reason, never
    repaired. A lenient parser here would manufacture research questions out of
    parse errors, and a hypothesis is not a harmless artifact: it decides what
    the system spends its next fetches on.
  * THE MAPPER NEVER GUESSES A CODE. GDELT themes are a controlled vocabulary,
    and a wrong-but-well-formed code returns an empty result set that reads
    exactly like "nothing is happening". No entry means SKIP, with the skip
    visible so a caller can tell "looked and found nothing" from "never looked".
  * INFORMATION GAIN, NOT RECALL. A query returning a hundred articles that
    mention the topic must rank BELOW one returning two that settle the question.

    venv\\Scripts\\python.exe -m pytest test/test_hypothesis_search.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import hypothesis_search as hs  # noqa: E402


GOOD = json.dumps({"hypotheses": [
    {"hypothesis": "Grid storage additions outpaced solar curtailment in 2026.",
     "seeking": ["monthly curtailment figures", "storage MW added"],
     "confidence": 0.4, "youtube": ["grid curtailment 2026"], "github": ["grid-sim"]},
    {"hypothesis": "European gas demand fell despite a cold winter.",
     "seeking": ["gas demand by month"], "confidence": 0.6},
]})


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "hypotheses.jsonl"


# ---------------------------------------------------------------------------
# (a) The contract
# ---------------------------------------------------------------------------

def test_a_well_formed_reply_yields_hypotheses():
    got, rej = hs.parse_hypotheses(GOOD, axis="ENERGY_REVIEW")
    assert len(got) == 2 and not rej
    assert got[0].seeking and 0.0 <= got[0].confidence <= 1.0
    assert got[0].axis == "ENERGY_REVIEW"
    assert got[0].id and got[0].id != got[1].id


@pytest.mark.parametrize("label,raw", [
    ("truncated mid-object", '{"hypotheses":[{"hypothesis":"h","seeking":'),
    ("prose, no JSON", "Sure! Here are five hypotheses you might consider."),
    ("empty string", ""),
    ("null", "null"),
    ("a JSON number", "42"),
    ("object without the key", '{"result": "ok"}'),
    ("hypotheses is not a list", '{"hypotheses": "three of them"}'),
])
def test_junk_yields_zero_hypotheses_and_a_reason(label, raw):
    got, rej = hs.parse_hypotheses(raw, axis="X")
    assert got == [], f"{label} produced a hypothesis out of nothing"
    assert rej and rej[0].get("reason"), f"{label} was rejected without a reason"


@pytest.mark.parametrize("bad,why", [
    ({"seeking": ["s"], "confidence": 0.5}, "hypothesis missing"),
    ({"hypothesis": "", "seeking": ["s"], "confidence": 0.5}, "empty hypothesis"),
    ({"hypothesis": "h", "confidence": 0.5}, "seeking missing"),
    ({"hypothesis": "h", "seeking": [], "confidence": 0.5}, "seeking empty"),
    ({"hypothesis": "h", "seeking": [None, 3], "confidence": 0.5}, "seeking unusable"),
    ({"hypothesis": "h", "seeking": ["s"]}, "confidence missing"),
    ({"hypothesis": "h", "seeking": ["s"], "confidence": "high"}, "confidence text"),
    ({"hypothesis": "h", "seeking": ["s"], "confidence": 1.4}, "confidence out of range"),
    ({"hypothesis": "h", "seeking": ["s"], "confidence": -0.1}, "negative confidence"),
    ({"hypothesis": "h", "seeking": ["s"], "confidence": True}, "bool is not a number"),
    ("just a string", "item is not an object"),
])
def test_each_malformed_item_is_dropped_with_its_reason(bad, why):
    raw = json.dumps({"hypotheses": [bad]})
    got, rej = hs.parse_hypotheses(raw, axis="X")
    assert got == [], f"{why}: accepted anyway"
    assert len(rej) == 1 and rej[0]["reason"]


def test_one_bad_item_does_not_discard_the_good_ones():
    raw = json.dumps({"hypotheses": [
        {"hypothesis": "good", "seeking": ["s"], "confidence": 0.5},
        {"hypothesis": "bad", "seeking": [], "confidence": 0.5},
    ]})
    got, rej = hs.parse_hypotheses(raw, axis="X")
    assert [h.hypothesis for h in got] == ["good"]
    assert len(rej) == 1


def test_more_than_asked_for_is_capped_and_the_excess_is_reported():
    raw = json.dumps({"hypotheses": [
        {"hypothesis": f"h{i}", "seeking": ["s"], "confidence": 0.5}
        for i in range(9)]})
    got, rej = hs.parse_hypotheses(raw, axis="X", n=5)
    assert len(got) == 5
    assert any("beyond the 5" in r["reason"] for r in rej)


def test_an_empty_list_is_a_valid_answer_not_an_error():
    got, rej = hs.parse_hypotheses('{"hypotheses": []}', axis="X")
    assert got == [] and rej == [], (
        "returning nothing is a legitimate outcome — the prompt says so in those "
        "words, and treating it as failure is what produces padding")


def test_json_inside_a_code_fence_and_after_think_tags_is_found():
    for wrapped in (f"```json\n{GOOD}\n```",
                    f"<think>reasoning...</think>{GOOD}",
                    f"Here you go:\n```\n{GOOD}\n```\nHope that helps!"):
        got, _ = hs.parse_hypotheses(wrapped, axis="X")
        assert len(got) == 2, "the 3b's usual wrappers defeated the extractor"


def test_a_bare_list_is_accepted_as_well_as_an_object():
    raw = json.dumps([{"hypothesis": "h", "seeking": ["s"], "confidence": 0.5}])
    got, _ = hs.parse_hypotheses(raw, axis="X")
    assert len(got) == 1


def test_query_variants_are_taken_but_never_invented():
    got, _ = hs.parse_hypotheses(GOOD, axis="X")
    assert got[0].youtube == ["grid curtailment 2026"]
    assert got[1].youtube == [] and got[1].github == [], (
        "the second hypothesis offered no phrases; inventing them is exactly the "
        "failure the fail-closed rule exists to prevent")


def test_variants_are_capped_at_three():
    raw = json.dumps({"hypotheses": [{
        "hypothesis": "h", "seeking": ["s"], "confidence": 0.5,
        "youtube": ["a", "b", "c", "d", "e"]}]})
    got, _ = hs.parse_hypotheses(raw, axis="X")
    assert len(got[0].youtube) == 3


# ---------------------------------------------------------------------------
# The prompt and the call
# ---------------------------------------------------------------------------

def test_the_prompt_carries_the_axis_the_priorities_and_the_claims():
    p = hs.build_prompt("ENERGY_REVIEW",
                        prio={"THREAT": ["WATER_REVIEW"], "WATCH": ["FOOD_REVIEW"]},
                        claims=[{"claim": "grid is short", "status": "confirmed"}])
    assert "ENERGY_REVIEW" in p and "WATER_REVIEW" in p and "FOOD_REVIEW" in p
    assert "grid is short" in p and "[confirmed]" in p
    assert "JSON only" in p


def test_the_prompt_tells_a_small_model_that_fewer_is_allowed():
    p = hs.build_prompt("X", prio={"THREAT": [], "WATCH": []}, claims=[])
    assert "FEWER IS BETTER THAN PADDED" in p, (
        "a 3b told 'give me exactly 5' pads to five with restatements")


def test_propose_refuses_to_pick_a_model_for_itself():
    with pytest.raises(ValueError, match="ask"):
        hs.propose("ENERGY_REVIEW")


def test_propose_uses_the_injected_model():
    got, rej = hs.propose("ENERGY_REVIEW", ask=lambda prompt: GOOD,
                          prio={"THREAT": [], "WATCH": []}, claims=[])
    assert len(got) == 2 and not rej


def test_a_model_that_raises_yields_no_hypotheses_and_says_why():
    def _boom(prompt):
        raise RuntimeError("ollama is down")

    got, rej = hs.propose("X", ask=_boom, prio={"THREAT": [], "WATCH": []}, claims=[])
    assert got == []
    assert "ollama is down" in rej[0]["reason"]


# ---------------------------------------------------------------------------
# (b) The deterministic mapper
# ---------------------------------------------------------------------------

def _h(axis="ENERGY_REVIEW", **kw):
    kw.setdefault("seeking", ["grid capacity figures"])
    return hs.Hypothesis(kw.pop("hypothesis", "h"), kw.pop("seeking"),
                         kw.pop("confidence", 0.5), axis=axis, **kw)


def test_a_mapped_axis_produces_a_gdelt_query_with_a_real_theme_code():
    qs = {q["source"]: q for q in hs.to_queries(_h())}
    assert qs["GDELT"]["skipped_reason"] is None
    assert "theme:ENV_OIL" in qs["GDELT"]["query"]


def test_an_unmapped_axis_is_skipped_never_guessed():
    qs = {q["source"]: q for q in hs.to_queries(_h(axis="MADE_UP_AXIS"))}
    assert qs["GDELT"]["query"] is None
    assert "skipping rather than guessing" in qs["GDELT"]["skipped_reason"]
    assert qs["arXiv"]["query"] is None


def test_the_skip_is_visible_rather_than_the_source_being_absent():
    sources = {q["source"] for q in hs.to_queries(_h(axis="MADE_UP_AXIS"))}
    assert {"GDELT", "arXiv", "YouTube", "GitHub"} <= sources, (
        "a skipped source vanished from the plan; the caller cannot then tell "
        "'we looked and found nothing' from 'we never looked'")


def test_an_unknown_location_is_skipped_not_defaulted():
    qs = {q["source"]: q for q in hs.to_queries(_h(), location="Wakanda")}
    assert qs["GDELT"]["query"] is None
    assert "no FIPS code" in qs["GDELT"]["skipped_reason"]


def test_locations_use_fips_not_iso():
    """FIPS and ISO disagree exactly where it matters: UK is UK in FIPS, GB in ISO."""
    assert hs.GDELT_LOCATIONS["united kingdom"] == "UK"
    assert hs.GDELT_LOCATIONS["germany"] == "GM"        # ISO would be DE


def test_world_means_no_location_filter():
    q = {x["source"]: x for x in hs.to_queries(_h(), location="world")}["GDELT"]
    assert "locationcc" not in q["query"]


def test_arxiv_uses_the_category_and_exactly_one_seeking_term():
    q = {x["source"]: x for x in hs.to_queries(
        _h(seeking=["grid capacity figures", "second thing", "third"]))}["arXiv"]
    assert "cat:eess.SY" in q["query"]
    assert q["query"].count("all:") == 1, "more than one seeking term was used"


def test_a_hypothesis_with_nothing_seekable_skips_arxiv():
    q = {x["source"]: x for x in hs.to_queries(_h(seeking=["!!", "?"]))}["arXiv"]
    assert q["query"] is None and "nothing to seek" in q["skipped_reason"]


def test_the_mapper_is_deterministic():
    h = _h(youtube=["a", "b"], github=["c"])
    assert hs.to_queries(h) == hs.to_queries(h)


def test_every_produced_query_carries_a_url():
    for q in hs.to_queries(_h(youtube=["a"], github=["b"])):
        if q["skipped_reason"] is None:
            assert q["url"], f"{q['source']} produced a query with no url"


# ---------------------------------------------------------------------------
# (c) The ledger
# ---------------------------------------------------------------------------

def test_a_hypothesis_opens_as_pending(ledger):
    rec = hs.open_hypothesis(_h(), path=ledger)
    assert rec["status"] == hs.PENDING and rec["cycles"] == 0


def test_opening_the_same_hypothesis_twice_does_not_duplicate_it(ledger):
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    hs.open_hypothesis(h, path=ledger)
    assert len(hs.read_ledger(ledger)) == 1


def test_no_verdict_before_three_cycles(ledger):
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    for _ in range(2):
        rec = hs.record_evidence(h.id, ["https://a"], supporting=1, path=ledger)
    assert rec["status"] == hs.PENDING


def test_after_three_cycles_supporting_evidence_confirms(ledger):
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    for i in range(3):
        rec = hs.record_evidence(h.id, [f"https://a{i}"], supporting=1, path=ledger)
    assert rec["status"] == hs.CONFIRMED


def test_after_three_cycles_refuting_evidence_falsifies(ledger):
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    for i in range(3):
        rec = hs.record_evidence(h.id, [f"https://a{i}"], refuting=1, path=ledger)
    assert rec["status"] == hs.FALSIFIED


def test_three_cycles_of_nothing_is_UNKNOWN_and_not_FALSIFIED(ledger):
    """'The search found nothing' is a fact about the SEARCH. 'The evidence went
    against it' is a fact about the WORLD. Collapsing them lets a badly-formed
    query masquerade as a refutation."""
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    for i in range(3):
        rec = hs.record_evidence(h.id, [f"https://a{i}"], path=ledger)
    assert rec["status"] == hs.UNKNOWN


def test_evidence_for_an_unknown_hypothesis_returns_none(ledger):
    assert hs.record_evidence("nosuchid", ["https://a"], path=ledger) is None


def test_urls_are_deduplicated_across_cycles(ledger):
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    hs.record_evidence(h.id, ["https://a", "https://a"], path=ledger)
    rec = hs.record_evidence(h.id, ["https://a"], path=ledger)
    assert rec["urls"] == ["https://a"]


def test_a_torn_line_does_not_lose_the_rest_of_the_ledger(ledger):
    h = _h()
    hs.open_hypothesis(h, path=ledger)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write('{"id": "torn", "hypo\n')
    assert len(hs.read_ledger(ledger)) == 1


# ---------------------------------------------------------------------------
# Information gain, not recall
# ---------------------------------------------------------------------------

def test_gain_is_the_discriminating_fraction():
    assert hs.information_gain_per_fetch(
        {"docs_fetched": 10, "docs_supporting": 2, "docs_refuting": 0}) == 0.2


def test_an_untried_hypothesis_scores_highest():
    assert hs.information_gain_per_fetch({"docs_fetched": 0}) == 1.0


def test_a_hundred_irrelevant_documents_rank_below_two_decisive_ones():
    noisy = {"id": "noisy", "status": hs.PENDING, "cycles": 1,
             "docs_fetched": 100, "docs_supporting": 1, "docs_refuting": 0}
    sharp = {"id": "sharp", "status": hs.PENDING, "cycles": 1,
             "docs_fetched": 2, "docs_supporting": 1, "docs_refuting": 1}
    order = [r["id"] for r in hs.prioritize([noisy, sharp])]
    assert order == ["sharp", "noisy"], (
        "recall won over information gain — the exact inversion this module "
        "exists to correct")


def test_settled_hypotheses_are_not_asked_again():
    recs = [
        {"id": "done", "status": hs.CONFIRMED, "docs_fetched": 1, "docs_supporting": 1},
        {"id": "dead", "status": hs.FALSIFIED, "docs_fetched": 1, "docs_refuting": 1},
        {"id": "live", "status": hs.PENDING, "docs_fetched": 1, "docs_supporting": 1},
    ]
    assert [r["id"] for r in hs.prioritize(recs)] == ["live"]


def test_unknown_stays_in_the_queue():
    recs = [{"id": "u", "status": hs.UNKNOWN, "docs_fetched": 3,
             "docs_supporting": 0, "docs_refuting": 0}]
    assert [r["id"] for r in hs.prioritize(recs)] == ["u"], (
        "UNKNOWN means the search failed, not the hypothesis; it deserves "
        "another query shape")


def test_ties_break_toward_the_less_asked_question():
    a = {"id": "asked_thrice", "status": hs.PENDING, "cycles": 3, "docs_fetched": 0}
    b = {"id": "asked_once", "status": hs.PENDING, "cycles": 1, "docs_fetched": 0}
    assert [r["id"] for r in hs.prioritize([a, b])] == ["asked_once", "asked_thrice"]


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------

def test_the_knowledge_base_really_has_no_verdict_markers():
    """Pins the finding the module documents: every existing claim reads pending
    because the store has no marking, not because this module defaulted."""
    kb = json.loads((REPO / "memory" / "knowledge_base.json").read_text(encoding="utf-8"))
    fields = set()
    for entry in kb.values():
        if isinstance(entry, dict):
            fields |= set(entry)
    verdict_ish = {f for f in fields
                   if any(w in f.lower() for w in
                          ("status", "verdict", "confirm", "falsif", "pending"))}
    assert not verdict_ish, (
        f"knowledge_base.json now carries {verdict_ish}; recent_claims() should "
        f"read that instead of reporting every claim as pending")
    # And the claims themselves are bare strings, so there is nowhere per-claim
    # for a status to hide either.
    for entry in kb.values():
        for x in (entry.get("key_insights") or []) if isinstance(entry, dict) else []:
            assert isinstance(x, str), (
                "key_insights became structured; a status may now be available "
                "per claim")


def test_the_selftest_says_NOT_WIRED(capsys):
    hs._selftest()
    assert "NOT WIRED" in capsys.readouterr().out
