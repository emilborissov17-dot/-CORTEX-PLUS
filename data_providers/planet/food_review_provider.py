#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "prevalence_undernourishment_pct": "SN.ITK.DEFC.ZS",
    "food_production_index":           "AG.PRD.FOOD.XD",
    "cereal_yield_kg_per_ha":          "AG.YLD.CREL.KG",
    "agricultural_land_pct":           "AG.LND.AGRI.ZS",
    "food_imports_pct_merch":          "TM.VAL.FOOD.ZS.UN",
    "arable_land_per_person_ha":       "AG.LND.ARBL.HA.PC",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class FoodProvider(PlanetDataProvider):
    axis: str = "FOOD_REVIEW"
    source_name: str = "world_bank_api"
    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        fetched = sum(1 for v in m.values() if v is not None)
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(), "metrics": m,
                "data_quality": f"{fetched}/{len(m)} indicators fetched"}
