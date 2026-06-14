#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
agents/planet/planet_snapshots_agent_qwen.py

PLANET snapshot агент:
- За всяка PLANET child-ос (CLIMATE, ENERGY, WATER, FOOD, MATERIALS_WASTE, ECOSYSTEMS_BIODIVERSITY)
  генерира JSON snapshot с LEVEL + SIGNALS + KEY_METRICS.
- Пише ./snapshots/planet/<axis_short>/<axis_short>_snapshot_latest.json
- planetary_potential_review_agent_qwen ги чете и интегрира.

Режими:
- REAL_DATA: за CLIMATE, WATER, FOOD, MATERIALS_WASTE, ECOSYSTEMS_BIODIVERSITY
  използва реални/placeholder провайдъри през data_providers.
- LLM_FALLBACK: за останалите оси използва QWEN LLM, както досега,
  с изключение на ENERGY_REVIEW, който тук се пропуска и се обслужва от ENERGY агента.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from core.llm_backend import call_internal_llm
from data_providers.planet.climate_global_risk_review_provider import (
    ClimateGlobalRiskReviewProvider,
    ClimateConfig,
)
from data_providers.planet.water_review_provider import WaterProvider
from data_providers.planet.food_review_provider import FoodProvider
from data_providers.planet.ecosystems_biodiversity_review_provider import (
    BiodiversityProvider,
)
from data_providers.planet.materials_waste_review_provider import (
    MaterialsWasteReviewProvider,
)
from data_providers.planet.energy_review_provider import EnergyReviewProvider
from data_providers.planet.planetary_potential_provider import PlanetaryPotentialProvider
from data_providers.planet.planet_normalization import (
    normalize_climate,
    normalize_water,
    normalize_food,
    normalize_biodiversity,
    normalize_materials_waste,
)


ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_ROOT = ROOT / "snapshots" / "planet"
SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)

# Флаг за реални данни – CLIMATE + WATER + FOOD + MATERIALS_WASTE + ECOSYSTEMS_BIODIVERSITY
# имат реални/placeholder провайдъри
USE_REAL_DATA_PLANET_SNAPSHOTS = True


AXIS_CONFIG = {
    "CLIMATE_GLOBAL_RISK_REVIEW": {
        "short": "climate_global_risk",
        "label": "Глобален климатичен риск",
    },
    "ENERGY_REVIEW": {
        "short": "energy",
        "label": "Енергийна система",
    },
    "WATER_REVIEW": {
        "short": "water",
        "label": "Водни ресурси",
    },
    "FOOD_REVIEW": {
        "short": "food",
        "label": "Храна и продоволствена сигурност",
    },
    "MATERIALS_WASTE_REVIEW": {
        "short": "materials_waste",
        "label": "Материали и отпадъци",
    },
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": {
        "short": "ecosystems_biodiversity",
        "label": "Екосистеми и биоразнообразие",
    },
    "PLANETARY_POTENTIAL_REVIEW": {
        "short": "planetary_potential",
        "label": "Планетарен потенциал",
    },
}


BASE_PROMPT = """
Ти си QWEN_PLANET_SNAPSHOT_AGENT, част от CORTEX++_QWEN.

ЗАДАЧА:
  - Генерираш КОМПАКТЕН JSON snapshot за една ос.
  - Отговаряш САМО с един валиден JSON обект, БЕЗ никакъв текст преди или след него.
  - НЕ използвай префикси като "Thinking..." или "done thinking.".
  - LEVEL трябва да е LOW, MEDIUM или HIGH.
  - SIGNALS са 3–5 много кратки bullets (по 1 изречение).
  - KEY_METRICS са 3–7 метрики с име и кратко текстово описание (без числа).

ОС:
  - {axis} ({label})

ИЗХОД (примерен формат, който трябва да спазиш):

{{
  "axis": "{axis}",
  "level": "MEDIUM",
  "signals": [
    "кратък сигнал 1",
    "кратък сигнал 2",
    "кратък сигнал 3"
  ],
  "key_metrics": [
    {{ "name": "metric_1", "description": "кратко текстово описание на метриката" }},
    {{ "name": "metric_2", "description": "кратко текстово описание" }}
  ]
}}

Върни само реален JSON обект в този формат, без допълнителен текст.
IMPORTANT: Respond ONLY in English. All text values must be in English.
"""


