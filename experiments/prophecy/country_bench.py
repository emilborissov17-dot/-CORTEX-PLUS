#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/prophecy/country_bench.py — LEARNING FROM A WORLD THAT DOES NOT MOVE.
(10 September 2026. Emil: "МОДЕЛЪТ МОЖЕ ДА СЕ УЧИ И ОТ НЕДВИЖЕЩ СЕ СВЯТ ...
ОТ КОНСТАНТНА НЕПРОМЕНЛИВА РЕАЛНОСТ (ЗНАЕЙКИ ПРИЧИНАТА)".)

He is right, and the morning's diagnosis was too narrow. Time is one axis of
variance. The other is SPACE: 179 countries that differ from each other today.
A world model that knows WHY institutions, wealth and energy hang together can
be tested without waiting a single night — hide a country, predict it from the
others, check. That is transfer (point 1) and world model (point 10) on data
the system ALREADY HOLDS: data/vdem_cache/vdem_lookup.json (V-Dem, 179
countries) and data/energy/owid-energy-data.csv (OWID, per country-year).

THE TEST
  target   : a V-Dem index for a country the learner never saw
             (v2x_rule = rule of law, v2x_corr_inv = 1 - corruption,
              v2x_freexp_altinf = free expression)
  features : what the ENERGY dataset knows about the same country —
             log energy per capita, log GDP per capita, renewables share,
             electricity per capita (latest year with data)
  learners : (a) k-nearest countries in feature space, k=5
             (b) ridge regression (closed form, no library)
  baseline : the mean of the training countries (knows nothing about X)
  protocol : leave-one-country-out. Every country is predicted by a model
             that never saw it. MAE per learner vs baseline, and the share
             of countries where the learner is closer than the baseline.

  A "knowing the cause" check on top: does a ONE-feature model (energy per
  capita alone) already beat the baseline on unseen countries? If yes, the
  single strongest cause carries transferable knowledge on its own.

No LLM, no neural weights, no time series. If this does not beat the mean,
nothing more expensive deserves to be tried on this data.

Usage:
  venv\\Scripts\\python.exe experiments/prophecy/country_bench.py            # print
  venv\\Scripts\\python.exe experiments/prophecy/country_bench.py --write    # + claude/reports/COUNTRY_BENCH.md
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
VDEM = REPO / "data" / "vdem_cache" / "vdem_lookup.json"
OWID = REPO / "data" / "energy" / "owid-energy-data.csv"
REPORT = REPO / "claude" / "reports" / "COUNTRY_BENCH.md"

FEATURES = ["log_energy_per_capita", "log_gdp_per_capita", "renewables_share_energy", "log_elec_per_capita"]
TARGETS = ["v2x_rule", "v2x_corr_inv", "v2x_freexp_altinf"]
K = 5
RIDGE_LAMBDA = 1.0


# ── data ─────────────────────────────────────────────────────────────────────

def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def load_table(vdem_path: Path = VDEM, owid_path: Path = OWID, max_year: int = 2023) -> list[dict]:
    """One row per ISO3 that exists in BOTH datasets with all features present.
    OWID: latest year <= max_year where the needed columns are populated."""
    vdem = json.loads(vdem_path.read_text(encoding="utf-8"))
    latest: dict = {}
    with owid_path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            iso = r.get("iso_code") or ""
            if not iso or iso.startswith("OWID") or iso not in vdem:
                continue
            y = int(r["year"]) if r.get("year", "").isdigit() else 0
            if y > max_year:
                continue
            pop, gdp = _f(r.get("population")), _f(r.get("gdp"))
            epc, ren = _f(r.get("energy_per_capita")), _f(r.get("renewables_share_energy"))
            elec = _f(r.get("electricity_generation"))
            if not (pop and pop > 0 and gdp and gdp > 0 and epc and epc > 0 and ren is not None and elec and elec > 0):
                continue
            row = {"iso": iso, "year": y,
                   "log_energy_per_capita": math.log(epc),
                   "log_gdp_per_capita": math.log(gdp / pop),
                   "renewables_share_energy": ren,
                   "log_elec_per_capita": math.log(elec * 1e9 / pop)}   # TWh -> kWh per person
            for t in TARGETS:
                row[t] = _f(vdem[iso].get(t))
            if all(row[t] is not None for t in TARGETS):
                if iso not in latest or y > latest[iso]["year"]:
                    latest[iso] = row
    return sorted(latest.values(), key=lambda r: r["iso"])


# ── learners (pure) ──────────────────────────────────────────────────────────

def _standardise(train: list[dict], feats: list[str]):
    mu = {f: statistics.mean(r[f] for r in train) for f in feats}
    sd = {f: (statistics.pstdev(r[f] for r in train) or 1.0) for f in feats}
    return lambda r: [(r[f] - mu[f]) / sd[f] for f in feats]


def knn_predict(train: list[dict], x: dict, target: str, feats: list[str], k: int = K) -> float:
    z = _standardise(train, feats)
    zx = z(x)
    d = sorted(((sum((a - b) ** 2 for a, b in zip(z(r), zx)), r[target]) for r in train), key=lambda t: t[0])
    return statistics.mean(v for _, v in d[:k])


def ridge_predict(train: list[dict], x: dict, target: str, feats: list[str], lam: float = RIDGE_LAMBDA) -> float:
    """Closed-form ridge on standardised features with intercept; tiny Gauss-Jordan solve."""
    z = _standardise(train, feats)
    X = [[1.0] + z(r) for r in train]
    y = [r[target] for r in train]
    p = len(feats) + 1
    A = [[sum(X[n][i] * X[n][j] for n in range(len(X))) + (lam if (i == j and i > 0) else 0.0) for j in range(p)] for i in range(p)]
    b = [sum(X[n][i] * y[n] for n in range(len(X))) for i in range(p)]
    # solve A w = b
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(p):
        piv = max(range(c, p), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(p):
            if r != c:
                f = M[r][c] / M[c][c]
                M[r] = [a - f * bb for a, bb in zip(M[r], M[c])]
    w = [M[i][p] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(p)]
    xz = [1.0] + z(x)
    return sum(wi * xi for wi, xi in zip(w, xz))


def mean_predict(train: list[dict], x: dict, target: str, feats: list[str]) -> float:
    return statistics.mean(r[target] for r in train)


# ── the bench ────────────────────────────────────────────────────────────────

def loo(table: list[dict], target: str, feats: list[str], fn) -> list[float]:
    errs = []
    for i, x in enumerate(table):
        train = table[:i] + table[i + 1:]
        errs.append(abs(fn(train, x, target, feats) - x[target]))
    return errs


def bench(table: list[dict] | None = None) -> dict:
    table = load_table() if table is None else table
    out = {"countries": len(table), "features": FEATURES, "targets": {}}
    for t in TARGETS:
        base = loo(table, t, FEATURES, mean_predict)
        knn = loo(table, t, FEATURES, knn_predict)
        rdg = loo(table, t, FEATURES, ridge_predict)
        one = loo(table, t, ["log_energy_per_capita"], ridge_predict)
        def summ(e):
            return {"mae": round(statistics.mean(e), 4),
                    "closer_than_baseline": sum(1 for a, b in zip(e, base) if a < b)}
        out["targets"][t] = {
            "baseline_mean": {"mae": round(statistics.mean(base), 4)},
            "knn_k5": summ(knn), "ridge_4_features": summ(rdg),
            "ridge_energy_only": summ(one),
            "n": len(table),
        }
    return out


def to_markdown(b: dict) -> str:
    L = ["# COUNTRY BENCH — learning from a world that does not move",
         "", f"{b['countries']} countries present in BOTH V-Dem (data/vdem_cache) and OWID energy (data/energy),",
         "features from the energy dataset only: " + ", ".join(b["features"]) + ".",
         "Leave-one-country-out: every number below is a prediction for a country the model never saw.",
         "MAE on a 0–1 index; lower is better. `closer` = countries where the learner beat the mean baseline.", "",
         "| target | baseline (mean) | kNN k=5 | ridge, 4 features | ridge, energy only | n |",
         "|---|---:|---:|---:|---:|---:|"]
    for t, r in b["targets"].items():
        L.append(f"| {t} | {r['baseline_mean']['mae']} | {r['knn_k5']['mae']} ({r['knn_k5']['closer_than_baseline']} closer) | "
                 f"{r['ridge_4_features']['mae']} ({r['ridge_4_features']['closer_than_baseline']} closer) | "
                 f"{r['ridge_energy_only']['mae']} ({r['ridge_energy_only']['closer_than_baseline']} closer) | {r['n']} |")
    L += ["", "Reading: if a learner's MAE is below the baseline and `closer` is well above n/2, knowledge about",
          "how wealth and energy relate to institutions TRANSFERS to countries it never saw — point 1 on",
          "data that never changed. The energy-only column is the 'knowing one cause' test.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    b = bench()
    md = to_markdown(b)
    if "--write" in sys.argv:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(md, encoding="utf-8")
        print(f"wrote {REPORT}")
    print(md)
