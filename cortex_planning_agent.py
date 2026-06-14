#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CORTEX++ Scoring Engine
Автоматична оценка LOW/MEDIUM/HIGH базирана на реални метрики и научни прагове.
"""
from __future__ import annotations
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

BASE_DIR = pathlib.Path(__file__).resolve().parent
SNAPSHOTS_DIR = BASE_DIR / "snapshots"


@dataclass
class ScoreResult:
    axis: str
    level: str          # LOW / MEDIUM / HIGH
    score: float        # 0.0 - 1.0 (1.0 = най-добро)
    signals: List[str]  # обяснения
    metrics_used: Dict[str, Any]


def _unwrap_metrics(metrics: Dict) -> Dict:
    """Unwrap nested metrics dicts (handles double/triple nesting)."""
    while "metrics" in metrics and isinstance(metrics["metrics"], dict):
        metrics = metrics["metrics"]
    return metrics


# ─────────────────────────────────────────────
# DOMAIN MAP
# ─────────────────────────────────────────────

AXIS_DOMAIN_MAP: Dict[str, str] = {
    "CLIMATE_GLOBAL_RISK_REVIEW":      "PLANET",
    "ENERGY_REVIEW":                   "PLANET",
    "FOOD_REVIEW":                     "PLANET",
    "WATER_REVIEW":                    "PLANET",
    "MATERIALS_WASTE_REVIEW":          "PLANET",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":  "PLANET",
    "PLANETARY_POTENTIAL_REVIEW":      "PLANET",
    "HUMAN_WELL_BEING_REVIEW":         "HUMAN",
    "CULTURE_MEDIA_REVIEW":            "HUMAN",
    "COGNITION_LEARNING_REVIEW":       "HUMAN",
    "SOCIAL_RELATIONS_REVIEW":         "HUMAN",
    "ECONOMY_WORK_REVIEW":             "CIVILIZATION",
    "INEQUALITY_POVERTY_REVIEW":       "CIVILIZATION",
    "GOVERNANCE_INSTITUTIONS_REVIEW":  "CIVILIZATION",
    "TECHNOLOGY_AI_REVIEW":            "CIVILIZATION",
    "EDUCATION_CULTURE_REVIEW":        "CIVILIZATION",
    "INFRASTRUCTURE_CITIES_REVIEW":    "CIVILIZATION",
    "TECHNOLOGY_INFRA_REVIEW":         "CIVILIZATION",
    "LONG_TERM_FUTURE_REVIEW":         "COSMOS",
    "DEEP_TIME_RISKS_REVIEW":          "COSMOS",
    "GOAL_PROGRESS_REVIEW":            "COSMOS",
    "SPACE_INFRASTRUCTURE_REVIEW":     "COSMOS",
    "COSMIC_RESOURCES_REVIEW":         "COSMOS",
    "GENERAL_SELF_REVIEW":             "COSMOS",
}


# ─────────────────────────────────────────────
# SCORING FUNCTIONS — по ос
# ─────────────────────────────────────────────

def score_climate(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 1.0

    co2 = metrics.get("co2_ppm_current", 0)
    co2_increase = metrics.get("co2_annual_increase", 0)
    max_temp_7d = metrics.get("forecast_forecast_max_temp_7d", 0)

    if co2 > 430:
        score -= 0.4
        signals.append(f"⚠️ CO2 {co2} ppm — опасно над 420 ppm (пред-индустриален: 280 ppm)")
    elif co2 > 420:
        score -= 0.2
        signals.append(f"⚡ CO2 {co2} ppm — над безопасния праг")
    else:
        signals.append(f"✅ CO2 {co2} ppm — под критичния праг")

    if co2_increase > 3.5:
        score -= 0.3
        signals.append(f"⚠️ Годишен ръст на CO2: +{co2_increase} ppm — ускорен")
    elif co2_increase > 2.5:
        score -= 0.15
        signals.append(f"⚡ Годишен ръст на CO2: +{co2_increase} ppm — над нормата")
    else:
        signals.append(f"✅ Годишен ръст на CO2: +{co2_increase} ppm")

    if max_temp_7d > 35:
        score -= 0.2
        signals.append(f"⚠️ Прогноза: екстремна топлина {max_temp_7d}°C")
    elif max_temp_7d > 25:
        score -= 0.05
        signals.append(f"⚡ Прогноза: висока температура {max_temp_7d}°C")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="CLIMATE_GLOBAL_RISK_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"co2_ppm": co2, "co2_increase": co2_increase, "max_temp_7d": max_temp_7d}
    )


def score_energy(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    renewables = (metrics.get("renewable_energy_pct") or
                  metrics.get("renewables_share_pct"))
    fossil = (metrics.get("fossil_fuel_consumption_pct") or
              metrics.get("fossil_fuel_share_pct"))
    access = metrics.get("access_to_electricity_pct")

    if renewables is not None:
        if renewables > 60:
            score = 0.8
            signals.append(f"✅ Възобновяеми: {renewables:.1f}% — добро ниво")
        elif renewables > 30:
            score = 0.5
            signals.append(f"⚡ Възобновяеми: {renewables:.1f}% — нужен напредък")
        else:
            score = 0.2
            signals.append(f"⚠️ Възобновяеми: {renewables:.1f}% — критично ниско")
    else:
        signals.append("⚡ Липсват данни за дял на възобновяеми")

    if fossil is not None and fossil > 70:
        score -= 0.15
        signals.append(f"⚠️ Изкопаеми горива: {fossil:.1f}% — висока зависимост")

    if access is not None and access < 85:
        score -= 0.1
        signals.append(f"⚠️ Достъп до ел. енергия: {access:.1f}% — под 85%")
    elif access is not None:
        signals.append(f"✅ Достъп до ел. енергия: {access:.1f}%")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="ENERGY_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"renewable_pct": renewables, "fossil_pct": fossil, "access_pct": access}
    )


def score_human_well_being(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    uhc = metrics.get("uhc_service_coverage_index")
    suicide = metrics.get("suicide_rate_per_100k")
    poverty = metrics.get("poverty_headcount")
    life_exp = metrics.get("life_expectancy")

    if uhc is not None:
        if uhc > 80:
            score = 0.8
            signals.append(f"✅ UHC индекс: {uhc} — добро покритие")
        elif uhc > 60:
            score = 0.55
            signals.append(f"⚡ UHC индекс: {uhc} — средно покритие")
        else:
            score = 0.25
            signals.append(f"⚠️ UHC индекс: {uhc} — слабо покритие")

    if suicide is not None:
        if suicide > 15:
            score -= 0.2
            signals.append(f"⚠️ Самоубийства: {suicide:.1f}/100k — висок стрес")
        elif suicide > 10:
            score -= 0.1
            signals.append(f"⚡ Самоубийства: {suicide:.1f}/100k — над средното")
        else:
            signals.append(f"✅ Самоубийства: {suicide:.1f}/100k")

    if poverty is not None:
        if poverty > 20:
            score -= 0.2
            signals.append(f"⚠️ Бедност: {poverty}% — критично")
        elif poverty > 10:
            score -= 0.1
            signals.append(f"⚡ Бедност: {poverty}% — значително")
        else:
            signals.append(f"✅ Бедност: {poverty}%")

    if life_exp is not None:
        if life_exp > 75:
            score += 0.05
            signals.append(f"✅ Продължителност на живота: {life_exp:.1f} г.")
        elif life_exp < 65:
            score -= 0.15
            signals.append(f"⚠️ Продължителност на живота: {life_exp:.1f} г. — ниска")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="HUMAN_WELL_BEING_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"uhc": uhc, "suicide_rate": suicide, "poverty": poverty, "life_exp": life_exp}
    )


def score_economy(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    gdp = metrics.get("gdp_per_capita_usd")
    growth = metrics.get("gdp_growth_pct")
    unemployment = metrics.get("unemployment_pct")
    gini = metrics.get("gini_index")

    if gdp is not None:
        if gdp > 20000:
            score = 0.75
            signals.append(f"✅ БВП на глава: ${gdp:,.0f} — над 20k USD")
        elif gdp > 5000:
            score = 0.5
            signals.append(f"⚡ БВП на глава: ${gdp:,.0f} — среден доход")
        else:
            score = 0.25
            signals.append(f"⚠️ БВП на глава: ${gdp:,.0f} — нисък доход")

    if growth is not None:
        if growth < 0:
            score -= 0.2
            signals.append(f"⚠️ БВП ръст: {growth:.1f}% — рецесия")
        elif growth < 1.5:
            score -= 0.05
            signals.append(f"⚡ БВП ръст: {growth:.1f}% — бавен растеж")
        else:
            signals.append(f"✅ БВП ръст: {growth:.1f}%")

    if unemployment is not None:
        if unemployment > 10:
            score -= 0.2
            signals.append(f"⚠️ Безработица: {unemployment:.1f}% — висока")
        elif unemployment > 6:
            score -= 0.1
            signals.append(f"⚡ Безработица: {unemployment:.1f}% — умерена")
        else:
            signals.append(f"✅ Безработица: {unemployment:.1f}%")

    if gini is not None:
        if gini > 45:
            score -= 0.15
            signals.append(f"⚠️ Джини: {gini:.1f} — висока неравенственост")
        elif gini > 35:
            score -= 0.05
            signals.append(f"⚡ Джини: {gini:.1f} — умерена неравнственост")
        else:
            signals.append(f"✅ Джини: {gini:.1f} — ниска неравнственост")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="ECONOMY_WORK_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"gdp_per_capita": gdp, "growth": growth, "unemployment": unemployment}
    )


def score_inequality(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.6

    gini = metrics.get("gini_index")
    poverty = (metrics.get("poverty_headcount") or
               metrics.get("poverty_headcount_190"))
    bottom20 = (metrics.get("income_share_bottom20") or
                metrics.get("income_share_bottom40"))
    top10 = metrics.get("income_share_top10")

    if gini is not None:
        if gini > 45:
            score = 0.25
            signals.append(f"⚠️ Джини: {gini:.1f} — висока неравнственост")
        elif gini > 35:
            score = 0.5
            signals.append(f"⚡ Джини: {gini:.1f} — умерена")
        else:
            score = 0.75
            signals.append(f"✅ Джини: {gini:.1f} — ниска неравнственост")
    else:
        signals.append("⚡ Липсват данни за Джини индекс")

    if poverty is not None:
        if poverty > 20:
            score -= 0.2
            signals.append(f"⚠️ Бедност: {poverty:.1f}% — критично")
        elif poverty > 10:
            score -= 0.1
            signals.append(f"⚡ Бедност: {poverty:.1f}%")
        else:
            signals.append(f"✅ Бедност: {poverty:.1f}%")

    if bottom20 is not None and bottom20 < 5:
        score -= 0.1
        signals.append(f"⚠️ Дял на дохода на долните 20%: {bottom20:.1f}% — много нисък")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="INEQUALITY_POVERTY_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"gini": gini, "poverty": poverty, "bottom20": bottom20}
    )


def score_governance(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    rule_of_law = (metrics.get("rule_of_law") or
                   metrics.get("rule_of_law_weighted_mean"))
    corruption = (metrics.get("control_of_corruption") or
                  metrics.get("control_of_corruption_weighted_mean"))
    political_stability = (metrics.get("political_stability") or
                           metrics.get("political_stability_weighted_mean"))
    gov_effectiveness = (metrics.get("government_effectiveness") or
                         metrics.get("government_effectiveness_weighted_mean"))
    democracy = metrics.get("democracy_index")
    press_freedom = metrics.get("press_freedom_index")

    wb_scores = []
    for val, label in [
        (rule_of_law, "Върховенство на закона"),
        (corruption, "Контрол на корупцията"),
        (political_stability, "Политическа стабилност"),
        (gov_effectiveness, "Ефективност на управлението"),
    ]:
        if val is not None:
            normalized = (val + 2.5) / 5.0  # -2.5..2.5 → 0..1
            wb_scores.append(normalized)
            if normalized > 0.6:
                signals.append(f"✅ {label}: {val:.2f}")
            elif normalized > 0.4:
                signals.append(f"⚡ {label}: {val:.2f}")
            else:
                signals.append(f"⚠️ {label}: {val:.2f} — слабо")

    if wb_scores:
        score = sum(wb_scores) / len(wb_scores)
    else:
        signals.append("⚡ Липсват World Bank governance данни")

    if democracy is not None:
        if democracy > 7:
            score += 0.05
            signals.append(f"✅ Демокрация индекс: {democracy:.1f}/10")
        elif democracy < 4:
            score -= 0.1
            signals.append(f"⚠️ Демокрация индекс: {democracy:.1f}/10 — авторитарен режим")

    if press_freedom is not None:
        if press_freedom < 30:
            score += 0.05
            signals.append(f"✅ Свобода на пресата: #{press_freedom}")
        elif press_freedom > 100:
            score -= 0.1
            signals.append(f"⚠️ Свобода на пресата: #{press_freedom} — ограничена")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="GOVERNANCE_INSTITUTIONS_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"rule_of_law": rule_of_law, "corruption": corruption,
                      "political_stability": political_stability}
    )


def score_technology_ai(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    internet = (metrics.get("internet_penetration_pct") or
                metrics.get("individuals_internet_pct"))
    rd_spend = metrics.get("rd_expenditure_pct_gdp")
    patent_apps = metrics.get("patent_applications")
    ai_investment = metrics.get("ai_investment_usd_bn")
    high_tech = metrics.get("high_tech_exports_pct")

    if internet is not None:
        if internet > 80:
            score = 0.7
            signals.append(f"✅ Интернет покритие: {internet:.1f}%")
        elif internet > 50:
            score = 0.5
            signals.append(f"⚡ Интернет покритие: {internet:.1f}%")
        else:
            score = 0.3
            signals.append(f"⚠️ Интернет покритие: {internet:.1f}% — ниско")

    if rd_spend is not None:
        if rd_spend > 2.5:
            score += 0.1
            signals.append(f"✅ НИРД разходи: {rd_spend:.1f}% от БВП")
        elif rd_spend < 1.0:
            score -= 0.1
            signals.append(f"⚠️ НИРД разходи: {rd_spend:.1f}% — под 1% от БВП")
        else:
            signals.append(f"⚡ НИРД разходи: {rd_spend:.1f}% от БВП")

    if high_tech is not None:
        if high_tech > 20:
            score += 0.05
            signals.append(f"✅ Високотехнологичен износ: {high_tech:.1f}%")
        elif high_tech < 10:
            score -= 0.05
            signals.append(f"⚠️ Високотехнологичен износ: {high_tech:.1f}% — нисък")

    if patent_apps is not None:
        signals.append(f"ℹ️ Патентни заявки: {patent_apps:,.0f}")

    if ai_investment is not None:
        signals.append(f"ℹ️ AI инвестиции: ${ai_investment:.1f}B")

    if not signals:
        signals.append("⚡ Липсват детайлни технологични метрики")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="TECHNOLOGY_AI_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"internet_pct": internet, "rd_pct": rd_spend, "high_tech_pct": high_tech}
    )


def score_food(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.6

    undernourishment = metrics.get("prevalence_undernourishment_pct")
    cereal_yield = metrics.get("cereal_yield_kg_per_ha")
    food_production = metrics.get("food_production_index")
    arable_land = metrics.get("arable_land_per_person_ha")

    if undernourishment is not None:
        if undernourishment > 15:
            score = 0.2
            signals.append(f"⚠️ Недохранване: {undernourishment:.1f}% — критично (SDG цел: <5%)")
        elif undernourishment > 8:
            score = 0.45
            signals.append(f"⚡ Недохранване: {undernourishment:.1f}% — над SDG целта")
        else:
            score = 0.7
            signals.append(f"✅ Недохранване: {undernourishment:.1f}%")
    else:
        signals.append("⚡ Липсват данни за недохранване")

    if cereal_yield is not None:
        if cereal_yield > 4000:
            score += 0.05
            signals.append(f"✅ Зърнен добив: {cereal_yield:.0f} kg/ha")
        elif cereal_yield < 2000:
            score -= 0.1
            signals.append(f"⚠️ Зърнен добив: {cereal_yield:.0f} kg/ha — нисък")
        else:
            signals.append(f"⚡ Зърнен добив: {cereal_yield:.0f} kg/ha")

    if food_production is not None:
        if food_production < 90:
            score -= 0.1
            signals.append(f"⚠️ Индекс на хранително производство: {food_production:.1f} — спад")
        else:
            signals.append(f"✅ Индекс на хранително производство: {food_production:.1f}")

    if arable_land is not None and arable_land < 0.1:
        score -= 0.05
        signals.append(f"⚠️ Обработваема земя: {arable_land:.3f} ha/човек — критично ниска")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="FOOD_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"undernourishment": undernourishment, "cereal_yield": cereal_yield,
                      "food_production": food_production}
    )


def score_water(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    safe_water = metrics.get("access_safe_water_pct")
    sanitation = metrics.get("access_sanitation_pct")
    withdrawal = metrics.get("annual_freshwater_withdrawal_pct")
    rural_water = metrics.get("rural_water_access_pct")

    if safe_water is not None:
        if safe_water > 90:
            score = 0.8
            signals.append(f"✅ Достъп до чиста вода: {safe_water:.1f}%")
        elif safe_water > 70:
            score = 0.55
            signals.append(f"⚡ Достъп до чиста вода: {safe_water:.1f}% — нужен напредък")
        else:
            score = 0.25
            signals.append(f"⚠️ Достъп до чиста вода: {safe_water:.1f}% — критично")
    else:
        signals.append("⚡ Липсват данни за достъп до вода")

    if sanitation is not None:
        if sanitation < 50:
            score -= 0.15
            signals.append(f"⚠️ Санитация: {sanitation:.1f}% — критично ниска")
        elif sanitation < 75:
            score -= 0.05
            signals.append(f"⚡ Санитация: {sanitation:.1f}%")
        else:
            signals.append(f"✅ Санитация: {sanitation:.1f}%")

    if withdrawal is not None and withdrawal > 40:
        score -= 0.15
        signals.append(f"⚠️ Изтегляне на сладка вода: {withdrawal:.1f}% — воден стрес")
    elif withdrawal is not None:
        signals.append(f"✅ Изтегляне на сладка вода: {withdrawal:.1f}% — устойчиво")

    if rural_water is not None and rural_water < 60:
        score -= 0.1
        signals.append(f"⚠️ Селски достъп до вода: {rural_water:.1f}% — нисък")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="WATER_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"safe_water": safe_water, "sanitation": sanitation, "withdrawal": withdrawal}
    )


def score_ecosystems(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    forest = metrics.get("forest_area_pct")
    protected = metrics.get("protected_terrestrial_area_pct")
    marine_protected = metrics.get("marine_protected_area_pct")
    threatened = metrics.get("threatened_species_count")

    if forest is not None:
        if forest > 40:
            score = 0.7
            signals.append(f"✅ Горска площ: {forest:.1f}%")
        elif forest > 25:
            score = 0.5
            signals.append(f"⚡ Горска площ: {forest:.1f}%")
        else:
            score = 0.3
            signals.append(f"⚠️ Горска площ: {forest:.1f}% — ниска")
    else:
        signals.append("⚡ Липсват данни за горска площ")

    if protected is not None:
        if protected > 17:
            score += 0.05
            signals.append(f"✅ Защитени територии: {protected:.1f}% (над Aichi целта 17%)")
        elif protected > 10:
            signals.append(f"⚡ Защитени територии: {protected:.1f}%")
        else:
            score -= 0.05
            signals.append(f"⚠️ Защитени територии: {protected:.1f}% — под 10%")

    if threatened is not None:
        if threatened > 5000:
            score -= 0.2
            signals.append(f"⚠️ Застрашени видове: {threatened:.0f} — критично")
        elif threatened > 2000:
            score -= 0.1
            signals.append(f"⚡ Застрашени видове: {threatened:.0f} — значително")
        else:
            signals.append(f"✅ Застрашени видове: {threatened:.0f}")

    if marine_protected is not None:
        if marine_protected > 10:
            score += 0.05
            signals.append(f"✅ Морски защитени зони: {marine_protected:.1f}%")
        else:
            signals.append(f"⚡ Морски защитени зони: {marine_protected:.1f}%")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="ECOSYSTEMS_BIODIVERSITY_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"forest_pct": forest, "protected_pct": protected, "threatened": threatened}
    )


def score_education(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    literacy = (metrics.get("adult_literacy_rate") or
                metrics.get("literacy_rate_adult_total"))
    enrollment = (metrics.get("school_enrollment_secondary") or
                  metrics.get("school_enrollment_tertiary"))
    edu_exp = (metrics.get("education_expenditure_pct_gdp") or
               metrics.get("govt_expenditure_education_pct"))
    pisa = metrics.get("pisa_score_average")

    if literacy is not None:
        if literacy > 95:
            score = 0.8
            signals.append(f"✅ Грамотност: {literacy:.1f}%")
        elif literacy > 80:
            score = 0.55
            signals.append(f"⚡ Грамотност: {literacy:.1f}%")
        else:
            score = 0.3
            signals.append(f"⚠️ Грамотност: {literacy:.1f}% — ниска")
    else:
        signals.append("⚡ Липсват данни за грамотност")

    if enrollment is not None:
        if enrollment > 80:
            score += 0.05
            signals.append(f"✅ Записване в училище: {enrollment:.1f}%")
        elif enrollment < 50:
            score -= 0.1
            signals.append(f"⚠️ Записване в училище: {enrollment:.1f}% — ниско")
        else:
            signals.append(f"⚡ Записване в училище: {enrollment:.1f}%")

    if edu_exp is not None:
        if edu_exp > 5:
            score += 0.05
            signals.append(f"✅ Разходи за образование: {edu_exp:.1f}% от БВП")
        elif edu_exp < 3:
            score -= 0.1
            signals.append(f"⚠️ Разходи за образование: {edu_exp:.1f}% — недостатъчно")
        else:
            signals.append(f"⚡ Разходи за образование: {edu_exp:.1f}% от БВП")

    if pisa is not None:
        if pisa > 500:
            score += 0.05
            signals.append(f"✅ PISA резултат: {pisa:.0f}")
        elif pisa < 420:
            score -= 0.1
            signals.append(f"⚠️ PISA резултат: {pisa:.0f} — нисък")

    if not signals:
        signals.append("⚡ Липсват данни за образование")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="EDUCATION_CULTURE_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"literacy": literacy, "enrollment": enrollment, "edu_exp": edu_exp}
    )


def score_infrastructure(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    electricity = metrics.get("access_to_electricity_pct")
    internet = (metrics.get("internet_penetration_pct") or
                metrics.get("individuals_internet_pct"))
    logistics = metrics.get("logistics_performance_index")
    urban_pop = metrics.get("urban_population_pct")

    if electricity is not None:
        if electricity > 95:
            score = 0.75
            signals.append(f"✅ Достъп до електричество: {electricity:.1f}%")
        elif electricity > 80:
            score = 0.55
            signals.append(f"⚡ Достъп до електричество: {electricity:.1f}%")
        else:
            score = 0.3
            signals.append(f"⚠️ Достъп до електричество: {electricity:.1f}% — критично")
    else:
        signals.append("⚡ Липсват данни за електричество")

    if internet is not None:
        if internet > 70:
            score += 0.05
            signals.append(f"✅ Интернет: {internet:.1f}%")
        elif internet < 40:
            score -= 0.1
            signals.append(f"⚠️ Интернет: {internet:.1f}% — нисък")
        else:
            signals.append(f"⚡ Интернет: {internet:.1f}%")

    if logistics is not None:
        if logistics > 3.5:
            score += 0.05
            signals.append(f"✅ Логистичен индекс: {logistics:.2f}/5")
        elif logistics < 2.5:
            score -= 0.1
            signals.append(f"⚠️ Логистичен индекс: {logistics:.2f}/5 — слаб")
        else:
            signals.append(f"⚡ Логистичен индекс: {logistics:.2f}/5")

    if urban_pop is not None:
        if urban_pop > 80:
            score += 0.03
            signals.append(f"✅ Урбанизация: {urban_pop:.1f}%")
        elif urban_pop < 40:
            score -= 0.05
            signals.append(f"⚡ Урбанизация: {urban_pop:.1f}% — ниска")

    if not signals:
        signals.append("⚡ Липсват данни за инфраструктура")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="INFRASTRUCTURE_CITIES_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"electricity": electricity, "internet": internet, "logistics": logistics}
    )


def score_materials_waste(metrics: Dict) -> ScoreResult:
    metrics = _unwrap_metrics(metrics)
    signals = []
    score = 0.5

    recycling = metrics.get("recycling_rate_pct")
    waste_per_capita = metrics.get("municipal_waste_per_capita_kg")
    material_footprint = metrics.get("material_footprint_per_capita")
    plastic_waste = metrics.get("plastic_waste_mismanaged_pct")

    if recycling is not None:
        if recycling > 50:
            score = 0.75
            signals.append(f"✅ Рециклиране: {recycling:.1f}%")
        elif recycling > 25:
            score = 0.5
            signals.append(f"⚡ Рециклиране: {recycling:.1f}%")
        else:
            score = 0.25
            signals.append(f"⚠️ Рециклиране: {recycling:.1f}% — ниско")
    else:
        signals.append("⚡ Липсват данни за рециклиране")

    if waste_per_capita is not None:
        if waste_per_capita > 500:
            score -= 0.1
            signals.append(f"⚠️ Отпадъци: {waste_per_capita:.0f} kg/човек — високо потребление")
        else:
            signals.append(f"✅ Отпадъци: {waste_per_capita:.0f} kg/човек")

    if plastic_waste is not None and plastic_waste > 20:
        score -= 0.15
        signals.append(f"⚠️ Неуправляван пластмасов отпадък: {plastic_waste:.1f}%")

    if material_footprint is not None:
        if material_footprint > 20:
            score -= 0.1
            signals.append(f"⚠️ Материален отпечатък: {material_footprint:.1f} тона/човек — висок")
        else:
            signals.append(f"⚡ Материален отпечатък: {material_footprint:.1f} тона/човек")

    if not signals:
        signals.append("⚡ Липсват данни за отпадъци и материали")

    score = max(0.0, min(1.0, score))
    return ScoreResult(
        axis="MATERIALS_WASTE_REVIEW",
        level=_score_to_level(score),
        score=round(score, 2),
        signals=signals,
        metrics_used={"recycling": recycling, "waste_per_capita": waste_per_capita}
    )


def score_generic(axis: str, metrics: Dict, level_hint: str) -> ScoreResult:
    level_map = {"LOW": 0.2, "MEDIUM": 0.5, "HIGH": 0.8}
    score = level_map.get(level_hint, 0.5)
    return ScoreResult(
        axis=axis,
        level=level_hint,
        score=score,
        signals=["⚡ Generic scorer — няма специфични прагове за тази ос"],
        metrics_used={}
    )


# ─────────────────────────────────────────────
# INTER-AXIS CORRELATION
# ─────────────────────────────────────────────

CORRELATION_MATRIX = {
    ("CLIMATE_GLOBAL_RISK_REVIEW", "FOOD_REVIEW"): -0.3,
    ("CLIMATE_GLOBAL_RISK_REVIEW", "WATER_REVIEW"): -0.25,
    ("CLIMATE_GLOBAL_RISK_REVIEW", "HUMAN_WELL_BEING_REVIEW"): -0.2,
    ("ENERGY_REVIEW", "CLIMATE_GLOBAL_RISK_REVIEW"): -0.1,
    ("ENERGY_REVIEW", "ECONOMY_WORK_REVIEW"): 0.15,
    ("INEQUALITY_POVERTY_REVIEW", "HUMAN_WELL_BEING_REVIEW"): -0.3,
    ("GOVERNANCE_INSTITUTIONS_REVIEW", "ECONOMY_WORK_REVIEW"): 0.2,
    ("TECHNOLOGY_AI_REVIEW", "ECONOMY_WORK_REVIEW"): 0.15,
    ("FOOD_REVIEW", "HUMAN_WELL_BEING_REVIEW"): 0.1,
    ("WATER_REVIEW", "HUMAN_WELL_BEING_REVIEW"): 0.1,
    ("ECOSYSTEMS_BIODIVERSITY_REVIEW", "FOOD_REVIEW"): 0.1,
    ("ECOSYSTEMS_BIODIVERSITY_REVIEW", "WATER_REVIEW"): 0.1,
}


def apply_correlations(scores: Dict[str, ScoreResult]) -> Dict[str, ScoreResult]:
    adjustments: Dict[str, float] = {}

    for (axis_a, axis_b), effect in CORRELATION_MATRIX.items():
        if axis_a not in scores or axis_b not in scores:
            continue
        score_a = scores[axis_a].score
        if score_a < 0.4 and effect < 0:
            adjustments[axis_b] = adjustments.get(axis_b, 0) + effect
            scores[axis_b].signals.append(
                f"🔗 Корелация: {axis_a} (score={score_a}) влияе негативно"
            )
        elif score_a > 0.6 and effect > 0:
            adjustments[axis_b] = adjustments.get(axis_b, 0) + effect
            scores[axis_b].signals.append(
                f"🔗 Корелация: {axis_a} (score={score_a}) влияе позитивно"
            )

    for axis, adj in adjustments.items():
        if axis in scores:
            new_score = max(0.0, min(1.0, scores[axis].score + adj))
            scores[axis].score = round(new_score, 2)
            scores[axis].level = _score_to_level(new_score)

    return scores


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _score_to_level(score: float) -> str:
    if score >= 0.65:
        return "HIGH"
    elif score >= 0.35:
        return "MEDIUM"
    else:
        return "LOW"


def _load_snapshot(path: pathlib.Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ─────────────────────────────────────────────
# AXIS SCORERS REGISTRY
# ─────────────────────────────────────────────

AXIS_SCORERS = {
    "CLIMATE_GLOBAL_RISK_REVIEW":      score_climate,
    "ENERGY_REVIEW":                   score_energy,
    "HUMAN_WELL_BEING_REVIEW":         score_human_well_being,
    "ECONOMY_WORK_REVIEW":             score_economy,
    "INEQUALITY_POVERTY_REVIEW":       score_inequality,
    "GOVERNANCE_INSTITUTIONS_REVIEW":  score_governance,
    "TECHNOLOGY_AI_REVIEW":            score_technology_ai,
    "FOOD_REVIEW":                     score_food,
    "WATER_REVIEW":                    score_water,
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":  score_ecosystems,
    "EDUCATION_CULTURE_REVIEW":        score_education,
    "INFRASTRUCTURE_CITIES_REVIEW":    score_infrastructure,
    "MATERIALS_WASTE_REVIEW":          score_materials_waste,
}


def score_all_snapshots() -> Dict[str, ScoreResult]:
    scores: Dict[str, ScoreResult] = {}

    for json_file in sorted(SNAPSHOTS_DIR.rglob("*_snapshot_latest.json")):
        snap = _load_snapshot(json_file)
        if not snap:
            continue

        axis = snap.get("axis", "")
        if not axis:
            continue

        raw = snap.get("raw")
        raw = raw if isinstance(raw, dict) else {}
        metrics = snap.get("metrics") or raw.get("metrics", {}) or {}
        level_hint = snap.get("level", "MEDIUM")

        if axis in AXIS_SCORERS:
            result = AXIS_SCORERS[axis](metrics)
        else:
            result = score_generic(axis, metrics, level_hint)

        scores[axis] = result

    scores = apply_correlations(scores)
    return scores


def print_report(scores: Dict[str, ScoreResult]) -> None:
    level_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}
    print("\n" + "=" * 60)
    print("CORTEX++ SCORING REPORT")
    print("=" * 60)

    by_domain = {
        "PLANET": ["CLIMATE_GLOBAL_RISK_REVIEW", "ENERGY_REVIEW", "FOOD_REVIEW",
                   "WATER_REVIEW", "MATERIALS_WASTE_REVIEW", "ECOSYSTEMS_BIODIVERSITY_REVIEW",
                   "PLANETARY_POTENTIAL_REVIEW"],
        "HUMAN": ["HUMAN_WELL_BEING_REVIEW", "CULTURE_MEDIA_REVIEW",
                  "COGNITION_LEARNING_REVIEW", "SOCIAL_RELATIONS_REVIEW"],
        "CIVILIZATION": ["ECONOMY_WORK_REVIEW", "INEQUALITY_POVERTY_REVIEW",
                         "GOVERNANCE_INSTITUTIONS_REVIEW", "TECHNOLOGY_AI_REVIEW",
                         "EDUCATION_CULTURE_REVIEW", "INFRASTRUCTURE_CITIES_REVIEW"],
        "COSMOS": ["LONG_TERM_FUTURE_REVIEW", "DEEP_TIME_RISKS_REVIEW",
                   "GOAL_PROGRESS_REVIEW", "SPACE_INFRASTRUCTURE_REVIEW",
                   "COSMIC_RESOURCES_REVIEW"],
    }

    for domain, axes in by_domain.items():
        print(f"\n── {domain} ──")
        domain_scores = []
        for axis in axes:
            if axis in scores:
                r = scores[axis]
                icon = level_icon.get(r.level, "⚪")
                print(f"  {icon} {axis:<45} score={r.score:.2f}  [{r.level}]")
                for sig in r.signals[:2]:
                    print(f"       {sig}")
                domain_scores.append(r.score)
        if domain_scores:
            avg = sum(domain_scores) / len(domain_scores)
            print(f"     Domain avg: {avg:.2f}")

    scored = {a for axes in by_domain.values() for a in axes}
    others = [a for a in scores if a not in scored]
    if others:
        print("\n── ДРУГИ ──")
        for axis in others:
            r = scores[axis]
            icon = level_icon.get(r.level, "⚪")
            print(f"  {icon} {axis:<45} score={r.score:.2f}  [{r.level}]")

    all_scores = [r.score for r in scores.values()]
    if all_scores:
        global_avg = sum(all_scores) / len(all_scores)
        level = _score_to_level(global_avg)
        icon = level_icon.get(level, "⚪")
        print(f"\n{icon} GLOBAL CIVILIZATION SCORE: {global_avg:.2f}  [{level}]")

    print("\n" + "=" * 60)


def save_scores(scores: Dict[str, ScoreResult]) -> None:
    out = {
        axis: {
            "level": r.level,
            "score": r.score,
            "signals": r.signals,
            "domain": AXIS_DOMAIN_MAP.get(axis, "UNKNOWN"),
        }
        for axis, r in scores.items()
    }
    out_path = BASE_DIR / "output" / "cortex_scores_latest.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[SCORER] Saved -> {out_path}")


if __name__ == "__main__":
    scores = score_all_snapshots()
    print_report(scores)
    save_scores(scores)