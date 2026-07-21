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

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import prophecy_ledger as pl  # noqa: E402

LEDGER_JSONL = REPO / "memory" / "existence_ledger.jsonl"
RECENT_WINDOW = 5   # how many recent cycles count as "recent self-state"


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


def cmd_predict() -> dict:
    outcomes = _cycle_outcomes()
    hist = [o["outcome"] for o in outcomes]
    baseline_p = _rate(hist)                       # static prior — no current self-knowledge
    learner_p = _rate(hist[-RECENT_WINDOW:])       # attends to recent self-state
    anchor = outcomes[-1]["ts"] if outcomes else "genesis"
    rec = pl.seal_prediction(
        target_kind="self_failure",
        target_id=f"next_cycle_after::{anchor}",
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


def cmd_score() -> None:
    outcomes = _cycle_outcomes()
    records = pl.read_all()
    scored_refs = {r.get("ref_hash") for r in records if r.get("event") == pl.OUTCOME}
    open_preds = [r for r in records
                  if r.get("event") == pl.PREDICTION
                  and r.get("target_kind") == "self_failure"
                  and r.get("hash") not in scored_refs]
    n = 0
    for p in open_preds:
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


def _learner_baseline(scores: list[float]) -> tuple[float, float, float]:
    """baseline = persistence (last score, no self-knowledge of trend).
    learner  = recent-trend self-model (extrapolate the last step), clamped."""
    cur = scores[-1]
    baseline = cur
    if len(scores) >= 2:
        learner = max(0.0, min(100.0, cur + (scores[-1] - scores[-2])))
    else:
        learner = cur  # degenerate — no trend to attend to yet
    return round(learner, 4), round(baseline, 4), round(cur, 4)


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
            basis="learner=last-step trend extrapolation; baseline=persistence; scale=axis_history 0-100",
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
