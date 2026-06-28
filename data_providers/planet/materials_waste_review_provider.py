#!/usr/bin/env python3
from __future__ import annotations
import csv, io
from datetime import date
from typing import Any, Dict, Optional
import requests
from data_providers.planet.base_provider import PlanetDataProvider

WB_API   = "https://api.worldbank.org/v2/country/WLD/indicator"
OWID_CSV = "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv"

# EN.ATM.CO2E.KT archived by WB — CO2 total now from OWID
# Recycling rate: no WB indicator; OECD average ~34%, global ~13.5% (WB What-a-Waste 2.0)
OECD_RECYCLING_URL = (
    "https://sdmx.oecd.org/public/rest/data/"
    "OECD.ENV.EPI,DSD_ENV_EPI@DF_ENVIRON_WASTE/A.OECD.TOT_RCV_R"
    "?format=jsondata&startPeriod=2018&endPeriod=2023"
)
RECYCLING_STATIC_FALLBACK = 13.5  # WB What-a-Waste 2.0 global estimate

# WB WDI has no material footprint or waste generation indicators at global scale.
# Best available proxies:
#   NY.ADJ.DRES.GN.ZS — resource depletion (% GNI): how fast natural capital is drawn down
#   NY.GDP.TOTL.RT.ZS — natural resource rents (% GDP): extraction dependency
#   AG.LND.FRST.ZS    — forest area: land-use proxy for linear economy pressure
#   ER.LND.PTLD.ZS    — protected terrestrial areas: conservation signal
WB_INDICATORS = {
    "resource_depletion_pct_gni":     "NY.ADJ.DRES.GN.ZS",
    "natural_resource_rents_pct_gdp": "NY.GDP.TOTL.RT.ZS",
    "forest_area_pct":                "AG.LND.FRST.ZS",
    "protected_areas_pct":            "ER.LND.PTLD.ZS",
}


def _wb(ind: str) -> Optional[float]:
    try:
        r = requests.get(f"{WB_API}/{ind}?format=json&mrv=5&per_page=5", timeout=15)
        for item in r.json()[1]:
            if item.get("value") is not None:
                return float(item["value"])
        return None
    except:
        return None


def _owid_co2_total_kt() -> Optional[float]:
    try:
        r = requests.get(OWID_CSV, timeout=30)
        reader = csv.DictReader(io.StringIO(r.text))
        world_rows = [
            row for row in reader
            if row.get("country") == "World" and row.get("co2")
        ]
        if not world_rows:
            return None
        latest = sorted(world_rows, key=lambda x: int(x["year"]))[-1]
        # OWID co2 is in million tonnes; convert to kt (1 Mt = 1000 kt)
        return round(float(latest["co2"]) * 1000, 0)
    except Exception:
        return None


def _recycling_rate_pct() -> Optional[float]:
    try:
        r = requests.get(OECD_RECYCLING_URL, timeout=15)
        if r.status_code != 200:
            return RECYCLING_STATIC_FALLBACK
        data = r.json()
        series = data.get("dataSets", [{}])[0].get("series", {})
        values = [
            obs[0] for s in series.values()
            for obs in s.get("observations", {}).values()
            if obs and obs[0] is not None
        ]
        return round(sum(values) / len(values), 2) if values else RECYCLING_STATIC_FALLBACK
    except Exception:
        return RECYCLING_STATIC_FALLBACK


class MaterialsWasteReviewProvider(PlanetDataProvider):
    axis: str = "MATERIALS_WASTE_REVIEW"
    source_name: str = "world_bank_api+owid+oecd"

    def fetch(self) -> Dict[str, Any]:
        m: Dict[str, Any] = {n: _wb(c) for n, c in WB_INDICATORS.items()}
        m["co2_emissions_total_kt"] = _owid_co2_total_kt()
        m["recycling_rate_pct"]     = _recycling_rate_pct()
        fetched = sum(1 for v in m.values() if v is not None)
        return {
            "axis": self.axis,
            "source": self.source_name,
            "fetched_date": date.today().isoformat(),
            "metrics": m,
            "data_quality": f"{fetched}/{len(m)} indicators fetched",
        }