def strip_thinking(raw: str) -> str:
    if not raw:
        return raw
    if "Thinking..." in raw:
        _, tail = raw.split("Thinking...", 1)
        raw = tail
    if "...done thinking." in raw:
        head, _ = raw.split("...done thinking.", 1)
        raw = head
    return raw.strip()


def parse_axis_json(raw: str) -> Dict[str, Any]:
    """
    По-брутален парсер:
    - чисти "Thinking..." boilerplate;
    - намира първия '{';
    - върви от последната '}' назад, докато успее да парсне валиден JSON обект.
    Това позволява да игнорираме текст преди/след JSON-а.
    """
    raw = strip_thinking(raw)
    raw = raw.strip()

    start = raw.find("{")
    if start == -1:
        raise ValueError("LLM output does not contain '{'")

    last = raw.rfind("}")
    if last == -1 or last <= start:
        raise ValueError("LLM output does not contain '}' after '{'")

    for end in range(last, start, -1):
        try:
            json_str = raw[start : end + 1]
            data = json.loads(json_str)
            if isinstance(data, dict):
                return data
        except Exception:
            continue

    raise ValueError("LLM output is not a valid JSON object")


def ensure_axis_dir(short: str) -> Path:
    axis_dir = SNAPSHOT_ROOT / short
    axis_dir.mkdir(parents=True, exist_ok=True)
    return axis_dir


def write_axis_snapshot(axis: str, short: str, payload: Dict[str, Any]) -> Path:
    axis_dir = ensure_axis_dir(short)
    out_path = axis_dir / f"{short}_snapshot_latest.json"

    now = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "axis": axis,
        "timestamp": now,
        "level": payload.get("level", "MEDIUM"),
        "signals": payload.get("signals", []),
        "key_metrics": payload.get("key_metrics", []),
        "model": payload.get("model", "QWEN_PLANET_SNAPSHOT_AGENT"),
        "source_type": payload.get("source_type", "LLM"),
        "metrics": payload.get("metrics", payload.get("raw", {}).get("metrics", {})),
        "data_quality": payload.get("data_quality", payload.get("raw", {}).get("data_quality", "")),
        "fetched_date": payload.get("fetched_date", payload.get("raw", {}).get("fetched_date", "")),
    }

    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[PLANET_SNAPSHOT] wrote {axis} -> {out_path}")
    return out_path


def generate_axis_snapshot_llm(axis: str, cfg: Dict[str, Any]) -> None:
    short = cfg["short"]
    label = cfg["label"]

    prompt = BASE_PROMPT.format(axis=axis, label=label)

    print(f"[PLANET_SNAPSHOT] generating snapshot via LLM for {axis} ({short})...")
    try:
        raw = call_internal_llm(prompt)
    except Exception as e:
        print(f"[PLANET_SNAPSHOT][ERROR] LLM call failed for {axis}: {e}")
        return

    try:
        obj = parse_axis_json(raw)
    except Exception as e:
        print(f"[PLANET_SNAPSHOT][ERROR] cannot parse JSON for {axis}: {e}")
        print("RAW LLM OUTPUT (truncated):")
        print(raw[:1200])
        return

    obj["axis"] = axis
    write_axis_snapshot(axis, short, obj)


