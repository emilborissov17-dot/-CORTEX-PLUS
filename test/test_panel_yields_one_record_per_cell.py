# -*- coding: utf-8 -*-
"""
test/test_panel_yields_one_record_per_cell.py — a panel is N observations, not one.

WHAT THIS EXISTS TO STOP (20 September 2026)
---------------------------------------------
The OpenClaw wire wrote this card and the gate accepted it:

    axis  COGNITION_LEARNING_REVIEW
    key   "Youth literacy rate (ages 15-24) %"
    value 83.3899993896484
    unit  "unknown"
    no country, no year

Measured against the body saved beside this file, that number is AFE / 2024 —
"Africa Eastern and Southern", one aggregate region, one year, selected by the
path "1.1.value" out of a page of 60 rows and a panel of 17,490 cells. The
worker was obeying a spec that asked only for "a quote and two dates".

HERMETIC. Both fixtures are committed; nothing here fetches, and nothing reads
memory/ or any journal. The whole chain — declaration, extractor, gate — runs
against the same bytes, because the two halves were green separately for a
month while the pipeline delivered a nameless number.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import observation_record as OR   # noqa: E402
from core import quote_gate as qg           # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
PANEL = FIXTURES / "worldbank_SE.ADT.1524.LT.ZS_page1.json"
COUNTRY_LIST = FIXTURES / "worldbank_country_list.json"

RETRIEVED = "2026-09-21T10:00:00+00:00"

# Assembled rather than written, so the hermeticity check below does not
# have to exempt its own needles from its own scan.
LIVE_DIR = "mem" + "ory/"
JOURNAL_NAME = "brain_" + "journal"

# The declaration as it must be written for a World Bank panel. Every path was
# read off the real body: rows at [1], the entity at countryiso3code, the period
# at date, the publication stamp at meta[0].lastupdated. The unit is NOT in the
# row — the World Bank leaves `unit` empty on all four indicators sampled on
# 21 Sep — so it is taken verbatim from the parenthetical of the indicator's own
# name, which is the source stating it rather than us inferring it.
WB = {
    "id": "scout:World Bank:ffbbf72a",
    "url": ("https://api.worldbank.org/v2/country/all/indicator/"
            "SE.ADT.1524.LT.ZS?format=json&per_page=5000"),
    "rows_path": "1",
    "entity_path": "countryiso3code",
    "period_path": "date",
    "period_granularity": "year",
    "value_path": "value",
    "unit_path": "indicator.value",
    "unit_pattern": r"\((.+)\)",
    "published_at_path": "0.lastupdated",
}


@pytest.fixture(scope="module")
def body() -> str:
    assert PANEL.exists(), f"the committed panel fixture is missing: {PANEL}"
    return PANEL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def codes():
    text = COUNTRY_LIST.read_text(encoding="utf-8")
    return (OR.countries_from_country_list(text),
            OR.aggregates_from_country_list(text))


def _extract(decl, body, codes):
    declared, aggregates = codes
    return OR.extract(decl, body, retrieved_at=RETRIEVED,
                      declared_codes=declared, aggregates=aggregates)


# ── (a) a panel yields N records, each a distinct cell ──────────────────────

def test_the_panel_yields_more_than_one_record_each_a_distinct_cell(body, codes):
    records, refusals = _extract(WB, body, codes)
    assert refusals == []
    assert len(records) > 1, "a panel collapsed into one record again"
    pairs = [(r["entity"], r["period"]) for r in records]
    assert len(set(pairs)) == len(pairs), (
        "two records share an (entity, period); one cell was emitted twice")
    # the exact cell the old card reported as a bare number
    bad = [r for r in records if r["period"] == "2024"]
    assert bad and bad[0]["entity"] == "AFE"
    assert abs(bad[0]["value"] - 83.3899993896484) < 1e-9


# ── (b) every record passes the gate against THAT SAME body ─────────────────

def test_every_record_passes_the_gate_against_the_same_body(body, codes):
    records, _ = _extract(WB, body, codes)
    verdicts = [(r["selector_path"], qg.judge_record(r, body)) for r in records]
    bad = [(p, v) for p, v in verdicts if v["verdict"] != "VERIFIED"]
    assert not bad, bad[:4]
    assert len(verdicts) == len(records)


def test_the_gate_unties_a_record_whose_entity_does_not_match_its_span(body, codes):
    """The check the card gate could not make. A span proves the number is on
    the page; only the tie proves it belongs to THIS country and year."""
    records, _ = _extract(WB, body, codes)
    r = dict(records[0])
    r["entity"] = "BGR"                      # a real code, wrong for this span
    assert qg.judge_record(r, body)["verdict"] == "UNTIED"

    r2 = dict(records[0])
    r2["period"] = "1999"
    assert qg.judge_record(r2, body)["verdict"] == "UNTIED"


def test_a_span_that_is_not_on_the_page_is_refused(body, codes):
    records, _ = _extract(WB, body, codes)
    r = dict(records[0])
    r["span"] = '{"countryiso3code":"AFE","date":"2024","value":1.0}'
    assert qg.judge_record(r, body)["verdict"] == "SPAN_NOT_ON_PAGE"


# ── (c) no entity_path -> ZERO records and one REFUSED ──────────────────────

def test_a_source_with_no_entity_path_yields_zero_records_and_one_refusal(body, codes):
    """Zero is a correct answer; one nameless number is not."""
    undeclared = {k: v for k, v in WB.items() if k != "entity_path"}
    records, refusals = _extract(undeclared, body, codes)
    assert records == []
    assert len(refusals) == 1
    assert refusals[0]["source_id"] == WB["id"]
    assert "entity_path" in refusals[0]["reason"]


def test_a_source_with_no_period_path_also_yields_zero(body, codes):
    undeclared = {k: v for k, v in WB.items() if k != "period_path"}
    records, refusals = _extract(undeclared, body, codes)
    assert records == [] and len(refusals) == 1
    assert "period_path" in refusals[0]["reason"]


# ── (d) no placeholder anywhere ─────────────────────────────────────────────

def test_no_record_carries_a_placeholder(body, codes):
    """unit:'unknown', entity:'unknown', period:None are forbidden. A
    placeholder passes every check that only tests presence, which makes it
    worse than absence — absence is visible."""
    records, _ = _extract(WB, body, codes)
    assert records
    for r in records:
        assert r["unit"] != "unknown", r
        assert r["entity"] != "unknown", r
        assert r["period"] is not None, r
        assert r["unit"] and r["unit"].strip(), r
        for f in OR.REQUIRED_FIELDS:
            assert r.get(f) not in (None, ""), (f, r["selector_path"])


def test_a_row_whose_unit_cannot_be_read_is_unverified_not_placeheld(body, codes):
    """The remedy for a missing required field is UNVERIFIED with the field
    NAMED, never a filler value."""
    no_unit = {k: v for k, v in WB.items() if k not in ("unit_path", "unit_pattern")}
    records, refusals = _extract(no_unit, body, codes)
    assert refusals == [] and records
    assert all(r["unit"] is None for r in records)
    assert all(r["verified"] is False for r in records)
    assert all("unit" in r["unverified_reason"] for r in records)


# ── the three timestamps ────────────────────────────────────────────────────

def test_period_published_at_and_retrieved_at_are_three_different_facts(body, codes):
    """None substitutes for another. The 2024 cell was published 2026-07-13 and
    fetched later still; a card that carried only the fetch date said none of
    it."""
    records, _ = _extract(WB, body, codes)
    r = [x for x in records if x["period"] == "2024"][0]
    assert r["period"] == "2024"
    assert r["published_at"] == "2026-07-13"
    assert r["retrieved_at"] == RETRIEVED
    assert r["period"] != r["published_at"] != r["retrieved_at"]

    old = [x for x in records if x["period"] == "1990"]
    assert old, "the fixture no longer carries a 1990 cell"
    assert old[0]["retrieved_at"] == RETRIEVED, (
        "a 1990 observation retrieved today: the fetch date says nothing about "
        "the reading, which is why they are separate fields")


# ── aggregates: allowed only because the SOURCE declares them ───────────────

def test_an_aggregate_is_labelled_because_the_source_declares_it(body, codes):
    """AFE is not a country. The World Bank says so itself — /v2/country marks
    every aggregate region.id == "NA" — so the code is allowed AND labelled,
    rather than inferred from its shape or silently passed off as a country."""
    declared, aggregates = codes
    assert "AFE" in aggregates and "BGR" not in aggregates
    assert "AFE" in declared and "BGR" in declared
    records, _ = _extract(WB, body, codes)
    assert all(r.get("entity_is_aggregate") for r in records)


def test_without_the_declaration_an_unconfirmable_code_is_unverified(body):
    """No country list, no way to tell a country from an aggregate — so the
    record says that, instead of promoting the code."""
    records, _ = OR.extract(WB, body, retrieved_at=RETRIEVED)
    assert records
    assert all(r["verified"] is False for r in records)
    assert all("country from an aggregate" in r["unverified_reason"]
               for r in records)


# ── the names are locked ────────────────────────────────────────────────────

def test_the_record_names_are_registered(body):
    """Rule 3: the spellings above are the only ones written, and each is in
    config/field_names.json so tools/ask.py can answer for it."""
    doc = json.loads((REPO / "config" / "field_names.json").read_text(encoding="utf-8"))
    known = {e["spelling"] for e in
             doc["concepts"]["OBSERVATION_RECORD"]["spellings"]}
    assert set(OR.RECORD_FIELDS) == known, (
        set(OR.RECORD_FIELDS) ^ known)


def test_a_record_carries_no_field_outside_the_locked_list(body, codes):
    allowed = set(OR.RECORD_FIELDS) | {"verified", "unverified_reason",
                                       "entity_is_aggregate"}
    records, _ = _extract(WB, body, codes)
    for r in records:
        assert set(r) <= allowed, set(r) - allowed


def test_nothing_here_reads_a_journal_or_live_state():
    """Hermetic by assertion, not by intention — and each half asserts the
    property that actually holds for it.

    CODE, NOT PROSE. The first version scanned raw text and failed on the word
    it was looking for, inside its own docstring explaining that it does not use
    it. The second failed on its own list of needles. String literals are read
    by AST with docstrings stripped, and the two files are asked different
    questions because they have different jobs.
    """
    import ast

    # 1. the module under test names no live path at all
    under_test = REPO / "core" / "observation_record.py"
    tree = ast.parse(under_test.read_text(encoding="utf-8"))
    docs = _docstring_positions(tree)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and (node.lineno, node.col_offset) not in docs):
            assert not node.value.startswith(LIVE_DIR), (
                f"observation_record.py:{node.lineno} names {node.value!r}")
            assert JOURNAL_NAME not in node.value, node.value

    # 2. THIS file opens only what is committed beside it. Asserted over the
    #    paths it actually resolves, not over its prose.
    for path in (PANEL, COUNTRY_LIST):
        assert path.parent == FIXTURES, path
        assert path.exists(), path
    assert FIXTURES.parent == pathlib.Path(__file__).resolve().parent.parent / "test"


def _docstring_positions(tree):
    import ast
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None) or []
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add((body[0].value.lineno, body[0].value.col_offset))
    return out
