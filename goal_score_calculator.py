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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── paths ─────────────────────────────────────────────────────────────────────
BASE                = Path(__file__).resolve().parent
TRENDS_FILE         = BASE / "cortex_memory" / "abstractions" / "trends.json"
LAST_OBS_FILE       = BASE / "data" / "last_observations.json"
TARGET_CFG_FILE     = BASE / "config" / "target_config.json"
WELLBEING_GLOBE_FILE = BASE / "output" / "wellbeing_globe.json"
GLOBAL_IND_FILE     = BASE / "snapshots" / "master" / "global_indicators_latest.json"
GLOBAL_IND_FRESHNESS_DAYS = 14
PROBED_FILE         = BASE / "memory" / "probed_signals.json"   # what the organism's own hands fetched

# How many trend points to use for linear extrapolation
TTI_WINDOW = 10

# Governance globals (from wellbeing_globe.py --governance-only) older than this
# are treated as unavailable rather than silently consumed as a frozen "real" score.
GOVERNANCE_FRESHNESS_DAYS = 90


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


def load_governance_globals() -> dict:
    """
    Load the two governance axis globals from output/wellbeing_globe.json,
    gated by a freshness check on governance_computed_at.

    Returns {} (axes fall back to qualitative 0.5) if the file is missing,
    has no timestamp, or the timestamp is older than GOVERNANCE_FRESHNESS_DAYS —
    always with a loud stderr warning, never a silent stale "real" score.
    """
    data = _load(WELLBEING_GLOBE_FILE, {})
    ts_str = data.get("governance_computed_at")
    if not ts_str:
        print(
            "[goal_score] WARNING: output/wellbeing_globe.json has no governance_computed_at "
            "— GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL / GOVERNANCE_INSTITUTIONS_REVIEW falling back to 0.5. "
            "Run: python wellbeing_globe.py --governance-only",
            file=sys.stderr,
        )
        return {}
    try:
        ts = datetime.fromisoformat(ts_str)
    except ValueError:
        print(
            f"[goal_score] WARNING: unparsable governance_computed_at={ts_str!r} "
            "— governance axes falling back to 0.5.",
            file=sys.stderr,
        )
        return {}

    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    if age_days > GOVERNANCE_FRESHNESS_DAYS:
        print(
            f"[goal_score] WARNING: governance globals are {age_days:.0f} days old "
            f"(> {GOVERNANCE_FRESHNESS_DAYS}d freshness threshold) — falling back to 0.5. "
            f"Run: python wellbeing_globe.py --governance-only",
            file=sys.stderr,
        )
        return {}

    return {
        "governance_rights_score_global":       data.get("governance_rights_score"),
        "governance_institutions_score_global": data.get("governance_institutions_score"),
    }


def load_global_indicators() -> dict:
    """Adapt the LIVE global_indicators_latest.json (written each cycle by
    core.global_indicators.fetch_all) into the flat obs keys _resolve_metric
    expects. Fresh data overrides stale data/last_observations.json.
    Freshness-gated; loud stderr + {} if missing or too old."""
    data = _load(GLOBAL_IND_FILE, {})
    if not data:
        print("[goal_score] WARNING: global_indicators_latest.json missing — dead axes stay 0.5.", file=sys.stderr)
        return {}
    ts_str = data.get("timestamp")
    if ts_str:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts_str)).total_seconds() / 86400
            if age > GLOBAL_IND_FRESHNESS_DAYS:
                print(f"[goal_score] WARNING: global_indicators {age:.0f}d old (>{GLOBAL_IND_FRESHNESS_DAYS}d) — not used.", file=sys.stderr)
                return {}
        except ValueError:
            pass
    co2, wb   = data.get("co2", {}),   data.get("world_bank", {})
    food, dsp = data.get("food", {}),  data.get("displaced", {})
    econ, cty = data.get("economy", {}), data.get("cities", {})
    out: dict = {}
    def put(k, v):
        if v is not None: out[k] = v
    put("noaa_co2_ppm",         co2.get("co2_ppm"))
    put("wb_AG.LND.FRST.ZS",    wb.get("forest_area_pct"))
    put("wb_EG.ELC.RNEW.ZS",    wb.get("renewable_elec_pct"))
    put("wb_SH.H2O.SMDW.ZS",    wb.get("safe_water_access_pct"))
    put("wb_SH.DYN.MORT",       wb.get("infant_mortality_per1k"))     # APPROX: infant vs under-5
    put("wb_SI.POV.DDAY",       wb.get("poverty_190_pct"))
    put("wb_SE.ADT.1524.LT.ZS", wb.get("literacy_rate_adult_pct"))    # APPROX: adult vs youth
    put("wb_SN.ITK.DEFC.ZS",    food.get("undernourishment_pct"))
    r = dsp.get("refugees_millions")
    put("unhcr_refugees",       r * 1_000_000 if r is not None else None)
    put("wb_NY.GDP.MKTP.KD.ZG", econ.get("gdp_growth_annual_pct"))
    put("wb_SP.URB.TOTL.IN.ZS", cty.get("urban_population_pct"))
    return out


