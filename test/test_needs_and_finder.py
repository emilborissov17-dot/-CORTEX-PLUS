# -*- coding: utf-8 -*-
"""test/test_needs_and_finder.py — core/needs.py ranking and scripts/openclaw_finder.py
(C-OC-3 Part 3). Search and getter are injected; every store, ledger and needs
file is under tmp_path. No model is reachable from either module.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import needs  # noqa: E402
from scripts import openclaw_finder as fin  # noqa: E402

COMPOSER = {
    "WATER_REVIEW": {"items": [
        {"slot": "measurement_daily", "kind": "slot_unfilled", "detail": "needs >= 1 live source, has 0"},
        {"slot": "anchor_annual", "kind": "slot_nominally_filled", "detail": "1 live source"}]},
    "ENERGY_REVIEW": {"items": [
        {"slot": "event_daily", "kind": "human_sense_request", "detail": "Emil asked; usgs:summary_4.5_day"}]},
}


@pytest.fixture
def p(tmp_path, monkeypatch):
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    cp = tmp_path / "composer_needs.json"
    cp.write_text(json.dumps(COMPOSER), encoding="utf-8")
    return {"composer": cp, "labels": tmp_path / "labels.json", "atoms": tmp_path / "atoms",
            "needs": tmp_path / "needs.json", "ledger": tmp_path / "ledger.jsonl", "store": tmp_path / "s.jsonl",
            "seen": tmp_path / "seen.json", "park": tmp_path / "park.json"}


# ── needs ───────────────────────────────────────────────────────────────────
def test_declared_needs_come_first_human_demand_first_and_nominal_ones_are_not_needs(p):
    doc = needs.rebuild(out=p["needs"], composer_path=p["composer"], labels_path=p["labels"], atoms_root=p["atoms"])
    ids = [n["need_id"] for n in doc["needs"]]
    assert ids[:2] == ["declared:ENERGY_REVIEW:event_daily:human_sense_request",
                       "declared:WATER_REVIEW:measurement_daily:slot_unfilled"]
    assert not any("slot_nominally_filled" in i for i in ids)
    assert doc["needs"][0]["source_ids"] == ["usgs:summary_4.5_day"]


def test_world_needs_never_include_domain_e_and_cover_all_105(p):
    doc = needs.rebuild(out=p["needs"], composer_path=p["composer"], labels_path=p["labels"], atoms_root=p["atoms"])
    world = [n for n in doc["needs"] if n["tier"] == "world"]
    assert len(world) == 105 and not any(n["subcategory"].startswith("E") for n in world)


def test_fewest_items_first_then_maslow_lowest_first(p):
    labels = {"labels": {f"s{i}": {"subcategory": "A1.1"} for i in range(3)}}
    p["labels"].write_text(json.dumps(labels), encoding="utf-8")
    doc = needs.rebuild(out=p["needs"], composer_path=p["composer"], labels_path=p["labels"], atoms_root=p["atoms"])
    world = [n for n in doc["needs"] if n["tier"] == "world"]
    assert world[-1]["subcategory"] == "A1.1", "the best-covered subcategory is not last"
    zero = [n for n in world if n["statements"] + n["measurements"] == 0]
    order = [needs.MASLOW.index(n["maslow"]) if n["maslow"] else len(needs.MASLOW) for n in zero]
    assert order == sorted(order), "ties are not ordered by Maslow level"


def test_mutation_ranking_by_most_items_puts_the_covered_one_first(p, monkeypatch):
    labels = {"labels": {f"s{i}": {"subcategory": "A1.1"} for i in range(3)}}
    p["labels"].write_text(json.dumps(labels), encoding="utf-8")
    real = needs.world
    monkeypatch.setattr(needs, "world", lambda counts, tree=None: list(reversed(real(counts, tree))))
    doc = needs.rebuild(out=p["needs"], composer_path=p["composer"], labels_path=p["labels"], atoms_root=p["atoms"])
    assert [n for n in doc["needs"] if n["tier"] == "world"][0]["subcategory"] == "A1.1"


def test_no_model_is_imported_by_needs_or_finder():
    banned = {"ollama", "openai", "anthropic", "core.local_brain", "core.llm", "core.data_scout"}
    for f in (REPO / "core" / "needs.py", REPO / "scripts" / "openclaw_finder.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not names & banned, f"{f.name} imports {names & banned}"


# ── finder ──────────────────────────────────────────────────────────────────
PAGE = "<html><body><p>Reservoir levels fell to 41 percent.</p><p>Rationing began.</p></body></html>"


def _run(p, search, getter, n=2):
    return fin.run(n=n, per_need=3, search=search, getter=getter, ledger=p["ledger"], store=p["store"],
                   seen_path=p["seen"], needs_out=p["needs"], composer_path=p["composer"],
                   labels_path=p["labels"], atoms_root=p["atoms"], parking=p["park"])


def _ledger(p):
    return [json.loads(l) for l in p["ledger"].read_text(encoding="utf-8").splitlines()]


def test_finder_writes_every_ledger_step_and_the_pages_enter_the_store(p):
    search = lambda q, k: [{"url": "https://a.org/r", "title": "t"}, {"url": "https://down.org/x", "title": "t"}]
    def getter(url, t):
        return (200, None, None, PAGE) if "a.org" in url else (None, None, "ConnectionError: down", None)
    r = _run(p, search, getter)
    ev = [x["event"] for x in _ledger(p)]
    assert ev[0] == "EMITTED"
    assert ev[1:] == ["TAKEN", "SEARCHED", "UNREACHABLE", "FETCHED", "GAINED",
                      "TAKEN", "SEARCHED", "UNREACHABLE", "FETCHED", "GAINED"]
    assert r["taken"][0]["gained"] == 2 and r["taken"][1]["gained"] == 0, "the same page was stored twice"
    from core import knowledge as kn
    assert {x["origin"] for x in kn.statements(p["store"])} == {"finder"}


def test_no_results_is_its_own_row(p):
    _run(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE), n=1)
    ev = [x["event"] for x in _ledger(p)]
    assert ev == ["EMITTED", "TAKEN", "NO_RESULTS", "FETCHED", "GAINED"]


def test_a_search_that_raises_is_no_results_with_the_reason(p):
    def boom(q, k):
        raise TimeoutError("ddg slow")
    _run(p, boom, lambda u, t: (200, None, None, PAGE), n=1)
    nr = [x for x in _ledger(p) if x["event"] == "NO_RESULTS"][0]
    assert "TimeoutError" in nr["why"]


def test_a_need_that_names_a_parked_source_unparks_it(p):
    from core import fetch_standard as fs
    for _ in range(3):
        fs.record("usgs:summary_4.5_day", ok=False, err="x", path=p["park"])
    assert fs.is_parked("usgs:summary_4.5_day", p["park"])
    _run(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE), n=1)
    assert not fs.is_parked("usgs:summary_4.5_day", p["park"])


def test_mutation_without_unpark_the_source_stays_parked(p, monkeypatch):
    from core import fetch_standard as fs
    for _ in range(3):
        fs.record("usgs:summary_4.5_day", ok=False, err="x", path=p["park"])
    monkeypatch.setattr(fs, "unpark", lambda *a, **k: None)
    _run(p, lambda q, k: [], lambda u, t: (200, None, None, PAGE), n=1)
    assert fs.is_parked("usgs:summary_4.5_day", p["park"])


def test_the_default_fetch_goes_through_the_fetch_standard(monkeypatch):
    from core import fetch_standard as fs
    calls = []
    monkeypatch.setattr(fs, "get", lambda url, **kw: calls.append(url) or (_ for _ in ()).throw(fs.FetchRefused("lan")))
    r = fin._fetch("http://192.168.0.1/")
    assert calls == ["http://192.168.0.1/"] and "REFUSED_BY_FETCH_STANDARD" in r["err"]


def test_the_chain_runs_worker_then_finder_then_judge():
    assert fin.chain_steps() == ["openclaw_axis_worker.py", "openclaw_finder.py", "card_intake.py"]


def test_mutation_a_chain_without_the_finder_is_seen(tmp_path):
    bat = tmp_path / "c.bat"
    bat.write_text("rem openclaw_finder.py in a comment\n%PY% scripts\openclaw_axis_worker.py\n%PY% core\card_intake.py\n",
                   encoding="utf-8")
    assert fin.chain_steps(bat) == ["openclaw_axis_worker.py", "card_intake.py"]
