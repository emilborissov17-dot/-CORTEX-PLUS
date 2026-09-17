#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_cockpit_trace_link.py — the per-step trace must be reachable.

The trace was recorded every night from 13 Sep 2026 and rendered into
claude/reports/TRACE_LATEST.html every morning from 17 Sep — and nothing linked
it. A page written on a schedule that no door opens is indistinguishable from a
page nobody writes, and it rots the same way: tools/trace_report.py itself sat
with no caller for four days because nothing depended on its output.

So the link is pinned here. Remove the route or move the link out of the CYCLE
tab and this file goes red naming it.

    venv\\Scripts\\python.exe -m pytest test/test_cockpit_trace_link.py -v
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import server as srv          # noqa: E402

ROUTE = "/trace_latest.html"
PAGE = REPO / "cockpit" / "templates" / "cockpit.html"


def test_the_route_is_registered_and_is_a_read():
    """A GET, and only a GET: this hands over a file and writes nothing."""
    rules = {str(r): r for r in srv.app.url_map.iter_rules()}
    assert ROUTE in rules, f"{ROUTE} is not registered at all"
    methods = rules[ROUTE].methods
    assert "GET" in methods
    assert "POST" not in methods, "a page that only reads must not accept POST"


def test_it_serves_the_page_when_it_is_on_disk(tmp_path, monkeypatch):
    d = tmp_path / "claude" / "reports"
    d.mkdir(parents=True)
    (d / "TRACE_LATEST.html").write_text("<h1>TRACE marker-9f3c</h1>",
                                         encoding="utf-8")
    monkeypatch.setattr(srv.ds, "BASE", tmp_path)
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().get(ROUTE)
    assert r.status_code == 200, r.data[:200]
    assert "marker-9f3c" in r.data.decode("utf-8"), (
        "the route did not serve the file it points at")
    assert "text/html" in r.headers.get("Content-Type", "")


def test_it_says_so_rather_than_serving_nothing_under_a_promising_name(
        tmp_path, monkeypatch):
    """THE FORBIDDEN FALLBACK is a blank 200, or an older TRACE_<date>.html
    served as "latest". Absent must read as absent, in words, with the path."""
    monkeypatch.setattr(srv.ds, "BASE", tmp_path)
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().get(ROUTE)
    assert r.status_code == 404, (
        f"a missing trace answered {r.status_code}, not 404")
    body = r.data.decode("utf-8")
    assert "TRACE_LATEST.html" in body, "the answer does not name the file"
    assert "trace_report.py" in body, "it does not say what would write it"


def test_the_cycle_tab_is_where_the_link_lives():
    """Not merely present somewhere in the page — present in tabCycle. A link
    in the wrong tab is a link nobody with a reason to want it will find."""
    page = PAGE.read_text(encoding="utf-8")
    needle = 'href="/trace_latest.html"'
    assert needle in page, "the cockpit links the trace from nowhere"

    i = page.index("async function tabCycle(")
    j = page.index("function sparkline(", i)
    assert needle in page[i:j], (
        "the trace link is in the page but not in the CYCLE tab, which is the "
        "one tab whose reader is asking what the steps did")


def test_the_panel_says_what_boundary_only_means():
    """The whole point of the rewritten report is that BOUNDARY ONLY is not 0.
    A link with no explanation hands the reader the same confusion one click
    later."""
    page = PAGE.read_text(encoding="utf-8")
    i = page.index("async function tabCycle(")
    j = page.index("function sparkline(", i)
    block = page[i:j]
    assert "BOUNDARY ONLY" in block, (
        "the panel does not explain the one column a reader will misread")
