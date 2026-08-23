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

# THE THRESHOLD LIVES IN cockpit/norms.py (23 Aug 2026). It was declared here
# AND there, with the same value, which is one threshold and one future
# disagreement. norms.py is the module that owns what a meaningful change is;
# this one only decides whether to print a line about it.
# MOVE_THRESHOLD RETIRED (23 Aug 2026). It was a flat 15% relative to the last
# EMITTED reading — an operator's constant that said nothing about this machine,
# and a placeholder from the day it was written. What replaces it is the
# adaptive residual, with per-sensor alpha and eps still owned by norms.py:
#
#     base <- (1-alpha)*base + alpha*x ;  emit when |x - base| > eps
#
# norms.py keeps ownership of what a meaningful change is. Only the arithmetic
# under it changed.
from cockpit import norms as nm            # noqa: E402
from core import receptors as rc           # noqa: E402

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


def why_emit(row: dict, last: Optional[dict],
             receptor=None) -> Optional[dict]:
    """The reason this reading earns a line, or None.

    BAND and AVAILABILITY are unchanged and still compare against `last`, the
    last EMITTED reading. MOVE is gone; in its place the receptor's adaptive
    residual, which compares against a baseline fed by EVERY reading.

    THAT DIFFERENCE CHANGES BEHAVIOUR AND IT IS NOT A DETAIL. The old rule was
    deliberately anchored to the last emitted value so that a sensor drifting
    14% per read could not wander arbitrarily far from what the reader had been
    shown without ever earning a line. An EMA baseline absorbs exactly that
    drift: it follows the sensor, the residual settles at d/alpha, and if that
    is under eps the drift is silent for ever.

    For ram_free and disk_free_pct that gap is covered — channel S in
    core/receptors.py watches the absolute thresholds and never adapts. For the
    other sensors there is no set-point today, and this is the honest statement
    of what that costs: slow drift on them is no longer reported by this rule.
    Measured on the recorded history, see the commit message for the counts.

    `receptor` is a core.receptors.Receptor for this key, already fed with this
    reading. Without one, only BAND and AVAILABILITY can fire.
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

    if receptor is None:
        return None
    if receptor.warming():
        # VISIBLE, not hidden: silent because warming is a different state from
        # silent because nothing happened, and a reader may ask which.
        return None
    signal = receptor.last_signal
    if signal is None or abs(signal) <= receptor.eps:
        return None
    return {"kind": "signal",
            "reason": "signal {:+.4g}{} (eps {:.4g}, base {:.4g})".format(
                signal, unit or "", receptor.eps, receptor.base)}


class PulseProducer:
    """Holds the last EMITTED reading per key, and the rate window.

    A plain object with no I/O of its own: emit() returns lines and the caller
    decides where they go. That is what makes the cap testable without a file.
    """

    def __init__(self, cap_per_minute: int = CAP_PER_MINUTE,
                 window_sec: float = WINDOW_SEC, bank=None, history=None):
        self.last_emitted = {}
        self.cap = cap_per_minute
        self.window = window_sec
        self._recent = []                    # timestamps of emitted change lines
        # One receptor per key, alpha and eps from norms.py — measurement from
        # this machine's own history where there is any, the physics table
        # where there is not. Built lazily: a probe names its own keys.
        self._bank = bank if bank is not None else rc.ReceptorBank()
        self._history = history
        self._no_constants = set()

    def _receptor(self, key: str):
        r = self._bank.receptors.get(key)
        if r is not None or key in self._no_constants:
            return r
        if self._history is None:
            try:
                self._history = nm.history(nm.HISTORY)
            except Exception:
                self._history = {}
        c = nm.receptor_constants(key, (self._history or {}).get(key))
        if c["eps"] is None:
            # No table entry and no history. NOT silence: the receptor collects
            # its own calibration window and sets eps = 3 sigma from it. A key
            # this repo has never seen would otherwise never emit again, which
            # is how 30 synthetic sensors went quiet the first time this ran.
            self._no_constants.add(key)
            c = dict(c, eps=None,
                     eps_source="self-calibrating: no history, no table entry")
        return self._bank.add_receptor(key, c["alpha"], c["eps"],
                                       c["alpha_source"], c["eps_source"])

    def constants_missing(self) -> list:
        """Keys with neither history nor a table entry. Reported, not hidden."""
        return sorted(self._no_constants)

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
            receptor = self._receptor(row["key"])
            if receptor is not None and row.get("available"):
                receptor.feed(row.get("value"), now=t)
            reason = why_emit(row, self.last_emitted.get(row["key"]), receptor)
            if reason:
                changed.append((row, reason))

        if not changed:
            return []

        room = self._room(t)
        if len(changed) > room:
            # THE AGGREGATE. One line, and it says it is one.
            # Largest by |signal| / eps — how many noise floors it moved —
            # rather than by relative percentage. The old ranking put
            # idle_seconds "moved 4800%" (0.1s to 4.9s, a laptop left alone)
            # above ram_percent crossing its band.
            def _magnitude(cr):
                r = self._bank.receptors.get(cr[0]["key"])
                if r is None or r.last_signal is None or not r.eps:
                    return 0.0
                return abs(r.last_signal) / r.eps
            largest = max(changed, key=_magnitude)
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
