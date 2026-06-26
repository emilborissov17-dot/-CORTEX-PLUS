#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import json, urllib.request
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_WLD = "https://api.worldbank.org/v2/country/WLD/indicator"
WB_ALL = "https://api.worldbank.org/v2/country/all/indicator"

WGI_CODES = {
    "rule_of_law":          "GOV_WGI_RL.EST",
    "voice_accountability": "GOV_WGI_VA.EST",
    "political_stability":  "GOV_WGI_PV.EST",
}

WB_CODES = {
    "gender_inequality_index": "SG.GEN.PARL.ZS",
    "child_labor_pct":         "SL.TLF.0714.ZS",
    "access_justice_score":    "IQ.CPA.PROT.XQ",
}


def _wgi_mean(indicator_code: str) -> Optional[float]:
    url = f"{WB_ALL}/{indicator_code}?format=json&mrv=1&per_page=300"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
        values = [
            float(d["value"])
            for d in (data[1] or [])
            if d.get("value") is not None and d.get("countryiso3code")
        ]
        return round(sum(values) / len(values), 3) if values else None
    except Exception:
        return None


def _wb(ind: str) -> Optional[float]:
    try:
        r = requests.get(f"{WB_WLD}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except Exception:
        return None


class GovernanceRightsHumanProvider(HumanDataProvider):
    axis = "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL"
    source_name = "world_bank_wgi+wdi"

    def fetch(self) -> Dict[str, Any]:
        m: Dict[str, Any] = {}
        for name, code in WGI_CODES.items():
            m[name] = _wgi_mean(code)
        for name, code in WB_CODES.items():
            m[name] = _wb(code)
        fetched = sum(1 for v in m.values() if v is not None)
        return {
            "axis":         self.axis,
            "source":       self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics":      m,
            "data_quality": f"{fetched}/{len(m)} fetched",
        }
