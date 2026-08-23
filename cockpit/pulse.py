#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/pulse.py — THE PRODUCER OF PULSE LINES. NO MODEL ANYWHERE.

Every line this module emits is source:sensor, reflexivity:0. Nothing here
interprets anything; it decides only WHETHER a reading is worth a line, and the
decision is arithmetic a reader can redo by hand.

WHY A CHANGE RULE AT ALL
--------------------------
A sensor read every 15 seconds produces 5,760 readings a day. Streaming all of
them is the same as streaming none: the window scrolls faster than anyone reads
and the one line that mattered is gone before it is seen. So a reading earns a
line only when it is MEANINGFULLY DIFFERENT from the last one that was emitted —
not from the last one taken.

Three ways to earn one, checked in this order:

  BAND      the bar's colour changed. This is the one that matters most,
            because it is the change a human would have noticed on the page.
  MOVE      more than 15% from the last emitted value. Relative, so a 2-degree
            GPU swing and a 2-percent RAM swing are judged on their own scales.
  AVAILABILITY  a sensor that could not be read now can, or the reverse. This
            is the change most likely to be a real event and least likely to
            look like one, since the value on either side may be identical.

PLUS ONE SPINE LINE PER CYCLE STEP, REGARDLESS
------------------------------------------------
Without it the stream has gaps where nothing moved, and a reader cannot tell a
quiet system from a dead producer. The spine is the timeline; the change lines
hang off it.

THE CAP TELLS YOU IT IS A CAP
-------------------------------
Twenty pulse lines a minute. Past that the module emits ONE aggregate line
naming how many sensors moved and the largest mover, and the line SAYS IT IS A
TRUNCATION. A stream that silently drops lines is worse than a noisy one,
because the reader cannot tell the difference between calm and censored.

    venv/Scripts/python.exe -m cockpit.pulse --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import expression as ex        # noqa: E402

MOVE_THRESHOLD = 0.15           # 15%, relative
CAP_PER_MINUTE = 20
WINDOW_SEC = 60.0

# ── THE BAND COMES FROM THE DIRECTION MAP, NOT FROM THE UNIT (23 Aug 2026) ──
# This module used to band by UNIT: anything in percent turned amber at 65 and
# red at 85. So wifi_signal_pct at 85% — the best Wi-Fi this laptop has ever
# had — rendered "band amber -> red", twice, at an unchanged value, while the
# structured `band` field on the very same line said "green". The line
# disagreed with itself, and the page was right.
#
# cockpit/somatic.DIRECTIONS is the map that already knows which way is bad for
# each metric: HIGHER_BETTER (battery, wifi signal) warns at the LOW end,
# LOWER_BETTER (load, temperature, memory) at the high end. It is what the panel
# has used since COMMAND 21e item D, and it is what this uses now. Two band
# tables over the same readings is how the two halves of one line end up
# contradicting each other.
#
# A metric with no entry gets NO BAND — not green. A grey bar says "not judged";
# a green bar says "judged, and fine", and this module must not make the second
# claim by accident either.

TRUNCATION_NOTE = ("TRUNCATED: over {cap} pulse lines in {window:.0f}s, so the "
                   "individual lines were not emitted")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def band_of(value, unit: str = "", key: str = "") -> Optional[str]:
    """green / amber / red for THIS metric, or None when nobody has judged it.

    `key` is what decides; `unit` is kept only so the older two-argument calls
    still parse, and with no key there is no band — a guess from the unit is
    exactly what produced "wifi at 85% is red".
    """
    if not key:
        return None
    try:
        from cockpit import somatic as som          # noqa: PLC0415
    except Exception:
        return None
    return som.band_for(key, value)


def _relative_move(new, old) -> Optional[float]:
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in (new, old)):
        return None
    if old == 0:
        return None if new == 0 else 1.0
    return abs(float(new) - float(old)) / abs(float(old))


