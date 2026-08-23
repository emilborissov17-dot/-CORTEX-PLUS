#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/receptors.py — TWO CHANNELS THAT NEVER MIX.

23 Aug 2026.

Each defended or watched variable gets two independent channels:

  CHANNEL R — the receptor. Adaptive. Emits CHANGE, not value.
        base   <- (1 - alpha) * base + alpha * x
        signal <- x - base
        emit only if |signal| > eps

  CHANNEL S — the set-point. No adaptation, ever. The absolute thresholds
        already in config/homeostasis.json, read through core/homeostasis.py.

WHY BOTH, AND THIS IS THE CORRECTION THAT SAVES THE DESIGN
------------------------------------------------------------
AN EMA WITH A FIXED ALPHA CANNOT EXPRESS "SLOWLY APPROACHING A LIMIT", and the
arithmetic is worth writing down because it is slightly worse than the usual
telling of it.

Feed this receptor a steady ramp of d units per tick. The residual does not
grow and it does not vanish; it settles at a constant, and because `signal` is
measured against the PRE-update baseline that constant is

    steady-state |signal|  =  d / alpha          (measured, not just derived —
                                                  see the ramp tests)

So there are two regimes and BOTH are useless for catching a slow slide:

    d/alpha <= eps    R is silent for ever. The disk fills at 1% a day, the
                      receptor never fires, and the first news is that the disk
                      is full. This is the failure the two-channel design was
                      specified to prevent.

    d/alpha >  eps    R fires on EVERY TICK, for ever, with the same value. A
                      permanent alarm that never changes is indistinguishable
                      from a stuck sensor, and it is the reading a human stops
                      looking at by the second day.

Neither regime says "getting closer". That is not a tuning problem to be solved
by picking a better alpha — alpha only moves the boundary between the two
failures. R is for DYNAMICS: it answers "did something just change". Only an
absolute set-point answers "where are we against the limit".

So R is for dynamics and S is for catastrophe, and expecting one channel to
catch both is expecting the ear to measure blood pressure. S never adapts,
which is the whole reason it is a separate channel and not a mode of the first.
The ramp tests in test/test_receptors.py are the proof and they are the point
of the file: a ramp under d/alpha <= eps emits NOTHING on R while S crosses
notice, action and gate exactly on schedule.

WARMUP, AND IT IS MANDATORY
-----------------------------
This system runs about two hours a day. On a cold start every baseline is zero,
every first reading is therefore a signal the size of the reading itself, and
the first fifty events scream together. "The steady state is silence" is false
until the baselines have settled.

  * baselines are serialised at clean shutdown and loaded as the SEED next time;
  * with a seed: WARMUP_SECONDS of warmup_phase — events feed the baseline and
    are NOT emitted;
  * with no seed: CALIBRATION_TICKS of silent calibration;
  * the warmup state is VISIBLE. A consumer can always tell "silent because
    nothing happened" from "silent because warming up", because phase() says
    which, and every suppressed event is counted.

THE SOURCE LIMIT IS A HARD CAP
--------------------------------
At most MAX_HIGH_FREQUENCY push sources and MAX_LOW_FREQUENCY low-frequency
ones. Eight in total. One ETW disk callback can produce 10,000 events a second
under load and each callback is a kernel-to-user context switch; past roughly
twelve threads the GIL starts to bite. register_source() refuses the ninth.

alpha and eps come from cockpit/norms.py, which owns what a meaningful change
is. Measurement beats the physics table wherever this machine has history.

    venv/Scripts/python.exe core/receptors.py --report     # read-only
    venv/Scripts/python.exe core/receptors.py --selftest
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any, Callable, Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import event_bus as eb                        # noqa: E402

SEED_PATH = BASE / "memory" / "receptor_baselines.json"

WARMUP_SECONDS = 5 * 60.0        # with a seed
CALIBRATION_TICKS = 30           # without one

PHASE_CALIBRATING = "calibrating"   # no seed: silent for CALIBRATION_TICKS
PHASE_WARMUP = "warmup"             # seeded: silent for WARMUP_SECONDS
PHASE_LIVE = "live"

# The hard cap. Eight total.
MAX_HIGH_FREQUENCY = 3           # network, ETW disk, WMI thermal
MAX_LOW_FREQUENCY = 5            # battery, power, file changes, registry, firewall
HIGH, LOW = "high", "low"


class TooManySources(Exception):
    """The ninth source. See the cap and the reason above it."""


