#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_receptors.py — THE RAMP TEST IS THE WHOLE POINT.

The command names three:
  * a constant input goes silent after adaptation;
  * a step change emits;
  * a ramp emits nothing on R and crosses S on schedule.

The third is why two channels exist, and it turned out to be sharper than the
brief: the residual on a ramp settles at d/alpha, so R has TWO failure modes,
silence and a permanent unchanging alarm, and neither says "getting closer".
Both are tested.

    venv/Scripts/python.exe -m pytest test/test_receptors.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import event_bus as eb        # noqa: E402
from core import receptors as rc        # noqa: E402


@pytest.fixture
def bank(tmp_path):
    return rc.ReceptorBank(bus=eb.EventBus(), seed_path=tmp_path / "seed.json")


def _live(bank, key="t", alpha=0.2, eps=1.0, value=100.0, ticks=5):
    r = bank.add_receptor(key, alpha=alpha, eps=eps, calibration_ticks=ticks)
    for _ in range(ticks):
        r.feed(value)
    assert r.phase() == rc.PHASE_LIVE
    return r


# ── channel R ───────────────────────────────────────────────────────────────

def test_a_constant_input_goes_silent_after_adaptation(bank):
    r = _live(bank)
    for _ in range(50):
        r.feed(100.0)
    assert r.emitted == 0
    assert r.suppressed_quiet > 0, "silence must be counted, not merely absent"


def test_a_step_change_emits(bank):
    r = _live(bank)
    ev = r.feed(150.0)
    assert ev is not None
    assert ev.channel == eb.CHANNEL_R
    assert ev.topic == "receptor.t"
    assert abs(ev.meta["signal"] - 50.0) < 1e-9


def test_a_wobble_inside_eps_does_not_emit(bank):
    r = _live(bank, eps=5.0)
    for v in (100.5, 99.5, 101.0, 99.0, 100.0):
        assert r.feed(v) is None
    assert r.emitted == 0


def test_after_a_step_the_baseline_follows_and_it_goes_quiet_again(bank):
    r = _live(bank, alpha=0.5, eps=1.0)
    assert r.feed(150.0) is not None
    for _ in range(40):
        r.feed(150.0)
    assert r.feed(150.0) is None, "the receptor never re-adapted"


def test_the_event_carries_base_eps_and_alpha(bank):
    r = _live(bank)
    ev = r.feed(150.0)
    assert set(ev.meta) >= {"signal", "base", "eps", "alpha", "key"}


def test_an_unreadable_value_is_ignored_not_guessed(bank):
    r = _live(bank)
    assert r.feed(None) is None
    assert r.feed("not a number") is None
    assert r.last == 100.0


# ═══ THE RAMP — why there are two channels ══════════════════════════════════

def test_a_ramp_under_d_over_alpha_emits_nothing_on_R_and_S_fires(bank):
    """The headline, AMENDED 24 Aug 2026 by the anchor (COMMAND 28 part 1).

    The RESIDUAL is still silent for ever on this ramp - d/alpha = 1/0.2 = 5,
    under eps = 6 - and that is still the reason channel S exists. What changed
    is that the receptor is no longer silent overall: the anchor fires every
    band/d ticks. The assertion below therefore pins emitted_by_residual, which
    is the quantity the original claim was really about.

    anchor_k is set to infinity here so the ramp's own crossings of S are read
    without anchor lines interleaved; test/test_anchor.py holds the anchor."""
    r = bank.add_receptor("disk", alpha=0.2, eps=6.0, calibration_ticks=3,
                          anchor_k=1e18)
    s = bank.add_setpoint("disk", {"notice": 28, "action": 15, "gate": 5}, "%")

    value, crossings = 100.0, []
    for _ in range(120):
        value -= 1.0
        out = bank.feed("disk", value)
        if out["S"] is not None:
            crossings.append((round(value), out["S"].meta["level"]))

    assert r.emitted_by_residual == 0, "the residual fired on a slow ramp"
    assert r.emitted == 0, "with the anchor disabled R should be wholly silent"
    assert crossings == [(28, "notice"), (15, "action"), (5, "gate")]
    assert s.last_level == "gate"


