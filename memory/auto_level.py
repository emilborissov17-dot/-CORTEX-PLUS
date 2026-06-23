#!/usr/bin/env python3
"""
memory/auto_level.py
Изчислява level (LOW/MEDIUM/HIGH) автоматично от реални метрики.
Когато липсват реални метрики → fallback към severity от LLM анализа.
Сравнява с предишния level и алармира при промяна.
"""
import json, pathlib
from datetime import datetime, timezone

BASE_DIR    = pathlib.Path(__file__).resolve().parents[1]
MASTER_PATH = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"
LEVELS_PATH = BASE_DIR / "memory" / "auto_levels.json"

RULES = {
    "HUMAN_WELL_BEING_REVIEW": [
        ("life_expectancy",        "higher_is_better", 65, 75),
        ("infant_mortality",       "lower_is_better",  50, 20),
        ("health_expenditure_pct", "higher_is_better",  5, 10),
    ],
    "COGNITION_LEARNING_REVIEW": [
        ("literacy_rate_youth_pct",   "higher_is_better", 80, 95),
        ("primary_completion_rate",   "higher_is_better", 70, 90),
        ("tertiary_enrollment_pct",   "higher_is_better", 20, 50),
    ],
    "SOCIAL_RELATIONS_REVIEW": [
        ("homicide_rate_per_100k", "lower_is_better", 10, 3),
    ],
    "ECONOMY_WORK_REVIEW": [
        ("gdp_per_capita_usd", "higher_is_better", 5000,  20000),
        ("gdp_growth_pct",     "higher_is_better",    1,      4),
        ("unemployment_pct",   "lower_is_better",    10,      5),
    ],
    "INEQUALITY_POVERTY_REVIEW": [
        ("poverty_headcount_190",   "lower_is_better", 20,  5),
        ("gini_index",              "lower_is_better", 45, 30),
        ("income_share_bottom40",   "higher_is_better", 15, 25),
    ],
    "INFRASTRUCTURE_CITIES_REVIEW": [
        ("access_electricity_pct",  "higher_is_better", 70, 95),
        ("access_clean_fuels_pct",  "higher_is_better", 50, 85),
    ],
    "EDUCATION_CULTURE_REVIEW": [
        ("literacy_rate_adult_pct",    "higher_is_better", 70, 90),
        ("primary_enrollment_pct",     "higher_is_better", 70, 95),
        ("secondary_enrollment_pct",   "higher_is_better", 50, 80),
    ],
    "TECHNOLOGY_AI_REVIEW": [
        ("rd_expenditure_pct_gdp", "higher_is_better", 1.0, 3.0),
        ("high_tech_exports_pct",  "higher_is_better", 10,  30),
    ],
    "TECHNOLOGY_INFRA_REVIEW": [
        ("internet_users_pct",          "higher_is_better", 40, 80),
        ("fixed_broadband_per100",      "higher_is_better",  5, 30),
    ],
    "ENERGY_REVIEW": [
        ("renewable_energy_pct",        "higher_is_better", 20, 50),
        ("fossil_fuel_consumption_pct", "lower_is_better",  80, 50),
    ],
    "WATER_REVIEW": [
        ("access_safe_water_pct",   "higher_is_better", 60, 90),
        ("access_sanitation_pct",   "higher_is_better", 50, 85),
    ],
    "FOOD_REVIEW": [
        ("prevalence_undernourishment_pct", "lower_is_better", 20, 5),
        ("food_production_index",           "higher_is_better", 90, 120),
    ],
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": [
        ("forest_area_pct",                "higher_is_better", 20, 35),
        ("protected_terrestrial_area_pct", "higher_is_better", 10, 20),
    ],
    "SPACE_INFRASTRUCTURE_REVIEW": [
        ("active_satellites_est", "higher_is_better", 1000, 5000),
        ("annual_launches_est",   "higher_is_better",   50,  200),
    ],
    "CLIMATE_GLOBAL_RISK_REVIEW": [
        ("co2_ppm_current",      "lower_is_better", 420, 350),
        ("co2_annual_increase",  "lower_is_better",   3,   1),
    ],
    "MATERIALS_WASTE_REVIEW": [
        ("municipal_waste_per_capita_kg", "lower_is_better",  500, 200),
        ("recycling_rate_pct",            "higher_is_better",  20,  50),
        ("material_consumption_per_gdp",  "lower_is_better",   2.0, 0.8),
    ],
    "GOVERNANCE_INSTITUTIONS_REVIEW": [
        ("rule_of_law_weighted_mean",                  "higher_is_better", -0.2, 0.4),
        ("control_of_corruption_weighted_mean",        "higher_is_better", -0.2, 0.4),
        ("political_stability_weighted_mean",          "higher_is_better", -0.3, 0.3),
        ("voice_accountability_weighted_mean",         "higher_is_better", -0.2, 0.4),
        ("political_stability_pct_pop_below_minus05",  "lower_is_better",   50,  20),
        ("voice_accountability_pct_pop_below_minus05", "lower_is_better",   40,  15),
    ],
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": [
        ("rule_of_law",         "higher_is_better", 0.0, 0.8),
        ("voice_accountability","higher_is_better", 0.0, 0.8),
        ("political_stability", "higher_is_better", 0.0, 0.8),
    ],
    "CULTURE_MEDIA_REVIEW": [
        ("internet_users_pct",         "higher_is_better", 40, 80),
        ("mobile_subscriptions_per100","higher_is_better", 60, 100),
        ("literacy_rate_adult_pct",    "higher_is_better", 70, 90),
    ],
    "COSMIC_RESOURCES_REVIEW": [
        ("outer_space_treaty_signatories", "higher_is_better", 50, 100),
        ("asteroid_mining_missions_active","higher_is_better",  0,   3),
    ],
}

