#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_WORLD = "https://api.worldbank.org/v2/country/WLD/indicator"
WB_ALL   = "https://api.worldbank.org/v2/country/all/indicator"

# Available at WLD aggregate level
WLD_INDICATORS = {
    "gdp_per_capita_usd":        "NY.GDP.PCAP.CD",
    "gdp_growth_pct":            "NY.GDP.MKTP.KD.ZG",
    "unemployment_pct":          "SL.UEM.TOTL.ZS",
    "labor_force_participation": "SL.TLF.CACT.ZS",
}

# Only available per-country — aggregated as simple mean
PER_COUNTRY_INDICATORS = {
    "gini_index":            "SI.POV.GINI",
    "income_share_bottom20": "SI.DST.FRST.20",
    "income_share_top10":    "SI.DST.10TH.10",
}


def _wb_latest(indicator: str) -> Optional[float]:
    try:
        url = f"{WB_WORLD}/{indicator}?format=json&mrv=5&per_page=5"
        r = requests.get(url, timeout=15)
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except Exception:
        return None


def _wb_global_mean(indicator: str) -> Optional[float]:
    try:
        url = f"{WB_ALL}/{indicator}?format=json&mrv=1&per_page=500"
        r = requests.get(url, timeout=20)
        raw = r.json()
        items = raw[1] if len(raw) > 1 and raw[1] else []
        values = [float(i["value"]) for i in items if i.get("value") is not None]
        return round(sum(values) / len(values), 4) if values else None
    except Exception:
        return None

class EconomyWorkProvider(CivilizationDataProvider):
    axis: str = "ECONOMY_WORK_REVIEW"
    source_name: str = "world_bank_api"

    def fetch(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {n: _wb_latest(c) for n, c in WLD_INDICATORS.items()}
        for name, code in PER_COUNTRY_INDICATORS.items():
            metrics[name] = _wb_global_mean(code)
        fetched = sum(1 for v in metrics.values() if v is not None)
        total = len(WLD_INDICATORS) + len(PER_COUNTRY_INDICATORS)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": metrics,
            "data_quality": f"{fetched}/{total} indicators fetched",
        }
