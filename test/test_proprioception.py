#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_proprioception.py — A STALL IS FELT, A STEADY TICK IS NOT.

The two the command names:
  * an artificially stalled tick produces a signal proportional to the stall;
  * an unstalled run is silent after warmup.

Plus the tagging question, which this file settles against the repo's existing
taxonomy rather than against the brief.

    venv/Scripts/python.exe -m pytest test/test_proprioception.py -v
"""
from __future__ import annotations

import pathlib
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import event_bus as eb          # noqa: E402
from core import proprioception as pp     # noqa: E402
from core import receptors as rc          # noqa: E402


@pytest.fixture
def meter():
    bank = rc.ReceptorBank(bus=eb.EventBus(), seed_path="_no_seed_")
    return pp.TickMeter(expected_ms=15.0, bank=bank, calibration_ticks=5)


def _warm(m, ms=15.0, n=5):
    for _ in range(n):
        m.record(ms)
    assert m.receptor.phase() == rc.PHASE_LIVE
    return m


# ── silence ─────────────────────────────────────────────────────────────────

def test_an_unstalled_run_is_silent_after_warmup(meter):
    _warm(meter)
    for _ in range(100):
        meter.record(15.0)
    assert meter.receptor.emitted == 0


def test_jitter_under_eps_stays_silent(meter):
    """eps is 5 ms, from time.sleep() jitter on Windows.

    Amplitude 2, not 4, and the difference is worth knowing: against an
    ADAPTING baseline an alternating jitter of amplitude A produces a residual
    LARGER than A, because the baseline chases each swing and then meets the
    next one coming the other way. At alpha 0.3 a +/-4 ms square wave settles
    at a residual of about 5.2 ms and trips a 5 ms eps. Real sleep jitter is
    not a square wave, but the noise floor for an adaptive channel is not
    simply the amplitude either."""
    _warm(meter)
    for i in range(50):
        meter.record(15.0 + (2.0 if i % 2 else -2.0))
    assert meter.receptor.emitted == 0
    assert meter.receptor.suppressed_quiet >= 50


def test_a_square_wave_at_the_eps_amplitude_does_trip_it(meter):
    """The other half of the finding above, pinned so it is not a surprise."""
    _warm(meter)
    for i in range(20):
        meter.record(15.0 + (4.0 if i % 2 else -4.0))
    assert meter.receptor.emitted > 0


def test_it_is_silent_while_calibrating_even_on_a_stall(meter):
    ev = meter.record(500.0)
    assert ev is None
    assert meter.receptor.phase() == rc.PHASE_CALIBRATING


# ── the stall ───────────────────────────────────────────────────────────────

def test_a_stall_emits_a_signal_proportional_to_it(meter):
    _warm(meter)
    ev = meter.record(115.0)
    assert ev is not None
    assert abs(ev.meta["signal"] - 100.0) < 2.0, ev.meta["signal"]


def test_a_bigger_stall_is_a_bigger_signal(meter):
    small = pp.TickMeter(expected_ms=15.0, calibration_ticks=5,
                         bank=rc.ReceptorBank(bus=eb.EventBus()))
    big = pp.TickMeter(expected_ms=15.0, calibration_ticks=5,
                       bank=rc.ReceptorBank(bus=eb.EventBus()))
    _warm(small); _warm(big)
    a = small.record(65.0).meta["signal"]        # +50 ms
    b = big.record(215.0).meta["signal"]         # +200 ms
    assert b > a * 3.5, (a, b)


def test_the_signal_scales_linearly_with_the_stall():
    got = []
    for stall in (50.0, 100.0, 200.0, 400.0):
        m = pp.TickMeter(expected_ms=15.0, calibration_ticks=5,
                         bank=rc.ReceptorBank(bus=eb.EventBus()))
        _warm(m)
        got.append(m.record(15.0 + stall).meta["signal"])
    for i in range(1, len(got)):
        assert abs(got[i] / got[i - 1] - 2.0) < 0.1, got


def test_a_real_stall_measured_with_a_real_sleep(meter):
    """Not a hand-fed number: an actual wall-clock stall through the context
    manager, which is how it will be used."""
    for _ in range(5):
        with meter:
            time.sleep(0.005)
    before = meter.receptor.emitted
    with meter:
        time.sleep(0.120)
    assert meter.receptor.emitted == before + 1
    assert meter.last_ms > 100.0


def test_the_event_carries_the_expected_duration_and_the_stretch(meter):
    _warm(meter)
    ev = meter.record(150.0)
    assert ev.meta["expected_ms"] == 15.0
    assert abs(ev.meta["stretch_ratio"] - 10.0) < 0.01
    assert ev.meta["sensor"] == "tick_latency_ms"
    assert ev.meta["unit"] == "ms"


def test_after_a_sustained_slowdown_it_adapts_and_goes_quiet(meter):
    """It senses CHANGE. A box that is permanently slower is the new normal,
    and channel R says so by falling silent — which is exactly why a set-point
    would be needed to say 'still too slow'."""
    _warm(meter)
    assert meter.record(115.0) is not None
    for _ in range(60):
        meter.record(115.0)
    assert meter.record(115.0) is None


# ── the instrument ──────────────────────────────────────────────────────────

def test_perf_counter_is_cheap_enough_to_sit_on_the_hot_path():
    ns = pp.measure_instrument_cost(20000)
    assert ns < 1000, "{} ns per call is too expensive for every tick".format(ns)


def test_the_meter_uses_perf_counter_and_not_a_wall_clock():
    src = (REPO / "core" / "proprioception.py").read_text(encoding="utf-8")
    body = src.split("class TickMeter", 1)[1]
    assert "perf_counter" in body
    assert "time.time()" not in body, "a wall clock can step backwards"


def test_it_makes_no_syscall_and_starts_no_thread():
    import threading
    before = threading.active_count()
    m = pp.TickMeter(bank=rc.ReceptorBank(bus=eb.EventBus()))
    for _ in range(1000):
        m.record(15.0)
    assert threading.active_count() == before


# ── the tagging, settled against the repo's own taxonomy ────────────────────

def test_it_is_tagged_reflexivity_zero_because_no_model_touches_it():
    """The brief asked for reflexivity 1. This repo's ladder
    (cockpit/timeline.py:79) counts MODEL PASSES, and 1 means 'one model pass
    over a state the system just read'. Nothing interprets a tick duration."""
    from cockpit import timeline as tl
    assert pp.REFLEXIVITY == tl.MEASUREMENT == 0
    assert tl.REFLEXIVITY_MEANING[0] == "a measurement; no model touched it"
    assert "model pass" in tl.REFLEXIVITY_MEANING[1]


