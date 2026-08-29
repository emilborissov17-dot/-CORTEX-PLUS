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

def _force_utf8_stdout() -> None:
    """UTF-8 stdout за Windows (решава UnicodeEncodeError с емоджи).

    Вика се САМО от __main__, не при import. Преди това се изпълняваше на
    module level и подменяше sys.stdout на всеки, който импортне модула —
    включително pytest, чийто capture се чупеше с
    "ValueError: I/O operation on closed file".
    Библиотечен модул не бива да пипа глобалния stdout при import.
    """
    if getattr(sys.stdout, "encoding", "").lower().startswith("utf"):
        return  # вече е UTF-8, няма какво да поправяме
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

def is_measured(entry: Dict) -> bool:
    """Did this point actually carry measurements?

    Both shapes occur. The LIVE file holds "metrics": {} — a present key with an
    empty dict — not an absent key, so a check written against `"metrics" not in
    entry` matches nothing on real data. `.get("metrics")` is falsy for {}, None
    and absent alike, which is what the deleted filter relied on and what this
    keeps, minus the deleting.
    """
    return bool(isinstance(entry, dict) and entry.get("metrics"))


def retain(history: Dict) -> Dict:
    """Every dated point survives, and says whether it measured anything.

    WHAT THIS REPLACED, and why it is the whole item (ITEM 12c, 29 Aug 2026):

        for axis in list(history.keys()):
            history[axis] = [e for e in history[axis] if e.get("metrics")]

    That line loaded the file, dropped every point whose metrics were falsy, and
    _save_history wrote the survivors back over the original — a full rewrite,
    not an append. Measured on the live file 2026-08-29: seven axes held exactly
    ONE point each, written by one cycle and deleted by the next. BODY_SCAN,
    DEEP_TIME_RISKS_REVIEW, GENERAL_SELF_REVIEW, GOAL_PROGRESS_REVIEW,
    HYPERCLAW_PLAN, LONG_TERM_FUTURE_REVIEW and PLANETARY_POTENTIAL_REVIEW have
    never had a history at all, and every trend, score and resolution computed
    for them ran over a series that empties itself.

    It arrived in commit 14ca73c, 2026-06-14, "feat: add QWEN architecture as
    base" — a 226-line machine-authored bulk import, already at line 166. No
    commit has ever discussed it. There is no intent to honour.

    Kimi, binding, 2026-08-29: "Coverage data — distinguishing 'ran and found
    nothing' from 'did not run' — is exactly what this system has been silently
    destroying. A marker makes the emptiness explicit and searchable; deletion
    makes it invisible."
    """
    out: Dict = {}
    for axis, entries in history.items():
        if not isinstance(entries, list):
            out[axis] = entries
            continue
        kept = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            kept.append({**e, "measured": is_measured(e)})
        out[axis] = kept
    return out


def measured_days(series: List[Dict]) -> int:
    """How many days actually carry measurement.

    NOT len(series). Line 290 published len(history[axis]) as "history_days",
    which was harmless while unmeasured points were being deleted and becomes a
    lie the moment they are kept. No consumer of axis_history.json reads any
    flag — checked across all eight readers — so the marker cannot be left to
    defend this on its own.
    """
    return sum(1 for e in series if is_measured(e))


def previous_measured_score(series: List[Dict]) -> Optional[float]:
    """The last measured score BEFORE the most recent measured one.

    NOT series[-2]["score"]. That indexed blindly and, with unmeasured points
    preserved, [-2] can be a point whose score is None.

    series[-1] is ALWAYS today's entry — it is appended, or replaced in place
    when the date already matches, just below. So "the previous score" means the
    last measured score among everything BEFORE today, which is what [-2] gave
    while unmeasured points were being deleted. Taking scored[-2] instead would
    skip a day whenever today is measured.
    """
    earlier = series[:-1]
    scored = [e for e in earlier
              if is_measured(e) and isinstance(e.get("score"), (int, float))]
    return float(scored[-1]["score"]) if scored else None


def axis_is_blocked(series: List[Dict]) -> bool:
    """True when this axis must not be scored or resolved.

    An axis whose LATEST point measured nothing is reported as unmeasured, never
    scored. The marker without the block is exactly the fabrication Kimi warned
    of: a growing series of empty rows that reads as history.
    """
    if not series:
        return True
    return not is_measured(series[-1])


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

# World Bank WGI indicators (rule_of_law, voice_accountability, ...) are
# z-scores on a -2.5..+2.5 scale where the world average is ~0 — NOT percentages.
WGI_METRICS = {
    "rule_of_law", "voice_accountability", "political_stability",
    "control_of_corruption", "government_effectiveness", "regulatory_quality",
}
WGI_MIN, WGI_MAX = -2.5, 2.5

SCORES_PATH = BASE_DIR / "output" / "cortex_scores_latest.json"


