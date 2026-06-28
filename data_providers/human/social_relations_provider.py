#!/usr/bin/env python3
from __future__ import annotations
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.human.base_provider import HumanDataProvider

WB_API        = "https://api.worldbank.org/v2/country/WLD/indicator"
UNHCR_URL     = "https://api.unhcr.org/population/v1/population/"
UCDP_VERSIONS = ["25.1", "24.1", "23.1", "22.1"]


def _wb(ind: str) -> Optional[float]:
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=1&per_page=1", timeout=15)
        v = r.json()[1][0].get("value")
        return float(v) if v is not None else None
    except Exception:
        return None


def _unhcr() -> Dict[str, Optional[float]]:
    """Fetch global totals from UNHCR Population API v1."""
    out: Dict[str, Optional[float]] = {
        "refugees_millions": None,
        "asylum_seekers_millions": None,
        "idps_millions": None,
    }
    try:
        r = requests.get(
            UNHCR_URL,
            params={"yearFrom": 2022, "yearTo": 2024, "cf_type": "ISO", "limit": 1},
            timeout=25,
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return out
        row = items[0]
        def _m(key: str) -> Optional[float]:
            v = row.get(key)
            return round(float(v) / 1_000_000, 3) if v else None
        out["refugees_millions"]       = _m("refugees")
        out["asylum_seekers_millions"] = _m("asylum_seekers")
        out["idps_millions"]           = _m("idps")
    except Exception:
        pass
    return out


def _ucdp() -> Optional[int]:
    """Fetch count of active armed conflicts from UCDP API (tries multiple versions)."""
    for ver in UCDP_VERSIONS:
        try:
            r = requests.get(
                f"https://ucdpapi.pcr.uu.se/api/conflict/{ver}?pagesize=1&page=1",
                timeout=30,
            )
            if r.status_code == 200:
                total = r.json().get("TotalCount")
                if total is not None:
                    return int(total)
        except Exception:
            continue
    return None


class SocialRelationsProvider(HumanDataProvider):
    axis = "SOCIAL_RELATIONS_REVIEW"
    source_name = "unhcr_api+ucdp_api+world_bank"

    def fetch(self) -> Dict[str, Any]:
        m: Dict[str, Any] = {}
        m["homicide_rate_per_100k"] = _wb("VC.IHR.PSRC.P5")
        m.update(_unhcr())
        m["active_armed_conflicts"] = _ucdp()
        fetched = sum(1 for v in m.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": m,
            "data_quality": f"{fetched}/{len(m)} fetched",
        }
