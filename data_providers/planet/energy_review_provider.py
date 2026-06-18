#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import csv, io
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

# EN.ATM.CO2E.PC archived by WB — fetched from OWID (IEA/GCP data) instead
OWID_CO2_CSV = "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"

WB_INDICATORS = {
    "renewable_energy_pct":        "EG.FEC.RNEW.ZS",
    "energy_intensity_per_gdp":    "EG.EGY.PRIM.PP.KD",
    "access_to_electricity_pct":   "EG.ELC.ACCS.ZS",
    "fossil_fuel_consumption_pct": "EG.USE.COMM.FO.ZS",
    "energy_use_per_capita_kg":    "EG.USE.PCAP.KG.OE",
}


def _wb_latest(indicator: str) -> Optional[float]:
    try:
        url = f"{WB_API}/{indicator}?format=json&mrv=5&per_page=5"
        r = requests.get(url, timeout=15)
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except Exception:
        return None


def _owid_co2_per_capita() -> Optional[float]:
    try:
        r = requests.get(OWID_CO2_CSV, timeout=30)
        reader = csv.DictReader(io.StringIO(r.text))
        world_rows = [
            row for row in reader
            if row.get("country") == "World" and row.get("co2_per_capita")
        ]
        if not world_rows:
            return None
        latest = sorted(world_rows, key=lambda x: int(x["year"]))[-1]
        return round(float(latest["co2_per_capita"]), 4)
    except Exception:
        return None


class EnergyReviewProvider(PlanetDataProvider):
    axis = "ENERGY_REVIEW"
    source_name = "world_bank_api+owid"

    def fetch(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {n: _wb_latest(c) for n, c in WB_INDICATORS.items()}
        metrics["co2_emissions_per_capita"] = _owid_co2_per_capita()
        fetched = sum(1 for v in metrics.values() if v is not None)
        total = len(WB_INDICATORS) + 1
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": metrics,
            "data_quality": f"{fetched}/{total} indicators fetched",
            "notes": "WB: renewable/intensity/access/fossil/energy-use. OWID(IEA/GCP): CO2 per capita.",
        }