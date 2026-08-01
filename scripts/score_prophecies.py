#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/score_prophecies.py — the calendar-horizon prediction, and the loop that scores it.

THE HOLE THIS CLOSES
--------------------
The ledger already seals predictions and scores them, but every horizon in it is
SYMBOLIC — "next_cycle_axis_score". A symbolic horizon is falsifiable only relative to
the system's own schedule: it matures when the system says it matures, and the thing it
is checked against is another number the system produced. That is a closed circuit.

A CALENDAR horizon is different. "gi_noaa_co2 will read within [a, b] on 15 August" can
be held against the system by a human with a calendar, and the answer comes from a
source outside it. This module adds that target_kind (composer_series) and the
deterministic scorer for it. No LLM is involved in either direction: the band is
arithmetic over the series' own variance, and the verdict is a comparison.

TWO RULES IT WILL NOT BEND
--------------------------
1. Never fabricate a prediction to have one. A band around a series with no variance
   cannot fail, so it proves nothing; a band wide enough to always contain the value is
   the same cheat with more decimals. If the data cannot support a falsifiable band, this
   writes a PREDICTION_PENDING record naming exactly how many points are missing, and
   nothing else.
2. Never mutate a sealed prediction. Outcomes are APPENDED as their own chained records
   referencing the original by hash. The prediction's text, band and hash are untouched
   forever — that is the entire basis on which a later "we got it right" can be believed.

  python scripts/score_prophecies.py            # score matured + propose if possible
  python scripts/score_prophecies.py --score    # score matured only
  python scripts/score_prophecies.py --propose  # propose the next prediction only
  python scripts/score_prophecies.py --dry      # report, write nothing
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "prophecy"))

import prophecy_ledger as pl  # noqa: E402

COMPOSER_STATE = REPO / "memory" / "composer_state"

KIND = "composer_series"

# A band is only worth sealing if the series has enough history for its own variance to
# mean something. Fourteen daily points is the smallest window that survives a weekend
# gap and one bad fetch without the standard deviation being an artefact of noise.
MIN_POINTS = 14
HORIZON_DAYS = 14

# A series that never moves has zero variance, and a zero-width band around a constant is
# a prediction that cannot fail. Refuse it by name rather than widening it into meaning.
MIN_DISTINCT = 2

# How far past its horizon a prediction waits for an observation before it is closed as
# unresolvable. Without this a source that quietly dies leaves predictions open forever,
# and an open prediction is one that never got to be wrong.
GRACE_DAYS = 14


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


# ── reading the world ────────────────────────────────────────────────────────

def _series(axis: str, source_id: str) -> list:
    """[(datetime, float)] for one composer source, oldest first. Never raises."""
    state = _load(COMPOSER_STATE / f"{axis}.json", {}) or {}
    st = (state.get("sources") or {}).get(source_id)
    if not st:
        return []
    out = []
    for row in st.get("history") or []:
        try:
            ts, val = row[0], float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        dt = _parse_ts(ts)
        if dt:
            out.append((dt, val))
    return sorted(out)


def _all_series() -> list:
    """(axis, source_id, series) for every source that has any history."""
    out = []
    for f in sorted(COMPOSER_STATE.glob("*.json")):
        state = _load(f, {}) or {}
        for sid in (state.get("sources") or {}):
            s = _series(f.stem, sid)
            if s:
                out.append((f.stem, sid, s))
    return out


# ── the band ─────────────────────────────────────────────────────────────────

def band_for(series: list) -> tuple:
    """(band, centre, sigma, reason) — the falsification band, or (None, ..., reason).

    Persistence centre, width from the series' OWN recent variance. Deliberately dull:
    a fancier model would be harder to check and no more honest."""
    if len(series) < MIN_POINTS:
        return None, None, None, f"only {len(series)} point(s), need {MIN_POINTS}"
    vals = [v for _, v in series][-MIN_POINTS:]
    if len(set(vals)) < MIN_DISTINCT:
        return None, None, None, (f"last {MIN_POINTS} points are a single repeated value "
                                  f"({vals[-1]}) — a band around a constant cannot fail")
    sigma = statistics.pstdev(vals)
    if sigma <= 0:
        return None, None, None, "zero variance — no falsifiable width"
    centre = vals[-1]
    half = 2.0 * sigma
    return ([round(centre - half, 6), round(centre + half, 6)],
            round(centre, 6), round(sigma, 6), None)


