#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.civilization.base_provider import CivilizationDataProvider

WB_API = "https://api.worldbank.org/v2/country/WLD/indicator"
INDICATORS = {
    "secure_internet_servers_per1m": "IT.NET.SECR.P6",
    "fixed_broadband_per100":        "IT.NET.BBND.P2",
    "mobile_subscriptions_per100":   "IT.CEL.SETS.P2",
    "air_transport_passengers":      "IS.AIR.PSGR",
    "container_port_traffic":        "IS.SHP.GOOD.TU",
    "logistics_performance_index":   "LP.LPI.OVRL.XQ",
}

def _wb(ind):
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except: return None

class TechnologyInfraProvider(CivilizationDataProvider):
    axis = "TECHNOLOGY_INFRA_REVIEW"
    source_name = "world_bank_api"
    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in INDICATORS.items()}
        return {"axis": self.axis, "source": self.source_name,
                "fetched_date": date.today().isoformat(), "metrics": m,
                "data_quality": f"{sum(1 for v in m.values() if v is not None)}/{len(m)} fetched"}