def _load_engine_scores() -> Dict[str, float]:
    """The authoritative per-axis scores from cortex_scoring_engine (0-1 scale).

    This is the number the rest of the system means by "axis score": it comes
    from per-axis scorers with real thresholds. Returned on the 0-100 scale
    used by axis_history.json.
    """
    if not SCORES_PATH.exists():
        return {}
    try:
        data = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[TREND_TRACKER] cortex_scores_latest.json unreadable "
              f"({type(e).__name__}: {e}) — falling back to metric mean")
        return {}

    out: Dict[str, float] = {}
    for axis, entry in (data.get("scores") or {}).items():
        score = entry.get("score")
        if isinstance(score, (int, float)):
            out[axis] = round(float(score) * 100, 2)   # 0-1 -> 0-100
    return out


def _fallback_metric_mean(metrics: Dict[str, float]) -> Optional[float]:
    """Last-resort score when the scoring engine has no entry for an axis.

    This is a CRUDE approximation and is labelled as such in the output. It
    assumes metrics are 0-100 percentages, which is false for plenty of them
    (satellite counts, patent counts, WGI z-scores). WGI is special-cased here
    because it was the loudest failure: the old code did max(0, min(100, val))
    on a -2.5..+2.5 z-score, so every negative value — i.e. every below-average
    governance indicator on Earth — collapsed to exactly 0.0.
    """
    if not metrics:
        return None
    scores = []
    for key, val in metrics.items():
        if key in WGI_METRICS:
            # -2.5..+2.5 -> 0..100
            pct = (val - WGI_MIN) / (WGI_MAX - WGI_MIN) * 100
            scores.append(max(0.0, min(100.0, pct)))
        elif key in INVERTED_METRICS:
            scores.append(max(0.0, min(100.0, 100 - val)))
        else:
            scores.append(max(0.0, min(100.0, val)))
    return round(sum(scores) / len(scores), 2) if scores else None


def _compute_axis_score(metrics: Dict[str, float], axis: str,
                        engine_scores: Optional[Dict[str, float]] = None) -> tuple:
    """Return (score, source) for an axis, on a 0-100 scale.

    Prefers the authoritative cortex_scoring_engine score. The old behaviour —
    averaging raw metric values clamped to 0..100 — was silently wrong for any
    axis whose metrics are not percentages, which is most of them. It reported
    GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL as 0.0 while the real scorer said 0.44.
    """
    if engine_scores is None:
        engine_scores = _load_engine_scores()

    if axis in engine_scores:
        return engine_scores[axis], "cortex_scoring_engine"

    return _fallback_metric_mean(metrics), "fallback_metric_mean"

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

    history = retain(history)

    engine_scores = _load_engine_scores()
    if engine_scores:
        print(f"[TREND_TRACKER] using cortex_scoring_engine scores for "
              f"{len(engine_scores)} axes")
    else:
        print("[TREND_TRACKER] WARNING: no cortex_scores_latest.json — "
              "all scores fall back to the crude metric mean")

    trends = {}
    fallback_axes = []

    for axis, snapshot in snapshots.items():
        metrics = _extract_metrics(snapshot, axis)
        score, score_source = _compute_axis_score(metrics, axis, engine_scores)
        if score_source == "fallback_metric_mean" and score is not None:
            fallback_axes.append(axis)

        if axis not in history:
            history[axis] = []

        entry = {
            "date": today,
            "timestamp": timestamp,
            "metrics": metrics,
            "score": score,
            # 0-100 here, 0-1 in output/cortex_scores_latest.json, for the same
            # axis on the same day — this module is what multiplies by 100 (see
            # _load_engine_scores). Neither file said so until 2026-08-28.
            # trends_latest.json has carried this key all along; the series it
            # is derived FROM did not.
            "score_scale": "0-100",
            "score_source": score_source,
        }

        if not history[axis] or history[axis][-1]["date"] != today:
            history[axis].append(entry)
        else:
            history[axis][-1] = entry

        trend = _compute_trend(history[axis])
        trends[axis] = {
            "trend": trend,
            "score_today": score,
            "score_prev": previous_measured_score(history[axis]),
            "score_source": score_source,
            "score_scale": "0-100",
            "metrics_count": len(metrics),
            "history_days": measured_days(history[axis]),
            "points_total": len(history[axis]),
            "unmeasured": axis_is_blocked(history[axis]),
        }

        trend_icon = "UP" if trend == "IMPROVING" else "DOWN" if trend == "DETERIORATING" else "->"
        print(f"[TREND_TRACKER] {trend_icon} {axis}: {trend} (score={score}, days={len(history[axis])})")

    _save_history(history)

    trends_report = {
        "date": today,
        "timestamp": timestamp,
        "axes_tracked": len(trends),
        "score_scale": "0-100",
        # Axes whose score is the crude metric mean, not a real scorer output.
        # Never let a fallback number pass as authoritative.
        "axes_on_fallback_score": sorted(fallback_axes),
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
    if fallback_axes:
        print(f"  ⚠️  FALLBACK SCORE:  {len(fallback_axes)} axes have no scoring-engine "
              f"entry (crude metric mean): {', '.join(sorted(fallback_axes)[:5])}"
              + (" ..." if len(fallback_axes) > 5 else ""))
    print(f"\n[TREND_TRACKER] history -> {HISTORY_FILE}")
    print(f"[TREND_TRACKER] trends  -> {TRENDS_FILE}")

    return trends_report

if __name__ == "__main__":
    _force_utf8_stdout()
    run()