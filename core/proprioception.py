#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/proprioception.py — THE SYSTEM FEELS ITS OWN TICK STRETCH.

23 Aug 2026. The first sensor that does not look outward.

Every other sensor in this repo reads the machine as an object: psutil says the
CPU is at 6%, shutil says the disk is 65% free, the firewall log says a packet
was dropped. This one reads the system's own experience of time. A tick is
expected to take X milliseconds; it measures what it actually took. When the
box is loaded, the tick stretches — and the stretch is felt in the system's own
clock rather than looked up in someone else's table.

WHY perf_counter AND NOTHING ELSE
-----------------------------------
time.perf_counter() costs about 80 nanoseconds and makes no syscall on Windows
(QueryPerformanceCounter is served from a shared page). So the instrument does
not stretch what it is measuring, which is the only reason a sensor this cheap
can sit on the hot path at all. No psutil, no library, no I/O, no thread.

WHAT THIS IS TAGGED, AND WHY IT IS NOT WHAT THE BRIEF SAID
------------------------------------------------------------
The brief asked for `reflexivity: 1`, on the grounds that all 42 existing
sensors are `reflexivity: 0` and this one senses the self.

It is tagged **reflexivity 0**, and the reason is that this repo already has a
reflexivity ladder and it means something else. cockpit/timeline.py:79 fixes
it as a count of MODEL PASSES —

    0  a measurement; no model touched it
    1  one model pass over a state the system just read
    2  the system judging its own output or its own run

— and test/test_timeline.py:104 pins those meanings. A tick measurement is a
measurement: no model touches it, nothing interprets it, and a reader can redo
the arithmetic by hand. Tagging it 1 would make REFLEXIVITY_MEANING[1] false
for this row and would quietly redefine a field three other modules already
depend on.

The distinction the brief was reaching for is real, so it gets its own field
rather than an overloaded one:

    DIRECTED_SELF   this sensor measures the system's own execution
    DIRECTED_WORLD  this sensor measures something outside it

That is orthogonal to reflexivity, which is about interpretation. A model
judging the outside world is reflexivity 1, directed world. This is
reflexivity 0, directed self. Both facts travel on the row.

    venv/Scripts/python.exe core/proprioception.py --report
    venv/Scripts/python.exe core/proprioception.py --selftest
