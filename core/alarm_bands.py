#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/alarm_bands.py — A RED LINE RINGS THE MOMENT IT IS CROSSED.

WHAT THIS IS
-------------
One number per axis: the value past which a person should be told at once, not
in the morning digest. Crossing it sends immediately and bypasses quiet hours,
because a red line that waits until 08:00 is a report, not an alarm.

    lower_better    alarms when the value goes ABOVE the line
    higher_better   alarms when the value goes BELOW it
    stable_better   alarms on either side of the target by the band's width

Under Emil's polarity ruling of 21 August the direction is unambiguous on all
25 axes, so this needs no per-axis special-casing.

EVERY THRESHOLD STARTS null AND STAYS null UNTIL A HUMAN SIGNS IT
------------------------------------------------------------------
A null threshold never alarms. That is not a gap to be filled by a default: a
red line nobody chose is a number the system invented and then measured itself
against. The count of unset bands is reported as AWAITING_HUMAN_VALUES so the
emptiness stays a standing question rather than a quiet zero.

scripts/propose_alarm_thresholds.py derives a SUGGESTED value per axis from
target_config's own rationale and reference_worst, and files them as proposals.
Suggestions are proposals, never defaults.

A MISSING DIRECTION IS AN ERROR, NOT A SKIP
--------------------------------------------
If an axis has a threshold but no usable direction, the sweep cannot know which
side of the line is bad. It reports CONFIG_ERROR. Skipping would mean a red
line that is set, looks armed, and silently checks nothing.

INDICATOR BANDS (10 Sep 2026) — THE FIRST THREE SIGNED LINES
-------------------------------------------------------------
The axis bands above sit on each axis's PRIMARY metric, and on 10 Sep 2026 all
24 were still null. The first red lines Emil actually signed that day are not
on primary metrics at all: CO2 annual INCREASE (a rate, not the 427 ppm level),
USGS M5+ count per 7 days, and GDACS Orange/Red wildfire count per 7 days vs
its own trailing median. They live in config/alarm_indicators.json and are
swept by sweep_indicators(), with two rules that do not bend:

  * a value reaches a band ONLY from memory/verified_observations.jsonl with
    verdict ACCEPTED — a number whose quote the gate found on the live page.
    Nothing an agent merely said can ring a bell.
  * every alarm carries its baseline: the fixed line, or the median and the
    window it was measured against. RECORD_ONLY until the history exists.

    venv\\Scripts\\python.exe core/alarm_bands.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
CONFIG = BASE / "config" / "target_config.json"
GOAL_SCORE = BASE / "snapshots" / "master" / "goal_score_latest.json"
LOG = BASE / "memory" / "alarm_bands_latest.json"
INDICATORS = BASE / "config" / "alarm_indicators.json"
VERIFIED = BASE / "memory" / "verified_observations.jsonl"

OK, ALARM, UNSET, NO_VALUE, CONFIG_ERROR = (
    "OK", "ALARM", "UNSET", "NO_VALUE", "CONFIG_ERROR")
RECORD_ONLY = "RECORD_ONLY"          # indicator band: armed, history too short to judge

