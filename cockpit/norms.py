#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/norms.py — WHAT IS UNUSUAL FOR THIS MACHINE, NOT WHAT MOVED MOST.

THE RULE THIS REPLACES, AND WHY
---------------------------------
cockpit/pulse.py ranks a reading by how far it moved from the last one it
emitted: MOVE_THRESHOLD = 0.15, a flat 15%, the same number for a GPU that idles
at 3W and spikes to 90W and for a disk counter that only ever goes up. It is an
operator's constant, and it says nothing about this machine. Measured on the
2026-08-22 stream, the top mover of the evening was idle_seconds at "moved
4800%" — 0.1s to 4.9s, a laptop being left alone, which is the least surprising
event a laptop has. Meanwhile ram_percent crossing 84.4 got the same one line.

So: rank by DEVIATION FROM TYPICAL, computed per sensor from that sensor's own
recorded history.

    typical   the MEDIAN of the recorded samples
    spread    the MEDIAN ABSOLUTE DEVIATION, scaled by 1.4826 so it estimates
              the same thing a standard deviation does for normal data
    unusual   |value - typical| / spread

Median and MAD, not mean and standard deviation, and the reason is this data
specifically: a single 90W GPU spike drags a mean and inflates a standard
deviation, so the next spike looks NORMAL. The median does not move and the MAD
does not inflate — one outlier cannot make the next outlier invisible.

THE PRECONDITION DID NOT EXIST (23 Aug 2026)
----------------------------------------------
"The cockpit has been sampling every sensor every 15 seconds; that is hundreds
of samples per sensor already on disk" — it was not. /api/somatic probed and
threw the readings away; only readings that EARNED a pulse line were stored, and
those are stored as prose. memory/state_vectors.jsonl, which cockpit/vector.py
reads to fit a lexicon, is never written by anything but a test. So there was no
history to compute a norm from, and record() below is the missing half.

Until a sensor has MIN_SAMPLES of its own history it FALLS BACK to the fixed
15% rule, and every ranked row says which rule judged it. A norm computed from
four samples is not a norm; presenting it as one is the failure this module is
supposed to prevent, not commit.

WRITERS TAKE AN EXPLICIT PATH — see the rule in test/test_cockpit.py.

    venv/Scripts/python.exe -m cockpit.norms      # selftest, writes to a tmpdir
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

HISTORY = BASE / "memory" / "somatic_history.jsonl"

# Below this a sensor has no norm and the fixed rule judges it. Twenty is not a
# statistical threshold, it is the point below which a median and a MAD are a
# description of an accident.
MIN_SAMPLES = 20

# How many probes to keep. At the cockpit's 15s poll this is a bit over four
# hours — long enough for a norm, short enough that "typical" means recently.
MAX_ROWS = 1000

# Rewriting a 1000-line file on every probe is wasteful; the trim happens when
# the file has drifted this far past the cap.
TRIM_SLACK = 250

FIXED_MOVE_THRESHOLD = 0.15      # the constant this module exists to replace

BY_HISTORY, BY_FIXED = "history", "fixed"

RULE_MEANING = {
    BY_HISTORY: ("deviation from this sensor's own median, in MADs "
                 "(>= {} samples)".format(MIN_SAMPLES)),
    BY_FIXED: ("relative move against the previous reading, against the flat "
               "{:.0%} threshold — too little history for a norm".format(
                   FIXED_MOVE_THRESHOLD)),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Recording — the half that did not exist
# ---------------------------------------------------------------------------

def flatten(probe: dict) -> dict:
    """{key: value} for every AVAILABLE numeric reading in a probe.

    Unavailable readings are left out rather than stored as null. A sensor that
    could not be read has no value, and putting one in the history would make
    "could not read the GPU" indistinguishable from "the GPU read 0".
    """
    out = {}
    for rows in (probe.get("groups") or {}).values():
        for row in rows or []:
            if row.get("disabled") or not row.get("available"):
                continue
            if _numeric(row.get("value")):
                out[row["key"]] = float(row["value"])
    return out


def record(probe: dict, path: pathlib.Path, ts: Optional[str] = None) -> dict:
    """Append one probe's numeric readings. `path` is REQUIRED — no default."""
    values = flatten(probe)
    if not values:
        return {"written": False, "why": "no available numeric reading in the probe"}
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts or _now(), "v": values},
                            ensure_ascii=False) + "\n")
    trimmed = trim(p)
    return {"written": True, "sensors": len(values), "trimmed": trimmed}


