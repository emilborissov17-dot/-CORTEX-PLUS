#!/usr/bin/env python3
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API    = "https://api.worldbank.org/v2/country/WLD/indicator"
GBIF_URL  = "https://api.gbif.org/v1/occurrence/search"
NOAA_CO2_URL = "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv"

# EN.ATM.CO2E.PC has no WLD aggregate — replaced with NOAA Mauna Loa real-time CO2
WB_INDICATORS = {
    "forest_area_pct":                "AG.LND.FRST.ZS",
    "protected_terrestrial_area_pct": "ER.LND.PTLD.ZS",
    "marine_protected_area_pct":      "ER.MRN.PTMR.ZS",
    "threatened_mammal_species":      "EN.MAM.THRD.NO",
}

def _wb(ind: str) -> float | None:
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=5&per_page=5", timeout=15)
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except:
        return None

def _noaa_co2_ppm() -> float | None:
    """Latest weekly CO2 ppm from NOAA Mauna Loa.
    EN.ATM.CO2E.PC has no WLD aggregate — NOAA provides real-time atmospheric CO2.
    """
    try:
        r = requests.get(NOAA_CO2_URL, timeout=15)
        lines = [l for l in r.text.strip().splitlines()
                 if not l.startswith("#") and l.strip()]
        def _valid(l):
            try: return float(l.split(",")[4].strip()) > 0
            except: return False
        lines = [l for l in lines if _valid(l)]
        return float(lines[-1].split(",")[4].strip())
    except:
        return None

def _gbif_observations_30d() -> int | None:
    """Species occurrence records in last 30 days from GBIF.
    Real-time proxy for global biodiversity monitoring activity.
    """
    try:
        today     = datetime.utcnow().strftime("%Y-%m-%d")
        month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        r = requests.get(GBIF_URL, params={
            "eventDate": f"{month_ago},{today}",
            "limit": 0,
        }, timeout=15)
        return int(r.json().get("count", 0))
    except:
        return None

class BiodiversityProvider(PlanetDataProvider):
    axis: str = "ECOSYSTEMS_BIODIVERSITY_REVIEW"
    source_name: str = "world_bank_api+gbif+noaa"

    def fetch(self) -> Dict[str, Any]:
        m = {n: _wb(c) for n, c in WB_INDICATORS.items()}
        m["co2_ppm_mauna_loa"]             = _noaa_co2_ppm()
        m["species_observations_30d_gbif"] = _gbif_observations_30d()

        fetched = sum(1 for v in m.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": m,
            "data_quality": f"{fetched}/{len(m)} indicators fetched",
        }
