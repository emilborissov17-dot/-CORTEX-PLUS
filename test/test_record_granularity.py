# -*- coding: utf-8 -*-
"""test/test_record_granularity.py — a JSON record is ONE statement (C-TURN-1 7a).
Old field-level rows stay and are marked so the reader collapses them by record."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import knowledge as kn  # noqa: E402

EONET = {"title": "EONET Events", "events": [
    {"id": "EONET_1", "title": "Flood in Thailand. Severe.", "categories": [{"id": "floods"}],
     "geometry": [{"date": "2026-10-04", "coordinates": [17.7, 97.7]}]},
    {"id": "EONET_2", "title": "Wildfire", "categories": [{"id": "wildfires"}], "geometry": []}]}


def test_one_record_is_one_line_with_everything_nested_in_it():
    lines = kn.flatten_json(EONET).splitlines()
    assert lines[0] == "$: title=EONET Events"
    assert lines[1].startswith("events.0: id=EONET_1; title=Flood in Thailand. Severe.; categories.0.id=floods")
    assert "geometry.0.coordinates=[17.7, 97.7]" in lines[1] and len(lines) == 3


def test_a_record_with_a_full_stop_inside_stays_one_statement(tmp_path):
    text = kn.flatten_json(EONET)
    r = kn.ingest("eonet", text, url="https://eonet.example/e", store=tmp_path / "s.jsonl", seen_path=tmp_path / "seen.json",
                  extra={"granularity": "record"})
    assert r["added"] == 3
    rows = kn.statements(tmp_path / "s.jsonl")
    assert all(x["granularity"] == "record" for x in rows)


def test_mutation_without_line_mode_the_record_splits_at_its_full_stop(tmp_path):
    text = kn.flatten_json(EONET)
    r = kn.ingest("eonet", text, url="https://eonet.example/e", store=tmp_path / "s.jsonl", seen_path=tmp_path / "seen.json")
    assert r["added"] > 3


def test_flattening_is_still_lossless():
    kn.assert_flatten_lossless(EONET, kn.flatten_json(EONET))


def test_record_key_of_field_level_paths():
    assert kn.record_key("events.0.geometry.0: date=x") == "events.0"
    assert kn.record_key("events.0: id=E") == "events.0"
    assert kn.record_key("1.0: indicator.id=AG") == "1.0"
    assert kn.record_key("$: title=EONET") == "$"
    assert kn.record_key("A plain sentence.") is None


def test_old_field_rows_are_marked_and_collapse_by_record(tmp_path):
    store = tmp_path / "s.jsonl"
    rows = [{"id": "f0", "source_id": "eonet", "sentence": "$: title=EONET Events", "content_sha256": "h", "index": 0},
            {"id": "f1", "source_id": "eonet", "sentence": "events.0: id=EONET_1; title=Flood", "content_sha256": "h"},
            {"id": "f2", "source_id": "eonet", "sentence": "events.0.categories.0: id=floods", "content_sha256": "h"},
            {"id": "f3", "source_id": "eonet", "sentence": "events.1: id=EONET_2; title=Wildfire", "content_sha256": "h"},
            {"id": "t1", "source_id": "talk", "sentence": "A flood hit the region.", "origin": "transcript"}]
    store.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    per = kn.mark_field_granularity(store, tmp_path / "idx.json")
    assert per == {"eonet": 4}
    idx = json.loads((tmp_path / "idx.json").read_text(encoding="utf-8"))["rows"]
    items = [{"type": "statement", "id": r["id"], "text": r["sentence"], "source_id": r["source_id"], "relevance": 0.5,
              "corroborated_by": 0} for r in rows]
    out = kn.collapse_fields(items, idx)
    assert len(out) == 4 and out[1]["ids"] == ["f1", "f2"] and "id=floods" in out[1]["text"]


def test_mutation_without_the_index_nothing_collapses():
    items = [{"type": "statement", "id": "f1", "text": "a", "source_id": "s", "relevance": 0.1, "corroborated_by": 0},
             {"type": "statement", "id": "f2", "text": "b", "source_id": "s", "relevance": 0.1, "corroborated_by": 0}]
    assert len(kn.collapse_fields(items, {})) == 2


def test_an_html_page_with_label_colons_is_not_marked(tmp_path):
    store = tmp_path / "s.jsonl"
    rows = [{"id": "h0", "source_id": "blog", "sentence": "Welcome to the blog.", "content_sha256": "p", "index": 0},
            {"id": "h1", "source_id": "blog", "sentence": "Note: this is not a path.", "content_sha256": "p", "index": 1}]
    store.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert kn.mark_field_granularity(store, tmp_path / "idx.json") == {}
