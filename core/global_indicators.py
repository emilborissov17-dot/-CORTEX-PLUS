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
  UNHCR Population API     — forcibly displaced persons (refugees, IDPs, stateless)
  NASA Exoplanet Archive   — confirmed exoplanet count (TAP, no key)
  CelesTrak SATCAT         — active satellites in Earth orbit (no key)
  EIA Open Data            — US total primary energy (optional EIA_API_KEY env var)
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta, timezone
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
# 8. Forcibly displaced persons — UNHCR Population API v1 (no key)
# ---------------------------------------------------------------------------

def fetch_unhcr() -> dict:
    """Refugees, asylum seekers, IDPs and stateless persons (UNHCR, latest year)."""
    data = _get(
        "https://api.unhcr.org/population/v1/population/",
        params={"yearFrom": 2022, "yearTo": 2023, "cf_type": "ISO", "limit": 1},
        timeout=25,
    )
    if not data or not isinstance(data, dict):
        return {}
    items = data.get("items") or []
    if not items:
        return {}
    row = items[0]
    def _m(key: str) -> Optional[float]:
        v = row.get(key)
        return round(float(v) / 1e6, 3) if v else None
    return {
        "refugees_millions":       _m("refugees"),
        "asylum_seekers_millions": _m("asylum_seekers"),
        "idps_millions":           _m("idps"),
        "stateless_millions":      _m("stateless"),
        "unhcr_year":              row.get("year"),
    }


# ---------------------------------------------------------------------------
# 9. Confirmed exoplanets — NASA Exoplanet Archive TAP (no key)
# ---------------------------------------------------------------------------

def fetch_exoplanets() -> dict:
    """Count of confirmed exoplanets from NASA Exoplanet Archive (TAP service)."""
    data = _get(
        "https://exoplanetarchive.ipac.caltech.edu/TAP/sync",
        params={
            "query":  "select count(pl_name) from ps where default_flag=1",
            "format": "json",
        },
        timeout=30,
    )
    if not data or not isinstance(data, list) or not data:
        return {}
    row = data[0]
    count = next((v for v in row.values() if isinstance(v, (int, float))), None)
    return {"confirmed_exoplanets": int(count)} if count is not None else {}


# ---------------------------------------------------------------------------
# 10. Active satellites — CelesTrak SATCAT (no key)
# ---------------------------------------------------------------------------

def fetch_satellites() -> dict:
    """Active payload objects in Earth orbit — CelesTrak SATCAT."""
    data = _get(
        "https://celestrak.org/satcat/records.php",
        params={"STATUS": "A", "OBJECT_TYPE": "PAYLOAD", "FORMAT": "JSON"},
        timeout=30,
    )
    if not data or not isinstance(data, list):
        return {}
    return {
        "active_satellites":        len(data),
        "satellites_source":        "CelesTrak SATCAT",
    }


# ---------------------------------------------------------------------------
# 11. Energy — EIA Open Data (free key via EIA_API_KEY env var; skips if absent)
# ---------------------------------------------------------------------------

def fetch_eia() -> dict:
    """US total primary energy consumption (quadrillion BTU) — EIA API v2."""
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        return {}
    data = _get(
        "https://api.eia.gov/v2/total-energy/data/",
        params={
            "frequency":              "annual",
            "data[0]":                "value",
            "facets[msn][]":          "TPCIUS",   # Total Primary Energy Consumption, US
            "sort[0][column]":        "period",
            "sort[0][direction]":     "desc",
            "offset":                 0,
            "length":                 1,
            "api_key":                key,
        },
        timeout=25,
    )
    if not data or not isinstance(data, dict):
        return {}
    rows = (data.get("response") or {}).get("data") or []
    if not rows:
        return {}
    row = rows[0]
    try:
        return {
            "us_primary_energy_quad_btu": round(float(row["value"]), 2),
            "us_primary_energy_year":     int(row["period"]),
            "eia_unit":                   row.get("unit", "Quadrillion Btu"),
        }
    except (KeyError, ValueError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# 12. Culture & media — GDELT DOC 2.0 (no key)
# ---------------------------------------------------------------------------

def fetch_gdelt() -> dict:
    """Global news tone/sentiment — GDELT DOC 2.0 API (no key, 65 languages)."""
    raw = _get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query":    "news",
            "mode":     "timelinetone",
            "timespan": "1month",
            "format":   "json",
        },
        timeout=30,
    )
    # Response shape: {"timeline": [{"series": "Average Tone", "data": [{date, value}, ...]}]}
    rows: list = []
    if isinstance(raw, dict):
        for series_obj in (raw.get("timeline") or []):
            rows.extend(series_obj.get("data") or [])
        if not rows:
            rows = raw.get("data") or []
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            for series_obj in (parsed.get("timeline") or []):
                rows.extend(series_obj.get("data") or [])
            if not rows:
                rows = parsed.get("data") or []
        except Exception:
            return {}
    if not rows:
        return {}
    values = []
    for r in rows:
        if isinstance(r, dict):
            try:
                values.append(float(r["value"]))
            except (KeyError, TypeError, ValueError):
                pass
    if not values:
        return {}
    return {
        "news_tone_avg_1month":  round(sum(values) / len(values), 3),
        "news_tone_latest":      round(values[-1], 3),
        "news_tone_min":         round(min(values), 3),
        "news_tone_max":         round(max(values), 3),
        "news_tone_datapoints":  len(values),
        "news_tone_scale":       "-100=very negative, 0=neutral, +100=very positive",
    }


