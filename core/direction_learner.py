# -*- coding: utf-8 -*-
"""
core/direction_learner.py — A LEARNER THAT LEARNS DIRECTION, SAYS WHEN IT IS NOT SURE,
AND CAN BE TAUGHT NEW THINGS TO LOOK AT BY THE BRAIN (11 Sep 2026, E3, Emil).

Three corrections Emil made today, each one a design rule here:
  1. "Asking a model to hit an exact price is madness" -> it learns DIRECTION directly
     (logistic regression on up/down), not the size of the move.
  2. "Not 'I don't know' — UNCONFIDENT_TO_CHOOSE" -> it outputs P(up). Near 0.5 it abstains.
     The width of the abstention band is LEARNED from its own past out-of-sample record,
     not set by us.
  3. "Who chooses, and why?" -> every decision carries its reasons: the inputs that pushed
     it (weight x standardized value), largest first.
And the question behind all three — "is it the brain, or mechanics?" — is answered by the
division of labour in core/feature_proposals.py: the BRAIN chooses what to look at (it
proposes inputs); the learner fits how much each matters; the EXAM decides whether the
brain's proposal made the predictions better on days the learner had not seen.

Inputs are named features computed from the daily tier, only from data up to day t:
  own_lag1..3          the target's last three daily moves
  ret_W                % change over the last W days            (W in 2..60)
  vol_W                std of daily moves over the last W days  (W in 2..60)
  zdev_W               distance from the W-day mean, in stds    (W in 2..60)
  dow                  day of week (as two numbers: sin, cos)
  x_move:<series>      another series' last daily move
  x_ret_W:<series>     another series' % change over W days
Anything outside this grammar is refused by name (FEATURE_GRAMMAR).

Walk-forward: at day t the model has seen only days < t; it is refitted every REFIT days.
Nothing here trades, sizes or recommends anything (spec §VI).
"""
from __future__ import annotations

import math
import re
import statistics
from datetime import date
from typing import Optional

WARM = 60                 # first prediction after this many labelled days
REFIT = 5                 # refit the weights every REFIT days (cost; the decision is still daily)
L2 = 1.0                  # ridge penalty on standardized weights
BANDS = [i / 100 for i in range(0, 21, 2)]   # candidate half-widths of the abstention band
MIN_COMMIT_SHARE = 0.4    # the learned band may not abstain on more than 60% of days
MIN_BAND_HISTORY = 30     # past out-of-sample predictions needed before a band is learned
BASE_FEATURES = ("own_lag1", "own_lag2", "own_lag3")
UNCONFIDENT = "UNCONFIDENT_TO_CHOOSE"

FEATURE_GRAMMAR = re.compile(
    r"^(own_lag[123]|dow|(ret|vol|zdev)_([2-9]|[1-5][0-9]|60)|x_move:[\w.\-]+|x_ret_([2-9]|[1-5][0-9]|60):[\w.\-]+)$")


def valid_feature(name: str, series_names=None) -> tuple[bool, str]:
    if not isinstance(name, str) or not FEATURE_GRAMMAR.match(name):
        return False, "not in the feature grammar"
    if ":" in name and series_names is not None and name.split(":", 1)[1] not in series_names:
        return False, f"unknown series {name.split(':', 1)[1]!r}"
    return True, ""


# ── features (only data up to day t) ─────────────────────────────────────────

def _moves(col):
    return [None if (a is None or b is None) else b - a for a, b in zip(col[:-1], col[1:])]


