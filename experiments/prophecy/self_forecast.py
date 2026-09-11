#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/prophecy/self_forecast.py — THE SYSTEM PREDICTS ITS OWN NEXT NIGHT,
IN MORE THAN ONE NUMBER. (10 September 2026, written from the cloud session at
Ivan's order: "направи каквото трябва да предсказва пълноценно".)

WHAT ALREADY EXISTED, AND WHY THIS IS NOT A SECOND COPY OF IT
-------------------------------------------------------------
experiments/prophecy/prophecy.py seals ONE self-prediction per day —
target_kind "self_failure": P(the next cycle finishes). Learner = recent
5-cycle finish-rate, baseline = all-time finish-rate. 52 scored outcomes at
the time of writing; the learner wins 40/52 (Brier 0.171 vs 0.331).

That is a real self-prediction, but it is one bit. "Will I finish" is not
"how will I do". A self-model that predicts its own performance has to say,
BEFORE the night, how long it will take, whether it will limp, and WHICH
step will fall over — and be scored on each of those separately.

This module adds three target kinds to the SAME tamper-evident ledger
(prophecy_ledger.py — seal_prediction / score_prediction, unchanged):

  self_duration            numeric, seconds. learner = median of the last
                           RECENT_WINDOW finished durations; baseline = the
                           last finished duration (persistence). Scored by
                           absolute error, like axis_next.
  self_degraded            probability that degraded_steps >= 1 in the next
                           sealed cycle. learner = Laplace-smoothed recent
                           rate; baseline = all-time rate. Scored by BRIER
                           (squared error of the probability) — passed
                           explicitly as learner_err / baseline_err so the
                           ledger's default |p - actual| is NOT used.
  self_step_fail           one prediction PER STEP that has said "-> FAILED"
                           in at least one of the recent cycle logs:
                           P(this step FAILS again next cycle). Same
                           learner/baseline shape as self_degraded, Brier.

Every prediction carries the same target_id anchor as self_failure —
"next_cycle_after::<ts of the last terminal event>" — so the three kinds and
the old one describe the same night and can be read side by side.

REFUSALS (a prediction sealed after the outcome started is not a prediction)
---------------------------------------------------------------------------
  --predict REFUSES when the existence ledger's last event is CYCLE_STARTED
  with no terminal event after it: the night is already running. Exit 2, the
  reason printed, nothing written. The forbidden fallback is "seal anyway
  with a note" — that would let a late run score as foresight.
  --predict REFUSES when there are fewer than MIN_HISTORY finished cycles:
  a rate over two nights is a coin, not a self-model. note_pending() records
  the named absence instead.
  --score scores only predictions whose anchor precedes a CYCLE_FINISHED
  that came after the seal; a prediction for a night that has not ended
  stays open. A prediction is never scored twice (ref_hash set).

WHAT THIS DOES NOT DO
---------------------
It does not enter the composite (self_mirror rule: nothing from the mirror
enters the composite). It does not write anything a model prompt reads
(p_survive rule). It does not touch fast_cycle_runner.py or supervisor.py:
WIRING IS A SEPARATE, PROVEN STEP — the same scheduled task that runs
prophecy.py --predict / --score at 09:00 UTC should run this file with the
same flags, after it. Until that is done this module is INERT in production,
and --selftest says so.

Usage (venv interpreter, from the repo root):
  venv\\Scripts\\python.exe experiments/prophecy/self_forecast.py --predict
  venv\\Scripts\\python.exe experiments/prophecy/self_forecast.py --score
  venv\\Scripts\\python.exe experiments/prophecy/self_forecast.py --status
  venv\\Scripts\\python.exe experiments/prophecy/self_forecast.py --selftest
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import prophecy_ledger as pl  # noqa: E402

EXISTENCE_LEDGER = REPO / "memory" / "existence_ledger.jsonl"
CYCLE_LOGS_DIR = REPO / "memory" / "cycle_logs"

RECENT_WINDOW = 7          # nights that count as "recent self-state"
MIN_HISTORY = 3            # fewer finished cycles than this -> note_pending, not a coin
KINDS = ("self_duration", "self_degraded", "self_step_fail")
# self_survive is SEALED AT BOOT by core/survival_gate.py (the number exists only
# then) and SCORED here in the morning. It is not in KINDS because --predict must
# not seal it: a 09:00 seal would be a guess about a p that is computed at 03:04.
SURVIVE_KIND = "self_survive"
SCORED_KINDS = KINDS + (SURVIVE_KIND,)
TERMINAL = ("CYCLE_FINISHED", "CYCLE_DIED", "CYCLE_KILLED")

# The one line a failed step leaves in the cycle log, e.g.
#   [FAST_CYCLE] merkle_to_training -> FAILED: cannot unpack non-iterable Mapping object
_STEP_FAILED = re.compile(r"^\[FAST_CYCLE\] ([A-Za-z0-9_]+) -> FAILED\b", re.M)
# The same line, with whatever the exception said after the colon. ONE regex pair
# in ONE module: experiments/needs/needs_report.py reads the cycle logs for ITEM 70
# through the functions below rather than carrying a second copy of this pattern,
# because two parsers of one log format are two things that can disagree about what
# "FAILED" means (the merkle_to_training defect was exactly two readers of one
# contract drifting apart).
_STEP_FAILED_WHY = re.compile(
    r"^\[FAST_CYCLE\] ([A-Za-z0-9_]+) -> FAILED:?\s*(.*)$", re.M)


class Refused(RuntimeError):
    """Raised instead of returning: a refusal must not look like an empty result."""


# ── existence ledger ──────────────────────────────────────────────────────────

def read_existence(path: Path = EXISTENCE_LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def finished_cycles(events: list[dict]) -> list[dict]:
    """CYCLE_FINISHED events in ledger order, with the numbers this module scores."""
    out = []
    for e in events:
        if e.get("event") != "CYCLE_FINISHED":
            continue
        out.append({
            "ts": e.get("ts"),
            "cycle_id": e.get("cycle_id"),
            "duration_sec": e.get("duration_sec"),
            "degraded_steps": e.get("degraded_steps"),
            "steps_completed": e.get("steps_completed"),
        })
    return out


def last_terminal(events: list[dict]) -> Optional[dict]:
    for e in reversed(events):
        if e.get("event") in TERMINAL:
            return e
    return None


def cycle_is_running(events: list[dict]) -> bool:
    """True iff the last event is CYCLE_STARTED with no terminal event after it."""
    for e in reversed(events):
        ev = e.get("event")
        if ev == "CYCLE_STARTED":
            return True
        if ev in TERMINAL:
            return False
    return False


# ── cycle logs: which steps FAILED on which night ─────────────────────────────

def _log_for_cycle(cycle_id: str, logs_dir: Path = CYCLE_LOGS_DIR) -> Optional[Path]:
    """cycle_id '2026-09-10T03:04:02.271866+03:00' -> memory/cycle_logs/cycle_2026-09-10_0304*.log"""
    if not cycle_id or not logs_dir.exists():
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})", str(cycle_id))
    if not m:
        return None
    stem = f"cycle_{m.group(1)}_{m.group(2)}{m.group(3)}"
    hits = sorted(logs_dir.glob(stem + "*.log"))
    return hits[0] if hits else None


