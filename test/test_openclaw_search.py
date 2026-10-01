# -*- coding: utf-8 -*-
"""test/test_openclaw_search.py — OpenClaw is the searcher (C-TURN-1 Part 4g).
OpenClaw's browser is injected; pages and the ledger are under tmp_path."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from scripts import openclaw_search as oc  # noqa: E402

DDG = "https://duckduckgo.com/l/?uddg="


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


class FakeBrowser:
    def __init__(self, links, pages, search_page=None):
        self.links, self.pages = links, pages
        self.search_page = search_page or {"title": "results", "text": "results", "url": "https://html.duckduckgo.com/"}

    def search(self, query):
        return {"page": self.search_page, "links": [{"url": DDG + u, "title": u} for u in self.links], "raw": {}}

    def read(self, url):
        p = self.pages[url]
        return {"page": p, "raw": {"ok": True, "result": json.dumps(p)}} if p is not None else {"page": {}, "raw": None}


@pytest.fixture
def run(tmp_path):
    rows, ingested = [], []

    def ingest(source_id, text, url="", origin="", extra=None):
        ingested.append({"url": url, "text": text, "origin": origin, **(extra or {})})
        return {"added": len(text.split(". "))}

    def go(browser):
        return oc.serve("BN-1", "refugees returned to Syria 2026", browser, ingest, rows.append,
                        pages_dir=tmp_path / "pages")
    return {"go": go, "rows": rows, "ingested": ingested, "pages": tmp_path / "pages"}


def _ev(run):
    return [r["event"] for r in run["rows"]]


def test_a_need_with_pages_ends_gained_and_the_text_is_the_tools(run):
    b = FakeBrowser(["https://unhcr.example/r"], {"https://unhcr.example/r": {"title": "UNHCR", "text":
                    "UNHCR says 1.2 million refugees returned. Many lack housing.", "url": "https://unhcr.example/r"}})
    r = run["go"](b)
    assert r["pages"] == 1 and r["statements_added"] == 2 and _ev(run) == ["SEARCHED", "FETCHED", "GAINED"]
    assert run["ingested"][0]["text"].startswith("UNHCR says") and run["ingested"][0]["need_id"] == "BN-1"
    stored = json.loads(next(run["pages"].glob("*.json")).read_text(encoding="utf-8"))
    assert stored["need_id"] == "BN-1" and stored["url"] == "https://unhcr.example/r" and len(stored["sha256"]) == 64


def test_a_captcha_page_is_recorded_and_skipped(run):
    b = FakeBrowser(["https://blocked.example/x", "https://ok.example/y"], {
        "https://blocked.example/x": {"title": "Just a moment...", "text": "Verify you are human by completing the CAPTCHA"},
        "https://ok.example/y": {"title": "ok", "text": "A plain page."}})
    r = run["go"](b)
    assert r["captcha"] == 1 and r["hosts_captcha"] == ["blocked.example"] and r["pages"] == 1
    assert [x["url"] for x in run["ingested"]] == ["https://ok.example/y"], "a CAPTCHA page was ingested"


def test_a_captcha_on_the_search_page_stops_the_need_and_says_where(run):
    b = FakeBrowser([], {}, search_page={"title": "DuckDuckGo", "text": "Unfortunately, bots use DuckDuckGo too.",
                                         "url": "https://html.duckduckgo.com/html/"})
    r = run["go"](b)
    assert r["captcha"] == 1 and r["hosts_captcha"] == ["html.duckduckgo.com"] and _ev(run) == ["SEARCHED", "CAPTCHA"]


def test_no_pages_leaves_the_need_with_nothing_and_says_so(run):
    r = run["go"](FakeBrowser([], {}))
    assert r["pages"] == 0 and _ev(run) == ["SEARCHED", "NO_RESULTS"]


def test_a_page_with_no_tool_text_is_unbacked_and_ingests_nothing(run):
    b = FakeBrowser(["https://claimed.example/z"], {"https://claimed.example/z": None})
    r = run["go"](b)
    assert r["unbacked"] == 1 and run["ingested"] == [] and "UNBACKED" in _ev(run)


def test_mutation_text_taken_from_anywhere_but_the_tool_result_would_ingest_it(run, monkeypatch):
    class Prose(FakeBrowser):
        def read(self, url):                      # a model's prose: a page dict, but no tool result behind it
            return {"page": {"text": "The model says the page says 5 million returned."}, "raw": None}
    run["go"](Prose(["https://claimed.example/z"], {}))
    assert run["ingested"] == [], "prose with no tool result was ingested"
    real = oc.serve

    def lenient(*a, **k):                          # the mutation: accept page text whatever the raw result
        b = a[2]
        orig = b.read
        b.read = lambda url: {**orig(url), "raw": {"ok": True}}
        return real(*a, **k)
    monkeypatch.setattr(oc, "serve", lenient)
    oc.serve("BN-1", "q", Prose(["https://claimed.example/z"], {}), lambda *a, **k: (run["ingested"].append(1) or {"added": 1}),
             run["rows"].append, pages_dir=run["pages"])
    assert run["ingested"], "without the tool-result rule the prose would have entered the store"


def test_a_pdf_link_is_recorded_for_the_pdf_reader_not_read_as_text(run):
    b = FakeBrowser(["https://unhcr.example/report.pdf"], {})
    r = run["go"](b)
    assert r["pdfs"] == ["https://unhcr.example/report.pdf"] and "PDF_NEED" in _ev(run)


def test_the_duckduckgo_redirect_is_unwrapped():
    assert oc.unwrap(DDG + "https%3A%2F%2Fwww.unhcr.org%2Fx&rut=abc") == "https://www.unhcr.org/x"


def test_the_searcher_imports_no_requests():
    assert "requests" not in oc.imported_modules()


def test_mutation_a_searcher_that_imports_requests_is_seen(tmp_path):
    f = tmp_path / "s.py"
    f.write_text("import requests\n", encoding="utf-8")
    assert "requests" in oc.imported_modules(f)


def test_a_browser_that_went_away_is_started_again_once(monkeypatch):
    calls = []

    def fake_call(self, *args):
        calls.append(args[0])
        if args[0] == "navigate":
            raise oc.OpenClawFailed('Browser profile "openclaw" is not running')
        return {"tabId": "t9"} if args[0] == "open" else {"ok": True}
    monkeypatch.setattr(oc.OpenClawBrowser, "_call", fake_call)
    b = oc.OpenClawBrowser()
    b.tab = "t1"
    b._goto("https://x.example/")
    assert calls[:3] == ["navigate", "start", "open"] and b.tab == "t9"


def test_mutation_a_driver_that_kept_the_dead_tab_fails_every_call(monkeypatch):
    def dead(self, *args):
        raise oc.OpenClawFailed('Browser profile "openclaw" is not running')
    monkeypatch.setattr(oc.OpenClawBrowser, "_call", dead)
    b = oc.OpenClawBrowser()
    b.tab = "t1"
    with pytest.raises(oc.OpenClawFailed):
        b._goto("https://x.example/")


def test_a_searcher_failure_is_an_error_not_no_results(run):
    class Broken(FakeBrowser):
        def search(self, query):
            raise oc.OpenClawFailed("gateway closed")
    r = run["go"](Broken([], {}))
    assert r["errors"] and _ev(run) == ["SEARCHED", "SEARCHER_ERROR"]
