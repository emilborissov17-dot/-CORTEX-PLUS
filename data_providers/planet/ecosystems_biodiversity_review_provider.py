#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "forest_area_pct":              "AG.LND.FRST.ZS",
    "protected_terrestrial_area_pct": "ER.LND.PTLD.ZS",
    "marine_protected_area_pct":    "ER.MRN.PTMR.ZS",
    "annual_deforestation_pct":     "AG.LND.FRST.K2",
    "threatened_species_count":     "EN.MAM.THRD.NO",
    "co2_emissions_per_capita":     "EN.ATM.CO2E.PC",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class BiodiversityProvider(PlanetDataProvider):
    axis: str = "ECOSYSTEMS_BIODIVERSITY_REVIEW"
    source_name: str = "world_bank_api"
    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        fetched = sum(1 for v in m.values() if v is not None)
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(), "metrics": m,
                "data_quality": f"{fetched}/{len(m)} indicators fetched"}
