# -*- coding: utf-8 -*-
"""test/test_openclaw_seed_sources.py — every seed source in
config/openclaw_sources.json that names a subcategory is fully declared, and its
declared subcategory is the key map's rule for its key (C-OC-1 Part 3, 1 Oct 2026).

Static checks only; no network. Which candidates entered the file, and why the
others did not, is recorded in claude/reports/OPENCLAW_FIX_2026-10-01.md from the
one live fetch each candidate got.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from scripts import openclaw_axis_worker as w  # noqa: E402
from core import taxonomy as tx  # noqa: E402
import build_taxonomy_key_map as bkm  # noqa: E402

CFG = json.loads((REPO / "config" / "openclaw_sources.json").read_text(encoding="utf-8"))
DECLARED = [s for s in CFG["sources"] if s.get("subcategory")]


def test_there_are_declared_seed_sources():
    assert len(DECLARED) >= 50, len(DECLARED)


@pytest.mark.parametrize("src", DECLARED, ids=[s["id"] for s in DECLARED])
def test_every_declared_seed_passes_the_declaration_rule(src):
    assert w.declaration_problems(src) == [], src["id"]
    assert w.subcategory_problem(src) is None, src["id"]
    assert not tx.is_system(src["subcategory"]), "a seed may not feed domain E"
    assert src["axis"] == f"TAXONOMY:{src['subcategory']}"
    assert src["url"].startswith("https://"), src["url"]


def test_seed_ids_are_unique():
    ids = [s["id"] for s in CFG["sources"]]
    assert len(ids) == len(set(ids))


def test_a_declared_subcategory_is_the_key_maps_rule():
    doc = bkm.build(dry=True)
    for s in DECLARED:
        assert doc["keys"][s["key"]]["subcategory"] == s["subcategory"], s["key"]


def test_a_declaration_that_contradicts_a_rule_is_refused():
    """Mutation: a seed that declares C3.3 for a key the rule table puts in C2.1."""
    with pytest.raises(bkm.Refused, match="contradicts"):
        bkm.declared_rules([{"key": "forest_area_pct", "subcategory": "C3.3", "id": "x"}],
                           bkm.rule_table())


def test_two_seeds_declaring_one_key_differently_are_refused():
    with pytest.raises(bkm.Refused, match="two subcategories"):
        bkm.declared_rules([{"key": "k_new", "subcategory": "C2.1", "id": "a"},
                            {"key": "k_new", "subcategory": "C3.3", "id": "b"}], {})
