# -*- coding: utf-8 -*-
"""
core/axis_backfill.py — THE YEARS BEHIND EVERY AXIS (11 Sep 2026, Emil).

"Why is the historical record for these axes not taken into account — the years
back, from the oldest date to the last — to form the base and the trend, the
development of each?"

Until now memory/axis_history.json held only what the nightly cycle wrote since
March 2026: ~180 days of an annual number copied every night. No base, no trend,
and constancy() could not classify 15 of 16 axes ("history shorter than the
400-day window"). This module fetches the FULL annual series behind each
measurable axis, from the source's first year to its last, and stores it in

    memory/axis_history_annual.json     {axis: [{date, year, metrics, source, fetched}]}

A SEPARATE file, on purpose: memory/axis_history.json feeds world_forecast's
learner, and Emil's rule is that annual numbers are not training material — the
daily tier is. The annual base is for judgement (alarm_bands.constancy: base,
trend, stagnation) and for the brain's briefing, not for the learner.

Sources:
  * World Bank API, country WLD, every year with a value  (12 metrics)
  * NOAA GML Mauna Loa annual mean CO2                     (1 metric)
Idempotent: a (axis, year) already on file is not rewritten unless the value changed.

Usage:
  venv\\Scripts\\python.exe core\\axis_backfill.py           # fetch + merge, print per-axis years
  venv\\Scripts\\python.exe core\\axis_backfill.py --dry     # fetch, print, write nothing
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ANNUAL = BASE / "memory" / "axis_history_annual.json"
TARGETS = BASE / "config" / "target_config.json"

WB_URL = "https://api.worldbank.org/v2/country/WLD/indicator/{code}?format=json&per_page=200"
NOAA_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.txt"

# metric name (target_config.primary_metric) -> World Bank code. Mirrors obs_map in
# goal_score_calculator.py; test_axis_backfill pins that the two agree.
WB_CODES = {
    "child_mortality_per_1000": "SH.DYN.MORT",
    "safe_water_access_pct": "SH.H2O.SMDW.ZS",
    "extreme_poverty_rate_pct": "SI.POV.DDAY",
    "literacy_rate_youth_pct": "SE.ADT.1524.LT.ZS",
    "primary_completion_rate": "SE.PRM.CMPT.ZS",
    "forest_area_pct": "AG.LND.FRST.ZS",
    "protected_terrestrial_area_pct": "ER.LND.PTLD.ZS",
    "urbanization_pct": "SP.URB.TOTL.IN.ZS",
    "gdp_growth_pct": "NY.GDP.MKTP.KD.ZG",
    "food_insecurity_pct": "SN.ITK.DEFC.ZS",
    "renewable_energy_pct": "EG.ELC.RNEW.ZS",
    "adjusted_net_savings_pct": "NY.ADJ.SVNG.GN.ZS",
}
NOAA_METRICS = {"co2_ppm_mauna_loa": NOAA_URL}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def measurable_axes(targets_path=None) -> dict[str, str]:
    """axis -> primary_metric for every axis whose metric has an annual source here."""
    try:
        cfg = json.loads((targets_path or TARGETS).read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for group in cfg.values():
        if not isinstance(group, dict):
            continue
        for axis, spec in group.items():
            if isinstance(spec, dict) and spec.get("primary_metric") in (set(WB_CODES) | set(NOAA_METRICS)):
                out[axis] = spec["primary_metric"]
    return out


# ── parsers (pure) ───────────────────────────────────────────────────────────

def parse_wb(payload) -> list[tuple[int, float]]:
    """World Bank JSON -> [(year, value)] oldest first, nulls dropped."""
    try:
        rows = payload[1] or []
    except (IndexError, TypeError, KeyError):
        return []
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            if r.get("value") is None:
                continue
            out.append((int(r["date"]), float(r["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def parse_noaa_annual(text: str) -> list[tuple[int, float]]:
    """co2_annmean_mlo.txt: '# comment' lines, then 'year mean unc'."""
    out = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        try:
            out.append((int(parts[0]), float(parts[1])))
        except (IndexError, ValueError):
            continue
    return sorted(out)


# ── fetching (injectable) ────────────────────────────────────────────────────

def _get(url: str, timeout: int = 30) -> str:
    import requests
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "CORTEX++ axis_backfill"})
    r.raise_for_status()
    return r.text


def fetch_series(metric: str, get=None) -> tuple[list[tuple[int, float]], str]:
    """([(year, value)], source_label). Empty list on any failure — never raises."""
    get = get or _get
    try:
        if metric in WB_CODES:
            url = WB_URL.format(code=WB_CODES[metric])
            return parse_wb(json.loads(get(url))), f"worldbank:{WB_CODES[metric]}:WLD"
        if metric in NOAA_METRICS:
            return parse_noaa_annual(get(NOAA_METRICS[metric])), "noaa:co2_annmean_mlo"
    except Exception:
        return [], f"fetch_failed:{metric}"
    return [], f"no_source:{metric}"


# ── merge (pure, idempotent) ─────────────────────────────────────────────────

def merge(history: dict, axis: str, metric: str, series: list[tuple[int, float]], source: str, now=None) -> dict:
    """Add/refresh one (axis, year) row per value. Returns counts. A year already on
    file with the same value is untouched; a changed value (source revision) is replaced."""
    ts = now or _now()
    rows = {int(r["year"]): r for r in history.get(axis, []) if isinstance(r, dict) and "year" in r}
    added = revised = 0
    for year, value in series:
        old = rows.get(year)
        if old and (old.get("metrics") or {}).get(metric) == value:
            continue
        rows[year] = {"date": f"{year}-12-31", "year": year, "metrics": {metric: value},
                      "source": source, "fetched": ts}
        if old:
            revised += 1
        else:
            added += 1
    history[axis] = [rows[y] for y in sorted(rows)]
    return {"axis": axis, "metric": metric, "years": len(rows), "added": added, "revised": revised,
            "first": min(rows) if rows else None, "last": max(rows) if rows else None}


def load(path=None) -> dict:
    try:
        d = json.loads((path or ANNUAL).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def series_for(axis: str, path=None) -> list[tuple[int, float]]:
    """[(year, value)] for the axis's metric from the annual file; [] if none."""
    out = []
    for r in load(path).get(axis, []):
        try:
            (metric, value), = (r.get("metrics") or {}).items()
            out.append((int(r["year"]), float(value)))
        except (ValueError, TypeError, KeyError):
            continue
    return sorted(out)


