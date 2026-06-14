#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

INDICATORS = {
    "gdp_per_capita_usd":        "NY.GDP.PCAP.CD",
    "gdp_growth_pct":            "NY.GDP.MKTP.KD.ZG",
    "unemployment_pct":          "SL.UEM.TOTL.ZS",
    "gini_index":                "SI.POV.GINI",
    "income_share_bottom20":     "SI.DST.FRST.20",
    "income_share_top10":        "SI.DST.10TH.10",
    "labor_force_participation": "SL.TLF.CACT.ZS",
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

class EconomyWorkProvider(CivilizationDataProvider):
    axis: str = "ECONOMY_WORK_REVIEW"
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
        }
