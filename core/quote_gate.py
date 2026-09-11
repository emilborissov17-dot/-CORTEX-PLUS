#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/quote_gate.py — R43 AT INGEST: a number from an agent is accepted only if
its quote is REALLY on the page it names. (ITEM 80, 10 September 2026.)

WHY, WITH THE CASE THAT FORCED IT
---------------------------------
Task card #1 to the OpenClaw sensor, 10 Sep 2026 ~15:15 UTC: NOAA daily CO2.
The agent returned {"value": 426.62, "quote": "September 09:   426.62 ppm"}.
The cloud session's two fetches of that URL showed the previous day's version
(Last Updated: September 9, no "September 09" row) and the cloud session called
it a plausible invention. IT WAS NOT: Emil opened the page — the row was there,
Last Updated: September 10. The VERIFIER was stale, the sensor was right.
Both halves of that hour are the reason this module exists: an agent's quote
must be checked, and the check must be against the LIVE page, at ingest time,
on this machine, never through a cache — otherwise the gate itself invents
refusals. (7 Sep, FIRST_BET_MARKETS: 22 of 24 invented "signals" passed a shape
check — the other failure mode, the one the gate is for.)

A shape check cannot do this job. Only the page can. So the gate FETCHES the
URL itself and requires the quote to be a substring of the page text
(whitespace-normalised, case-preserved). No fetch, no acceptance. A quote that
is not on the page is REFUSED by name, and the refusal is a record, because a
sensor that invents once will invent again and the rate is the thing to know.

VERDICTS
  ACCEPTED           quote found; value parsed from the quote equals `value`
  VALUE_MISMATCH     quote found, but the number in it is not `value`
  QUOTE_NOT_ON_PAGE  fetched fine; quote absent
  FETCH_FAILED       could not fetch (network, 4xx/5xx) — NOT an acceptance,
                     NOT a refusal of the agent: left open, retry later
  MALFORMED          missing fields / value not a number / quote empty
  RECOUNT_MISMATCH   aggregate card: the gate recounted the page and got a
                     different number

TWO THINGS THE FIRST VERSION GOT WRONG (11 Sep 2026, cards A/B/C)
  * A number token inside a timestamp counted as a number: value 0 was
    ACCEPTED because "2026-08-14T00:00:00" contains "00". Numbers are now
    STANDALONE tokens — not glued to '-', ':', 'T', '/', letters or digits.
  * A COUNT of items in a list (card B: GDACS Orange/Red wildfires in the
    last 7 days) is never printed on any page, so no quote can carry it.
    For such an AGGREGATE card the record names its window (`window_utc`)
    and the gate RECOUNTS the page itself: every JSON object carrying a
    `fromdate` inside the window. The quote must still be on the page; the
    value must equal the gate's own count. An agent that cannot be checked
    by substring is checked by recomputation, never by trust.

The gate never modifies the record and never guesses a value. It is pure:
`judge(record, page_text)` takes the text; `check(record)` fetches then judges.
"""
from __future__ import annotations

import html
import json
import re
import sys
from typing import Callable, Optional

REQUIRED = ("axis", "key", "value", "unit", "url", "quote")
# standalone numbers only: "2.23" in "2025 2.23 0.11" yes; "00" in "T00:00:00" no
_NUM = re.compile(r"(?<![\w:./\-])-?\d+(?:[.,]\d+)?(?![\w:./\-])")
_WS = re.compile(r"\s+")
_DATE_KEYS = ("fromdate", "from_date", "date", "time", "starttime")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def recount(page_text: str, window_utc: str, date_key: str = "fromdate") -> int | None:
    """Count JSON objects whose `date_key` falls inside "start/end" (ISO, UTC).
    None if the page is not JSON or the window is unreadable."""
    try:
        data = json.loads(page_text)
        start, end = [x.strip().replace("Z", "") for x in str(window_utc).split("/", 1)]
    except (ValueError, TypeError):
        return None
    n = 0
    for obj in _walk(data):
        d = obj.get(date_key)
        if isinstance(d, str) and start <= d.replace("Z", "")[:len(start)] <= end:
            n += 1
    return n


def judge(record: dict, page_text: Optional[str]) -> dict:
    """Pure verdict. page_text=None means the fetch failed."""
    missing = [k for k in REQUIRED if k not in record or record[k] in (None, "")]
    if record.get("value") is None and record.get("reason"):
        return {"verdict": "NULL_WITH_REASON", "reason": record["reason"]}   # a named absence is a correct answer
    if missing:
        return {"verdict": "MALFORMED", "missing": missing}
    try:
        value = float(record["value"])
    except (TypeError, ValueError):
        return {"verdict": "MALFORMED", "missing": ["value:not-a-number"]}
    quote = _norm(str(record["quote"]))
    if not quote:
        return {"verdict": "MALFORMED", "missing": ["quote:empty"]}
    if page_text is None:
        return {"verdict": "FETCH_FAILED", "url": record["url"]}
    page = _norm(page_text)
    # whitespace-collapsed first; then whitespace-free, for JSON/API bodies where the
    # agent quotes '"count": 38' and the server serves '"count":38' (card 5, 10 Sep)
    if quote not in page and _WS.sub("", quote) not in _WS.sub("", page):
        return {"verdict": "QUOTE_NOT_ON_PAGE", "quote": quote, "url": record["url"]}
    if record.get("window_utc"):
        # AGGREGATE: the value is a count over the page, not a number on it
        n = recount(page_text, record["window_utc"], record.get("date_key", "fromdate"))
        if n is None:
            return {"verdict": "MALFORMED", "missing": ["window_utc:page-not-json-or-window-unreadable"]}
        if n != int(value):
            return {"verdict": "RECOUNT_MISMATCH", "value": value, "gate_count": n,
                    "window_utc": record["window_utc"]}
        return {"verdict": "ACCEPTED", "value": value, "gate_count": n, "aggregate": True,
                "quote": quote, "url": record["url"]}
    nums = [float(n.replace(",", ".")) for n in _NUM.findall(quote)]
    if not any(abs(n - value) < 1e-9 for n in nums):
        return {"verdict": "VALUE_MISMATCH", "value": value, "numbers_in_quote": nums}
    return {"verdict": "ACCEPTED", "value": value, "quote": quote, "url": record["url"]}


def _fetch(url: str, timeout: int = 30) -> Optional[str]:
    try:
        import requests  # noqa: PLC0415
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "CORTEX++ quote_gate/1.0"})
        if r.status_code != 200:
            return None
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        # ENTITIES ARE DECODED — RESTORED 11 Sep 2026 after this line was lost.
        # The 10 Sep live run refused a TRUE reading: monthly.html serves
        # "September 09:&nbsp;&nbsp; 426.62 ppm" and the agent, reading the
        # RENDERED page, quoted spaces. Tag-stripping leaves the literal
        # "&nbsp;", so no whitespace normalisation could ever match, and a
        # correct observation would have been filed against the sensor's
        # invention rate. The uploaded version of this file dropped the fix and
        # its three tests with it; both are back, and the tests are what make
        # dropping it again visible.
        return html.unescape(text)
    except Exception:  # noqa: BLE001 — a failed fetch is a named verdict, never an exception
        return None


def check(record: dict, fetch: Callable[[str], Optional[str]] = _fetch) -> dict:
    return judge(record, fetch(str(record.get("url", ""))))


if __name__ == "__main__":
    raw = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1], encoding="utf-8").read()
    rec = json.loads(raw)
    out = check(rec)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if out["verdict"] in ("ACCEPTED", "NULL_WITH_REASON") else 2)