def why_emit(row: dict, last: Optional[dict]) -> Optional[dict]:
    """The reason this reading earns a line, or None. Pure; no state touched.

    `last` is the last EMITTED reading for this key, not the last one taken —
    otherwise a value drifting 14% per read would never emit while wandering
    arbitrarily far from anything the reader was shown.
    """
    key, unit = row.get("key"), row.get("unit", "")
    now_available = bool(row.get("available"))
    value = row.get("value")

    if last is None:
        return {"reason": "first reading", "kind": "first"} if now_available else None

    was_available = bool(last.get("available"))
    if now_available != was_available:
        return {"kind": "availability",
                "reason": ("became readable" if now_available
                           else "became NOT AVAILABLE: {}".format(
                               (row.get("reason") or "")[:60]))}
    if not now_available:
        return None

    nb, ob = band_of(value, unit, key), band_of(last.get("value"), unit, key)
    if nb and ob and nb != ob:
        return {"kind": "band", "reason": "band {} -> {}".format(ob, nb)}

    move = _relative_move(value, last.get("value"))
    if move is not None and move > MOVE_THRESHOLD:
        return {"kind": "move", "reason": "moved {:.0%} (> {:.0%})".format(
            move, MOVE_THRESHOLD)}
    return None


class PulseProducer:
    """Holds the last EMITTED reading per key, and the rate window.

    A plain object with no I/O of its own: emit() returns lines and the caller
    decides where they go. That is what makes the cap testable without a file.
    """

    def __init__(self, cap_per_minute: int = CAP_PER_MINUTE,
                 window_sec: float = WINDOW_SEC):
        self.last_emitted = {}
        self.cap = cap_per_minute
        self.window = window_sec
        self._recent = []                    # timestamps of emitted change lines

    def _prune(self, now: float) -> None:
        self._recent = [t for t in self._recent if now - t < self.window]

    def _room(self, now: float) -> int:
        self._prune(now)
        return max(0, self.cap - len(self._recent))

    def spine(self, step: str, index: str = "", ts: Optional[str] = None) -> dict:
        """One line per cycle step, ALWAYS. The timeline the rest hangs off."""
        return ex.make_line(
            ex.SYS, ex.PULSE,
            "step {} {}".format(index or "", step).strip(),
            ts=ts, source_tag="sensor", reflexivity=0, kind="spine")

    def emit(self, probe: dict, now: Optional[float] = None) -> list:
        """Lines for one somatic probe. Updates the last-emitted state."""
        import time
        t = time.monotonic() if now is None else now
        rows = [r for rows in probe.get("groups", {}).values() for r in rows]

        changed = []
        for row in rows:
            if row.get("disabled"):
                continue
            reason = why_emit(row, self.last_emitted.get(row["key"]))
            if reason:
                changed.append((row, reason))

        if not changed:
            return []

        room = self._room(t)
        if len(changed) > room:
            # THE AGGREGATE. One line, and it says it is one.
            largest = max(
                changed,
                key=lambda cr: (_relative_move(cr[0].get("value"),
                                               (self.last_emitted.get(cr[0]["key"]) or {}).get("value"))
                                or 0.0))
            for row, _ in changed:
                self.last_emitted[row["key"]] = dict(row)
            self._recent.append(t)
            return [ex.make_line(
                ex.ENV, ex.PULSE,
                "{} sensors moved, largest: {} — {}".format(
                    len(changed), largest[0]["key"],
                    TRUNCATION_NOTE.format(cap=self.cap, window=self.window)),
                source_tag="sensor", reflexivity=0, kind="aggregate",
                truncated=True, moved=len(changed))]

        out = []
        for row, reason in changed:
            # THE STRUCTURED FIELDS ARE THE POINT, not decoration. A downstream
            # reader had to parse "gpu_power_w=35.1 W (moved 15%)" back out of a
            # display string to learn anything, so it did not — reflex.movers()
            # returned value=None for every sensor. value, unit and magnitude
            # travel beside the text now, and magnitude is what makes "the three
            # that moved MOST" answerable at all.
            prev = self.last_emitted.get(row["key"]) or {}
            magnitude = _relative_move(row.get("value"), prev.get("value"))
            self.last_emitted[row["key"]] = dict(row)
            self._recent.append(t)
            out.append(ex.make_line(
                ex.ENV, ex.PULSE,
                "{}={}{} ({})".format(row["key"],
                                      row.get("value"),
                                      (" " + row["unit"]) if row.get("unit") else "",
                                      reason["reason"]),
                source_tag="sensor", reflexivity=0,
                kind=reason["kind"], sensor=row["key"],
                value=row.get("value"), unit=row.get("unit", ""),
                magnitude=(round(magnitude, 4) if magnitude is not None else None),
                band=row.get("band"), why=reason["reason"]))
        return out