# Severity → score mapping за fallback
# CRITICAL/HIGH → LOW ниво на цивилизацията
# MEDIUM → MEDIUM
# LOW → HIGH
SEVERITY_TO_LEVEL = {
    "CRITICAL": "LOW",
    "HIGH":     "LOW",
    "MEDIUM":   "MEDIUM",
    "LOW":      "HIGH",
}

def _score_metric(value, direction, thresh_low, thresh_high):
    if direction == "higher_is_better":
        if value >= thresh_high: return 2
        if value >= thresh_low:  return 1
        return 0
    else:
        if value <= thresh_high: return 2
        if value <= thresh_low:  return 1
        return 0

def _severity_fallback(snap):
    """
    Извлича severity от snapshot-а и го конвертира в level.
    Търси в: snap["severity"], snap["analysis"]["severity"],
             snap["llm_analysis"]["severity"], snap["data"]["severity"]
    Връща (level, source_description) или (None, None).
    """
    candidates = [
        snap.get("severity"),
        (snap.get("analysis") or {}).get("severity"),
        (snap.get("llm_analysis") or {}).get("severity"),
        (snap.get("data") or {}).get("severity"),
    ]
    for sev in candidates:
        if isinstance(sev, str):
            sev_upper = sev.upper().strip()
            level = SEVERITY_TO_LEVEL.get(sev_upper)
            if level:
                return level, f"severity_fallback({sev_upper})"
    return None, None