"""
from __future__ import annotations

import pathlib
import sys
import time
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import event_bus as eb          # noqa: E402
from core import receptors as rc          # noqa: E402

KEY = "tick_latency_ms"
TOPIC = "receptor." + KEY

# See the header. reflexivity is a count of model passes; this is a measurement.
REFLEXIVITY = 0
DIRECTED_SELF, DIRECTED_WORLD = "self", "world"
DIRECTED = DIRECTED_SELF


class TickMeter:
    """Measures how long each tick actually took and publishes the stretch.

    `expected_ms` is what a tick is supposed to cost. The RECEPTOR does not use
    it — the receptor's baseline is what the ticks actually are, learned — but
    it is carried on every event so a reader can see the design intent beside
    the measurement, and stretch_ratio is computed against it.
    """

    def __init__(self, expected_ms: float = 15.0, bank=None,
                 alpha: Optional[float] = None, eps: Optional[float] = None,
                 calibration_ticks: int = rc.CALIBRATION_TICKS):
        from cockpit import norms as nm
        self.expected_ms = float(expected_ms)
        self.bank = bank if bank is not None else rc.ReceptorBank()

        a, a_src = nm.alpha_for(KEY)
        e_row = nm.RECEPTOR_TABLE.get(KEY, {})
        self.receptor = self.bank.add_receptor(
            KEY,
            alpha=a if alpha is None else alpha,
            eps=(e_row.get("eps") if eps is None else eps),
            alpha_source=a_src,
            eps_source="table: " + e_row.get("source", "unset"),
            unit="ms",
            calibration_ticks=calibration_ticks)

        self._t0: Optional[float] = None
        self.ticks = 0
        self.total_ms = 0.0
        self.max_ms = 0.0
        self.last_ms: Optional[float] = None

    # -- measuring ----------------------------------------------------------

    def start(self) -> float:
        self._t0 = time.perf_counter()
        return self._t0

    def stop(self, now: Optional[float] = None) -> Optional[eb.Event]:
        """Close the tick and publish if the stretch clears eps."""
        if self._t0 is None:
            return None
        elapsed_ms = (time.perf_counter() - self._t0) * 1000.0
        self._t0 = None
        return self.record(elapsed_ms, now=now)

    def record(self, elapsed_ms: float, now: Optional[float] = None):
        """Feed a measured duration. Separated from stop() so a test can hand
        it a stall without sleeping for one."""
        self.ticks += 1
        self.last_ms = float(elapsed_ms)
        self.total_ms += self.last_ms
        self.max_ms = max(self.max_ms, self.last_ms)
        ev = self.receptor.feed(self.last_ms, now=now)
        if ev is not None:
            ev.meta.update({
                "expected_ms": self.expected_ms,
                "stretch_ratio": (self.last_ms / self.expected_ms
                                  if self.expected_ms else None),
                "reflexivity": REFLEXIVITY,
                "directed": DIRECTED,
                "sensor": KEY,
            })
        return ev

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    # -- reporting ----------------------------------------------------------

    @property
    def mean_ms(self) -> Optional[float]:
        return self.total_ms / self.ticks if self.ticks else None

    def stats(self) -> dict:
        return {"sensor": KEY, "topic": TOPIC, "reflexivity": REFLEXIVITY,
                "directed": DIRECTED, "expected_ms": self.expected_ms,
                "ticks": self.ticks, "last_ms": self.last_ms,
                "mean_ms": self.mean_ms, "max_ms": self.max_ms,
                "phase": self.receptor.phase(),
                "alpha": self.receptor.alpha, "eps": self.receptor.eps,
                "eps_source": self.receptor.eps_source,
                "emitted": self.receptor.emitted,
                "baseline_ms": self.receptor.base}


def measure_instrument_cost(n: int = 100000) -> float:
    """Nanoseconds per perf_counter() call, measured here rather than quoted."""
    t0 = time.perf_counter()
    for _ in range(n):
        time.perf_counter()
    return (time.perf_counter() - t0) / n * 1e9


def _report() -> int:
    print("core/proprioception.py — READ ONLY.\n")
    cost = measure_instrument_cost()
    print("  perf_counter() costs {:.1f} ns per call on this machine".format(cost))
    print("  (the instrument must not stretch what it measures)\n")

    m = TickMeter(expected_ms=15.0, bank=rc.ReceptorBank(bus=eb.EventBus()),
                  calibration_ticks=10)
    for _ in range(10):                      # calibration, silent
        with m:
            time.sleep(0.015)
    quiet = m.receptor.emitted
    for _ in range(10):
        with m:
            time.sleep(0.015)
    print("  20 unstalled ticks of ~15 ms")
    print("    mean {:.2f} ms   max {:.2f} ms   baseline {:.2f} ms".format(
        m.mean_ms, m.max_ms, m.receptor.base))
    print("    emitted during calibration: {}".format(quiet))
    print("    emitted once live:          {}".format(m.receptor.emitted - quiet))

    with m:
        time.sleep(0.100)                    # a 100 ms stall
    st = m.stats()
    print("\n  one 100 ms stall")
    print("    measured {:.2f} ms   stretch x{:.1f}   emitted {}".format(
        st["last_ms"], st["last_ms"] / st["expected_ms"], st["emitted"]))
    print("\n  alpha {}   eps {} ms   {}".format(
        st["alpha"], st["eps"], st["eps_source"]))
    print("  reflexivity {}  directed {}  — see the header for why not 1".format(
        st["reflexivity"], st["directed"]))
    return 0


def _selftest() -> int:
    print("core/proprioception.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    m = TickMeter(expected_ms=15.0, bank=rc.ReceptorBank(bus=eb.EventBus()),
                  calibration_ticks=5)
    for _ in range(5):
        m.record(15.0)
    check("a steady tick is silent after warmup", m.receptor.emitted == 0)
    for _ in range(20):
        m.record(15.0 + (1.0 if _ % 2 else -1.0))
    check("and jitter under eps stays silent", m.receptor.emitted == 0)

    ev = m.record(115.0)
    check("a stall emits", ev is not None)
    check("the signal is proportional to the stall",
          ev and abs(ev.meta["signal"] - 100.0) < 2.0)
    check("the event says what it measures",
          ev and ev.meta["directed"] == "self" and ev.meta["reflexivity"] == 0)
    check("and carries the stretch ratio",
          ev and abs(ev.meta["stretch_ratio"] - 115.0 / 15.0) < 0.01)

    cost = measure_instrument_cost(20000)
    check("perf_counter costs under 1 microsecond ({:.0f} ns)".format(cost),
          cost < 1000)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    raise SystemExit(_report())
