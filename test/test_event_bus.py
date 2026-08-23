#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_event_bus.py — FAN-OUT, BACKPRESSURE, AND THE ONE RULE.

The three the command names:
  * two subscribers on one topic both receive every event;
  * a subscriber that stops consuming does not stall the publisher;
  * no subscriber code path reaches a sensor call.

The third is the one that matters and it is tested twice: at runtime, against
the REAL guarded sensors, and statically, over the source of every module that
subscribes.

    venv/Scripts/python.exe -m pytest test/test_event_bus.py -v
"""
from __future__ import annotations

import pathlib
import sys
import threading
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import event_bus as eb  # noqa: E402


@pytest.fixture
def bus():
    return eb.EventBus(maxlen=8)


# ── fan-out ─────────────────────────────────────────────────────────────────

def test_two_subscribers_both_receive_every_event(bus):
    a = bus.subscribe("ram_free", "a")
    b = bus.subscribe("ram_free", "b")
    for i in range(20):
        bus.publish("ram_free", i)
    # maxlen is 8, so each keeps the last 8 — but each got all 20 offered
    assert a.received == b.received == 20
    assert [e.value for e in a.drain()] == [e.value for e in b.drain()]


def test_a_small_burst_is_delivered_whole(bus):
    a = bus.subscribe("t", "a")
    b = bus.subscribe("t", "b")
    for i in range(5):
        bus.publish("t", i)
    assert [e.value for e in a.drain()] == [0, 1, 2, 3, 4]
    assert [e.value for e in b.drain()] == [0, 1, 2, 3, 4]
    assert a.dropped == b.dropped == 0


def test_a_subscriber_added_later_does_not_see_history(bus):
    early = bus.subscribe("t", "early")
    bus.publish("t", 1)
    late = bus.subscribe("t", "late")
    bus.publish("t", 2)
    assert [e.value for e in early.drain()] == [1, 2]
    assert [e.value for e in late.drain()] == [2]


def test_unsubscribing_stops_delivery(bus):
    a = bus.subscribe("t", "a")
    bus.publish("t", 1)
    a.close()
    bus.publish("t", 2)
    assert [e.value for e in a.drain()] == [1]


def test_a_topic_with_no_subscribers_still_publishes(bus):
    ev = bus.publish("nobody_listening", 1)
    assert ev.seq == 1 and bus.published == 1


# ── backpressure: the slow subscriber pays, nobody else ─────────────────────

def test_a_subscriber_that_stops_consuming_does_not_stall_the_publisher(bus):
    slow = bus.subscribe("t", "slow")
    fast = bus.subscribe("t", "fast")
    t0 = time.monotonic()
    for i in range(1000):
        bus.publish("t", i)
        fast.drain()
    elapsed = time.monotonic() - t0
    assert bus.published == 1000
    assert elapsed < 2.0, "publishing stalled: {:.2f}s".format(elapsed)
    assert slow.pending() == 8, slow.pending()
    assert fast.pending() == 0


def test_the_slow_subscriber_drops_its_own_oldest(bus):
    slow = bus.subscribe("t", "slow")
    for i in range(20):
        bus.publish("t", i)
    assert slow.dropped == 12
    assert [e.value for e in slow.drain()] == list(range(12, 20)), "not the oldest"


def test_one_subscribers_drops_do_not_touch_another(bus):
    slow = bus.subscribe("t", "slow")
    fast = bus.subscribe("t", "fast")
    seen = []
    for i in range(30):
        bus.publish("t", i)
        seen += [e.value for e in fast.drain()]
    assert seen == list(range(30)), "the fast subscriber lost events"
    assert slow.dropped == 22
    assert fast.dropped == 0


def test_the_drop_is_counted_never_silent(bus):
    s = bus.subscribe("t", "s")
    for i in range(12):
        bus.publish("t", i)
    st = s.stats()
    assert st["dropped"] == 4 and st["received"] == 12 and st["pending"] == 8


def test_a_consumer_that_raises_does_not_poison_the_bus(bus):
    s = bus.subscribe("t", "s")
    bus.publish("t", 1)
    with pytest.raises(ValueError):
        s.consume(lambda e: (_ for _ in ()).throw(ValueError("boom")))
    assert not eb.in_subscriber(), "the guard leaked after an exception"
    bus.publish("t", 2)
    assert [e.value for e in s.drain()] == [2]


def test_publishing_from_several_threads_loses_nothing(bus):
    s = bus.subscribe("t", "s", maxlen=4096)
    def w(n):
        for i in range(200):
            bus.publish("t", (n, i))
    threads = [threading.Thread(target=w, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert bus.published == 800
    assert s.received == 800 and s.dropped == 0


# ── ONE PUBLISHER PER RECEPTOR ──────────────────────────────────────────────

def test_a_second_publisher_on_one_topic_is_refused(bus):
    bus.register_publisher("ram_free", "receptor:ram_free")
    with pytest.raises(eb.TopicOwned):
        bus.register_publisher("ram_free", "somebody_else")


def test_the_same_publisher_may_reclaim_its_own_topic(bus):
    bus.register_publisher("t", "me")
    bus.register_publisher("t", "me")
    assert bus.publisher_of("t") == "me"


def test_publish_can_claim_the_topic_as_it_writes(bus):
    bus.publish("t", 1, owner="receptor:t")
    assert bus.publisher_of("t") == "receptor:t"
    with pytest.raises(eb.TopicOwned):
        bus.publish("t", 2, owner="an_impostor")


# ── THE EVENT SHAPE ─────────────────────────────────────────────────────────

def test_an_event_carries_topic_ts_value_and_channel(bus):
    ev = bus.publish("disk_free_pct", 65.5, eb.CHANNEL_S, meta={"unit": "%"})
    assert ev.topic == "disk_free_pct"
    assert ev.value == 65.5
    assert ev.channel == "S"
    assert isinstance(ev.ts, float)
    assert ev.meta["unit"] == "%"
    assert set(ev.as_dict()) >= {"topic", "ts", "value", "channel"}


def test_the_timestamp_is_monotonic_not_wall_clock(bus):
    """A wall clock steps backwards over an NTP correction and produces a
    negative duration. These timestamps are used for rates."""
    a = bus.publish("t", 1).ts
    b = bus.publish("t", 2).ts
    assert b >= a
    assert abs(a - time.monotonic()) < 5.0
    assert a < 10 ** 9, "that looks like a wall clock"


def test_only_R_and_S_are_channels(bus):
    assert eb.CHANNELS == ("R", "S")
    with pytest.raises(eb.BusError):
        bus.publish("t", 1, "Q")


def test_sequence_numbers_are_per_topic(bus):
    bus.publish("a", 1)
    bus.publish("b", 1)
    assert bus.publish("a", 2).seq == 2
    assert bus.publish("b", 2).seq == 2


# ═══ A SUBSCRIBER NEVER PROBES A SENSOR ═════════════════════════════════════

def test_a_subscriber_that_probes_the_real_ram_sensor_raises(bus):
    from core import homeostasis as h
    s = bus.subscribe("ram_free", "a_panel")
    bus.publish("ram_free", 4000.0)
    with pytest.raises(eb.SensorProbeInSubscriber) as exc:
        s.consume(lambda e: h.read_ram_free_mb())
    assert "ram_free" in str(exc.value)
    assert "a_panel" in str(exc.value)


def test_a_subscriber_that_probes_the_real_disk_sensor_raises(bus):
    from core import homeostasis as h
    s = bus.subscribe("t", "another_panel")
    bus.publish("t", 1)
    with pytest.raises(eb.SensorProbeInSubscriber):
        s.consume(lambda e: h.read_disk_free_pct())


def test_a_subscriber_that_calls_the_somatic_probe_raises(bus):
    """This is the bug by name: /api/somatic probed every 15 seconds and threw
    the readings away."""
    from cockpit import somatic as som
    s = bus.subscribe("t", "api_somatic")
    bus.publish("t", 1)
    with pytest.raises(eb.SensorProbeInSubscriber):
        s.consume(lambda e: som.probe())


def test_the_real_sensors_are_actually_guarded():
    """Not a decorator on a stand-in. These three."""
    from core import homeostasis as h
    from cockpit import somatic as som
    assert h.read_ram_free_mb.__guarded_sensor__ == "ram_free"
    assert h.read_disk_free_pct.__guarded_sensor__ == "disk_free_pct"
    assert som.probe.__guarded_sensor__ == "somatic.probe"


def test_the_sensors_still_work_outside_a_subscriber():
    from core import homeostasis as h
    assert h.read_ram_free_mb() > 0
    assert 0 < h.read_disk_free_pct() <= 100


def test_the_guard_is_released_after_consume(bus):
    from core import homeostasis as h
    s = bus.subscribe("t", "s")
    bus.publish("t", 1)
    s.consume(lambda e: e.value)
    assert not eb.in_subscriber()
    assert h.read_ram_free_mb() > 0


def test_nested_consumes_do_not_release_the_guard_early(bus):
    from core import homeostasis as h
    outer = bus.subscribe("a", "outer")
    inner = bus.subscribe("b", "inner")
    bus.publish("a", 1)
    bus.publish("b", 1)

    def inner_fn(e):
        return e.value

    def outer_fn(e):
        inner.consume(inner_fn)              # returns, depth back to 1
        assert eb.in_subscriber(), "the guard was released by the inner drain"
        with pytest.raises(eb.SensorProbeInSubscriber):
            h.read_ram_free_mb()
        return e.value

    outer.consume(outer_fn)
    assert not eb.in_subscriber()


def test_drain_is_documented_as_the_unguarded_path(bus):
    """drain() cannot guard what happens after it returns. consume() is the
    blessed path and the docstring has to say so, or the guard is advisory."""
    doc = eb.Subscription.consume.__doc__ or ""
    assert "BLESSED PATH" in doc
    assert "not raise the subscriber guard" in (
        eb.Subscription.drain.__doc__ or "").lower()


def test_no_module_that_subscribes_also_imports_a_sensor():
    """Static half. A subscriber module that imports a probe is one edit away
    from calling it, and today's fixtures would not catch that."""
    import subprocess
    r = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                       capture_output=True, text=True)
    offenders = []
    for rel in r.stdout.splitlines():
        if rel.startswith("test/") or rel in ("core/event_bus.py",):
            continue
        try:
            src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "event_bus" not in src or ".subscribe(" not in src:
            continue
        for probe in ("somatic.probe", "read_ram_free_mb", "read_disk_free_pct"):
            if probe in src:
                offenders.append((rel, probe))
    assert not offenders, offenders


def test_the_selftest_passes():
    assert eb._selftest() == 0
