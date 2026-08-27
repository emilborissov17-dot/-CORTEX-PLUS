#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_integrity.py — FIVE HONEST SCALARS, and no product of them.

WHAT THIS REPLACES. flow_score computed

    fs = (steps_full / steps_total) * (60.0 / median_step_seconds)

a completeness ratio MULTIPLIED BY a speed. Two independent facts collapsed into
one number, so a cycle that did half the work twice as fast scored the same as a
cycle that did all of it at the usual pace — and neither reading could be
recovered from the result. Worse, the speed term is unbounded: the smallest
non-zero median the step contract can record is 0.005s, which puts the ceiling
at 12000, and band() called everything above 4.0 "flowing". A cycle whose steps
all returned in milliseconds — one that did nothing at all — scored maximally
flowing.

So: five scalars, computed independently, never combined. If a reader wants a
single number they must choose one and say which.

    integrity_ratio       the share of steps that actually did their work
    degraded_ratio        the share that answered from a fallback
    failed_ratio          the share that raised, went missing or had no effect
    median_step_seconds   pace, as a plain number with no verdict attached
    cloud_success_ratio   the share that did NOT have to fall back to a local model

FULL IS REDEFINED, and it is stricter. A step counts as full only when it
completed, was not degraded, did not time out, and was answered by the source
that was supposed to answer it. UNKNOWN — the warmup verdict, returned for a
step's first three runs — NO LONGER COUNTS AS FULL. It used to, which meant a
brand-new step inflated the score for three nights precisely when a human was
most likely to be watching.

    venv/Scripts/python.exe core/cycle_integrity.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

CONTRACT = BASE / "memory" / "step_contract_latest.json"
BASELINE = BASE / "memory" / "step_contract_baseline.json"

# Verdicts that mean the step did not deliver. UNKNOWN is deliberately NOT full
# and deliberately NOT a failure: it is "no baseline yet, no opinion", which is
# an absence of judgement rather than a bad one.
FAILED_VERDICTS = frozenset({"RAISED", "MISSING", "NO_EFFECT"})
DEGRADED_VERDICTS = frozenset({"DEGRADED", "SLOW"})

# THE ONLY STEPS ALLOWED TO ANSWER FROM A LOCAL MODEL AND STILL COUNT AS FULL.
# Sourced from test/test_no_ollama_in_live_path.py, where groq_backend.py and
# data_scout.py are named as owning "a LABELLED sovereign local fallback
# (Emil-approved)". Everything else answering locally has fallen back, and a
# fallback is not the work that was asked for.
#
# HUMAN-EDITABLE. Adding a name here says "this step was designed to answer
# locally", which is a claim about intent that no code can infer.
LOCAL_PLANNED = frozenset({"data_scout"})

# How a cloud→local fallback announces itself in the contract's own words, e.g.
# "answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned at its
# slice of B=122s".
_FALLBACK_MARKERS = ("after the cloud tier was abandoned", "local_3b",
                     "cloud tier was abandoned", "ALL cloud backends down")
_TIMEOUT_MARKERS = ("timeout", "timed out", "timedout")

# SUSPECT_PACE: a step that finishes in under this share of its own historical
# median has probably failed open rather than run fast.
PACE_FLOOR = 0.10
PACE_MIN_OBSERVATIONS = 5


def _text(step: dict) -> str:
    return " ".join(str(step.get(k) or "") for k in
                    ("error", "why", "degraded")).lower()


def answered_locally(step: dict) -> bool:
    return any(m.lower() in _text(step) for m in _FALLBACK_MARKERS)


def timed_out(step: dict) -> bool:
    return any(m in _text(step) for m in _TIMEOUT_MARKERS)


