#!/usr/bin/env python3
"""
data_providers/planet/climate_provider.py
Реални климатични данни от NOAA + World Bank
"""
import json, pathlib, requests
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[3]

def fetch() -> dict:
    metrics = {}
    
    # 1. CO2 от NOAA Mauna Loa
    try:
        url = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv"
        r = requests.get(url, timeout=20)
        lines = [l for l in r.text.splitlines() if not l.startswith("#") and l.strip()]
        if lines:
            last = lines[-1].split(",")
            metrics["co2_ppm_current"]      = float(last[4])
            metrics["co2_ppm_year_ago"]     = float(last[6])
            metrics["co2_annual_increase"]  = round(float(last[4]) - float(last[6]), 2)
            metrics["co2_measurement_date"] = f"{last[0]}-{last[1].zfill(2)}-{last[2].zfill(2)}"
    except Exception as e:
        print(f"  NOAA CO2 error: {e}")

    # 2. Temperature anomaly от NOAA
    try:
        url = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_annmean_mlo.csv"
        r = requests.get(url, timeout=20)
        lines = [l for l in r.text.splitlines() if not l.startswith("#") and l.strip()]
        if len(lines) >= 2:
            recent = lines[-1].split(",")
            prev   = lines[-2].split(",")
            metrics["co2_annual_mean_latest"] = float(recent[1])
            metrics["co2_annual_mean_prev"]   = float(prev[1])
    except Exception as e:
        print(f"  NOAA annual error: {e}")

    # 3. Renewable energy & emissions от World Bank
    try:
        wb_indicators = {
            "co2_emissions_per_capita": "EN.ATM.CO2E.PC",
            "forest_area_pct":          "AG.LND.FRST.ZS",
        }
        for name, indicator in wb_indicators.items():
            url = f"https://api.worldbank.org/v2/country/WLD/indicator/{indicator}?format=json&mrv=1&per_page=1"
            resp = requests.get(url, timeout=15)
            data = resp.json()
            if data[1] and data[1][0].get("value"):
                metrics[name] = round(float(data[1][0]["value"]), 3)
    except Exception as e:
        print(f"  World Bank error: {e}")

    return metrics

def normalize(metrics: dict) -> dict:
    return metrics

class ClimateProvider:
    def fetch(self) -> dict:
        return fetch()
    def normalize(self, metrics: dict) -> dict:
        return metrics

if __name__ == "__main__":
    print("[CLIMATE] Зареждам реални климатични данни...")
    m = fetch()
    for k, v in m.items():
        print(f"  {k} = {v}")
    
    # Анализ
    co2 = m.get("co2_ppm_current", 0)
    if co2 > 430:
        print(f"\n  🔴 КРИТИЧНО: CO2 = {co2} ppm — над 430 ppm прага!")
    elif co2 > 420:
        print(f"\n  🟡 ВИСОК: CO2 = {co2} ppm — над 420 ppm")
    
    increase = m.get("co2_annual_increase", 0)
    print(f"  Годишен ръст: +{increase} ppm")
