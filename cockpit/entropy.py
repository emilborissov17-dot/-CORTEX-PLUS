#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/entropy.py — WHAT IS ACTUALLY WEARING, IN NUMBERS.

24 Aug 2026. No simulated ageing. Nothing here is a metaphor for tiredness;
every figure is a file size, a count or a duration read off disk.

  ledger growth        bytes and rows in the append-only records, and the rate
  journal size         the same for what the brain writes
  duration vs steps    118 minutes over 56 steps is normal. 118 minutes over 10
                       is an anomaly, and the ratio is what says so - neither
                       number alone does
  INSUFFICIENT marks   how often the homeostatic layer fired an action that did
                       not move the value
  idle_seconds         how long since anything was asked of it

THE LAST ONE IS A NUMBER AND STAYS A NUMBER. `idle_seconds` is shown as
seconds. It is not called loneliness, restlessness or boredom. The reading is
"nothing has been asked of this machine for N seconds", and any word for how
that feels would be one this repo put in its mouth.

AMBIENT SENSORS ARE DECLARED, NOT BUILT. Room temperature, light and sound are
reported for readability only; the mic and camera stay behind their gates in
config_expression.yaml and this module never touches them.

Zero new sensor probes: everything is a file stat or a cached reading.

    venv/Scripts/python.exe -m cockpit.entropy
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
import time
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LEDGERS = {
    "existence_ledger": BASE / "memory" / "existence_ledger.jsonl",
    "brain_journal": BASE / "memory" / "brain_journal.jsonl",
    "divergence_log": BASE / "memory" / "divergence_log.jsonl",
    "prophecy_ledger": BASE / "experiments" / "prophecy" / "prophecy_ledger.jsonl",
    "state_vectors": BASE / "memory" / "state_vectors.jsonl",
    "merit_ledger": BASE / "memory" / "merit_ledger.jsonl",
}
HOMEOSTASIS_STATE = BASE / "memory" / "homeostasis_state.json"

# A cycle that took as long as usual while doing a fraction of the work.
NORMAL_MIN_PER_STEP = 118.0 / 56.0        # the command's own reference point