def compute_level(axis, metrics, snap=None):
    """
    1. Опитва реални метрики от RULES.
    2. Ако няма → fallback към severity от snap.
    Връща (level, details, source) където source е "metrics" или "severity_fallback".
    """
    try:
        from memory.auto_threshold import get_dynamic_level
    except Exception:
        get_dynamic_level = lambda *a, **k: None

    rules = RULES.get(axis)
    scores = []
    details = []

    if rules:
        for metric_name, direction, thresh_low, thresh_high in rules:
            val = metrics.get(metric_name)
            if val is None:
                continue
            try:
                val = float(val)
            except Exception:
                continue
            score = _score_metric(val, direction, thresh_low, thresh_high)
            scores.append(score)
            level_str = ["LOW", "MEDIUM", "HIGH"][score]
            details.append(f"{metric_name}={round(val,1)} → {level_str}")

    if scores:
        avg = sum(scores) / len(scores)
        if avg >= 1.5:   level = "HIGH"
        elif avg >= 0.7: level = "MEDIUM"
        else:            level = "LOW"
        return level, details, "metrics"

    # ── Fallback: severity от LLM анализа ──
    if snap is not None:
        level, source_desc = _severity_fallback(snap)
        if level:
            details = [source_desc]
            return level, details, "severity_fallback"

    return None, [], None

def run():
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    snapshots = master.get("snapshots", {})

    try:
        prev_levels = json.loads(LEVELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        prev_levels = {}

    new_levels = {}
    alerts = []
    corrections = []
    fallback_count = 0

    print("[AUTO_LEVEL] Изчислявам levels от реални метрики (+ severity fallback)...")
    print()

    for axis, snap in snapshots.items():
        if not isinstance(snap, dict):
            continue

        raw = snap.get("raw")
        metrics = snap.get("metrics") or (raw.get("metrics", {}) if isinstance(raw, dict) else {})
        if isinstance(metrics, dict) and "metrics" in metrics and len(metrics) < 8:
            inner = metrics.get("metrics", {})
            if inner and isinstance(inner, dict):
                metrics = inner
        if not metrics or not isinstance(metrics, dict):
            metrics = {}

        # Подаваме snap за severity fallback
        level, details, source = compute_level(axis, metrics, snap=snap)
        if level is None:
            print(f"⚪ {axis}: ПРОПУСНАТ (няма метрики и severity)")
            continue

        if source == "severity_fallback":
            fallback_count += 1

        old_level = snap.get("level", "?")
        prev_auto  = prev_levels.get(axis, {}).get("level")

        new_levels[axis] = {
            "level": level,
            "details": details,
            "source": source,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        icon = "[OK]" if level == "HIGH" else "[~~]" if level == "MEDIUM" else "[!!]"
        fallback_tag = " [FALLBACK]" if source == "severity_fallback" else ""
        print(f"{icon} {axis}: {level}{fallback_tag}")
        for d in details:
            print(f"   {d}")

        if old_level != "?" and old_level != level and source == "metrics":
            # Корекции само когато имаме реални метрики (не fallback)
            corrections.append({
                "axis": axis,
                "llm_level": old_level,
                "real_level": level,
                "details": details,
            })
            print(f"   [CORR] КОРЕКЦИЯ: LLM казва {old_level}, данните казват {level}")

        if prev_auto and prev_auto != level:
            score_map = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
            if score_map.get(level, 1) < score_map.get(prev_auto, 1):
                alerts.append(f"{axis}: {prev_auto} → {level} ВЛОШАВАНЕ")
                print(f"   [ALERT] {prev_auto} -> {level}")
        print()

    LEVELS_PATH.write_text(
        json.dumps(new_levels, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 50)
    print(f"[AUTO_LEVEL] {len(new_levels)} оси изчислени")
    print(f"[AUTO_LEVEL]   • реални метрики: {len(new_levels) - fallback_count}")
    print(f"[AUTO_LEVEL]   • severity fallback: {fallback_count}")
    if corrections:
        print(f"[AUTO_LEVEL] {len(corrections)} КОРЕКЦИИ (LLM vs реални данни):")
        for c in corrections:
            print(f"   {c['axis']}: LLM={c['llm_level']} vs REAL={c['real_level']}")
    if alerts:
        print(f"[AUTO_LEVEL] {len(alerts)} ALERTS (влошаване):")
        for a in alerts:
            print(f"   {a}")

    return new_levels, corrections, alerts

if __name__ == "__main__":
    run()