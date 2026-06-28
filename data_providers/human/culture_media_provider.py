#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"

INDICATORS = {
    "internet_users_pct":          "IT.NET.USER.ZS",
    "mobile_subscriptions_per100": "IT.CEL.SETS.P2",
    "literacy_rate_adult_pct":     "SE.ADT.LITR.ZS",
    "primary_school_enrollment":   "SE.PRM.NENR",
    "secondary_school_enrollment": "SE.SEC.NENR",
    "fixed_broadband_per100":      "IT.NET.BBND.P2",
    # Proxy for cultural investment capacity (UNESCO minimum: 4% GDP)
    "education_spend_pct_gdp":     "SE.XPD.TOTL.GD.ZS",
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

class CultureMediaProvider(HumanDataProvider):
    axis: str = "CULTURE_MEDIA_REVIEW"
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