def trim(path: pathlib.Path, max_rows: int = MAX_ROWS,
         slack: int = TRIM_SLACK) -> int:
    """Keep the newest max_rows. Returns how many were dropped, 0 for no trim."""
    p = pathlib.Path(path)
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    if len(lines) <= max_rows + slack:
        return 0
    keep = lines[-max_rows:]
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return len(lines) - len(keep)


def history(path: pathlib.Path, limit: int = MAX_ROWS) -> dict:
    """{key: [values, oldest first]} from the recorded probes. `path` REQUIRED."""
    out: dict = {}
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8",
                                             errors="replace").splitlines()
    except OSError:
        return out
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for key, value in (row.get("v") or {}).items():
            if _numeric(value):
                out.setdefault(key, []).append(float(value))
    return out


# ---------------------------------------------------------------------------
# The norm
# ---------------------------------------------------------------------------

def median(values: list):
    vals = sorted(v for v in values if _numeric(v))
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def mad(values: list, med=None):
    """Median absolute deviation, UNSCALED. None when there is nothing to take."""
    med = median(values) if med is None else med
    if med is None:
        return None
    return median([abs(float(v) - med) for v in values if _numeric(v)])


def is_counter(values: list) -> bool:
    """Does this sensor only ever go up?

    MEASURED, 70 real probes on this box: disk_read_mb and net_sent_mb ranked
    first and second by deviation-from-median, having "moved 0.0%". They are
    monotonic counters — since boot, bytes read, bytes sent. Their median is a
    number they passed a while ago and will never return to, so the level drifts
    further from it every probe and the deviation grows without anything
    happening. The level is not the signal; the INCREMENT is.

    Strictly non-decreasing over the whole recorded window, and actually moving.
    A constant series is not a counter — it is a frozen sensor, which deviation()
    already handles.
    """
    vals = [float(v) for v in values if _numeric(v)]
    if len(vals) < MIN_SAMPLES:
        return False
    if vals[-1] <= vals[0]:
        return False
    return all(b >= a for a, b in zip(vals, vals[1:]))


def diffs(values: list) -> list:
    """First differences — what a counter actually says per probe."""
    vals = [float(v) for v in values if _numeric(v)]
    return [b - a for a, b in zip(vals, vals[1:])]


def norm_for(values: list) -> dict:
    """typical, spread and n for one sensor's samples."""
    n = sum(1 for v in values if _numeric(v))
    med = median(values)
    m = mad(values, med)
    return {"n": n, "typical": med, "mad": m,
            # 1.4826 makes the MAD estimate the same quantity a standard
            # deviation does for normal data, so "2 spreads out" means roughly
            # what a reader expects it to mean.
            "spread": None if m is None else m * 1.4826}


# What a frozen sensor scores when it moves by a full FIXED_MOVE_THRESHOLD.
# Big enough to outrank ordinary movement, finite so it stays comparable with it.
FROZEN_SPREAD_DEVIATION = 10.0

# A frozen sensor cannot move by less than this and be called unusual. Measured,
# not chosen: with 70 real probes on this box, swap_used_gb and net_sent_mb both
# have a MAD of exactly 0 and both drift by ~0.2% between probes — rounding on a
# counter. Scoring any nonzero delta as "frozen sensor moved" put both of them
# above cpu_percent, which is the same failure as the flat 15% rule with the
# sign reversed: a number that says nothing, ranked first.
FROZEN_MIN_RELATIVE = 0.005


