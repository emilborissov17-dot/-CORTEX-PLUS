# -*- coding: utf-8 -*-
"""
Retrieval tests, R48. Never a live search and never the key.

The suite moved from a whitelist to a hygiene blacklist and from two date states to
three. What did NOT move: an undated snippet is still not treated as fresh, and a dated
snippet outside the window is still dropped.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.market_news import (NewsUnavailable, _parse_dt,  # noqa: E402
                              block_reason, fetch_news, filter_results,
                              host_allowed, host_class, host_of)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _r(url="https://www.reuters.com/markets/x", hours_ago=2,
       content="CPI rose 0.3% in August", title="t", dated=True):
    d = {"url": url, "title": title, "content": content}
    if dated:
        d["published_date"] = (NOW - timedelta(hours=hours_ago)).isoformat()
    return d


def _code_of(path: Path) -> str:
    """Executable code only, with every string constant blanked.

    Three tests in this repo have now failed against their own prose - twice on a
    docstring naming the thing it forbids, once on a refusal message. A capability
    needs an identifier; it cannot live in a sentence.
    """
    class _Blank(ast.NodeTransformer):
        def visit_Constant(self, node):
            return ast.copy_location(
                ast.Constant(value="" if isinstance(node.value, str) else node.value),
                node)

    return ast.unparse(_Blank().visit(
        ast.parse(path.read_text(encoding="utf-8")))).lower()


# ── the blacklist ───────────────────────────────────────────────────────────
def test_a_non_blacklisted_host_passes():
    """THE INVERSION. Everything not blacklisted is allowed — including hosts the old
    whitelist would have refused."""
    for url in ("https://www.marketwatch.com/a", "https://www.investing.com/b",
                "https://finance.yahoo.com/c", "https://simplywall.st/d",
                "https://www.some-outlet-nobody-listed.com/e"):
        assert host_allowed(url) is True, url
        assert block_reason(url) is None


def test_a_blacklisted_host_is_dropped_and_the_reason_names_why():
    kept, ctx, dropped = filter_results([_r(url="https://www.reddit.com/r/stocks/x")],
                                        now=NOW)
    assert kept == [] and ctx == []
    assert dropped[0]["host"] == "reddit.com"
    assert "blacklisted host" in dropped[0]["why"]
    assert "instructions aimed at the model" in dropped[0]["why"]


def test_a_subdomain_of_a_blacklisted_host_is_also_blocked():
    assert host_allowed("https://news.reddit.com/x") is False
    assert "subdomain of blacklisted reddit.com" in block_reason(
        "https://news.reddit.com/x")


def test_open_publishing_suffixes_are_blocked():
    for url in ("https://someone.blogspot.com/p", "https://x.substack.com/p",
                "https://y.wordpress.com/p"):
        assert host_allowed(url) is False, url
        assert "open publishing platform" in block_reason(url)


def test_a_lookalike_host_is_not_blocked_by_accident():
    """`notreddit.com` is not reddit. Matching a suffix without the dot would eat it."""
    assert host_allowed("https://notreddit.com/x") is True
    assert host_of("https://WWW.Reuters.COM/a") == "reuters.com"


# ── the three date states ───────────────────────────────────────────────────
def test_dated_and_in_window_is_CITABLE():
    citable, ctx, dropped = filter_results([_r(hours_ago=47)], now=NOW)
    assert len(citable) == 1 and ctx == [] and dropped == []
    assert citable[0].dated is True and citable[0].published_utc


def test_dated_and_out_of_window_is_DROPPED():
    citable, ctx, dropped = filter_results([_r(hours_ago=49)], now=NOW)
    assert citable == [] and ctx == []
    assert "older than 48h" in dropped[0]["why"]


def test_a_date_FIELD_that_is_present_but_OLD_is_still_dropped():
    """The VALUE is checked, never merely the presence. Tavily's `days` is best-effort:
    asking for 2 days returned articles 101–112 hours old on 2026-09-07, and a filter
    that trusted the request would have admitted all of them."""
    r = _r(dated=False)
    r["published_date"] = "Wed, 02 Sep 2026 19:29:11 GMT"
    citable, ctx, dropped = filter_results([r], now=NOW)
    assert citable == [] and ctx == []
    assert "older than 48h" in dropped[0]["why"]


def test_UNDATED_is_DOWNGRADED_not_dropped():
    """THE CHANGE. Absence of a date is not evidence of staleness — but it is not
    evidence of freshness either, so it becomes context-only rather than citable."""
    citable, ctx, dropped = filter_results([_r(dated=False)], now=NOW)
    assert citable == [] and dropped == []
    assert len(ctx) == 1
    assert ctx[0].dated is False and ctx[0].published_utc == ""


def test_an_unparseable_date_is_treated_as_undated_not_as_fresh():
    r = _r(dated=False)
    r["published_date"] = "last Tuesday"
    citable, ctx, dropped = filter_results([r], now=NOW)
    assert citable == [] and len(ctx) == 1 and dropped == []


def test_an_empty_snippet_is_dropped_whatever_its_date():
    citable, ctx, dropped = filter_results([_r(content="   ")], now=NOW)
    assert citable == [] and ctx == [] and dropped[0]["why"] == "empty snippet"


def test_the_date_formats_tavily_actually_sends_all_parse():
    for raw in ("Fri, 04 Sep 2026 12:35:01 GMT", "Sun, 06 Sep 2026 10:00:00 UTC",
                "2026-09-05T12:30:00Z", "2026-09-05T12:30:00+00:00", "2026-09-05"):
        dt = _parse_dt(raw)
        assert dt is not None and dt.tzinfo is not None, raw
    assert _parse_dt("last Tuesday") is None
    assert _parse_dt("") is None


# ── the citable / context precedence ────────────────────────────────────────
def test_citable_wins_and_the_bet_is_not_flagged():
    got, ungrounded = fetch_news("SPY", now=NOW,
                                 searcher=lambda q: [_r(), _r(dated=False)])
    assert ungrounded is False
    assert [s.dated for s in got] == [True]


def test_context_only_is_used_ONLY_when_nothing_citable_exists_and_is_FLAGGED():
    got, ungrounded = fetch_news("SPY", now=NOW, searcher=lambda q: [_r(dated=False)])
    assert ungrounded is True
    assert [s.dated for s in got] == [False]


def test_with_nothing_at_all_it_still_refuses_loud():
    raw = [_r(url="https://www.reddit.com/a"), _r(hours_ago=99)]
    with pytest.raises(NewsUnavailable) as e:
        fetch_news("SPY", now=NOW, searcher=lambda q: raw)
    m = str(e.value)
    assert "2 result(s)" in m and "2 dropped" in m and "no fallback" in m


# ── the class is metadata, never a gate ─────────────────────────────────────
def test_the_class_travels_with_the_snippet_and_never_filters():
    citable, _, _ = filter_results([_r(url="https://www.reuters.com/a"),
                                    _r(url="https://www.fool.com/b"),
                                    _r(url="https://www.forex.com/c"),
                                    _r(url="https://nobody-has-heard-of-this.io/d")],
                                   now=NOW)
    assert len(citable) == 4, "class must not remove anything"
    by_host = {s.host: s.source_class for s in citable}
    assert by_host["reuters.com"] == "independent"
    assert by_host["fool.com"] == "adversarial"
    assert by_host["forex.com"] == "self_reported"
    assert by_host["nobody-has-heard-of-this.io"] == "unknown"


def test_an_unknown_host_is_class_unknown_and_is_allowed():
    assert host_class("https://brand-new-outlet.example/x")["class"] == "unknown"
    assert host_allowed("https://brand-new-outlet.example/x") is True


def test_the_classes_are_the_four_already_declared():
    bl = json.loads((REPO / "config" / "news_blacklist.json").read_text(encoding="utf-8"))
    ri = json.loads((REPO / "config" / "reporter_independence.json")
                    .read_text(encoding="utf-8"))
    used = {h["class"] for h in bl["host_classes"].values()}
    assert used <= set(ri["_classes"]), f"a fifth class was invented: {used}"
    assert bl["max_age_hours"] == 48


# ── key, transport, and the absence of a quiet fallback ─────────────────────
def test_a_missing_key_raises_and_names_the_key(monkeypatch):
    import core.market_news as mn
    monkeypatch.setattr("core.source_status.credential_for", lambda k: None)
    with pytest.raises(NewsUnavailable) as e:
        mn.fetch_news("SPY")
    msg = str(e.value)
    assert "TAVILY_API_KEY" in msg and "REFUSED by name" in msg and "browser" in msg


def test_any_exception_becomes_a_named_refusal():
    def searcher(_q):
        raise TimeoutError("read timed out")
    with pytest.raises(NewsUnavailable) as e:
        fetch_news("SPY", searcher=searcher)
    assert "TimeoutError" in str(e.value) and "REFUSED" in str(e.value)


def test_the_search_asks_for_NEWS_because_basic_returns_no_dates(monkeypatch):
    """MEASURED: search_depth='basic' returned 0 of 6 with a published_date;
    topic='news' returned 6 of 6."""
    import core.market_news as mn
    sent = {}

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"results": []}

    import requests
    monkeypatch.setattr(
        requests, "post",
        lambda url, timeout=None, json=None: (sent.update(json or {}), R())[1])
    with pytest.raises(NewsUnavailable):
        mn.fetch_news("SPY")
    assert sent.get("topic") == "news" and sent.get("days") == 2
    assert "search_depth" not in sent


def test_no_hidden_fallback_in_the_executable_code():
    code = _code_of(REPO / "core" / "market_news.py")
    for forbidden in ("cache", "synthes", "widen", "selenium", "playwright",
                      "webdriver", "captcha"):
        assert forbidden not in code, forbidden


def test_prediction_only_no_order_path():
    """Checked on IDENTIFIERS. 'broker' now appears in prose — a broker's commentary is
    self_reported — and a text grep would fail on the explanation rather than on code."""
    # NOT "api_key": that is Tavily's own request field, a SEARCH parameter. Listing
    # it here failed on the retrieval code and would have pushed me to rename a
    # third-party field to satisfy a test - the test bending the code instead of
    # checking it. What must be absent is an ORDER PATH.
    for f in ("core/market_news.py", "tools/market_bet.py"):
        code = _code_of(REPO / f)
        for word in ("place_order", "submit_order", "create_order", "alpaca",
                     "ib_insync", "portfolio", "position_size"):
            assert word not in code, f"{word} in {f}"