# ---------------------------------------------------------------------------
# 13. Food security — World Bank WDI (no key)
# ---------------------------------------------------------------------------

def fetch_food() -> dict:
    """Undernourishment, food insecurity and production — World Bank WDI."""
    gdp_food_pct = _wb_world("NV.AGR.TOTL.ZS")   # Agriculture % of GDP (structural proxy)
    food_prod    = _wb_world("AG.PRD.FOOD.XD")    # Food production index (2014-16=100)
    return {
        "undernourishment_pct":          _wb_world("SN.ITK.DEFC.ZS"),
        "food_insecurity_moderate_severe_pct": _wb_world("SN.ITK.MSFI.ZS"),
        "food_production_index":         food_prod,
        "agriculture_pct_gdp":           gdp_food_pct,
        "cereal_yield_kg_per_ha":        _wb_world("AG.YLD.CREL.KG"),
    }


# ---------------------------------------------------------------------------
# 14. Materials & waste — UN SDG API + World Bank (no key)
# ---------------------------------------------------------------------------

def fetch_waste() -> dict:
    """Resource depletion and material throughput proxies — World Bank WDI.
    Note: UN SDG e-waste series (EN_EWT_ELECTR) has no data in the SDG API
    as of 2026; UNEP/ITU publish static reports instead.
    """
    return {
        "resource_depletion_pct_gni":   _wb_world("NY.ADJ.DRES.GN.ZS"),
        "natural_resources_rents_pct":  _wb_world("NY.GDP.TOTL.RT.ZS"),
        "adjusted_net_savings_pct":     _wb_world("NY.ADJ.SVNG.GN.ZS"),
        "fossil_fuel_consumption_pct":  _wb_world("EG.USE.COMM.FO.ZS"),
    }


# ---------------------------------------------------------------------------
# 15. Economy & work — World Bank WDI (no key)
# ---------------------------------------------------------------------------

def fetch_economy() -> dict:
    """Unemployment, GDP per capita, growth — World Bank WDI."""
    gdp_pc = _wb_world("NY.GDP.PCAP.PP.KD")   # constant 2017 USD, PPP
    return {
        "unemployment_pct":              _wb_world("SL.UEM.TOTL.ZS"),
        "gdp_per_capita_ppp_usd":        round(gdp_pc) if gdp_pc else None,
        "gdp_growth_annual_pct":         _wb_world("NY.GDP.MKTP.KD.ZG"),
        "labour_force_participation_pct": _wb_world("SL.TLF.CACT.ZS"),
        "industry_value_added_pct_gdp":  _wb_world("NV.IND.TOTL.ZS"),
    }


# ---------------------------------------------------------------------------
# 16. Infrastructure & cities — World Bank WDI (no key)
# ---------------------------------------------------------------------------

def fetch_cities() -> dict:
    """Urban access to electricity, internet, and urbanisation — World Bank."""
    return {
        "internet_users_pct":      _wb_world("IT.NET.USER.ZS"),
        "electricity_access_pct":  _wb_world("EG.ELC.ACCS.ZS"),
        "urban_population_pct":    _wb_world("SP.URB.TOTL.IN.ZS"),
        "urban_growth_annual_pct": _wb_world("SP.URB.GROW"),
        # IS.ROD.PAVE.ZS has no WLD aggregate → use cross-country mean
        "roads_paved_pct":         _wb_global_mean("IS.ROD.PAVE.ZS"),
    }


