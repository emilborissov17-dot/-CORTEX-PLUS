#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/prophecy/cross_series_bench.py — E1: DOES KNOWING THE OTHERS HELP?
(11 Sep 2026. Emil: "search for a solution for AGI in parallel — experiment".)

THE CURRICULUM (Emil, 11 Sep 2026, correcting me): asking a model to hit an exact price
is the wrong exam, and I was ready to call the markets "unpredictable" from it.
  STAGE 1  direction — up or down, over the next day, week (5) and month (20), against
           honest baselines (always up, momentum, training majority), win = +2 SE;
  STAGE 2  the size of the step in % of today's value, as an 80% conformal range;
  STAGE 3  the exact level — kept only as the hardest table, never as the verdict.

The daily tier is the world that moves. world_forecast learns ONE parameter per
series from that series alone. This bench asks the two questions the AGI table
leaves empty on the moving substrate:

  point 1 (transfer)     — does a model that sees ALL daily series predict a series
                           better than the same model on that series alone? And do
                           weights learned on series A, applied to series B, beat
                           persistence on B? ("learned there, judged here")
  point 3 (few examples) — how fast does the error fall with the number of training
                           rows: k = 10, 20, 40, 80? A learner that needs 80 rows to
                           beat yesterday's value has not learned from few examples.

