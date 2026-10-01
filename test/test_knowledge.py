# -*- coding: utf-8 -*-
"""test/test_knowledge.py — core.knowledge (C-OC-3 Part 1).

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
    e = kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                     wait=lambda: None)
    assert e["embedded"] == 3 and e["remaining"] == 0
    again = kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                     wait=lambda: None)
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
    kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                     wait=lambda: None)
    monkeypatch.setattr(kn, "SUBCAT_THRESHOLD", 0.99)
    kn.label_all(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                 out=paths["labels"])
    lab = list(json.loads(paths["labels"].read_text(encoding="utf-8"))["labels"].values())[0]
    assert lab["subcategory"] == "unplaced"
    items = kn.read("anything", k=5, embed=stub_embed, store=paths["store"], vec_path=paths["vec"], field_index={},
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
    kn.embed_pending(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                     wait=lambda: None)
    kn.label_all(embed=stub_embed, store=paths["store"], vec_path=paths["vec"], ids_path=paths["ids"],
                 out=paths["labels"])
    items = kn.read("forest area", k=10, embed=stub_embed, store=paths["store"], vec_path=paths["vec"], field_index={},
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
    from scripts import data_feed_reader as w
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
                         ids_path=paths["ids"], wait=lambda: None)
    ids, mat = kn.load_vectors(paths["vec"], paths["ids"])
    assert len(ids) == 256 * 20 == mat.shape[0]


# ── existing caches (Part 2) ────────────────────────────────────────────────
def _caches(tmp_path):
    wi = tmp_path / "wi" / "2026-09-30" / "planet"; wi.mkdir(parents=True)
    item = {"title": "Sea ice hits a record low", "summary": "Antarctic winter ice peaked early.",
            "link": "https://nsidc.org/a"}
    (wi / "x_web_intel.json").write_text(json.dumps({"raw_items": [item], "analysis": {
        "problem": "MODEL SAID THIS"}}), encoding="utf-8")
    wi2 = tmp_path / "wi" / "2026-10-01"; wi2.mkdir(parents=True)
    (wi2 / "y_web_intel.json").write_text(json.dumps({"raw_items": [item]}), encoding="utf-8")   # same article again
    news = tmp_path / "news" / "2026-10-01"; news.mkdir(parents=True)
    (news / "e.json").write_text(json.dumps({"rss": [{"title": "Grid model opened", "snippet": "A tool.",
                                                      "url": "https://t.org/g"}], "podcast": "A talk on AI."}),
                                 encoding="utf-8")
    (news / "broken.json").write_text("{not json", encoding="utf-8")
    tr = tmp_path / "tr"; tr.mkdir()
    (tr / "v1.json").write_text(json.dumps({"video_id": "v1", "transcript": "Hello there. Bye now."}),
                                encoding="utf-8")
    bs = tmp_path / "bs"; bs.mkdir()
    (bs / "c.json").write_text(json.dumps({"metric": "conflicts", "value": 56, "source_url": "https://ucdp.uu.se/"}),
                               encoding="utf-8")
    return {"web_intelligence": tmp_path / "wi", "news": tmp_path / "news", "transcript_cache": tr,
            "browse_sources": bs}


def test_caches_ingest_per_item_with_counts_per_origin(paths, tmp_path):
    roots = _caches(tmp_path)
    r = kn.ingest_caches(roots=roots, store=paths["store"], seen_path=paths["seen"])
    assert r["web_intelligence"]["items"] == 2 and r["web_intelligence"]["skipped_same_content"] == 1
    assert r["news"]["items"] == 2 and r["news"]["unreadable_files"] == 1
    assert r["transcript_cache"]["statements_added"] == 2 and r["browse_sources"]["statements_added"] >= 1
    recs = kn.statements(paths["store"])
    sents = " ".join(x["sentence"] for x in recs)
    assert "MODEL SAID THIS" not in sents, "a model's analysis was stored as a source's words"
    assert {x["host"] for x in recs if "Sea ice" in x["sentence"]} == {"nsidc.org"}
    again = kn.ingest_caches(roots=roots, store=paths["store"], seen_path=paths["seen"])
    assert sum(v["statements_added"] for v in again.values()) == 0, "a second pass wrote something twice"


def test_a_transcript_ingested_before_under_its_path_is_held(paths, tmp_path):
    roots = _caches(tmp_path)
    from core import statements as st
    sid = (roots["transcript_cache"] / "v1.json").as_posix()
    rep = st.ingest_text(sid, "Hello there. Bye now.", origin="transcript")   # as statements.py --ingest did:
    with paths["store"].open("a", encoding="utf-8") as fh:                     # straight to the store
        for rec in rep["records"]:
            fh.write(json.dumps(rec) + chr(10))
    r = kn.ingest_caches(origins=["transcript_cache"], roots=roots, store=paths["store"], seen_path=paths["seen"])
    assert r["transcript_cache"]["statements_added"] == 0 and r["transcript_cache"]["already_held"] == 2


def test_ingest_batch_writes_the_seen_index_once(paths, monkeypatch):
    writes = []
    real = Path.write_text
    monkeypatch.setattr(Path, "write_text", lambda self, *a, **k: (writes.append(self), real(self, *a, **k))[1])
    kn.ingest_batch(({"source_id": f"s{i}", "text": f"Line {i}."} for i in range(50)),
                    store=paths["store"], seen_path=paths["seen"])
    assert writes.count(paths["seen"]) == 1