def run(get=None, path=None, targets_path=None, dry=False, now=None) -> dict:
    path = path or ANNUAL
    history = load(path)
    report = []
    for axis, metric in measurable_axes(targets_path).items():
        series, source = fetch_series(metric, get)
        if not series:
            report.append({"axis": axis, "metric": metric, "years": 0, "added": 0, "revised": 0,
                           "first": None, "last": None, "error": source})
            continue
        report.append(merge(history, axis, metric, series, source, now))
    if not dry:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            return {"rows": report, "write_error": f"{type(exc).__name__}: {exc}"}
    return {"rows": report, "axes_with_series": sum(1 for r in report if r["years"]),
            "added": sum(r["added"] for r in report), "revised": sum(r["revised"] for r in report)}


if __name__ == "__main__":
    out = run(dry="--dry" in sys.argv)
    for r in out["rows"]:
        if r["years"]:
            print(f"[BACKFILL] {r['axis']:34s} {r['metric']:32s} {r['first']}..{r['last']} "
                  f"({r['years']} years; +{r['added']} new, {r['revised']} revised)")
        else:
            print(f"[BACKFILL] {r['axis']:34s} {r['metric']:32s} NO SERIES ({r.get('error')})")
    print(f"[BACKFILL] {out.get('axes_with_series', 0)} axes with an annual base; "
          f"+{out.get('added', 0)} rows, {out.get('revised', 0)} revised"
          + (f"; WRITE ERROR {out['write_error']}" if out.get("write_error") else ""))
    sys.exit(0 if out.get("axes_with_series") else 2)
