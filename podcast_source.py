#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
podcast_source.py
Finds recent podcast episodes from hardcoded scientific/climate RSS feeds.
No anti-bot protection needed — RSS is open. Direct MP3 links in enclosure tags.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import requests

MAX_EPISODE_AGE_DAYS = 730  # 2 years back

PODCAST_FEEDS: list[dict] = [
    {
        "name": "Outrage + Optimism",
        "rss":  "https://feeds.acast.com/public/shows/6781112bec40818e0b501b6a",
    },
    {
        "name": "Science Friday",
        "rss":  "https://feeds.simplecast.com/h18ZIZD_",
    },
    {
        "name": "The Energy Gang",
        "rss":  "https://rss.art19.com/the-energy-gang",
    },
    {
        "name": "NPR Short Wave",
        "rss":  "https://feeds.npr.org/510351/podcast.xml",
    },
    {
        "name": "Science Vs",
        "rss":  "https://feeds.megaphone.fm/sciencevs",
    },
    {
        "name": "TED Radio Hour",
        "rss":  "https://feeds.npr.org/510298/podcast.xml",
    },
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CORTEX-MediaBot/1.0)"}


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_pub_date(raw: str) -> datetime | None:
    """Parse RFC 2822 / RSS pubDate to aware datetime. Returns None on failure."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _parse_rss_feed(feed_name: str, feed_url: str) -> list[dict]:
    """Fetch one RSS feed and return a list of episode dicts."""
    try:
        resp = requests.get(feed_url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [POD-RSS] {feed_name} — fetch error: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        print(f"  [POD-RSS] {feed_name} — XML parse error: {e}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_EPISODE_AGE_DAYS)
    episodes: list[dict] = []

    for item in channel.findall("item"):
        title_el     = item.find("title")
        desc_el      = item.find("description")
        pubdate_el   = item.find("pubDate")
        enclosure_el = item.find("enclosure")

        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        audio_url = ""
        if enclosure_el is not None:
            audio_url = enclosure_el.get("url", "").strip()
        if not audio_url:
            continue

        raw_pub = (pubdate_el.text or "").strip() if pubdate_el is not None else ""
        pub_dt  = _parse_pub_date(raw_pub) if raw_pub else None
        if pub_dt and pub_dt < cutoff:
            continue

        desc = ""
        if desc_el is not None and desc_el.text:
            desc = _strip_html(desc_el.text)[:800]

        episodes.append({
            "title":          title,
            "description":    desc,
            "audio_url":      audio_url,
            "published_date": raw_pub,
            "podcast_name":   feed_name,
        })

    return episodes


def _keyword_hit(text: str, keywords: list[str]) -> bool:
    """True if any keyword substring appears in text (case-insensitive)."""
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def find_podcast_episodes(
    keywords: list[str],
    axis_name: str,
    max_per_feed: int = 3,
) -> list[dict]:
    """
    Search all PODCAST_FEEDS for episodes relevant to keywords.
    Returns list of {title, description, audio_url, published_date, podcast_name}.
    Keyword match is a lightweight pre-filter; LLM scoring happens in the worker.
    """
    results: list[dict] = []

    # Expand keyword list — split multi-word phrases into individual words
    # so narrow phrases still catch relevant titles
    expanded = set()
    for phrase in keywords:
        for word in phrase.lower().split():
            if len(word) > 3:
                expanded.add(word)
    # Also add axis label words
    for word in axis_name.lower().replace("_review", "").split("_"):
        if len(word) > 3:
            expanded.add(word)
    all_kw = list(expanded)

    for feed in PODCAST_FEEDS:
        episodes = _parse_rss_feed(feed["name"], feed["rss"])
        print(f"  [POD-RSS] {feed['name']}: {len(episodes)} recent episodes")

        matched: list[dict] = []
        for ep in episodes:
            combined = f"{ep['title']} {ep['description']}"
            if _keyword_hit(combined, all_kw):
                matched.append(ep)
            if len(matched) >= max_per_feed:
                break

        if matched:
            print(f"  [POD-RSS] {feed['name']}: {len(matched)} matched -> adding")
        results.extend(matched)

    return results
