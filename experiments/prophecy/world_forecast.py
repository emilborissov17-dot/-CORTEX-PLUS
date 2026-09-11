#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/prophecy/world_forecast.py — THE WORLD LOOP. Predict tomorrow's
number, seal it, fetch the outcome, score it, and let the ERROR change the
predictor. (10 September 2026. Emil: "действай и мисли така, че да помага".)

WHY THIS IS THE AGI-RELEVANT PIECE, AND WHY OPENCLAW SITS INSIDE IT
-------------------------------------------------------------------
Measured on 2026-09-10 over memory/axis_history.json: of 104 world indicators
the system carries, 8 change five or more times across ~100 nights. The rest
are annual World Bank figures — at the system's sampling rate the world is
frozen, so nothing can be learned about it (no variance -> no causality, no
credit, no transfer). That is why 609 of 736 axis_next predictions were
degenerate and why archive-LoRA had nothing to learn: the archive was the
system talking to itself about a world that did not move.

The daily tier (L1-DAILY: NOAA CO2, USGS, GDACS, GDELT, NSIDC, SWPC, UNHCR,
Wikimedia; core/gdelt_daily.py, usgs_quakes.py, market_daily.py) is the
substrate that moves. This module is the loop on top of it:

  1. every night, for every indicator that MOVES, seal a prediction of its
     next value — learner vs persistence — in the SAME tamper-evident
     prophecy ledger (target_kind "world_next");
  2. when the next value arrives (the cycle's own fetch, or OpenClaw for a
     source with no API — Layer A's job is to go and GET the outcome, which
     is the action->consequence contour, point 15), score it;
  3. the learner's parameter (EWMA alpha per indicator) is re-fitted from the
     scored errors and STORED in memory/learner_state.json — learning that
     stays in the system (point 11), not in a prompt;
  4. the transfer test (point 1): alpha fitted on indicator set A is judged
     on indicator set B it never saw, against persistence. That is the
     smallest honest version of "learned here works there".

What this refuses to do: no neural weights, no LLM in the learner. The
learner must beat persistence on unseen data BEFORE anything more expensive
is tried — the same rule that killed archive-LoRA, applied in advance.

Usage:
  venv\\Scripts\\python.exe experiments/prophecy/world_forecast.py --bench      # rolling one-step eval + transfer, read-only
  venv\\Scripts\\python.exe experiments/prophecy/world_forecast.py --predict    # seal world_next for every moving indicator
  venv\\Scripts\\python.exe experiments/prophecy/world_forecast.py --score      # score matured predictions, refit alpha
  venv\\Scripts\\python.exe experiments/prophecy/world_forecast.py --selftest
