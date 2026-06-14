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

from typing import Any, Dict, List


def _safe_get(d: Dict[str, Any], key: str, default: Any = None) -> Any:
    value = d.get(key, default)
    return value if value is not None else default


# ---------- CLIMATE ----------


def normalize_climate(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализира сурови климатични данни към snapshot payload:

    {
      "level": "LOW|MEDIUM|HIGH",
      "signals": [ ... ],
      "key_metrics": [ { "name": ..., "description": ... }, ... ]
    }
    """

    metrics = _safe_get(raw, "metrics", {})
    temp_trend = _safe_get(metrics, "temperature_trend", 0.0)
    extreme_days_share = _safe_get(metrics, "extreme_days_share", 0.0)
    precip_change = _safe_get(metrics, "precipitation_change", 0.0)

    # Много опростена логика за MVP
    risk_score = 0.0
    risk_score += abs(temp_trend)
    risk_score += extreme_days_share * 2.0
    risk_score += abs(precip_change) * 0.5

    if risk_score < 0.5:
        level = "LOW"
    elif risk_score < 1.5:
        level = "MEDIUM"
    else:
        level = "HIGH"

    signals: List[str] = []

    if abs(temp_trend) > 0.05:
        if temp_trend > 0:
            signals.append("Средните температури показват стабилен възходящ тренд.")
        else:
            signals.append("Средните температури показват лек низходящ тренд.")
    else:
        signals.append("Средните температури остават относително стабилни във времето.")

    if extreme_days_share > 0.05:
        signals.append("Делът на дните с екстремни температури се увеличава.")
    else:
        signals.append("Делът на дните с екстремни температури остава нисък.")

    if abs(precip_change) > 0.05:
        if precip_change > 0:
            signals.append("Наблюдава се тенденция към по-високи валежи.")
        else:
            signals.append("Наблюдава се тенденция към по-ниски валежи.")
    else:
        signals.append("Валежите остават без ясно изразен тренд.")

    key_metrics: List[Dict[str, str]] = [
        {
            "name": "temperature_trend",
            "description": "Дългосрочен тренд на средните температури според климатичните модели.",
        },
        {
            "name": "extreme_temperature_days_share",
            "description": "Относителен дял на дните с екстремни температурни стойности.",
        },
        {
            "name": "precipitation_change",
            "description": "Промяна във валежите спрямо дългосрочната база.",
        },
        {
            "name": "climate_risk_score",
            "description": "Обобщен индикатор за климатичен риск, комбиниращ няколко климатични фактори.",
        },
    ]

    # Прехвърли всички реални метрики от raw["metrics"]
    raw_metrics = _safe_get(raw, "metrics", {})

    return {
        "level": level,
        "signals": signals,
        "key_metrics": key_metrics,
        "metrics": raw_metrics,
        "source_type": "REAL_DATA",
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