def failed_steps_in_log(path: Path) -> Optional[dict]:
    """{step name -> the exception text it printed} for one cycle log, or None if
    the log cannot be read. The single reader of the '-> FAILED' line format; see
    _STEP_FAILED_WHY. A step that failed more than once in a night keeps the LAST
    message, which is the one a reader would see at the bottom of the log."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {step: (why or "").strip() for step, why in _STEP_FAILED_WHY.findall(text)}


def failed_steps(cycle_id: str, logs_dir: Path = CYCLE_LOGS_DIR) -> Optional[set]:
    """Set of step names that wrote '-> FAILED' in that night's log; None if no log."""
    p = _log_for_cycle(cycle_id, logs_dir)
    if p is None:
        return None
    d = failed_steps_in_log(p)
    return None if d is None else set(d)


def repeated_step_failures(logs_dir: Path = CYCLE_LOGS_DIR, nights: int = 2) -> dict:
    """Steps that wrote '-> FAILED' in EVERY one of the last `nights` cycle logs.

    ITEM 70, Kimi 3 Sep: "Трябва да спре моделът 'логнал съм FAILED, значи съм си
    свършил работата'." Measured from memory/cycle_logs/, never from memory or from
    a status file that could itself be stale.

    Returns {step: [message per night, oldest first]}. EMPTY IS THE NORMAL ANSWER
    and is not a failure of this function: fewer than `nights` logs on disk, or no
    step failing in all of them, both yield {}. The forbidden behaviour is
    reporting a step because it failed ONCE — a single bad night is not a pattern,
    and paging on it is how a channel gets muted."""
    logs = sorted(logs_dir.glob("cycle_*.log")) if logs_dir.exists() else []
    if len(logs) < nights:
        return {}
    recent = logs[-nights:]
    per_night = [failed_steps_in_log(p) for p in recent]
    if any(d is None for d in per_night):
        return {}                     # an unreadable log is unknowable, not innocent
    common = set(per_night[0])
    for d in per_night[1:]:
        common &= set(d)
    return {step: [d[step] for d in per_night] for step in sorted(common)}


