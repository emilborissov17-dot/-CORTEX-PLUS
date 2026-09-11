#!/usr/bin/env python3
"""
experiments/prophecy/prophecy.py — K1a runner: sealed self-prediction vs control.

THE TEST (not "does the error curve fall" — a trend-line does that):
does a predictor that ATTENDS TO THE SYSTEM'S RECENT SELF-STATE beat a matched
control that uses only the static base rate? If yes, self-observation adds
predictive value about the system's OWN behaviour — direct evidence for the bet.

FIRST TARGET — self_failure (grounded in the existence ledger, tied to efee6f5):
  learner  = recent-window finish rate  (self-observation: "am I in a healthy
             streak or a dying one right now?")
  baseline = all-time finish rate       (static prior, no current self-knowledge)
  outcome  = did the NEXT cycle actually finish? (existence_ledger)
Both sealed BEFORE the next cycle runs, in the tamper-evident prophecy ledger.

Other targets use the SAME seal API with other signals (scaffolded below):
  patch_effect — a just-applied patch's own measurable_goal vs "no change"
  axis_next    — self-model of next-cycle axis level vs persistence

Usage:
  python experiments/prophecy/prophecy.py --predict   # seal a prediction for the next cycle
  python experiments/prophecy/prophecy.py --score     # score any matured predictions
  python experiments/prophecy/prophecy.py --status     # the K1a scoreboard (learner vs control)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import prophecy_ledger as pl  # noqa: E402

LEDGER_JSONL = REPO / "memory" / "existence_ledger.jsonl"
RECENT_WINDOW = 5   # how many recent cycles count as "recent self-state"


class Refused(Exception):
    """A prediction that cannot honestly be sealed. Raised, never returned, and
    never downgraded to a seal 'with a note'. __main__ exits 2 on it, which
    tools/prophecy_morning.bat reports as an announced non-failure."""


def _cycle_outcomes(ledger_path: Path = LEDGER_JSONL) -> list[dict]:
    """Ordered list of terminal cycle outcomes from the existence ledger.
    finished -> 1, died/killed -> 0. (Read directly; schema is stable.)"""
    if not ledger_path.exists():
        return []
    out = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = e.get("event")
        if ev == "CYCLE_FINISHED":
            out.append({"ts": e.get("ts"), "outcome": 1, "cycle_id": e.get("cycle_id")})
        elif ev in ("CYCLE_DIED", "CYCLE_KILLED"):
            out.append({"ts": e.get("ts"), "outcome": 0, "cycle_id": e.get("cycle_id"),
                        "step": (e.get("last_step") or (e.get("reason") or {}).get("wedged_step"))})
    return out


def _rate(seq: list[int], default: float = 0.9) -> float:
    return round(sum(seq) / len(seq), 4) if seq else default


def cmd_predict(ledger_path: Optional[Path] = None) -> dict:
    # The path is a PARAMETER, resolved at call time. _cycle_outcomes' default
    # binds LEDGER_JSONL at definition time, so a test that monkeypatched the
    # module constant still read the REAL existence ledger — which is how the
    # first run of test_prophecy_one_per_night.py reported on_history=114.
    outcomes = _cycle_outcomes(ledger_path or LEDGER_JSONL)
    hist = [o["outcome"] for o in outcomes]
    baseline_p = _rate(hist)                       # static prior — no current self-knowledge
    learner_p = _rate(hist[-RECENT_WINDOW:])       # attends to recent self-state
    anchor = outcomes[-1]["ts"] if outcomes else "genesis"
    tid = f"next_cycle_after::{anchor}"
    # ONE FORECAST PER NIGHT (added 10 Sep 2026 after this defect was REALISED,
    # not merely spotted: two scheduler runs 64 seconds apart on 10 Sep sealed two
    # identical self_failure forecasts, 5b23984 and 95d22eb, for anchor
    # 2026-09-10T01:49:35. The anchor is the last terminal cycle event, so every
    # --predict between two cycles describes the SAME night. cmd_score() dedupes on
    # ref_hash, not on target, so both copies would score against that one night
    # and one observation would count twice in the Brier mean.
    already = [r for r in pl.read_all()
               if r.get("event") == pl.PREDICTION
               and r.get("target_kind") == "self_failure"
               and r.get("target_id") == tid]
    if already:
        why = Refused(f"{len(already)} self_failure forecast(s) already sealed for anchor "
                      f"{anchor} — one forecast per night; nothing to seal until a cycle "
                      f"ends and the anchor moves")
        print(json.dumps({"REFUSED": str(why), "sealed": 0}, ensure_ascii=False, indent=2))
        raise why
    rec = pl.seal_prediction(
        target_kind="self_failure",
        target_id=tid,
        horizon_utc="next_terminal_cycle_event",
        learner_value=learner_p,       # P(next cycle finishes)
        baseline_value=baseline_p,
        basis=f"learner=recent {RECENT_WINDOW}-cycle finish-rate; baseline=all-time finish-rate",
        seen_cycles=len(hist),
    )
    print(json.dumps({"sealed": rec["hash"][:12], "learner_p_finish": learner_p,
                      "baseline_p_finish": baseline_p, "on_history": len(hist)},
                     ensure_ascii=False, indent=2))
    return rec


def cmd_score(ledger_path: Optional[Path] = None) -> None:
    outcomes = _cycle_outcomes(ledger_path or LEDGER_JSONL)
    records = pl.read_all()
    scored_refs = {r.get("ref_hash") for r in records if r.get("event") == pl.OUTCOME}
    open_preds = [r for r in records
                  if r.get("event") == pl.PREDICTION
                  and r.get("target_kind") == "self_failure"
                  and r.get("hash") not in scored_refs]
    # THE DUPLICATE ALREADY IN THE CHAIN. The guard in cmd_predict stops new ones,
    # but the ledger is an append-only hash chain with no void event: 95d22eb is in
    # it for good and cannot be deleted without breaking every hash after it. So
    # the containment lives here. Where several OPEN self_failure predictions share
    # one target_id, they are one forecast of one night; only the earliest is
    # scored, and the rest are recorded PENDING with the reason, so the duplicate
    # stays visible in the ledger and still never becomes a second observation.
    # Scoped to self_failure on purpose: axis_next's target_id is
    # '<AXIS>::next_cycle_score', which is NOT anchor-scoped and repeats legitimately
    # every night, so the same rule there would discard real predictions.
    # A superseded duplicate is never scored, so it stays OPEN forever. Noting it
    # on every --score would append one PENDING record per morning without end, so
    # the note is written once and the record of having written it is the guard.
    noted = {r.get("superseded_hash") for r in records if r.get("event") == pl.PENDING}
    seen_targets: set = set()
    deduped = []
    for p in sorted(open_preds, key=lambda r: str(r.get("ts") or "")):
        tid = p.get("target_id")
        if tid in seen_targets:
            if p.get("hash") not in noted:
                pl.note_pending(tid, "duplicate seal for this anchor — an earlier sealed "
                                     "prediction already covers this night; superseded, "
                                     "never scored, so one night counts once",
                                superseded_hash=p.get("hash"))
            continue
        seen_targets.add(tid)
        deduped.append(p)
    n = 0
    for p in deduped:
        # the actual = the first terminal cycle outcome that happened AFTER the seal
        later = [o for o in outcomes if o["ts"] and o["ts"] > p["ts"]]
        if not later:
            continue  # horizon not matured yet — leave it open
        actual = later[0]["outcome"]   # 1 finished / 0 died
        pl.score_prediction(p["hash"], actual)
        n += 1
    print(json.dumps({"newly_scored": n}, ensure_ascii=False, indent=2))


def cmd_status() -> None:
    print(json.dumps(pl.scoreboard(), ensure_ascii=False, indent=2))


# ── axis_next: sealed axis-level self-predictions ─────────────────────────────
# The second target_kind, under the SAME tamper-evident apparatus (prophecy_ledger).
# This replaces the legacy, UNSEALED memory/predictions.json path — those records
# are quarantined as non-authoritative (see memory/prediction_tracker.py). We seal
# only axes whose scorer's key contract holds (core.scorer_self_check LIVE), so a
# prediction is never sealed against an outcome we cannot honestly measure later.

AXIS_HISTORY = REPO / "memory" / "axis_history.json"


def _axis_history_scores(axis: str) -> list[float]:
    """Numeric score series for an axis (cortex_scoring_engine-derived, 0-100)."""
    try:
        hist = json.loads(AXIS_HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return []
    series = hist.get(axis) if isinstance(hist, dict) else None
    if not isinstance(series, list):
        return []
    out = []
    for e in series:
        v = e.get("score") if isinstance(e, dict) else e
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(float(v))
    return out


def _live_axes() -> set:
    """Axes whose scorer actually consumes real data (authoritative outcome).
    Uses the facade self-check so we never seal against a fabricated ground."""
    from core.scorer_self_check import run_from_snapshots, LIVE
    return {r["axis"] for r in run_from_snapshots()["axes"] if r["verdict"] == LIVE}


def _learner_baseline(scores: list[float], alpha: Optional[float] = None) -> tuple[float, float, float]:
    """baseline = persistence (last score, no self-knowledge of trend).
    learner  = EWMA over the axis's own history, alpha chosen by past error.

    UNTIL 2026-09-10 the learner was last-step extrapolation
    (cur + (cur - prev)). Measured on the six indicators that move
    (claude/reports/WORLD_FORECAST_BENCH.md) it lost to persistence 0/6,
    at roughly twice the error, and on the 127 non-degenerate axis_next
    outcomes in this ledger it won 12. A learner that is worse than doing
    nothing is retired; the replacement must EARN its place on the scoreboard
    (experiments/prophecy/scoreboard.py, kinds axis_next / world_next) or it
    goes the same way.
    """
    cur = scores[-1]
    baseline = cur
    if len(scores) >= 2:
        a = alpha if alpha is not None else _fit_alpha(scores)
        s = scores[0]
        for v in scores[1:]:
            s = a * v + (1 - a) * s
        learner = max(0.0, min(100.0, s))
    else:
        learner = cur  # degenerate — no history to attend to yet
    return round(learner, 4), round(baseline, 4), round(cur, 4)


def _fit_alpha(scores: list[float]) -> float:
    """The EWMA alpha with the lowest rolling one-step error on THIS history —
    the same rule world_forecast.fit_alpha uses. Duplicated in a few lines rather
    than imported so this file keeps its single sibling import (prophecy_ledger)."""
    def mae(a: float) -> float:
        errs = []
        for t in range(3, len(scores)):
            s = scores[0]
            for v in scores[1:t]:
                s = a * v + (1 - a) * s
            errs.append(abs(s - scores[t]))
        return sum(errs) / len(errs) if errs else float("inf")
    return min((0.1, 0.2, 0.3, 0.5, 0.7, 0.9), key=mae)


def seal_axis_prediction(axis: str, learner: float, baseline: float,
                         current: float, basis: str, **extra) -> dict:
    """Seal ONE axis-level self-prediction into the tamper-evident prophecy
    ledger (target_kind='axis_next'), BEFORE the next cycle's score is known."""
    return pl.seal_prediction(
        target_kind="axis_next",
        target_id=f"{axis}::next_cycle_score",
        horizon_utc="next_cycle_axis_score",
        learner_value=learner,
        baseline_value=baseline,
        basis=basis,
        axis=axis,
        current_score=current,
        **extra,
    )


