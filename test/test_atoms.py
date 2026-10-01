# -*- coding: utf-8 -*-
"""test/test_atoms.py — an accepted card becomes one atom in its subcategory
folder (C-OC-1 Part 4, 1 Oct 2026).

Everything runs in tmp_path; the live atoms/ is never touched here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import atoms as at  # noqa: E402
from core import card_intake as ci  # noqa: E402

REC = {"axis": "TAXONOMY:C2.1", "key": "forest_area_pct", "value": 31.0951828663057,
       "unit": "pct_land_area", "url": "https://api.worldbank.org/v2/country/WLD/indicator/AG.LND.FRST.ZS?format=json&mrv=1",
       "quote": '31.0951828663057,"unit":"","obs_status":"","decimal":1}', "data_date": None,
       "subcategory": "C2.1", "place": "WLD", "period": "2023"}


def _row(rec=None, key="ck1"):
    rec = dict(REC if rec is None else rec)
    return {"card_key": key, "judged_utc": "2026-10-01T12:00:00+00:00", "verdict": "ACCEPTED",
            "gate": {"verdict": "ACCEPTED"}, "record": rec}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    monkeypatch.setattr(ci, "ACCEPTED", tmp_path / "verified_observations.jsonl")
    return tmp_path / "atoms"


# ── REWRITTEN 1 Oct 2026 (C-OC-3, Emil R27): labels, not refusals ───────────
def test_a_card_without_a_subcategory_is_filed_unplaced(root):
    rec = {k: v for k, v in REC.items() if k != "subcategory"}
    out = at.write(_row(rec), root=root)
    assert out["written"] is True and out["path"].startswith("_unplaced/")
    assert list(at.read(root=root))[0]["subcategory_how"] == "unknown"


def test_an_unresolvable_subcategory_is_a_dropped_label(root):
    out = at.write(_row(dict(REC, subcategory="Z9.9")), root=root)
    assert out["written"] is True and out["path"].startswith("_unplaced/")
    assert "does not resolve" in list(at.read(root=root))[0]["subcategory_how"]


def test_a_domain_e_subcategory_on_an_external_card_is_dropped_not_filed_in_e(root):
    out = at.write(_row(dict(REC, subcategory="E1.3")), root=root)
    assert out["written"] is True and not out["path"].startswith("E/")


def test_only_a_value_that_is_not_a_number_is_refused(root):
    with pytest.raises(at.AtomRefused):
        at.write(_row({k: v for k, v in REC.items() if k != "value"}), root=root)
    for drop in ("place", "period", "unit"):
        out = at.write(_row({k: v for k, v in REC.items() if k != drop}, key=f"ck-{drop}"), root=root)
        assert out["written"] is True or out.get("seen_again"), drop


def test_mutation_requiring_a_place_would_refuse_a_reading_with_none(root, monkeypatch):
    real = at.atom_of

    def strict(row):
        if not (row.get("record") or {}).get("place"):
            raise at.AtomRefused("place required")
        return real(row)
    monkeypatch.setattr(at, "atom_of", strict)
    with pytest.raises(at.AtomRefused):
        at.write(_row({k: v for k, v in REC.items() if k != "place"}), root=root)


# ── the atom ────────────────────────────────────────────────────────────────
def test_one_accepted_card_is_one_json_line_and_one_metta_line(root):
    out = at.write(_row(), root=root)
    folder = root / "C" / "C2" / "C2.1"
    j = (folder / "forest_area_pct.jsonl").read_text(encoding="utf-8").splitlines()
    m = (folder / "forest_area_pct.metta").read_text(encoding="utf-8").splitlines()
    assert len(j) == 1 and len(m) == 1 and out["written"] is True
    atom = json.loads(j[0])
    qh = hashlib.sha256(REC["quote"].encode("utf-8")).hexdigest()
    assert atom["quote_hash"] == qh and atom["card_key"] == "ck1" and atom["period"] == "2023"
    assert atom["source_class"] in ("independent", "adversarial", "self_reported", "unknown")
    assert m[0] == (f'(obs "C2.1" "forest_area_pct" "WLD" "2023" 31.095183 "pct_land_area" '
                    f'"{atom["source_class"]}" "{qh}")')


def test_writing_the_same_card_twice_adds_nothing(root):
    at.write(_row(), root=root)
    out = at.write(_row(), root=root)
    assert out["written"] is False and "already" in out["why"]
    assert len((root / "C" / "C2" / "C2.1" / "forest_area_pct.jsonl").read_text().splitlines()) == 1


def test_a_hostile_key_cannot_escape_the_folder(root):
    out = at.write(_row(dict(REC, key="../../etc/passwd")), root=root)
    assert out["written"] is True
    assert all(root in p.parents for p in root.rglob("*.jsonl"))


# ── the manifest ────────────────────────────────────────────────────────────
def test_the_manifest_is_recomputed_from_disk_not_incremented(root):
    at.write(_row(), root=root)
    man = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    f = "C/C2/C2.1/forest_area_pct.jsonl"
    assert man["files"][f]["lines"] == 1
    assert man["files"][f]["sha256"] == hashlib.sha256((root / f).read_bytes()).hexdigest()
    # a hand edit to the manifest does not survive the next write
    man["files"][f]["lines"] = 99
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")
    at.write(_row(dict(REC, period="2024", value=31.2), key="ck2"), root=root)
    man = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    assert man["files"][f]["lines"] == 2


def test_mutation_an_incremented_manifest_would_keep_the_hand_edit(root, monkeypatch):
    at.write(_row(), root=root)
    f = "C/C2/C2.1/forest_area_pct.jsonl"
    man = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    man["files"][f]["lines"] = 99
    (root / "MANIFEST.json").write_text(json.dumps(man), encoding="utf-8")

    def incremented(r):
        m = json.loads((r / "MANIFEST.json").read_text(encoding="utf-8"))
        m["files"][f]["lines"] += 1
        return m
    monkeypatch.setattr(at, "compute_manifest", incremented)
    at.write(_row(dict(REC, period="2024", value=31.2), key="ck2"), root=root)
    assert json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))["files"][f]["lines"] == 100


# ── retraction ──────────────────────────────────────────────────────────────
def test_a_retracted_card_is_skipped_by_read_and_manifest_and_stays_on_disk(root):
    ci.ACCEPTED.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    at.write(_row(), root=root)
    f = root / "C" / "C2" / "C2.1" / "forest_area_pct.jsonl"
    before = f.read_bytes()
    ci.retract("ck1", reason="test", by="test")
    assert list(at.read(root=root)) == []
    assert f.read_bytes() == before
    man = at.compute_manifest(root)
    assert man["files"]["C/C2/C2.1/forest_area_pct.jsonl"]["lines"] == 1
    assert man["files"]["C/C2/C2.1/forest_area_pct.jsonl"]["live_lines"] == 0
    assert man["subcategories_with_live_atoms"] == []


def test_mutation_without_the_retraction_filter_read_returns_it(root, monkeypatch):
    ci.ACCEPTED.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    at.write(_row(), root=root)
    ci.retract("ck1", reason="test", by="test")
    monkeypatch.setattr(ci, "retracted_keys", lambda path=None: set())
    assert len(list(at.read(root=root))) == 1


# ── card_intake wiring ──────────────────────────────────────────────────────
def test_judge_inbox_writes_an_atom_for_an_accepted_card_and_counts_the_rest(tmp_path, root):
    inbox = tmp_path / "cards"
    inbox.mkdir()
    no_sub = {k: v for k, v in REC.items() if k not in ("subcategory",)}
    page = '[{"page":1},[{"date":"2023","value":31.0951828663057,"unit":"","obs_status":"","decimal":1}]]'
    (inbox / "x.jsonl").write_text(json.dumps(REC) + "\n" + json.dumps(dict(no_sub, place="ISL")) + "\n",
                                   encoding="utf-8")
    c = ci.judge_inbox(inbox=inbox, fetch=lambda u: page, accepted_path=tmp_path / "acc.jsonl",
                       refused_path=tmp_path / "ref.jsonl", atoms_root=root)
    # C-OC-3: the card without a subcategory is judged on its quote and filed unplaced
    assert c["accepted"] == 2 and c["atoms_written"] == 2
    assert (root / "MANIFEST.json").exists()


def test_selftest_reports_integrations():
    r = at.selftest()
    assert set(r["integrations"]) >= {"config/taxonomy.json", "config/reporter_independence.json",
                                      "config/data_feeds.json"}


def test_a_judge_on_non_live_observations_never_writes_live_atoms(tmp_path, root, monkeypatch):
    """1 Oct 2026: fixture atoms leaked into the repo's atoms/ this way."""
    sentinel = tmp_path / "LIVE_ATOMS"
    monkeypatch.setattr(at, "ROOT", sentinel)
    inbox = tmp_path / "cards"
    inbox.mkdir()
    page = '[{"page":1},[{"date":"2023","value":31.0951828663057,"unit":"","obs_status":"","decimal":1}]]'
    (inbox / "x.jsonl").write_text(json.dumps(REC) + chr(10), encoding="utf-8")
    c = ci.judge_inbox(inbox=inbox, fetch=lambda u: page, accepted_path=tmp_path / "acc.jsonl",
                       refused_path=tmp_path / "ref.jsonl")
    assert c["atoms_written"] == 1
    assert not sentinel.exists(), "a test judge wrote into the live atoms root"
    assert any((tmp_path / "atoms").rglob("*.jsonl"))


def test_mutation_a_default_that_ignores_accepted_path_would_write_live(tmp_path, monkeypatch):
    sentinel = tmp_path / "LIVE_ATOMS"
    monkeypatch.setattr(at, "ROOT", sentinel)
    monkeypatch.setattr(ci, "_atoms_root_for", lambda accepted_path, atoms_root: atoms_root)
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "ret.jsonl")
    inbox = tmp_path / "cards"
    inbox.mkdir()
    page = '[{"page":1},[{"date":"2023","value":31.0951828663057,"unit":"","obs_status":"","decimal":1}]]'
    (inbox / "x.jsonl").write_text(json.dumps(REC) + chr(10), encoding="utf-8")
    ci.judge_inbox(inbox=inbox, fetch=lambda u: page, accepted_path=tmp_path / "acc.jsonl",
                   refused_path=tmp_path / "ref.jsonl")
    assert sentinel.exists()
