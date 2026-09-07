# -*- coding: utf-8 -*-
"""
Tests 1–7 of claude/SPEC_7SEP_R43_GROUNDED_BET.md §4.

Never a live search and never the key: `fetch_news` takes an injectable `searcher`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.market_news import (NewsUnavailable, Snippet, fetch_news,  # noqa: E402
                              filter_results, host_allowed, host_of)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _r(url="https://www.reuters.com/markets/x", hours_ago=2, content="CPI rose 0.3% in August",
       title="t", dated=True):
    d = {"url": url, "title": title, "content": content}
    if dated:
        d["published_date"] = (NOW - timedelta(hours=hours_ago)).isoformat()
    return d


# ── 1. off-whitelist host is dropped, and the drop names the host ───────────
def test_an_off_whitelist_host_is_dropped_and_logged():
    kept, dropped = filter_results([_r(url="https://randomblog.example/post")], now=NOW)
    assert kept == []
    assert len(dropped) == 1
    assert dropped[0]["host"] == "randomblog.example"
    assert "whitelist" in dropped[0]["why"]


def test_a_lookalike_host_does_not_pass_as_the_real_one():
    """`evil-reuters.com` must not match `reuters.com`. endswith() would let it."""
    assert host_allowed("https://reuters.com/x") is True
    assert host_allowed("https://www.reuters.com/x") is True
    assert host_allowed("https://feeds.reuters.com/x") is True
    assert host_allowed("https://evil-reuters.com/x") is False
    assert host_allowed("https://reuters.com.evil.io/x") is False
    assert host_of("https://WWW.Reuters.COM/a") == "reuters.com"


# ── 2. too old is dropped ───────────────────────────────────────────────────
def test_a_snippet_older_than_48_hours_is_dropped():
    kept, dropped = filter_results([_r(hours_ago=49)], now=NOW)
    assert kept == [] and "older than 48h" in dropped[0]["why"]


def test_a_snippet_inside_the_window_is_kept():
    kept, _ = filter_results([_r(hours_ago=47)], now=NOW)
    assert len(kept) == 1 and isinstance(kept[0], Snippet)
    assert kept[0].host == "reuters.com"


# ── 3. no date is dropped, NOT treated as fresh ─────────────────────────────
def test_a_snippet_with_no_published_date_is_dropped():
    """UNKNOWN AGE IS NOT RECENT AGE. Treating an undated page as fresh is how a stale
    document becomes tomorrow's reason."""
    kept, dropped = filter_results([_r(dated=False)], now=NOW)
    assert kept == []
    assert "unknown age is not recent age" in dropped[0]["why"]


def test_an_empty_snippet_is_dropped():
    kept, dropped = filter_results([_r(content="   ")], now=NOW)
    assert kept == [] and dropped[0]["why"] == "empty snippet"


# ── 4. missing key refuses BY NAME, no browser ──────────────────────────────
def test_a_missing_key_raises_and_names_the_key(monkeypatch):
    import core.market_news as mn
    monkeypatch.setattr("core.source_status.credential_for", lambda k: None)
    with pytest.raises(NewsUnavailable) as e:
        mn.fetch_news("SPY")
    msg = str(e.value)
    assert "TAVILY_API_KEY" in msg
    assert "REFUSED by name" in msg
    assert "browser" in msg


# ── 5. HTTP error refuses, naming the status ────────────────────────────────
def test_an_http_error_refuses_and_names_the_status():
    def searcher(_q):
        raise NewsUnavailable("tavily: HTTP 429 for 'SPY' — REFUSED. No retry into a "
                              "browser, no cached snippet.")
    with pytest.raises(NewsUnavailable, match="HTTP 429"):
        fetch_news("SPY", searcher=searcher)


def test_any_other_exception_is_turned_into_a_named_refusal():
    def searcher(_q):
        raise TimeoutError("read timed out")
    with pytest.raises(NewsUnavailable) as e:
        fetch_news("SPY", searcher=searcher)
    assert "TimeoutError" in str(e.value) and "REFUSED" in str(e.value)


# ── 6. zero usable results refuses, saying how many were dropped and why ────
def test_zero_usable_results_refuses_with_counts_and_reasons():
    raw = [_r(url="https://blog.example/a"), _r(hours_ago=99), _r(dated=False)]
    with pytest.raises(NewsUnavailable) as e:
        fetch_news("SPY", now=NOW, searcher=lambda q: raw)
    m = str(e.value)
    assert "3 result(s)" in m and "3 dropped" in m
    assert "whitelist" in m and "older than" in m and "unknown age" in m
    assert "no fallback" in m


def test_a_usable_result_comes_back_with_its_provenance():
    got = fetch_news("SPY", now=NOW, searcher=lambda q: [_r()])
    assert len(got) == 1
    s = got[0]
    assert s.url.startswith("https://www.reuters.com/")
    assert s.published_utc and s.retrieved_utc
    assert s.snippet == "CPI rose 0.3% in August"


