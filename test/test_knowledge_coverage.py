# -*- coding: utf-8 -*-
"""test/test_knowledge_coverage.py — KNOWN · MEASURED · CURRENT · SEEN through
core.knowledge only, and the board row that shows them (C-OC-3 Part 4).
Atoms, labels and the coverage file are under tmp_path.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from core import atoms as at  # noqa: E402
from core import knowledge as kn  # noqa: E402

TODAY = date(2026, 10, 1)


@pytest.fixture
def root(tmp_path, monkeypatch):
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    return tmp_path


def _atom(root, key, sub, period, cls_url, ck):
    rec = {"axis": "A", "key": key, "value": 1.0, "unit": "u", "url": cls_url, "quote": "1.0",
           "period": period, "place": "WLD", "subcategory": sub}
    out = at.write({"card_key": ck, "verdict": "ACCEPTED", "gate": {"verdict": "ACCEPTED"}, "record": rec},
                   root=root / "atoms")
    assert out["written"] is True


def _cov(root, labels=None):
    lp = root / "labels.json"
    if labels is not None:
        lp.write_text(json.dumps({"labels": labels}), encoding="utf-8")
    return kn.coverage(TODAY, labels_path=lp, atoms_root=root / "atoms")


def _independent_url():
    cfg = json.loads((REPO / "config" / "reporter_independence.json").read_text(encoding="utf-8"))
    from experiments.composers import provenance as prov
    for host in ("https://api.worldbank.org/x", "https://earthquake.usgs.gov/x", "https://gml.noaa.gov/x"):
        if prov.reporter_class({"org": None, "url": host}, prov.reporter_config())[0] in kn.INDEPENDENT:
            return host
    pytest.skip("no independent host in config/reporter_independence.json")


def test_known_is_missing_while_statement_labels_are_absent_never_zero(root):
    c = _cov(root)
    assert c["world"]["known"] is None and c["statement_labels"] == "MISSING"
    assert c["world"]["measured"] == 0 and c["world"]["of"] == 105


def test_a_labelled_statement_makes_its_subcategory_known(root):
    c = _cov(root, {"s1": {"subcategory": "A1.1"}, "s2": {"subcategory": "unplaced"}})
    assert c["world"]["known"] == 1 and c["per_subcategory"]["A1.1"]["statements"] == 1


def test_measured_and_current_from_atoms(root):
    _atom(root, "k_old", "A1.1", "2015", "https://x.org", "c1")
    _atom(root, "k_new", "A1.2", "2025", "https://x.org", "c2")
    c = _cov(root, {})
    assert c["world"]["measured"] == 2 and c["world"]["current"] == 1
    assert c["per_subcategory"]["A1.2"]["current"] and not c["per_subcategory"]["A1.1"]["current"]


def test_seen_needs_state_change_and_source_on_one_key(root):
    url = _independent_url()
    _atom(root, "k1", "A1.1", "2026-09-25", url, "c1")
    c = _cov(root, {})
    assert c["per_subcategory"]["A1.1"]["seen"] and c["world"]["seen"] == 1


def test_split_across_keys_is_not_seen(root):
    url = _independent_url()
    _atom(root, "fresh_selfreported", "A1.1", "2026-09-25", "https://some-blog.example/x", "c1")
    _atom(root, "old_independent", "A1.1", "2019", url, "c2")
    assert not _cov(root, {})["per_subcategory"]["A1.1"]["seen"]


def test_mutation_without_the_one_key_rule_a_split_would_count(root, monkeypatch):
    url = _independent_url()
    _atom(root, "fresh_selfreported", "A1.1", "2026-09-25", "https://some-blog.example/x", "c1")
    _atom(root, "old_independent", "A1.1", "2019", url, "c2")
    real = kn.subcategory_counts

    def one_key(*a, **k):                     # the mutation: group by subcategory, not by key
        counts, present = real(*a, **k)
        for v in counts.values():
            v["measurements"] = [{**m, "key": "ALL"} for m in v["measurements"]]
        return counts, present
    monkeypatch.setattr(kn, "subcategory_counts", one_key)
    assert _cov(root, {})["per_subcategory"]["A1.1"]["seen"]


def test_old_day_fails_change(root):
    url = _independent_url()
    _atom(root, "k1", "A1.1", "2026-07-01", url, "c1")
    assert not _cov(root, {})["per_subcategory"]["A1.1"]["seen"]


# ── the board row ───────────────────────────────────────────────────────────
def _board_row(tmp_path, knowledge):
    import daily_board as db
    doc = {"generated_utc": datetime.now(timezone.utc).isoformat(), "totals": {"knowledge": knowledge}}
    p = tmp_path / "memory" / "taxonomy_coverage_latest.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return db.row_taxonomy(tmp_path, datetime.now(timezone.utc))


KW = {"world": {"known": None, "measured": 38, "current": 30, "seen": 2, "of": 105},
      "per_domain": {"A": {"known": 0, "known_missing": 26, "measured": 14, "current": 11, "seen": 0, "of": 26}},
      "statement_labels": "MISSING", "rule": {"KNOWN": "x"}}


def test_the_board_prints_four_counts_and_missing_for_an_absent_one(tmp_path):
    r = _board_row(tmp_path, KW)
    assert r["headline"] == "world: KNOWN MISSING/105 · MEASURED 38/105 · CURRENT 30/105 · SEEN 2/105"


def test_mutation_a_board_that_zero_fills_would_print_known_0(tmp_path):
    r = _board_row(tmp_path, {**KW, "world": {**KW["world"], "known": 0}})
    assert "KNOWN 0/105" in r["headline"], "zero and MISSING must print differently"


def test_the_board_refuses_a_file_without_the_knowledge_totals(tmp_path):
    import daily_board as db
    with pytest.raises(db.SourceMissing):
        _board_row(tmp_path, None)


def test_the_board_row_reads_no_snapshot_totals():
    import ast
    import inspect
    import daily_board as db
    src = inspect.getsource(db.row_taxonomy)
    subs = {n.slice.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)}
    assert "knowledge" in subs and not subs & {"system_E", "overall", "atoms"}
