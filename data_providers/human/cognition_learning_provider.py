#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_WORLD = "https://api.worldbank.org/v2/country/WLD/indicator"
WB_ALL   = "https://api.worldbank.org/v2/country/all/indicator"

WLD_INDICATORS = {
    "literacy_rate_youth_pct":        "SE.ADT.1524.LT.ZS",
    "primary_completion_rate":        "SE.PRM.CMPT.ZS",
    "tertiary_enrollment_pct":        "SE.TER.ENRR",
    "govt_expenditure_education_pct": "SE.XPD.TOTL.GD.ZS",
}
# No WLD aggregate — per-country mean (latest value per country, mrv=5)
PER_COUNTRY_INDICATORS = {
    "pupil_teacher_ratio_primary": "SE.PRM.ENRL.TC.ZS",
}


def _wb(ind: str) -> Optional[float]:
    try:
        r = requests.get(f"{WB_WORLD}/{ind}?format=json&mrv=5&per_page=5", timeout=15)
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except:
        return None


def _wb_global_mean(ind: str) -> Optional[float]:
    try:
        r = requests.get(f"{WB_ALL}/{ind}?format=json&mrv=5&per_page=500", timeout=20)
        raw = r.json()
        items = raw[1] if len(raw) > 1 and raw[1] else []
        by_country: dict = {}
        for i in items:
            if i.get("value") is not None:
                cc = i.get("countryiso3code", "")
                if cc not in by_country or i["date"] > by_country[cc][0]:
                    by_country[cc] = (i["date"], float(i["value"]))
        vals = [v for _, v in by_country.values()]
        return round(sum(vals) / len(vals), 4) if vals else None
    except:
        return None


class CognitionLearningProvider(HumanDataProvider):
    axis = "COGNITION_LEARNING_REVIEW"
    source_name = "world_bank_api"

    def fetch(self) -> Dict[str, Any]:
        m: Dict[str, Any] = {n: _wb(c) for n, c in WLD_INDICATORS.items()}
        for name, ind in PER_COUNTRY_INDICATORS.items():
            m[name] = _wb_global_mean(ind)
        fetched = sum(1 for v in m.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": m,
            "data_quality": f"{fetched}/{len(m)} fetched",
        }