# ---------------------------------------------------------------------------
# Channel R
# ---------------------------------------------------------------------------

class Receptor:
    """One sensor, one adaptive baseline, one publisher on the bus."""

    def __init__(self, key: str, alpha: float, eps: float,
                 alpha_source: str = "", eps_source: str = "",
                 unit: str = "", seed: Optional[dict] = None,
                 bus: Optional[eb.EventBus] = None,
                 warmup_seconds: float = WARMUP_SECONDS,
                 calibration_ticks: int = CALIBRATION_TICKS):
        self.key = key
        self.alpha = float(alpha)
        # eps=None means SELF-CALIBRATING. A sensor this repo has never seen has
        # no history to measure and no entry in the physics table, and the
        # alternative to calibrating is being silent for ever — which is what
        # happened to 30 synthetic keys the first time this ran. So it collects
        # its own calibration window and sets eps = 3 sigma from what it saw,
        # which is exactly the fallback rule the table itself prescribes.
        self.eps = None if eps is None else float(eps)
        self._calibrating_values = []
        self.alpha_source = alpha_source
        self.eps_source = eps_source
        self.unit = unit
        self.bus = bus if bus is not None else eb.BUS

        self.base: Optional[float] = None
        self.last: Optional[float] = None
        # The residual from the most recent feed(), kept so a consumer can ask
        # "why" without recomputing it against a baseline that has since moved.
        self.last_signal: Optional[float] = None
        self.ticks = 0
        self.emitted = 0
        self.suppressed_warmup = 0
        self.suppressed_quiet = 0

        self._warmup_seconds = float(warmup_seconds)
        self._calibration_ticks = int(calibration_ticks)
        self._started: Optional[float] = None

        self.seeded = False
        if seed and isinstance(seed.get("base"), (int, float)):
            self.base = float(seed["base"])
            self.seeded = True
            self.seed_ts = seed.get("ts")
        else:
            self.seed_ts = None

        self.bus.register_publisher(self.topic, "receptor:" + key)

    # -- identity -----------------------------------------------------------

    @property
    def topic(self) -> str:
        return "receptor.{}".format(self.key)

    def phase(self, now: Optional[float] = None) -> str:
        """VISIBLE, never hidden. A consumer must be able to tell 'silent
        because nothing happened' from 'silent because warming up'."""
        now = time.monotonic() if now is None else now
        if self.eps is None:
            return PHASE_CALIBRATING     # no threshold yet: it cannot judge
        if not self.seeded:
            return PHASE_LIVE if self.ticks >= self._calibration_ticks \
                else PHASE_CALIBRATING
        if self._started is None:
            return PHASE_WARMUP
        return PHASE_LIVE if (now - self._started) >= self._warmup_seconds \
            else PHASE_WARMUP

    def warming(self, now: Optional[float] = None) -> bool:
        return self.phase(now) != PHASE_LIVE

    # -- the channel --------------------------------------------------------

    def feed(self, value: Any, now: Optional[float] = None) -> Optional[eb.Event]:
        """One reading in. Returns the published Event, or None.

        None has two meanings and they are distinguishable through phase():
        the signal was under eps, or the receptor is still warming.
        """
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        now = time.monotonic() if now is None else now
        if self._started is None:
            self._started = now

        if self.base is None:
            self.base = x                  # first ever reading IS the baseline
            self.last = x
            self.last_signal = 0.0
            if self.eps is None:
                # It counts toward the calibration window too. Leaving it out
                # made a 20-tick window need 21 ticks and never close.
                self._calibrating_values.append(x)
            self.ticks += 1
            self.suppressed_warmup += 1
            return None

        if self.eps is None:
            self._calibrating_values.append(x)
            if len(self._calibrating_values) >= self._calibration_ticks:
                self._finish_calibration()

        signal = x - self.base
        self.last_signal = signal
        # The baseline is fed by EVERY reading, warming or not. That is what
        # warming up MEANS: the events are used, they are simply not emitted.
        self.base = (1.0 - self.alpha) * self.base + self.alpha * x
        self.last = x
        self.ticks += 1

        if self.warming(now):
            self.suppressed_warmup += 1
            return None
        if abs(signal) <= self.eps:
            self.suppressed_quiet += 1
            return None

        self.emitted += 1
        return self.bus.publish(
            self.topic, x, eb.CHANNEL_R,
            meta={"signal": signal, "base": self.base, "eps": self.eps,
                  "alpha": self.alpha, "unit": self.unit,
                  "key": self.key, "ticks": self.ticks},
            ts=now)

    # -- persistence --------------------------------------------------------

    def _finish_calibration(self) -> None:
        """eps = 3 sigma of the calibration window it just collected."""
        from cockpit import norms as nm
        vals = self._calibrating_values
        mean = sum(vals) / len(vals)
        sigma = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        self.eps = max(nm.EPS_SIGMA_MULTIPLE * sigma, nm.EPS_ZERO_FLOOR)
        self.eps_source = ("self-calibrated at runtime: {} sigma over {} "
                           "ticks".format(nm.EPS_SIGMA_MULTIPLE, len(vals)))
        self._calibrating_values = []

    def seed_record(self) -> dict:
        return {"base": self.base, "ticks": self.ticks,
                "alpha": self.alpha, "eps": self.eps,
                "ts": time.time()}

    def stats(self) -> dict:
        return {"key": self.key, "topic": self.topic, "phase": self.phase(),
                "seeded": self.seeded, "base": self.base, "last": self.last,
                "alpha": self.alpha, "alpha_source": self.alpha_source,
                "eps": self.eps, "eps_source": self.eps_source,
                "ticks": self.ticks, "emitted": self.emitted,
                "suppressed_warmup": self.suppressed_warmup,
                "suppressed_quiet": self.suppressed_quiet}

    def __repr__(self) -> str:
        return "Receptor({} alpha={} eps={} {})".format(
            self.key, self.alpha, round(self.eps, 4), self.phase())


