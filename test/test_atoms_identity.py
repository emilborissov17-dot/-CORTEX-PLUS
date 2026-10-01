# -*- coding: utf-8 -*-
"""test/test_atoms_identity.py — an observation seen again is one observation
(C-OC-3 Part 0, 1 Oct 2026).

Identity = (source_id, key, place, period, value). A period read from a
PROCESSING-TIME field (the feed's own clock: generated, updated, fetched, ts)
is labelled how="processing_time" and never enters identity; for a rolling-window
count it becomes the window's end DAY (how="window_end_day"). The USGS case of
1 Oct is the fixture: 13.0 at generated=1790857400000 and again at
1790857520000 is ONE atom, seen twice. Nothing on disk is deleted; read() and
the manifest collapse. Mutation: an identity with the raw stamp brings the
duplicate back.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import atoms as at  # noqa: E402
from core import card_intake as ci  # noqa: E402

GEN1, GEN2 = "1790857400000", "1790857520000"     # 2026-10-01 12:23:20Z / 12:25:20Z


def _row(value=13.0, period=GEN1, how="window_end_day", ck="ck1", quote='13,"title":"USGS"'):
    rec = {"axis": "TAXONOMY:C5.1", "key": "quake_m45_count", "value": value, "unit": "events_past_day",
           "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
           "quote": quote, "subcategory": "C5.1", "place": "WLD", "period": period, "period_how": how}
    return {"card_key": ck, "judged_utc": "2026-10-01T12:25:00+00:00", "verdict": "ACCEPTED", "record": rec}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "ret.jsonl")
    monkeypatch.setattr(ci, "ACCEPTED", tmp_path / "acc.jsonl")
    return tmp_path / "atoms"


def test_period_classification_reads_the_field_name():
    assert at.classify_period("metadata.generated", GEN1, rolling=True) == ("2026-10-01", "window_end_day")
    assert at.classify_period("metadata.generated", GEN1, rolling=False) == (GEN1, "processing_time")
    for f in ("x.updated", "0.lastupdated", "fetched_at", "row.ts", "generated_at"):
        assert at.classify_period(f, "2026-09-30", rolling=False)[1] == "processing_time", f
    assert at.classify_period("1.0.date", "2024", rolling=False) == ("2024", "same_record")


def test_a_second_fetch_with_a_new_generated_stamp_is_the_same_observation(root):
    at.write(_row(period=GEN1, ck="ck1"), root=root)
    out = at.write(_row(period=GEN2, ck="ck2", quote='13,"title":"USGS","generated":2'), root=root)
    atoms = list(at.read(root=root))
    assert out["written"] is False and out.get("seen_again") is True
    assert len(atoms) == 1
    assert atoms[0]["times_seen"] == 2 and atoms[0]["last_seen_utc"]


def test_a_changed_value_is_a_new_observation(root):
    at.write(_row(value=13.0, ck="ck1"), root=root)
    out = at.write(_row(value=14.0, period=GEN2, ck="ck2"), root=root)
    assert out["written"] is True
    assert sorted(a["value"] for a in at.read(root=root)) == [13.0, 14.0]


def test_processing_time_period_never_enters_identity(root):
    at.write(_row(period=GEN1, how="processing_time", ck="ck1"), root=root)
    at.write(_row(period=GEN2, how="processing_time", ck="ck2"), root=root)
    assert len(list(at.read(root=root))) == 1


def test_legacy_duplicate_lines_on_disk_collapse_and_are_counted(root):
    """The two lines C-OC-2 wrote, without period_how, stay on disk and collapse."""
    folder = root / "C" / "C5" / "C5.1"
    folder.mkdir(parents=True)
    legacy = []
    for gen, ck in ((GEN1, "a"), (GEN2, "b")):
        legacy.append({"subcategory": "C5.1", "key": "quake_m45_count", "value": 13.0, "unit": "events_past_day",
                       "place": "WLD", "period": gen, "source_id": "usgs:summary_4.5_day", "source_class": "independent",
                       "quote_hash": "q", "card_key": ck, "judged_utc": "2026-10-01T12:25:00+00:00"})
    (folder / "quake_m45_count.jsonl").write_text("".join(json.dumps(x) + chr(10) for x in legacy), encoding="utf-8")
    atoms = list(at.read(root=root))
    assert len(atoms) == 1 and atoms[0]["times_seen"] == 2
    man = at.compute_manifest(root)
    assert man["collapsed"] == 1 and man["atoms_total"] == 2 and man["atoms_live"] == 1
    assert len((folder / "quake_m45_count.jsonl").read_text().splitlines()) == 2, "nothing deleted"


def test_mutation_identity_with_the_raw_stamp_brings_the_duplicate_back(root, monkeypatch):
    monkeypatch.setattr(at, "identity_of", lambda a: (a.get("source_id"), a.get("key"), a.get("place"),
                                                      a.get("raw_period", a.get("period")), a.get("value")))
    at.write(_row(period=GEN1, ck="ck1"), root=root)
    at.write(_row(period=GEN2, ck="ck2"), root=root)
    assert len(list(at.read(root=root))) == 2
