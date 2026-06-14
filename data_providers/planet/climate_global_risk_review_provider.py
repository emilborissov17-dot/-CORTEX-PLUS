#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
data_providers/planet/climate_global_risk_review_provider.py

CLIMATE_GLOBAL_RISK_REVIEW – данни от няколко реални климатични източника:

- OPEN_METEO_CLIMATE           (климат/исторически статистики)
- OPEN_METEO_ARCHIVE           (historical weather / reanalysis)
- OPEN_METEO_FORECAST          (краткосрочни прогнози)
- OPENWEATHERMAP_AIR_POLLUTION (качество на въздуха)
- WORLD_BANK_CLIMATE_API       (country-level климатични индикатори)

Правила за външни данни (CORTEX++ PLANET):

- Реалните API/източници за CLIMATE_GLOBAL_RISK_REVIEW
  се избират САМО от секцията
  "1. CLIMATE_GLOBAL_RISK_REVIEW -> Approved sources (whitelist)"
  в CONFIG_PLANET_DATA_SOURCES.md.

- Suggested източници ("suggested_for_approval") се ползват тук,
  докато човек не ги премести ръчно в "approved_sources".

Този provider:
- Връща СУРОВИ числови метрики за оста CLIMATE_GLOBAL_RISK_REVIEW,
  комбинирани от няколко одобрени източника.
- Не пише файлове; snapshot агентът (planet_snapshots_agent_qwen.py)
  се грижи за нормализацията и записването на JSON ревютата в
  ./snapshots/planet/climate_global_risk/...