def feature_values(name: str, t: int, cols: dict, target: str, dates: list, moves: dict) -> Optional[list]:
    """The value(s) of feature `name` at day t, or None if not computable. Uses indices <= t."""
    col = cols[target]
    try:
        if name.startswith("own_lag"):
            k = int(name[-1])
            v = moves[target][t - k] if t - k >= 0 else None
            return None if v is None else [v]
        if name == "dow":
            wd = date.fromisoformat(dates[t][:10]).weekday()
            return [math.sin(2 * math.pi * wd / 7), math.cos(2 * math.pi * wd / 7)]
        if name.startswith("x_move:"):
            s = name.split(":", 1)[1]
            v = moves[s][t - 1] if t - 1 >= 0 else None
            return None if v is None else [v]
        if name.startswith("x_ret_"):
            w, s = name[len("x_ret_"):].split(":", 1)
            c = cols[s]
            w = int(w)
            if t - w < 0 or c[t] is None or not c[t - w]:
                return None
            return [(c[t] - c[t - w]) / abs(c[t - w])]
        kind, w = name.split("_")
        w = int(w)
        if t - w < 0:
            return None
        if kind == "ret":
            if col[t] is None or not col[t - w]:
                return None
            return [(col[t] - col[t - w]) / abs(col[t - w])]
        if kind == "vol":
            m = [x for x in moves[target][t - w:t] if x is not None]
            return [statistics.pstdev(m)] if len(m) >= 2 else None
        if kind == "zdev":
            win = [x for x in col[t - w + 1:t + 1] if x is not None]
            if len(win) < 2 or col[t] is None:
                return None
            sd = statistics.pstdev(win)
            return [(col[t] - statistics.mean(win)) / sd] if sd else [0.0]
    except (KeyError, ValueError, IndexError, TypeError):
        return None
    return None


def design(features: list, cols: dict, target: str, dates: list, horizon: int):
    """Rows (t, x, label) with label = 1 if value(t+H) > value(t), 0 if lower; flat days skipped."""
    moves = {n: _moves(c) for n, c in cols.items()}
    col = cols[target]
    rows = []
    for t in range(3, len(col) - horizon):
        if col[t] is None or col[t + horizon] is None or col[t + horizon] == col[t]:
            continue
        x = []
        ok = True
        for f in features:
            v = feature_values(f, t, cols, target, dates, moves)
            if v is None:
                ok = False
                break
            x.extend(v)
        if ok:
            rows.append((t, x, 1 if col[t + horizon] > col[t] else 0))
    return rows


# ── logistic regression, pure python ─────────────────────────────────────────

def _sig(z):
    return 1 / (1 + math.exp(-max(-35.0, min(35.0, z))))


def _solve(A, b):
    n = len(A)
    M = [A[i][:] + [b[i]] for i in range(n)]
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