def test_a_ramp_over_d_over_alpha_emits_on_every_tick_which_is_no_better(bank):
    """The other regime. A permanent alarm that never changes is
    indistinguishable from a stuck sensor."""
    r = bank.add_receptor("d2", alpha=0.2, eps=2.0, calibration_ticks=3)
    v = 1000.0
    for _ in range(60):
        v -= 1.0
        r.feed(v)
    assert r.emitted >= 50
    sig = abs(r.last_signal)
    assert abs(sig - 1.0 / 0.2) < 0.05, sig


def test_the_steady_state_residual_is_d_over_alpha(bank):
    """The number the design rests on, measured rather than asserted."""
    for alpha in (0.5, 0.3, 0.2, 0.05):
        for d in (1.0, 0.01):
            r = rc.Receptor("x", alpha=alpha, eps=1e18, bus=eb.EventBus(),
                            calibration_ticks=1)
            x = 1000.0
            for _ in range(400):
                x -= d
                r.feed(x)
            assert abs(abs(r.last_signal) - d / alpha) < max(1e-6, d / alpha * 0.02), \
                (alpha, d, r.last_signal, d / alpha)


def test_a_slower_alpha_does_not_rescue_the_ramp(bank):
    """alpha only moves the boundary between the two failures."""
    silent = rc.Receptor("a", alpha=0.02, eps=100.0, bus=eb.EventBus(),
                         calibration_ticks=1)
    loud = rc.Receptor("b", alpha=0.02, eps=1.0, bus=eb.EventBus(),
                       calibration_ticks=1)
    x = 1000.0
    for _ in range(300):
        x -= 1.0
        silent.feed(x)
        loud.feed(x)
    assert silent.emitted == 0
    assert loud.emitted > 250
    assert not (0 < silent.emitted < 250), "there is no middle regime"


# ── channel S never adapts ──────────────────────────────────────────────────

def test_S_emits_only_on_a_level_change(bank):
    s = bank.add_setpoint("d", {"notice": 28, "action": 15, "gate": 5}, "%")
    assert s.feed(50.0) is None                 # clear -> clear
    assert s.feed(27.0) is not None             # -> notice
    assert s.feed(20.0) is None                 # still notice
    assert s.feed(14.0) is not None             # -> action


def test_S_has_no_baseline_and_no_eps(bank):
    s = bank.add_setpoint("d", {"notice": 28, "action": 15, "gate": 5})
    assert not hasattr(s, "base")
    assert not hasattr(s, "eps")
    assert s.stats()["adapts"] is False


def test_S_still_fires_after_a_thousand_ticks_at_the_same_level(bank):
    """An adaptive channel would have absorbed this. That is the point."""
    s = bank.add_setpoint("d", {"notice": 28, "action": 15, "gate": 5})
    s.feed(50.0)
    for _ in range(1000):
        s.feed(50.0)
    assert s.feed(4.0) is not None
    assert s.last_level == "gate"


def test_S_reads_the_signed_config(bank):
    live = rc.build(bus=eb.EventBus(), history={},
                    seed_path=REPO / "memory" / "_nope.json")
    assert set(live.setpoints) == {"ram_free", "disk_free_pct"}
    assert live.setpoints["disk_free_pct"].levels == {
        "notice": 28, "action": 15, "gate": 5}


def test_the_two_channels_are_separate_topics(bank):
    bank.add_receptor("ram_free", alpha=0.2, eps=1.0)
    bank.add_setpoint("ram_free", {"notice": 1200, "action": 900, "gate": 600})
    assert bank.receptors["ram_free"].topic == "receptor.ram_free"
    assert bank.setpoints["ram_free"].topic == "setpoint.ram_free"


