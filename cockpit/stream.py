#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/stream.py — THE LIVE TEXT OF THE BUS, AND ITS SILENCE EXPLAINED.

24 Aug 2026. `source:hardware, mediation:code`.

Every line carries what actually crossed and nothing else: the monotonic
timestamp, the topic, the channel, the raw value, the adapted baseline, and the
residual or the drift that did it. Nothing aggregated, nothing rounded for
beauty, nothing summarised.

    12345.678  receptor.ram_percent   R  anchor    82.50  base 79.31  drift +9.02 > 8.90
    12350.114  setpoint.disk_free_pct S  action    14.20                level notice -> action

THE PANEL SHOWS ITS OWN SILENCE HONESTLY
------------------------------------------
An empty panel has three possible meanings and a reader must never have to
guess which:

    WARMUP (N ticks remaining)     the receptors have not settled yet, so they
                                   are suppressing on purpose
    QUIET (adapted, nothing crossed)  they are live and nothing crossed
    NO RECEPTORS YET               nothing has been built in this process

"The body registered nothing" and "the panel is broken" are different
statements, and a panel that cannot tell them apart is a panel that gets
ignored the first time it is wrong.

ZERO NEW SENSOR PROBES
------------------------
It is a SUBSCRIBER. It reads what the bus already carried; it never calls a
sensor. core/event_bus.py raises SensorProbeInSubscriber if anything in a
consumer callback reaches for one, and test/test_stream.py counts probes with
the panel shut and again after rendering it sixty times.

    venv/Scripts/python.exe -m cockpit.stream --selftest