# ---------------------------------------------------------------------------
# 17. Governance — World Bank Worldwide Governance Indicators (WGI, no key)
# ---------------------------------------------------------------------------

def fetch_governance() -> dict:
    """
    World Bank Worldwide Governance Indicators (WGI) — global means.
    Scale: -2.5 (worst) to +2.5 (best). Country-level estimates; WLD aggregate
    does not exist, so we compute an unweighted mean across all reporting countries.

    ProACT (World Bank Procurement Analytics) requires WBG login.
    Open Contracting Partnership (OCDS) has no single public global API —
    data is per-country (Prozorro, Mercado Público, etc.); no infrastructure
    deficiency metric is available without authentication.
    """
    # WGI uses GOV_WGI_ prefix in the standard v2 API (source ID 3)
    return {
        "ge_est": _wb_global_mean("GOV_WGI_GE.EST"),   # Government Effectiveness
        "cc_est": _wb_global_mean("GOV_WGI_CC.EST"),   # Control of Corruption
        "rl_est": _wb_global_mean("GOV_WGI_RL.EST"),   # Rule of Law
    }


# ---------------------------------------------------------------------------
# 18. Technology infrastructure — World Bank WDI (no key)
# ---------------------------------------------------------------------------

def fetch_tech_infra() -> dict:
    """Digital connectivity — fixed broadband, mobile, secure servers (WB WDI)."""
    return {
        "broadband_per100":              _wb_world("IT.NET.BBND.P2"),
        "mobile_subscriptions_per100":   _wb_world("IT.CEL.SETS.P2"),
        "secure_internet_servers_per1m": _wb_world("IT.NET.SECR.P6"),
        "high_tech_exports_pct_manuf":   _wb_world("TX.VAL.TECH.MF.ZS"),
    }


# ---------------------------------------------------------------------------
# 18. AI & technology activity — arXiv API + Hugging Face Hub (no key)
# ---------------------------------------------------------------------------

def fetch_ai_activity() -> dict:
    """AI research output — arXiv cs.AI paper count + GitHub AI repo count (no key)."""
    # arXiv: total cs.AI papers (Atom XML); max_results=1 required — 0 returns 500
    arxiv_total: Optional[int] = None
    xml_text = _get(
        "https://export.arxiv.org/api/query",
        params={"search_query": "cat:cs.AI", "max_results": 1},
        timeout=30,
    )
    if xml_text and isinstance(xml_text, str):
        try:
            root = ET.fromstring(xml_text)
            ns   = {"os": "http://a9.com/-/spec/opensearch/1.1/"}
            el   = root.find("os:totalResults", ns)
            if el is not None and el.text:
                arxiv_total = int(el.text)
        except Exception:
            pass

    # GitHub Search: AI-tagged repositories (no auth, 10 req/min limit)
    github_ai_repos: Optional[int] = None
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            params={"q": "topic:artificial-intelligence", "per_page": 1},
            headers={"Accept": "application/vnd.github+json"},
            timeout=20,
        )
        if r.status_code == 200:
            github_ai_repos = int(r.json().get("total_count", 0)) or None
    except Exception:
        pass

    return {
        "arxiv_ai_papers_total":  arxiv_total,
        "github_ai_repos_total":  github_ai_repos,
    }


# ---------------------------------------------------------------------------
# 19. Near-Earth Objects — NASA JPL CAD API (no key)
# ---------------------------------------------------------------------------

