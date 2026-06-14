#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

INDICATORS = {
    "access_safe_water_pct":     "SH.H2O.SMDW.ZS",
    "access_sanitation_pct":     "SH.STA.SMSS.ZS",
    "water_productivity_usd_m3": "ER.GDP.FWTL.M3.KD",
    "annual_freshwater_withdrawal_pct": "ER.H2O.FWTL.ZS",
    "rural_water_access_pct":    "SH.H2O.SMDW.RU.ZS",
    "urban_water_access_pct":    "SH.H2O.SMDW.UR.ZS",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class WaterProvider(PlanetDataProvider):
    axis: str = "WATER_REVIEW"
    source_name: str = "world_bank_api"

    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        fetched = sum(1 for v in m.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": m,
            "data_quality": f"{fetched}/{len(m)} indicators fetched",
        }
