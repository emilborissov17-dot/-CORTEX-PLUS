# -*- coding: utf-8 -*-
"""test/test_open_criterion.py — every fetched page passes whole (C-OC-3 Part 1f,
Emil R27, 1 Oct 2026).

ONE CRITERION, AND IT IS ON US: what we attribute to a source must really be in it.
So a page is never refused for its form. Its sentences enter the store; a number we
can quote becomes a card in addition. Only two refusals remain, both of OUR claim:
  (a) a quote that is not on the fetched page  — the gate;
  (b) a label that contradicts the source's own structure — the World Bank header
      count named "forest area".
Even then the page's content still enters as statements. Each refusal has a
mutation test. Fixtures only; every store is under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import data_feed_reader as w  # noqa: E402
from core import knowledge as kn  # noqa: E402
from core import quote_gate as qg  # noqa: E402
from core import statements as st  # noqa: E402

FIX = REPO / "test" / "fixtures" / "data_feeds"
FOREST_ALL = (FIX / "wb_AG.LND.FRST.ZS_country_all.json").read_text(encoding="utf-8")
FOREST_WLD = (FIX / "wb_AG.LND.FRST.ZS_WLD_mrv1.json").read_text(encoding="utf-8")
OWID = (FIX / "owid_1228789_reduced.json").read_text(encoding="utf-8")
HTML = ("<html><head><title>Report</title><script>var x=1;</script></head><body>"
        "<h1>Detention in the region</h1><p>Observers say arbitrary detention rose in the north.</p>"
        "<p>The ministry denied it. No figures were published.</p></body></html>")


def _page(raw, as_json=True):
    def g(url, timeout):
        return 200, (json.loads(raw) if as_json else None), None, raw
    return g


@pytest.fixture
def harness(tmp_path, monkeypatch):
    import core.source_lifecycle as life
    from core import card_intake as ci
    monkeypatch.setattr(life, "observe", lambda sid, **kw: {"state": "CANDIDATE"})
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    store, seen = tmp_path / "statements.jsonl", tmp_path / "seen.json"
    calls = []

    def ingest(source_id, text, url="", origin="web", extra=None):
        calls.append(text)
        return kn.ingest(source_id, text, url=url, origin=origin, store=store, seen_path=seen, extra=extra)

    def run(sources, getter):
        seed = tmp_path / "seed.json"
        seed.write_text(json.dumps({"sources": sources, "timeout_sec": 5}), encoding="utf-8")
        return w.run(seed, queue_dir=tmp_path / "q", getter=getter, dry_run=False,
                     discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl", ingest=ingest)
    return {"run": run, "store": store, "calls": calls, "tmp": tmp_path}


# ── a page with no number ───────────────────────────────────────────────────
def test_a_page_with_no_number_yields_statements_and_zero_refusals(harness):
    r = harness["run"]([{"id": "html1", "url": "https://example.org/report", "path": "x"}], _page(HTML, False))
    assert r["refusals"] == [] and r["unreachable"] == [] and r["cards"] == []
    assert r["pages"]["statements_added"] >= 3
    sentences = [x["sentence"] for x in kn.statements(harness["store"])]
    assert any("arbitrary detention rose" in s for s in sentences)
    assert not any("var x" in s for s in sentences), "script text is not page content"


def test_the_same_page_twice_is_ingested_once(harness):
    src = [{"id": "html1", "url": "https://example.org/report", "path": "x"}]
    harness["run"](src, _page(HTML, False))
    r2 = harness["run"](src, _page(HTML, False))
    assert r2["pages"]["skipped_same_content"] == 1 and r2["pages"]["statements_added"] == 0


def test_a_sentence_with_no_place_period_or_unit_is_returned_by_read(harness, tmp_path):
    harness["run"]([{"id": "html1", "url": "https://example.org/report", "path": "x"}], _page(HTML, False))
    items = kn.read("arbitrary detention", k=5, store=harness["store"], vec_path=tmp_path / "v.npy", field_index={},
                    ids_path=tmp_path / "ids.json", labels_path=tmp_path / "l.json",
                    atoms_root=tmp_path / "atoms", with_vectors=False)
    assert items and items[0]["type"] == "statement" and "detention" in items[0]["text"]


# ── refusal (b): a label that contradicts the source's own structure ──────────
WB_HEADER = {"id": "wb_forest_all", "key": "Forest area (% of total land area)", "unit": "unknown",
             "url": "https://api.worldbank.org/v2/country/all/indicator/AG.LND.FRST.ZS?format=json",
             "path": "0.total"}


def test_the_world_bank_header_count_is_refused_as_forest_area_while_the_rows_still_enter(harness):
    r = harness["run"]([WB_HEADER], _page(FOREST_ALL))
    assert r["cards"] == [] and r["refusals"][0]["status"] == "LABEL_REFUSED"
    assert "World Bank header, not an observation" in r["refusals"][0]["reason"]
    text = "\n".join(harness["calls"])
    assert "countryiso3code=AFE" in text and "total=17490" in text, "the page itself did not enter"


def test_mutation_without_the_header_guard_17490_becomes_a_forest_card(harness, monkeypatch):
    monkeypatch.setattr(w, "worldbank_header_problem", lambda payload, path: None)
    r = harness["run"]([WB_HEADER], _page(FOREST_ALL))
    assert r["cards"] and r["cards"][0]["value"] == 17490.0


# ── refusal (a): a quote that is not on the page ────────────────────────────
def test_an_invented_quote_is_refused_while_the_pages_sentences_still_enter(harness):
    src = {"id": "wb_wld", "key": "forest_area_pct", "unit": "pct", "url": "https://api.worldbank.org/x",
           "path": "1.0.value", "period_path": "1.0.date"}
    r = harness["run"]([src], _page(FOREST_WLD))
    card = dict(r["cards"][0], quote="31.0951828663057 percent, says nobody")
    assert qg.judge(card, FOREST_WLD)["verdict"] == "QUOTE_NOT_ON_PAGE"
    assert qg.judge(r["cards"][0], FOREST_WLD)["verdict"] == "ACCEPTED"
    assert any("value=31.0951828663057" in x["sentence"] for x in kn.statements(harness["store"]))


def test_mutation_without_the_page_check_the_invented_quote_would_pass(monkeypatch):
    card = {"axis": "A", "key": "k", "value": 31.0951828663057, "unit": "pct", "url": "u",
            "quote": "31.0951828663057 percent, says nobody"}
    monkeypatch.setattr(qg, "_norm", lambda t: "31.0951828663057 percent, says nobody")
    assert qg.judge(card, FOREST_WLD)["verdict"] == "ACCEPTED"


# ── a measurement with only a value and a quote is an atom ──────────────────
def test_a_measurement_without_a_period_is_carded(harness):
    src = {"id": "wb_wld", "key": "forest_area_pct", "url": "https://api.worldbank.org/x", "path": "1.0.value"}
    r = harness["run"]([src], _page(FOREST_WLD))
    c = r["cards"][0]
    assert c["period"] is None and c["period_how"] == "unknown" and c["unit"] == "unknown"


# ── parallel arrays (the OWID endpoint finder arm D found) ──────────────────
OWID_SRC = {"id": "owid:1228789:WLD", "key": "disaster_deaths", "unit": "people", "place": "WLD",
            "subcategory": "A2.5", "url": "https://api.ourworldindata.org/v1/indicators/1228789.data.json",
            "parallel": {"values": "values", "periods": "years", "entities": "entities", "entity": 355}}


def test_parallel_arrays_pass_with_parallel_index(harness):
    r = harness["run"]([OWID_SRC], _page(OWID))
    c = r["cards"][0]
    assert (c["value"], c["period"], c["period_how"]) == (1930.0, "2026", "parallel_index")
    assert qg.judge(c, OWID)["verdict"] == "ACCEPTED"


# ── no-loss ─────────────────────────────────────────────────────────────────
def test_no_loss_on_an_html_page():
    text = kn.html_text(HTML)
    sents, _mode = st.segment(text)                # raises SegmentationLostText on any loss
    assert "".join(sents).replace(" ", "") == st.normalise(text).replace(" ", "").replace(chr(10), "")


def test_no_loss_on_a_flattened_json_body():
    payload = json.loads(FOREST_ALL)
    text = kn.flatten_json(payload)                # raises FlattenLostValue on any loss
    for v in ("AFE", "Africa Eastern and Southern", "17490", "2026-07-13"):
        assert v in text


def test_mutation_a_flattener_that_drops_a_value_is_caught():
    with pytest.raises(kn.FlattenLostValue):
        kn.assert_flatten_lossless({"a": {"b": "kept", "c": "dropped"}}, "a: b=kept")
