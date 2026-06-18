#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/global_indicators.py
Реални глобални индикатори от безплатни публични API-та — без API ключ.
Извиква се веднъж на цикъл; резултатът се инжектира в LLM промптовете.

Sources:
  NOAA Mauna Loa CO2       — atmospheric CO2 ppm (weekly)
  NASA GISTEMP             — global temperature anomaly vs 1951-1980
  NOAA sea level           — global mean sea level (mm, satellite altimetry)
  World Bank WDI           — poverty, population, health, forest, renewables
  GBIF                     — species occurrence observations (30d)
  UCDP                     — active armed conflicts
  SIPRI 2024 (static)      — nuclear warheads estimate
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, timeout: int = 20, params: dict | None = None) -> Any:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        return r.json() if "json" in ct else r.text
    except Exception as e:
        print(f"  [GI] fetch error {url[:70]}: {e}")
        return None


# ---------------------------------------------------------------------------
# 1. CO2 — NOAA Mauna Loa
# ---------------------------------------------------------------------------

def fetch_co2() -> dict:
    text = _get("https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_weekly_mlo.csv")
    if not text:
        return {}
    lines = [l for l in str(text).splitlines() if not l.startswith("#") and l.strip()]
    if not lines:
        return {}
    try:
        p = lines[-1].split(",")
        return {
            "co2_ppm":             float(p[4]),
            "co2_ppm_1yr_ago":     float(p[6]),
            "co2_annual_increase": round(float(p[4]) - float(p[6]), 2),
            "co2_date":            f"{p[0]}-{p[1].zfill(2)}-{p[2].zfill(2)}",
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 2. Global temperature anomaly — NASA GISTEMP
# ---------------------------------------------------------------------------

def fetch_gistemp() -> dict:
    """Annual surface temp anomaly (°C) vs 1951-1980 baseline."""
    text = _get(
        "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv",
        timeout=25,
    )
    if not text:
        return {}
    for line in reversed(str(text).splitlines()):
        if not line.strip() or line.startswith("Year"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 14:
            continue
        try:
            year   = int(parts[0])
            annual = float(parts[13])   # J-D column = annual mean
            return {
                "temp_anomaly_c":        round(annual, 3),
                "temp_anomaly_year":     year,
                "temp_anomaly_baseline": "1951-1980",
            }
        except (ValueError, IndexError):
            continue
    return {}


# ---------------------------------------------------------------------------
# 3. Global mean sea level — NOAA satellite altimetry
# ---------------------------------------------------------------------------

def fetch_sea_level() -> dict:
    """Global mean sea level rise (mm) vs 1993 baseline — CU Boulder."""
    # CU Sea Level Research Group annual data
    for url in (
        "https://sealevel.colorado.edu/sites/default/files/2024-06/sl_ns_global.txt",
        "https://sealevel.colorado.edu/sites/default/files/2023-06/sl_ns_global.txt",
    ):
        text = _get(url, timeout=30)
        if not text:
            continue
        for line in reversed(str(text).splitlines()):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return {
                        "sea_level_rise_mm":       round(float(parts[1]), 1),
                        "sea_level_year_fraction":  round(float(parts[0]), 3),
                        "sea_level_baseline":       "1993",
                        "sea_level_source":         "CU Boulder SLRG",
                    }
                except ValueError:
                    continue
    return {}


# ---------------------------------------------------------------------------
# 4. World Bank WDI
# ---------------------------------------------------------------------------

_WB_WORLD = "https://api.worldbank.org/v2/country/WLD/indicator"
_WB_ALL   = "https://api.worldbank.org/v2/country/all/indicator"


def _wb_world(ind: str, mrv: int = 5) -> Optional[float]:
    data = _get(f"{_WB_WORLD}/{ind}?format=json&mrv={mrv}&per_page={mrv}")
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    for item in (data[1] or []):
        if item.get("value") is not None:
            return round(float(item["value"]), 4)
    return None


def _wb_global_mean(ind: str) -> Optional[float]:
    data = _get(f"{_WB_ALL}/{ind}?format=json&mrv=1&per_page=500")
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    values = [float(i["value"]) for i in (data[1] or []) if i.get("value") is not None]
    return round(sum(values) / len(values), 4) if values else None


def fetch_world_bank() -> dict:
    pop = _wb_world("SP.POP.TOTL")
    return {
        "population_billions":       round(pop / 1e9, 3) if pop else None,
        "poverty_190_pct":           _wb_world("SI.POV.DDAY"),
        "life_expectancy":           _wb_world("SP.DYN.LE00.IN"),
        "infant_mortality_per1k":    _wb_world("SP.DYN.IMRT.IN"),
        "gini_mean":                 _wb_global_mean("SI.POV.GINI"),
        "forest_area_pct":           _wb_world("AG.LND.FRST.ZS"),
        "renewable_elec_pct":        _wb_world("EG.ELC.RNEW.ZS"),
        "safe_water_access_pct":     _wb_world("SH.H2O.SMDW.ZS"),
        "literacy_rate_adult_pct":   _wb_world("SE.ADT.LITR.ZS"),
        "threatened_mammals_no":     _wb_world("EN.MAM.THRD.NO"),
        "co2_emissions_kt":          _wb_world("EN.ATM.CO2E.KT"),
    }


# ---------------------------------------------------------------------------
# 5. Biodiversity — GBIF
# ---------------------------------------------------------------------------

def fetch_gbif() -> dict:
    today     = datetime.utcnow().strftime("%Y-%m-%d")
    month_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
    data = _get(
        "https://api.gbif.org/v1/occurrence/search",
        params={"eventDate": f"{month_ago},{today}", "limit": 0},
    )
    if not data or not isinstance(data, dict):
        return {}
    return {"species_observations_30d": int(data.get("count", 0))}


# ---------------------------------------------------------------------------
# 6. Armed conflicts — UCDP
# ---------------------------------------------------------------------------

def fetch_ucdp() -> dict:
    """Number of active armed conflicts from Uppsala Conflict Data Program."""
    for version in ("25.1", "24.1", "23.1", "22.1"):
        data = _get(
            f"https://ucdpapi.pcr.uu.se/api/conflict/{version}?pagesize=1&page=1",
            timeout=30,
        )
        if data and isinstance(data, dict) and "TotalCount" in data:
            return {
                "active_armed_conflicts": data["TotalCount"],
                "ucdp_version": version,
            }
    return {}


# ---------------------------------------------------------------------------
# 7. Nuclear warheads — SIPRI 2024 (static)
# ---------------------------------------------------------------------------

def fetch_nuclear() -> dict:
    """SIPRI Yearbook 2024 estimate. Update when new edition releases."""
    return {
        "nuclear_warheads_total":    12121,
        "nuclear_warheads_deployed": 3904,
        "nuclear_warheads_on_alert": 2100,
        "source_year":               2024,
        "source":                    "SIPRI Yearbook 2024",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_SECTIONS = [
    ("co2",          fetch_co2,          "NOAA Mauna Loa CO2"),
    ("temperature",  fetch_gistemp,      "NASA GISTEMP"),
    ("sea_level",    fetch_sea_level,    "NOAA Satellite Altimetry"),
    ("world_bank",   fetch_world_bank,   "World Bank WDI"),
    ("biodiversity", fetch_gbif,         "GBIF"),
    ("conflicts",    fetch_ucdp,         "UCDP"),
    ("nuclear",      fetch_nuclear,      "SIPRI 2024"),
]


def fetch_all() -> dict:
    """Fetch all global indicators. Prints progress. Returns full dict."""
    print("[GI] Fetching global indicators from 7 sources...")
    result: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources":   {},
    }
    for key, fn, source in _SECTIONS:
        try:
            data = fn()
            result[key] = data
            result["sources"][key] = source
            ok = sum(1 for v in data.values() if v is not None)
            print(f"  [GI] {source}: {ok}/{len(data)} metrics")
        except Exception as e:
            result[key] = {}
            print(f"  [GI] {source}: ERROR {e}")
    return result


def as_prompt_block(ind: dict) -> str:
    """Compact text block ready to inject into any LLM prompt."""
    lines = ["── REAL GLOBAL INDICATORS (this cycle) ──────────────────"]

    co2 = ind.get("co2", {})
    if co2.get("co2_ppm"):
        lines.append(
            f"CO2: {co2['co2_ppm']} ppm "
            f"(+{co2.get('co2_annual_increase','?')} ppm/yr, {co2.get('co2_date','')})"
        )

    t = ind.get("temperature", {})
    if t.get("temp_anomaly_c") is not None:
        lines.append(
            f"Global temp anomaly: +{t['temp_anomaly_c']}°C vs 1951-1980 "
            f"({t.get('temp_anomaly_year','')})"
        )

    sl = ind.get("sea_level", {})
    if sl.get("sea_level_rise_mm") is not None:
        lines.append(f"Sea level rise: +{sl['sea_level_rise_mm']} mm vs 1993")

    wb = ind.get("world_bank", {})
    if wb.get("population_billions"):
        lines.append(f"World population: {wb['population_billions']:.3f} B")
    if wb.get("poverty_190_pct") is not None:
        lines.append(f"Extreme poverty (<$1.90/day): {wb['poverty_190_pct']:.2f}%")
    if wb.get("life_expectancy"):
        lines.append(f"Life expectancy: {wb['life_expectancy']:.1f} yrs")
    if wb.get("gini_mean"):
        lines.append(f"Gini (global mean): {wb['gini_mean']:.1f}")
    if wb.get("forest_area_pct"):
        lines.append(f"Forest area: {wb['forest_area_pct']:.1f}% of land")
    if wb.get("renewable_elec_pct"):
        lines.append(f"Renewable electricity: {wb['renewable_elec_pct']:.1f}%")
    if wb.get("safe_water_access_pct"):
        lines.append(f"Safe water access: {wb['safe_water_access_pct']:.1f}%")
    if wb.get("threatened_mammals_no"):
        lines.append(f"Threatened mammal species: {int(wb['threatened_mammals_no'])}")

    bio = ind.get("biodiversity", {})
    if bio.get("species_observations_30d"):
        lines.append(f"GBIF species observations (30d): {bio['species_observations_30d']:,}")

    conf = ind.get("conflicts", {})
    if conf.get("active_armed_conflicts") is not None:
        lines.append(f"Active armed conflicts (UCDP): {conf['active_armed_conflicts']}")

    nuc = ind.get("nuclear", {})
    if nuc.get("nuclear_warheads_total"):
        lines.append(
            f"Nuclear warheads (SIPRI {nuc.get('source_year',2024)}): "
            f"{nuc['nuclear_warheads_total']:,} total, "
            f"{nuc.get('nuclear_warheads_on_alert',0):,} on alert"
        )

    lines.append("──────────────────────────────────────────────────────────")
    return "\n".join(lines)
