"""
goal_score_calculator.py
========================
Computes a weighted composite civilization goal score from:
  - trend vectors in cortex_memory/abstractions/trends.json  (MerkleMemory)
  - live observations in data/last_observations.json
  - scientific thresholds in config/target_config.json

Returns:
  {
    "composite_score":  float  0-1,
    "axis_scores":      {axis: score},
    "metric_details":   {metric: {current, target, score, tti_cycles}},
    "timestamp":        str,
  }

Time-to-threshold (TTI): linear extrapolation over last N trend points.
  positive tti  = cycles until target is reached at current rate
  negative tti  = already past target
  None          = no trend data or metric moving away from target
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── paths ─────────────────────────────────────────────────────────────────────
BASE            = Path(__file__).resolve().parent
TRENDS_FILE     = BASE / "cortex_memory" / "abstractions" / "trends.json"
LAST_OBS_FILE   = BASE / "data" / "last_observations.json"
TARGET_CFG_FILE = BASE / "config" / "target_config.json"

# How many trend points to use for linear extrapolation
TTI_WINDOW = 10


# ── loaders ───────────────────────────────────────────────────────────────────

def _load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def load_trends() -> dict:
    return _load(TRENDS_FILE, {})


def load_last_obs() -> dict:
    return _load(LAST_OBS_FILE, {})


def load_targets() -> dict:
    return _load(TARGET_CFG_FILE, {})


# ── metric resolution ─────────────────────────────────────────────────────────

def _resolve_metric(metric_name: str, trends: dict, last_obs: dict) -> float | None:
    """
    Find the current value for a metric.
    Checks trends (most recent point) first, then last_observations.
    """
    if not metric_name:
        return None

    # Trends keys (MerkleMemory naming)
    trend_map = {
        "co2_ppm_mauna_loa":          "co2_ppm",
        "co2_ppm":                    "co2_ppm",
        "refugee_population":         "refugees",
        "total_refugees":             "refugees",
        "species_observations_30d":   "gbif_30d",
        "goal_score":                 "goal_score",
        "kp_index":                   "kp_index",
    }
    trend_key = trend_map.get(metric_name)
    if trend_key and trends.get(trend_key):
        return float(trends[trend_key][-1])

    # last_observations keys
    obs_map = {
        "child_mortality_per_1000":   "wb_SH.DYN.MORT",
        "safe_water_access_pct":      "wb_SH.H2O.SMDW.ZS",
        "extreme_poverty_rate_pct":   "wb_SI.POV.DDAY",
        "refugee_population":         "unhcr_refugees",
        "literacy_rate_youth_pct":    "wb_SE.ADT.1524.LT.ZS",
        "primary_completion_rate":    "wb_SE.PRM.CMPT.ZS",
        "forest_area_pct":            "wb_AG.LND.FRST.ZS",
        "protected_terrestrial_area_pct": "wb_ER.LND.PTLD.ZS",
        "urbanization_pct":           "wb_SP.URB.TOTL.IN.ZS",
        "gdp_growth_pct":             "wb_NY.GDP.MKTP.KD.ZG",
        "food_insecurity_pct":        "wb_SN.ITK.DEFC.ZS",
        "renewable_energy_pct":       "wb_EG.ELC.RNEW.ZS",
    }
    obs_key = obs_map.get(metric_name, metric_name)
    val = last_obs.get(obs_key)
    if val is not None:
        return float(val)

    return None


# ── scoring ───────────────────────────────────────────────────────────────────

def _normalize(
    current: float, target: float, direction: str, reference_worst: float | None = None
) -> float:
    """
    Returns a 0-1 score.
      1.0  = at or better than target
      0.0  = at or worse than reference_worst

    For lower_better:
      - If target > 0: score = target / current  (ratio; 1.0 at target, decays to 0)
      - If target = 0: score = 1 - current / reference_worst  (reference needed)
    For higher_better:
      - score = current / target  (capped at 1.0)
    For stable_better:
      - 0.5 (no directional pressure)
    """
    if direction == "lower_better":
        if current <= target:
            return 1.0
        if target > 0:
            return min(1.0, target / current)
        else:  # target = 0: use reference_worst as denominator
            worst = reference_worst if reference_worst else max(current * 2, 1.0)
            return max(0.0, 1.0 - current / worst)

    elif direction == "higher_better":
        if target <= 0:
            return 1.0 if current >= 0 else 0.0
        return min(1.0, current / target)

    else:  # stable_better
        return 0.5


def _time_to_threshold(
    metric_name: str,
    current: float,
    target: float,
    direction: str,
    trends: dict,
) -> float | None:
    """
    Linear extrapolation: how many cycles until target is reached?
    Returns None if not computable or moving wrong direction.
    """
    trend_map = {
        "co2_ppm_mauna_loa": "co2_ppm",
        "co2_ppm":           "co2_ppm",
        "refugee_population": "refugees",
        "goal_score":        "goal_score",
    }
    key = trend_map.get(metric_name)
    if not key:
        return None

    series = trends.get(key, [])
    if len(series) < 2:
        return None

    window = series[-TTI_WINDOW:]
    # Simple linear regression slope
    n = len(window)
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(window) / n
    num = sum((xs[i] - x_mean) * (window[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    if abs(den) < 1e-12:
        return None

    slope = num / den  # units per cycle

    if direction == "lower_better":
        if slope >= 0:
            return None  # moving away from target
        gap = current - target
        return round(gap / (-slope), 1)

    elif direction == "higher_better":
        if slope <= 0:
            return None
        gap = target - current
        return round(gap / slope, 1)

    return None


# ── main calculator ───────────────────────────────────────────────────────────

def compute_goal_score(
    trends: dict | None = None,
    last_obs: dict | None = None,
    targets: dict | None = None,
) -> dict:
    """
    Computes weighted composite civilization goal score.

    Returns a dict with composite_score, per-axis scores, and metric details.
    """
    if trends is None:
        trends = load_trends()
    if last_obs is None:
        last_obs = load_last_obs()
    if targets is None:
        targets = load_targets()

    metric_details: dict = {}
    axis_scores:    dict = {}

    total_weight  = 0.0
    weighted_sum  = 0.0

    for domain_key, axes in targets.items():
        if domain_key.startswith("_"):
            continue
        for axis_name, cfg in axes.items():
            metric      = cfg.get("primary_metric")
            target_val  = cfg.get("target_value")
            direction   = cfg.get("direction", "higher_better")
            weight      = float(cfg.get("weight", 1))
            unit        = cfg.get("unit", "")

            current_val = _resolve_metric(metric, trends, last_obs) if metric else None

            reference_worst = cfg.get("reference_worst")
            if current_val is not None and target_val is not None:
                score = _normalize(current_val, target_val, direction, reference_worst)
                tti   = _time_to_threshold(metric, current_val, target_val, direction, trends)
            elif direction == "stable_better":
                score = 0.5
                tti   = None
            else:
                # Qualitative / no data → neutral 0.5
                score = 0.5
                tti   = None

            axis_scores[axis_name] = round(score, 4)
            weighted_sum  += score * weight
            total_weight  += weight

            if metric:
                metric_details[metric] = {
                    "axis":         axis_name,
                    "current":      current_val,
                    "target":       target_val,
                    "unit":         unit,
                    "direction":    direction,
                    "score":        round(score, 4),
                    "weight":       weight,
                    "tti_cycles":   tti,
                }

    composite = round(weighted_sum / total_weight, 4) if total_weight > 0 else 0.0

    return {
        "composite_score": composite,
        "axis_scores":     axis_scores,
        "metric_details":  metric_details,
        "total_weight":    total_weight,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
    }


# ── standalone run ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    result = compute_goal_score()

    print("\n" + "=" * 65)
    print(f"  COMPOSITE CIVILIZATION GOAL SCORE: {result['composite_score']:.4f} / 1.0")
    print("=" * 65)

    print("\n--- PER-AXIS SCORES (weight / score) ---")
    targets = load_targets()
    for domain_key, axes in targets.items():
        if domain_key.startswith("_"):
            continue
        print(f"\n  [{domain_key}]")
        for axis_name, cfg in axes.items():
            score  = result["axis_scores"].get(axis_name, 0.5)
            weight = cfg.get("weight", 1)
            bar    = "#" * int(score * 20) + "." * (20 - int(score * 20))
            print(f"    {axis_name:<40} w={weight:2}  [{bar}]  {score:.3f}")

    print("\n--- METRICS WITH REAL DATA ---")
    for metric, detail in sorted(result["metric_details"].items()):
        if detail["current"] is None:
            continue
        tti_str = f"  TTI={detail['tti_cycles']} cycles" if detail["tti_cycles"] else ""
        print(
            f"  {metric:<42} "
            f"current={detail['current']:>12.2f} {detail['unit']:<20} "
            f"target={str(detail['target']):<10} "
            f"score={detail['score']:.3f}{tti_str}"
        )

    print("\n--- QUALITATIVE AXES (score=0.50, no threshold) ---")
    for metric, detail in sorted(result["metric_details"].items()):
        if detail["current"] is not None:
            continue
        print(f"  {detail['axis']:<45} score={detail['score']:.3f} (no data)")