def _rows(p: pathlib.Path) -> int:
    try:
        with p.open("rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def growth() -> dict:
    """Size and row count of every append-only record, with a per-day rate."""
    out = {}
    now = time.time()
    for name, p in LEDGERS.items():
        try:
            st = p.stat()
        except OSError:
            out[name] = {"exists": False}
            continue
        rows = _rows(p)
        age_days = max((now - _oldest_ts(p, st.st_mtime)) / 86400.0, 1e-9)
        out[name] = {
            "exists": True,
            "bytes": st.st_size,
            "rows": rows,
            "age_days": round(age_days, 2),
            "bytes_per_day": round(st.st_size / age_days, 1),
            "rows_per_day": round(rows / age_days, 2),
            "last_written": datetime.fromtimestamp(
                st.st_mtime, timezone.utc).isoformat(),
        }
    return out


def _oldest_ts(p: pathlib.Path, fallback: float) -> float:
    """The timestamp of the first row, so a rate is over the file's real life."""
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
        d = json.loads(first)
        t = datetime.fromisoformat(str(d.get("ts", "")).replace("Z", "+00:00"))
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()
    except Exception:
        try:
            return p.stat().st_ctime
        except OSError:
            return fallback


def duration_against_steps(n: int = 12) -> dict:
    """118 minutes over 56 steps is normal; 118 over 10 is an anomaly.

    Neither number alone says that, so the ratio is what is reported.
    """
    out = {"cycles": [], "why": ""}
    try:
        from memory import existence_ledger as ledger
        rows = ledger.read_all()
    except Exception as exc:
        out["why"] = "{}: {}".format(type(exc).__name__, exc)
        return out
    fin = [r for r in rows if str(r.get("event", "")).upper() == "CYCLE_FINISHED"]
    for r in fin[-n:]:
        dur = r.get("duration_sec")
        if not isinstance(dur, (int, float)) or dur <= 0:
            continue
        steps = r.get("steps_completed")
        minutes = dur / 60.0
        row = {"cycle_id": r.get("cycle_id"), "minutes": round(minutes, 1),
               "steps": steps}
        if isinstance(steps, (int, float)) and steps > 0:
            row["min_per_step"] = round(minutes / steps, 2)
            row["vs_normal"] = round((minutes / steps) / NORMAL_MIN_PER_STEP, 2)
        out["cycles"].append(row)
    rated = [c["min_per_step"] for c in out["cycles"] if "min_per_step" in c]
    if rated:
        out["median_min_per_step"] = round(statistics.median(rated), 2)
    else:
        out["why"] = out["why"] or (
            "CYCLE_FINISHED rows carry duration_sec but not steps_completed, so "
            "the ratio cannot be formed - only the duration is available")
    out["normal_min_per_step"] = round(NORMAL_MIN_PER_STEP, 2)
    return out


def insufficient_marks() -> dict:
    """How often an action fired and did not move the value it was for."""
    try:
        st = json.loads(HOMEOSTASIS_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"count": 0, "marks": {}, "why": "no homeostasis state on disk"}
    marks = st.get("insufficient") or {}
    return {"count": len(marks),
            "marks": {k: v.get("at") for k, v in marks.items()},
            "why": "" if marks else "no actuator has been marked insufficient"}


def idle_seconds(last_reading: Optional[dict] = None) -> dict:
    """How long since anything was asked of it. A NUMBER, not a feeling."""
    val = None
    if last_reading:
        val = last_reading.get("idle_seconds")
    if val is None:
        try:
            from cockpit import norms as nm
            series = (nm.history(nm.HISTORY) or {}).get("idle_seconds") or []
            series = [v for v in series if isinstance(v, (int, float))]
            val = series[-1] if series else None
        except Exception:
            val = None
    return {"idle_seconds": val,
            "note": "seconds since the last input. The number is the reading; "
                    "this panel does not name a feeling for it."}


def fragmentation() -> dict:
    """Reported only if it can be read without elevation. It cannot, here."""
    return {"readable": False,
            "why": ("Windows exposes fragmentation through defrag /A, which "
                    "needs an elevated process. Not run: this panel is "
                    "read-only and unprivileged by design.")}


AMBIENT = {
    "room_temperature": {"built": False, "readable": False,
                         "why": "no thermometer on this laptop; the only "
                                "thermal sensors are CPU/GPU dies and the WMI "
                                "thermal zone needs elevation"},
    "light": {"built": False, "readable": False,
              "why": "no ambient light sensor is exposed by this hardware"},
    "sound": {"built": False, "readable": True,
              "why": "the microphone CAN be read, and stays OFF behind its "
                     "gate in config_expression.yaml. Declared, not built."},
}


def report(last_reading: Optional[dict] = None) -> dict:
    return {"panel": "entropy",
            "label": "Render of existing numbers. Mediation 1.0. Not expression.",
            "growth": growth(),
            "duration": duration_against_steps(),
            "insufficient": insufficient_marks(),
            "idle": idle_seconds(last_reading),
            "fragmentation": fragmentation(),
            "ambient": AMBIENT}


def _selftest() -> int:
    from core import event_bus as eb
    print("cockpit/entropy.py — what is actually wearing\n")
    before = eb.probe_count()
    d = report()
    ok = eb.probe_count() == before
    print("  {}  zero new sensor probes".format("OK  " if ok else "FAIL"))

    print("\n  GROWTH")
    for name, g in sorted(d["growth"].items()):
        if not g.get("exists"):
            print("    {:<20} absent".format(name))
            continue
        print("    {:<20} {:>10,} bytes  {:>6,} rows  {:>10,.0f} B/day  "
              "{:>7.1f} rows/day".format(name, g["bytes"], g["rows"],
                                         g["bytes_per_day"], g["rows_per_day"]))

    print("\n  DURATION vs STEPS   (normal {} min/step)".format(
        d["duration"]["normal_min_per_step"]))
    for c in d["duration"]["cycles"][-6:]:
        print("    {:>7.1f} min over {} step(s){}".format(
            c["minutes"], c["steps"],
            "  = {} min/step, {}x normal".format(c["min_per_step"],
                                                 c["vs_normal"])
            if "min_per_step" in c else "  - no step count recorded"))
    if d["duration"].get("why"):
        print("    note: {}".format(d["duration"]["why"]))

    print("\n  INSUFFICIENT marks: {}  ({})".format(
        d["insufficient"]["count"], d["insufficient"]["why"] or "listed above"))
    print("  idle_seconds      : {}".format(d["idle"]["idle_seconds"]))
    print("  fragmentation     : {}".format(d["fragmentation"]["why"][:70]))
    print("\n  AMBIENT (declared, not built)")
    for k, v in AMBIENT.items():
        print("    {:<18} readable={:<6} {}".format(k, str(v["readable"]),
                                                    v["why"][:60]))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
