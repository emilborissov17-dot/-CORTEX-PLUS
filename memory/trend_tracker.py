#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory/trend_tracker.py

Сравнява днешния master snapshot с предишните.
Открива тенденции (IMPROVING / STABLE / DETERIORATING) по всяка ос.
Записва историята в memory/axis_history.json
и последните тенденции в memory/trends_latest.json
"""
from __future__ import annotations
import sys, io, json, pathlib, datetime
from typing import Any, Dict, List, Optional

# ── Fix: UTF-8 stdout за Windows (решава UnicodeEncodeError с емоджи) ──
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE_DIR     = pathlib.Path(__file__).resolve().parents[1]
MEMORY_DIR   = BASE_DIR / "memory"
MASTER_PATH  = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"
HISTORY_FILE = MEMORY_DIR / "axis_history.json"
TRENDS_FILE  = MEMORY_DIR / "trends_latest.json"

MEMORY_DIR.mkdir(exist_ok=True)

TRACKED_METRICS = {
    "HUMAN_WELL_BEING_REVIEW":          ["life_expectancy", "infant_mortality", "poverty_headcount", "uhc_service_coverage_index"],
    "CULTURE_MEDIA_REVIEW":             ["internet_users_pct", "literacy_rate_adult_pct", "secondary_school_enrollment"],
    "COGNITION_LEARNING_REVIEW":        ["literacy_rate_youth_pct", "primary_completion_rate", "tertiary_enrollment_pct"],
    "SOCIAL_RELATIONS_REVIEW":          ["homicide_rate_per_100k", "refugee_population", "urbanization_pct"],
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": ["rule_of_law", "voice_accountability", "political_stability"],
    "CLIMATE_GLOBAL_RISK_REVIEW":       ["temperature_2m_max", "precipitation_sum"],
    "ENERGY_REVIEW":                    ["renewable_energy_pct", "co2_emissions_per_capita", "access_to_electricity_pct"],
    "WATER_REVIEW":                     ["access_safe_water_pct", "access_sanitation_pct", "water_productivity_usd_m3", "annual_freshwater_withdrawal_pct", "rural_water_access_pct", "urban_water_access_pct"],
    "FOOD_REVIEW":                      ["food_supply_kcal_per_capita", "undernourishment_pct", "cereal_yield_kg_per_ha", "food_price_index"],
    "MATERIALS_WASTE_REVIEW":           ["material_footprint_per_capita", "domestic_material_consumption", "waste_generation_kg_per_capita"],
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":   ["forest_area_pct", "protected_areas_pct", "red_list_index"],
    "PLANETARY_POTENTIAL_REVIEW":       ["planetary_boundaries_score", "ecological_footprint", "biocapacity"],
    "ECONOMY_WORK_REVIEW":              ["gdp_per_capita_usd", "gdp_growth_pct", "unemployment_pct", "gini_index"],
    "INEQUALITY_POVERTY_REVIEW":        ["gini_index", "poverty_headcount_190", "income_share_top10"],
    "INFRASTRUCTURE_CITIES_REVIEW":     ["access_electricity_pct", "urban_population_pct", "fixed_broadband_per100"],
    "GOVERNANCE_INSTITUTIONS_REVIEW":   ["rule_of_law", "control_of_corruption", "government_effectiveness"],
    "EDUCATION_CULTURE_REVIEW":         ["literacy_rate_adult_pct", "primary_enrollment_pct", "govt_education_spend_pct_gdp"],
    "TECHNOLOGY_INFRA_REVIEW":          ["fixed_broadband_per100", "mobile_subscriptions_per100"],
    "TECHNOLOGY_AI_REVIEW":             ["rd_expenditure_pct_gdp", "high_tech_exports_pct", "patent_applications"],
    "LONG_TERM_FUTURE_REVIEW":          ["hdi", "social_progress_index", "future_readiness_score"],
    "SPACE_INFRASTRUCTURE_REVIEW":      ["active_satellites_est", "annual_launches_est"],
    "COSMIC_RESOURCES_REVIEW":          ["outer_space_treaty_signatories"],
    "DEEP_TIME_RISKS_REVIEW":           ["nuclear_warheads_est", "existential_risk_index"],
    "GENERAL_SELF_REVIEW":              ["system_health_score", "components_active", "uptime_days"],
    "GOAL_PROGRESS_REVIEW":             ["goals_completed_pct", "active_goals", "progress_score"],
}

INVERTED_METRICS = {
    "infant_mortality", "poverty_headcount", "co2_emissions_per_capita",
    "homicide_rate_per_100k", "refugee_population", "unemployment_pct",
    "gini_index", "poverty_headcount_190", "income_share_top10",
    "annual_freshwater_withdrawal_pct", "undernourishment_pct",
    "material_footprint_per_capita", "waste_generation_kg_per_capita",
    "ecological_footprint", "nuclear_warheads_est", "existential_risk_index",
}

def _load_history() -> Dict[str, List[Dict]]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {}

def _save_history(history: Dict) -> None:
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

def _extract_metrics(snapshot: Dict, axis: str) -> Dict[str, float]:
    tracked = TRACKED_METRICS.get(axis, [])
    metrics = {}

    direct_metrics = snapshot.get("metrics", {})
    raw = snapshot.get("raw") or {}
    raw_metrics = raw.get("metrics", {}) if isinstance(raw, dict) else {}
    all_metrics = {**raw_metrics, **direct_metrics}

    if tracked:
        for key in tracked:
            val = all_metrics.get(key)
            if val is not None:
                try:
                    metrics[key] = float(val)
                except Exception:
                    pass

    if not metrics and all_metrics:
        for key, val in all_metrics.items():
            if val is not None:
                try:
                    metrics[key] = float(val)
                except Exception:
                    pass

    return metrics

def _compute_trend(history: List[Dict]) -> str:
    if len(history) < 2:
        return "INSUFFICIENT_DATA"

    recent = [h for h in history[-5:] if h.get("metrics")]
    if len(recent) < 2:
        return "INSUFFICIENT_DATA"

    prev_m = recent[-2]["metrics"]
    curr_m = recent[-1]["metrics"]

    improvements = 0
    deteriorations = 0

    for key in curr_m:
        if key not in prev_m:
            continue
        curr_val = curr_m[key]
        prev_val = prev_m[key]
        if prev_val == 0:
            continue
        change_pct = (curr_val - prev_val) / abs(prev_val) * 100

        if key in INVERTED_METRICS:
            change_pct = -change_pct

        if change_pct > 0.5:
            improvements += 1
        elif change_pct < -0.5:
            deteriorations += 1

    total = improvements + deteriorations
    if total == 0:
        return "STABLE"
    if improvements > deteriorations * 1.5:
        return "IMPROVING"
    if deteriorations > improvements * 1.5:
        return "DETERIORATING"
    return "STABLE"

def _compute_axis_score(metrics: Dict[str, float], axis: str) -> Optional[float]:
    if not metrics:
        return None
    scores = []
    for key, val in metrics.items():
        if key in INVERTED_METRICS:
            score = max(0, min(100, 100 - val))
        else:
            score = max(0, min(100, val))
        scores.append(score)
    return round(sum(scores) / len(scores), 2) if scores else None

def run() -> Dict:
    print("[TREND_TRACKER] loading master snapshot...")
    if not MASTER_PATH.exists():
        print("[TREND_TRACKER] ERROR: master snapshot not found!")
        return {}

    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    snapshots = master.get("snapshots", {})
    today = datetime.date.today().isoformat()
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    history = _load_history()

    for axis in list(history.keys()):
        history[axis] = [e for e in history[axis] if e.get("metrics")]

    trends = {}

    for axis, snapshot in snapshots.items():
        metrics = _extract_metrics(snapshot, axis)
        score = _compute_axis_score(metrics, axis)

        if axis not in history:
            history[axis] = []

        entry = {
            "date": today,
            "timestamp": timestamp,
            "metrics": metrics,
            "score": score,
        }

        if not history[axis] or history[axis][-1]["date"] != today:
            history[axis].append(entry)
        else:
            history[axis][-1] = entry

        trend = _compute_trend(history[axis])
        trends[axis] = {
            "trend": trend,
            "score_today": score,
            "score_prev": history[axis][-2]["score"] if len(history[axis]) >= 2 else None,
            "metrics_count": len(metrics),
            "history_days": len(history[axis]),
        }

        trend_icon = "UP" if trend == "IMPROVING" else "DOWN" if trend == "DETERIORATING" else "->"
        print(f"[TREND_TRACKER] {trend_icon} {axis}: {trend} (score={score}, days={len(history[axis])})")

    _save_history(history)

    trends_report = {
        "date": today,
        "timestamp": timestamp,
        "axes_tracked": len(trends),
        "improving": [a for a, t in trends.items() if t["trend"] == "IMPROVING"],
        "deteriorating": [a for a, t in trends.items() if t["trend"] == "DETERIORATING"],
        "stable": [a for a, t in trends.items() if t["trend"] == "STABLE"],
        "insufficient_data": [a for a, t in trends.items() if t["trend"] == "INSUFFICIENT_DATA"],
        "details": trends,
    }
    TRENDS_FILE.write_text(json.dumps(trends_report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[TREND_TRACKER] SUMMARY:")
    print(f"  IMPROVING:          {len(trends_report['improving'])}")
    print(f"  STABLE:             {len(trends_report['stable'])}")
    print(f"  DETERIORATING:      {len(trends_report['deteriorating'])}")
    print(f"  INSUFFICIENT_DATA:  {len(trends_report['insufficient_data'])}")
    print(f"\n[TREND_TRACKER] history -> {HISTORY_FILE}")
    print(f"[TREND_TRACKER] trends  -> {TRENDS_FILE}")

    return trends_report

if __name__ == "__main__":
    run()