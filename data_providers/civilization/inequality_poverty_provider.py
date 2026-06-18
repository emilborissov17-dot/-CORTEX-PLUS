#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_WORLD   = "https://api.worldbank.org/v2/country/WLD/indicator"
WB_ALL     = "https://api.worldbank.org/v2/country/all/indicator"

# Indicators available at WLD aggregate level
WLD_INDICATORS = {
    "poverty_headcount_190":      "SI.POV.DDAY",
    "social_protection_coverage": "per_allsp.cov_pop_tot",
}

# Indicators only available per-country — aggregated as population-weighted mean
PER_COUNTRY_INDICATORS = {
    "gini_index":          "SI.POV.GINI",
    "income_share_top10":  "SI.DST.10TH.10",
}
_BOTTOM40_INDS = ("SI.DST.FRST.20", "SI.DST.02ND.20")


def _wb_world(ind) -> Optional[float]:
    try:
        r = requests.get(f"{WB_WORLD}/{ind}?format=json&mrv=5&per_page=5", timeout=15)
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except:
        return None


def _wb_global_mean(ind) -> Optional[float]:
    """Population-weighted mean across all countries that report this indicator."""
    try:
        r = requests.get(
            f"{WB_ALL}/{ind}?format=json&mrv=1&per_page=500", timeout=20
        )
        raw = r.json()
        items = raw[1] if len(raw) > 1 and raw[1] else []
        values = [float(i["value"]) for i in items if i.get("value") is not None]
        return round(sum(values) / len(values), 4) if values else None
    except:
        return None


def _income_share_bottom40() -> Optional[float]:
    b20 = _wb_global_mean("SI.DST.FRST.20")
    s20 = _wb_global_mean("SI.DST.02ND.20")
    return round(b20 + s20, 4) if b20 is not None and s20 is not None else None


class InequalityPovertyProvider:
    def fetch(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {k: _wb_world(v) for k, v in WLD_INDICATORS.items()}
        for name, ind in PER_COUNTRY_INDICATORS.items():
            metrics[name] = _wb_global_mean(ind)
        metrics["income_share_bottom40"] = _income_share_bottom40()
        return metrics