# ── 7. NO FALLBACK EXISTS ───────────────────────────────────────────────────
def test_the_module_has_no_fallback_path():
    """Not a style check. Every one of these turns "no evidence" into "some evidence",
    which is the exact failure R43 exists to stop."""
    import ast
    # STRIP DOCSTRINGS AND COMMENTS FIRST. The second version of this test failed
    # against the module's own docstring, which names "no synthesised headline, no
    # widened window" in order to FORBID them. A test that cannot tell prose from code
    # is testing the comments — the same mistake as test_generation_does_not_route_
    # through_brain_think, made twice in one day.
    class _Blank(ast.NodeTransformer):
        """Every STRING CONSTANT is blanked, not just docstrings.

        The third version of this test failed on the refusal message "No retry into a
        browser, no cached snippet" — a string that DENIES caching. A real fallback
        needs an identifier: an import, a call, an attribute. It cannot live in a
        message. So identifiers are what gets checked.
        """

        def visit_Constant(self, node):
            return ast.copy_location(
                ast.Constant(value="" if isinstance(node.value, str) else node.value),
                node)

    tree = _Blank().visit(
        ast.parse((REPO / "core" / "market_news.py").read_text(encoding="utf-8")))
    code = ast.unparse(tree).lower()
    for forbidden in ("cache", "fallback", "synthes", "widen",
                      "selenium", "playwright", "webdriver", "captcha"):
        assert forbidden not in code, f"{forbidden!r} appears in executable code"


def test_it_raises_rather_than_returning_an_empty_list():
    """An empty list reads as 'nothing happened'. The caller must be able to tell that
    apart from 'we could not look'."""
    import inspect

    import core.market_news as mn
    src = inspect.getsource(mn.fetch_news)
    assert "return []" not in src
    assert "raise NewsUnavailable" in src


def test_prediction_only_no_order_path():
    src = (REPO / "core" / "market_news.py").read_text(encoding="utf-8").lower()
    for word in ("place_order", "buy(", "sell(", "broker", "alpaca"):
        assert word not in src


def test_the_whitelist_uses_only_the_four_declared_classes():
    wl = json.loads((REPO / "config" / "news_whitelist.json").read_text(encoding="utf-8"))
    ri = json.loads((REPO / "config" / "reporter_independence.json")
                    .read_text(encoding="utf-8"))
    used = {h["class"] for h in wl["hosts"].values()}
    assert used <= set(ri["_classes"]), f"a fifth class was invented: {used}"
    assert wl["max_age_hours"] == 48


# ── the retrieval mode, fixed after the first grounded run refused everything ──
def test_the_search_asks_for_NEWS_because_basic_returns_no_dates():
    """MEASURED 2026-09-07: search_depth='basic' returned 0 of 6 results with a
    published_date; topic='news' returned 6 of 6. Since a result with no date is
    dropped by design, 'basic' meant the filter discarded everything it was handed —
    including whitelisted hosts — and no bet could ever be grounded.

    This asserts the request body, not the response, so it needs no network."""
    import core.market_news as mn
    sent = {}

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"results": []}

    def fake_post(url, timeout=None, json=None):
        sent.update(json or {})
        return R()

    import requests
    orig = requests.post
    requests.post = fake_post
    try:
        with pytest.raises(NewsUnavailable):
            mn.fetch_news("SPY")
    finally:
        requests.post = orig

    assert sent.get("topic") == "news", "basic search carries no published dates"
    assert sent.get("days") == 2, "the window is bounded at the source, not after"
    assert "search_depth" not in sent


# ── the date format Tavily actually sends ───────────────────────────────────
def test_it_parses_rfc1123_with_a_NAMED_zone_which_is_what_tavily_sends():
    """THE THIRD BUG, and the one that cost a whole run. Tavily returns
    'Fri, 04 Sep 2026 12:35:01 GMT'. strptime's %z wants +0000 and rejects 'GMT', so
    _parse_dt returned None for EVERY result and the freshness filter dropped them all
    as undated — including the whitelisted, genuinely dated ones.

    A parser that cannot read the only format the source emits is indistinguishable
    from a source that sends no dates."""
    from core.market_news import _parse_dt
    for raw in ("Fri, 04 Sep 2026 12:35:01 GMT",
                "Sun, 06 Sep 2026 10:00:00 UTC",
                "2026-09-05T12:30:00Z",
                "2026-09-05T12:30:00+00:00",
                "2026-09-05"):
        dt = _parse_dt(raw)
        assert dt is not None, raw
        assert dt.tzinfo is not None, raw
        assert dt.year == 2026


def test_a_real_tavily_shaped_result_survives_the_filter():
    """End to end on the exact shape the API returns."""
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    now = _dt(2026, 9, 5, 18, 0, tzinfo=_tz.utc)
    raw = [{"url": "https://www.cnbc.com/2026/09/04/gold.html",
            "title": "Gold hits record",
            "content": "Gold climbed to a record high on Friday as the dollar eased",
            "published_date": "Fri, 04 Sep 2026 12:35:01 GMT"}]
    kept, dropped = filter_results(raw, now=now)
    assert dropped == [], dropped
    assert len(kept) == 1 and kept[0].host == "cnbc.com"


def test_an_unparseable_date_is_still_dropped():
    """The fix must not become 'accept anything'."""
    from core.market_news import _parse_dt
    assert _parse_dt("last Tuesday") is None
    assert _parse_dt("") is None
