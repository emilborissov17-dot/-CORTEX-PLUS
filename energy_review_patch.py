#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_providers/planet/energy_review_provider.py
ENERGY_REVIEW – реални данни от World Bank API.
"""
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

INDICATORS = {
    "renewable_energy_pct":         "EG.FEC.RNEW.ZS",
    "energy_intensity_per_gdp":     "EG.EGY.PRIM.PP.KD",
    "co2_emissions_per_capita":     "EN.ATM.CO2E.PC",
    "access_to_electricity_pct":    "EG.ELC.ACCS.ZS",
    "fossil_fuel_consumption_pct":  "EG.USE.COMM.FO.ZS",
    "energy_use_per_capita_kg":     "EG.USE.PCAP.KG.OE",
}

def _wb_latest(indicator: str) -> Optional[float]:
    url = f"{WB_API}/indicator/{indicator}/latest"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data and len(data) > 1:
            return float(data[1][0]['value'])
    return None

def energy_review() -> Dict[str, Any]:
    data = {}
    for key, indicator in INDICATORS.items():
        value = _wb_latest(indicator)
        data[key] = value
    return data