# ── scoring ──────────────────────────────────────────────────────────────────

def _verdict(band, actual) -> tuple:
    """(verdict, learner_err). learner_err is 0 inside the band, else the distance to
    the nearest edge — so a near miss and a wild miss are not the same number."""
    lo, hi = band
    if lo <= actual <= hi:
        return "hit", 0.0
    return "miss", round(min(abs(actual - lo), abs(actual - hi)), 6)


def score_matured(dry: bool = False, now: datetime = None) -> dict:
    """Score every calendar-horizon prediction whose date has passed. Deterministic."""
    now = now or _now()
    recs = pl.read_all()
    already = {r.get("ref_hash") for r in recs if r.get("event") == pl.OUTCOME}
    results = {"hit": 0, "miss": 0, "unresolvable": 0, "waiting": 0, "details": []}

    for p in recs:
        if p.get("event") != pl.PREDICTION or p.get("target_kind") != KIND:
            continue
        if p.get("hash") in already:
            continue
        horizon = _parse_ts(p.get("horizon_utc"))
        if horizon is None or horizon > now:
            results["waiting"] += 1
            continue

        axis, sid = p.get("axis"), p.get("source_id")
        band = p.get("band")
        series = _series(axis or "", sid or "")
        after = [(dt, v) for dt, v in series if dt >= horizon]

        reason = None
        if not band or len(band) != 2:
            reason = "sealed record carries no band"
        elif not series:
            reason = f"source {sid} no longer present in composer_state for {axis}"
        elif not after:
            if now - horizon < timedelta(days=GRACE_DAYS):
                results["waiting"] += 1
                results["details"].append(
                    {"target_id": p.get("target_id"), "verdict": "not yet",
                     "note": f"horizon passed, no observation yet ({GRACE_DAYS}d grace)"})
                continue
            reason = (f"no observation within {GRACE_DAYS}d after the horizon — "
                      f"source stopped updating")

        if reason:
            results["unresolvable"] += 1
            results["details"].append({"target_id": p.get("target_id"),
                                       "verdict": "unresolvable", "reason": reason})
            if not dry:
                pl.score_prediction(p["hash"], None, verdict="unresolvable", reason=reason,
                                    learner_err=None, baseline_err=None)
            continue

        actual = after[0][1]                      # first observation AT OR AFTER the horizon
        verdict, l_err = _verdict(band, actual)
        try:
            b_err = round(abs(float(p.get("baseline")) - actual), 6)
        except (TypeError, ValueError):
            b_err = None

        results[verdict] += 1
        results["details"].append({"target_id": p.get("target_id"), "verdict": verdict,
                                   "actual": actual, "band": band,
                                   "learner_err": l_err, "baseline_err": b_err})
        if not dry:
            pl.score_prediction(p["hash"], actual, verdict=verdict, band=band,
                                observed_at=after[0][0].isoformat(),
                                learner_err=l_err, baseline_err=b_err)
    return results


# ── proposing ────────────────────────────────────────────────────────────────

def _open_prediction(recs, target_id) -> bool:
    scored = {r.get("ref_hash") for r in recs if r.get("event") == pl.OUTCOME}
    return any(r.get("event") == pl.PREDICTION and r.get("target_kind") == KIND
               and r.get("target_id") == target_id and r.get("hash") not in scored
               for r in recs)


