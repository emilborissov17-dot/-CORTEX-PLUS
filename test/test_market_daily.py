# -*- coding: utf-8 -*-
"""
SPY / GLD / UUP wiring. PREDICTION ONLY — nothing here trades, sizes or recommends.

Values are REAL, measured 2026-09-07 from Yahoo's chart API, recorded so a guard test
never depends on a third party being up.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core.market_daily import (ASSETS, EXTRACT_PATH, INDICATORS,  # noqa: E402
                               MOMENTUM_DAYS, UNITS, is_registered, last_close,
                               momentum_sign, parse_chart, registration_entry)

# measured 2026-09-07; last complete session was Friday 2026-09-04
REAL_LAST = {"SPY": ("2026-09-04", 770.19), "GLD": ("2026-09-04", 406.77),
             "UUP": ("2026-09-04", 28.08)}
REAL_MOMENTUM = {"SPY": ("DOWN", -0.000187), "GLD": ("UP", 0.001170),
                 "UUP": ("UP", 0.000023)}


def _payload(prices, start=dt.date(2026, 6, 8), adj=None):
    """A chart payload in the real shape: epoch at 13:30 UTC (the OPEN), adjclose."""
    ts, days = [], []
    d = start
    while len(ts) < len(prices):
        if d.weekday() < 5:
            ts.append(int(dt.datetime(d.year, d.month, d.day, 13, 30,
                                      tzinfo=dt.timezone.utc).timestamp()))
            days.append(d)
        d += dt.timedelta(days=1)
    return {"chart": {"result": [{
        "meta": {"symbol": "TEST", "regularMarketTime": ts[-1] + 23400},
        "timestamp": ts,
        "indicators": {"quote": [{"close": list(prices)}],
                       "adjclose": [{"adjclose": list(adj if adj is not None else prices)}]},
    }]}}


# ── the extract path ────────────────────────────────────────────────────────
def test_it_reads_ADJCLOSE_and_not_close():
    """THE TRAP THAT WOULD HAVE BITTEN SILENTLY. They are identical today for all three
    and diverge on every ex-dividend date, where the raw close drops by the dividend. A
    direction bet scored on raw close records a loss on a day the holder broke even."""
    p = _payload([100.0, 101.0, 102.0], adj=[90.0, 91.0, 92.0])
    assert [v for _, v in parse_chart(p)] == [90.0, 91.0, 92.0]


def test_only_the_DATE_is_taken_from_the_bar_never_the_time():
    """Bars carry 13:30 UTC = 09:30 New York, the market OPEN. meta.regularMarketTime
    is the close. Reading the bar timestamp as a close time is wrong by 6.5 hours."""
    p = _payload([1.0, 2.0], start=dt.date(2026, 9, 3))
    got = parse_chart(p)
    assert got[0][0] == dt.date(2026, 9, 3)
    assert all(isinstance(d, dt.date) and not isinstance(d, dt.datetime)
               for d, _ in got)


def test_a_bar_with_no_close_is_skipped_not_read_as_zero():
    p = _payload([100.0, 101.0, 102.0])
    p["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][1] = None
    assert [v for _, v in parse_chart(p)] == [100.0, 102.0]


def test_the_extract_path_and_units_are_recorded():
    assert "adjclose" in EXTRACT_PATH and "MARKET OPEN" in EXTRACT_PATH
    assert "dividend-adjusted" in UNITS


# ── the momentum baseline ───────────────────────────────────────────────────
def test_momentum_uses_TRADING_days_not_calendar_days():
    """Observed gaps between bars are 1, 3 and 4 days. 20 trading days spans about 28
    calendar days; a calendar window would use a different number of returns."""
    p = _payload([100.0 + i for i in range(30)])
    m = momentum_sign(parse_chart(p), days=20)
    assert m["n_returns"] == 20
    span = (dt.date.fromisoformat(m["to_date"]) - dt.date.fromisoformat(m["from_date"])).days
    assert span > 20, f"20 trading days spanned only {span} calendar days"


def test_momentum_sign_is_up_for_a_rising_series_and_down_for_a_falling_one():
    up = momentum_sign(parse_chart(_payload([100.0 + i for i in range(25)])))
    dn = momentum_sign(parse_chart(_payload([100.0 - i for i in range(25)])))
    assert up["sign"] == "UP" and up["mean_daily_return"] > 0
    assert dn["sign"] == "DOWN" and dn["mean_daily_return"] < 0


def test_too_few_bars_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="need 21 bars"):
        momentum_sign(parse_chart(_payload([100.0] * 10)))


def test_the_recorded_live_momentum_matches_what_was_registered():
    for s in ASSETS:
        sign, mean = REAL_MOMENTUM[s]
        assert sign == ("UP" if mean > 0 else "DOWN")


# ── registration ────────────────────────────────────────────────────────────
def test_every_asset_has_its_own_indicator_name():
    assert set(INDICATORS) == set(ASSETS)
    assert len(set(INDICATORS.values())) == 3
    assert INDICATORS["SPY"] == "MARKET_SPY_CLOSE"


def test_the_registration_entry_ends_in_the_latest_close():
    e = registration_entry({"SPY": [1.0, 2.0, 770.19]})
    assert e["MARKET_SPY_CLOSE"][-1] == 770.19


def test_the_registration_IS_live_for_all_three():
    """Flipped in the commit that registers them."""
    import evaluator
    live = json.loads(Path(evaluator.TRENDS_PATH).read_text(encoding="utf-8"))
    for s in ASSETS:
        assert INDICATORS[s] in live, f"{INDICATORS[s]} did not land"
        assert live[INDICATORS[s]][-1] == pytest.approx(REAL_LAST[s][1])
    assert is_registered() is True


def test_the_gate_ADMITS_each_asset_with_the_REAL_cadence_check():
    from core.proposal_intake import judge
    for s in ASSETS:
        v = judge({"indicator": INDICATORS[s], "expected_delta": 1.0,
                   "deadline": (dt.date.today() + dt.timedelta(days=1)).isoformat()},
                  scale_check=lambda i, d: (None, "injected"))
        assert v["verdict"] == "ADMITTED", (s, v)


def test_ground_truth_returns_the_last_close():
    import evaluator
    for s in ASSETS:
        v, trail = evaluator.ground_truth(INDICATORS[s])
        assert v == pytest.approx(REAL_LAST[s][1]), (s, v, trail)


# ── prediction only ─────────────────────────────────────────────────────────
def test_nothing_here_trades():
    """§VI. A module that reads prices must not grow an order path by accident."""
    src = (REPO / "core" / "market_daily.py").read_text(encoding="utf-8").lower()
    for word in ("order", "buy(", "sell(", "position", "broker", "alpaca", "api_key"):
        assert word not in src, f"{word!r} appears in a prediction-only module"
