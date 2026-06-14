#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
WHO_API = "https://ghoapi.azureedge.net/api"

INDICATORS = {
    "life_expectancy":        "SP.DYN.LE00.IN",
    "health_expenditure_pct": "SH.XPD.CHEX.GD.ZS",
    "infant_mortality":       "SP.DYN.IMRT.IN",
    "physicians_per_1000":    "SH.MED.PHYS.ZS",
    "poverty_headcount":      "SI.POV.DDAY",
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

def _who_latest(indicator_code: str) -> Optional[float]:
    try:
        url = f"{WHO_API}/{indicator_code}?$filter=SpatialDim eq 'GLOBAL'&$orderby=TimeDim desc&$top=1"
        r = requests.get(url, timeout=15)
        items = r.json().get("value", [])
        if items:
            return float(items[0].get("NumericValue", 0))
        return None
    except Exception:
        return None

class HumanWellBeingProvider(HumanDataProvider):
    axis: str = "HUMAN_WELL_BEING_REVIEW"
    source_name: str = "world_bank_who_api"

    def fetch(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        for name, code in INDICATORS.items():
            metrics[name] = _wb_latest(code)
        metrics["suicide_rate_per_100k"] = _who_latest("SDGSUICIDE")
        metrics["uhc_service_coverage_index"] = _who_latest("UHC_INDEX_REPORTED")
        fetched = sum(1 for v in metrics.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": metrics,
            "data_quality": f"{fetched}/{len(metrics)} indicators fetched",
        }