def run_once(producer: PulseProducer, stream_path: pathlib.Path,
             probe: Optional[dict] = None) -> list:
    """Probe, decide, append. `stream_path` is REQUIRED — no default."""
    from cockpit import somatic as som
    p = probe if probe is not None else som.probe()
    lines = producer.emit(p)
    for line in lines:
        ex.append_line(line, path=stream_path)
    return lines


def _selftest() -> int:
    print("cockpit/pulse.py --selftest")

    def row(key, value, unit="%", available=True):
        return {"key": key, "value": value, "unit": unit,
                "available": available, "disabled": False, "reason": ""}

    p = PulseProducer()
    probe1 = {"groups": {"COMPUTE": [row("cpu_percent", 40.0)]}}
    print("  first reading        {} line(s)".format(len(p.emit(probe1, now=0))))

    same = {"groups": {"COMPUTE": [row("cpu_percent", 41.0)]}}
    print("  +2.5%, same band     {} line(s)  <- must be 0".format(
        len(p.emit(same, now=1))))

    crossed = {"groups": {"COMPUTE": [row("cpu_percent", 70.0)]}}
    lines = p.emit(crossed, now=2)
    print("  band green->amber    {} line(s): {}".format(
        len(lines), lines[0]["text"] if lines else ""))

    # THE ONE THAT WAS WRONG. 85% of Wi-Fi signal is the best this laptop gets;
    # the unit table called it red because 85 is a big number in percent.
    w = PulseProducer()
    w.emit({"groups": {"NETWORK": [row("wifi_signal_pct", 60.0)]}}, now=0)
    lines = w.emit({"groups": {"NETWORK": [row("wifi_signal_pct", 85.0)]}}, now=1)
    print("  wifi 60% -> 85%      {} line(s) {}  (band_of={}; the unit table "
          "said 'amber -> red')".format(
              len(lines), lines[0]["text"] if lines else "",
              band_of(85.0, "%", "wifi_signal_pct")))
    print("  no key, no band      {}".format(band_of(85.0, "%")))

    gone = {"groups": {"COMPUTE": [row("cpu_percent", None, available=False)]}}
    lines = p.emit(gone, now=3)
    print("  became unavailable   {} line(s): {}".format(
        len(lines), lines[0]["text"] if lines else ""))

    p2 = PulseProducer(cap_per_minute=3)
    flood = {"groups": {"X": [row("k{}".format(i), 10.0) for i in range(30)]}}
    p2.emit({"groups": {"X": [row("k{}".format(i), 1.0) for i in range(30)]}}, now=0)
    lines = p2.emit(flood, now=1)
    print("  flood past the cap   {} line(s): {}".format(
        len(lines), lines[0]["text"][:88] if lines else ""))
    print("  says it truncated    {}".format(
        "TRUNCATED" in (lines[0]["text"] if lines else "")))

    s = p.spine("deduction", "12.5")
    print("  spine line           [{}|{}] {}".format(s["source"], s["depth"], s["text"]))
    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
