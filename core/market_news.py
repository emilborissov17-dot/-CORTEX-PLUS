#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Retrieved news snippets for a grounded market bet. See claude/SPEC_7SEP_R43_GROUNDED_BET.md.

PREDICTION ONLY (§VI). This reads public documents. It places nothing.

WHY THIS EXISTS. On 2026-09-07 a market bet sealed three forecasts whose every cited
fact was invented — a Jackson Hole transcript dated thirteen days AFTER the session it
claimed to explain, corporate earnings offered as the driver for gold and the dollar
index, Q1 GDP "released 7 Sep". The model had prices only and was asked for facts, so it
produced well-shaped fiction and the gate, which checked shape, admitted 22 of 24.

This module removes the possibility rather than the temptation: the model stops
supplying facts and starts being handed them.

REFUSE LOUD, NEVER FALL BACK. Every failure raises `NewsUnavailable` with the reason
named. There is no cache, no synthesised headline, no widened window, no relaxed
whitelist, and no browser attempt when the key is missing. Each of those turns "no
evidence" into "some evidence", which is exactly the failure being fixed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
WHITELIST_PATH = REPO / "config" / "news_whitelist.json"
SOURCE_KEY = "tavily"
API_URL = "https://api.tavily.com/search"

QUERIES = {
    "SPY": "S&P 500 stocks market move",
    "GLD": "gold price move",
    "UUP": "US dollar index move",
}


class NewsUnavailable(RuntimeError):
    """No usable evidence, and the reason is in the message.

    Raised rather than returning [] on purpose: an empty list reads as "nothing
    happened", and the caller must be able to tell that apart from "we could not look".
    """


@dataclass(frozen=True)
class Snippet:
    title: str
    url: str
    host: str
    published_utc: str
    snippet: str
    retrieved_utc: str

    def as_dict(self) -> dict:
        return asdict(self)


def _whitelist() -> dict:
    return json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))


def host_of(url: str) -> str:
    """Registrable host, lowercased, `www.` stripped."""
    h = (urlparse(str(url or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def host_allowed(url: str, hosts: dict | None = None) -> bool:
    """A host matches if it IS a listed host or a subdomain of one.

    `evil-reuters.com` must NOT match `reuters.com`, which is why this compares
    labels rather than calling `endswith`.
    """
    hosts = hosts if hosts is not None else _whitelist()["hosts"]
    h = host_of(url)
    if not h:
        return False
    for allowed in hosts:
        if h == allowed or h.endswith("." + allowed):
            return True
    return False


def _parse_dt(value):
    """A published date, or None. None is never treated as fresh."""
    if not value:
        return None
    s = str(value).strip().replace("Z", "+00:00")
    for parse in (datetime.fromisoformat,
                  lambda x: datetime.strptime(x, "%a, %d %b %Y %H:%M:%S %z"),
                  lambda x: datetime.strptime(x, "%Y-%m-%d")):
        try:
            dt = parse(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def filter_results(raw: list, now: datetime | None = None,
                   whitelist: dict | None = None) -> tuple:
    """(kept, dropped) — every drop carries its reason so the filter is auditable."""
    wl = whitelist if whitelist is not None else _whitelist()
    hosts, max_age = wl["hosts"], int(wl["max_age_hours"])
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age)

    kept, dropped = [], []
    for r in raw or []:
        url = r.get("url") or ""
        h = host_of(url)
        if not host_allowed(url, hosts):
            dropped.append({"host": h or "(none)", "url": url,
                            "why": f"host not on the whitelist ({len(hosts)} allowed)"})
            continue
        pub = _parse_dt(r.get("published_date") or r.get("published_time"))
        if pub is None:
            # UNKNOWN AGE IS NOT RECENT AGE. Treating an undated document as fresh is
            # how a stale page becomes tomorrow's reason.
            dropped.append({"host": h, "url": url,
                            "why": "no published date — unknown age is not recent age"})
            continue
        if pub < cutoff:
            dropped.append({"host": h, "url": url,
                            "why": f"published {pub.isoformat()}, older than {max_age}h"})
            continue
        text = str(r.get("content") or r.get("snippet") or "").strip()
        if not text:
            dropped.append({"host": h, "url": url, "why": "empty snippet"})
            continue
        kept.append(Snippet(title=str(r.get("title") or "").strip(), url=url, host=h,
                            published_utc=pub.astimezone(timezone.utc).isoformat(),
                            snippet=text,
                            retrieved_utc=now.astimezone(timezone.utc).isoformat()))
    return kept, dropped


def _api_key() -> str:
    from core.source_status import credential_for
    key = (credential_for(SOURCE_KEY) or "").strip()
    if not key:
        raise NewsUnavailable(
            "tavily: no TAVILY_API_KEY — discovery REFUSED by name, not attempted in a "
            "browser. Put TAVILY_API_KEY=<key> in .env; config/dead_sources.json "
            "registers it as NEEDS_AUTH.")
    return key


def fetch_news(asset: str, query: str | None = None, now: datetime | None = None,
               searcher=None, timeout: int = 45) -> list:
    """Usable snippets for `asset`, or raise NewsUnavailable naming why not.

    `searcher` is injectable so the tests never touch the network or the key.
    """
    q = query or QUERIES.get(asset) or asset
    if searcher is None:
        key = _api_key()

        def searcher(question):
            import requests
            r = requests.post(API_URL, timeout=timeout,
                              json={"api_key": key, "query": question,
                                    "search_depth": "basic", "max_results": 12,
                                    "include_raw_content": False})
            if r.status_code != 200:
                raise NewsUnavailable(
                    f"tavily: HTTP {r.status_code} for {asset!r} — REFUSED. "
                    f"No retry into a browser, no cached snippet.")
            return (r.json() or {}).get("results") or []

    try:
        raw = searcher(q)
    except NewsUnavailable:
        raise
    except Exception as e:                                        # noqa: BLE001
        raise NewsUnavailable(
            f"tavily: {type(e).__name__} for {asset!r} — REFUSED. {e}") from e

    kept, dropped = filter_results(raw, now=now)
    for d in dropped:
        print(f"  [NEWS] dropped {d['host']}: {d['why']}")
    if not kept:
        why = "; ".join(sorted({d["why"] for d in dropped})) or "the search returned nothing"
        raise NewsUnavailable(
            f"tavily: no usable evidence for {asset!r} — {len(raw or [])} result(s), "
            f"{len(dropped)} dropped ({why}). REFUSED: an asset with no fact gets no "
            f"bet, and there is no fallback.")
    return kept


def _selftest() -> int:
    from core.source_status import credential_for
    print("core/market_news.py --selftest   (PREDICTION ONLY — reads documents)")
    wl = _whitelist()
    print(f"  whitelist hosts : {len(wl['hosts'])}")
    print(f"  max age         : {wl['max_age_hours']} h")
    print(f"  key reachable   : {bool((credential_for(SOURCE_KEY) or '').strip())}")
    print("  NO live search is performed by --selftest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
