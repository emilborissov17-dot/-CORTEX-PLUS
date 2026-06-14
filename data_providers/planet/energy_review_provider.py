#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

INDICATORS = {
    "renewable_energy_pct":        "EG.FEC.RNEW.ZS",
    "energy_intensity_per_gdp":    "EG.EGY.PRIM.PP.KD",
    "co2_emissions_per_capita":    "EN.ATM.CO2E.PC",
    "access_to_electricity_pct":   "EG.ELC.ACCS.ZS",
    "fossil_fuel_consumption_pct": "EG.USE.COMM.FO.ZS",
    "energy_use_per_capita_kg":    "EG.USE.PCAP.KG.OE",
}

def _wb_latest(indicator):
    try:
        url = f"{WB_API}/{indicator}?format=json&mrv=1&per_page=1"
        r = requests.get(url, timeout=15)
        data = r.json()
        val = data[1][0].get("value")
        return float(val) if val is not None else None
    except Exception:
        return None

class EnergyReviewProvider(PlanetDataProvider):
    axis = "ENERGY_REVIEW"
    source_name = "world_bank_api"

    def fetch(self):
        metrics = {}
        for name, code in INDICATORS.items():
            metrics[name] = _wb_latest(code)
        fetched = sum(1 for v in metrics.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": metrics,
            "data_quality": f"{fetched}/{len(metrics)} indicators fetched",
            "notes": "Renewable energy share, energy intensity, CO2 per capita, electricity access, fossil fuel use.",
        }