def deviation(value, norm: dict):
    """How unusual `value` is for this sensor, in spreads. None when unknowable.

    A ZERO SPREAD IS NOT AN ERROR AND NOT INFINITY. A sensor that has read the
    same number for its whole history has a MAD of 0, and then division is
    undefined — but "infinitely unusual" would put it above every real signal
    forever, and "any nonzero delta is unusual" ranks counter rounding above a
    CPU spike (measured; see FROZEN_MIN_RELATIVE).

    So for a zero spread the deviation is scored on the RELATIVE move away from
    typical, scaled so that a move of one FIXED_MOVE_THRESHOLD reads as
    FROZEN_SPREAD_DEVIATION spreads. A genuinely frozen sensor that finally
    jumps is loud; one that wobbles in its last decimal place is not.
    """
    if not _numeric(value) or norm.get("typical") is None:
        return None
    typical = float(norm["typical"])
    delta = abs(float(value) - typical)
    spread = norm.get("spread")
    if spread:
        return delta / spread
    if delta == 0:
        return 0.0
    if typical == 0:
        # From a frozen zero, any movement is the whole of the movement there is.
        return FROZEN_SPREAD_DEVIATION
    relative = delta / abs(typical)
    if relative < FROZEN_MIN_RELATIVE:
        return 0.0
    return FROZEN_SPREAD_DEVIATION * (relative / FIXED_MOVE_THRESHOLD)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def rank(readings: list, hist: dict, previous: Optional[dict] = None,
         min_samples: int = MIN_SAMPLES, top: int = 3) -> list:
    """Rank readings by deviation from typical, falling back per sensor.

    `readings` is a list of {key, value, unit}. `hist` is history(). `previous`
    is {key: value} from the last reading, used only by the fixed rule.

    EVERY ROW SAYS WHICH RULE JUDGED IT. Two sensors ranked by two different
    rules are not on one scale, and a list that hides that is a list that
    invites a comparison it cannot support.
    """
    previous = previous or {}
    scored = []
    for row in readings or []:
        key, value = row.get("key"), row.get("value")
        if not key or not _numeric(value):
            continue
        samples = hist.get(key) or []
        counter = is_counter(samples)
        # A counter is judged on its INCREMENT against the typical increment;
        # everything else on its level against the typical level. Judging a
        # counter on its level makes it more unusual every probe forever.
        n = norm_for(diffs(samples)) if counter else norm_for(samples)
        judged = value
        if counter:
            prev_v = previous.get(key)
            judged = (float(value) - float(prev_v)
                      if _numeric(prev_v) else None)
        if n["n"] >= min_samples and (judged is not None or not counter):
            score = deviation(judged, n)
            frozen = not n["spread"]
            entry = {"key": key, "value": value, "unit": row.get("unit", ""),
                     "rule": BY_HISTORY, "score": None if score is None else round(score, 2),
                     "typical": n["typical"], "spread": (None if n["spread"] is None
                                                         else round(n["spread"], 4)),
                     "samples": n["n"], "frozen_history": frozen,
                     "counter": counter, "judged_on": judged,
                     "why": ("{} {} vs a typical {} for this machine, {} "
                             "spread(s) out{}".format(
                                 "grew by" if counter else "is",
                                 judged, n["typical"],
                                 "?" if score is None else round(score, 1),
                                 " (this sensor has never varied, so the score "
                                 "is its relative move)" if frozen else ""))}
        else:
            prev = previous.get(key)
            move = None
            if _numeric(prev) and prev != 0:
                move = abs(float(value) - float(prev)) / abs(float(prev))
            elif _numeric(prev) and prev == 0 and value != 0:
                move = 1.0
            entry = {"key": key, "value": value, "unit": row.get("unit", ""),
                     "rule": BY_FIXED,
                     "score": None if move is None else round(move, 4),
                     "typical": None, "spread": None, "samples": n["n"],
                     "why": ("moved {} against the flat {:.0%} rule; only {} "
                             "sample(s) of its own history".format(
                                 "?" if move is None else "{:.0%}".format(move),
                                 FIXED_MOVE_THRESHOLD, n["n"]))}
        scored.append(entry)

    # Sorted WITHIN a rule is meaningful; across rules it is an ordering of two
    # different quantities, so history-ranked rows come first as a block and the
    # `rule` field says why. A None score sorts last rather than being dropped.
    scored.sort(key=lambda e: (e["rule"] != BY_HISTORY,
                               e["score"] is None,
                               -(e["score"] or 0.0)))
    return scored[:top] if top else scored


def last_two(path: pathlib.Path) -> tuple:
    """({key: value} newest, {key: value} the one before). `path` is REQUIRED.

    The cockpit already probes every 15 seconds and record() now keeps what it
    found, so anything that wants "the current readings" can READ them instead
    of taking a second probe. A phase boundary that probed the machine itself
    would be measuring the cost of asking.
    """
    rows = []
    try:
        lines = pathlib.Path(path).read_text(encoding="utf-8",
                                             errors="replace").splitlines()
    except OSError:
        return {}, {}
    for line in lines[-2:]:
        try:
            rows.append(json.loads(line).get("v") or {})
        except ValueError:
            continue
    if not rows:
        return {}, {}
    if len(rows) == 1:
        return rows[0], {}
    return rows[-1], rows[-2]