# ── the forecasts ────────────────────────────────────────────────────────────

def _laplace(seq: list[int]) -> float:
    """(k+1)/(n+2): a rate that is never exactly 0 or 1 on finite evidence,
    so a Brier score can never be 'free'."""
    return round((sum(seq) + 1) / (len(seq) + 2), 4)


def build_forecasts(events: list[dict], logs_dir: Path = CYCLE_LOGS_DIR) -> dict:
    """Pure: returns what WOULD be sealed. Raises Refused on the two refusals."""
    if cycle_is_running(events):
        raise Refused("a cycle is running (CYCLE_STARTED with no terminal event) — "
                      "a forecast sealed now is not a forecast")
    fin = finished_cycles(events)
    if len(fin) < MIN_HISTORY:
        raise Refused(f"only {len(fin)} finished cycles on record; "
                      f"need {MIN_HISTORY} before a rate means anything")
    term = last_terminal(events)
    anchor = term.get("ts") if term else "genesis"
    recent = fin[-RECENT_WINDOW:]

    durations_all = [c["duration_sec"] for c in fin if isinstance(c["duration_sec"], (int, float))]
    durations_rec = [c["duration_sec"] for c in recent if isinstance(c["duration_sec"], (int, float))]
    degraded_all = [1 if (c["degraded_steps"] or 0) >= 1 else 0 for c in fin]
    degraded_rec = [1 if (c["degraded_steps"] or 0) >= 1 else 0 for c in recent]

    out = {
        "anchor": anchor,
        "seen_cycles": len(fin),
        "self_duration": {
            "learner": round(statistics.median(durations_rec), 1),
            "baseline": round(float(durations_all[-1]), 1),
            "basis": f"learner=median of last {len(durations_rec)} finished durations; "
                     f"baseline=last finished duration (persistence); unit=seconds",
        },
        "self_degraded": {
            "learner": _laplace(degraded_rec),
            "baseline": _laplace(degraded_all),
            "basis": f"learner=Laplace rate of degraded_steps>=1 over last {len(degraded_rec)}; "
                     f"baseline=Laplace rate over all {len(degraded_all)}; scored by Brier",
        },
        "self_step_fail": {},
    }

    # Per-step: only steps that FAILED at least once in the recent logs.
    # A night with no log is unknowable and is dropped from BOTH rates.
    rec_sets = [(c, failed_steps(c["cycle_id"], logs_dir)) for c in recent]
    all_sets = [(c, failed_steps(c["cycle_id"], logs_dir)) for c in fin]
    rec_known = [s for _, s in rec_sets if s is not None]
    all_known = [s for _, s in all_sets if s is not None]
    candidates = set().union(*rec_known) if rec_known else set()
    for step in sorted(candidates):
        out["self_step_fail"][step] = {
            "learner": _laplace([1 if step in s else 0 for s in rec_known]),
            "baseline": _laplace([1 if step in s else 0 for s in all_known]),
            "basis": f"learner=Laplace rate of '{step} -> FAILED' over last {len(rec_known)} "
                     f"logged nights; baseline=over all {len(all_known)} logged nights; Brier",
        }
    out["logs_seen"] = {"recent": len(rec_known), "all": len(all_known)}
    return out