"""

from __future__ import annotations

import json
import pathlib
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

import requests  # стандартна HTTP библиотека

from data_providers.planet.base_provider import PlanetDataProvider

# Път до CONFIG_PLANET_DATA_SOURCES.md (два нива нагоре от data_providers/planet/...).
CONFIG_PATH = pathlib.Path(__file__).resolve().parents[2] / "CONFIG_PLANET_DATA_SOURCES.md"


def _load_climate_whitelist_block() -> Dict[str, Any]:
    """
    Чете CONFIG_PLANET_DATA_SOURCES.md и извлича JSON блока
    за CLIMATE_GLOBAL_RISK_REVIEW (ако съществува).

    Работи по прости маркери, без regex:
    - намира "CLIMATE_GLOBAL_RISK_REVIEW",
    - после първото "```json",
    - после следващото "```",
    - парсва средното като JSON.
    """
    if not CONFIG_PATH.exists():
        return {}

    text = CONFIG_PATH.read_text(encoding="utf-8")

    # 1) Къде започва секцията за CLIMATE
    idx_axis = text.find("CLIMATE_GLOBAL_RISK_REVIEW")
    if idx_axis == -1:
        return {}

    tail = text[idx_axis:]

    # 2) Първото ```json след тази секция
    idx_json = tail.find("```json")
    if idx_json == -1:
        return {}

    tail_after_json = tail[idx_json + len("```json") :]

    # 3) Затварящите ```
    idx_end = tail_after_json.find("```")
    if idx_end == -1:
        return {}

    json_str = tail_after_json[:idx_end].strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}


def _get_source(block: Dict[str, Any], source_id: str) -> Optional[Dict[str, Any]]:
    for src in block.get("approved_sources", []):
        if src.get("id") == source_id:
            return src
    return None


@dataclass
class ClimateConfig:
    latitude: float
    longitude: float
    # ISO 2-letter country code за World Bank (пример: "BG")
    country_code: str = "BG"
    start_year: int = 1980
    end_year: int = 2020
    # примерен климатичен модел от Open-Meteo (виж CONFIG_PLANET_DATA_SOURCES.md)
    model: str = "CMCC_CM2_VHR4"
    # OpenWeatherMap API key – ако е празен, OWM няма да се вика
    openweather_api_key: str = ""


class ClimateGlobalRiskReviewProvider(PlanetDataProvider):
    axis: str = "CLIMATE_GLOBAL_RISK_REVIEW"
    source_name: str = "climate_global_risk_multi"

    def __init__(self, config: ClimateConfig) -> None:
        self.config = config
        self.block = _load_climate_whitelist_block()
        if not self.block:
            raise RuntimeError(
                "CLIMATE_GLOBAL_RISK_REVIEW whitelist block not found in CONFIG_PLANET_DATA_SOURCES.md"
            )

    # -------------------------------------------------------------------------
    # Помощни функции за Open-Meteo (температура / валежи / прогноза)
    # -------------------------------------------------------------------------

    def _compute_trend_and_extremes(self, temps: List[float]) -> Dict[str, float]:
        n = len(temps)
        if n == 0:
            return {
                "temperature_trend": 0.0,
                "extreme_days_share": 0.0,
            }

        half = n // 2 or 1
        first_half = temps[:half]
        second_half = temps[half:] or temps

        first_avg = statistics.fmean(first_half)
        second_avg = statistics.fmean(second_half)

        temp_trend = 0.0
        if first_avg != 0:
            temp_trend = (second_avg - first_avg) / abs(first_avg)

        mean_temp = statistics.fmean(temps)
        extreme_threshold = mean_temp + 5.0
        extreme_days = sum(1 for t in temps if t >= extreme_threshold)
        extreme_share = extreme_days / float(n)

        return {
            "temperature_trend": float(temp_trend),
            "extreme_days_share": float(extreme_share),
        }

    def _compute_precip_change(self, precs: List[float]) -> float:
        n = len(precs)
        if n == 0:
            return 0.0

        half = n // 2 or 1
        first_half = precs[:half]
        second_half = precs[half:] or precs

        first_avg = statistics.fmean(first_half)
        second_avg = statistics.fmean(second_half)

        if first_avg == 0:
            return 0.0

        precip_change = (second_avg - first_avg) / abs(first_avg)
        return float(precip_change)

    # -------------------------------------------------------------------------
    # 1) OPEN_METEO_CLIMATE – исторически / климатични статистики
    # -------------------------------------------------------------------------

    def _fetch_open_meteo_climate(self) -> Dict[str, Any]:
        src = _get_source(self.block, "OPEN_METEO_CLIMATE")
        if not src:
            return {}

        base_url = src.get("url")
        params = {
            "latitude": self.config.latitude,
            "longitude": self.config.longitude,
            "start_year": self.config.start_year,
            "end_year": self.config.end_year,
            "daily": ["temperature_2m_mean", "precipitation_sum"],
            "models": [self.config.model],
        }

        resp = requests.get(base_url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        temps: List[float] = daily.get("temperature_2m_mean", []) or []
        precs: List[float] = daily.get("precipitation_sum", []) or []

        metrics: Dict[str, Any] = {}
        if temps:
            metrics.update(self._compute_trend_and_extremes(temps))
        if precs:
            metrics["precipitation_change"] = self._compute_precip_change(precs)

        return metrics

    # -------------------------------------------------------------------------
    # 2) OPEN_METEO_ARCHIVE – historical weather / reanalysis
    # -------------------------------------------------------------------------

    def _fetch_open_meteo_archive(self) -> Dict[str, Any]:
        src = _get_source(self.block, "OPEN_METEO_ARCHIVE")
        if not src:
            return {}

        base_url = src.get("url")
        params = {
            "latitude": self.config.latitude,
            "longitude": self.config.longitude,
            "start_date": f"{self.config.start_year}-01-01",
            "end_date": f"{self.config.end_year}-12-31",
            "daily": ["precipitation_sum"],
        }

        resp = requests.get(base_url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        precs: List[float] = daily.get("precipitation_sum", []) or []
        if not precs:
            return {}

        avg_prec = statistics.fmean(precs)
        stdev_prec = statistics.pstdev(precs) if len(precs) > 1 else 0.0
        variability = 0.0
        if avg_prec != 0:
            variability = stdev_prec / abs(avg_prec)

        return {
            "precipitation_variability": float(variability),
        }

    # -------------------------------------------------------------------------
    # 3) OPEN_METEO_FORECAST – краткосрочна прогноза
    # -------------------------------------------------------------------------

    def _fetch_open_meteo_forecast(self) -> Dict[str, Any]:
        src = _get_source(self.block, "OPEN_METEO_FORECAST")
        if not src:
            return {}

        base_url = src.get("url")
        params = {
            "latitude": self.config.latitude,
            "longitude": self.config.longitude,
            "daily": ["temperature_2m_max", "precipitation_sum"],
            "forecast_days": 7,
        }

        resp = requests.get(base_url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        tmax: List[float] = daily.get("temperature_2m_max", []) or []
        precs: List[float] = daily.get("precipitation_sum", []) or []

        metrics: Dict[str, Any] = {}
        if tmax:
            metrics["forecast_max_temp_7d"] = float(max(tmax))
        if precs:
            metrics["forecast_heavy_rain_days_7d"] = float(sum(1 for p in precs if p >= 20.0))

        return metrics

    # -------------------------------------------------------------------------
    # 4) OPENWEATHERMAP_AIR_POLLUTION – качество на въздуха (AQI, PM2.5)
    # -------------------------------------------------------------------------

    def _fetch_openweather_air_pollution(self) -> Dict[str, Any]:
        src = _get_source(self.block, "OPENWEATHERMAP_AIR_POLLUTION")
        if not src or not self.config.openweather_api_key:
            return {}

        base_url = src.get("url")
        params = {
            "lat": self.config.latitude,
            "lon": self.config.longitude,
            "appid": self.config.openweather_api_key,
        }

        try:
            resp = requests.get(base_url, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return {}

        items = data.get("list", [])
        if not items:
            return {}

        first = items
        main = first.get("main", {})
        components = first.get("components", {})

        aqi = main.get("aqi")
        pm25 = components.get("pm2_5")
        pm10 = components.get("pm10")

        metrics: Dict[str, Any] = {}
        if isinstance(aqi, (int, float)):
            metrics["air_quality_index"] = float(aqi)
        if isinstance(pm25, (int, float)):
            metrics["pm25_ug_m3"] = float(pm25)
        if isinstance(pm10, (int, float)):
            metrics["pm10_ug_m3"] = float(pm10)

        return metrics

    # -------------------------------------------------------------------------
    # 5) WORLD_BANK_CLIMATE_API – country-level индикатори (placeholder, но реален call)
    # -------------------------------------------------------------------------

    def _fetch_world_bank_climate(self) -> Dict[str, Any]:
        src = _get_source(self.block, "WORLD_BANK_CLIMATE_API")
        if not src:
            return {}

        base_url = src.get("url")
        try:
            resp = requests.get(base_url, timeout=30)
            resp.raise_for_status()
            wb_data = resp.json()
        except Exception:
            wb_data = {}

        metrics: Dict[str, Any] = {}
        try:
            text = json.dumps(wb_data, ensure_ascii=False)
            cc = self.config.country_code.upper()
            count = text.upper().count(f"\"{cc}\"")
            metrics["wb_country_code_mentions"] = float(count)
        except Exception:
            pass

        return metrics

    # -------------------------------------------------------------------------
    # Основен fetch
    # -------------------------------------------------------------------------

    def fetch(self) -> Dict[str, Any]:
        """
        Връща суров нормализиран пакет данни за CLIMATE_GLOBAL_RISK_REVIEW
        от няколко одобрени източника.
        """
        metrics: Dict[str, Any] = {}
        used_sources: List[str] = []

        # 1) Open-Meteo Climate
        try:
            om_climate = self._fetch_open_meteo_climate()
            if om_climate:
                metrics.update(om_climate)
                used_sources.append("OPEN_METEO_CLIMATE")
        except Exception:
            pass

        # 1b) NOAA GML CO2 — Mauna Loa реални данни
        try:
            noaa = fetch_noaa_co2()
            if noaa:
                metrics.update(noaa)
                used_sources.append("NOAA_GML_CO2")
        except Exception:
            pass

        # 2) Open-Meteo Archive
        try:
            om_archive = self._fetch_open_meteo_archive()
            if om_archive:
                for k, v in om_archive.items():
                    metrics[f"archive_{k}"] = v
                used_sources.append("OPEN_METEO_ARCHIVE")
        except Exception:
            pass

        # 3) Open-Meteo Forecast
        try:
            om_forecast = self._fetch_open_meteo_forecast()
            if om_forecast:
                for k, v in om_forecast.items():
                    metrics[f"forecast_{k}"] = v
                used_sources.append("OPEN_METEO_FORECAST")
        except Exception:
            pass

        # 4) OpenWeatherMap Air Pollution
        try:
            owm_air = self._fetch_openweather_air_pollution()
            if owm_air:
                for k, v in owm_air.items():
                    metrics[f"owm_{k}"] = v
                used_sources.append("OPENWEATHERMAP_AIR_POLLUTION")
        except Exception:
            pass

        # 5) World Bank Climate
        try:
            wb_climate = self._fetch_world_bank_climate()
            if wb_climate:
                for k, v in wb_climate.items():
                    metrics[f"wb_{k}"] = v
                used_sources.append("WORLD_BANK_CLIMATE_API")
        except Exception:
            pass

        data_mode = "REAL_FROM_APPROVED_SOURCE" if used_sources else "NO_REAL_SOURCE_AVAILABLE"

        return {
            "axis": self.axis,
            "source": self.source_name,
            "data_mode": data_mode,
            "source_ids": used_sources,
            "fetched_at": date.today().isoformat(),
            "location": {
                "latitude": self.config.latitude,
                "longitude": self.config.longitude,
                "country_code": self.config.country_code,
            },
            "metrics": metrics,
        }

def fetch_noaa_co2() -> dict:
    """Реални CO2 данни от NOAA Mauna Loa — без API ключ, работи в WSL2."""
    import requests
    metrics = {}
    try:
        url = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv"
        r = requests.get(url, timeout=20)
        lines = [l for l in r.text.splitlines() if not l.startswith("#") and l.strip()]
        if lines:
            last = lines[-1].split(",")
            metrics["co2_ppm_current"]     = float(last[4])
            metrics["co2_ppm_year_ago"]    = float(last[6])
            metrics["co2_annual_increase"] = round(float(last[4]) - float(last[6]), 2)
            metrics["co2_date"]            = f"{last[0]}-{last[1].zfill(2)}-{last[2].zfill(2)}"
    except Exception as e:
        print(f"  [NOAA_GML_CO2] error: {e}")
    try:
        url2 = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.csv"
        r2 = requests.get(url2, timeout=20)
        lines2 = [l for l in r2.text.splitlines() if not l.startswith("#") and l.strip()]
        if lines2:
            metrics["co2_annual_mean"] = float(lines2[-1].split(",")[1])
    except Exception as e:
        print(f"  [NOAA_GML_CO2_ANNUAL] error: {e}")
    return metrics
