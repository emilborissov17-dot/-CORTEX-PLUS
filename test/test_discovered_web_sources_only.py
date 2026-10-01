# -*- coding: utf-8 -*-
"""C-TURN-1 7c: memory/discovered_data_sources.json is shared by the composers and
the data-feed worker. A composer source of kind "file" (url local://snapshots/...)
is legitimate for a composer and is NOT a web source: the worker must not take it
into its fetch list, where it failed as InvalidSchema on every run."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from scripts import data_feed_reader as w  # noqa: E402

BLOB = {"SOCIAL_RELATIONS_REVIEW": {"sources": [
    {"url": "local://snapshots/master/global_indicators_latest.json#conflicts.active_armed_conflicts", "kind": "file",
     "format": "json", "extract": "conflicts.active_armed_conflicts", "status": "active", "org": "UCDP/PRIO"},
    {"url": "https://api.example.org/x.json", "kind": "http_json_path", "format": "json", "extract": "a.b",
     "status": "active", "org": "Example"}]}}


def test_a_composer_file_source_is_not_a_web_source(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(BLOB), encoding="utf-8")
    urls = [s["url"] for s in w.load_discovered(p)]
    assert urls == ["https://api.example.org/x.json"]


def test_mutation_without_the_scheme_check_local_would_be_fetched(tmp_path, monkeypatch):
    p = tmp_path / "d.json"
    p.write_text(json.dumps(BLOB), encoding="utf-8")
    monkeypatch.setattr(w, "is_web_source", lambda src: True)
    assert any(s["url"].startswith("local://") for s in w.load_discovered(p))
