#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

INDICATORS = {
    "rd_expenditure_pct_gdp":     "GB.XPD.RSDV.GD.ZS",
    "high_tech_exports_pct":      "TX.VAL.TECH.MF.ZS",
    "patent_applications":        "IP.PAT.RESD",
    "secure_internet_servers":    "IT.NET.SECR.P6",
    "individuals_internet_pct":   "IT.NET.USER.ZS",
}

def _wb_latest(indicator: str) -> Optional[float]:
    try:
        url = f"{WB_API}/{indicator}?format=json&mrv=1&per_page=1"
        r = requests.get(url, timeout=15)
        data = r.json()
        val = data[1][0].get("value")
        return float(val) if val is not None else None
    except Exception:
        return None

class TechnologyAIProvider(CivilizationDataProvider):
    axis: str = "TECHNOLOGY_AI_REVIEW"
    source_name: str = "world_bank_api"

    def fetch(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        for name, code in INDICATORS.items():
            metrics[name] = _wb_latest(code)
        fetched = sum(1 for v in metrics.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": metrics,
            "data_quality": f"{fetched}/{len(metrics)} indicators fetched",
            "notes": "R&D spend, high-tech exports, patents, internet security — World Bank proxies for tech/AI axis.",
        }