def cmd_predict(events: Optional[list[dict]] = None, logs_dir: Path = CYCLE_LOGS_DIR) -> list[dict]:
    events = read_existence() if events is None else events
    try:
        fc = build_forecasts(events, logs_dir)
    except Refused as why:
        print(json.dumps({"REFUSED": str(why), "sealed": 0}, ensure_ascii=False, indent=2))
        raise
    tid = f"next_cycle_after::{fc['anchor']}"
    # ONE FORECAST PER NIGHT (added 10 Sep 2026, before this file was scheduled).
    # The anchor is the last terminal cycle event. If --predict runs twice with no
    # cycle in between — a second morning with no night, a re-run by hand, a
    # scheduled run after a manual one — the anchor is unchanged, and without this
    # the SAME forecast for the SAME night is sealed again. cmd_score() dedupes on
    # ref_hash, not on target, so both copies then score against that one night and
    # a single observation is counted twice in the Brier/MAE mean. The board would
    # move with no new evidence, which is exactly the kind of number this ledger
    # exists to make impossible. Refusing is the correct output: nothing to seal
    # until a cycle ends. (The live ledger had 53 self_failure seals across 53
    # distinct anchors when this was added — the defect was latent, not realised.)
    already = [r for r in pl.read_all()
               if r.get("event") == pl.PREDICTION
               and r.get("target_kind") in KINDS
               and r.get("target_id") == tid]
    if already:
        why = Refused(f"{len(already)} forecast(s) of this file's kinds are already sealed "
                      f"for anchor {fc['anchor']} — one forecast per night; nothing to seal "
                      f"until a cycle ends and the anchor moves")
        print(json.dumps({"REFUSED": str(why), "sealed": 0}, ensure_ascii=False, indent=2))
        raise why
    sealed = []
    for kind in ("self_duration", "self_degraded"):
        f = fc[kind]
        sealed.append(pl.seal_prediction(
            target_kind=kind, target_id=tid, horizon_utc="next_terminal_cycle_event",
            learner_value=f["learner"], baseline_value=f["baseline"], basis=f["basis"],
            seen_cycles=fc["seen_cycles"]))
    for step, f in fc["self_step_fail"].items():
        sealed.append(pl.seal_prediction(
            target_kind="self_step_fail", target_id=tid, horizon_utc="next_terminal_cycle_event",
            learner_value=f["learner"], baseline_value=f["baseline"], basis=f["basis"],
            step=step, seen_cycles=fc["seen_cycles"], logs_seen=fc["logs_seen"]))
    print(json.dumps({"sealed": len(sealed), "anchor": fc["anchor"],
                      "duration_s": fc["self_duration"], "degraded": fc["self_degraded"],
                      "steps": {k: v["learner"] for k, v in fc["self_step_fail"].items()}},
                     ensure_ascii=False, indent=2))
    return sealed


# ── scoring ──────────────────────────────────────────────────────────────────

def _brier(p, actual) -> float:
    return round((float(p) - float(actual)) ** 2, 6)