DIRECTIONS = ("lower_better", "higher_better", "stable_better")
RULES = ("fixed", "relative_median")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def axes(config_path=None) -> dict[str, dict]:
    try:
        cfg = json.loads((config_path or CONFIG).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for branch, group in cfg.items():
        if branch.startswith("_") or not isinstance(group, dict):
            continue
        for axis, spec in group.items():
            if isinstance(spec, dict):
                out[axis] = spec
    return out


def values(goal_path=None) -> dict[str, float]:
    try:
        goal = json.loads((goal_path or GOAL_SCORE).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for detail in (goal.get("metric_details") or {}).values():
        axis, current = detail.get("axis"), _num(detail.get("current"))
        if axis and current is not None:
            out[axis] = current
    return out


def crossed(value: float, threshold: float, direction: str,
            target: float | None = None) -> bool:
    """Is the red line crossed? Direction decides which side is bad."""
    if direction == "lower_better":
        return value > threshold
    if direction == "higher_better":
        return value < threshold
    if direction == "stable_better":
        base = target if target is not None else threshold
        return abs(value - base) > abs(threshold)
    raise ValueError(f"unusable direction {direction!r}")


def sweep(config_path=None, goal_path=None) -> dict:
    """One row per axis. Never raises."""
    spec_by_axis = axes(config_path)
    value_by_axis = values(goal_path)

    rows = []
    for axis in sorted(spec_by_axis):
        spec = spec_by_axis[axis]
        threshold = _num(spec.get("alarm_threshold"))
        value = value_by_axis.get(axis)
        direction = spec.get("direction")

        if threshold is None:
            rows.append({"axis": axis, "verdict": UNSET, "value": value,
                         "threshold": None,
                         "why": "no red line has been set for this axis"})
            continue

        if direction not in DIRECTIONS:
            # NOT a skip. A threshold that is set but uncheckable is worse than
            # no threshold: it looks armed.
            rows.append({
                "axis": axis, "verdict": CONFIG_ERROR, "value": value,
                "threshold": threshold, "direction": direction,
                "why": (f"alarm_threshold={threshold} is set but direction is "
                        f"{direction!r} — the sweep cannot tell which side of "
                        f"the line is bad, so the band is armed and checks "
                        f"nothing"),
            })
            continue

        if value is None:
            rows.append({"axis": axis, "verdict": NO_VALUE, "value": None,
                         "threshold": threshold, "direction": direction,
                         "why": "a red line is set but nothing measured this axis"})
            continue

        try:
            is_over = crossed(value, threshold, direction,
                              _num(spec.get("target_value")))
        except ValueError as exc:
            rows.append({"axis": axis, "verdict": CONFIG_ERROR, "value": value,
                         "threshold": threshold, "direction": direction,
                         "why": str(exc)})
            continue

        rows.append({
            "axis": axis, "verdict": ALARM if is_over else OK,
            "value": value, "threshold": threshold, "direction": direction,
            "unit": spec.get("unit"),
            "why": (f"{value} {spec.get('unit') or ''} against a red line of "
                    f"{threshold} ({direction})") if is_over else None,
        })

    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (OK, ALARM, UNSET, NO_VALUE, CONFIG_ERROR)}
    return {
        "ts": _now(),
        "axes": len(rows),
        "counts": counts,
        "AWAITING_HUMAN_VALUES": counts[UNSET],
        "alarms": [r for r in rows if r["verdict"] == ALARM],
        "config_errors": [r for r in rows if r["verdict"] == CONFIG_ERROR],
        "rows": rows,
    }


# ── INDICATOR BANDS ────────────────────────────────────────────────────────

def indicator_bands(path=None) -> dict[str, dict]:
    try:
        cfg = json.loads((path or INDICATORS).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {k: v for k, v in (cfg.get("indicators") or {}).items() if isinstance(v, dict)}


def _obs_date(o: dict) -> str:
    rec = o.get("record") or {}
    return str(rec.get("observed_date") or (o.get("judged_utc") or "")[:10])


class UnreadableSeries(OSError):
    """The observations file is present but cannot be read as a file.

    A DIFFERENT FACT FROM "not there yet", and the distinction is the point:
    an absent file is the normal early state and means "no series". A path that
    is there and unreadable — a directory, a lock, lost permissions — means the
    series cannot be known, and a band that cannot be judged must say so rather
    than quietly behave like a band with no history.
    """


def indicator_values(path=None) -> dict[str, list[tuple[str, float]]]:
    """key -> [(date, value)] from ACCEPTED observations only, oldest first.

    ACCEPTED means core/quote_gate.py found the quote on the live page. A
    NULL_WITH_REASON is a correct answer but not a number; a refused card is
    not a value at all. Neither reaches a band.

    Raises UnreadableSeries if the path is present but unreadable. sweep_indicators
    catches it into config_errors — see its docstring for why it must not escape.
    """
    p = path or VERIFIED
    # `exists()` was the wrong question, and --selftest proved it on 10 Sep 2026.
    # The check has to be "is there a FILE I can read", because a path can exist
    # and still be unreadable. The selftest passed pathlib.Path("/nonexistent")
    # as its fixture for "no history"; on Windows that resolves to C:\nonexistent,
    # which on this machine EXISTS and is a DIRECTORY — so exists() said True,
    # read_text raised PermissionError, and `--selftest` died with a traceback
    # and exit 1 while all 39 tests were green. The tests never exercised this
    # branch; the module's own selftest did.
    if not p.is_file():
        if p.exists():
            raise UnreadableSeries(f"{p} exists but is not a readable file "
                                   f"(is_dir={p.is_dir()})")
        return {}
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnreadableSeries(f"{p} could not be read: "
                               f"{type(exc).__name__}: {exc}") from exc
    out: dict[str, list[tuple[str, float]]] = {}
    for line in text.splitlines():
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("verdict") != "ACCEPTED":
            continue
        rec = o.get("record") or {}
        key, val = rec.get("key"), _num(rec.get("value"))
        if key and val is not None:
            out.setdefault(key, []).append((_obs_date(o), float(val)))
    for k in out:
        out[k].sort()
    return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _judge_indicator(key: str, band: dict, series: list[tuple[str, float]]) -> dict:
    """One row. Every ALARM carries its baseline; nothing here raises."""
    row = {"indicator": key, "axis": band.get("axis"), "rule": band.get("rule"),
           "unit": band.get("unit"), "signed_by": band.get("signed_by"),
           "signed_on": band.get("signed_on"), "n_history": len(series)}
    rule, direction = band.get("rule"), band.get("direction")
    if rule not in RULES or direction not in DIRECTIONS:
        return dict(row, verdict=CONFIG_ERROR,
                    why=f"rule={rule!r} direction={direction!r} — armed and checks nothing")
    if not series:
        return dict(row, verdict=NO_VALUE, value=None,
                    why="a red line is signed but no ACCEPTED observation carries this key yet")
    date, value = series[-1]
    row.update(value=value, observed=date)

    if rule == "fixed":
        threshold = _num(band.get("threshold"))
        if threshold is None:
            return dict(row, verdict=CONFIG_ERROR, why="rule=fixed without a numeric threshold")
        try:
            over = crossed(value, threshold, direction)
        except ValueError as exc:
            return dict(row, verdict=CONFIG_ERROR, why=str(exc))
        baseline = {"kind": "fixed", "threshold": threshold, "direction": direction}
        return dict(row, verdict=ALARM if over else OK, threshold=threshold, baseline=baseline,
                    why=(f"{value} {band.get('unit') or ''} on {date} against a signed line of "
                         f"{threshold} ({direction}; signed {band.get('signed_by')} {band.get('signed_on')})")
                    if over else None)

    # relative_median: the line is the indicator's own recent past
    mult = _num(band.get("multiplier")) or 2.0
    window = int(band.get("window_days") or 56)
    min_hist = int(band.get("min_history_days") or window)
    prior = [(d, v) for d, v in series[:-1] if d]
    span_days = None
    if prior:
        try:
            first = datetime.fromisoformat(prior[0][0]).date()
            last = datetime.fromisoformat(date).date()
            span_days = (last - first).days
        except ValueError:
            span_days = None
    if not prior or span_days is None or span_days < min_hist:
        return dict(row, verdict=RECORD_ONLY, value=value,
                    baseline={"kind": "relative_median", "multiplier": mult, "window_days": window,
                              "history_days": span_days, "min_history_days": min_hist},
                    why=(f"recorded, not judged: {span_days or 0} days of accepted history, "
                         f"{min_hist} needed before a median means anything"))
    try:
        cutoff = datetime.fromisoformat(date).date()
        recent = [v for d, v in prior if (cutoff - datetime.fromisoformat(d).date()).days <= window]
    except ValueError:
        recent = [v for _, v in prior]
    if not recent:
        recent = [v for _, v in prior]
    med = _median(recent)
    threshold = mult * med
    over = value > threshold if direction == "lower_better" else value < med / mult
    baseline = {"kind": "relative_median", "multiplier": mult, "window_days": window,
                "median": med, "n_in_window": len(recent), "threshold": threshold}
    return dict(row, verdict=ALARM if over else OK, threshold=threshold, baseline=baseline,
                why=(f"{value} {band.get('unit') or ''} on {date} is over {mult}x the trailing "
                     f"{window}-day median of {med} ({len(recent)} accepted values; "
                     f"signed {band.get('signed_by')} {band.get('signed_on')})") if over else None)


def sweep_indicators(bands_path=None, verified_path=None) -> dict:
    """One row per signed indicator band. Never raises.

    "Never raises" is a contract, not a description, and it was broken until
    10 Sep 2026: indicator_values read the observations file with only an
    exists() guard in front of it, so an unreadable path came straight through
    this function as a PermissionError. This is a cycle step (the sweep runs
    right after scoring, test_the_sweep_runs_right_after_scoring), so a raise
    here takes down the step that is supposed to be watching the red lines.

    An unreadable series does NOT become "no history". Every band is marked
    CONFIG_ERROR with the reason, which means: no band can alarm, and the
    problem travels to the cycle report through the same channel a bad
    threshold does (test_config_errors_are_surfaced_not_buried). Silence would
    be the forbidden fallback — a red line that cannot be checked must not look
    like a red line that is quiet.
    """
    bands = indicator_bands(bands_path)
    try:
        series = indicator_values(verified_path)
        unreadable = None
    except UnreadableSeries as exc:
        series, unreadable = {}, str(exc)
    if unreadable:
        rows = [dict({"indicator": k, "axis": bands[k].get("axis"),
                      "rule": bands[k].get("rule"), "unit": bands[k].get("unit"),
                      "signed_by": bands[k].get("signed_by"),
                      "signed_on": bands[k].get("signed_on"), "n_history": 0},
                     verdict=CONFIG_ERROR, value=None,
                     why=f"the accepted-observation history cannot be read, so this "
                         f"signed line was NOT checked: {unreadable}")
                for k in sorted(bands)]
    else:
        rows = [_judge_indicator(k, bands[k], series.get(k, [])) for k in sorted(bands)]
    counts = {v: sum(1 for r in rows if r["verdict"] == v)
              for v in (OK, ALARM, RECORD_ONLY, NO_VALUE, CONFIG_ERROR)}
    return {"ts": _now(), "bands": len(rows), "counts": counts,
            "alarms": [r for r in rows if r["verdict"] == ALARM],
            "config_errors": [r for r in rows if r["verdict"] == CONFIG_ERROR],
            "rows": rows}


def send(result: dict, sender=None) -> int:
    """One message per alarm, immediately, past quiet hours."""
    sent = 0
    for row in result["alarms"]:
        name = row.get("axis") or row.get("indicator")
        if row.get("indicator"):
            name = f"{row['axis']} · {row['indicator']}"
        text = (f"🚨 CORTEX++ · ЧЕРВЕНА ЛИНИЯ · {name}\n"
                f"{row['why']}\n"
                f"Това не е дайджест — прагът е пресечен сега.")
        try:
            if sender is not None:
                sender(name, text)
            else:
                import supervisor
                supervisor.alarm_human(
                    f"червена линия {name}", text,
                    dedup_key=f"alarm:{name}:{row['value']}",
                    trigger="MANUAL",      # MANUAL bypasses the quiet window
                    # ALARM, and one of the three things that earn it: a
                    # threshold the human set has been crossed NOW.
                    level=supervisor.ALARM)
            sent += 1
        except Exception:
            pass
    return sent


def for_cycle_report() -> dict:
    """The counter the report carries: how many red lines nobody has drawn."""
    try:
        result = sweep()
        ind = sweep_indicators()
        return {"awaiting_human_values": result["AWAITING_HUMAN_VALUES"],
                "axes": result["axes"], "alarms": len(result["alarms"]),
                "config_errors": len(result["config_errors"]),
                "indicator_bands": ind["bands"], "indicator_counts": ind["counts"],
                "indicator_alarms": len(ind["alarms"])}
    except Exception:
        return {}


def run() -> dict:
    result = sweep()
    result["indicators"] = sweep_indicators()
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    except Exception:
        pass
    sent = send(result)
    sent_ind = send(result["indicators"])
    c = result["counts"]
    print(f"[ALARM] {result['axes']} axes | ALARM {c[ALARM]} ({sent} sent) | "
          f"OK {c[OK]} | AWAITING_HUMAN_VALUES {c[UNSET]} | "
          f"no value {c[NO_VALUE]} | CONFIG_ERROR {c[CONFIG_ERROR]}")
    for row in result["alarms"]:
        print(f"[ALARM] CROSSED {row['axis']}: {row['why']}")
    for row in result["config_errors"]:
        print(f"[ALARM] CONFIG_ERROR {row['axis']}: {row['why']}")
    ind, ic = result["indicators"], result["indicators"]["counts"]
    print(f"[ALARM] {ind['bands']} signed indicator bands | ALARM {ic[ALARM]} ({sent_ind} sent) | "
          f"OK {ic[OK]} | RECORD_ONLY {ic[RECORD_ONLY]} | no value {ic[NO_VALUE]} | "
          f"CONFIG_ERROR {ic[CONFIG_ERROR]}")
    for row in ind["rows"]:
        if row["verdict"] in (ALARM, CONFIG_ERROR, RECORD_ONLY):
            print(f"[ALARM] {row['verdict']} {row['axis']} · {row['indicator']}: {row['why']}")
    return result


def _absent_history() -> dict:
    """sweep_indicators against a path that is genuinely not there."""
    import tempfile  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as d:
        return sweep_indicators(verified_path=pathlib.Path(d) / "no_such_file.jsonl")


def _unreadable_is_reported() -> bool:
    """A directory where a file should be: every band CONFIG_ERROR, none ALARM,
    and the sweep still returns instead of raising."""
    import tempfile  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as d:
        ind = sweep_indicators(verified_path=pathlib.Path(d))
        return (not ind["alarms"]
                and len(ind["config_errors"]) == ind["bands"] > 0
                and all("cannot be read" in (r.get("why") or "") for r in ind["config_errors"]))


def _selftest() -> int:
    print("core/alarm_bands.py --selftest")
    result = sweep()
    ind = sweep_indicators()
    ok = True
    # 24 axes since GENERAL_SELF_REVIEW was retired on 21 Aug 2026 (test/test_alarm_bands.py
    # AXIS_COUNT). Until 10 Sep this selftest still said 25 and reported BROKEN every run.
    checks = [
        ("every axis is swept", result["axes"] == 24),
        ("nothing alarms while every band is null", not result["alarms"]),
        (f"AWAITING_HUMAN_VALUES is 24 ({result['AWAITING_HUMAN_VALUES']})",
         result["AWAITING_HUMAN_VALUES"] == 24),
        ("no config errors", not result["config_errors"]),
        (f"the signed indicator bands load ({ind['bands']})", ind["bands"] == 3),
        ("no indicator config errors", not ind["config_errors"]),
        # A GENUINELY ABSENT PATH, built rather than assumed. This check used to
        # pass pathlib.Path("/nonexistent"), which on Windows is C:\nonexistent —
        # a real DIRECTORY on this machine, so the "no history" fixture was
        # neither missing nor readable and the selftest crashed with
        # PermissionError and exit 1. A fixture has to be constructed to be
        # absent; a hardcoded POSIX path is a guess about someone else's disk.
        ("indicator bands never alarm on an empty history", not _absent_history()["alarms"]),
        # and the other half of the same lesson: a path that IS there but cannot
        # be read must be reported, never mistaken for a quiet red line
        ("an unreadable history is a config error, not silence", _unreadable_is_reported()),
        ("lower_better alarms above", crossed(500, 350, "lower_better")),
        ("lower_better is quiet below", not crossed(300, 350, "lower_better")),
        ("higher_better alarms below", crossed(20, 50, "higher_better")),
        ("higher_better is quiet above", not crossed(80, 50, "higher_better")),
    ]
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  counts: {result['counts']}")
    print(f"  indicator counts: {ind['counts']}")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else (run() and 0))
