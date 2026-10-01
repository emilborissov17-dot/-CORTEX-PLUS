# -*- coding: utf-8 -*-
"""test/test_taxonomy.py — core/taxonomy.py and the generated key map.

REFUSAL FIRST. load() must raise on a corrupted tree — a broken id, a broken
count, a subgoal that is not one of target_config's five or SYSTEM — and each
of those is tested on a corrupted COPY before anything about the happy path.

THE GUARD THAT MATTERS MOST is that domain E (the system itself) can never be
returned by a world-facing listing. It is tested twice: the listing never
contains E, and — as a mutation — with the filter removed the listing RAISES,
and with filter AND re-check removed the check in this file catches the leak.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from core import taxonomy as tx  # noqa: E402
import build_taxonomy_key_map as bkm  # noqa: E402

TREE_DOC = json.loads((REPO / "config" / "taxonomy.json").read_text(encoding="utf-8"))
KEY_MAP_DOC = json.loads((REPO / "config" / "taxonomy_key_map.json").read_text(encoding="utf-8"))


def _write(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "taxonomy.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _no_system(rows_or_map) -> bool:
    """The check this file applies to a world-facing listing, independent of
    core/taxonomy.py's own re-check, so the mutation test can remove both."""
    tree = tx.load()
    if isinstance(rows_or_map, dict):
        return all(tx.subcategory(s, tree)["domain"] != "E" for s in rows_or_map.values())
    return all(r["domain"] != "E" for r in rows_or_map)


# ── refusal ────────────────────────────────────────────────────────────────
def test_unreadable_file_raises(tmp_path: Path):
    p = tmp_path / "taxonomy.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(tx.TaxonomyError):
        tx.load(p)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(tx.TaxonomyError):
        tx.load(tmp_path / "absent.json")


def test_a_broken_id_raises(tmp_path: Path):
    """Mutation: one subcategory takes another's id."""
    doc = copy.deepcopy(TREE_DOC)
    subs = doc["domains"][0]["categories"][0]["subcategories"]
    subs[1]["id"] = subs[0]["id"]
    with pytest.raises(tx.TaxonomyError, match="duplicate id"):
        tx.load(_write(tmp_path, doc))


def test_an_id_outside_its_parent_raises(tmp_path: Path):
    doc = copy.deepcopy(TREE_DOC)
    doc["domains"][0]["categories"][0]["subcategories"][0]["id"] = "Z9.9"
    with pytest.raises(tx.TaxonomyError, match="not under category"):
        tx.load(_write(tmp_path, doc))


@pytest.mark.parametrize("which", ["domains", "categories", "subcategories"])
def test_a_broken_count_raises(tmp_path: Path, which: str):
    """Mutation: _meta.counts disagrees with the tree by one."""
    doc = copy.deepcopy(TREE_DOC)
    doc["_meta"]["counts"][which] += 1
    with pytest.raises(tx.TaxonomyError, match="count mismatch"):
        tx.load(_write(tmp_path, doc))


def test_a_removed_subcategory_raises_on_count(tmp_path: Path):
    doc = copy.deepcopy(TREE_DOC)
    doc["domains"][1]["categories"][0]["subcategories"].pop()
    with pytest.raises(tx.TaxonomyError, match="count mismatch"):
        tx.load(_write(tmp_path, doc))


def test_an_unknown_subgoal_raises(tmp_path: Path):
    doc = copy.deepcopy(TREE_DOC)
    doc["domains"][0]["categories"][0]["subgoal"] = "HAPPINESS"
    with pytest.raises(tx.TaxonomyError, match="subgoal"):
        tx.load(_write(tmp_path, doc))


def test_subgoals_come_from_target_config_not_from_this_file(tmp_path: Path):
    """A target_config that loses a sub-goal makes the tree that uses it refuse."""
    tc = json.loads((REPO / "config" / "target_config.json").read_text(encoding="utf-8"))
    tc.pop("SAFETY")
    p = tmp_path / "target_config.json"
    p.write_text(json.dumps(tc), encoding="utf-8")
    with pytest.raises(tx.TaxonomyError, match="SAFETY"):
        tx.load(target_path=p)


