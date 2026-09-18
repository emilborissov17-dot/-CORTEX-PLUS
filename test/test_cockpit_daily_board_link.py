#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_cockpit_daily_board_link.py — the daily board must be reachable.

Same reason as test/test_cockpit_trace_link.py, and the same failure it was
written after: tools/trace_report.py wrote a page every morning for four days
that nothing linked, and a page on a schedule that no door opens is
indistinguishable from a page nobody writes.

The daily board exists because of Emil's rule of 17 Sep 2026 — an experiment
that does not show a number every day is built wrong. A board written into
claude/reports/ and linked from nowhere would break that rule while looking like
it keeps it.

So the route, the link and the 404 wording are pinned here.

    venv\\Scripts\\python.exe -m pytest test/test_cockpit_daily_board_link.py -v
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import server as srv          # noqa: E402

ROUTE = "/daily_board.md"
PAGE = REPO / "cockpit" / "templates" / "cockpit.html"
BAT = REPO / "tools" / "prophecy_morning.bat"


def test_the_route_is_registered_and_is_a_read():
    """A GET, and only a GET: this hands over a file and writes nothing."""
    rules = {str(r): r for r in srv.app.url_map.iter_rules()}
    assert ROUTE in rules, f"{ROUTE} is not registered at all"
    methods = rules[ROUTE].methods
    assert "GET" in methods
    assert "POST" not in methods, "a page that only reads must not accept POST"


def test_it_serves_the_board_when_it_is_on_disk(tmp_path, monkeypatch):
    d = tmp_path / "claude" / "reports"
    d.mkdir(parents=True)
    (d / "DAILY_BOARD.md").write_text("# DAILY BOARD marker-4b71\n", encoding="utf-8")
    monkeypatch.setattr(srv.ds, "BASE", tmp_path)
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().get(ROUTE)
    assert r.status_code == 200, r.data[:200]
    assert "marker-4b71" in r.data.decode("utf-8"), (
        "the route did not serve the file it points at")
    ctype = r.headers.get("Content-Type", "")
    assert "text/plain" in ctype, (
        f"served as {ctype!r}; text/markdown makes the browser download it instead "
        f"of showing it, and a board nobody opens is a board that is not kept")


def test_it_says_so_rather_than_serving_nothing_under_a_promising_name(
        tmp_path, monkeypatch):
    """THE FORBIDDEN FALLBACK is a blank 200, or yesterday's dated board served
    as today's. Absent must read as absent, in words, with the path."""
    monkeypatch.setattr(srv.ds, "BASE", tmp_path)
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().get(ROUTE)
    assert r.status_code == 404, f"a missing board answered {r.status_code}, not 404"
    body = r.data.decode("utf-8")
    assert "DAILY_BOARD.md" in body, "the answer does not name the file"
    assert "daily_board.py" in body, "it does not say what would write it"


def test_the_route_never_falls_back_to_a_dated_board(tmp_path, monkeypatch):
    """An archived board beside an absent DAILY_BOARD.md must still be a 404.

    Serving claude/reports/daily_board/<older>.md under a name that promises
    today is precisely the stale-number failure the board itself refuses to
    commit row by row.
    """
    d = tmp_path / "claude" / "reports" / "daily_board"
    d.mkdir(parents=True)
    (d / "2026-09-17.md").write_text("# DAILY BOARD marker-stale\n", encoding="utf-8")
    monkeypatch.setattr(srv.ds, "BASE", tmp_path)
    srv.app.config["TESTING"] = True
    r = srv.app.test_client().get(ROUTE)
    assert r.status_code == 404
    assert "marker-stale" not in r.data.decode("utf-8")


def test_the_cycle_tab_links_it_beside_the_trace():
    """Beside TRACE_LATEST, in tabCycle — the one tab whose reader is asking
    what the night did."""
    page = PAGE.read_text(encoding="utf-8")
    needle = 'href="/daily_board.md"'
    assert needle in page, "the cockpit links the daily board from nowhere"

    i = page.index("async function tabCycle(")
    j = page.index("function sparkline(", i)
    block = page[i:j]
    assert needle in block, (
        "the daily board link is in the page but not in the CYCLE tab, beside "
        "the trace link it belongs with")
    assert 'href="/trace_latest.html"' in block


def test_the_morning_writes_it_after_the_scoreboard():
    """The board reads what agi_scoreboard and the two --score steps wrote. A
    board generated before them shows last night's predictions as still open,
    which is a true statement about a board built at the wrong time and a false
    one about the experiment."""
    bat = BAT.read_text(encoding="utf-8", errors="replace")
    assert "daily_board.py --write" in bat, (
        "tools/prophecy_morning.bat does not run the board at all")
    assert bat.index("agi_scoreboard.py") < bat.index("daily_board.py"), (
        "the daily board step runs before agi_scoreboard")
    for earlier in ("self_forecast.py --score", "world_forecast.py --score"):
        assert bat.index(earlier) < bat.index("daily_board.py"), (
            f"the daily board step runs before {earlier}")
