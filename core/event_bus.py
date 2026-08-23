#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/event_bus.py — ONE PUBLISHER PER RECEPTOR. SUBSCRIBERS NEVER PROBE.

23 Aug 2026.

IT IS CALLED AN EVENT BUS BECAUSE THAT IS WHAT IT IS.
"One body, many observers" is a pub/sub pattern wearing a metaphor. The
metaphor was doing real work — it is why the constraint below exists — but a
module named for the metaphor is a module the next reader has to decode. The
name is precise and the constraint survives without it.

THE CONSTRAINT THAT MATTERS, AND IT IS ENFORCED RATHER THAN DOCUMENTED
-----------------------------------------------------------------------
**A subscriber never probes a sensor.**

Two independent probes of one sensor are not two sensings. They are one state
read twice, half a second apart, and they will disagree — and then two panels
show two different truths about one machine and there is no way to tell which
is stale. Reading is the bus's job; a subscriber consumes what was read.

This is the exact bug from two days ago: `/api/somatic` probed every 15 seconds
and threw the readings away. A viewer is a visitor with the chart, not a nurse
with a thermometer.

Enforcement is a thread-local depth counter. `Subscription.consume()` raises it
around the consumer callback; every guarded sensor calls
`assert_not_in_subscriber()` and raises `SensorProbeInSubscriber` if the depth
is non-zero. A subscriber that reaches for a thermometer gets an exception with
the topic name in it, not a comment it can ignore.

BACKPRESSURE: THE SLOW SUBSCRIBER PAYS, NOBODY ELSE
-----------------------------------------------------
Delivery is pull, not push. `publish()` appends to each subscription's own
bounded `deque` and returns; a full deque discards its own oldest by
construction. So a subscriber that stops consuming loses ITS OWN history and
cannot stall the publisher or any sibling. Every drop is counted and reported,
because a stream that silently drops is worse than one that says it dropped.

One publisher per topic is registered and enforced: a second claim on a live
topic raises. Two writers on one receptor is the same disagreement as two
probes, moved one layer out.

In-process, standard library only, no thread of its own.

    venv/Scripts/python.exe core/event_bus.py --selftest
"""
from __future__ import annotations

import functools
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

# Channels. See core/receptors.py — R adapts, S never does.
CHANNEL_R = "R"
CHANNEL_S = "S"
CHANNELS = (CHANNEL_R, CHANNEL_S)

DEFAULT_MAXLEN = 512


class BusError(Exception):
    """Base for everything this module refuses to do."""


class TopicOwned(BusError):
    """A second publisher tried to claim a topic that already has one."""


class SensorProbeInSubscriber(BusError):
    """A subscriber reached for a sensor. That is the one thing it may not do."""


class Event:
    """topic, monotonic timestamp, value, channel. Nothing else is promised.

    The timestamp is `time.monotonic()`, not wall clock: these are used for
    intervals and rates, and a wall clock can step backwards over an NTP
    correction or a DST boundary and produce a negative duration.
    """

    __slots__ = ("topic", "ts", "value", "channel", "seq", "meta")

    def __init__(self, topic: str, ts: float, value: Any, channel: str,
                 seq: int, meta: Optional[dict] = None):
        self.topic = topic
        self.ts = ts
        self.value = value
        self.channel = channel
        self.seq = seq
        self.meta = meta or {}

    def as_dict(self) -> dict:
        return {"topic": self.topic, "ts": self.ts, "value": self.value,
                "channel": self.channel, "seq": self.seq, "meta": self.meta}

    def __repr__(self) -> str:
        return "Event({}#{} {} ch={} v={!r})".format(
            self.topic, self.seq, round(self.ts, 3), self.channel, self.value)


# ---------------------------------------------------------------------------
# The guard — a subscriber never probes a sensor
# ---------------------------------------------------------------------------

_local = threading.local()


def _depth() -> int:
    return getattr(_local, "depth", 0)


def _set_depth(n: int) -> None:
    _local.depth = n


def in_subscriber() -> bool:
    return _depth() > 0


def current_consumer() -> Optional[str]:
    return getattr(_local, "who", None)


def assert_not_in_subscriber(what: str) -> None:
    """Called by every guarded sensor. Raises inside a consumer callback."""
    if _depth() > 0:
        raise SensorProbeInSubscriber(
            "{!r} was probed from inside subscriber {!r}. A subscriber consumes "
            "what the bus read; it does not read again. Two probes of one "
            "sensor are one state read twice and they will disagree.".format(
                what, current_consumer() or "<unknown>"))


# Every guarded probe is COUNTED. Not for policy — nothing throttles on this —
# but so that "this panel adds zero new sensor probes" is a measurement a test
# can take rather than a claim a reviewer has to believe. See
# test/test_glass.py, which counts probes with the tab shut and with it open.
PROBES = {}


def probe_count(name: Optional[str] = None) -> int:
    if name is None:
        return sum(PROBES.values())
    return PROBES.get(name, 0)


def reset_probe_count() -> None:
    PROBES.clear()


def guard_sensor(name: str) -> Callable:
    """Decorator. Marks a function as a real probe of the machine."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            assert_not_in_subscriber(name)
            PROBES[name] = PROBES.get(name, 0) + 1
            return fn(*a, **k)
        wrapper.__guarded_sensor__ = name
        return wrapper
    return deco


