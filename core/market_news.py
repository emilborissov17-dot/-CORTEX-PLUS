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
BLACKLIST_PATH = REPO / "config" / "news_blacklist.json"
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
    source_class: str = "unknown"
    source_kind: str = "unclassified"
    dated: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


def _blacklist() -> dict:
    return json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))


def host_of(url: str) -> str:
    """Registrable host, lowercased, `www.` stripped."""
    h = (urlparse(str(url or "")).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def host_allowed(url: str, cfg: dict | None = None) -> bool:
    """Everything NOT blacklisted is allowed.

    The verbatim gate is the fabrication guard and it does not care who published the
    snippet. What a quote CANNOT protect against is prompt injection and machine-spun
    text with no author, and both are properties of the host - so the host is filtered
    for those two things and nothing else.
    """
    cfg = cfg if cfg is not None else _blacklist()
    h = host_of(url)
    if not h:
        return False
    if h in cfg["blocked_hosts"]:
        return False
    for suf in cfg["blocked_suffixes"]:
        if h.endswith(suf):
            return False
    # A blocked host must also block its subdomains: news.reddit.com is reddit.
    for blocked in cfg["blocked_hosts"]:
        if h.endswith("." + blocked):
            return False
    return True


def block_reason(url: str, cfg: dict | None = None) -> str | None:
    cfg = cfg if cfg is not None else _blacklist()
    h = host_of(url)
    if not h:
        return "no host in url"
    entry = cfg["blocked_hosts"].get(h)
    if entry:
        return f"blacklisted host ({entry['why']})"
    for blocked, e in cfg["blocked_hosts"].items():
        if h.endswith("." + blocked):
            return f"subdomain of blacklisted {blocked} ({e['why']})"
    for suf in cfg["blocked_suffixes"]:
        if h.endswith(suf):
            return f"open publishing platform ({suf})"
    return None


def host_class(url: str, cfg: dict | None = None) -> dict:
    """METADATA, never a gate. An unknown host is 'unknown' and is allowed.

    It reaches the prompt because the SOURCE TYPE IS PART OF THE MARKET SIGNAL: a wire
    report and a broker's commentary move a price differently, and the model should see
    which it is holding. It is not a trust score and nothing filters on it.
    """
    cfg = cfg if cfg is not None else _blacklist()
    h = host_of(url)
    known = cfg["host_classes"].get(h)
    if known:
        return dict(known)
    for host, meta in cfg["host_classes"].items():
        if h.endswith("." + host):
            return dict(meta)
    return {"class": "unknown", "kind": "unclassified"}


def _parse_dt(value):
    """A published date, or None. None is never treated as fresh.

    RFC-1123 WITH A NAMED ZONE IS THE FORMAT TAVILY ACTUALLY SENDS:
    'Fri, 04 Sep 2026 12:35:01 GMT'. strptime's %z does NOT accept 'GMT' — it wants
    +0000 — so the first version returned None for every single result and the
    freshness filter dropped them all as undated. The second grounded run refused GLD
    and UUP that way even though both carried whitelisted, dated sources.

    A parser that cannot read the only format the source emits is indistinguishable
    from a source that sends no dates, which is why the named zones are mapped
    explicitly rather than hoped for.
    """
    if not value:
        return None
    s = str(value).strip()
    for name, offset in (("GMT", "+0000"), ("UTC", "+0000"), ("Z", "+00:00")):
        if s.endswith(" " + name):
            s = s[: -len(name)] + offset
            break
        if name == "Z" and s.endswith("Z"):
            s = s[:-1] + offset
    for parse in (datetime.fromisoformat,
                  lambda x: datetime.strptime(x, "%a, %d %b %Y %H:%M:%S %z"),
                  lambda x: datetime.strptime(x, "%a, %d %b %Y %H:%M:%S"),
                  lambda x: datetime.strptime(x, "%Y-%m-%d")):
        try:
            dt = parse(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def filter_results(raw: list, now: datetime | None = None,
                   cfg: dict | None = None) -> tuple:
    """(citable, context_only, dropped) — THREE date states, not two.

    dated AND inside the window  -> CITABLE. It can carry the grounding citation.
    dated AND outside            -> DROPPED. The date is a real claim and it failed.
    UNDATED                      -> DOWNGRADED to context-only, not dropped.

    The third state is the change. Absence of a date is not evidence of staleness, but
    it is not evidence of freshness either, so an undated snippet may ground a bet ONLY
    when nothing citable exists - and a bet grounded that way is flagged
    'ungrounded-citation' so the weakness travels with it instead of disappearing.

    WHEN A DATE FIELD EXISTS, ITS VALUE IS CHECKED, never merely its presence. Tavily's
    `days` parameter is best-effort: asking for 2 days returned articles 101 to 112
    hours old on 2026-09-07. A filter that trusted the request would have admitted all
    of them.
    """
    cfg = cfg if cfg is not None else _blacklist()
    max_age = int(cfg["max_age_hours"])
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age)

    citable, context_only, dropped = [], [], []
    for r in raw or []:
        url = r.get("url") or ""
        h = host_of(url)
        why = block_reason(url, cfg)
        if why:
            dropped.append({"host": h or "(none)", "url": url, "why": why})
            continue
        text = str(r.get("content") or r.get("snippet") or "").strip()
        if not text:
            dropped.append({"host": h, "url": url, "why": "empty snippet"})
            continue

        raw_date = r.get("published_date") or r.get("published_time")
        pub = _parse_dt(raw_date)
        meta = host_class(url, cfg)

        if pub is None:
            # Includes the case where a date FIELD is present but unparseable: an
            # unreadable date is an unknown date, not a fresh one.
            context_only.append(Snippet(
                title=str(r.get("title") or "").strip(), url=url, host=h,
                published_utc="", snippet=text,
                retrieved_utc=now.astimezone(timezone.utc).isoformat(),
                source_class=meta["class"], source_kind=meta["kind"], dated=False))
            continue
        if pub < cutoff:
            dropped.append({"host": h, "url": url,
                            "why": f"published {pub.isoformat()}, older than {max_age}h"})
            continue
        citable.append(Snippet(
            title=str(r.get("title") or "").strip(), url=url, host=h,
            published_utc=pub.astimezone(timezone.utc).isoformat(), snippet=text,
            retrieved_utc=now.astimezone(timezone.utc).isoformat(),
            source_class=meta["class"], source_kind=meta["kind"], dated=True))
    return citable, context_only, dropped


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
               searcher=None, timeout: int = 45) -> tuple:
    """(snippets, ungrounded_citation) or raise NewsUnavailable naming why not.

    `ungrounded_citation` is True when the only evidence available was undated.

    `searcher` is injectable so the tests never touch the network or the key.
    """
    q = query or QUERIES.get(asset) or asset
    if searcher is None:
        key = _api_key()

        def searcher(question):
            import requests
            # topic="news", NOT search_depth="basic".
            #
            # MEASURED 2026-09-07, after the first grounded run refused all three
            # assets: basic returns 0 of 6 results WITH a published_date, news returns
            # 6 of 6. The 48-hour filter was therefore discarding everything it was
            # handed - including whitelisted hosts - so the pipeline could never have
            # grounded a bet. `days` bounds the search at the source instead of
            # fetching a month and throwing most of it away.
            r = requests.post(API_URL, timeout=timeout,
                              json={"api_key": key, "query": question,
                                    "topic": "news", "days": 2, "max_results": 20,
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

    citable, context_only, dropped = filter_results(raw, now=now)
    for d in dropped:
        print(f"  [NEWS] dropped {d['host']}: {d['why']}")
    for c in context_only:
        print(f"  [NEWS] downgraded {c.host}: no usable published date — context only")
    print(f"  [NEWS] {asset}: kept {len(citable)} citable, "
          f"{len(context_only)} context-only, {len(dropped)} dropped")

    if citable:
        return citable, False
    if context_only:
        # THE FALLBACK THAT IS ALLOWED, because it is declared rather than hidden: an
        # undated snippet may carry the citation when nothing dated exists, and the bet
        # is flagged so the weakness is visible at grading time.
        print(f"  [NEWS] {asset}: NO DATED EVIDENCE — grounding on context-only "
              f"snippets, the bet will be flagged 'ungrounded-citation'")
        return context_only, True
    why = "; ".join(sorted({d["why"] for d in dropped})) or "the search returned nothing"
    raise NewsUnavailable(
        f"tavily: no usable evidence for {asset!r} — {len(raw or [])} result(s), "
        f"{len(dropped)} dropped ({why}). REFUSED: an asset with no fact gets no "
        f"bet, and there is no fallback.")


def _selftest() -> int:
    from core.source_status import credential_for
    print("core/market_news.py --selftest   (PREDICTION ONLY — reads documents)")
    bl = _blacklist()
    print(f"  blocked hosts   : {len(bl['blocked_hosts'])}")
    print(f"  blocked suffixes: {len(bl['blocked_suffixes'])}")
    print(f"  known classes   : {len(bl['host_classes'])} (metadata, never a gate)")
    print(f"  max age         : {bl['max_age_hours']} h")
    print(f"  key reachable   : {bool((credential_for(SOURCE_KEY) or '').strip())}")
    print("  NO live search is performed by --selftest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
