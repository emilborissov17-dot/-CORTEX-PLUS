#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/prophecy/scoreboard.py — THE BOARD FOR CORTEX'S OWN PREDICTIONS.
(10 September 2026. Ivan: "Brier скорборд има, но той мери Claude, не CORTEX —
да се направи и за CORTEX.")

WHAT EXISTED
------------
claude/reports/PREDICTIONS_SCOREBOARD.md scores CLAUDE's pre-registered
numbers. prophecy_ledger.scoreboard() scores CORTEX, but as ONE lump: every
target_kind pooled into one MAE, so 620 degenerate axis predictions
(learner == baseline == 50.0) drown the 52 real self_failure calls, and the
verdict "learner_beats_control: false" says nothing about which predictor is
actually bad. And it reports MAE for probabilities, which is not a proper
scoring rule — a hedge to 0.5 is never punished.

WHAT THIS DOES
--------------
Reads the SAME ledger (read-only), verifies the chain FIRST and refuses to
score a broken one, then reports PER target_kind:

  probability kinds (self_failure, self_degraded, self_step_fail):
      BRIER for learner, baseline, and the climatology reference
      (the actual base rate over the scored set — the score a predictor gets
      for saying the same number every night). Brier is recomputed here from
      the SEALED values, so the number is the same rule for every kind
      regardless of what the sealer wrote into learner_err at the time.
  numeric kinds (axis_next, self_duration, composer_series, ...):
      MAE for learner and baseline; degenerate predictions (learner ==
      baseline at seal time) are COUNTED and shown but excluded from the
      head-to-head, because a tie carries no information about either.

  Each row also shows the last-30 window, so a predictor that has started
  learning is visible before the all-time mean moves.

Writes claude/reports/PROPHECY_SCOREBOARD.md only with --write. Prints JSON
otherwise. Never appends to the ledger.

Usage:
  venv\\Scripts\\python.exe experiments/prophecy/scoreboard.py
  venv\\Scripts\\python.exe experiments/prophecy/scoreboard.py --write
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import prophecy_ledger as pl  # noqa: E402

REPORT = REPO / "claude" / "reports" / "PROPHECY_SCOREBOARD.md"
PROB_KINDS = {"self_failure", "self_degraded", "self_step_fail"}
WINDOW = 30


class ChainBroken(RuntimeError):
    pass


def _mean(xs: list) -> Optional[float]:
    return round(sum(xs) / len(xs), 4) if xs else None


def _pairs(records: list[dict]) -> list[tuple[dict, dict]]:
    """(sealed, outcome) pairs, ledger order, one per scored prediction."""
    sealed = {r["hash"]: r for r in records if r.get("event") == pl.PREDICTION}
    out = []
    for r in records:
        if r.get("event") != pl.OUTCOME:
            continue
        s = sealed.get(r.get("ref_hash"))
        if s is not None:
            out.append((s, r))
    return out


def _is_degenerate(s: dict) -> bool:
    if s.get("degenerate") is True:
        return True
    try:
        return float(s.get("learner")) == float(s.get("baseline"))
    except (TypeError, ValueError):
        return False


def _row(kind: str, pairs: list[tuple[dict, dict]]) -> dict:
    """One scoreboard row for one kind. Pure."""
    live = [(s, o) for s, o in pairs if not _is_degenerate(s)]
    deg = len(pairs) - len(live)
    row = {"kind": kind, "scored": len(pairs), "degenerate_excluded": deg, "compared": len(live)}
    if kind in PROB_KINDS:
        def brier(sel):
            L = [(float(s["learner"]) - float(o["actual"])) ** 2 for s, o in sel]
            B = [(float(s["baseline"]) - float(o["actual"])) ** 2 for s, o in sel]
            acts = [float(o["actual"]) for s, o in sel]
            base_rate = (sum(acts) / len(acts)) if acts else None
            C = [(base_rate - a) ** 2 for a in acts] if acts else []
            return {"learner": _mean(L), "baseline": _mean(B), "climatology": _mean(C),
                    "base_rate": round(base_rate, 4) if base_rate is not None else None,
                    "learner_wins": sum(1 for l, b in zip(L, B) if l < b), "n": len(sel)}
        row["rule"] = "brier"
        row["all_time"] = brier(live)
        row["last_30"] = brier(live[-WINDOW:])
    else:
        def mae(sel):
            L = [float(o["learner_err"]) for s, o in sel if o.get("learner_err") is not None]
            B = [float(o["baseline_err"]) for s, o in sel if o.get("baseline_err") is not None]
            return {"learner": _mean(L), "baseline": _mean(B),
                    "learner_wins": sum(1 for l, b in zip(L, B) if l < b), "n": len(L)}
        row["rule"] = "mae"
        row["all_time"] = mae(live)
        row["last_30"] = mae(live[-WINDOW:])
    a = row["all_time"]
    row["learner_beats_baseline"] = (a["n"] > 0 and a["learner"] is not None and a["baseline"] is not None
                                     and a["learner"] < a["baseline"])
    return row


def build(records: Optional[list[dict]] = None) -> dict:
    ver = pl.verify()
    if not ver.get("valid"):
        raise ChainBroken(f"prophecy ledger chain broken at seq {ver.get('broken_at')} — "
                          f"nothing on it can be scored until that is explained")
    records = pl.read_all() if records is None else records
    pairs = _pairs(records)
    kinds = sorted({s.get("target_kind") for s, _ in pairs})
    rows = [_row(k, [(s, o) for s, o in pairs if s.get("target_kind") == k]) for k in kinds]
    open_by_kind = {}
    scored_refs = {o.get("ref_hash") for _, o in pairs}
    for r in records:
        if r.get("event") == pl.PREDICTION and r.get("hash") not in scored_refs:
            open_by_kind[r.get("target_kind")] = open_by_kind.get(r.get("target_kind"), 0) + 1
    return {"generated_utc": datetime.now(timezone.utc).isoformat(), "chain": ver,
            "events": len(records), "rows": rows, "open_predictions": open_by_kind}


def to_markdown(board: dict) -> str:
    L = ["# PROPHECY SCOREBOARD — CORTEX's own sealed predictions, scored",
         f"Generated {board['generated_utc']} · ledger events {board['events']} · chain "
         f"{'VALID' if board['chain'].get('valid') else 'BROKEN'} · head {str(board['chain'].get('head_hash'))[:12]}",
         "", "Learner = the self-observing predictor. Baseline = the control that does not look at",
         "recent self-state. Climatology = the constant base rate over the scored set. Lower is better.",
         "Brier for probabilities, MAE for numbers. Degenerate = learner and baseline sealed the same",
         "number: counted, not compared.", "",
         "| kind | rule | scored | degen. | compared | learner | baseline | climatology | learner wins | last-30 learner | last-30 baseline | verdict |",
         "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in board["rows"]:
        a, w = r["all_time"], r["last_30"]
        clim = a.get("climatology")
        L.append(f"| {r['kind']} | {r['rule']} | {r['scored']} | {r['degenerate_excluded']} | {r['compared']} | "
                 f"{a['learner']} | {a['baseline']} | {'' if clim is None else clim} | "
                 f"{a['learner_wins']}/{a['n']} | {w['learner']} | {w['baseline']} | "
                 f"{'LEARNER BEATS BASELINE' if r['learner_beats_baseline'] else 'baseline holds'} |")
    if board["open_predictions"]:
        L += ["", "Open (sealed, not yet matured): " +
              ", ".join(f"{k} {v}" for k, v in sorted(board["open_predictions"].items()))]
    L += ["", "Read-only over experiments/prophecy/prophecy_ledger.jsonl. Regenerate: "
          "`venv\\Scripts\\python.exe experiments/prophecy/scoreboard.py --write`."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    try:
        board = build()
    except ChainBroken as why:
        print(json.dumps({"REFUSED": str(why)}, ensure_ascii=False))
        sys.exit(2)
    if "--write" in sys.argv:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(to_markdown(board), encoding="utf-8")
        print(f"wrote {REPORT}")
    print(json.dumps(board, ensure_ascii=False, indent=2))
