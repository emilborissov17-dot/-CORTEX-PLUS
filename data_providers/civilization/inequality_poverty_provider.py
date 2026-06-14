#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "gini_index":                    "SI.POV.GINI",
    "poverty_headcount_190":         "SI.POV.DDAY",
    "income_share_bottom40":         "SI.DST.04TH.20",
    "income_share_top10":            "SI.DST.10TH.10",
    "multidimensional_poverty_pct":  "SI.POV.MDIM",
    "social_protection_coverage":    "per_allsp.cov_pop_tot",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=5&per_page=1", timeout=15)
        data = r.json()[1]
        for item in data:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except: return None

class InequalityPovertyProvider:
    def fetch(self) -> Dict[str, Any]:
        return {k: _wb(v) for k, v in INDICATORS.items()}