def propose(dry: bool = False, now: datetime = None) -> dict:
    """Seal the next calendar-horizon prediction over the longest usable series — or, if
    no series can support a falsifiable band, record exactly what is missing."""
    now = now or _now()
    # Variance ranks ABOVE length. A series that never moves can never support a
    # falsifiable band no matter how long it grows, so naming it as "8 points short"
    # would promise a prediction that will still be refused when those points arrive.
    # The series that is actually on track to qualify is the one that varies.
    candidates = sorted(_all_series(),
                        key=lambda t: (len({v for _, v in t[2]}) >= MIN_DISTINCT, len(t[2])),
                        reverse=True)
    if not candidates:
        return {"action": "none", "reason": "no composer series at all"}

    recs = pl.read_all()
    for axis, sid, series in candidates:
        band, centre, sigma, why_not = band_for(series)
        if band is None:
            continue
        target_id = f"{axis}::{sid}"
        if _open_prediction(recs, target_id):
            return {"action": "skipped", "reason": f"{target_id} already has an open prediction"}
        horizon = (now + timedelta(days=HORIZON_DAYS)).replace(microsecond=0)
        rec = None
        if not dry:
            rec = pl.seal_prediction(
                KIND, target_id, horizon.isoformat(),
                learner_value=centre, baseline_value=centre,
                basis=(f"persistence centre = last observed value; band = centre +/- 2*sigma "
                       f"over the last {MIN_POINTS} points (sigma={sigma}); "
                       f"falsified if the first observation at/after the horizon is outside it"),
                band=band, axis=axis, source_id=sid, sigma=sigma,
                n_points=len(series), current=centre, horizon_days=HORIZON_DAYS)
        return {"action": "sealed", "target_id": target_id, "band": band, "centre": centre,
                "sigma": sigma, "n_points": len(series),
                "horizon_utc": horizon.isoformat(),
                "hash": (rec or {}).get("hash")}

    # Nothing qualifies. Say so, precisely, and store the shortfall rather than a
    # prediction that could not fail.
    axis, sid, series = candidates[0]
    _, _, _, why_not = band_for(series)
    target_id = f"{axis}::{sid}"
    need = max(0, MIN_POINTS - len(series))
    reason = (f"first calendar prediction pending: longest series {target_id} has "
              f"{len(series)} point(s) ({why_not}); needs {need} more — auto-checked next cycle")

    prior = [r for r in recs if r.get("event") == pl.PENDING and r.get("target_id") == target_id]
    if prior and prior[-1].get("have_points") == len(series):
        return {"action": "pending_unchanged", "target_id": target_id,
                "have_points": len(series), "need_more": need, "reason": reason}
    if not dry:
        pl.note_pending(target_id, reason, have_points=len(series),
                        need_points=MIN_POINTS, need_more=need,
                        distinct_values=len({v for _, v in series}))
    return {"action": "pending", "target_id": target_id, "have_points": len(series),
            "need_more": need, "reason": reason}


# ── cycle entry point ────────────────────────────────────────────────────────

def run(dry: bool = False) -> dict:
    """One line for the cycle log. Fail-open is the CALLER's job — see
    core/cortex_orchestrator.py; this returns normally or raises, it never sys.exits."""
    scored = score_matured(dry=dry)
    proposed = propose(dry=dry)
    return {"scored": scored, "proposed": proposed}


def summary_line(res: dict) -> str:
    s, p = res["scored"], res["proposed"]
    return (f"calendar prophecies: {s['hit']} hit / {s['miss']} miss / "
            f"{s['unresolvable']} unresolvable / {s['waiting']} waiting; "
            f"propose -> {p.get('action')}"
            + (f" ({p.get('target_id')} band {p.get('band')})" if p.get("action") == "sealed"
               else f" ({p.get('need_more')} more points needed)"
               if p.get("action") in ("pending", "pending_unchanged") else ""))


if __name__ == "__main__":
    dry = "--dry" in sys.argv
    if "--score" in sys.argv:
        out = {"scored": score_matured(dry=dry)}
    elif "--propose" in sys.argv:
        out = {"proposed": propose(dry=dry)}
    else:
        out = run(dry=dry)
        print(summary_line(out))
        print()
    print(json.dumps(out, ensure_ascii=False, indent=2))