def test_an_unknown_subcategory_id_raises():
    with pytest.raises(tx.TaxonomyError):
        tx.subcategory("Q7.7")


# ── the tree as it is ───────────────────────────────────────────────────────
def test_counts_are_5_25_123():
    t = tx.load()
    assert t["counts"] == {"domains": 5, "categories": 25, "subcategories": 123}
    assert len(tx.subcategories(t)) == 123


def test_ids_are_unique():
    t = tx.load()
    ids = [d["id"] for d in TREE_DOC["domains"]]
    ids += [c["id"] for d in TREE_DOC["domains"] for c in d["categories"]]
    ids += [s["id"] for d in TREE_DOC["domains"] for c in d["categories"] for s in c["subcategories"]]
    assert len(ids) == len(set(ids)) == len(t["by_id"]) == 153


def test_folder_for_and_is_system():
    assert tx.folder_for("A1.1") == "atoms/A/A1/A1.1"
    assert tx.folder_for("E1.10") == "atoms/E/E1/E1.10"
    assert tx.is_system("E2.1") is True
    assert tx.is_system("C1.1") is False


# ── the key map ─────────────────────────────────────────────────────────────
def test_every_axis_with_a_primary_metric_resolves_to_a_subcategory():
    t = tx.load()
    km = tx.load_key_map(tree=t)
    pms = bkm.keys_target_config()
    assert pms, "target_config yielded no primary_metric: the test would pass vacuously"
    missing = [k for k in pms if k not in km]
    assert not missing, f"primary metrics with no subcategory: {missing}"
    for k in pms:
        assert tx.subcategory(km[k], t)["level"] == "subcategory"


def test_no_key_is_mapped_twice_in_the_rule_table():
    keys = [k for k, _s, _w in bkm.RULES]
    assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]


def test_a_duplicated_rule_is_refused():
    """Mutation: the same key ruled to two subcategories must not silently win."""
    dup = list(bkm.RULES) + [(bkm.RULES[0][0], "A1.1", "duplicate")]
    with pytest.raises(bkm.Refused):
        bkm.rule_table(dup)


def test_no_key_is_both_mapped_and_unmapped():
    mapped = set(KEY_MAP_DOC["keys"])
    unmapped = [u["key"] for u in KEY_MAP_DOC["unmapped"]]
    assert len(unmapped) == len(set(unmapped))
    assert not (mapped & set(unmapped))


def test_every_rule_targets_a_real_subcategory():
    t = tx.load()
    for key, sub, _why in bkm.RULES:
        tx.subcategory(sub, t)


# ── domain E never in a world-facing listing ────────────────────────────────
def test_world_listing_never_contains_domain_e():
    rows = tx.world_subcategories()
    assert len(rows) == 105
    assert _no_system(rows)


def test_world_keys_never_contain_a_domain_e_key():
    km = tx.load_key_map()
    assert any(tx.is_system(s) for s in km.values()), "no E key in the map: the test would be vacuous"
    assert _no_system(tx.world_keys(km))


def test_mutation_filter_removed_makes_the_listing_raise(monkeypatch):
    monkeypatch.setattr(tx, "_is_world", lambda row: True)
    with pytest.raises(tx.TaxonomyError, match="leaked"):
        tx.world_subcategories()
    with pytest.raises(tx.TaxonomyError, match="leaked"):
        tx.world_keys(tx.load_key_map())


def test_mutation_both_guards_removed_is_caught_by_this_files_check(monkeypatch):
    """If someone deletes the filter AND the re-check, the assertion used in
    test_world_listing_never_contains_domain_e must fail."""
    monkeypatch.setattr(tx, "_is_world", lambda row: True)
    monkeypatch.setattr(tx, "_assert_world", lambda rows: rows)
    assert not _no_system(tx.world_subcategories())
    assert not _no_system(tx.world_keys(tx.load_key_map()))
