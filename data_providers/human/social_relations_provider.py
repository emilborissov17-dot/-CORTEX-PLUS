#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "homicide_rate_per_100k":    "VC.IHR.PSRC.P5",
    "refugee_population":        "SM.POP.REFG",
    "internally_displaced":      "VC.IDP.TOTL.HE",
    "conflict_deaths_per_100k":  "VC.BTL.DETH",
    "urbanization_pct":          "SP.URB.TOTL.IN.ZS",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class SocialRelationsProvider(HumanDataProvider):
    axis = "SOCIAL_RELATIONS_REVIEW"
    source_name = "world_bank_api"
    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(), "metrics": m,
                "data_quality": f"{sum(1 for v in m.values() if v is not None)}/{len(m)} fetched"}