# ── WARMUP, AND IT ADMITS ITSELF ────────────────────────────────────────────

def test_a_cold_start_calibrates_silently(bank):
    r = bank.add_receptor("t", alpha=0.2, eps=0.001, calibration_ticks=10)
    assert r.phase() == rc.PHASE_CALIBRATING
    for i in range(9):
        assert r.feed(100.0 + i * 10) is None, "it emitted while calibrating"
    assert r.emitted == 0
    assert r.suppressed_warmup == 9


def test_the_warmup_state_is_visible_not_hidden(bank):
    """A consumer must be able to tell 'silent because nothing happened' from
    'silent because warming up'."""
    r = bank.add_receptor("t", alpha=0.2, eps=1.0, calibration_ticks=5)
    r.feed(100.0)
    assert r.warming() is True
    assert r.phase() == rc.PHASE_CALIBRATING
    for _ in range(5):
        r.feed(100.0)
    assert r.warming() is False
    assert r.phase() == rc.PHASE_LIVE
    st = r.stats()
    assert st["phase"] == "live"
    assert "suppressed_warmup" in st and "suppressed_quiet" in st


def test_the_two_kinds_of_silence_are_counted_separately(bank):
    r = bank.add_receptor("t", alpha=0.2, eps=1.0, calibration_ticks=3)
    for _ in range(3):
        r.feed(100.0)
    for _ in range(4):
        r.feed(100.0)
    # 3 calibration ticks: the 1st sets the baseline and the 2nd is suppressed
    # as warmup; by the 3rd, ticks >= calibration_ticks and it is live. So 2
    # warmup and 5 quiet across the 7 feeds.
    assert r.suppressed_warmup == 2
    assert r.suppressed_quiet == 5


def test_a_seed_is_saved_and_loaded_as_the_baseline(tmp_path):
    seed = tmp_path / "seed.json"
    b1 = rc.ReceptorBank(bus=eb.EventBus(), seed_path=seed)
    r1 = b1.add_receptor("t", alpha=0.2, eps=1.0, calibration_ticks=3)
    for _ in range(10):
        r1.feed(500.0)
    assert b1.save_seed() is True
    assert seed.exists()

    b2 = rc.ReceptorBank(bus=eb.EventBus(), seed_path=seed)
    r2 = b2.add_receptor("t", alpha=0.2, eps=1.0)
    assert r2.seeded is True
    assert abs(r2.base - 500.0) < 1e-6, "the baseline did not survive"


def test_a_seeded_receptor_warms_by_time_not_by_ticks(tmp_path):
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps({"receptors": {"t": {"base": 500.0}}}),
                    encoding="utf-8")
    b = rc.ReceptorBank(bus=eb.EventBus(), seed_path=seed)
    r = b.add_receptor("t", alpha=0.2, eps=1.0, warmup_seconds=300.0)
    r.feed(500.0, now=1000.0)
    assert r.phase(now=1000.0) == rc.PHASE_WARMUP
    assert r.feed(900.0, now=1100.0) is None, "it emitted during warmup"
    assert r.phase(now=1400.0) == rc.PHASE_LIVE


def test_warmup_still_feeds_the_baseline(bank):
    """That is what warming up MEANS: the events are used, not emitted."""
    r = bank.add_receptor("t", alpha=0.5, eps=1.0, calibration_ticks=4)
    for _ in range(4):
        r.feed(100.0)
    for _ in range(4):
        r.feed(200.0)
    assert abs(r.base - 200.0) < 20.0, r.base


def test_a_missing_seed_file_is_a_cold_start_not_a_crash(tmp_path):
    b = rc.ReceptorBank(bus=eb.EventBus(), seed_path=tmp_path / "absent.json")
    r = b.add_receptor("t", alpha=0.2, eps=1.0)
    assert r.seeded is False
    assert r.phase() == rc.PHASE_CALIBRATING


