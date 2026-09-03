# -*- coding: utf-8 -*-
"""
core/consolidation.py — the system reads its own memory (H, 3 Sep 2026).

The daily cycle sees one reading per metric and asks whether it moved; it cannot see
a series. Over 30 days a metric can drift monotonically while every night's delta
sits inside the noise, and no nightly step will ever raise it. Consolidation reads
the sealed archive as a time series and asks what has been moving all along.

No model, no network, no subprocess: the output is a falsifiable interval, and an
interval is worth exactly what the procedure behind it is inspectable.

Everything here is tmp_path. No live archive is written.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import core.consolidation as CO        # noqa: E402


def _cycle(root: Path, n: int, when: date, signals: list):
    d = root / f"cycle_{n:06d}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "signals.json").write_text(json.dumps({
        "cycle_id": f"c{n}",
        "timestamp": datetime(when.year, when.month, when.day,
                              tzinfo=timezone.utc).isoformat(),
        "count": len(signals), "signals": signals}), encoding="utf-8")
    return d


def _drifting(root: Path, days: int, start: float, step: float, noise=(0.0,)):
    """A metric that creeps by `step` a day. Whether that is invisible night to
    night depends on `noise`: the drift must be small against the night-to-night
    step, or the daily cycle would already have caught it."""
    today = date(2026, 9, 3)
    for i in range(days):
        when = today - timedelta(days=days - 1 - i)
        val = start + step * i + noise[i % len(noise)]
        _cycle(root, i + 1, when, [{"metric": "m", "value": round(val, 6),
                                    "domain": "ENERGY_REVIEW", "source": "metrics"}])
    return today


# ── H: consolidation ──────────────────────────────────────────────────────────

def test_it_uses_no_model_no_network_no_subprocess():
    """The central design promise, checked against the AST rather than the text —
    this module's own docstring says the words while promising not to use them."""
    assert CO.imported_forbidden() == set()


def test_a_slow_drift_no_single_night_could_see_becomes_a_hypothesis(tmp_path):
    # 0.02/day under +/-0.5 night-to-night noise: each night's move is swamped,
    # 30 nights of it is not. A drift of 0.4/day with 0.15 noise would be visible
    # nightly and is correctly refused as the daily cycle's job, not this module's.
    root = tmp_path / "archive"
    today = _drifting(root, days=30, start=100.0, step=0.02,
                      noise=(0.5, -0.5))

    rec = CO.run(write=False, archive=root, today=today)

    assert rec["cycles_read"] == 30
    assert rec["emitted"] == 1
    h = rec["hypotheses"][0]
    assert h["axis"] == "ENERGY_REVIEW" and h["metric"] == "m"
    assert h["direction"] == "up"
    assert h["horizon_days"] in CO.HORIZONS
    assert h["lo"] < h["predicted"] < h["hi"], "a point without an interval"
    assert h["due_on"] > h["made_on"]
    assert h["method"] == "linear_drift"


def test_a_constant_series_yields_nothing_and_says_which_reason(tmp_path):
    """46 of the 48 live series are perfectly constant — World Bank annual figures
    do not move nightly. Reporting that as a vague 'nothing found' would hide the
    reason consolidation has so little to work with."""
    root = tmp_path / "archive"
    today = _drifting(root, days=30, start=50.0, step=0.0)

    rec = CO.run(write=False, archive=root, today=today)

    assert rec["emitted"] == 0
    assert rec["rejected"]["constant_series"] == 1


def test_a_series_a_nightly_step_could_already_see_is_left_to_the_cycle(tmp_path):
    """Consolidation must not duplicate the daily cycle. If the per-night move is
    large relative to the night-to-night step, the cycle can catch it."""
    # noise is required: a PERFECTLY linear series has zero residual, and sigma<=0
    # is refused as constant_series before the speed test is ever reached.
    root = tmp_path / "archive"
    today = _drifting(root, days=30, start=100.0, step=5.0, noise=(0.0, 0.2, -0.2))

    rec = CO.run(write=False, archive=root, today=today)

    assert rec["emitted"] == 0
    assert rec["rejected"]["fast_enough_for_a_nightly_step"] == 1


def test_too_short_a_history_is_not_a_trend(tmp_path):
    root = tmp_path / "archive"
    today = _drifting(root, days=4, start=100.0, step=0.4)
    rec = CO.run(write=False, archive=root, today=today)
    assert rec["emitted"] == 0
    assert rec["rejected"]["too_few_points"] == 1


def test_two_cycles_on_one_day_do_not_get_double_leverage(tmp_path):
    """A catch-up night can seal two cycles for one date. Two readings of the same
    day are not two observations of a trend."""
    root = tmp_path / "archive"
    when = date(2026, 9, 1)
    _cycle(root, 1, when, [{"metric": "m", "value": 1.0, "domain": "A"}])
    _cycle(root, 2, when, [{"metric": "m", "value": 2.0, "domain": "A"}])
    series = CO.build_series(CO.read_cycles(30, root, date(2026, 9, 3)))
    assert len(series[("A", "m")]) == 1


def test_the_artifact_is_written_even_on_a_night_with_nothing_to_say(tmp_path):
    """A module that leaves a trace only when it has news cannot be told from one
    that has stopped running."""
    root = tmp_path / "archive"
    today = _drifting(root, days=30, start=50.0, step=0.0)
    q, latest = tmp_path / "q.json", tmp_path / "latest.json"

    rec = CO.run(write=True, archive=root, today=today, queue=q, latest=latest)

    assert rec["emitted"] == 0
    assert latest.is_file() and q.is_file()
    assert json.loads(latest.read_text(encoding="utf-8"))["cycles_read"] == 30


def test_it_reads_the_live_archive():
    """Against the real cortex_memory/ — proof it ran here, not in a fixture."""
    rec = CO.run(write=False)
    assert rec["cycles_read"] >= 20, rec["cycles_read"]
    assert rec["uses_model"] is False