def fetch_neo() -> dict:
    """Near-Earth Object close approaches — NASA JPL CNEOS CAD API (no key)."""
    today_str = date.today().isoformat()
    data = _get(
        "https://ssd-api.jpl.nasa.gov/cad.api",
        params={
            "dist-max":  "0.1",    # within 0.1 AU (~15 million km)
            "date-min":  today_str,
            "date-max":  "+90",    # next 90 days
            "sort":      "dist",
        },
        timeout=30,
    )
    if not data or not isinstance(data, dict):
        return {}

    total_approaches = int(data.get("count", 0))

    # Count objects passing within 1 Lunar Distance (≈ 0.00257 AU)
    within_ld = 0
    for row in (data.get("data") or []):
        try:
            if float(row[4]) < 0.00257:
                within_ld += 1
        except (IndexError, TypeError, ValueError):
            pass

    return {
        "neo_close_approaches_90d": total_approaches,   # within 0.1 AU
        "neo_within_lunar_dist_90d": within_ld,         # within 1 Lunar Distance
        "neo_dist_threshold_au":    0.1,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_SECTIONS = [
    # ── Climate / Planet ──────────────────────────────────────────────────
    ("co2",          fetch_co2,          "NOAA Mauna Loa CO2"),
    ("temperature",  fetch_gistemp,      "NASA GISTEMP"),
    ("sea_level",    fetch_sea_level,    "NOAA Satellite Altimetry"),
    ("biodiversity", fetch_gbif,         "GBIF"),
    ("food",         fetch_food,         "World Bank WDI — Food"),
    ("waste",        fetch_waste,        "UN SDG + World Bank — Waste"),
    # ── Human / Civilization ─────────────────────────────────────────────
    ("world_bank",   fetch_world_bank,   "World Bank WDI — Core"),
    ("displaced",    fetch_unhcr,        "UNHCR Population API"),
    ("economy",      fetch_economy,      "World Bank WDI — Economy"),
    ("cities",       fetch_cities,       "World Bank WDI — Cities"),
    ("governance",   fetch_governance,   "World Bank WGI — Governance"),
    ("tech_infra",   fetch_tech_infra,   "World Bank WDI — Tech Infra"),
    ("ai_activity",  fetch_ai_activity,  "arXiv + Hugging Face Hub"),
    ("media",        fetch_gdelt,        "GDELT DOC 2.0"),
    # ── Conflict / Security ───────────────────────────────────────────────
    ("conflicts",    fetch_ucdp,         "UCDP"),
    ("nuclear",      fetch_nuclear,      "SIPRI 2024"),
    ("energy",       fetch_eia,          "EIA Open Data"),
    # ── Cosmos ────────────────────────────────────────────────────────────
    ("exoplanets",   fetch_exoplanets,   "NASA Exoplanet Archive TAP"),
    ("satellites",   fetch_satellites,   "CelesTrak SATCAT"),
    ("neo",          fetch_neo,          "NASA JPL CNEOS CAD"),
]


def fetch_all() -> dict:
    """Fetch all global indicators. Prints progress. Returns full dict."""
    print("[GI] Fetching global indicators from 20 sources...")
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

    dis = ind.get("displaced", {})
    if dis.get("refugees_millions") is not None:
        lines.append(
            f"Forcibly displaced (UNHCR {dis.get('unhcr_year','')}): "
            f"{dis['refugees_millions']:.1f}M refugees, "
            f"{dis.get('idps_millions', 0) or 0:.1f}M IDPs, "
            f"{dis.get('asylum_seekers_millions', 0) or 0:.1f}M asylum seekers"
        )
    if dis.get("stateless_millions") is not None:
        lines.append(f"  Stateless persons: {dis['stateless_millions']:.2f}M")

    exo = ind.get("exoplanets", {})
    if exo.get("confirmed_exoplanets"):
        lines.append(f"Confirmed exoplanets (NASA Archive): {exo['confirmed_exoplanets']:,}")

    sat = ind.get("satellites", {})
    if sat.get("active_satellites"):
        lines.append(f"Active satellites in orbit (CelesTrak): {sat['active_satellites']:,}")

    eia = ind.get("energy", {})
    if eia.get("us_primary_energy_quad_btu"):
        lines.append(
            f"US primary energy ({eia.get('us_primary_energy_year','')}): "
            f"{eia['us_primary_energy_quad_btu']} quad BTU (EIA)"
        )

    # ── Food ──────────────────────────────────────────────────────────────
    food = ind.get("food", {})
    if food.get("undernourishment_pct") is not None:
        lines.append(f"Undernourishment: {food['undernourishment_pct']:.2f}% of population")
    if food.get("food_insecurity_moderate_severe_pct") is not None:
        lines.append(
            f"Food insecurity (moderate+severe): "
            f"{food['food_insecurity_moderate_severe_pct']:.1f}%"
        )
    if food.get("food_production_index") is not None:
        lines.append(f"Food production index: {food['food_production_index']:.1f} (2014-16=100)")

    # ── Materials / waste ─────────────────────────────────────────────────
    waste = ind.get("waste", {})
    if waste.get("resource_depletion_pct_gni") is not None:
        lines.append(
            f"Natural resource depletion: {waste['resource_depletion_pct_gni']:.2f}% of GNI"
        )
    if waste.get("natural_resources_rents_pct") is not None:
        lines.append(
            f"Natural resources rents: {waste['natural_resources_rents_pct']:.2f}% of GDP"
        )
    if waste.get("adjusted_net_savings_pct") is not None:
        lines.append(f"Adjusted net savings: {waste['adjusted_net_savings_pct']:.2f}% of GNI")

    # ── Economy & work ────────────────────────────────────────────────────
    econ = ind.get("economy", {})
    if econ.get("unemployment_pct") is not None:
        lines.append(f"Global unemployment: {econ['unemployment_pct']:.2f}%")
    if econ.get("gdp_per_capita_ppp_usd") is not None:
        lines.append(
            f"GDP per capita PPP: ${econ['gdp_per_capita_ppp_usd']:,} (constant 2017 USD)"
        )
    if econ.get("gdp_growth_annual_pct") is not None:
        lines.append(f"GDP growth: {econ['gdp_growth_annual_pct']:.2f}% annual")

    # ── Governance (WGI) ─────────────────────────────────────────────────
    gov = ind.get("governance", {})
    if gov.get("ge_est") is not None:
        cc  = f"{gov['cc_est']:+.3f}" if gov.get("cc_est") is not None else "N/A"
        rl  = f"{gov['rl_est']:+.3f}" if gov.get("rl_est") is not None else "N/A"
        lines.append(
            f"Govt Effectiveness (WGI GE.EST): {gov['ge_est']:+.3f}"
            f"  |  Corruption Control (CC.EST): {cc}"
            f"  |  Rule of Law (RL.EST): {rl}"
        )

    # ── Infrastructure & cities ───────────────────────────────────────────
    cities = ind.get("cities", {})
    if cities.get("internet_users_pct") is not None:
        lines.append(f"Internet users: {cities['internet_users_pct']:.1f}% of population")
    if cities.get("electricity_access_pct") is not None:
        lines.append(f"Electricity access: {cities['electricity_access_pct']:.1f}%")
    if cities.get("urban_population_pct") is not None:
        lines.append(f"Urban population: {cities['urban_population_pct']:.1f}%")

    # ── Technology infrastructure ─────────────────────────────────────────
    ti = ind.get("tech_infra", {})
    if ti.get("broadband_per100") is not None:
        lines.append(f"Fixed broadband: {ti['broadband_per100']:.1f} per 100 people")
    if ti.get("mobile_subscriptions_per100") is not None:
        lines.append(f"Mobile subscriptions: {ti['mobile_subscriptions_per100']:.0f} per 100")

    # ── AI activity ───────────────────────────────────────────────────────
    ai = ind.get("ai_activity", {})
    if ai.get("arxiv_ai_papers_total") is not None:
        lines.append(f"arXiv cs.AI papers total: {ai['arxiv_ai_papers_total']:,}")
    if ai.get("github_ai_repos_total") is not None:
        lines.append(f"GitHub AI repos (topic:artificial-intelligence): {ai['github_ai_repos_total']:,}")

    # ── Culture / media ───────────────────────────────────────────────────
    media = ind.get("media", {})
    if media.get("news_tone_avg_1month") is not None:
        lines.append(
            f"Global news tone (GDELT 1mo): {media['news_tone_avg_1month']:+.2f} "
            f"(latest: {media.get('news_tone_latest', '?'):+})"
        )

    # ── NEO / Cosmic resources ────────────────────────────────────────────
    neo = ind.get("neo", {})
    if neo.get("neo_close_approaches_90d") is not None:
        lines.append(
            f"NEO close approaches 90d (≤0.1 AU): {neo['neo_close_approaches_90d']}"
            + (
                f", within lunar dist: {neo['neo_within_lunar_dist_90d']}"
                if neo.get("neo_within_lunar_dist_90d") is not None
                else ""
            )
        )

    lines.append("──────────────────────────────────────────────────────────")
    return "\n".join(lines)
