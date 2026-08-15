"""The RSS feed roster: no dead entries, and every request identifies itself.

On 2026-08-04 fourteen of the configured feeds failed in one cycle. The log called them
all dead. Five were not: `requests` announces itself as "python-requests/2.x", and the
CDN in front of renewableenergyworld, un.org/press, un.org/sustainabledevelopment,
foreignpolicy and the EA forum answers an unidentified client with 403. That reads in a
log exactly like a dead feed, so a one-line client detail had quietly cost five sources
and nobody could tell the difference from the outside.

The offline checks here run everywhere and are the regression guard. The network check
is opt-in — it must never turn a CI run red because a publisher had a bad afternoon:

    CORTEX_RSS_NETWORK=1 venv/Scripts/python.exe -m pytest test/test_rss_feeds.py
"""
import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

import web_intelligence_agent as W  # noqa: E402


def _internet_agent_feeds() -> list:
    text = (REPO / "agents" / "internet" / "internet_agent.py").read_text(encoding="utf-8")
    block = text.split("RSS_FEEDS = {")[1].split("}")[0]
    return sorted(set(re.findall(r"'(https?://[^']+)'", block)))


def _web_intel_feeds() -> list:
    return sorted({u for cfg in W.AXES.values() for u in cfg.get("rss", [])})


def test_fetcher_identifies_itself():
    """The 403s were a missing User-Agent, not dead publishers."""
    ua = W._RSS_HEADERS.get("User-Agent", "")
    assert ua and "python-requests" not in ua.lower()
    assert "Mozilla" in ua


def test_known_dead_feeds_are_gone():
    """Every URL retired on 2026-08-04 after probing it live and getting 404/403."""
    retired = {
        "https://www.waterworld.com/rss.xml",              # 404
        "https://www.fao.org/news/rss-feed/en/",           # 404
        "https://www.foodnavigator.com/rss/feed.php",      # 404
        "https://resource.co/rss.xml",                     # 404
        "https://www.oxfam.org/en/feed",                   # 404
        "https://blogs.worldbank.org/rss.xml",             # 404
        "https://www.hrw.org/rss",                         # 403 even with a browser UA
        "https://www.thebulletin.org/feed/",               # 403 even with a browser UA
        "https://www.edsurge.com/feed",                    # redirected to localhost:8080
        "https://climate.nasa.gov/news/rss.xml",           # 200 but zero entries
        "https://feeds.theecologist.org/resilience",       # zero entries
    }
    configured = set(_web_intel_feeds()) | set(_internet_agent_feeds())
    assert not (configured & retired), f"dead feed back in the roster: {configured & retired}"


def test_no_feed_points_at_localhost():
    """edsurge.com/feed redirected into localhost:8080 and the log blamed the network."""
    for url in _web_intel_feeds() + _internet_agent_feeds():
        assert "localhost" not in url and "127.0.0.1" not in url, url


@pytest.mark.skipif(not os.environ.get("CORTEX_RSS_NETWORK"),
                    reason="network check is opt-in: set CORTEX_RSS_NETWORK=1")
def test_every_configured_feed_returns_items():
    dead = [u for u in _web_intel_feeds() if not W._fetch_rss(u, max_items=3)]
    assert not dead, f"{len(dead)} dead feed(s): {dead}"