def cmd_predict_axes(one_axis: str | None = None) -> list:
    """Seal axis_next predictions. With one_axis, seal just that axis (the
    sanity path). Otherwise seal every LIVE axis (batch)."""
    live = _live_axes()
    targets = [one_axis] if one_axis else sorted(live)
    sealed = []
    for ax in targets:
        if ax not in live:
            print(json.dumps({"skipped": ax, "reason": "scorer not LIVE — no authoritative outcome"}))
            continue
        scores = _axis_history_scores(ax)
        if not scores:
            print(json.dumps({"skipped": ax, "reason": "no score history"}))
            continue
        learner, baseline, cur = _learner_baseline(scores)
        rec = seal_axis_prediction(
            ax, learner, baseline, cur,
            basis="learner=EWMA(alpha fitted on this axis's history); baseline=persistence; scale=axis_history 0-100",
            seen=len(scores), degenerate=(learner == baseline),
        )
        sealed.append(rec)
        print(json.dumps({"sealed": rec["hash"][:12], "axis": ax,
                          "learner": learner, "baseline": baseline, "current": cur},
                         ensure_ascii=False))
    return sealed


def cmd_score_axes() -> None:
    """Score matured axis_next predictions against the next observed score."""
    records = pl.read_all()
    scored_refs = {r.get("ref_hash") for r in records if r.get("event") == pl.OUTCOME}
    open_preds = [r for r in records
                  if r.get("event") == pl.PREDICTION and r.get("target_kind") == "axis_next"
                  and r.get("hash") not in scored_refs]
    n = 0
    for p in open_preds:
        scores = _axis_history_scores(p.get("axis", ""))
        if len(scores) <= int(p.get("seen", 0)):
            continue  # horizon not matured — no newer score yet
        pl.score_prediction(p["hash"], scores[-1])
        n += 1
    print(json.dumps({"newly_scored": n}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        if "--predict-axes" in sys.argv:
            _axis = None
            if "--axis" in sys.argv:
                _axis = sys.argv[sys.argv.index("--axis") + 1]
            cmd_predict_axes(_axis)
        elif "--score-axes" in sys.argv:
            cmd_score_axes()
        elif "--predict" in sys.argv:
            cmd_predict()
        elif "--score" in sys.argv:
            cmd_score()
        else:
            cmd_status()
    except Refused:
        # A refusal is an outcome, not a crash. Exit 2 is the house convention
        # (self_forecast.py uses it too) and tools/prophecy_morning.bat reports it
        # as announced-and-not-a-failure rather than cancelling the rest of the
        # morning, which `&&` chaining used to do.
        sys.exit(2)