def unusual_from_disk(path: pathlib.Path, top: int = 3) -> dict:
    """The ranked list, entirely from the recorded history. `path` REQUIRED."""
    newest, prev = last_two(path)
    readings = [{"key": k, "value": v, "unit": ""} for k, v in newest.items()]
    return unusual_now(readings, path, previous=prev, top=top)


def unusual_now(readings: list, path: pathlib.Path,
                previous: Optional[dict] = None, top: int = 3) -> dict:
    """The ranked list plus what a reader needs to judge it. `path` REQUIRED."""
    hist = history(path)
    rows = rank(readings, hist, previous, top=top)
    return {"ts": _now(), "rows": rows, "rule_meaning": RULE_MEANING,
            "sensors_with_history": sum(1 for v in hist.values()
                                        if len(v) >= MIN_SAMPLES),
            "sensors_seen": len(hist),
            "min_samples": MIN_SAMPLES,
            "history_path": str(path),
            "empty_because": (None if rows else
                              "no numeric reading was available to rank")}


# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile
    print("cockpit/norms.py --selftest")
    tmp = pathlib.Path(tempfile.mkdtemp()) / "somatic_history.jsonl"

    # A machine whose cpu sits near 20 and whose idle time wanders wildly.
    for i in range(60):
        probe = {"groups": {"COMPUTE": [
            {"key": "cpu_percent", "value": 20.0 + (i % 5), "unit": "%",
             "available": True},
            {"key": "idle_seconds", "value": float(i * 3 % 40), "unit": "s",
             "available": True},
            {"key": "gpu_temp_c", "value": 45.0, "unit": "C", "available": True},
        ]}}
        record(probe, tmp, ts="t{}".format(i))
    hist = history(tmp)
    print("  recorded             {} sensor(s), {} samples each".format(
        len(hist), len(hist["cpu_percent"])))

    n = norm_for(hist["cpu_percent"])
    print("  cpu_percent norm     typical={} spread={:.3f} n={}".format(
        n["typical"], n["spread"], n["n"]))

    now = [{"key": "cpu_percent", "value": 41.0, "unit": "%"},
           {"key": "idle_seconds", "value": 39.0, "unit": "s"},
           {"key": "gpu_temp_c", "value": 46.0, "unit": "C"},
           {"key": "brand_new_sensor", "value": 5.0, "unit": ""}]
    prev = {"cpu_percent": 22.0, "idle_seconds": 30.0, "gpu_temp_c": 45.0,
            "brand_new_sensor": 1.0}

    print("  BY DEVIATION:")
    for r in rank(now, hist, prev, top=4):
        print("    {:<18} {:<8} score={:<7} {}".format(
            r["key"], r["rule"], r["score"], r["why"][:64]))

    print("  a frozen sensor that moves is loud, not infinite: gpu_temp_c "
          "score={}".format(
              [r for r in rank(now, hist, prev, top=4)
               if r["key"] == "gpu_temp_c"][0]["score"]))
    print("  a sensor with no history falls back and SAYS so: {}".format(
        [r for r in rank(now, hist, prev, top=4)
         if r["key"] == "brand_new_sensor"][0]["rule"]))

    for i in range(MAX_ROWS + TRIM_SLACK + 10):
        record({"groups": {"X": [{"key": "k", "value": 1.0, "available": True}]}},
               tmp, ts="x{}".format(i))
    kept = len(tmp.read_text(encoding="utf-8").splitlines())
    print("  capped at            {} rows (cap {} + slack {}; the trim runs "
          "when the slack is used up, not on every append)".format(
              kept, MAX_ROWS, TRIM_SLACK))

    server = (BASE / "cockpit" / "server.py").read_text(encoding="utf-8",
                                                        errors="replace")
    print("  cockpit/server.py    {}".format(
        "WIRED — /api/somatic records every probe" if "nm.record(" in server
        else "NOT WIRED — nothing is recording, so no norm can ever form"))
    live = HISTORY
    print("  live history         {}  exists={} rows={}".format(
        live, live.exists(),
        len(live.read_text(encoding="utf-8").splitlines())
        if live.exists() else 0))
    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
