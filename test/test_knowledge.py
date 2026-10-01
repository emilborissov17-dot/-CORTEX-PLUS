# -*- coding: utf-8 -*-
"""test/test_knowledge.py — core.knowledge: the store the brain reads (C-OC-3 Part 1).

Labels order, they never remove. Every store, vector file and label file here is
under tmp_path; the embedder is a deterministic stub (hashed bag of words), so no
model runs.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import knowledge as kn  # noqa: E402


def stub_embed(texts):
    out = []
    for t in texts:
        v = np.zeros(768, dtype="float32")
        for w in re.findall(r"[a-z]+", t.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 768] += 1.0
        out.append(v.tolist())
    return out


@pytest.fixture
def paths(tmp_path, monkeypatch):
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    return {"store": tmp_path / "s.jsonl", "seen": tmp_path / "seen.json", "vec": tmp_path / "v.npy",
            "ids": tmp_path / "ids.json", "labels": tmp_path / "labels.json", "atoms": tmp_path / "atoms"}


def _ingest(p, sid, text, url):
    return kn.ingest(sid, text, url=url, store=p["store"], seen_path=p["seen"])


def test_ingest_dedups_by_source_and_content(paths):
    a = _ingest(paths, "s1", "Rivers flooded the valley. Crops were lost.", "https://a.org/x")
    b = _ingest(paths, "s1", "Rivers flooded the valley. Crops were lost.", "https://a.org/x")
    c = _ingest(paths, "s2", "Rivers flooded the valley. Crops were lost.", "https://b.org/y")
    assert a["added"] == 2 and b["outcome"] == "SKIPPED_SAME_CONTENT" and c["added"] == 2
    hosts = {r["host"] for r in kn.statements(paths["store"])}
    assert hosts == {"a.org", "b.org"}


def test_body_to_text_json_html_and_unreadable_pdf():
    t, form = kn.body_to_text('{"a": {"b": 1}}', {"a": {"b": 1}}, "application/json")
    assert form == "json" and "b=1" in t
    t, form = kn.body_to_text("<p>Hello world.</p>", None, "text/html")
    assert form == "html" and "Hello world." in t
    _t, form = kn.body_to_text("%PDF-1.7 ...", None, "application/pdf")
    assert form == "pdf_unreadable"


def test_kind_rules_come_from_config_and_default_is_other():
    rules = [{"kind": "event", "pattern": r"\bflooded\b"}]
    assert kn.kind_of("Rivers flooded the valley.", rules) == "event"
    assert kn.kind_of("A quiet day.", rules) == "other"


def test_embed_pending_then_label_corroborates_across_hosts_only(paths, monkeypatch):
    _ingest(paths, "s1", "Rivers flooded the valley.", "https://a.org/x")
    _ingest(paths, "s2", "Rivers flooded the valley.", "https://b.org/y")
    _ingest(paths, "s3", "Rivers flooded the valley.", "https://a.org/z")       # same host as s1
    e = kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"])
    assert e["embedded"] == 3 and e["remaining"] == 0
    again = kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"])
    assert again["embedded"] == 0, "a statement was embedded twice"
    r = kn.label_all(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                     out=paths["labels"])
    assert r["labelled"] == 3
    labs = json.loads(paths["labels"].read_text(encoding="utf-8"))["labels"]
    by_host = {}
    for rec in kn.statements(paths["store"]):
        by_host.setdefault(rec["host"], []).append(labs[rec["id"]]["corroborated_by"])
    assert by_host == {"a.org": [1, 1], "b.org": [1]}


def test_a_low_scoring_statement_is_labelled_unplaced_and_still_read(paths, monkeypatch):
    _ingest(paths, "s1", "Zzzq wibble frobnicate.", "https://a.org/x")
    kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"])
    monkeypatch.setattr(kn, "SUBCAT_THRESHOLD", 0.99)
    kn.label_all(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                 out=paths["labels"])
    lab = list(json.loads(paths["labels"].read_text(encoding="utf-8"))["labels"].values())[0]
    assert lab["subcategory"] == "unplaced"
    items = kn.read("anything", k=5, embed=stub_embed, store=paths["store"], vec_path=paths["vec"],
                    ids_path=paths["ids"], labels_path=paths["labels"], atoms_root=paths["atoms"])
    assert [i["text"] for i in items] == ["Zzzq wibble frobnicate."], "an unplaced statement was withheld"


def test_read_returns_statements_and_atoms_together_and_orders_by_corroboration(paths):
    from core import atoms as at
    _ingest(paths, "s1", "Forest area fell sharply.", "https://a.org/x")
    _ingest(paths, "s2", "Forest area fell sharply.", "https://b.org/y")
    _ingest(paths, "s3", "Forest area fell sharply!", "https://c.org/z")
    row = {"card_key": "ck1", "source_id": "src", "verdict": "ACCEPTED", "gate": {"verdict": "ACCEPTED"},
           "record": {
        "axis": "A", "key": "forest_area_pct", "value": 31.1, "unit": "pct", "url": "https://w.org",
        "quote": "31.1", "period": "2023", "place": "WLD", "subcategory": "C2.1"}}
    assert at.write(row, root=paths["atoms"])["written"] is True
    kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"])
    kn.label_all(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                 out=paths["labels"])
    items = kn.read("forest area", k=10, embed=stub_embed, store=paths["store"], vec_path=paths["vec"],
                    ids_path=paths["ids"], labels_path=paths["labels"], atoms_root=paths["atoms"])
    types = {i["type"] for i in items}
    assert types == {"statement", "measurement"}
    meas = [i for i in items if i["type"] == "measurement"][0]
    assert meas["value"] == 31.1 and meas["labels"]["period"] == "2023"


def test_contradictions_count_other_values_for_the_same_key_place_period():
    atoms = [{"card_key": "a", "key": "k", "place": "P", "period": "2023", "value": 1.0},
             {"card_key": "b", "key": "k", "place": "P", "period": "2023", "value": 2.0},
             {"card_key": "c", "key": "k", "place": "P", "period": "2024", "value": 9.0}]
    assert kn.contradictions(atoms) == {"a": 1, "b": 1, "c": 0}


def test_selftest_reports_integrations_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(kn, "STORE", tmp_path / "none.jsonl")
    monkeypatch.setattr(kn, "VECTORS", tmp_path / "none.npy")
    monkeypatch.setattr(kn, "VECTOR_IDS", tmp_path / "none.json")
    monkeypatch.setattr(kn, "LABELS", tmp_path / "nolabels.json")
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))
    r = kn.selftest()
    assert r["integrations"]["memory/statements.jsonl (the store)"].startswith("INERT")
    assert r["integrations"]["ollama nomic-embed-text"].startswith("INERT")
    assert not list(tmp_path.iterdir()), "selftest wrote a file"


def test_mutation_a_worker_run_without_ingest_reports_inert(monkeypatch, tmp_path):
    from scripts import openclaw_axis_worker as w
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("offline")))
    key = "worker ingests every fetched page"
    assert kn.selftest()["integrations"][key] == "LIVE"
    monkeypatch.setattr(w, "run", lambda sources_path, queue_dir=None: None)
    assert kn.selftest()["integrations"][key] == "INERT"


def test_a_changed_page_writes_only_its_new_sentences(paths):
    _ingest(paths, "feed", "Quake A struck. Quake B struck.", "https://a.org/f")
    r = _ingest(paths, "feed", "Quake A struck. Quake B struck. Quake C struck.", "https://a.org/f")
    assert (r["added"], r["already_held"]) == (1, 2)
    sents = [x["sentence"] for x in kn.statements(paths["store"])]
    assert sorted(sents) == ["Quake A struck.", "Quake B struck.", "Quake C struck."]


def test_repeats_inside_one_page_are_kept(paths):
    r = _ingest(paths, "t", "Yes. Yes. No.", "https://a.org/t")
    assert r["added"] == 3


def test_mutation_without_the_held_check_a_changed_page_writes_twice(paths, monkeypatch):
    monkeypatch.setattr(kn, "_sentences_of", lambda store: {})
    _ingest(paths, "feed", "Quake A struck. Quake B struck.", "https://a.org/f")
    _ingest(paths, "feed", "Quake A struck. Quake B struck. Quake C struck.", "https://a.org/f")
    assert len(kn.statements(paths["store"])) == 5


def test_embed_pending_checkpoints_so_a_killed_run_keeps_its_vectors(paths):
    text = " ".join(f"Sentence number {chr(97 + i % 26)}{i}." for i in range(256 * 20 + 10))
    _ingest(paths, "big", text, "https://a.org/b")
    calls = {"n": 0}

    def dies_after_checkpoint(texts):
        calls["n"] += 1
        if calls["n"] > 20:
            raise RuntimeError("killed")
        return stub_embed(texts)
    with pytest.raises(RuntimeError):
        kn.embed_pending(embed=dies_after_checkpoint, store=paths["store"], vec_path=paths["vec"],
                         ids_path=paths["ids"])
    ids, mat = kn.load_vectors(paths["vec"], paths["ids"])
    assert len(ids) == 256 * 20 == mat.shape[0]
