#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data_providers/planet/planet_normalization.py

Нормализира сурови REAL данни към PLANET snapshot payload формат.
Засега имплементираме:
- CLIMATE
- WATER
- FOOD
- ECOSYSTEMS_BIODIVERSITY
- MATERIALS_WASTE
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _safe_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    value = d.get(key, default)
    return value if value is not None else default


# ---------- CLIMATE ----------


def _num(metrics: Dict[str, Any], key: str) -> Optional[float]:
    """Return metrics[key] only if it is a real number, else None.

    Missing/non-numeric MUST map to None (unknown), never to 0.0 — a silent 0.0
    default is exactly the bug that let this axis publish LOW risk over CO₂ 428.
    """
    v = metrics.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize_climate(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализира сурови климатични данни към snapshot payload:

    {
      "level": "LOW|MEDIUM|HIGH|UNKNOWN",   # RISK level (HIGH = high climate risk)
      "risk_score": float,
      "signals": [ ... ],
      "key_metrics": [ { "name": ..., "description": ... }, ... ]
    }

    Rebuilt 2026-07-21: the previous version scored risk from three keys the
    provider never emits (`temperature_trend`, `extreme_days_share`,
    `precipitation_change`), so risk_score was always 0.0 → always LOW, while the
    real, alarming CO₂ readings rode along unused. This version scores from the
    keys the provider actually emits (see climate_global_risk_review_provider.py),
    led by the CO₂ concentration, which is the globally-valid signal.
    """

    metrics = _safe_get(raw, "metrics", {})

    # Keys the provider ACTUALLY emits (verified against fetch()):
    #   co2_ppm_current / co2_annual_increase / co2_annual_mean  — NOAA Mauna Loa (global)
    #   forecast_max_temp_7d                                     — Open-Meteo 7-day (LOCAL)
    #   archive_precipitation_variability                        — Open-Meteo reanalysis (LOCAL)
    #   temperature_trend / extreme_days_share                   — Open-Meteo climate (optional, LOCAL)
    co2        = _num(metrics, "co2_ppm_current")
    if co2 is None:
        co2 = _num(metrics, "co2_annual_mean")
    co2_incr   = _num(metrics, "co2_annual_increase")
    max_temp   = _num(metrics, "forecast_max_temp_7d")
    precip_var = _num(metrics, "archive_precipitation_variability")
    temp_trend = _num(metrics, "temperature_trend")
    extreme    = _num(metrics, "extreme_days_share")

    risk_score = 0.0
    have_real = False
    signals: List[str] = []

    # --- CO₂ concentration: dominant, globally-valid risk signal ---------------
    # Reference thresholds: pre-industrial ≈ 280 ppm; planetary boundary 350 ppm
    # (Rockström 2009 / Hansen 2008); 400 ppm crossed in 2015; ~450 ppm ≈ the
    # +2 °C commitment level. With +1.19 °C already on record, >425 ppm rising is
    # NOT a low-risk state.
    if co2 is not None:
        have_real = True
        if co2 >= 450:
            risk_score += 3.0
            signals.append(f"CO₂ {co2:.1f} ppm — при/над прага за +2 °C (~450 ppm). Критичен риск.")
        elif co2 >= 425:
            risk_score += 2.0
            signals.append(f"CO₂ {co2:.1f} ppm — далеч над безопасната граница (350 ppm) и над 400 ppm.")
        elif co2 >= 400:
            risk_score += 1.5
            signals.append(f"CO₂ {co2:.1f} ppm — над 400 ppm и над планетарната граница от 350 ppm.")
        elif co2 >= 350:
            risk_score += 1.0
            signals.append(f"CO₂ {co2:.1f} ppm — над безопасната граница от 350 ppm.")
        else:
            signals.append(f"CO₂ {co2:.1f} ppm — под планетарната граница от 350 ppm.")
    else:
        signals.append("CO₂ данни липсват — климатичният риск НЕ се приема за нисък (неопределен).")

    # --- Is CO₂ still rising? direction matters --------------------------------
    if co2_incr is not None:
        have_real = True
        if co2_incr >= 2.0:
            risk_score += 1.0
            signals.append(f"CO₂ нараства бързо: +{co2_incr:.2f} ppm спрямо преди година.")
        elif co2_incr > 0:
            risk_score += 0.5
            signals.append(f"CO₂ продължава да нараства: +{co2_incr:.2f} ppm спрямо преди година.")
        else:
            signals.append(f"CO₂ не нараства спрямо предходната година ({co2_incr:+.2f} ppm).")

    # --- Short-term forecast heat (LOCAL — secondary) --------------------------
    if max_temp is not None:
        have_real = True
        if max_temp >= 40:
            risk_score += 1.0
            signals.append(f"7-дневна прогноза: екстремна горещина до {max_temp:.1f} °C.")
        elif max_temp >= 35:
            risk_score += 0.5
            signals.append(f"7-дневна прогноза: висока горещина до {max_temp:.1f} °C.")

    # --- Precipitation variability (instability) -------------------------------
    if precip_var is not None:
        have_real = True
        if precip_var >= 2.0:
            risk_score += 0.5
            signals.append(f"Висока изменчивост на валежите (σ/μ = {precip_var:.2f}).")
        elif precip_var >= 1.0:
            risk_score += 0.25

    # --- Optional long-term local warming trend --------------------------------
    if temp_trend is not None and abs(temp_trend) > 0.05:
        have_real = True
        if temp_trend > 0:
            risk_score += 0.5
            signals.append("Дългосрочните средни температури показват възходящ тренд.")
    if extreme is not None and extreme > 0.05:
        have_real = True
        risk_score += 0.5
        signals.append("Делът на дните с екстремни температури нараства.")

    # --- Level from risk_score (RISK polarity: HIGH = high risk) ---------------
    if not have_real:
        level = "UNKNOWN"
    elif risk_score >= 2.5:
        level = "HIGH"
    elif risk_score >= 1.0:
        level = "MEDIUM"
    else:
        level = "LOW"

    key_metrics: List[Dict[str, str]] = [
        {"name": "co2_ppm_current",
         "description": "Текуща концентрация на CO₂ (NOAA Mauna Loa), ppm — водещ глобален сигнал."},
        {"name": "co2_annual_increase",
         "description": "Годишен ръст на CO₂ спрямо преди година, ppm."},
        {"name": "forecast_max_temp_7d",
         "description": "Максимална прогнозна температура за 7 дни (локален сигнал), °C."},
        {"name": "archive_precipitation_variability",
         "description": "Изменчивост на валежите (σ/μ) от реанализ (локален сигнал)."},
        {"name": "climate_risk_score",
         "description": "Обобщен индикатор за климатичен риск, комбиниращ горните фактори (по-високо = по-голям риск)."},
    ]

    # Pass real metrics through, and PERSIST the computed score so it is no longer
    # an empty placeholder that only ever existed as a description.
    out_metrics = dict(_safe_get(raw, "metrics", {}))
    out_metrics["climate_risk_score"] = round(risk_score, 2)

    return {
        "level": level,
        "risk_score": round(risk_score, 2),
        "signals": signals,
        "key_metrics": key_metrics,
        "metrics": out_metrics,
        "source_type": "REAL_DATA" if have_real else "NO_REAL_DATA",
        "data_quality": _safe_get(raw, "data_mode", "REAL_FROM_APPROVED_SOURCE"),
        "fetched_date": _safe_get(raw, "fetched_at", ""),
    }


# ---------- WATER ----------


def normalize_water(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Очакван суров формат от water провайдъра:

    {
      "metrics": {
        "water_quality_index": float,
        "water_stress_index": float,
        "trend_quality": float,   # -1..1
        "trend_availability": float  # -1..1
      }
    }
    """

    metrics = _safe_get(raw, "metrics", {})
    quality = _safe_get(metrics, "water_quality_index", 0.5)
    stress = _safe_get(metrics, "water_stress_index", 0.5)
    trend_quality = _safe_get(metrics, "trend_quality", 0.0)
    trend_availability = _safe_get(metrics, "trend_availability", 0.0)

    # Ниско качество + висок стрес + негативни трендове => по-висок риск
    risk_score = 0.0
    risk_score += (1.0 - quality)
    risk_score += stress
    risk_score += max(0.0, -trend_quality) * 0.5
    risk_score += max(0.0, -trend_availability) * 0.5

    if risk_score < 1.0:
        level = "LOW"
    elif risk_score < 2.0:
        level = "MEDIUM"
    else:
        level = "HIGH"

    signals: List[str] = []

    if quality >= 0.7:
        signals.append("Качеството на водните ресурси е относително добро.")
    elif quality >= 0.4:
        signals.append("Качеството на водните ресурси е смесено и изисква внимание.")
    else:
        signals.append("Качеството на водните ресурси е влошено и буди притеснение.")

    if stress >= 0.7:
        signals.append("Водният стрес е силно изразен в разглеждания регион.")
    elif stress >= 0.4:
        signals.append("Водният стрес е умерен и варира по сезони.")
    else:
        signals.append("Водният стрес остава в ниски граници.")

    if trend_quality > 0.05:
        signals.append("Има признаци за подобрение в качеството на водите.")
    elif trend_quality < -0.05:
        signals.append("Наблюдава се тенденция към влошаване на качеството на водите.")
    else:
        signals.append("Няма ясно изразен тренд в качеството на водите.")

    key_metrics: List[Dict[str, str]] = [
        {
            "name": "water_quality_index",
            "description": "Композитен индекс за качеството на повърхностни и подземни води.",
        },
        {
            "name": "water_stress_index",
            "description": "Индекс за натиск върху водните ресурси спрямо наличните количества.",
        },
        {
            "name": "trend_quality",
            "description": "Насока на дългосрочния тренд в качеството на водите.",
        },
        {
            "name": "trend_availability",
            "description": "Насока на тренда в наличността на водни ресурси.",
        },
    ]

    return {
        "level": level,
        "signals": signals,
        "key_metrics": key_metrics,
    }


# ---------- FOOD ----------


def normalize_food(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Очакван суров формат от food провайдъра (FAO):

    {
      "metrics": {
        "undernourishment_rate": float,
        "food_insecurity_index": float,
        "diet_diversity_index": float,
        "trend_food_insecurity": float  # -1..1
      }
    }
    """

    metrics = _safe_get(raw, "metrics", {})
    undernourishment = _safe_get(metrics, "undernourishment_rate", 0.0)
    food_insec = _safe_get(metrics, "food_insecurity_index", 0.0)
    diet_diversity = _safe_get(metrics, "diet_diversity_index", 0.5)
    trend_food_insec = _safe_get(metrics, "trend_food_insecurity", 0.0)

    risk_score = 0.0
    risk_score += undernourishment * 2.0
    risk_score += food_insec * 1.5
    risk_score += max(0.0, -diet_diversity)
    risk_score += max(0.0, trend_food_insec) * 0.5

    if risk_score < 1.0:
        level = "LOW"
    elif risk_score < 2.0:
        level = "MEDIUM"
    else:
        level = "HIGH"

    signals: List[str] = []

    if undernourishment < 0.05:
        signals.append("Делът на недохраненото население е в ниски граници.")
    elif undernourishment < 0.15:
        signals.append("Недохранването остава значим проблем за част от населението.")
    else:
        signals.append("Недохранването засяга голяма част от населението и е критичен проблем.")

    if food_insec < 0.3:
        signals.append("Хранителната несигурност е ограничена, но не изчезнала.")
    elif food_insec < 0.6:
        signals.append("Хранителната несигурност е широко разпространена.")
    else:
        signals.append("Хранителната несигурност е силно изразена и системна.")

    if diet_diversity >= 0.7:
        signals.append("Разнообразието на хранителния режим е относително добро.")
    else:
        signals.append("Разнообразието на хранителния режим е ограничено.")

    if trend_food_insec > 0.05:
        signals.append("Има признаци за нарастване на хранителната несигурност.")
    elif trend_food_insec < -0.05:
        signals.append("Има признаци за намаляване на хранителната несигурност.")
    else:
        signals.append("Хранителната несигурност не показва ясно изразен тренд.")

    key_metrics: List[Dict[str, str]] = [
        {
            "name": "undernourishment_rate",
            "description": "Относителен дял на населението в състояние на недохранване.",
        },
        {
            "name": "food_insecurity_index",
            "description": "Индекс за степента на хранителна несигурност в популацията.",
        },
        {
            "name": "diet_diversity_index",
            "description": "Индекс за разнообразието на хранителния режим.",
        },
        {
            "name": "trend_food_insecurity",
            "description": "Насока на дългосрочния тренд в хранителната несигурност.",
        },
    ]

    return {
        "level": level,
        "signals": signals,
        "key_metrics": key_metrics,
    }


# ---------- ECOSYSTEMS & BIODIVERSITY ----------


def normalize_biodiversity(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Очакван суров формат от biodiversity провайдъра (GBIF):

    {
      "metrics": {
        "species_richness_index": float,
        "observations_trend": float,    # -1..1
        "threatened_species_share": float,
        "habitat_fragmentation_index": float
      }
    }
    """

    metrics = _safe_get(raw, "metrics", {})
    richness = _safe_get(metrics, "species_richness_index", 0.5)
    obs_trend = _safe_get(metrics, "observations_trend", 0.0)
    threatened_share = _safe_get(metrics, "threatened_species_share", 0.0)
    fragmentation = _safe_get(metrics, "habitat_fragmentation_index", 0.5)

    risk_score = 0.0
    risk_score += max(0.0, -richness)
    risk_score += threatened_share * 2.0
    risk_score += fragmentation
    risk_score += max(0.0, -obs_trend) * 0.5

    if risk_score < 1.0:
        level = "LOW"
    elif risk_score < 2.0:
        level = "MEDIUM"
    else:
        level = "HIGH"

    signals: List[str] = []

    if richness >= 0.7:
        signals.append("Нивото на биоразнообразие е относително високо.")
    elif richness >= 0.4:
        signals.append("Биоразнообразието е средно и показва признаци на напрежение.")
    else:
        signals.append("Биоразнообразието е значително намалено.")

    if threatened_share > 0.3:
        signals.append("Голям дял от видовете в региона са застрашени.")
    elif threatened_share > 0.1:
        signals.append("Застрашените видове формират значим дял от биоразнообразието.")
    else:
        signals.append("Застрашените видове са относително малка част от биоразнообразието.")

    if fragmentation > 0.6:
        signals.append("Хабитатите са силно фрагментирани и изолирани.")
    elif fragmentation > 0.3:
        signals.append("Хабитатите са умерено фрагментирани.")
    else:
        signals.append("Фрагментацията на хабитатите е ограничена.")

    if obs_trend > 0.05:
        signals.append("Наблюдава се увеличение в записите за биоразнообразие.")
    elif obs_trend < -0.05:
        signals.append("Наблюдава се спад в записите за биоразнообразие.")
    else:
        signals.append("Няма ясно изразен тренд в записите за биоразнообразие.")

    key_metrics: List[Dict[str, str]] = [
        {
            "name": "species_richness_index",
            "description": "Индекс за относителното богатство на видовете в региона.",
        },
        {
            "name": "threatened_species_share",
            "description": "Дял на видовете в застрашени категории спрямо всички наблюдавани видове.",
        },
        {
            "name": "habitat_fragmentation_index",
            "description": "Индекс за степента на фрагментация на местообитанията.",
        },
        {
            "name": "observations_trend",
            "description": "Насока на тренда в наблюденията на видове във времето.",
        },
    ]

    return {
        "level": level,
        "signals": signals,
        "key_metrics": key_metrics,
    }


# ---------- MATERIALS & WASTE ----------


def normalize_materials_waste(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализира сурови данни за MATERIALS_WASTE_REVIEW
    до LEVEL / SIGNALS / KEY_METRICS.
    Очакваме формат, съвместим с materials_waste_review_provider:
    {
      "global_material_footprint_t_per_capita": float,
      "global_municipal_waste_kg_per_capita": float,
      "recycling_rate_percent": float,
      "e_waste_kg_per_capita": float,
    }
    """

    mf = raw.get("global_material_footprint_t_per_capita")
    mw = raw.get("global_municipal_waste_kg_per_capita")
    rr = raw.get("recycling_rate_percent")
    ew = raw.get("e_waste_kg_per_capita")

    def scale_inverse(x, low, high):
        if x is None:
            return None
        x = max(low, min(high, x))
        return 1.0 - (x - low) / (high - low)

    def scale_direct(x, low, high):
        if x is None:
            return None
        x = max(low, min(high, x))
        return (x - low) / (high - low)

    score_materials = scale_inverse(mf, 5, 25)
    score_waste = scale_inverse(mw, 300, 900)
    score_recycling = scale_direct(rr, 10, 70)
    score_ewaste = scale_inverse(ew, 3, 15)

    scores = [s for s in [score_materials, score_waste, score_recycling, score_ewaste] if s is not None]
    level_score = sum(scores) / len(scores) if scores else 0.0

    if level_score >= 0.66:
        level = "LOW"
    elif level_score >= 0.33:
        level = "MEDIUM"
    else:
        level = "HIGH"

    signals: List[str] = []

    if mf is not None:
        if mf > 20:
            signals.append("Материалният отпечатък на човек е много висок.")
        elif mf > 10:
            signals.append("Материалният отпечатък на човек е умерен към висок.")
        else:
            signals.append("Материалният отпечатък на човек е в по-ниски граници.")

    if mw is not None:
        if mw > 700:
            signals.append("Генерира се голямо количество битови отпадъци на човек.")
        elif mw > 400:
            signals.append("Количеството битови отпадъци е умерено.")
        else:
            signals.append("Количеството битови отпадъци на човек е относително ниско.")

    if rr is not None:
        if rr > 50:
            signals.append("Степента на рециклиране на материалите е относително висока.")
        elif rr > 25:
            signals.append("Степента на рециклиране е умерена, с потенциал за подобрение.")
        else:
            signals.append("Рециклирането на материали е с нисък дял и изисква значителни подобрения.")

    if ew is not None:
        if ew > 10:
            signals.append("Генерира се голямо количество електронни отпадъци на човек.")
        elif ew > 5:
            signals.append("Електронните отпадъци на човек са в умерени граници.")
        else:
            signals.append("Електронните отпадъци на човек са в относително ниски граници.")

    key_metrics: List[Dict[str, str]] = [
        {
            "name": "global_material_footprint_t_per_capita",
            "description": "Тонове материали, използвани на човек годишно.",
        },
        {
            "name": "global_municipal_waste_kg_per_capita",
            "description": "Килограми общински битови отпадъци на човек годишно.",
        },
        {
            "name": "recycling_rate_percent",
            "description": "Процент от генерираните отпадъци, които се рециклират.",
        },
        {
            "name": "e_waste_kg_per_capita",
            "description": "Килограми електронни отпадъци на човек годишно.",
        },
    ]

    return {
        "level": level,
        "signals": signals,
        "key_metrics": key_metrics,
    }