# ---------------------------------------------------------------------------
# Channel S — the set-point. NEVER adapts.
# ---------------------------------------------------------------------------

class SetPoint:
    """Absolute thresholds from config/homeostasis.json. No memory, no EMA.

    S exists precisely because R cannot be trusted with a slow ramp. It has no
    baseline to hide behind: it compares the value to a number a human approved
    and signed, and it will still be comparing it to that number a year from
    now.
    """

    def __init__(self, key: str, levels: dict, unit: str = "",
                 bus: Optional[eb.EventBus] = None):
        self.key = key
        self.levels = dict(levels)
        self.unit = unit
        self.bus = bus if bus is not None else eb.BUS
        self.last_level: Optional[str] = None
        self.emitted = 0
        self.bus.register_publisher(self.topic, "setpoint:" + key)

    @property
    def topic(self) -> str:
        return "setpoint.{}".format(self.key)

    def level_for(self, value: float) -> Optional[str]:
        """Lowest-is-worse: notice, then action, then gate."""
        held = None
        for name in ("notice", "action", "gate"):
            if name in self.levels and value <= self.levels[name]:
                held = name
        return held

    def feed(self, value: Any, now: Optional[float] = None) -> Optional[eb.Event]:
        """Emits on a LEVEL CHANGE. There is no eps and no warmup: a set-point
        that needed to warm up would be silent exactly when it mattered."""
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        level = self.level_for(x)
        if level == self.last_level:
            return None
        was, self.last_level = self.last_level, level
        self.emitted += 1
        return self.bus.publish(
            self.topic, x, eb.CHANNEL_S,
            meta={"level": level, "was": was, "levels": self.levels,
                  "unit": self.unit, "key": self.key},
            ts=time.monotonic() if now is None else now)

    def stats(self) -> dict:
        return {"key": self.key, "topic": self.topic, "levels": self.levels,
                "level": self.last_level, "emitted": self.emitted,
                "adapts": False}


# ---------------------------------------------------------------------------
# The bank
# ---------------------------------------------------------------------------

