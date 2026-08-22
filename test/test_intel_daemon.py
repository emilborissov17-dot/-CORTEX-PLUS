#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_intel_daemon.py — THE COLD SHELL FETCHES, AND DOES NOTHING ELSE.

Every test here runs with a STUBBED getter. A test suite that reaches the real
internet is a test suite that fails when a feed is down, and then gets marked
flaky and ignored.

What is held:

  * ZERO LLM. Not by promise but by construction — the daemon does not import
    the LLM chain at all, which is why it reads its source table out of
    internet_agent.py with ast.literal_eval instead of importing it. Both halves
    are asserted: no import at runtime, and no model call anywhere in the source.
  * THE LINK IS REQUIRED. A row without a url is refused at write time, and the
    sqlite schema refuses it too, so a future writer that forgets cannot get past
    the database.
  * APPEND-ONLY IS THE DATABASE'S RULE. UPDATE and DELETE abort.
  * THE CAPS ARE NOT CONFIGURABLE. 1MB and 15s, enforced while streaming, with
    no env var and no config file that can widen them.

    venv\\Scripts\\python.exe -m pytest test/test_intel_daemon.py -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import intel_daemon as d  # noqa: E402


RSS = (b"<rss><channel>"
       b"<item><title>Sea ice minimum</title><description>&lt;p&gt;text&lt;/p&gt;</description>"
       b"<link>https://example.org/ice</link></item>"
       b"<item><title>Second</title><description>d2</description>"
       b"<link>https://example.org/two</link></item>"
       b"</channel></rss>")

ARXIV = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
         b"<title>A paper</title><summary>abstract</summary>"
         b'<link rel="alternate" href="https://arxiv.org/abs/1234"/>'
         b"</entry></feed>")

GDELT = json.dumps({"articles": [
    {"title": "An article", "url": "https://news.example/1", "domain": "news.example"},
]}).encode()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "intel.db"


@pytest.fixture
def table():
    return {"RSS_FEEDS": {"AX": "https://feed/rss"},
            "ARXIV_CATEGORIES": {"AX": "physics.ao-ph"}}


# ---------------------------------------------------------------------------
# No model in this process
# ---------------------------------------------------------------------------

def test_the_daemon_does_not_import_the_llm_chain():
    """core.groq_backend must not be pulled in by importing the daemon.

    agents/internet/internet_agent.py imports it at module scope, which is the
    whole reason the source table is read by AST instead of by import.
    """
    import subprocess
    code = ("import sys; import scripts.intel_daemon; "
            "bad=[m for m in sys.modules if 'groq' in m or 'llm' in m]; "
            "print(bad)")
    out = subprocess.run([str(REPO / "venv" / "Scripts" / "python.exe"), "-c", code],
                         cwd=str(REPO), capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]", (
        f"importing the daemon pulled in {out.stdout.strip()}. The promise 'zero "
        f"LLM calls' has to be a property of the process, not a claim about "
        f"runtime behaviour")


def test_no_model_call_appears_anywhere_in_the_daemon_source():
    src = (REPO / "scripts" / "intel_daemon.py").read_text(encoding="utf-8")
    for forbidden in ("call_groq", "call_groq_meta", "brain.think",
                      "/api/chat", "/api/generate"):
        assert forbidden not in src, (
            f"{forbidden!r} appears in the cold shell. It fetches; it does not think")


def test_the_source_table_is_read_without_importing():
    tbl = d.source_table()
    assert tbl["RSS_FEEDS"], "no RSS feeds found"
    assert tbl["ARXIV_CATEGORIES"], "no arXiv categories found"


def test_a_moved_source_table_fails_loudly(tmp_path):
    """Silently finding no sources looks exactly like every source going quiet."""
    fake = tmp_path / "agent.py"
    fake.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not define"):
        d._literal_assignments(fake, ("RSS_FEEDS",))


def test_a_source_table_that_stopped_being_a_literal_fails_loudly(tmp_path):
    fake = tmp_path / "agent.py"
    fake.write_text("RSS_FEEDS = dict(a=compute())\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no longer a literal"):
        d._literal_assignments(fake, ("RSS_FEEDS",))


