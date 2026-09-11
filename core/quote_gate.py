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
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s).strip()


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
        # ENTITIES ARE DECODED, AND THE GATE'S FIRST LIVE RUN IS WHY (10 Sep 2026).
        # Card 1 — the NOAA CO2 reading this module's docstring was written about —
        # was REFUSED as QUOTE_NOT_ON_PAGE on the first real run. It was on the
        # page. monthly.html serves:
        #     September 09:&nbsp;&nbsp; 426.62 ppm
        # and the agent, reading the rendered page, quoted "September 09:   426.62
        # ppm". Stripping tags leaves the literal text "&nbsp;", so neither the
        # whitespace-collapsed nor the whitespace-free comparison could ever match,
        # and a TRUE reading would have been filed against the sensor's invention
        # rate — poisoning the one number this module exists to produce, and
        # starving the corpus of a row the world had confirmed.
        # This is precisely the failure the docstring names: a gate that invents
        # refusals is worse than no gate. html.unescape turns &nbsp; into U+00A0,
        # which _norm's \s+ then collapses like any other space.
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