class ReceptorBank:
    """Every receptor and set-point, the seed file, and the source cap."""

    def __init__(self, bus: Optional[eb.EventBus] = None,
                 seed_path: Optional[pathlib.Path] = None):
        self.bus = bus if bus is not None else eb.BUS
        self.seed_path = pathlib.Path(seed_path or SEED_PATH)
        self.receptors: dict = {}
        self.setpoints: dict = {}
        self.sources: dict = {}          # name -> HIGH | LOW
        self._seed = self._load_seed()

    # -- seeds --------------------------------------------------------------

    def _load_seed(self) -> dict:
        try:
            blob = json.loads(self.seed_path.read_text(encoding="utf-8"))
            return blob.get("receptors", {}) if isinstance(blob, dict) else {}
        except Exception:
            return {}

    def save_seed(self) -> bool:
        """Called at clean shutdown. Durable: the seed is what stops tomorrow's
        first fifty events from screaming together."""
        try:
            doc = {"ts": time.time(),
                   "receptors": {k: r.seed_record()
                                 for k, r in self.receptors.items()
                                 if r.base is not None}}
            self.seed_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.seed_path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.seed_path)
            return True
        except Exception:
            return False

    # -- the cap ------------------------------------------------------------

    def register_source(self, name: str, frequency: str) -> str:
        """Refuse the ninth. See MAX_HIGH_FREQUENCY / MAX_LOW_FREQUENCY."""
        if frequency not in (HIGH, LOW):
            raise ValueError("frequency must be {!r} or {!r}".format(HIGH, LOW))
        if name in self.sources:
            return name
        cap = MAX_HIGH_FREQUENCY if frequency == HIGH else MAX_LOW_FREQUENCY
        have = sum(1 for f in self.sources.values() if f == frequency)
        if have >= cap:
            raise TooManySources(
                "{} {}-frequency sources already registered ({}); the cap is {}. "
                "One ETW callback can produce 10,000 events a second and each is "
                "a kernel-to-user context switch.".format(
                    have, frequency,
                    ", ".join(n for n, f in self.sources.items() if f == frequency),
                    cap))
        self.sources[name] = frequency
        return name

    # -- construction -------------------------------------------------------

    def add_receptor(self, key: str, alpha: float, eps: float,
                     alpha_source: str = "", eps_source: str = "",
                     unit: str = "", **kw) -> Receptor:
        r = Receptor(key, alpha, eps, alpha_source, eps_source, unit,
                     seed=self._seed.get(key), bus=self.bus, **kw)
        self.receptors[key] = r
        return r

    def add_setpoint(self, key: str, levels: dict, unit: str = "") -> SetPoint:
        s = SetPoint(key, levels, unit, bus=self.bus)
        self.setpoints[key] = s
        return s

    # -- use ----------------------------------------------------------------

    def feed(self, key: str, value: Any, now: Optional[float] = None) -> dict:
        """One reading into BOTH channels. They never mix: R sees change, S
        sees the absolute value, and neither knows about the other."""
        out = {"R": None, "S": None}
        r = self.receptors.get(key)
        if r is not None:
            out["R"] = r.feed(value, now)
        s = self.setpoints.get(key)
        if s is not None:
            out["S"] = s.feed(value, now)
        return out

    def phases(self) -> dict:
        return {k: r.phase() for k, r in self.receptors.items()}

    def warming(self) -> bool:
        return any(r.warming() for r in self.receptors.values())

    def stats(self) -> dict:
        return {
            "receptors": {k: r.stats() for k, r in self.receptors.items()},
            "setpoints": {k: s.stats() for k, s in self.setpoints.items()},
            "sources": dict(self.sources),
            "source_capacity": {
                HIGH: "{}/{}".format(
                    sum(1 for f in self.sources.values() if f == HIGH),
                    MAX_HIGH_FREQUENCY),
                LOW: "{}/{}".format(
                    sum(1 for f in self.sources.values() if f == LOW),
                    MAX_LOW_FREQUENCY)},
            "seed": {"path": str(self.seed_path),
                     "exists": self.seed_path.exists(),
                     "seeded": sorted(k for k, r in self.receptors.items()
                                      if r.seeded)},
        }


# ---------------------------------------------------------------------------
# Building the live bank from what this repo already knows
# ---------------------------------------------------------------------------

def build(bus: Optional[eb.EventBus] = None,
          history: Optional[dict] = None,
          seed_path: Optional[pathlib.Path] = None,
          include_setpoints: bool = True) -> ReceptorBank:
    """A bank with alpha and eps from cockpit/norms.py — measurement first."""
    bank = ReceptorBank(bus=bus, seed_path=seed_path)

    from cockpit import norms as nm
    if history is None:
        try:
            history = nm.history(nm.HISTORY)
        except Exception:
            history = {}

    for key in sorted(history or {}):
        c = nm.receptor_constants(key, history.get(key))
        if c["eps"] is None:
            continue                      # no table entry and no history
        bank.add_receptor(key, c["alpha"], c["eps"],
                          c["alpha_source"], c["eps_source"])

    if include_setpoints:
        try:
            from core import homeostasis as h
            cfg = h.load_config()
            for key, spec in cfg["variables"].items():
                bank.add_setpoint(key, spec["levels"], spec.get("unit", ""))
        except Exception:
            pass
    return bank