def is_full(step: dict, local_planned=LOCAL_PLANNED) -> tuple:
    """(full, why_not). The redefinition, in one place.

    Returns the REASON, not just the verdict, because "42% integrity" with no
    account of the other 58% is a number a reader can only believe or ignore.
    """
    verdict = str(step.get("verdict") or "").upper()
    if verdict in FAILED_VERDICTS:
        return False, "verdict {}".format(verdict)
    if verdict in DEGRADED_VERDICTS:
        return False, "verdict {}".format(verdict)
    if verdict == "UNKNOWN":
        # warming up. Not a failure, but not evidence of work either.
        return False, "UNKNOWN (warmup: no baseline to judge against yet)"
    if step.get("degraded"):
        return False, "degraded"
    if timed_out(step):
        return False, "timed out"
    if answered_locally(step) and str(step.get("step")) not in local_planned:
        return False, "answered locally where cloud was expected"
    if verdict != "OK":
        return False, "verdict {}".format(verdict or "(none)")
    return True, ""


# ── SUSPECT_PACE ────────────────────────────────────────────────────────────

def _baseline_medians(baseline_path=None) -> dict:
    """{label: (median_seconds, n)} for labels with enough history to judge."""
    try:
        blob = json.loads(pathlib.Path(baseline_path or BASELINE)
                          .read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for label, rec in (blob or {}).items():
        if not isinstance(rec, dict):
            continue
        secs = [r.get("seconds") for r in (rec.get("runs") or [])
                if isinstance(r.get("seconds"), (int, float))
                and not isinstance(r.get("seconds"), bool)]
        if len(secs) >= PACE_MIN_OBSERVATIONS:
            out[label] = (float(statistics.median(secs)), len(secs))
    return out


def suspect_pace(steps: list, baseline_path=None) -> dict:
    """Steps that finished implausibly fast for their own history.

    A PROBABLE FAIL-OPEN, NEVER AN ACHIEVEMENT. A step that usually takes 65
    seconds and returns in two has almost certainly skipped its work — an empty
    API answer, a guard that returned early, a cache that lied. The old flow
    score treated exactly this as the best possible night.

    Silent where there is no history to judge against, and it says so rather
    than guessing: with fewer than 5 prior observations a label is not compared
    at all.
    """
    medians = _baseline_medians(baseline_path)
    flagged, unjudged = [], []
    for s in steps or []:
        label = str(s.get("step") or "")
        secs = s.get("seconds")
        if not isinstance(secs, (int, float)) or isinstance(secs, bool):
            continue
        if label not in medians:
            unjudged.append(label)
            continue
        med, n = medians[label]
        if med <= 0:
            unjudged.append(label)
            continue
        if float(secs) < PACE_FLOOR * med:
            flagged.append({
                "step": label, "seconds": round(float(secs), 3),
                "median_seconds": round(med, 3), "observations": n,
                "share_of_median": round(float(secs) / med, 4),
                "why": ("{} finished in {:.2f}s against its own median of "
                        "{:.2f}s over {} runs — under {:.0f}% of normal, which "
                        "is a probable fail-open, not an achievement"
                        .format(label, float(secs), med, n, PACE_FLOOR * 100)),
            })
    return {
        "alarm": bool(flagged),
        "steps": flagged,
        "unjudged": sorted(set(unjudged)),
        "why_silent": (None if medians else
                       "no label has {} prior observations on record, so no "
                       "pace can be judged".format(PACE_MIN_OBSERVATIONS)),
    }


# ── the five scalars ────────────────────────────────────────────────────────

def scalars(steps=None, contract_path=None, baseline_path=None,
            local_planned=LOCAL_PLANNED) -> dict:
    """The five, computed independently. No product, no composite, no band.

    NAMED scalars(), NOT measure(). test_perplexity.py bans every call to a
    method named `measure` outside core/perplexity.py, because that one makes a
    model call and must sit behind an enabled() check. A second, unrelated
    measure() would have made that guard ambiguous — and a guard that cannot
    tell a model call from an arithmetic one is not a guard. This function makes
    no call to anything; it reads two files.
    """
    if steps is None:
        try:
            blob = json.loads(pathlib.Path(contract_path or CONTRACT)
                              .read_text(encoding="utf-8"))
            steps = blob.get("steps") or []
            cycle_id = blob.get("cycle_id")
        except Exception:
            steps, cycle_id = [], None
    else:
        cycle_id = None

    total = len(steps)
    if total == 0:
        return {"cycle_id": cycle_id, "steps_total": 0,
                "integrity_ratio": None, "degraded_ratio": None,
                "failed_ratio": None, "median_step_seconds": None,
                "cloud_success_ratio": None,
                "suspect_pace": {"alarm": False, "steps": [], "unjudged": [],
                                 "why_silent": "no steps on record"},
                "not_full": [],
                "empty_because": "no step is on record for this cycle"}

    full, not_full = [], []
    for s in steps:
        ok, why = is_full(s, local_planned)
        (full if ok else not_full).append(
            s if ok else {"step": s.get("step"), "why": why,
                          "verdict": s.get("verdict"),
                          "seconds": s.get("seconds")})

    degraded = sum(1 for s in steps
                   if s.get("degraded")
                   or str(s.get("verdict") or "").upper() in DEGRADED_VERDICTS)
    failed = sum(1 for s in steps
                 if str(s.get("verdict") or "").upper() in FAILED_VERDICTS)
    fell_back = sum(1 for s in steps
                    if answered_locally(s)
                    and str(s.get("step")) not in local_planned)

    durations = [float(s["seconds"]) for s in steps
                 if isinstance(s.get("seconds"), (int, float))
                 and not isinstance(s.get("seconds"), bool)]

    return {
        "cycle_id": cycle_id,
        "steps_total": total,
        "steps_full": len(full),
        # THE FIVE. Independent. Never multiplied together.
        "integrity_ratio": round(len(full) / total, 4),
        "degraded_ratio": round(degraded / total, 4),
        "failed_ratio": round(failed / total, 4),
        "median_step_seconds": (round(statistics.median(durations), 3)
                                if durations else None),
        # the share of steps that did NOT have to fall back to a local model
        "cloud_success_ratio": round((total - fell_back) / total, 4),
        "suspect_pace": suspect_pace(steps, baseline_path),
        "not_full": not_full,
        "empty_because": None,
    }


def band(_value=None):
    """REMOVED ON PURPOSE. Kept as a loud failure, not deleted silently.

    flow_score.band() called anything above 4.0 "flowing", so a cycle whose
    steps all returned in milliseconds — one that did nothing — read as
    maximally flowing. There is no band on integrity_ratio because a share of
    work done needs no adjective; the thresholds live in the cockpit, where the
    colour is chosen, and nowhere else.
    """
    raise NotImplementedError(
        "band() is gone with the composite. Use integrity_ratio directly; the "
        "red/amber/green thresholds belong to the display, not to the metric.")


def _selftest() -> int:
    print("core/cycle_integrity.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    fast_degraded = [{"step": "a", "seconds": 0.01, "verdict": "DEGRADED",
                      "degraded": "answered by local_3b after the cloud tier "
                                  "was abandoned"},
                     {"step": "b", "seconds": 0.01, "verdict": "OK"}]
    m = scalars(steps=fast_degraded, baseline_path=None)
    check("a degraded step is not full", m["integrity_ratio"] == 0.5)
    check("degraded_ratio counts it", m["degraded_ratio"] == 0.5)
    check("cloud_success_ratio counts the fallback",
          m["cloud_success_ratio"] == 0.5)
    check("no composite is returned",
          not any(k in m for k in ("flow_score", "fs", "score")))

    check("UNKNOWN is not full",
          is_full({"step": "x", "verdict": "UNKNOWN"})[0] is False)
    check("a planned local fallback stays full",
          is_full({"step": "data_scout", "verdict": "OK",
                   "why": "answered by local_3b"})[0] is True)
    check("an unplanned one does not",
          is_full({"step": "other", "verdict": "OK",
                   "why": "answered by local_3b"})[0] is False)

    try:
        band(1.0)
        check("band() is gone", False)
    except NotImplementedError:
        check("band() is gone and says so", True)

    live = scalars()
    print("\n  LIVE, from {}:".format(CONTRACT.name))
    for k in ("steps_total", "integrity_ratio", "degraded_ratio",
              "failed_ratio", "median_step_seconds", "cloud_success_ratio"):
        print("    {:22s} {}".format(k, live.get(k)))
    sp = live.get("suspect_pace") or {}
    print("    {:22s} {}".format("suspect_pace",
                                 "ALARM: " + ", ".join(s["step"] for s in sp["steps"])
                                 if sp.get("alarm") else "silent"))
    print("  RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