# ── self_survive: p_survive, finally scored (11 Sep 2026, phase-A review) ──────
# core/p_survive.py has computed "the chance the next cycle reaches its end" at
# every boot since 23 Aug and nothing ever checked it: 7 Sep 0.04, 8 Sep 0.0009,
# 11 Sep 0.05 — and all three nights finished. A probability nobody scores is a
# formula. self_forecast already scores the same question (self_failure, Brier
# 0.17 vs 0.33); two self-models for one question is one too many, and the
# ledger decides which one lives. The hard constraint of p_survive.py stands:
# the number never enters a prompt — the ledger is a record, not a prompt.

def survival_baseline(events: list[dict], n: int = 20) -> float:
    """Climatology: Laplace rate of CYCLE_FINISHED among the last n terminal events."""
    term = [e for e in events if e.get("event") in TERMINAL][-n:]
    return _laplace([1 if e.get("event") == "CYCLE_FINISHED" else 0 for e in term])


def seal_survival(cycle_id: str, p, confidence, horizon_seconds=None,
                  events: Optional[list[dict]] = None) -> dict:
    """Seal p_survive for THIS cycle, at boot, before the outcome. Called by
    core/survival_gate._record_p_survive; fail-open there. p None -> note_pending."""
    events = read_existence() if events is None else events
    tid = f"cycle::{cycle_id}"
    if not isinstance(p, (int, float)):
        return pl.note_pending(tid, f"p_survive not measurable at boot (confidence {confidence})",
                               kind=SURVIVE_KIND)
    from datetime import datetime, timedelta, timezone
    hz = float(horizon_seconds or 6 * 3600)
    horizon = (datetime.now(timezone.utc) + timedelta(seconds=hz)).isoformat()
    return pl.seal_prediction(SURVIVE_KIND, tid, horizon, float(p), survival_baseline(events),
                              basis="p_survive: product of time-to-threshold ratios over defended variables "
                                    "(core/p_survive.py); baseline: Laplace rate of finished nights",
                              cycle_id=cycle_id, confidence=confidence, rule="brier")


def _terminal_for(cycle_id: str, events: list[dict]) -> Optional[str]:
    for e in reversed(events):
        if e.get("cycle_id") == cycle_id and e.get("event") in TERMINAL:
            return e.get("event")
    return None


def cmd_score(events: Optional[list[dict]] = None, logs_dir: Path = CYCLE_LOGS_DIR) -> int:
    events = read_existence() if events is None else events
    fin = finished_cycles(events)
    records = pl.read_all()
    already = {r.get("ref_hash") for r in records if r.get("event") == pl.OUTCOME}
    open_preds = [r for r in records if r.get("event") == pl.PREDICTION
                  and r.get("target_kind") in SCORED_KINDS and r.get("hash") not in already]
    n = 0
    for p in open_preds:
        if p["target_kind"] == SURVIVE_KIND:
            # the cycle it was sealed for, by id — its own terminal event decides
            cid = str(p.get("target_id", "")).split("::", 1)[-1]
            term = _terminal_for(cid, events)
            if term is None:
                continue                  # that cycle has not ended — stays open
            actual = 1 if term == "CYCLE_FINISHED" else 0
            pl.score_prediction(p["hash"], actual, scored_cycle=cid, terminal=term,
                                learner_err=_brier(p["learner"], actual),
                                baseline_err=_brier(p["baseline"], actual), rule="brier")
            n += 1
            continue
        # The night being predicted is the first CYCLE_FINISHED after the ANCHOR
        # (the terminal event the seal was made after), not after the seal's own
        # wall-clock — so a replayed or back-dated ledger scores the same way.
        anchor = str(p.get("target_id", "")).split("::", 1)[-1]
        later = [c for c in fin if c["ts"] and c["ts"] > anchor]
        if not later:
            continue                      # that night has not ended — stays open
        c = later[0]
        kind = p["target_kind"]
        if kind == "self_duration":
            if not isinstance(c["duration_sec"], (int, float)):
                continue
            pl.score_prediction(p["hash"], c["duration_sec"], scored_cycle=c["cycle_id"])
        elif kind == "self_degraded":
            actual = 1 if (c["degraded_steps"] or 0) >= 1 else 0
            pl.score_prediction(p["hash"], actual, scored_cycle=c["cycle_id"],
                                learner_err=_brier(p["learner"], actual),
                                baseline_err=_brier(p["baseline"], actual), rule="brier")
        elif kind == "self_step_fail":
            fs = failed_steps(c["cycle_id"], logs_dir)
            if fs is None:
                pl.note_pending(p["target_id"], "no cycle log for the scored night — step "
                                "outcome unknowable; left open", step=p.get("step"),
                                cycle_id=c["cycle_id"])
                continue
            actual = 1 if p.get("step") in fs else 0
            pl.score_prediction(p["hash"], actual, scored_cycle=c["cycle_id"], step=p.get("step"),
                                learner_err=_brier(p["learner"], actual),
                                baseline_err=_brier(p["baseline"], actual), rule="brier")
        n += 1
    print(json.dumps({"newly_scored": n}, ensure_ascii=False, indent=2))
    return n


