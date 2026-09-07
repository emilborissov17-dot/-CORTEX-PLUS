# -*- coding: utf-8 -*-
"""
PRE-FLIGHT D2 — the baseline is computed AT BET TIME, not read from a sealed file.

PREDICTION ONLY (§VI); nothing here trades, and no test here touches the network: the
price fetcher is injected.

It used to be read from BASELINE_2026-09-07_markets.json, whose SPY last close is
2026-09-04. Every bet after the 7th would have been graded against a stale close and
compared to a momentum sign measured over a window that had already moved. The baseline
is the null the bet must beat, and a null from last week is not a null.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (ASSETS, BaselineUnavailable,  # noqa: E402
                              compute_baseline)

STALE = "2026-09-04"


def _bars(last_day: date, n: int = 30, step: float = 1.0):
    """n daily bars ending on `last_day`, rising by `step` a day."""
    return [(last_day - timedelta(days=n - 1 - i), 100.0 + i * step) for i in range(n)]


def test_the_baseline_reports_the_actual_latest_close_not_a_hardcoded_date():
    """THE BLOCKER, stated as a test. to_date must be whatever the prices say."""
    today = date.today()
    b = compute_baseline(fetcher=lambda sym: _bars(today))
    for sym in ASSETS:
        assert b["last_close"][sym]["date"] == today.isoformat()
        assert b["baseline"][sym]["to_date"] == today.isoformat()
        assert b["baseline"][sym]["to_date"] != STALE


def test_it_moves_when_the_prices_move():
    a = compute_baseline(fetcher=lambda s: _bars(date(2026, 9, 4)))
    c = compute_baseline(fetcher=lambda s: _bars(date(2026, 9, 11)))
    assert a["baseline"]["SPY"]["to_date"] != c["baseline"]["SPY"]["to_date"]
    assert a["last_close"]["SPY"]["date"] != c["last_close"]["SPY"]["date"]


def test_the_momentum_sign_is_computed_not_copied():
    up = compute_baseline(fetcher=lambda s: _bars(date.today(), step=+1.0))
    down = compute_baseline(fetcher=lambda s: _bars(date.today(), step=-1.0))
    assert up["baseline"]["SPY"]["sign"] == "UP"
    assert down["baseline"]["SPY"]["sign"] == "DOWN"
    assert up["baseline"]["SPY"]["n_returns"] == 20


def test_it_declares_that_it_was_computed_at_bet_time():
    b = compute_baseline(fetcher=lambda s: _bars(date.today()))
    assert b["computed_at_bet_time"] is True
    assert b["ts"]


def test_a_fetch_failure_refuses_and_does_not_fall_back_to_the_stale_file():
    """THE FIX MUST NOT REINSTATE THE BUG UNDER A DIFFERENT NAME. Falling back to the
    sealed file on a network failure is exactly what this replaces, and a stale null is
    worse than no bet because it looks identical to a fresh one in the record."""
    def boom(sym):
        raise ConnectionError("yahoo unreachable")

    with pytest.raises(BaselineUnavailable, match="REFUSED"):
        compute_baseline(fetcher=boom)


def test_the_refusal_names_the_asset_and_the_cause():
    def boom(sym):
        raise ValueError("no chart.result")

    with pytest.raises(BaselineUnavailable) as e:
        compute_baseline(fetcher=boom)
    assert "SPY" in str(e.value) and "no chart.result" in str(e.value)


def test_too_few_bars_refuses_rather_than_shortening_the_window():
    """20 trading days or nothing. A baseline over 8 returns is a different statistic
    wearing the same name."""
    with pytest.raises(BaselineUnavailable):
        compute_baseline(fetcher=lambda s: _bars(date.today(), n=8))


def test_the_hardcoded_baseline_file_is_no_longer_read():
    import ast
    import inspect

    import tools.market_bet as mb

    class _Blank(ast.NodeTransformer):
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return None
            return node

    tree = _Blank().visit(ast.parse(inspect.getsource(mb.main).lstrip()))
    src = ast.unparse(tree)
    assert "BASELINE_2026-09-07" not in src
    assert "compute_baseline" in src


def test_the_stale_file_still_exists_and_is_simply_unused():
    """Not deleted — it is the record of what R48 was actually graded against."""
    from tools.market_bet import LEDGER
    assert (LEDGER / "BASELINE_2026-09-07_markets.json").exists()


def test_a_dry_run_may_stage_the_baseline_so_tests_never_fetch():
    import inspect

    import tools.market_bet as mb
    src = inspect.getsource(mb.main)
    assert '"baseline" in dry' in src, "the dry run cannot stage a baseline"