# ---------------------------------------------------------------------------

class Subscription:
    """One subscriber's own bounded view of one topic."""

    def __init__(self, bus: "EventBus", topic: str, name: str, maxlen: int):
        self._bus = bus
        self.topic = topic
        self.name = name
        self.maxlen = maxlen
        self._q: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self.received = 0
        self.dropped = 0
        self.consumed = 0

    # called by the publisher, holds only this subscription's lock
    def _offer(self, event: Event) -> None:
        with self._lock:
            if len(self._q) == self._q.maxlen:
                self.dropped += 1          # the deque discards its own oldest
            self._q.append(event)
            self.received += 1

    def pending(self) -> int:
        with self._lock:
            return len(self._q)

    def drain(self, limit: Optional[int] = None) -> list:
        """Take what is waiting. Does NOT raise the subscriber guard — use
        consume() for that, and prefer it."""
        with self._lock:
            n = len(self._q) if limit is None else min(limit, len(self._q))
            out = [self._q.popleft() for _ in range(n)]
        self.consumed += len(out)
        return out

    def consume(self, fn: Callable[[Event], Any],
                limit: Optional[int] = None) -> list:
        """Drain and hand each event to `fn` with the sensor guard raised.

        THIS IS THE BLESSED PATH. Anything `fn` does that reaches a guarded
        sensor raises SensorProbeInSubscriber instead of quietly producing a
        second, disagreeing reading.
        """
        events = self.drain(limit)
        if not events:
            return []
        prev_depth, prev_who = _depth(), current_consumer()
        _set_depth(prev_depth + 1)
        _local.who = self.name
        try:
            return [fn(e) for e in events]
        finally:
            _set_depth(prev_depth)
            _local.who = prev_who

    def close(self) -> None:
        self._bus.unsubscribe(self)

    def stats(self) -> dict:
        return {"topic": self.topic, "name": self.name, "maxlen": self.maxlen,
                "received": self.received, "consumed": self.consumed,
                "dropped": self.dropped, "pending": self.pending()}

    def __repr__(self) -> str:
        return "Subscription({} <- {})".format(self.name, self.topic)


class EventBus:
    def __init__(self, maxlen: int = DEFAULT_MAXLEN):
        self.default_maxlen = maxlen
        self._subs: dict = {}          # topic -> [Subscription]
        self._owners: dict = {}        # topic -> publisher name
        self._seq: dict = {}           # topic -> counter
        self._lock = threading.Lock()
        self.published = 0

    # -- publishers ---------------------------------------------------------

    def register_publisher(self, topic: str, owner: str) -> str:
        """Claim a topic. ONE publisher per receptor, and it is enforced.

        Two writers on one topic is the same disagreement as two probes of one
        sensor, moved one layer out: two sources of truth for one number.
        """
        with self._lock:
            held = self._owners.get(topic)
            if held is not None and held != owner:
                raise TopicOwned(
                    "topic {!r} is already published by {!r}; {!r} may not also "
                    "publish it".format(topic, held, owner))
            self._owners[topic] = owner
            self._seq.setdefault(topic, 0)
        return owner

    def publisher_of(self, topic: str) -> Optional[str]:
        return self._owners.get(topic)

    def publish(self, topic: str, value: Any, channel: str = CHANNEL_R,
                meta: Optional[dict] = None, ts: Optional[float] = None,
                owner: Optional[str] = None) -> Event:
        """Fan one event out to every subscription. Never blocks on a consumer."""
        if channel not in CHANNELS:
            raise BusError("channel must be one of {}, got {!r}".format(
                CHANNELS, channel))
        if owner is not None:
            self.register_publisher(topic, owner)
        with self._lock:
            self._seq[topic] = self._seq.get(topic, 0) + 1
            seq = self._seq[topic]
            targets = list(self._subs.get(topic, ()))
            targets += list(self._subs.get(self.ALL, ()))
            self.published += 1
        ev = Event(topic, time.monotonic() if ts is None else ts,
                   value, channel, seq, meta)
        for sub in targets:
            sub._offer(ev)             # bounded deque; cannot block
        return ev

    # -- subscribers --------------------------------------------------------

    # A subscription that is not tied to one topic. The raw-stream panel needs
    # every line the body produces, including from receptors that do not exist
    # yet when it subscribes — a panel that had to enumerate topics in advance
    # would silently miss the next sensor somebody adds.
    #
    # It is still a SUBSCRIBER: same bounded deque, same drops counted, same
    # guard against probing a sensor. Nothing about the rule changes because
    # the filter is wider.
    ALL = "*"

    def subscribe_all(self, name: str,
                      maxlen: Optional[int] = None) -> Subscription:
        return self.subscribe(self.ALL, name, maxlen)

    def subscribe(self, topic: str, name: str,
                  maxlen: Optional[int] = None) -> Subscription:
        sub = Subscription(self, topic, name, maxlen or self.default_maxlen)
        with self._lock:
            self._subs.setdefault(topic, []).append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> bool:
        with self._lock:
            lst = self._subs.get(sub.topic, [])
            if sub in lst:
                lst.remove(sub)
                return True
        return False

    def subscribers(self, topic: str) -> list:
        with self._lock:
            return list(self._subs.get(topic, ()))

    def topics(self) -> list:
        with self._lock:
            return sorted((set(self._owners) | set(self._subs)) - {self.ALL})

    def stats(self) -> dict:
        return {
            "published": self.published,
            "topics": {t: {"publisher": self._owners.get(t),
                           "subscribers": len(self._subs.get(t, ())),
                           "seq": self._seq.get(t, 0)}
                       for t in self.topics()},
            "subscriptions": [s.stats() for lst in self._subs.values()
                              for s in lst],
        }

    def reset(self) -> None:
        """Tests only. Drops every subscription and publisher claim."""
        with self._lock:
            self._subs.clear()
            self._owners.clear()
            self._seq.clear()
            self.published = 0


