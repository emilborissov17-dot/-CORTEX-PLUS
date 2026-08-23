#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_norms.py — UNUSUAL FOR THIS MACHINE, NOT THE BIGGEST PERCENTAGE.

Every path is explicit. cockpit/norms.py is a writer and, by the rule in
test/test_cockpit.py, has no default path on any function that writes.

    venv/Scripts/python.exe -m pytest test/test_norms.py -v
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from cockpit import norms as nm  # noqa: E402


def _probe(**values):
    return {"groups": {"X": [{"key": k, "value": v, "unit": "",
                              "available": True, "disabled": False}
                             for k, v in values.items()]}}


@pytest.fixture
def store(tmp_path):
    return tmp_path / "somatic_history.jsonl"


def test_a_writer_here_has_no_default_path():
    with pytest.raises(TypeError):
        nm.record(_probe(a=1.0))            # noqa: E1120 — that is the point


def test_an_unavailable_reading_is_not_stored_as_zero(store):
    probe = {"groups": {"X": [
        {"key": "gpu_temp_c", "value": None, "available": False},
        {"key": "cpu_percent", "value": 12.0, "available": True},
    ]}}
    nm.record(probe, store)
    hist = nm.history(store)
    assert "gpu_temp_c" not in hist, (
        "'could not read the GPU' must not become 'the GPU read 0'")
    assert hist["cpu_percent"] == [12.0]


def test_a_sensor_below_min_samples_falls_back_and_says_so(store):
    for i in range(nm.MIN_SAMPLES - 1):
        nm.record(_probe(cpu_percent=20.0 + i % 3), store, ts="t{}".format(i))
    row = nm.rank([{"key": "cpu_percent", "value": 90.0}], nm.history(store),
                  {"cpu_percent": 20.0}, top=1)[0]
    assert row["rule"] == nm.BY_FIXED
    assert str(nm.MIN_SAMPLES - 1) in row["why"]


def test_at_min_samples_the_norm_takes_over(store):
    for i in range(nm.MIN_SAMPLES):
        nm.record(_probe(cpu_percent=20.0 + i % 3), store, ts="t{}".format(i))
    row = nm.rank([{"key": "cpu_percent", "value": 90.0}], nm.history(store),
                  {"cpu_percent": 20.0}, top=1)[0]
    assert row["rule"] == nm.BY_HISTORY
    assert row["typical"] == pytest.approx(21.0, abs=1.0)


def test_the_noisy_sensor_stops_winning(store):
    """The whole point. idle_seconds swings wildly; cpu_percent does not."""
    for i in range(60):
        nm.record(_probe(idle_seconds=float(i * 7 % 300),
                         cpu_percent=20.0 + (i % 3)), store, ts="t{}".format(i))
    hist = nm.history(store)
    now = [{"key": "idle_seconds", "value": 290.0},
           {"key": "cpu_percent", "value": 44.0}]
    prev = {"idle_seconds": 4.0, "cpu_percent": 43.0}

    # Under the flat rule idle_seconds moved 7150% and cpu_percent 2%.
    fixed_top = max(now, key=lambda r: abs(r["value"] - prev[r["key"]])
                    / prev[r["key"]])
    assert fixed_top["key"] == "idle_seconds"

    # Under its own history, cpu_percent is the unusual one.
    assert nm.rank(now, hist, prev, top=1)[0]["key"] == "cpu_percent"


def test_one_outlier_does_not_hide_the_next_one(store):
    """Mean and stdev would; median and MAD do not."""
    for i in range(60):
        nm.record(_probe(gpu_power_w=5.0), store, ts="t{}".format(i))
    nm.record(_probe(gpu_power_w=90.0), store, ts="spike")
    hist = nm.history(store)
    n = nm.norm_for(hist["gpu_power_w"])
    assert n["typical"] == 5.0, "one spike moved the typical value"
    assert nm.deviation(90.0, n) >= nm.FROZEN_SPREAD_DEVIATION