def generate_axis_snapshot_real(axis: str, cfg: Dict[str, Any]) -> None:
    short = cfg["short"]

    if axis == "CLIMATE_GLOBAL_RISK_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating REAL-DATA snapshot for {axis} ({short})...")

        climate_cfg = ClimateConfig(
            latitude=42.7,
            longitude=23.3,
            country_code="BG",
            openweather_api_key="",  # ако добавиш ключ, OWM ще се активира
        )
        provider = ClimateGlobalRiskReviewProvider(climate_cfg)

        try:
            raw = provider.fetch()
        except Exception as e:
            print(f"[PLANET_SNAPSHOT][ERROR] real-data fetch failed for {axis}: {e}")
            return

        payload = normalize_climate(raw)
        payload["model"] = "CLIMATE_GLOBAL_RISK_MULTI_REAL_DATA"
        # Инжектирай NOAA CO2 метрики директно
        from data_providers.planet.climate_global_risk_review_provider import fetch_noaa_co2
        noaa = fetch_noaa_co2()
        if noaa:
            if "metrics" not in payload:
                payload["metrics"] = {}
            payload["metrics"].update(noaa)
            payload["data_quality"] = "REAL_NOAA"
        write_axis_snapshot(axis, short, payload)
        return

    if axis == "ENERGY_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating REAL-DATA snapshot for {axis} ({short})...")
        try:
            provider = EnergyReviewProvider()
            raw = provider.fetch()
            payload = {"axis": axis, "source_type": "REAL_DATA", "metrics": raw.get("metrics", {}), "data_quality": raw.get("data_quality", ""), "fetched_date": raw.get("fetched_date", "")}
            write_axis_snapshot(axis, short, payload)
        except Exception as e:
            print(f"[PLANET_SNAPSHOT][ERROR] real-data fetch failed for {axis}: {e}")
        return
    if axis == "PLANETARY_POTENTIAL_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating LLM composite snapshot for {axis}...")
        from core.llm_backend import call_internal_llm
        prompt = "You are CORTEX++ AGI. Generate a JSON snapshot for PLANETARY_POTENTIAL_REVIEW — the integrated carrying capacity of Earth. Include: current_level (LOW/MEDIUM/HIGH), key_signals list, main_bottlenecks list, trends list. Return ONLY valid JSON."
        try:
            raw = call_internal_llm(prompt)
            import json as _json
            if "```json" in raw: raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw: raw = raw.split("```")[1].split("```")[0].strip()
            if "</think>" in raw: raw = raw.split("</think>")[-1].strip()
            payload = _json.loads(raw)
        except Exception as e:
            payload = {"error": str(e)}
        payload["source_type"] = "LLM_COMPOSITE"
        write_axis_snapshot(axis, short, payload)
        return
    if axis == "WATER_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating REAL-DATA snapshot for {axis} ({short})...")
        provider = WaterProvider()
        try:
            raw = provider.fetch()
        except Exception as e:
            print(f"[PLANET_SNAPSHOT][ERROR] real-data fetch failed for {axis}: {e}")
            return

        payload = {"source_type": "REAL_DATA", "metrics": raw.get("metrics", {}), "data_quality": raw.get("data_quality", ""), "fetched_date": raw.get("fetched_date", ""), "model": "WORLD_BANK_API"}
        write_axis_snapshot(axis, short, payload)
        return

    if axis == "FOOD_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating REAL-DATA snapshot for {axis} ({short})...")
        provider = FoodProvider()
        try:
            raw = provider.fetch()
        except Exception as e:
            print(f"[PLANET_SNAPSHOT][ERROR] real-data fetch failed for {axis}: {e}")
            return

        payload = {"source_type": "REAL_DATA", "metrics": raw.get("metrics", {}), "data_quality": raw.get("data_quality", ""), "fetched_date": raw.get("fetched_date", ""), "model": "WORLD_BANK_API"}
        write_axis_snapshot(axis, short, payload)
        return

    if axis == "MATERIALS_WASTE_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating REAL-DATA snapshot for {axis} ({short})...")
        provider = MaterialsWasteReviewProvider()
        try:
            raw = provider.fetch()
        except Exception as e:
            print(f"[PLANET_SNAPSHOT][ERROR] real-data fetch failed for {axis}: {e}")
            return

        payload = {"source_type": "REAL_DATA", "metrics": raw.get("metrics", {}), "data_quality": raw.get("data_quality", ""), "fetched_date": raw.get("fetched_date", ""), "model": "WORLD_BANK_API"}
        write_axis_snapshot(axis, short, payload)
        return

    if axis == "ECOSYSTEMS_BIODIVERSITY_REVIEW":
        print(f"[PLANET_SNAPSHOT] generating REAL-DATA snapshot for {axis} ({short})...")
        provider = BiodiversityProvider()
        try:
            raw = provider.fetch()
        except Exception as e:
            print(f"[PLANET_SNAPSHOT][ERROR] real-data fetch failed for {axis}: {e}")
            return

        payload = {"source_type": "REAL_DATA", "metrics": raw.get("metrics", {}), "data_quality": raw.get("data_quality", ""), "fetched_date": raw.get("fetched_date", ""), "model": "WORLD_BANK_API"}
        write_axis_snapshot(axis, short, payload)
        return

    generate_axis_snapshot_llm(axis, cfg)


def main() -> None:
    print("[PLANET_SNAPSHOT] generating PLANET axis snapshots (REAL_DATA + LLM fallback)...")

    for axis, cfg in AXIS_CONFIG.items():

        if USE_REAL_DATA_PLANET_SNAPSHOTS:
            generate_axis_snapshot_real(axis, cfg)
        else:
            generate_axis_snapshot_llm(axis, cfg)

    print("[PLANET_SNAPSHOT] done.")


if __name__ == "__main__":
    main()
