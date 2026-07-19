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


if __name__ == "__main__":
    if "--predict" in sys.argv:
        cmd_predict()
    elif "--score" in sys.argv:
        cmd_score()
    else:
        cmd_status()