def test_the_self_directed_distinction_gets_its_own_field():
    """The brief's real point survives, on a field that does not already mean
    something else."""
    assert pp.DIRECTED == pp.DIRECTED_SELF == "self"
    m = pp.TickMeter(bank=rc.ReceptorBank(bus=eb.EventBus()),
                     calibration_ticks=2)
    m.record(15.0); m.record(15.0)
    ev = m.record(500.0)
    assert ev.meta["directed"] == "self"
    assert ev.meta["reflexivity"] == 0


def test_the_header_explains_the_departure_from_the_brief():
    src = (REPO / "core" / "proprioception.py").read_text(encoding="utf-8")
    head = src.split('"""')[1]
    assert "reflexivity" in head and "timeline.py" in head


# ── it is on the bus ────────────────────────────────────────────────────────

def test_it_publishes_on_the_bus_as_a_receptor(meter):
    sub = meter.bank.bus.subscribe(pp.TOPIC, "a_panel")
    _warm(meter)
    meter.record(115.0)
    got = sub.drain()
    assert len(got) == 1
    assert got[0].topic == "receptor.tick_latency_ms"
    assert got[0].channel == eb.CHANNEL_R


def test_it_uses_the_tables_alpha_and_eps(meter):
    from cockpit import norms as nm
    assert meter.receptor.alpha == nm.RECEPTOR_TABLE["tick_latency_ms"]["alpha"]
    assert meter.receptor.eps == nm.RECEPTOR_TABLE["tick_latency_ms"]["eps"]
    assert "time.sleep()" in meter.receptor.eps_source


def test_a_subscriber_cannot_probe_a_sensor_from_this_topic(meter):
    from core import homeostasis as h
    sub = meter.bank.bus.subscribe(pp.TOPIC, "greedy")
    _warm(meter)
    meter.record(115.0)
    with pytest.raises(eb.SensorProbeInSubscriber):
        sub.consume(lambda e: h.read_ram_free_mb())


def test_the_selftest_passes():
    assert pp._selftest() == 0