"""
from __future__ import annotations

import json
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

AXIS_HISTORY = REPO / "memory" / "axis_history.json"
LEARNER_STATE = REPO / "memory" / "learner_state.json"
REPORT = REPO / "claude" / "reports" / "WORLD_FORECAST_BENCH.md"

MIN_CHANGES = 5          # an indicator that changed fewer times is frozen; nothing to predict
MIN_POINTS = 12          # below this a fitted alpha is a guess
ALPHAS = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
KIND = "world_next"
# Things in axis_history that are the system's own output, not the world.
NOT_WORLD = {"STRATEGIST_SOLUTIONS", "OPENCLAW_SOLUTIONS", "BODY_SCAN", "HYPERCLAW_PLAN",
             "GENERAL_SELF_REVIEW", "master_snapshot_latest", "climate_global_risk_review_snapshot_latest"}


class Refused(RuntimeError):
    pass


# ── series ───────────────────────────────────────────────────────────────────

def _moving(pts: list) -> bool:
    vals = [v for _, v in pts]
    changes = sum(1 for a, b in zip(vals, vals[1:]) if a != b)
    return changes >= MIN_CHANGES and len(pts) >= MIN_POINTS


def load_series(path: Path = AXIS_HISTORY, tier_path: Optional[Path] = None) -> dict:
    """{ 'AXIS::metric': [(date, value), ...] } — one value per date (last wins),
    only indicators that MOVE. Read-only.

    Two sources, one rule. axis_history (the axis reviews' metrics, mostly annual)
    and the DAILY TIER (core/daily_tier.py: every numeric leaf of the nightly
    global_indicators fetch, kept instead of overwritten — AGI-5, 10 Sep 2026),
    under the key 'DAILY::section.key'. The tier is where the world moves at the
    system's sampling rate; before it existed this function found 8 moving
    indicators, all CLIMATE, and 609/736 axis_next predictions were degenerate."""
    out = {}
    try:
        from core import daily_tier as _dt  # noqa: PLC0415
        tier = _dt.series(tier_path) if tier_path is not None else _dt.series()
    except Exception:  # noqa: BLE001 — the tier is additive; its absence is not a refusal
        tier = {}
    for k, pts in tier.items():
        if _moving(pts):
            out[f"DAILY::{k}"] = pts
    if not path.exists():
        return out
    h = json.loads(path.read_text(encoding="utf-8"))
    for axis, ser in h.items():
        if axis in NOT_WORLD or not isinstance(ser, list):
            continue
        by_metric: dict = {}
        for e in ser:
            if not isinstance(e, dict):
                continue
            d = e.get("date")
            for k, v in (e.get("metrics") or {}).items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and d:
                    by_metric.setdefault(k, {})[d] = float(v)
        for k, dv in by_metric.items():
            pts = sorted(dv.items())
            if _moving(pts):
                out[f"{axis}::{k}"] = pts
    return out


# ── learners (pure functions over a history) ─────────────────────────────────

def persistence(vals: list[float]) -> float:
    return vals[-1]


def last_step(vals: list[float]) -> float:
    """What axis_next does today: extrapolate the last step. Kept as the thing to beat."""
    return vals[-1] + (vals[-1] - vals[-2]) if len(vals) >= 2 else vals[-1]


def ewma(vals: list[float], alpha: float) -> float:
    s = vals[0]
    for v in vals[1:]:
        s = alpha * v + (1 - alpha) * s
    return s


def rolling_mae(vals: list[float], fn, warm: int = 5) -> Optional[float]:
    """One-step-ahead: at each t >= warm predict vals[t] from vals[:t]."""
    errs = [abs(fn(vals[:t]) - vals[t]) for t in range(warm, len(vals))]
    return round(statistics.mean(errs), 6) if errs else None


def fit_alpha(vals: list[float]) -> float:
    """The alpha with the lowest rolling MAE on THIS history. This is the
    learning step: a number chosen by past error, stored, reused."""
    best = min(ALPHAS, key=lambda a: rolling_mae(vals, lambda h: ewma(h, a)) or float("inf"))
    return best


# ── the bench: learners vs persistence, and transfer ────────────────────────

def bench(series: Optional[dict] = None) -> dict:
    series = load_series() if series is None else series
    rows = []
    for name, pts in sorted(series.items()):
        vals = [v for _, v in pts]
        a = fit_alpha(vals)
        rows.append({
            "indicator": name, "n": len(vals),
            "persistence": rolling_mae(vals, persistence),
            "last_step": rolling_mae(vals, last_step),
            "ewma_fitted": rolling_mae(vals, lambda h: ewma(h, a)), "alpha": a,
        })
    # TRANSFER: fit alpha on every indicator EXCEPT this one (leave-one-out),
    # apply it here, compare with persistence. "Learned there, judged here."
    for r in rows:
        others = [x for x in rows if x is not r]
        if not others:
            r["transfer_alpha"] = None; r["ewma_transfer"] = None; continue
        # the alpha most often chosen elsewhere (mode); ties -> smallest
        counts = {}
        for x in others:
            counts[x["alpha"]] = counts.get(x["alpha"], 0) + 1
        ta = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        vals = [v for _, v in series[r["indicator"]]]
        r["transfer_alpha"] = ta
        r["ewma_transfer"] = rolling_mae(vals, lambda h: ewma(h, ta))
    def wins(key):
        return sum(1 for r in rows if r[key] is not None and r["persistence"] is not None and r[key] < r["persistence"])
    verdict = {
        "indicators_that_move": len(rows),
        "last_step_beats_persistence": f"{wins('last_step')}/{len(rows)}",
        "ewma_fitted_beats_persistence": f"{wins('ewma_fitted')}/{len(rows)}",
        "ewma_TRANSFER_beats_persistence": f"{wins('ewma_transfer')}/{len(rows)}",
        "reading": ("a learner that only ever sees the same indicator is not tested for transfer; "
                    "the TRANSFER row is the one that speaks to point 1 (generality)"),
    }
    return {"rows": rows, "verdict": verdict}


def bench_markdown(b: dict) -> str:
    L = ["# WORLD FORECAST BENCH — learners vs persistence on the indicators that actually move",
         "", "Rolling one-step-ahead MAE (lower is better). `last_step` is what axis_next does today.",
         "`ewma_fitted` chose its alpha on this indicator's own past; `ewma_transfer` uses the alpha",
         "learned on the OTHER indicators (leave-one-out) — the generality test.", "",
         "| indicator | n | persistence | last_step | ewma_fitted (α) | ewma_transfer (α) |",
         "|---|---:|---:|---:|---:|---:|"]
    for r in b["rows"]:
        L.append(f"| {r['indicator']} | {r['n']} | {r['persistence']} | {r['last_step']} | "
                 f"{r['ewma_fitted']} ({r['alpha']}) | {r['ewma_transfer']} ({r['transfer_alpha']}) |")
    L += ["", "## Verdict", ""] + [f"- {k}: {v}" for k, v in b["verdict"].items()] + [""]
    return "\n".join(L)


# ── seal / score in the prophecy ledger ──────────────────────────────────────

def _state() -> dict:
    if LEARNER_STATE.exists():
        try:
            return json.loads(LEARNER_STATE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def cmd_predict(series: Optional[dict] = None) -> list[dict]:
    series = load_series() if series is None else series
    if not series:
        raise Refused("no indicator moves >= %d times — nothing to predict; the daily tier is the fix" % MIN_CHANGES)
    state = _state()
    sealed = []
    for name, pts in sorted(series.items()):
        vals = [v for _, v in pts]
        last_date = pts[-1][0]
        alpha = state.get(name, {}).get("alpha") or fit_alpha(vals)
        sealed.append(pl.seal_prediction(
            target_kind=KIND, target_id=f"{name}::after::{last_date}",
            horizon_utc="next_observed_value",
            learner_value=round(ewma(vals, alpha), 6), baseline_value=round(persistence(vals), 6),
            basis=f"learner=EWMA(alpha={alpha}) over {len(vals)} obs; baseline=persistence; "
                  f"scored by abs error against the next value dated after {last_date}",
            indicator=name, last_date=last_date, seen=len(vals)))
    print(json.dumps({"sealed": len(sealed), "indicators": [s["indicator"] for s in sealed]}, ensure_ascii=False, indent=2))
    return sealed


def cmd_score(series: Optional[dict] = None) -> int:
    """Score every world_next whose indicator has a value dated AFTER last_date;
    then refit alpha from the full history and store it (the learning step)."""
    series = load_series() if series is None else series
    records = pl.read_all()
    already = {r.get("ref_hash") for r in records if r.get("event") == pl.OUTCOME}
    open_preds = [r for r in records if r.get("event") == pl.PREDICTION
                  and r.get("target_kind") == KIND and r.get("hash") not in already]
    n = 0
    touched = set()
    for p in open_preds:
        pts = series.get(p.get("indicator"), [])
        later = [(d, v) for d, v in pts if d > p.get("last_date", "")]
        if not later:
            continue
        d, v = later[0]
        pl.score_prediction(p["hash"], v, observed_date=d, indicator=p["indicator"])
        touched.add(p["indicator"])
        n += 1
    if touched:
        state = _state()
        for name in touched:
            vals = [v for _, v in series[name]]
            state[name] = {"alpha": fit_alpha(vals), "fitted_on": len(vals), "updated": pl._utc_now()}
        LEARNER_STATE.parent.mkdir(parents=True, exist_ok=True)
        LEARNER_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"newly_scored": n, "alpha_refit_for": sorted(touched)}, ensure_ascii=False, indent=2))
    return n


def _selftest() -> int:
    ok = True
    s = load_series()
    print(f"indicators that move (>= {MIN_CHANGES} changes, >= {MIN_POINTS} points): {len(s)}")
    for k in sorted(s):
        print("  ", k, len(s[k]))
    b = bench(s) if s else {"verdict": {}}
    print(json.dumps(b["verdict"], ensure_ascii=False, indent=2))
    sealed = sum(1 for r in pl.read_all() if r.get("event") == pl.PREDICTION and r.get("target_kind") == KIND)
    print(f"INTEGRATION: {'LIVE' if sealed else 'INERT'} — {sealed} {KIND} prediction(s) in the ledger; "
          f"learner_state.json {'exists' if LEARNER_STATE.exists() else 'absent'}")
    ok &= bool(s)
    return 0 if ok else 1


if __name__ == "__main__":
    a = sys.argv[1:]
    try:
        if "--bench" in a:
            b = bench()
            if "--write" in a:
                REPORT.parent.mkdir(parents=True, exist_ok=True)
                REPORT.write_text(bench_markdown(b), encoding="utf-8")
                print(f"wrote {REPORT}")
            print(bench_markdown(b))
        elif "--predict" in a:
            cmd_predict()
        elif "--score" in a:
            cmd_score()
        elif "--selftest" in a:
            sys.exit(_selftest())
        else:
            print(__doc__)
    except Refused as why:
        print(json.dumps({"REFUSED": str(why)}, ensure_ascii=False))
        sys.exit(2)
