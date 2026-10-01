# -*- coding: utf-8 -*-
"""test/test_data_feed_declarations.py — a source declares what it measures, where
and when; a mislabelled number is refused (1 Oct 2026, command C-OC-1 Part 1).

THE TWO FAILURES THIS FILE EXISTS FOR, both found in memory/verified_observations.jsonl:
  * "Forest area (% of total land area)" = 17490 — the World Bank HEADER's row
    count (path 0.total), accepted because the digits were on the page;
  * an ISS card whose value is a unix timestamp under a key that says
    "latitude, longitude, altitude".
Refusals first; every guard has a mutation test showing the refusal is load-bearing.
Bodies are real captures in test/fixtures/data_feeds/ (World Bank, 1 Oct 2026).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import data_feed_reader as w  # noqa: E402
from core import card_intake as ci  # noqa: E402
from core import quote_gate as qg  # noqa: E402

FIX = REPO / "test" / "fixtures" / "data_feeds"
FOREST_ALL = (FIX / "wb_AG.LND.FRST.ZS_country_all.json").read_text(encoding="utf-8")
FOREST_WLD = (FIX / "wb_AG.LND.FRST.ZS_WLD_mrv1.json").read_text(encoding="utf-8")

GOOD = {"id": "wb_forest_wld", "axis": "ECOSYSTEMS_BIODIVERSITY_REVIEW", "key": "forest_area_pct",
        "url": "https://api.worldbank.org/v2/country/WLD/indicator/AG.LND.FRST.ZS?format=json&mrv=1",
        "path": "1.0.value", "period_path": "1.0.date", "unit": "pct_land_area",
        "subcategory": "C2.1", "place": "WLD"}


def _getter(raw: str, status: int = 200):
    def g(url, timeout):
        return status, json.loads(raw), None, raw
    return g


class _Life:
    """A lifecycle that has already promoted every source, so the ONLY thing
    between a reading and a card is the rule under test."""
    TRUSTED, CANDIDATE, DEMOTED = "TRUSTED", "CANDIDATE", "DEMOTED"

    def observe(self, sid, **kw):
        return {"state": self.TRUSTED}


@pytest.fixture
def trusted(monkeypatch, tmp_path):
    import core.source_lifecycle as life
    fake = _Life()
    monkeypatch.setattr(life, "observe", fake.observe)
    monkeypatch.setattr(life, "summary", lambda st: {"TRUSTED": 1, "CANDIDATE": 0, "DEMOTED": 0})
    seed = tmp_path / "seed.json"

    def run_with(sources, raw):
        seed.write_text(json.dumps({"sources": sources, "timeout_sec": 5}), encoding="utf-8")
        return w.run(seed, queue_dir=tmp_path / "q", getter=_getter(raw), dry_run=True,
                     discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl")
    return run_with


# ── 1a, REWRITTEN 1 Oct 2026 (C-OC-3, Emil R27) ─────────────────────────────
# A declaration is a LABEL, not a gate. A source missing one still yields a card
# (the gate judges the quote); the missing piece is named in `undeclared` and the
# card carries how each label is known ("unknown").
@pytest.mark.parametrize("drop", ["subcategory", "place", "unit", "period_path"])
def test_a_source_missing_a_declaration_is_still_carded_and_names_it(trusted, drop):
    src = {k: v for k, v in GOOD.items() if k != drop}
    r = trusted([src], FOREST_WLD)
    assert len(r["cards"]) == 1, "a missing label kept a reading out"
    row = (r["feeds"] + r["carded"])[0]
    assert any(drop.split("_")[0] in p for p in row["undeclared"]), row["undeclared"]


def test_unit_unknown_is_a_label_not_a_refusal(trusted):
    r = trusted([{**GOOD, "unit": "unknown"}], FOREST_WLD)
    assert len(r["cards"]) == 1 and r["cards"][0]["unit"] == "unknown" and r["cards"][0]["unit_how"] == "unknown"


def test_an_unresolvable_subcategory_is_a_dropped_label_not_a_refusal(trusted):
    r = trusted([{**GOOD, "subcategory": "Z9.9"}], FOREST_WLD)
    assert not r["refusals"] and len(r["cards"]) == 1
    assert r["cards"][0]["subcategory"] is None


def test_a_period_in_another_record_is_a_missing_label(trusted):
    r = trusted([{**GOOD, "period_path": "0.lastupdated"}], FOREST_WLD)
    assert len(r["cards"]) == 1 and r["cards"][0]["period"] is None
    row = (r["feeds"] + r["carded"])[0]
    assert any("same record" in p for p in row["undeclared"])


def test_a_fully_declared_source_produces_a_card_with_subcategory_place_period(trusted):
    r = trusted([GOOD], FOREST_WLD)
    assert len(r["cards"]) == 1, (r["stored"], r["refusals"])
    c = r["cards"][0]
    assert (c["subcategory"], c["place"], c["period"]) == ("C2.1", "WLD", "2023")
    assert (c["place_how"], c["period_how"], c["subcategory_how"]) == ("declared", "same_record", "declared")
    assert c["value"] == pytest.approx(31.0951828663057)


# ── 1b: the World Bank header is not an observation ──────────────────────────
def test_the_forest_area_header_row_count_is_refused(trusted):
    src = {**GOOD, "url": "https://api.worldbank.org/v2/country/all/indicator/AG.LND.FRST.ZS?format=json",
           "path": "0.total", "period_path": "0.lastupdated"}
    r = trusted([src], FOREST_ALL)
    assert not r["feeds"] and not r["shadows"] and not r["cards"]
    assert "World Bank header, not an observation" in r["refusals"][0]["reason"]


def test_value_and_date_of_row_zero_pass():
    row = w.fetch_one(GOOD, 5, _getter(FOREST_WLD))
    assert row["value"] == pytest.approx(31.0951828663057) and row["period"] == "2023"
    assert row["undeclared"] == []


def test_mutation_without_the_header_guard_17490_would_be_read(monkeypatch):
    monkeypatch.setattr(w, "worldbank_header_problem", lambda payload, path: None)
    src = {**GOOD, "path": "0.total", "period_path": "0.lastupdated"}
    row = w.fetch_one(src, 5, _getter(FOREST_ALL))
    assert row["value"] == 17490.0


# ── 1c, REWRITTEN 1 Oct 2026 (C-OC-3): the gate is back to the six ─────────
def test_the_gate_requires_the_six_and_the_card_carries_the_labels():
    assert qg.REQUIRED == ("axis", "key", "value", "unit", "url", "quote")
    for f in ("subcategory", "place", "period", "period_how"):
        assert f in w.CARD_FIELDS and f not in qg.REQUIRED


def test_a_card_without_the_labels_is_judged_on_its_quote():
    old = {"axis": "A", "key": "k", "value": 1.0, "unit": "unknown", "url": "http://x", "quote": "1"}
    assert qg.judge(old, "1")["verdict"] == "ACCEPTED"


OLD_CARD = {"axis": "COGNITION_LEARNING_REVIEW", "key": "Youth literacy rate (ages 15-24) %",
            "value": 83.3899993896484, "unit": "unknown",
            "url": "https://api.worldbank.org/v2/country/all/indicator/SE.ADT.1524.LT.ZS?format=json&per_page=5000",
            "quote": "83.3899993896484,\"unit\":\"\",\"obs_status\":\"\",\"decimal\":0},{\"ind",
            "data_date": None,
            "data_date_missing": "the source declares no data_date_path, so the payload's own observation "
                                 "date is unknown; today's date would be the date of the FETCH, not of the reading"}
# The card_key memory/verified_observations.jsonl already holds for this exact card
# (ACCEPTED 2026-09-20), measured before this change.
OLD_CARD_KEY_MEASURED = "e8d18c26a2055de167353cb2ab19becbe52470cd214f08f02b1d94647bc16165"


def test_an_old_cards_key_is_unchanged():
    """The key is the sha256 of the card's own canonical JSON. Nothing in this
    change may add, default or reorder fields of a card already in the inbox:
    its key would move and the judged card would be re-judged as new."""
    assert ci._key(OLD_CARD) == OLD_CARD_KEY_MEASURED


# ── 1d: the quote is cut from the record the path walked ────────────────────
TRAP = ('[{"page":1,"total":1},[{"note":{"ref":"31.0951828663057"},"x":{"value":31.0951828663057,'
        '"date":"1999"}},{"country":"WLD","date":"2023","value":31.0951828663057,"unit":""}]]')


def test_the_quote_comes_from_the_walked_record_not_the_first_match():
    src = {**GOOD, "path": "1.1.value", "period_path": "1.1.date"}
    row = w.fetch_one(src, 5, _getter(TRAP))
    q = row["quote"]
    assert q is not None and q in TRAP
    start = TRAP.index(q)
    assert start > TRAP.index('"date":"2023"') - 40, "quote taken from an earlier field"
    rec_start = TRAP.index('{"country":"WLD"')
    assert rec_start <= start < TRAP.index("]]"), (start, rec_start)
    assert qg.judge({**w.card_from_row(row)}, TRAP)["verdict"] == "ACCEPTED"


def test_mutation_first_textual_match_would_quote_the_wrong_field(monkeypatch):
    monkeypatch.setattr(w, "quote_from_record", lambda raw, payload, path, value: w.quote_from_body(raw, value))
    src = {**GOOD, "path": "1.1.value", "period_path": "1.1.date"}
    row = w.fetch_one(src, 5, _getter(TRAP))
    assert TRAP.index(row["quote"]) < TRAP.index('{"country":"WLD"'), "the guard is not what chose the record"


# ── 1e: network down ────────────────────────────────────────────────────────
def _down(url, timeout):
    import requests
    raise requests.exceptions.ConnectionError("Failed to resolve 'x' ([Errno 11001] getaddrinfo failed)")


def test_every_source_failing_on_the_network_is_network_down_and_retried_once(monkeypatch, tmp_path):
    calls, slept = [], []
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [GOOD, {**GOOD, "id": "b", "url": "https://example.invalid/b"},
                                            {**GOOD, "id": "local", "url": "local://x"}]}), encoding="utf-8")

    def runner(**kw):
        calls.append(1)
        return w.run(seed, queue_dir=tmp_path / "q", getter=_down, dry_run=True,
                     discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl")
    res = w.run_with_retry(runner, sleep=slept.append)
    assert res["network_down"] is True and res["retried"] is True
    assert len(calls) == 2 and slept == [w.NETWORK_RETRY_SEC] and w.NETWORK_RETRY_SEC == 120


def test_one_source_up_is_not_network_down(monkeypatch, tmp_path):
    def g(url, timeout):
        if "mrv=1" in url:
            return _getter(FOREST_WLD)(url, timeout)
        return _down(url, timeout)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [GOOD, {**GOOD, "id": "b", "url": "https://y/z"}]}), encoding="utf-8")
    r = w.run(seed, queue_dir=tmp_path / "q", getter=g, dry_run=True,
              discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl")
    assert r["network_down"] is False


def test_finish_row_and_exit_code_say_network_down(monkeypatch, tmp_path):
    rows = []
    monkeypatch.setattr(w, "_task_row", lambda row, path=None: rows.append(row))
    monkeypatch.setattr(w, "unfinished_runs", lambda *a, **k: [])
    down = {"ts": "t", "sources": 2, "feeds": [], "shadows": [], "refusals": [{}, {}], "cards": [],
            "lifecycle": {}, "network_down": True, "retried": True, "first_pass": {"refused": 2}}
    monkeypatch.setattr(w, "run_with_retry", lambda runner, sleep=None: down)
    monkeypatch.setattr(sys, "argv", ["data_feed_reader.py"])
    rc = w.main()
    fin = [r for r in rows if r.get("event") == "finish"][0]
    assert fin["network_down"] is True and fin["retried"] is True
    assert rc != 0 and rc == w.EXIT_NETWORK_DOWN


def test_mutation_without_network_classification_a_dead_network_looks_like_bad_sources(monkeypatch, tmp_path):
    monkeypatch.setattr(w, "is_network_error", lambda exc: False)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"sources": [GOOD]}), encoding="utf-8")
    r = w.run(seed, queue_dir=tmp_path / "q", getter=_down, dry_run=True,
              discovered_path=tmp_path / "none.json", lifecycle_state={},
                     ledger=tmp_path / "ledger.jsonl")
    assert r["network_down"] is False
