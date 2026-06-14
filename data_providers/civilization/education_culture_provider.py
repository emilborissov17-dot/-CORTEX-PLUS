#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "literacy_rate_adult_pct":       "SE.ADT.LITR.ZS",
    "primary_enrollment_pct":        "SE.PRM.NENR",
    "secondary_enrollment_pct":      "SE.SEC.NENR",
    "tertiary_enrollment_pct":       "SE.TER.ENRR",
    "govt_education_spend_pct_gdp":  "SE.XPD.TOTL.GD.ZS",
    "internet_users_pct":            "IT.NET.USER.ZS",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class EducationCultureProvider(CivilizationDataProvider):
    axis = "EDUCATION_CULTURE_REVIEW"
    source_name = "world_bank_api"
    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(), "metrics": m,
                "data_quality": f"{sum(1 for v in m.values() if v is not None)}/{len(m)} fetched"}