# ── self-calibration when there is nothing to look up ───────────────────────

def test_a_receptor_with_no_constants_calibrates_itself(bank):
    r = bank.add_receptor("brand_new", alpha=0.2, eps=None,
                          calibration_ticks=20)
    assert r.eps is None
    assert r.phase() == rc.PHASE_CALIBRATING
    for i in range(20):
        r.feed(100.0 + (1.0 if i % 2 else -1.0))
    assert r.eps is not None and r.eps > 0
    assert "self-calibrated" in r.eps_source
    assert r.phase() == rc.PHASE_LIVE


def test_a_self_calibrated_receptor_then_behaves_normally(bank):
    r = bank.add_receptor("bn", alpha=0.2, eps=None, calibration_ticks=20)
    for i in range(20):
        r.feed(100.0 + (1.0 if i % 2 else -1.0))
    assert r.feed(100.0) is None
    assert r.feed(1000.0) is not None


# ── THE SOURCE CAP ──────────────────────────────────────────────────────────

def test_three_high_frequency_sources_and_no_more(bank):
    for i in range(rc.MAX_HIGH_FREQUENCY):
        bank.register_source("hi{}".format(i), rc.HIGH)
    with pytest.raises(rc.TooManySources) as e:
        bank.register_source("one_too_many", rc.HIGH)
    assert "cap is 3" in str(e.value)


def test_five_low_frequency_sources_and_no_more(bank):
    for i in range(rc.MAX_LOW_FREQUENCY):
        bank.register_source("lo{}".format(i), rc.LOW)
    with pytest.raises(rc.TooManySources):
        bank.register_source("six", rc.LOW)


def test_the_caps_are_independent(bank):
    for i in range(rc.MAX_HIGH_FREQUENCY):
        bank.register_source("hi{}".format(i), rc.HIGH)
    bank.register_source("lo", rc.LOW)      # must still be allowed
    assert bank.stats()["source_capacity"]["high"] == "3/3"
    assert bank.stats()["source_capacity"]["low"] == "1/5"


def test_eight_is_the_total(bank):
    assert rc.MAX_HIGH_FREQUENCY + rc.MAX_LOW_FREQUENCY == 8


def test_re_registering_the_same_source_is_not_a_new_one(bank):
    for _ in range(10):
        bank.register_source("net", rc.HIGH)
    assert bank.stats()["source_capacity"]["high"] == "1/3"


# ── one publisher per receptor, on the real bus ─────────────────────────────

def test_each_receptor_owns_its_topic(bank):
    bank.add_receptor("t", alpha=0.2, eps=1.0)
    assert bank.bus.publisher_of("receptor.t") == "receptor:t"
    with pytest.raises(eb.TopicOwned):
        bank.bus.register_publisher("receptor.t", "somebody_else")


def test_a_subscriber_sees_the_receptor_events(bank):
    sub = bank.bus.subscribe("receptor.t", "a_panel")
    r = _live(bank)
    r.feed(150.0)
    got = sub.drain()
    assert len(got) == 1 and got[0].value == 150.0


def test_constants_come_from_norms_with_measurement_first():
    from cockpit import norms as nm
    c = nm.receptor_constants("gpu_temp_c", [49.0 + (i % 3) for i in range(40)])
    assert c["eps"] is not None
    assert c["eps_source"].startswith("measured")
    assert "table said 2.0" in c["eps_source"], "the disagreement is hidden"
    assert c["alpha"] == 0.05


def test_a_counter_is_measured_on_its_increments():
    from cockpit import norms as nm
    counter = [1000.0 + i * 10 for i in range(40)]      # monotone, tiny noise
    eps, basis, n = nm.measure_eps(counter)
    assert "increments" in basis, basis
    assert eps < 5.0, "the level range was used instead of the increments"


def test_the_selftest_passes():
    assert rc._selftest() == 0
