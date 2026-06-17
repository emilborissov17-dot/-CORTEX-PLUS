#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "literacy_rate_youth_pct":       "SE.ADT.1524.LT.ZS",
    "primary_completion_rate":       "SE.PRM.CMPT.ZS",
    "tertiary_enrollment_pct":       "SE.TER.ENRR",
    "govt_expenditure_education_pct":"SE.XPD.TOTL.GD.ZS",
    "pupil_teacher_ratio_primary":   "SE.PRM.ENRL.TC.ZS",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class CognitionLearningProvider(HumanDataProvider):
    axis = "COGNITION_LEARNING_REVIEW"
    source_name = "world_bank_api"
    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(), "metrics": m,
                "data_quality": f"{sum(1 for v in m.values() if v is not None)}/{len(m)} fetched"}