def _report() -> int:
    bank = build()
    st = bank.stats()
    print("core/receptors.py — READ ONLY. No cycle is started.\n")
    print("  CHANNEL R — adaptive, emits change")
    print("  {:<22} {:>7} {:>14}  {}".format("sensor", "alpha", "eps", "where eps came from"))
    print("  " + "-" * 92)
    table, measured = 0, 0
    for k in sorted(st["receptors"]):
        r = st["receptors"][k]
        src = r["eps_source"]
        if src.startswith("measured"):
            measured += 1
        else:
            table += 1
        print("  {:<22} {:>7} {:>14} {}".format(
            k, r["alpha"], round(r["eps"], 4), src[:58]))
    print("\n  {} receptor(s): {} eps measured from this machine, {} from the "
          "table".format(len(st["receptors"]), measured, table))

    print("\n  CHANNEL S — absolute, never adapts")
    for k in sorted(st["setpoints"]):
        s = st["setpoints"][k]
        print("  {:<22} {}".format(k, s["levels"]))
    if not st["setpoints"]:
        print("    (none — config/homeostasis.json could not be read)")

    print("\n  sources   high {}   low {}".format(
        st["source_capacity"][HIGH], st["source_capacity"][LOW]))
    print("  seed      {}  exists={}".format(
        st["seed"]["path"], st["seed"]["exists"]))
    print("  seeded    {}".format(st["seed"]["seeded"] or "(none — a cold start "
                                  "calibrates silently for 30 ticks)"))
    return 0


