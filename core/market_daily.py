#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPY / GLD / UUP daily closes, and the 20-trading-day momentum baseline.

PREDICTION ONLY. Nothing here places, sizes, or recommends a trade. It reads a public
daily close and computes a direction, and the only thing done with that direction is
to record a forecast that reality grades. (Spec §VI.)

WHY NOT STOOQ. The brief suggested `stooq.com/q/d/l/?s=spy.us&i=d`. Measured 2026-09-07
it returns **HTTP 200 with a proof-of-work JavaScript challenge** - 796 bytes of
`crypto.subtle.digest` in a loop - not CSV. That is worse than a 404: a caller checking
`status == 200` accepts the challenge page as data. Solving it is bot-detection bypass,
which this project does not do, so Stooq is refused by name rather than worked around.

THE SOURCE. Yahoo's chart API, keyless:
    https://query1.finance.yahoo.com/v8/finance/chart/<SYM>?range=3mo&interval=1d
"""
from __future__ import annotations

import datetime as _dt
import statistics
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ASSETS = ("SPY", "GLD", "UUP")
INDICATOR_FMT = "MARKET_{sym}_CLOSE"
INDICATORS = {s: INDICATOR_FMT.format(sym=s) for s in ASSETS}
MOMENTUM_DAYS = 20
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=3mo&interval=1d"

TRENDS_PATH = REPO / "cortex_memory" / "abstractions" / "trends.json"

EXTRACT_PATH = ("chart.result[0].timestamp[i] (epoch, MARKET OPEN 13:30 UTC, not the "
                "close) + chart.result[0].indicators.adjclose[0].adjclose[i]")
UNITS = "USD per share, dividend-adjusted daily close"


def parse_chart(payload: dict) -> list:
    """[(date, adjclose)] for the whole range, oldest first.

    ADJCLOSE, NOT CLOSE. They are identical today for all three - checked on the last
    25 bars of each - and they diverge on every ex-dividend date, where the raw close
    drops by the dividend. A direction bet scored on raw close would record a loss on a
    day the holder broke even. SPY, GLD and UUP all distribute, so this will bite.

    THE TIMESTAMP IS THE OPEN. Bars carry 13:30 UTC = 09:30 America/New_York, the start
    of the session; `meta.regularMarketTime` is the close (20:00 UTC). Only the DATE is
    used from the bar, never the time.
    """
    r = payload["chart"]["result"][0]
    ts = r["timestamp"]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    out = []
    for t, a in zip(ts, adj):
        if a is None:
            continue                      # a bar with no close is not a zero close
        out.append((_dt.datetime.fromtimestamp(t, _dt.timezone.utc).date(), float(a)))
    return out


def last_close(bars: list) -> tuple:
    """(date, price) of the most recent COMPLETE session in the payload."""
    if not bars:
        raise ValueError("no bars")
    return bars[-1]


def momentum_sign(bars: list, days: int = MOMENTUM_DAYS) -> dict:
    """THE BASELINE the bet must beat: sign of the mean daily return over the last
    `days` TRADING days.

    Trading days, not calendar days. Observed gaps between consecutive bars are 1, 3
    and 4 days (weekends and holidays), so 20 trading days spans about 28 calendar
    days and a calendar window would silently use a different number of returns.
    """
    if len(bars) < days + 1:
        raise ValueError(f"need {days + 1} bars, have {len(bars)}")
    px = [p for _, p in bars]
    rets = [(px[i] - px[i - 1]) / px[i - 1] for i in range(len(px) - days, len(px))]
    mean = statistics.fmean(rets)
    return {"mean_daily_return": mean,
            "sign": "UP" if mean > 0 else "DOWN",
            "n_returns": len(rets),
            "from_date": bars[-days - 1][0].isoformat(),
            "to_date": bars[-1][0].isoformat()}


def fetch_chart(sym: str, timeout: int = 60) -> dict:
    """Network; never called by the tests."""
    import requests
    r = requests.get(CHART_URL.format(sym=sym), timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 (compatible; CORTEX++/1.0; research)"})
    r.raise_for_status()
    body = r.json()
    if not (body.get("chart") or {}).get("result"):
        raise ValueError(f"{sym}: no chart.result — {str(body)[:160]}")
    return body


def registration_entry(closes: dict) -> dict:
    """trends.json keys. ground_truth takes values[-1], so each is a LIST ending in the
    latest close."""
    return {INDICATORS[s]: [round(float(v), 4) for v in series]
            for s, series in closes.items()}


def is_registered(trends_path: Path | None = None) -> bool:
    import json
    p = Path(trends_path or TRENDS_PATH)
    try:
        live = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return False
    return all(v in live for v in INDICATORS.values())


def _selftest() -> int:
    print("core/market_daily.py --selftest   (PREDICTION ONLY — no trading)")
    print(f"  assets      : {ASSETS}")
    print(f"  indicators  : {INDICATORS}")
    print(f"  extract     : {EXTRACT_PATH}")
    print(f"  units       : {UNITS}")
    print(f"  registered  : {is_registered()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