"""
from __future__ import annotations

import pathlib
import sys
from collections import deque
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import event_bus as eb        # noqa: E402

LABEL_SOURCE = "hardware"
LABEL_MEDIATION = "code"

# The panel is a window on a live stream, not an archive. What scrolls off the
# top is gone here and is still in the ledgers that keep history.
BUFFER = 500

WARMUP = "WARMUP"
QUIET = "QUIET"
NO_RECEPTORS = "NO_RECEPTORS"
FLOWING = "FLOWING"


class StreamTap:
    """One wildcard subscription and a bounded ring of rendered lines."""

    def __init__(self, bus: Optional[eb.EventBus] = None, maxlen: int = BUFFER,
                 name: str = "glass_stream"):
        self.bus = bus if bus is not None else eb.BUS
        self.lines: deque = deque(maxlen=maxlen)
        self.sub = self.bus.subscribe_all(name, maxlen=maxlen)
        self.seen = 0

    # -- rendering ----------------------------------------------------------

    @staticmethod
    def render(ev: eb.Event) -> dict:
        """One event, as the panel shows it. No rounding for beauty: the values
        are printed at the precision they arrived with."""
        m = ev.meta or {}
        why = m.get("why")
        if ev.channel == eb.CHANNEL_S:
            crossed = "level {} -> {}".format(m.get("was"), m.get("level"))
            why = why or "setpoint"
        elif why == "anchor":
            crossed = "drift {:+} > {}".format(
                _num(m.get("drift")), _num(m.get("anchor_band")))
        elif why in ("residual", "both", None):
            crossed = "signal {:+} > {}".format(
                _num(m.get("signal")), _num(m.get("eps")))
            why = why or "residual"
        else:
            crossed = ""
        return {
            "ts": ev.ts,
            "topic": ev.topic,
            "channel": ev.channel,
            "why": why,
            "value": ev.value,
            "base": m.get("base"),
            "crossed": crossed,
            "unit": m.get("unit", ""),
            "source": m.get("source", LABEL_SOURCE),
            "directed": m.get("directed", "world"),
            "text": "{:.3f}  {:<28} {}  {:<8} {}{}  {}{}".format(
                ev.ts, ev.topic, ev.channel, str(why or ""),
                _num(ev.value), m.get("unit", ""),
                "base {} ".format(_num(m.get("base")))
                if m.get("base") is not None else "",
                crossed),
        }

    # -- pumping ------------------------------------------------------------

    def pump(self) -> int:
        """Drain whatever the bus has and render it. Returns how many arrived.

        drain(), not consume(): there is no callback here that could reach a
        sensor, and the rendered lines are pure functions of the event.
        """
        got = self.sub.drain()
        for ev in got:
            self.lines.append(self.render(ev))
        self.seen += len(got)
        return len(got)

    # -- the silence --------------------------------------------------------

    def silence(self, bank=None) -> dict:
        """Why the panel is empty, when it is. Never a guess."""
        receptors = list((bank.receptors if bank is not None else {}).values())
        if not receptors:
            return {"state": NO_RECEPTORS,
                    "text": "NO RECEPTORS YET",
                    "detail": ("nothing has been built in this process — the "
                               "cockpit builds them on its first somatic read")}
        warming = [r for r in receptors if r.warming()]
        if warming:
            remaining = max(
                (r._calibration_ticks - r.ticks) for r in warming)
            return {"state": WARMUP,
                    "text": "WARMUP ({} ticks remaining)".format(
                        max(0, remaining)),
                    "detail": "{} of {} receptors are still calibrating; they "
                              "are suppressing on purpose".format(
                                  len(warming), len(receptors)),
                    "warming": len(warming), "total": len(receptors)}
        return {"state": QUIET,
                "text": "QUIET (adapted, nothing crossed)",
                "detail": "{} receptors live; every reading was inside its own "
                          "noise floor".format(len(receptors))}

    def state(self, bank=None) -> dict:
        self.pump()
        s = self.silence(bank)
        if self.lines:
            s = {"state": FLOWING, "text": "", "detail": s["detail"]}
        return {
            "source": LABEL_SOURCE,
            "mediation": LABEL_MEDIATION,
            "label": "source:{}, mediation:{}".format(LABEL_SOURCE,
                                                      LABEL_MEDIATION),
            "lines": list(self.lines),
            "n": len(self.lines),
            "seen": self.seen,
            "dropped": self.sub.dropped,
            "buffer": self.lines.maxlen,
            "silence": s,
        }


def _num(x):
    if x is None:
        return "-"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int, float)):
        return round(x, 4)
    return x


_TAP: dict = {"tap": None}


def tap(bus=None) -> StreamTap:
    """One tap per process. Built lazily so importing costs nothing."""
    if _TAP["tap"] is None:
        _TAP["tap"] = StreamTap(bus=bus)
    return _TAP["tap"]


def _selftest() -> int:
    from core import receptors as rc
    print("cockpit/stream.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    bus = eb.EventBus()
    t = StreamTap(bus=bus, maxlen=10, name="selftest")
    bank = rc.ReceptorBank(bus=bus, seed_path=BASE / "memory" / "_none")

    check("no receptors is said, not guessed",
          t.silence(bank)["state"] == NO_RECEPTORS)

    r = bank.add_receptor("ram_percent", 0.2, 1.0, calibration_ticks=4,
                          unit="%")
    r.feed(80.0)
    check("warming says how many ticks remain",
          t.silence(bank)["state"] == WARMUP
          and "ticks remaining" in t.silence(bank)["text"])

    for _ in range(4):
        r.feed(80.0)
    check("then it is quiet, and says why",
          t.silence(bank)["state"] == QUIET
          and "nothing crossed" in t.silence(bank)["text"])

    r.feed(95.0)
    st = t.state(bank)
    check("a crossing produces one line", st["n"] == 1)
    line = st["lines"][0]
    check("the line carries ts, topic, channel, value, base and what crossed",
          all(line[k] is not None for k in
              ("ts", "topic", "channel", "value", "base"))
          and line["crossed"])
    check("and it is labelled", st["label"] ==
          "source:hardware, mediation:code")
    check("the raw value is not rounded for beauty", line["value"] == 95.0)

    sp = bank.add_setpoint("disk_free_pct", {"notice": 28, "action": 15,
                                             "gate": 5}, "%")
    sp.feed(50.0)
    sp.feed(14.0)
    t.pump()
    s_lines = [l for l in t.lines if l["channel"] == "S"]
    check("a set-point crossing shows its levels",
          s_lines and "->" in s_lines[-1]["crossed"])

    for i in range(50):
        r.feed(200.0 + i * 50)
    t.pump()
    check("the ring is bounded and the drops are counted",
          len(t.lines) == 10 and t.sub.dropped > 0)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
