# -*- coding: utf-8 -*-
"""test/test_page_regions.py — pages lose their furniture by LABEL, not by deletion
(C-BRAIN-1 Part 3). The HTML is stored beside the text; trafilatura's main text
labels each statement "main" or "furniture"; the reader shows a need's own
statements first, main before furniture. Nothing is removed (R27).

A REFUSAL here: a page whose main text trafilatura cannot find is labelled all
"main" and logged MAIN_UNKNOWN — never guessed, never dropped. HTML over 5 MB is
not stored and HTML_TOO_LARGE is logged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import knowledge as kn  # noqa: E402
from scripts import openclaw_search as oc  # noqa: E402

ARTICLE = ("Floods displaced 40,000 people in Kerala in August 2025. "
           "The state government opened 300 relief camps across six districts. "
           "Rainfall was 87 percent above the seasonal average, the weather office said.")
MENU = ["Home", "About us", "Contact", "Subscribe to our newsletter"]
HTML = ("<html><head><title>Kerala floods</title></head><body>"
        "<nav><ul>" + "".join(f"<li><a href='/x'>{m}</a></li>" for m in MENU) + "</ul></nav>"
        "<article><h1>Kerala floods</h1>" + "".join(f"<p>{s}.</p>" for s in ARTICLE.split(". ") if s)
        + "</article><footer><p>Subscribe to our newsletter</p></footer></body></html>")


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


@pytest.fixture
def p(tmp_path, monkeypatch):
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    return {"store": tmp_path / "s.jsonl", "seen": tmp_path / "seen.json"}


def _recs(*sentences):
    return [{"id": f"s{i}", "sentence": s} for i, s in enumerate(sentences)]


# ── 3a: the label ───────────────────────────────────────────────────────────
def test_trafilatura_finds_the_article_and_not_the_menu():
    m = kn.main_text(HTML)
    assert "relief camps" in m and "About us" not in m


def test_menu_lines_are_furniture_and_article_sentences_are_main():
    recs = _recs("Home", "About us", "The state government opened 300 relief camps across six districts.")
    assert kn.label_regions(recs, kn.main_text(HTML)) is False
    assert [r["region"] for r in recs] == ["furniture", "furniture", "main"]


def test_an_empty_extraction_labels_all_main_and_says_main_unknown():
    recs = _recs("Home", "Some text.")
    assert kn.label_regions(recs, "") is True
    assert [r["region"] for r in recs] == ["main", "main"]


def test_mutation_an_empty_extraction_treated_as_known_would_make_all_furniture(monkeypatch):
    recs = _recs("Home", "Some text.")
    monkeypatch.setattr(kn, "_squash", lambda s: (s or "").strip().lower() or "\x00")
    kn.label_regions(recs, "")
    assert [r["region"] for r in recs] == ["furniture", "furniture"], "the empty-main guard did not matter"


def test_labelling_never_removes_a_record():
    recs = _recs("Home", "About us", "Contact", "Floods displaced 40,000 people in Kerala in August 2025.")
    kn.label_regions(recs, kn.main_text(HTML))
    assert len(recs) == 4


def test_ingest_labels_every_record_and_stores_no_main_text(p):
    text = "\n".join(MENU) + "\n" + ARTICLE
    r = kn.ingest("url:k", text, url="https://k.example/a", store=p["store"], seen_path=p["seen"],
                  extra={"main_text": kn.main_text(HTML), "need_id": "BN-1"})
    recs = kn.statements(p["store"])
    assert r["main_unknown"] is False and r["regions"]["main"] >= 3 and r["regions"]["furniture"] >= 3
    assert all(x["region"] in ("main", "furniture") for x in recs)
    assert not any("main_text" in x for x in recs)
    assert {x["sentence"] for x in recs if x["region"] == "furniture"} >= {"Home", "About us", "Contact"}


def test_ingest_without_html_leaves_records_unlabelled(p):
    r = kn.ingest("url:k", ARTICLE, url="https://k.example/a", store=p["store"], seen_path=p["seen"])
    assert r["main_unknown"] is None and not any("region" in x for x in kn.statements(p["store"]))


# ── 3.0: the HTML beside the text ───────────────────────────────────────────
def test_the_html_is_stored_beside_the_text(tmp_path):
    st = oc.store_page("https://k.example/a", ARTICLE, "BN-1", {}, tmp_path, html=HTML, ledger=lambda r: None)
    doc = json.loads((tmp_path / f"{st['sha256']}.json").read_text(encoding="utf-8"))
    assert st["html"] is True and doc["html"] == HTML and doc["text"] == ARTICLE


def test_html_over_the_cap_is_not_stored_and_is_logged(tmp_path, monkeypatch):
    rows = []
    monkeypatch.setattr(oc, "HTML_CAP", 100)
    st = oc.store_page("https://k.example/a", ARTICLE, "BN-1", {}, tmp_path, html=HTML, ledger=rows.append)
    doc = json.loads((tmp_path / f"{st['sha256']}.json").read_text(encoding="utf-8"))
    assert st["html"] is False and "html" not in doc and doc["text"] == ARTICLE
    assert rows[0]["event"] == "HTML_TOO_LARGE" and rows[0]["bytes"] == len(HTML.encode("utf-8"))


def test_the_cap_is_five_megabytes():
    assert oc.HTML_CAP == 5 * 1024 * 1024


def test_the_page_script_returns_the_html():
    assert "outerHTML" in oc._TEXT_JS


class Browser:
    def __init__(self, page):
        self.page = page

    def search(self, query):
        return {"page": {"title": "r", "text": "r", "url": "https://html.duckduckgo.com/"},
                "links": [{"url": "https://duckduckgo.com/l/?uddg=https://k.example/a", "title": "a"}], "raw": {}}

    def read(self, url):
        return {"page": self.page, "raw": {"ok": True, "result": json.dumps(self.page)}}


def test_serve_labels_from_the_html_it_was_given(tmp_path):
    got, rows = [], []

    def ingest(source_id, text, url="", origin="", extra=None):
        got.append(extra)
        return {"added": 1, "main_unknown": False}
    oc.serve("BN-1", "q", Browser({"title": "K", "text": ARTICLE, "url": "https://k.example/a", "html": HTML}),
             ingest, rows.append, pages_dir=tmp_path)
    assert "relief camps" in got[0]["main_text"] and "MAIN_UNKNOWN" not in [r["event"] for r in rows]


def test_serve_logs_main_unknown(tmp_path):
    rows = []
    oc.serve("BN-1", "q", Browser({"title": "K", "text": ARTICLE, "url": "https://k.example/a", "html": "<p></p>"}),
             lambda *a, **k: {"added": 1, "main_unknown": True}, rows.append, pages_dir=tmp_path)
    assert "MAIN_UNKNOWN" in [r["event"] for r in rows]


def test_serve_without_html_passes_no_main_text(tmp_path):
    got = []
    oc.serve("BN-1", "q", Browser({"title": "K", "text": ARTICLE, "url": "https://k.example/a"}),
             lambda s, t, url="", origin="", extra=None: got.append(extra) or {"added": 1}, lambda r: None,
             pages_dir=tmp_path)
    assert "main_text" not in got[0]


# ── 3b: the reader's order ──────────────────────────────────────────────────
def test_an_unlabelled_record_is_unknown_never_guessed():
    assert kn.region_of({"id": "a"}) == "unknown"
    assert kn.region_of({"id": "a"}, {"a": "furniture"}) == "furniture"
    assert kn.region_of({"id": "a", "region": "main"}, {"a": "furniture"}) == "main"


def _store(p, rows):
    p["store"].write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


ROWS = [{"id": "x1", "sentence": "floods in Kerala relief camps", "need_id": None},
        {"id": "f1", "sentence": "Home", "need_id": "BN-1", "region": "furniture"},
        {"id": "m1", "sentence": "Kerala floods relief", "need_id": "BN-1", "region": "main"},
        {"id": "u1", "sentence": "Contact", "need_id": "BN-1"}]


def test_read_shows_the_needs_own_first_main_before_furniture(p):
    _store(p, ROWS)
    items = kn.read("Kerala floods relief camps", k=10, store=p["store"], vec_path=p["store"].parent / "v.npy",
                    ids_path=p["store"].parent / "ids.json", labels_path=p["store"].parent / "l.json",
                    atoms_root=p["store"].parent / "atoms", with_vectors=False, field_index={}, need_id="BN-1",
                    regions={})
    assert [i["id"] for i in items if i["type"] == "statement"] == ["m1", "u1", "f1", "x1"]


def test_mutation_without_need_id_relevance_alone_orders(p):
    _store(p, ROWS)
    items = kn.read("Kerala floods relief camps", k=10, store=p["store"], vec_path=p["store"].parent / "v.npy",
                    ids_path=p["store"].parent / "ids.json", labels_path=p["store"].parent / "l.json",
                    atoms_root=p["store"].parent / "atoms", with_vectors=False, field_index={}, regions={})
    assert [i["id"] for i in items if i["type"] == "statement"][0] == "x1"


def test_linked_statements_put_main_before_furniture(p, tmp_path):
    from core import brain_needs as bn
    _store(p, ROWS)
    idx = tmp_path / "regions.json"
    idx.write_text(json.dumps({"regions": {"u1": "main"}}), encoding="utf-8")
    got = bn.linked_statements(p["store"], regions_path=idx)["BN-1"]
    assert [(g["id"], g["region"]) for g in got] == [("m1", "main"), ("u1", "main"), ("f1", "furniture")]


def test_mutation_without_the_sort_furniture_leads(p, tmp_path, monkeypatch):
    from core import brain_needs as bn
    _store(p, ROWS)
    monkeypatch.setattr(kn, "REGION_ORDER", {})
    got = bn.linked_statements(p["store"], regions_path=tmp_path / "none.json")["BN-1"]
    assert got[0]["id"] == "f1"


# ── 3c: old pages re-opened and labelled into the index ─────────────────────
class Reader:
    def __init__(self, pages):
        self.pages, self.opened = pages, []

    def read(self, url):
        self.opened.append(url)
        p = self.pages.get(url)
        return {"page": p, "raw": {}} if p else {"page": {}, "raw": None}


def test_relabel_reopens_only_the_needs_pages_and_writes_the_index(p, tmp_path):
    _store(p, [{"id": "a", "sentence": "Home", "need_id": "BN-1", "url": "https://k.example/a"},
               {"id": "b", "sentence": "The state government opened 300 relief camps across six districts.",
                "need_id": "BN-1", "url": "https://k.example/a"},
               {"id": "c", "sentence": "A sentence the page no longer carries.", "need_id": "BN-1",
                "url": "https://k.example/a"},
               {"id": "d", "sentence": "From a PDF.", "need_id": "BN-1", "url": "https://k.example/r.pdf",
                "origin": "openclaw-pdf"},
               {"id": "e", "sentence": "Gone.", "need_id": "BN-1", "url": "https://gone.example/"},
               {"id": "z", "sentence": "Home", "need_id": "BN-9", "url": "https://other.example/"}])
    br = Reader({"https://k.example/a": {"text": "Home\nAbout us\n" + ARTICLE, "html": HTML}})
    out = tmp_path / "regions.json"
    r = oc.relabel_pages(["BN-1"], br, store=p["store"], out=out)
    assert br.opened == ["https://k.example/a", "https://gone.example/"]
    idx = json.loads(out.read_text(encoding="utf-8"))["regions"]
    assert idx == {"a": "furniture", "b": "main"}
    assert r["counts"] == {"main": 1, "furniture": 1, "unknown": 3}
    assert r["pages"]["https://k.example/r.pdf"]["why"] == "a PDF: no HTML"
    assert r["pages"]["https://gone.example/"]["why"] == "the page did not open"


def test_mutation_without_the_still_on_the_page_check_a_vanished_sentence_is_furniture(p, tmp_path, monkeypatch):
    _store(p, [{"id": "c", "sentence": "A sentence the page no longer carries.", "need_id": "BN-1",
                "url": "https://k.example/a"}])
    monkeypatch.setattr(oc, "_on_page", lambda sentence, text: True)
    r = oc.relabel_pages(["BN-1"], Reader({"https://k.example/a": {"text": ARTICLE, "html": HTML}}),
                         store=p["store"], out=tmp_path / "regions.json")
    assert r["counts"]["furniture"] == 1
