# -*- coding: utf-8 -*-
"""test/test_openclaw_first_fetch_card.py — a declared source that passes the gate
makes a card on its FIRST clean fetch (C-OC-2 Part 1, 1 Oct 2026).

THE RULING. The lifecycle ladder decides what enters the COMPOSITE. An atom is one
reading judged alone by the gate, and five identical fetches of an annual figure
prove nothing the first did not. So the CARD is gated by declaration + quote +
period + "not DEMOTED"; the ladder still decides `measured` (the composite) and
still demotes. Refusals first; the DEMOTED guard has a mutation test.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import openclaw_axis_worker as w  # noqa: E402

FIX = REPO / "test" / "fixtures" / "openclaw"
FOREST_WLD = (FIX / "wb_AG.LND.FRST.ZS_WLD_mrv1.json").read_text(encoding="utf-8")
GOOD = {"id": "wb_forest_wld", "axis": "TAXONOMY:C2.1", "key": "forest_area_pct",
        "url": "https://api.worldbank.org/v2/country/WLD/indicator/AG.LND.FRST.ZS?format=json&mrv=1",
        "path": "1.0.value", "period_path": "1.0.date", "unit": "pct_land_area",
        "subcategory": "C2.1", "place": "WLD"}


def _getter(url, timeout):
    return 200, json.loads(FOREST_WLD), None, FOREST_WLD


@pytest.fixture
def run_in_state(monkeypatch, tmp_path):
    """Run one source with the lifecycle pinned to a given state. Nothing live."""
    import core.source_lifecycle as life

    def go(src, state):
        monkeypatch.setattr(life, "observe", lambda sid, **kw: {"state": state})
        seed = tmp_path / "seed.json"
        seed.write_text(json.dumps({"sources": [src], "timeout_sec": 5}), encoding="utf-8")
        return w.run(seed, queue_dir=tmp_path / "q", getter=_getter, dry_run=True,
                     discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl")
    return go


def test_a_candidate_declared_source_yields_a_card_and_is_declared_not_measured(run_in_state):
    r = run_in_state(GOOD, "CANDIDATE")
    assert len(r["cards"]) == 1
    assert not r["feeds"], "a CANDIDATE must not enter the composite"
    assert len(r["declared"]) == 1 and r["declared"][0]["status"] == "DECLARED"
    assert r["declared"][0]["measured"] is False


def test_an_undeclared_candidate_yields_no_card(run_in_state):
    r = run_in_state({k: v for k, v in GOOD.items() if k != "place"}, "CANDIDATE")
    assert not r["cards"] and not r["declared"]
    assert r["shadows"] and r["shadows"][0]["status"] == "SHADOW"


def test_a_demoted_declared_source_yields_no_card(run_in_state):
    r = run_in_state(GOOD, "DEMOTED")
    assert not r["cards"] and not r["declared"] and r["shadows"]


def test_mutation_without_the_demoted_check_the_demoted_source_yields_a_card(run_in_state, monkeypatch):
    monkeypatch.setattr(w, "card_eligible",
                        lambda row, state: not row["undeclared"] and bool(row.get("quote")) and bool(row.get("period")))
    r = run_in_state(GOOD, "DEMOTED")
    assert r["cards"], "the DEMOTED check is not what kept the card out"


def test_a_trusted_declared_source_is_measured_and_carded(run_in_state):
    r = run_in_state(GOOD, "TRUSTED")
    assert len(r["feeds"]) == 1 and r["feeds"][0]["measured"] is True and len(r["cards"]) == 1


def test_no_quote_or_no_period_means_no_card(run_in_state, monkeypatch):
    real = w.fetch_one

    def no_quote(src, timeout, getter=None):
        row = real(src, timeout, getter)
        row["quote"] = None
        return row
    monkeypatch.setattr(w, "fetch_one", no_quote)
    assert not run_in_state(GOOD, "CANDIDATE")["cards"]


def test_finish_row_counts_the_four_populations(monkeypatch):
    rows = []
    monkeypatch.setattr(w, "_task_row", lambda row, path=None: rows.append(row))
    monkeypatch.setattr(w, "unfinished_runs", lambda *a, **k: [])
    res = {"ts": "t", "sources": 4, "feeds": [{}], "declared": [{}, {}], "shadows": [{}],
           "refusals": [], "cards": [{}, {}, {}], "lifecycle": {}, "network_down": False, "retried": False}
    monkeypatch.setattr(w, "run_with_retry", lambda runner, sleep=None: res)
    monkeypatch.setattr(sys, "argv", ["openclaw_axis_worker.py"])
    w.main()
    fin = [r for r in rows if r.get("event") == "finish"][0]
    assert (fin["trusted"], fin["declared"], fin["shadow"], fin["refused"], fin["cards"]) == (1, 2, 1, 0, 3)