def fit(X: list, y: list, l2: float = L2, iters: int = 12) -> tuple[list, list, list]:
    """Newton-Raphson logistic regression with an intercept and L2 on standardized inputs.
    Returns (weights incl. intercept first, means, stds)."""
    p = len(X[0])
    mu = [statistics.mean(r[j] for r in X) for j in range(p)]
    sd = [statistics.pstdev([r[j] for r in X]) or 1.0 for j in range(p)]
    Z = [[1.0] + [(r[j] - mu[j]) / sd[j] for j in range(p)] for r in X]
    w = [0.0] * (p + 1)
    for _ in range(iters):
        g = [0.0] * (p + 1)
        H = [[0.0] * (p + 1) for _ in range(p + 1)]
        for zi, yi in zip(Z, y):
            pi = _sig(sum(a * b for a, b in zip(w, zi)))
            r = pi - yi
            s = pi * (1 - pi)
            for a in range(p + 1):
                g[a] += r * zi[a]
                za = s * zi[a]
                for b in range(a, p + 1):
                    H[a][b] += za * zi[b]
        for a in range(p + 1):
            for b in range(a):
                H[a][b] = H[b][a]
            if a:                               # no penalty on the intercept
                g[a] += l2 * w[a]
                H[a][a] += l2
        step = _solve(H, g)
        w = [wi - si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return w, mu, sd


def predict(w, mu, sd, x) -> tuple[float, list]:
    """P(up) and the contributions (weight x standardized value) per input column."""
    z = [(x[j] - mu[j]) / sd[j] for j in range(len(x))]
    contrib = [w[j + 1] * z[j] for j in range(len(z))]
    return _sig(w[0] + sum(contrib)), contrib


def learn_band(history: list) -> float:
    """history: [(p_up, label)] of PAST out-of-sample predictions. The half-width b that
    maximizes accuracy on committed days, committing on at least MIN_COMMIT_SHARE of days.
    Ties go to the narrower band. Fewer than MIN_BAND_HISTORY: no abstention yet."""
    if len(history) < MIN_BAND_HISTORY:
        return 0.0
    best, best_acc = 0.0, -1.0
    for b in BANDS:
        committed = [(p, y) for p, y in history if abs(p - 0.5) > b]
        if len(committed) < MIN_COMMIT_SHARE * len(history):
            break
        acc = sum(1 for p, y in committed if (p > 0.5) == (y == 1)) / len(committed)
        if acc > best_acc + 1e-9:
            best, best_acc = b, acc
    return best


# ── the walk ─────────────────────────────────────────────────────────────────

def _column_names(features, series_names):
    out = []
    for f in features:
        out.extend([f + ":sin", f + ":cos"] if f == "dow" else [f])
    return out


def walk(all_series: dict, target: str, features: list, horizon: int = 1) -> dict:
    """Walk-forward direction learner. Returns per-day records and summary metrics."""
    import sys
    from pathlib import Path
    here = Path(__file__).resolve().parents[1] / "experiments" / "prophecy"
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from cross_series_bench import align
    dates, cols = align(all_series, target)
    rows = design(list(features), cols, target, dates, horizon)
    names = _column_names(features, list(cols))
    if len(rows) < WARM + 20:
        return {"target": target, "horizon": horizon, "features": list(features), "n": 0,
                "error": f"only {len(rows)} labelled days; {WARM + 20} needed"}
    recs, hist = [], []
    w = mu = sd = None
    band = 0.0
    for i in range(WARM, len(rows)):
        if w is None or (i - WARM) % REFIT == 0:
            train = rows[:i]
            if len({r[2] for r in train}) < 2:
                continue
            w, mu, sd = fit([r[1] for r in train], [r[2] for r in train])
            band = learn_band(hist)
        t, x, y = rows[i]
        p, contrib = predict(w, mu, sd, x)
        decision = UNCONFIDENT if abs(p - 0.5) <= band else ("UP" if p > 0.5 else "DOWN")
        top = sorted(zip(names, contrib), key=lambda kv: -abs(kv[1]))[:3]
        recs.append({"date": dates[t], "p_up": round(p, 4), "band": band, "decision": decision,
                     "actual": "UP" if y else "DOWN", "why": [(n, round(c, 3)) for n, c in top]})
        hist.append((p, y))
    return {"target": target, "horizon": horizon, "features": list(features),
            "weights": {n: round(v, 4) for n, v in zip(["intercept"] + names, w or [])},
            **summary(recs, horizon), "last": recs[-1] if recs else None, "records": recs}


def summary(recs: list, horizon: int = 1) -> dict:
    n = len(recs)
    if not n:
        return {"n": 0}
    forced = sum(1 for r in recs if (r["p_up"] > 0.5) == (r["actual"] == "UP")) / n
    committed = [r for r in recs if r["decision"] != UNCONFIDENT]
    conf_acc = (sum(1 for r in committed if r["decision"] == r["actual"]) / len(committed)) if committed else None
    ups = sum(1 for r in recs if r["actual"] == "UP") / n
    always_up = ups
    base = max(always_up, 1 - always_up)            # the better of "always up" / "always down" in hindsight
    logloss = -sum(math.log(max(1e-9, r["p_up"] if r["actual"] == "UP" else 1 - r["p_up"])) for r in recs) / n
    n_eff = max(1.0, n / max(1, horizon))
    z = (forced - base) / math.sqrt(base * (1 - base) / n_eff) if 0 < base < 1 else 0.0
    return {"n": n, "n_eff": round(n_eff, 1), "accuracy_forced": round(forced, 4),
            "committed_share": round(len(committed) / n, 3), "accuracy_when_confident":
            round(conf_acc, 4) if conf_acc is not None else None, "baseline_hindsight_majority": round(base, 4),
            "z_vs_baseline": round(z, 2), "logloss": round(logloss, 4),
            "calibration": _calibration(recs)}


def _calibration(recs: list) -> list:
    """When it says 60-70% up, is it up 60-70% of the time? Bins of P(up)."""
    bins = {}
    for r in recs:
        k = min(9, int(r["p_up"] * 10))
        bins.setdefault(k, []).append(1 if r["actual"] == "UP" else 0)
    return [{"p_up": f"{k / 10:.1f}-{(k + 1) / 10:.1f}", "n": len(v), "observed_up": round(sum(v) / len(v), 3)}
            for k, v in sorted(bins.items())]