def test_a_byte_order_mark_does_not_break_the_read(tmp_path):
    """internet_agent.py begins with a BOM; ast.parse rejects U+FEFF on line 1."""
    fake = tmp_path / "agent.py"
    fake.write_bytes(b"\xef\xbb\xbfRSS_FEEDS = {'A': 'u'}\n")
    assert d._literal_assignments(fake, ("RSS_FEEDS",))["RSS_FEEDS"] == {"A": "u"}


# ---------------------------------------------------------------------------
# The link is not optional
# ---------------------------------------------------------------------------

def test_a_row_without_a_url_is_refused(db):
    conn = d.connect(db)
    try:
        with pytest.raises(d.LinkRequired):
            d.write_row(conn, "RSS", "", title="a finding nobody can check")
    finally:
        conn.close()


def test_a_whitespace_url_is_refused(db):
    conn = d.connect(db)
    try:
        with pytest.raises(d.LinkRequired):
            d.write_row(conn, "RSS", "   ", title="still no link")
    finally:
        conn.close()


def test_the_schema_refuses_a_linkless_row_even_by_raw_sql(db):
    """The python guard can be bypassed; the database's cannot."""
    conn = d.connect(db)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO intel (ts, source, url) VALUES ('t','s','')")
            conn.commit()
    finally:
        conn.close()


def test_refused_rows_are_counted_not_hidden(db, table):
    linkless = (b"<rss><channel><item><title>T</title><description>d</description>"
                b"</item></channel></rss>")
    rep = d.run_once(axes=["AX"], db_path=db, getter=lambda u: linkless,
                     table={"RSS_FEEDS": {"AX": "https://f"}, "ARXIV_CATEGORIES": {}})
    assert rep["written"] == 0
    assert rep["refused_no_url"] >= 1, (
        "a linkless item vanished without a trace; the count is how anyone learns "
        "an endpoint has stopped giving links")


# ---------------------------------------------------------------------------
# Append-only
# ---------------------------------------------------------------------------

def test_update_is_refused_by_the_database(db):
    conn = d.connect(db)
    try:
        d.write_row(conn, "RSS", "https://a", "t")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("UPDATE intel SET title='rewritten'")
    finally:
        conn.close()


def test_delete_is_refused_by_the_database(db):
    conn = d.connect(db)
    try:
        d.write_row(conn, "RSS", "https://a", "t")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute("DELETE FROM intel")
    finally:
        conn.close()


def test_the_same_url_at_the_same_instant_is_a_duplicate_not_an_error(db):
    conn = d.connect(db)
    try:
        assert d.write_row(conn, "RSS", "https://a", "t", ts="2026-08-22T00:00:00Z")
        assert not d.write_row(conn, "RSS", "https://a", "t", ts="2026-08-22T00:00:00Z")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The caps
# ---------------------------------------------------------------------------

def test_the_caps_are_module_constants_with_no_override():
    src = (REPO / "scripts" / "intel_daemon.py").read_text(encoding="utf-8")
    assert d.MAX_CONTENT_BYTES == 1024 * 1024
    assert d.STREAM_TIMEOUT_SEC == 15
    for pattern in ("environ.get(\"CORTEX_MAX_CONTENT",
                    "environ.get('CORTEX_MAX_CONTENT",
                    "MAX_CONTENT_BYTES =  int(os.environ"):
        assert pattern not in src
    assert "os.environ" not in src, (
        "the cold shell reads an environment variable. A cap that something else "
        "can widen is a cap that will one day be widened")


def test_an_oversized_response_is_discarded_not_truncated():
    class _Big:
        def __init__(self):
            self.sent = 0

        def read(self, n):
            self.sent += n
            return b"x" * n if self.sent <= d.MAX_CONTENT_BYTES * 3 else b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert d.http_get("https://big", opener=lambda req, timeout: _Big()) is None, (
        "half a JSON document parses as nothing and half an article is a misquote")