def load_probed_signals() -> dict:
    """Signals the organism's OWN hands fetched (memory/probed_signals.json).
    ONLY the 'validated_obs' block feeds the score — self-discovered probes stay
    in the file's audit, pending semantic validation, so an unvalidated auto-found
    number can never move the goal. This is probe -> scoring, closed and gated."""
    data = _load(PROBED_FILE, {})
    obs = data.get("validated_obs", {}) if isinstance(data, dict) else {}
    return {k: v for k, v in obs.items() if isinstance(v, (int, float))}


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
        "co2_ppm_mauna_loa":          "noaa_co2_ppm",
        "co2_ppm":                    "noaa_co2_ppm",
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
        if metric_name == "refugee_population" and float(val) == 0.0:
            return None  # sentinel zero, not a real count
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
        last_obs = {**load_last_obs(), **load_governance_globals(),
                    **load_global_indicators(), **load_probed_signals()}
    if targets is None:
        targets = load_targets()

    metric_details: dict = {}
    axis_scores:    dict = {}

    total_weight    = 0.0
    weighted_sum    = 0.0
    measured_weight = 0.0      # теглото, зад което наистина стои число

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
                # ── КОНСЕНСУС С KIMI, 15 август 2026 ─────────────────────────
                # Дотук тук пишеше: „Qualitative / no data -> neutral 0.5", и това
                # 0.5 влизаше в претеглената сума С ПЪЛНОТО СИ ТЕГЛО. Преброено:
                # 11 от 25 оси нямаха разрешено число, тоест 65 от 173 тегло —
                # 38% ОТ КОМПОЗИТА стоеше на константа. Първата от тях беше
                # CLIMATE_GLOBAL_RISK_REVIEW, с най-високото тегло в конфигурацията.
                #
                # Kimi, дословно:
                #   „Оси без числа не са 'неизмервани' — те са ИЗМЕРЕНИ ОТ LLM БЕЗ
                #    КОНТРОЛ, което е по-опасно от призната невежда."
                #   „Не махай 0.5 — замени го с NULL, но остави осите в знаменателя.
                #    Така липсата се вижда."
                #   „Сравнимост: двойка (score, coverage). Ден с 62% не е сравним с
                #    95% — това не е бъг, а истина."
                #   „Едно число при 38% незнание е СТАТИСТИЧЕСКА ЛЪЖА. Публикуваш
                #    score само при coverage >= праг, иначе 'insufficient data'."
                #
                # Затова: липсата вече е None, не 0.5. Тежестта ѝ НЕ влиза в
                # числителя (иначе незнанието щеше да оценява), но влиза в общото
                # тегло — така покритието се вижда, вместо да се крие.
                score = None
                tti   = None

            axis_scores[axis_name] = round(score, 4) if score is not None else None
            total_weight  += weight
            if score is not None:
                weighted_sum  += score * weight
                measured_weight += weight

            if metric:
                metric_details[metric] = {
                    "axis":         axis_name,
                    "current":      current_val,
                    "target":       target_val,
                    "unit":         unit,
                    "direction":    direction,
                    "score":        (round(score, 4) if score is not None else None),
                    "measured":     score is not None,
                    "weight":       weight,
                    "tti_cycles":   tti,
                }

    # Покритието е ЧАСТ ОТ ОТГОВОРА, не бележка под линия.
    coverage = round(measured_weight / total_weight, 4) if total_weight > 0 else 0.0
    measured_composite = (round(weighted_sum / measured_weight, 4)
                          if measured_weight > 0 else None)

    # Прагът, под който едно число е лъжа. 0.80 е предложението на Kimi; стои тук
    # като явна константа, за да може да се оспори, а не скрито в израз.
    COVERAGE_MIN = 0.80
    enough = coverage >= COVERAGE_MIN
    unmeasured = sorted(a for a, s in axis_scores.items() if s is None)

    # ЗА СЪВМЕСТИМОСТ: composite_score остава ЧИСЛО, защото цикълът, Merkle
    # ангажиментът и отчетите го четат — но вече е средно САМО от измереното, а не
    # разредено с константи. Дали изобщо бива да се чете като истина, казва
    # composite_valid: под прага то е False и придружено с причина.
    composite = measured_composite if measured_composite is not None else 0.0

    return {
        "composite_score": composite,
        "composite_valid": enough,
        "coverage": coverage,
        "coverage_min": COVERAGE_MIN,
        "measured_weight": round(measured_weight, 1),
        "unmeasured_axes": unmeasured,
        "insufficient_data": (None if enough else
                              f"покритие {coverage:.0%} < {COVERAGE_MIN:.0%}: "
                              f"{len(unmeasured)} оси без число "
                              f"({', '.join(unmeasured[:4])}...). Едно число при "
                              f"{1 - coverage:.0%} незнание не е оценка."),
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