Method: walk-forward, one step ahead, pure Python (no numpy on the machine).
  * every series is turned into day-to-day differences, standardized on the
    training window only (no look-ahead);
  * features for day t: lags 1..LAGS of the standardized differences of every
    series (forward-filled to the target's calendar);
  * target: the standardized difference at t+1; the prediction is turned back
    into a value and judged by absolute error against the actual next value;
  * models: persistence (no change), EWMA (world_forecast.fit_alpha), ridge on
    the target's own lags, ridge on all lags; the same ridge weights transferred
    from every other target.
  * E2 (point 4, new concepts): the other series whose same-day moves go with the
    target's (|r| >= 0.5 on the training window) form a concept, named by its members;
    yesterday's signed mean move of the concept is one feature. The concept SURVIVES
    only if own-lags + concept beats own-lags alone out of sample.
  * E4 (point 7, calibrated uncertainty): split-conformal 80% intervals from errors
    already seen; coverage is counted against what actually happened.
Reports claude/reports/CROSS_SERIES_BENCH.md + .json. Read by scripts/agi_scoreboard.py
(points 1 and 3). Nothing here trades, sizes, or recommends anything (spec §VI).

Usage:
  venv\\Scripts\\python.exe experiments\\prophecy\\cross_series_bench.py            # print
  venv\\Scripts\\python.exe experiments\\prophecy\\cross_series_bench.py --write    # + reports
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "experiments" / "prophecy"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

REPORT = REPO / "claude" / "reports" / "CROSS_SERIES_BENCH.md"
REPORT_JSON = REPO / "claude" / "reports" / "CROSS_SERIES_BENCH.json"

LAGS = 3
MIN_POINTS = 40          # a target needs at least this many aligned days
WARM = 25                # first prediction after this many rows
LAMBDA = 1.0             # ridge penalty on standardized features
KS = (10, 20, 40, 80)    # learning curve: rows the model may see
CONCEPT_CORR = 0.5       # E2: a series joins the target's concept if |corr of daily moves| >= this on the training window
CONFORMAL_LEVEL = 0.8    # E4: the interval must contain the actual next value this often
CONFORMAL_MIN = 10       # past errors needed before an interval is issued
HORIZONS = (1, 5, 20)    # direction is judged over the next day, week (5 trading days) and month (20)


# ── data ─────────────────────────────────────────────────────────────────────

def load_tier() -> dict[str, list[tuple[str, float]]]:
    try:
        from core.daily_tier import series
        return series()
    except Exception:
        return {}


def align(all_series: dict, target: str) -> tuple[list[str], dict[str, list[float]]]:
    """Target's calendar; every series forward-filled onto it (None before its first value)."""
    tgt = sorted(all_series[target])
    dates = [d for d, _ in tgt]
    cols: dict[str, list[float]] = {}
    for name, pts in all_series.items():
        pts = sorted(pts)
        i, last, col = 0, None, []
        for d in dates:
            while i < len(pts) and pts[i][0] <= d:
                last = pts[i][1]; i += 1
            col.append(last)
        cols[name] = col
    return dates, cols


def diffs(col: list) -> list:
    return [None if (a is None or b is None) else b - a for a, b in zip(col[:-1], col[1:])]


# ── ridge, pure python ───────────────────────────────────────────────────────

def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def ridge_fit(X: list[list[float]], y: list[float], lam: float = LAMBDA) -> list[float]:
    """Weights (no intercept: features and target are standardized differences)."""
    if not X:
        return []
    p = len(X[0])
    A = [[sum(X[r][i] * X[r][j] for r in range(len(X))) + (lam if i == j else 0.0) for j in range(p)] for i in range(p)]
    b = [sum(X[r][i] * y[r] for r in range(len(X))) for i in range(p)]
    return _solve(A, b)


def _dot(w, x):
    return sum(a * b for a, b in zip(w, x))


# ── the walk ─────────────────────────────────────────────────────────────────

def _rows(cols: dict, names: list[str], target: str, horizon: int = 1):
    """Row t (0-based over diffs): features = lags 1..LAGS of every series' 1-day move (known at day t),
    y = the target's move over the next `horizon` days. Rows with any None are dropped.
    Returns (t_index, X_all, X_own, y, value_now, value_after_horizon)."""
    d = {n: diffs(cols[n]) for n in names}
    col = cols[target]
    out = []
    for t in range(LAGS, len(col) - horizon):
        feats_all, feats_own, ok = [], [], True
        for n in names:
            for k in range(1, LAGS + 1):
                v = d[n][t - k] if t - k < len(d[n]) else None
                if v is None:
                    ok = False; break
                feats_all.append(v)
                if n == target:
                    feats_own.append(v)
            if not ok:
                break
        if not ok or col[t] is None or col[t + horizon] is None:
            continue
        out.append((t, feats_all, feats_own, col[t + horizon] - col[t], col[t], col[t + horizon]))
    return out


def _std(xs: list[float]) -> float:
    return statistics.pstdev(xs) if len(xs) > 1 else 1.0


def walk(all_series: dict, target: str, k_limit: Optional[int] = None,
         transfer_from: Optional[list[float]] = None, extras: bool = True, horizon: int = 1) -> dict:
    """One target, walk-forward. k_limit: the model may fit on only the last k rows
    (learning curve). transfer_from: fixed weights for the all-lags ridge (transfer test)."""
    from world_forecast import fit_alpha, ewma
    dates, cols = align(all_series, target)
    names = sorted(all_series)
    rows = _rows(cols, names, target, horizon)
    if len(rows) < WARM + 5:
        return {"target": target, "n": len(rows), "error": f"fewer than {WARM + 5} usable rows"}
    err = {"persistence": [], "ewma": [], "ridge_own": [], "ridge_all": [], "ridge_concept": [], "transfer": []}
    n_pred = 0
    dd = {n: diffs(cols[n]) for n in names}          # E2: same-day moves, for grouping only (never a feature)
    others = [n for n in names if n != target]
    past_abs = {"ridge_all": [], "persistence": []}  # E4: errors already known before today's prediction
    cover = {"ridge_all": [], "persistence": []}
    width = {"ridge_all": [], "persistence": []}
    concept_last: dict = {}
    # DIRECTION FIRST, THEN THE SIZE OF THE STEP IN % (Emil, 11 Sep 2026: "asking a model to hit
    # an exact price is madness — first the direction, then the percent of the move").
    DIR_MODELS = ("ridge_all", "ridge_own", "ridge_concept", "ewma")
    dir_hits = {m: 0 for m in DIR_MODELS + ("always_up", "momentum", "train_majority")}
    dir_n = 0
    pct_past = {"ridge_all": [], "ewma": [], "persistence": []}
    pct_cover = {"ridge_all": [], "ewma": [], "persistence": []}
    pct_half = {"ridge_all": [], "ewma": [], "persistence": []}
    for i in range(WARM, len(rows)):
        train = rows[max(0, i - k_limit) if k_limit else 0:i]
        t, xa, xo, y, v0, v1 = rows[i]
        sd_y = _std([r[3] for r in train]) or 1.0
        sds_all = [(_std([r[1][j] for r in train]) or 1.0) for j in range(len(xa))]
        sds_own = [(_std([r[2][j] for r in train]) or 1.0) for j in range(len(xo))]
        Xa = [[r[1][j] / sds_all[j] for j in range(len(xa))] for r in train]
        Xo = [[r[2][j] / sds_own[j] for j in range(len(xo))] for r in train]
        Y = [r[3] / sd_y for r in train]
        w_all, w_own = ridge_fit(Xa, Y), ridge_fit(Xo, Y)
        xa_s = [xa[j] / sds_all[j] for j in range(len(xa))]
        xo_s = [xo[j] / sds_own[j] for j in range(len(xo))]
        pred = {"persistence": v0,
                "ridge_own": v0 + _dot(w_own, xo_s) * sd_y,
                "ridge_all": v0 + _dot(w_all, xa_s) * sd_y}
        hist = [cols[target][j] for j in range(t + 1) if cols[target][j] is not None]
        pred["ewma"] = ewma(hist, fit_alpha(hist)) if len(hist) >= 3 else v0
        if transfer_from is not None and len(transfer_from) == len(xa_s):
            pred["transfer"] = v0 + _dot(transfer_from, xa_s) * sd_y
        # ── E2: a CONCEPT = the other series whose same-day moves go with the target's,
        # found on the training window only; the feature is yesterday's signed mean of their
        # standardized moves. It "exists" only if it predicts better than the target's own past.
        members = _concept(dd, target, others, [r[0] for r in train]) if extras else {}
        if members:
            cf = [_concept_feature(dd, members, r[0]) for r in train]
            if all(v is not None for v in cf):
                sd_c = _std(cf) or 1.0
                Xc = [[r[2][j] / sds_own[j] for j in range(len(xo))] + [cf[k] / sd_c] for k, r in enumerate(train)]
                w_c = ridge_fit(Xc, Y)
                today = _concept_feature(dd, members, t)
                if today is not None:
                    pred["ridge_concept"] = v0 + _dot(w_c, xo_s + [today / sd_c]) * sd_y
            concept_last = members
        if "ridge_concept" not in pred:
            pred["ridge_concept"] = pred["ridge_own"]            # no concept: the model IS the own-lags model
        # ── E4: split-conformal interval from errors already seen (no look-ahead)
        for m in ("ridge_all", "persistence"):
            if len(past_abs[m]) >= CONFORMAL_MIN:
                q = _conformal_q(past_abs[m], CONFORMAL_LEVEL)
                cover[m].append(abs(pred[m] - v1) <= q)
                width[m].append(2 * q)
            past_abs[m].append(abs(pred[m] - v1))
        # ── direction: sign of the predicted move vs sign of the actual move (flat days skipped)
        actual = v1 - v0
        if actual != 0:
            dir_n += 1
            sa = 1 if actual > 0 else -1
            for m in DIR_MODELS:
                pm = pred[m] - v0
                if pm != 0 and (1 if pm > 0 else -1) == sa:
                    dir_hits[m] += 1
            dir_hits["always_up"] += 1 if sa > 0 else 0
            past = cols[target][t] - cols[target][t - horizon] if t - horizon >= 0 and cols[target][t - horizon] is not None else 0
            dir_hits["momentum"] += 1 if past != 0 and (1 if past > 0 else -1) == sa else 0
            mean_y = sum(r[3] for r in train) / len(train) if train else 0
            dir_hits["train_majority"] += 1 if mean_y != 0 and (1 if mean_y > 0 else -1) == sa else 0
        # ── the size of the step in percent of today's value, with an 80% conformal range
        if v0:
            for m in pct_past:
                e = abs((pred[m] - v1) / v0) * 100
                if len(pct_past[m]) >= CONFORMAL_MIN:
                    q = _conformal_q(pct_past[m], CONFORMAL_LEVEL)
                    pct_cover[m].append(e <= q)
                    pct_half[m].append(q)
                pct_past[m].append(e)
        for m, pv in pred.items():
            err[m].append(abs(pv - v1))
        n_pred += 1
    mae = {m: round(sum(e) / len(e), 6) for m, e in err.items() if e}
    closer = {m: sum(1 for a, b in zip(err[m], err["persistence"]) if a < b) for m in err if err[m] and m != "persistence"}
    # the last fitted all-lags weights, for the transfer test (standardized space)
    train = rows[:len(rows)]
    sds_all = [(_std([r[1][j] for r in train]) or 1.0) for j in range(len(train[0][1]))]
    sd_y = _std([r[3] for r in train]) or 1.0
    w_final = ridge_fit([[r[1][j] / sds_all[j] for j in range(len(r[1]))] for r in train], [r[3] / sd_y for r in train])
    conformal = {m: {"level": CONFORMAL_LEVEL, "n": len(cover[m]),
                     "coverage": round(sum(cover[m]) / len(cover[m]), 3) if cover[m] else None,
                     "mean_width": round(sum(width[m]) / len(width[m]), 6) if width[m] else None}
                 for m in cover}
    concept = {"members": {k: v for k, v in concept_last.items()},
               "name": "concept(" + target + ")=" + "{" + ", ".join(f"{'+' if v > 0 else '-'}{k}" for k, v in sorted(concept_last.items())) + "}"
               if concept_last else None,
               "survives": bool(concept_last) and mae.get("ridge_concept", 9e9) < mae.get("ridge_own", 0)}
    direction = _direction_verdict(dir_hits, dir_n, horizon, DIR_MODELS)
    pct = {m: {"level": CONFORMAL_LEVEL, "n": len(pct_cover[m]),
               "coverage": round(sum(pct_cover[m]) / len(pct_cover[m]), 3) if pct_cover[m] else None,
               "mean_half_width_pct": round(sum(pct_half[m]) / len(pct_half[m]), 3) if pct_half[m] else None,
               "mae_pct": round(sum(pct_past[m]) / len(pct_past[m]), 3) if pct_past[m] else None}
           for m in pct_past}
    return {"target": target, "horizon": horizon, "n": n_pred, "first": dates[LAGS + WARM], "last": dates[-1],
            "mae": mae, "closer_than_persistence": closer, "weights_all": w_final, "feature_names": names,
            "conformal": conformal, "concept": concept, "direction": direction, "pct_range": pct}


Z_WIN = 2.0          # a direction win must clear the best honest baseline by two standard errors


def _direction_verdict(hits: dict, n: int, horizon: int, models: tuple) -> dict:
    """Hit rates, the best baseline (always up / momentum / training majority), the best model,
    and z of (best model - best baseline) on the EFFECTIVE sample: overlapping H-day windows
    are not independent, so n_eff = n / horizon."""
    if not n:
        return {"n": 0}
    rate = {k: round(v / n, 4) for k, v in hits.items()}
    base = max(("always_up", "momentum", "train_majority"), key=lambda k: rate[k])
    best = max(models, key=lambda k: rate[k])
    n_eff = max(1.0, n / max(1, horizon))
    pb = min(max(rate[base], 1e-6), 1 - 1e-6)
    z = (rate[best] - rate[base]) / (pb * (1 - pb) / n_eff) ** 0.5
    return {"n": n, "n_eff": round(n_eff, 1), "rate": rate, "best_baseline": base, "best_model": best,
            "z": round(z, 2), "wins": z >= Z_WIN}


def _conformal_q(abs_errors: list[float], level: float) -> float:
    """Finite-sample split-conformal quantile: the ceil((n+1)·level)-th smallest past error."""
    import math
    s = sorted(abs_errors)
    k = min(len(s), max(1, math.ceil((len(s) + 1) * level)))
    return s[k - 1]


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 5:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5


def _concept(dd: dict, target: str, others: list[str], ts: list[int]) -> dict:
    """{member: sign} — series whose same-day moves correlate with the target's at |r| >= CONCEPT_CORR
    over the training days `ts`."""
    out = {}
    for o in others:
        pairs = [(dd[target][t], dd[o][t]) for t in ts if dd[target][t] is not None and dd[o][t] is not None]
        if len(pairs) < 10:
            continue
        r = _corr([a for a, _ in pairs], [b for _, b in pairs])
        if abs(r) >= CONCEPT_CORR:
            out[o] = 1 if r > 0 else -1
    return out


def _concept_feature(dd: dict, members: dict, t: int):
    """Yesterday's signed mean move of the concept's members (lag 1 — known before day t+1)."""
    vals = []
    for m, sign in members.items():
        v = dd[m][t - 1] if t - 1 >= 0 else None
        if v is None:
            return None
        vals.append(sign * v)
    return sum(vals) / len(vals) if vals else None


def bench(all_series: Optional[dict] = None) -> dict:
    all_series = load_tier() if all_series is None else all_series
    usable = {n: p for n, p in all_series.items() if len(p) >= MIN_POINTS}
    out = {"ts": datetime.now(timezone.utc).isoformat()[:19] + "Z", "series": len(all_series),
           "usable": sorted(usable), "lags": LAGS, "lambda": LAMBDA, "targets": {}, "learning_curve": {}, "transfer": {}}
    if len(usable) < 2:
        out["error"] = f"need >= 2 series with >= {MIN_POINTS} points; have {len(usable)}"
        return out
    base = {}
    for tgt in sorted(usable):
        r = walk(usable, tgt)
        base[tgt] = r
        out["targets"][tgt] = {k: v for k, v in r.items() if k not in ("weights_all", "feature_names")}
        if "error" in r:
            continue
        out["learning_curve"][tgt] = {}
        for k in KS:
            rk = walk(usable, tgt, k_limit=k, extras=False)
            if "error" not in rk:
                out["learning_curve"][tgt][str(k)] = {"ridge_all": rk["mae"]["ridge_all"], "persistence": rk["mae"]["persistence"],
                                                      "beats": rk["mae"]["ridge_all"] < rk["mae"]["persistence"]}
    # direction at 1, 5 and 20 days (the day, the week, the month): H=1 is the base walk above
    out["direction"] = {}
    for tgt, r in base.items():
        if "error" in r:
            continue
        out["direction"][tgt] = {"1": {**r["direction"], "pct_range": r["pct_range"]}}
        for h in HORIZONS[1:]:
            rh = walk(usable, tgt, extras=False, horizon=h)
            if "error" not in rh:
                out["direction"][tgt][str(h)] = {**rh["direction"], "pct_range": rh["pct_range"]}
    # transfer: weights fitted on A, judged on B
    for a, ra in base.items():
        if "error" in ra:
            continue
        for b, rb in base.items():
            if a == b or "error" in rb:
                continue
            rt = walk(usable, b, transfer_from=ra["weights_all"], extras=False)
            if "error" not in rt and "transfer" in rt["mae"]:
                out["transfer"][f"{a} -> {b}"] = {"transfer_mae": rt["mae"]["transfer"], "persistence_mae": rt["mae"]["persistence"],
                                                  "beats": rt["mae"]["transfer"] < rt["mae"]["persistence"]}
    ok = [t for t, r in out["targets"].items() if "error" not in r]
    out["verdict"] = {
        "targets": len(ok),
        "ridge_all_beats_persistence": sum(1 for t in ok if out["targets"][t]["mae"]["ridge_all"] < out["targets"][t]["mae"]["persistence"]),
        "ridge_all_beats_ridge_own": sum(1 for t in ok if out["targets"][t]["mae"]["ridge_all"] < out["targets"][t]["mae"]["ridge_own"]),
        "ewma_beats_persistence": sum(1 for t in ok if out["targets"][t]["mae"]["ewma"] < out["targets"][t]["mae"]["persistence"]),
        "transfer_pairs": len(out["transfer"]),
        "transfer_beats_persistence": sum(1 for v in out["transfer"].values() if v["beats"]),
        "few_examples": {str(k): sum(1 for t in ok if out["learning_curve"].get(t, {}).get(str(k), {}).get("beats")) for k in KS},
        "concepts_found": sum(1 for t in ok if (out["targets"][t].get("concept") or {}).get("name")),
        "concepts_survive": sum(1 for t in ok if (out["targets"][t].get("concept") or {}).get("survives")),
        "conformal_coverage": _mean([out["targets"][t]["conformal"]["ridge_all"]["coverage"] for t in ok
                                     if (out["targets"][t].get("conformal") or {}).get("ridge_all", {}).get("coverage") is not None]),
        "conformal_level": CONFORMAL_LEVEL,
        "direction_cells": sum(len(v) for v in out["direction"].values()),
        "direction_wins": sorted(f"{t}@{h}d" for t, hs in out["direction"].items() for h, d in hs.items() if d.get("wins")),
        "stage": ("2 — direction learned somewhere; the size of the step in % is now the headline"
                  if any(d.get("wins") for hs in out["direction"].values() for d in hs.values())
                  else "1 — learning the direction; no model beats an honest baseline by 2 SE yet"),
    }
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def markdown(b: dict) -> str:
    L = ["# CROSS-SERIES BENCH — direction first, then the % step, then (last) the level", "",
         f"_{b['ts']} · {b['series']} daily series, {len(b['usable'])} usable (>= {MIN_POINTS} points) · lags {b['lags']} · ridge λ={b['lambda']}_", ""]
    if b.get("error"):
        L += [f"**{b['error']}**", ""]
        return "\n".join(L)
    L += ["| target | n | persistence | EWMA | ridge own lags | ridge ALL lags | all closer than persistence |", "|---|---:|---:|---:|---:|---:|---:|"]
    for t, r in b["targets"].items():
        if "error" in r:
            L.append(f"| {t} | {r['n']} | — | — | — | — | {r['error']} |"); continue
        m = r["mae"]
        L.append(f"| {t} | {r['n']} | {m['persistence']} | {m['ewma']} | {m['ridge_own']} | {m['ridge_all']} | {r['closer_than_persistence'].get('ridge_all')}/{r['n']} |")
    L += ["", "## Few examples — rows the model may see (MAE ridge ALL vs persistence)", "",
          "| target | " + " | ".join(f"k={k}" for k in KS) + " |", "|---|" + "---:|" * len(KS)]
    for t, lc in b["learning_curve"].items():
        L.append(f"| {t} | " + " | ".join(
            (f"{lc[str(k)]['ridge_all']} {'✓' if lc[str(k)]['beats'] else '✗'}" if str(k) in lc else "—") for k in KS) + " |")
    L += ["", "## Transfer — weights fitted on A, judged on B against persistence", "", "| A -> B | transfer MAE | persistence MAE | beats |", "|---|---:|---:|---|"]
    for pair, v in b["transfer"].items():
        L.append(f"| {pair} | {v['transfer_mae']} | {v['persistence_mae']} | {'YES' if v['beats'] else 'no'} |")
    L += ["", "## STAGE 1 — direction (up/down), against honest baselines", "",
          "Baselines: always up (markets drift up), momentum (same sign as the last H days), training majority. "
          f"A win = best model beats the best baseline by >= {Z_WIN} standard errors on n_eff = n / H.", "",
          "| target | H days | n (eff) | best model hit rate | best baseline hit rate | z | win |", "|---|---:|---:|---:|---:|---:|---|"]
    for t, hs in b.get("direction", {}).items():
        for h, d in sorted(hs.items(), key=lambda kv: int(kv[0])):
            if not d.get("n"):
                continue
            L.append(f"| {t} | {h} | {d['n']} ({d['n_eff']}) | {d['best_model']} {d['rate'][d['best_model']]} | "
                     f"{d['best_baseline']} {d['rate'][d['best_baseline']]} | {d['z']} | {'YES' if d['wins'] else 'no'} |")
    L += ["", "## STAGE 2 — the size of the step in % of today's value (80% conformal range)", "",
          "| target | H days | ridge ALL: mean error % | range ±% | covered | EWMA: error % | range ±% | covered |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for t, hs in b.get("direction", {}).items():
        for h, d in sorted(hs.items(), key=lambda kv: int(kv[0])):
            pr = d.get("pct_range") or {}
            a, e = pr.get("ridge_all", {}), pr.get("ewma", {})
            L.append(f"| {t} | {h} | {a.get('mae_pct')} | {a.get('mean_half_width_pct')} | {a.get('coverage')} | "
                     f"{e.get('mae_pct')} | {e.get('mean_half_width_pct')} | {e.get('coverage')} |")
    L += ["", "## E2 — concepts: series that move together, used as one feature (point 4)", "",
          "| target | concept (found on the training window, named by its members) | own-lags MAE | concept MAE | survives |", "|---|---|---:|---:|---|"]
    for t, r in b["targets"].items():
        if "error" in r:
            continue
        c = r.get("concept") or {}
        L.append(f"| {t} | {c.get('name') or '— no series moves with it'} | {r['mae'].get('ridge_own')} | {r['mae'].get('ridge_concept')} | "
                 f"{'YES' if c.get('survives') else 'no'} |")
    L += ["", f"## E4 — calibrated uncertainty: {int(CONFORMAL_LEVEL * 100)}% intervals, judged against what happened (point 7)", "",
          "| target | ridge ALL coverage | width | persistence coverage | width |", "|---|---:|---:|---:|---:|"]
    for t, r in b["targets"].items():
        if "error" in r:
            continue
        cf = r.get("conformal") or {}
        a, p_ = cf.get("ridge_all", {}), cf.get("persistence", {})
        L.append(f"| {t} | {a.get('coverage')} (n={a.get('n')}) | {a.get('mean_width')} | {p_.get('coverage')} | {p_.get('mean_width')} |")
    v = b["verdict"]
    L += ["", f"**Stage:** {v['stage']}. Direction wins: {', '.join(v['direction_wins']) or 'none'} "
          f"(of {v['direction_cells']} target×horizon cells).", "",
          "The exact price is NOT the goal; it stays as the third, hardest table below only so that a model which "
          "is right about direction and wrong about size is not mistaken for one that is wrong about everything."]
    L += ["", f"**Verdict:** ridge on ALL lags beats persistence on {v['ridge_all_beats_persistence']}/{v['targets']} targets and beats its own-lags twin on "
          f"{v['ridge_all_beats_ridge_own']}/{v['targets']}; EWMA beats persistence on {v['ewma_beats_persistence']}/{v['targets']}; "
          f"transfer beats persistence on {v['transfer_beats_persistence']}/{v['transfer_pairs']} pairs; "
          f"few-examples wins: " + ", ".join(f"k={k}: {v['few_examples'][str(k)]}/{v['targets']}" for k in KS) + "; "
          f"concepts found {v['concepts_found']}, surviving out of sample {v['concepts_survive']}; "
          f"{int(v['conformal_level'] * 100)}% intervals covered {v['conformal_coverage']} of outcomes.", "",
          "Reading: on daily market closes persistence is a hard baseline (a random walk has no better one-step predictor); a win here must hold for weeks, "
          "not one run. USGS counts are not a random walk and are where a lag model should win first. Nothing here is a trade.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    b = bench()
    md = markdown(b)
    if "--write" in sys.argv:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(md, encoding="utf-8")
        REPORT_JSON.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {REPORT}")
    print(md)
    sys.exit(2 if b.get("error") else 0)