def test_a_response_under_the_cap_is_returned_whole():
    body = b"y" * 1000

    class _Small:
        def __init__(self):
            self.done = False

        def read(self, n):
            if self.done:
                return b""
            self.done = True
            return body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    assert d.http_get("https://small", opener=lambda req, timeout: _Small()) == body


def test_a_failing_request_returns_none_and_does_not_raise():
    def _boom(req, timeout):
        raise OSError("network down")

    assert d.http_get("https://x", opener=_boom) is None


def test_the_stream_timeout_is_passed_to_the_opener():
    seen = {}

    class _R:
        def read(self, n):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _opener(req, timeout):
        seen["timeout"] = timeout
        return _R()

    d.http_get("https://x", opener=_opener)
    assert seen["timeout"] == d.STREAM_TIMEOUT_SEC


# ---------------------------------------------------------------------------
# Parsing and the pass
# ---------------------------------------------------------------------------

def test_rss_arxiv_and_gdelt_parse_to_the_same_shape():
    for raw, parse in ((RSS, d.parse_rss), (ARXIV, d.parse_arxiv), (GDELT, d.parse_gdelt)):
        items = parse(raw)
        assert items, f"{parse.__name__} parsed nothing"
        for it in items:
            assert set(("title", "raw_text", "url", "source")) <= set(it)
            assert it["url"]


def test_malformed_xml_yields_nothing_rather_than_raising():
    assert d.parse_rss(b"<rss><broken") == []
    assert d.parse_arxiv(b"not xml at all") == []
    assert d.parse_gdelt(b"{not json") == []


def test_a_full_pass_writes_rows_and_reports_what_it_did(db, table):
    def _get(url):
        if "rss" in url:
            return RSS
        if "arxiv" in url:
            return ARXIV
        return GDELT

    rep = d.run_once(axes=["AX"], db_path=db, getter=_get, table=table)
    assert rep["written"] == 4, rep      # 2 rss + 1 arxiv + 1 gdelt
    assert rep["per_axis"]["AX"] == 4
    assert rep["fetch_failures"] == 0


def test_a_dead_endpoint_is_counted_and_does_not_stop_the_pass(db, table):
    def _get(url):
        return None if "rss" in url else GDELT

    rep = d.run_once(axes=["AX"], db_path=db, getter=_get, table=table)
    assert rep["fetch_failures"] >= 1
    assert rep["written"] >= 1, "one dead feed stopped the whole pass"


# ---------------------------------------------------------------------------
# The reader the cycle will use
# ---------------------------------------------------------------------------

def test_fresh_since_returns_only_rows_at_or_after_the_timestamp(db):
    conn = d.connect(db)
    try:
        d.write_row(conn, "s", "https://old", ts="2026-08-01T00:00:00+00:00")
        d.write_row(conn, "s", "https://new", ts="2026-08-20T00:00:00+00:00")
        rows = d.fresh_since(conn, "2026-08-10T00:00:00+00:00")
        assert [r["url"] for r in rows] == ["https://new"]
    finally:
        conn.close()


def test_fresh_since_can_filter_by_axis(db):
    conn = d.connect(db)
    try:
        d.write_row(conn, "s", "https://a", axis_hint="AX1", ts="2026-08-20T00:00:00+00:00")
        d.write_row(conn, "s", "https://b", axis_hint="AX2", ts="2026-08-20T00:00:00+00:00")
        rows = d.fresh_since(conn, "2026-01-01", axis_hint="AX2")
        assert [r["url"] for r in rows] == ["https://b"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------

def test_the_selftest_says_NOT_WIRED(capsys):
    d._selftest()
    out = capsys.readouterr().out
    assert "NOT WIRED" in out, (
        "the daemon claims to be wired. Nothing reads intel.db yet — that is "
        "item 7's plan, not today's work")


def test_schtasks_only_prints_and_never_registers():
    lines = d.schtasks_lines()
    assert "schtasks /Create" in lines
    src = (REPO / "scripts" / "intel_daemon.py").read_text(encoding="utf-8")
    assert "subprocess.run([\"schtasks\", \"/Create\"" not in src
    assert "/Create" not in src.split("def schtasks_lines")[0], (
        "something outside the printer touches schtasks /Create")