def _selftest() -> int:
    print("core/receptors.py --selftest\n")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    bus = eb.EventBus()
    bank = ReceptorBank(bus=bus, seed_path=BASE / "memory" / "_no_such_seed.json")
    r = bank.add_receptor("t", alpha=0.2, eps=1.0, calibration_ticks=3)
    check("a cold receptor starts calibrating", r.phase() == PHASE_CALIBRATING)
    for _ in range(5):
        r.feed(100.0)
    check("and goes live after its calibration ticks", r.phase() == PHASE_LIVE)
    check("a constant input is silent", r.emitted == 0)
    ev = r.feed(150.0)
    check("a step change emits", ev is not None and ev.channel == "R")
    check("the event carries the signal",
          ev and abs(ev.meta["signal"] - 50.0) < 1e-6)

    # the ramp — the whole point of two channels
    bus2 = eb.EventBus()
    bank2 = ReceptorBank(bus=bus2, seed_path=BASE / "memory" / "_no_such_seed.json")
    # d/alpha = 1/0.2 = 5, and eps is 6 — the regime where R goes silent.
    ramp = bank2.add_receptor("disk", alpha=0.2, eps=6.0, calibration_ticks=3)
    sp = bank2.add_setpoint("disk", {"notice": 28, "action": 15, "gate": 5}, "%")
    value, crossed = 100.0, []
    for _ in range(120):
        value -= 1.0
        out = bank2.feed("disk", value)
        if out["S"] is not None:
            crossed.append((round(value), out["S"].meta["level"]))
    check("a ramp under d/alpha <= eps emits NOTHING on R", ramp.emitted == 0)
    check("and crosses S on schedule",
          crossed == [(28, "notice"), (15, "action"), (5, "gate")])
    check("S never adapts", sp.stats()["adapts"] is False)

    # the other regime, and it is no better
    b4 = ReceptorBank(bus=eb.EventBus(),
                      seed_path=BASE / "memory" / "_no_such_seed.json")
    loud = b4.add_receptor("d2", alpha=0.2, eps=2.0, calibration_ticks=3)
    v = 1000.0
    for _ in range(60):
        v -= 1.0
        loud.feed(v)
    check("a ramp over d/alpha > eps emits on EVERY tick instead",
          loud.emitted >= 50)
    check("and always the same signal, which is not 'getting closer'",
          abs(abs(loud.feed(v - 1).meta["signal"]) - 1.0 / 0.2) < 0.01)

    # the cap
    b3 = ReceptorBank(bus=eb.EventBus())
    for i in range(3):
        b3.register_source("hi{}".format(i), HIGH)
    try:
        b3.register_source("hi3", HIGH)
        check("the fourth high-frequency source is refused", False)
    except TooManySources:
        check("the fourth high-frequency source is refused", True)

    print("\n  {}".format("every check passed" if ok else "SOMETHING FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    raise SystemExit(_report())


# ═══════════════════════════════════════════════════════════════════════════
# THE SOURCES THAT ARE FREE AND ALREADY AVAILABLE
# ═══════════════════════════════════════════════════════════════════════════
#
# WMI thermal and ETW disk are DECLARED, NOT BUILT. Part 0 measured what they
# cost: MSAcpi_ThermalZoneTemperature returns "Access denied" without an
# elevated process, and ETW needs a session and a callback thread. Neither is
# free, so neither is wired. See docs/HOMEOSTASIS_STATUS.md.
#
# These three are free: the files and counters already exist and reading them
# is a file read or a psutil call on data the OS is keeping anyway.

FIREWALL_LOG = pathlib.Path(
    r"C:\Windows\System32\LogFiles\Firewall\pfirewall.log")


def read_firewall_drops(path: Optional[pathlib.Path] = None,
                        since_offset: int = 0) -> dict:
    """Tail the Windows Firewall log. LOW frequency: one file read.

    The log's own header names the fields, and the last two are `path` and
    `pid` — so a dropped connection can be attributed to a process. Every row
    on this machine today is a DROP, and most of it is multicast background
    noise from the router. It is "blocked connections", never "attacks".
    """
    p = pathlib.Path(path or FIREWALL_LOG)
    out = {"available": False, "rows": [], "count": 0, "offset": since_offset,
           "why": ""}
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out["why"] = "{}: {}".format(type(exc).__name__, exc)
        return out
    out["available"] = True
    lines = raw.splitlines()
    fields = []
    for ln in lines:
        if ln.startswith("#Fields:"):
            fields = ln.split()[1:]
            break
    data = [ln for ln in lines if ln and not ln.startswith("#")]
    out["count"] = len(data)
    new = data[since_offset:] if since_offset < len(data) else []
    out["offset"] = len(data)
    for ln in new:
        parts = ln.split()
        if len(parts) < 3:
            continue
        out["rows"].append(dict(zip(fields, parts)) if fields
                           else {"raw": ln})
    return out


def read_network_counters() -> dict:
    """Bytes and packets since boot. LOW frequency: one psutil call."""
    import psutil
    c = psutil.net_io_counters()
    return {"bytes_sent": c.bytes_sent, "bytes_recv": c.bytes_recv,
            "packets_sent": c.packets_sent, "packets_recv": c.packets_recv,
            "errin": c.errin, "errout": c.errout,
            "dropin": c.dropin, "dropout": c.dropout}


def read_file_change_count(paths=None) -> dict:
    """How many files changed under the watched roots since the last call.

    LOW frequency, and deliberately a COUNT rather than a watcher: a real
    ReadDirectoryChangesW watcher is a thread per root and a callback per
    event, which is the kind of source the cap exists to ration. A stat sweep
    of a bounded directory list costs one syscall per file and no thread.
    """
    roots = [pathlib.Path(p) for p in (paths or [BASE / "memory"])]
    newest, count = 0.0, 0
    for root in roots:
        if not root.is_dir():
            continue
        for f in root.glob("*"):
            try:
                if f.is_file():
                    count += 1
                    newest = max(newest, f.stat().st_mtime)
            except OSError:
                continue
    return {"files": count, "newest_mtime": newest}


FREE_SOURCES = {
    "firewall_log":     (LOW, read_firewall_drops),
    "network_counters": (LOW, read_network_counters),
    "file_changes":     (LOW, read_file_change_count),
}

# Declared, not built. Each with the reason Part 0 measured.
DECLARED_SOURCES = {
    "wmi_thermal": (HIGH, "MSAcpi_ThermalZoneTemperature returns Access denied "
                          "without elevation; Win32_TemperatureProbe has no "
                          "instances on this hardware"),
    "etw_disk":    (HIGH, "needs an ETW session and a callback thread; one "
                          "callback can produce 10,000 events/second"),
}


def wire_free_sources(bank: "ReceptorBank") -> dict:
    """Register the three that cost nothing. Returns what was registered."""
    done = {}
    for name, (freq, _fn) in FREE_SOURCES.items():
        try:
            bank.register_source(name, freq)
            done[name] = freq
        except TooManySources as exc:
            done[name] = "REFUSED: {}".format(exc)
    return done