# The process-wide bus. One body, one bus.
BUS = EventBus()


def publish(topic: str, value: Any, channel: str = CHANNEL_R, **kw) -> Event:
    return BUS.publish(topic, value, channel, **kw)


def subscribe(topic: str, name: str, maxlen: Optional[int] = None) -> Subscription:
    return BUS.subscribe(topic, name, maxlen)


def register_publisher(topic: str, owner: str) -> str:
    return BUS.register_publisher(topic, owner)


def stats() -> dict:
    return BUS.stats()


# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/event_bus.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    bus = EventBus(maxlen=4)
    bus.register_publisher("ram_free", "receptor:ram_free")

    a = bus.subscribe("ram_free", "panel_a")
    b = bus.subscribe("ram_free", "panel_b")
    for i in range(3):
        bus.publish("ram_free", 1000 + i, CHANNEL_R)
    check("two subscribers each see every event",
          a.pending() == 3 and b.pending() == 3)

    got_a = [e.value for e in a.drain()]
    got_b = [e.value for e in b.drain()]
    check("and they see the same values", got_a == got_b == [1000, 1001, 1002])

    # a subscriber that stops consuming
    slow = bus.subscribe("ram_free", "slow")
    fast = bus.subscribe("ram_free", "fast")
    for i in range(10):
        bus.publish("ram_free", i, CHANNEL_R)
    check("the slow subscriber drops its own oldest",
          slow.pending() == 4 and slow.dropped == 6)
    check("and the publisher was not stalled", bus.published == 13)
    check("the fast one is unaffected", fast.pending() == 4)
    check("the drop is counted, not silent", slow.stats()["dropped"] == 6)

    # one publisher per topic
    try:
        bus.register_publisher("ram_free", "somebody_else")
        check("a second publisher is refused", False)
    except TopicOwned:
        check("a second publisher is refused", True)

    # the guard
    @guard_sensor("fake_sensor")
    def _probe():
        return 42

    check("a sensor works outside a subscriber", _probe() == 42)

    raised = {}

    def _naughty(event):
        try:
            _probe()
            raised["ok"] = False
        except SensorProbeInSubscriber as exc:
            raised["ok"] = True
            raised["msg"] = str(exc)
        return event.value

    c = bus.subscribe("ram_free", "naughty_panel")
    bus.publish("ram_free", 7, CHANNEL_R)
    c.consume(_naughty)
    check("a subscriber that probes a sensor raises", raised.get("ok") is True)
    check("and the message names the subscriber",
          "naughty_panel" in raised.get("msg", ""))
    check("the guard is released afterwards",
          not in_subscriber() and _probe() == 42)

    # channels
    ev = bus.publish("disk_free_pct", 65.5, CHANNEL_S)
    check("an event carries topic, ts, value and channel",
          ev.topic == "disk_free_pct" and ev.channel == CHANNEL_S
          and isinstance(ev.ts, float) and ev.value == 65.5)
    check("the timestamp is monotonic", ev.ts <= time.monotonic())
    try:
        bus.publish("x", 1, "Q")
        check("an unknown channel is refused", False)
    except BusError:
        check("an unknown channel is refused", True)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    import json
    print(json.dumps(stats(), indent=2, default=str))
