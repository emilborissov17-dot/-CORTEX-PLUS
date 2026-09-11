#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/prophecy/cross_series_bench.py — E1: DOES KNOWING THE OTHERS HELP?
(11 Sep 2026. Emil: "search for a solution for AGI in parallel — experiment".)

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

def _rows(cols: dict, names: list[str], target: str):
    """Row t (0-based over diffs): features = lags 1..LAGS of every series' diff, y = target diff at t.
    Rows with any None are dropped. Returns (t_index, X_all, X_own, y, value_before, value_after)."""
    d = {n: diffs(cols[n]) for n in names}
    T = len(d[target])
    out = []
    for t in range(LAGS, T):
        feats_all, feats_own, ok = [], [], True
        for n in names:
            for k in range(1, LAGS + 1):
                v = d[n][t - k]
                if v is None:
                    ok = False; break
                feats_all.append(v)
                if n == target:
                    feats_own.append(v)
            if not ok:
                break
        y = d[target][t]
        if not ok or y is None:
            continue
        out.append((t, feats_all, feats_own, y, cols[target][t], cols[target][t + 1]))
    return out


def _std(xs: list[float]) -> float:
    return statistics.pstdev(xs) if len(xs) > 1 else 1.0


def walk(all_series: dict, target: str, k_limit: Optional[int] = None,
         transfer_from: Optional[list[float]] = None) -> dict:
    """One target, walk-forward. k_limit: the model may fit on only the last k rows
    (learning curve). transfer_from: fixed weights for the all-lags ridge (transfer test)."""
    from world_forecast import fit_alpha, ewma
    dates, cols = align(all_series, target)
    names = sorted(all_series)
    rows = _rows(cols, names, target)
    if len(rows) < WARM + 5:
        return {"target": target, "n": len(rows), "error": f"fewer than {WARM + 5} usable rows"}
    err = {"persistence": [], "ewma": [], "ridge_own": [], "ridge_all": [], "transfer": []}
    n_pred = 0
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
    return {"target": target, "n": n_pred, "first": dates[LAGS + WARM], "last": dates[-1],
            "mae": mae, "closer_than_persistence": closer, "weights_all": w_final, "feature_names": names}


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
            rk = walk(usable, tgt, k_limit=k)
            if "error" not in rk:
                out["learning_curve"][tgt][str(k)] = {"ridge_all": rk["mae"]["ridge_all"], "persistence": rk["mae"]["persistence"],
                                                      "beats": rk["mae"]["ridge_all"] < rk["mae"]["persistence"]}
    # transfer: weights fitted on A, judged on B
    for a, ra in base.items():
        if "error" in ra:
            continue
        for b, rb in base.items():
            if a == b or "error" in rb:
                continue
            rt = walk(usable, b, transfer_from=ra["weights_all"])
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
    }
    return out


def markdown(b: dict) -> str:
    L = ["# CROSS-SERIES BENCH — does knowing the others help? (E1, points 1 and 3 on the moving world)", "",
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
    v = b["verdict"]
    L += ["", f"**Verdict:** ridge on ALL lags beats persistence on {v['ridge_all_beats_persistence']}/{v['targets']} targets and beats its own-lags twin on "
          f"{v['ridge_all_beats_ridge_own']}/{v['targets']}; EWMA beats persistence on {v['ewma_beats_persistence']}/{v['targets']}; "
          f"transfer beats persistence on {v['transfer_beats_persistence']}/{v['transfer_pairs']} pairs; "
          f"few-examples wins: " + ", ".join(f"k={k}: {v['few_examples'][str(k)]}/{v['targets']}" for k in KS) + ".", "",
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