def test_a_frozen_sensor_that_wobbles_in_its_last_decimal_is_not_news(store):
    for i in range(40):
        nm.record(_probe(swap_used_gb=4.11), store, ts="t{}".format(i))
    n = nm.norm_for(nm.history(store)["swap_used_gb"])
    assert n["spread"] == 0
    assert nm.deviation(4.12, n) == 0.0, "rounding on a flat sensor is not news"
    assert nm.deviation(6.0, n) > 1.0, "a real jump on a flat sensor is news"


def test_a_counter_is_judged_on_its_increment_not_its_level(store):
    """disk_read_mb only goes up: its median is a number it will never see again."""
    for i in range(60):
        nm.record(_probe(disk_read_mb=100000.0 + i * 10.0), store,
                  ts="t{}".format(i))
    hist = nm.history(store)
    assert nm.is_counter(hist["disk_read_mb"])
    steady = nm.rank([{"key": "disk_read_mb", "value": 100600.0}], hist,
                     {"disk_read_mb": 100590.0}, top=1)[0]
    assert steady["counter"] is True
    assert steady["score"] < 1.0, "a counter ticking normally is not unusual"
    burst = nm.rank([{"key": "disk_read_mb", "value": 105000.0}], hist,
                    {"disk_read_mb": 100590.0}, top=1)[0]
    assert burst["score"] > steady["score"] * 5


def test_a_flat_series_is_not_a_counter(store):
    for i in range(40):
        nm.record(_probe(k=3.0), store, ts="t{}".format(i))
    assert not nm.is_counter(nm.history(store)["k"])


def test_every_ranked_row_names_the_rule_that_judged_it(store):
    for i in range(40):
        nm.record(_probe(old=20.0 + i % 4), store, ts="t{}".format(i))
    rows = nm.rank([{"key": "old", "value": 30.0},
                    {"key": "brand_new", "value": 9.0}],
                   nm.history(store), {"old": 21.0, "brand_new": 1.0}, top=2)
    assert {r["rule"] for r in rows} == {nm.BY_HISTORY, nm.BY_FIXED}
    assert rows[0]["rule"] == nm.BY_HISTORY, (
        "the two rules are not one scale; the judged-by-history block comes "
        "first rather than being interleaved with scores of another quantity")


def test_the_file_is_capped(store):
    for i in range(nm.MAX_ROWS + nm.TRIM_SLACK + 5):
        nm.record(_probe(k=1.0), store, ts="t{}".format(i))
    kept = len(store.read_text(encoding="utf-8").splitlines())
    assert nm.MAX_ROWS <= kept <= nm.MAX_ROWS + nm.TRIM_SLACK


def test_last_two_reads_back_the_newest_probes(store):
    nm.record(_probe(k=1.0), store, ts="t1")
    nm.record(_probe(k=2.0), store, ts="t2")
    newest, prev = nm.last_two(store)
    assert newest["k"] == 2.0 and prev["k"] == 1.0


def test_the_probe_endpoint_records_and_reports(tmp_path, monkeypatch):
    from cockpit import server as srv
    store = tmp_path / "somatic_history.jsonl"
    monkeypatch.setattr(srv, "HISTORY_PATH", store)
    client = srv.app.test_client()
    blob = client.get("/api/somatic").get_json()
    assert store.exists(), "/api/somatic probed and threw the readings away again"
    assert "unusual" in blob and "rule_meaning" in blob["unusual"]


def test_the_state_handed_to_the_model_says_what_is_unusual():
    from cockpit import reflex as rx
    state = rx.current_state(
        pathlib.Path("does-not-exist.jsonl"), {"glyph": "Δ7"},
        unusual={"rows": [{"key": "ram_percent", "value": 91.0, "unit": "%",
                           "rule": "history", "score": 4.2,
                           "why": "91.0 vs a typical 54.0, 4.2 spreads out"}],
                 "rule_meaning": nm.RULE_MEANING})
    rendered = rx.render_state(state)
    assert "WHAT IS UNUSUAL FOR THIS MACHINE" in rendered
    assert "judged by the history rule" in rendered
    assert "4.2 spreads out" in rendered
