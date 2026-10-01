# -*- coding: utf-8 -*-
"""test/test_data_feed_first_fetch_card.py — a reading we can QUOTE makes a card on
its first fetch (C-OC-2 Part 1, REWRITTEN 1 Oct 2026 for C-OC-3 / Emil R27).

THE RULING NOW. One criterion, and it is on us: what we attribute must be on the
page. A card needs a quote, and the gate checks it. No declaration, period, place,
unit or ladder history decides whether a reading becomes a card. The ladder still
decides `measured` (the composite). The one guard left here — no quote, no card —
has a mutation test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import data_feed_reader as w  # noqa: E402

FIX = REPO / "test" / "fixtures" / "data_feeds"
FOREST_WLD = (FIX / "wb_AG.LND.FRST.ZS_WLD_mrv1.json").read_text(encoding="utf-8")
GOOD = {"id": "wb_forest_wld", "axis": "TAXONOMY:C2.1", "key": "forest_area_pct",
        "url": "https://api.worldbank.org/v2/country/WLD/indicator/AG.LND.FRST.ZS?format=json&mrv=1",
        "path": "1.0.value", "period_path": "1.0.date", "unit": "pct_land_area",
        "subcategory": "C2.1", "place": "WLD"}


def _getter(url, timeout):
    return 200, json.loads(FOREST_WLD), None, FOREST_WLD


@pytest.fixture
def run_in_state(monkeypatch, tmp_path):
    import core.source_lifecycle as life

    def go(src, state):
        monkeypatch.setattr(life, "observe", lambda sid, **kw: {"state": state})
        seed = tmp_path / "seed.json"
        seed.write_text(json.dumps({"sources": [src], "timeout_sec": 5}), encoding="utf-8")
        return w.run(seed, queue_dir=tmp_path / "q", getter=_getter, dry_run=True,
                     discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl")
    return go


def test_a_candidate_declared_source_yields_a_card_and_is_carded_not_measured(run_in_state):
    r = run_in_state(GOOD, "CANDIDATE")
    assert len(r["cards"]) == 1 and not r["feeds"]
    assert r["carded"][0]["status"] == "CARDED" and r["carded"][0]["measured"] is False


def test_an_undeclared_candidate_also_yields_a_card(run_in_state):
    r = run_in_state({k: v for k, v in GOOD.items() if k not in ("place", "subcategory")}, "CANDIDATE")
    assert len(r["cards"]) == 1 and r["cards"][0]["place_how"] == "unknown"


def test_a_demoted_source_still_yields_a_card(run_in_state):
    """History of clean runs is not a criterion (Emil, R27)."""
    assert len(run_in_state(GOOD, "DEMOTED")["cards"]) == 1


def test_a_trusted_declared_source_is_measured_and_carded(run_in_state):
    r = run_in_state(GOOD, "TRUSTED")
    assert len(r["feeds"]) == 1 and r["feeds"][0]["measured"] is True and len(r["cards"]) == 1


def test_no_quote_means_no_card(run_in_state, monkeypatch):
    real = w.fetch_one

    def no_quote(src, timeout, getter=None, page=None):
        row = real(src, timeout, getter, page)
        row["quote"] = None
        return row
    monkeypatch.setattr(w, "fetch_one", no_quote)
    r = run_in_state(GOOD, "CANDIDATE")
    assert not r["cards"] and r["stored"][0]["status"] == "STORED"


def test_mutation_without_the_quote_condition_an_unquotable_reading_is_carded(run_in_state, monkeypatch):
    real = w.fetch_one

    def no_quote(src, timeout, getter=None, page=None):
        row = real(src, timeout, getter, page)
        row["quote"] = None
        return row
    monkeypatch.setattr(w, "fetch_one", no_quote)
    monkeypatch.setattr(w, "card_eligible", lambda row, state: True)
    monkeypatch.setattr(w, "card_from_row", lambda row: {"value": row["value"]})
    assert run_in_state(GOOD, "CANDIDATE")["cards"], "the quote condition is not what kept it out"


def test_finish_row_counts_the_populations(monkeypatch):
    rows = []
    monkeypatch.setattr(w, "_task_row", lambda row, path=None: rows.append(row))
    monkeypatch.setattr(w, "unfinished_runs", lambda *a, **k: [])
    res = {"ts": "t", "sources": 5, "feeds": [{}], "carded": [{}, {}], "stored": [{}], "refusals": [{}],
           "unreachable": [{}], "cards": [{}, {}, {}], "lifecycle": {}, "network_down": False, "retried": False,
           "pages": {"ingested": 4, "statements_added": 40, "skipped_same_content": 1, "needs": []}}
    monkeypatch.setattr(w, "run_with_retry", lambda runner, sleep=None: res)
    monkeypatch.setattr(sys, "argv", ["data_feed_reader.py"])
    w.main()
    fin = [r for r in rows if r.get("event") == "finish"][0]
    assert (fin["trusted"], fin["carded"], fin["stored"], fin["label_refused"], fin["unreachable"],
            fin["cards"], fin["pages_ingested"], fin["statements_added"]) == (1, 2, 1, 1, 1, 3, 4, 40)