def cmd_status() -> dict:
    """Per-kind head-to-head for the three kinds this file owns (the full
    board, every kind, is experiments/prophecy/scoreboard.py)."""
    records = pl.read_all()
    out = {}
    for kind in SCORED_KINDS:
        sc = [r for r in records if r.get("event") == pl.OUTCOME and r.get("target_kind") == kind
              and r.get("learner_err") is not None and r.get("baseline_err") is not None]
        n = len(sc)
        out[kind] = {
            "sealed": sum(1 for r in records if r.get("event") == pl.PREDICTION and r.get("target_kind") == kind),
            "scored": n,
            "learner_mean_err": round(sum(r["learner_err"] for r in sc) / n, 4) if n else None,
            "baseline_mean_err": round(sum(r["baseline_err"] for r in sc) / n, 4) if n else None,
            "learner_wins": sum(1 for r in sc if r.get("learner_wins")),
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


# ── selftest: LIVE or INERT, said out loud ───────────────────────────────────

def _selftest() -> int:
    checks = []
    ev = read_existence()
    checks.append(("memory/existence_ledger.jsonl readable", bool(ev)))
    checks.append(("memory/cycle_logs/ exists", CYCLE_LOGS_DIR.exists()))
    checks.append(("prophecy_ledger chain valid", pl.verify().get("valid", False)))
    try:
        fc = build_forecasts(ev)
        checks.append(("build_forecasts() on the real ledger", True))
        print(json.dumps({"would_seal": {"duration": fc["self_duration"], "degraded": fc["self_degraded"],
                                         "steps": {k: v["learner"] for k, v in fc["self_step_fail"].items()},
                                         "logs_seen": fc["logs_seen"]}}, ensure_ascii=False, indent=2))
    except Refused as why:
        checks.append((f"build_forecasts() REFUSED (expected if a cycle runs): {why}", True))
    sealed_here = sum(1 for r in pl.read_all() if r.get("event") == pl.PREDICTION and r.get("target_kind") in KINDS)
    wired = sealed_here > 0
    print(f"INTEGRATION: {'LIVE' if wired else 'INERT'} — {sealed_here} prediction(s) of kinds "
          f"{KINDS} in the prophecy ledger. "
          + ("" if wired else "Nothing schedules this file yet; run --predict from the same task "
                              "that runs prophecy.py --predict."))
    ok = True
    for name, passed in checks:
        print(("OK   " if passed else "FAIL ") + name)
        ok &= bool(passed)
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        if "--predict" in args:
            cmd_predict()
        elif "--score" in args:
            cmd_score()
        elif "--status" in args:
            cmd_status()
        elif "--selftest" in args:
            sys.exit(_selftest())
        else:
            print(__doc__)
    except Refused:
        sys.exit(2)
