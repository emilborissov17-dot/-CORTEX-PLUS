#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_source_audit.py
Coverage audit: maps every axis from agi_axes_spec.txt to real API data
in core/global_indicators.py.

Status values:
  HAS_API  — axis has ≥1 live, real-time API metric
  PARTIAL  — axis has some data, but key signals are absent
  MISSING  — no API coverage at all
  N/A      — internal/derived axis; external API not applicable

Coverage snapshot (19 sources, 22 axes):
  HAS_API : 12  (CLIMATE, ECOSYSTEMS, INEQUALITY, SPACE_INFRA, FOOD, MATERIALS,
                  ECONOMY, CITIES, TECH_INFRA, TECHNOLOGY_AI, COSMIC_RESOURCES, LONG_TERM*)
  PARTIAL :  8  (HUMAN_WB, CULTURE_MEDIA, ENERGY, WATER, PLANETARY, GOVERNANCE,
                  EDUCATION, DEEP_TIME)
  MISSING :  0  — all substantive axes now have ≥1 live API
  N/A     :  2  (GENERAL_SELF_REVIEW, GOAL_PROGRESS_REVIEW — internal/derived)

Run:
    python data_source_audit.py
    python data_source_audit.py --missing-only
    python data_source_audit.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError with box-drawing chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ── Status constants ─────────────────────────────────────────────────────────

HAS_API = "HAS_API"
PARTIAL  = "PARTIAL"
MISSING  = "MISSING"
NA       = "N/A"


# ── Registry: one entry per axis ─────────────────────────────────────────────

REGISTRY: list[dict[str, Any]] = [

    # ── HUMAN ─────────────────────────────────────────────────────────────

    {
        "name":   "HUMAN_WELL_BEING_REVIEW",
        "label":  "Човешко благосъстояние",
        "group":  "HUMAN",
        "status": PARTIAL,
        "gi_sources": [
            "World Bank WDI — life_expectancy, infant_mortality_per1k, "
            "population_billions, safe_water_access_pct",
            "UNHCR Population API — refugees_millions, idps_millions, "
            "asylum_seekers_millions",
        ],
        "gi_keys": [
            "world_bank.life_expectancy",
            "world_bank.infant_mortality_per1k",
            "world_bank.safe_water_access_pct",
            "displaced.refugees_millions",
        ],
        "missing_signals": [
            "mental health workforce / burden (DALYs)",
            "global happiness / wellbeing index",
            "suicide rate per 100k",
            "universal health coverage index",
        ],
        "suggested_apis": [
            {
                "label":        "WHO GHO — Mental Health (psychiatrists per 100k)",
                "url":          "https://ghoapi.azureedge.net/api/MH_12",
                "params":       {},
                "key_required": False,
                "measures":     "Psychiatrists in mental health sector per 100 000 population",
            },
            {
                "label":        "WHO GHO — Universal Health Coverage Index",
                "url":          "https://ghoapi.azureedge.net/api/UHC_INDEX_REPORTED",
                "params":       {},
                "key_required": False,
                "measures":     "UHC Service Coverage Index (0–100)",
            },
        ],
    },

    {
        "name":   "CULTURE_MEDIA_REVIEW",
        "label":  "Култура и медии",
        "group":  "HUMAN",
        "status": PARTIAL,
        "gi_sources": [
            "GDELT DOC 2.0 — media.news_tone_avg_1month, news_tone_latest, "
            "news_tone_min, news_tone_max (65-language global coverage, 1-month window)",
        ],
        "gi_keys": [
            "media.news_tone_avg_1month",
            "media.news_tone_latest",
            "media.news_tone_min",
            "media.news_tone_max",
        ],
        "missing_signals": [
            "disinformation / misinformation index",
            "press freedom index (Reporters Without Borders)",
            "media ownership concentration",
            "social media toxicity score",
        ],
        "suggested_apis": [
            {
                "label":        "GDELT GEG 2.0 — Thematic news geographic spread",
                "url":          "https://api.gdeltproject.org/api/v2/geo/geo",
                "params":       {"query": "theme:EDUCATION", "format": "json"},
                "key_required": False,
                "measures":     "Geographic distribution of thematic news coverage across 65 languages",
                "note":         "Rate-limited to 1 req/5s — already handled gracefully in fetch_gdelt()",
            },
        ],
    },

    # ── PLANET ────────────────────────────────────────────────────────────

    {
        "name":   "CLIMATE_GLOBAL_RISK_REVIEW",
        "label":  "Глобален климатичен риск",
        "group":  "PLANET",
        "status": HAS_API,
        "gi_sources": [
            "NOAA Mauna Loa — co2_ppm, co2_annual_increase",
            "NASA GISTEMP   — temp_anomaly_c (vs 1951-1980 baseline)",
            "CU Boulder     — sea_level_rise_mm (vs 1993 baseline)",
            "World Bank WDI — co2_emissions_kt",
        ],
        "gi_keys": [
            "co2.co2_ppm",
            "co2.co2_annual_increase",
            "temperature.temp_anomaly_c",
            "sea_level.sea_level_rise_mm",
            "world_bank.co2_emissions_kt",
        ],
        "missing_signals": [
            "methane (CH4) concentration",
            "Arctic sea ice extent",
            "extreme weather event frequency",
        ],
        "suggested_apis": [
            {
                "label":        "NOAA GML — CH4 weekly (Mauna Loa)",
                "url":          "https://gml.noaa.gov/webdata/ccgg/trends/ch4/ch4_weekly_mlo.csv",
                "params":       {},
                "key_required": False,
                "measures":     "Atmospheric methane (CH4) in ppb, weekly",
            },
        ],
    },

    {
        "name":   "ENERGY_REVIEW",
        "label":  "Енергийна система",
        "group":  "PLANET",
        "status": PARTIAL,
        "gi_sources": [
            "World Bank WDI — renewable_elec_pct (EG.ELC.RNEW.ZS)",
            "EIA Open Data  — us_primary_energy_quad_btu (optional key)",
        ],
        "gi_keys": [
            "world_bank.renewable_elec_pct",
            "energy.us_primary_energy_quad_btu",
        ],
        "missing_signals": [
            "global fossil fuel share of primary energy",
            "global energy intensity (MJ / USD GDP)",
            "coal consumption trend",
            "per-capita energy use",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — Fossil fuel energy consumption %",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/EG.USE.COMM.FO.ZS",
                "params":       {"format": "json", "mrv": 3},
                "key_required": False,
                "measures":     "Fossil fuel energy consumption as % of total (coal+oil+gas)",
            },
            {
                "label":        "World Bank WDI — Energy use per capita (kg oil equiv)",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/EG.USE.PCAP.KG.OE",
                "params":       {"format": "json", "mrv": 3},
                "key_required": False,
                "measures":     "Energy use per capita in kg of oil equivalent",
            },
        ],
    },

    {
        "name":   "FOOD_REVIEW",
        "label":  "Хранителни системи",
        "group":  "PLANET",
        "status": HAS_API,
        "gi_sources": [
            "World Bank WDI (fetch_food) — undernourishment_pct (SN.ITK.DEFC.ZS), "
            "food_production_index (AG.PRD.FOOD.XD), cereal_yield_kg_per_ha (AG.YLD.CREL.KG), "
            "agriculture_pct_gdp (NV.AGR.TOTL.ZS)",
        ],
        "gi_keys": [
            "food.undernourishment_pct",
            "food.food_production_index",
            "food.cereal_yield_kg_per_ha",
            "food.agriculture_pct_gdp",
        ],
        "missing_signals": [
            "food price volatility index (FAO FFPI)",
            "number of people in acute food crisis (IPC Phase 3+)",
            "food waste as % of production",
            "food_insecurity_moderate_severe_pct — WB indicator SN.ITK.MSFI.ZS "
            "returns null at world aggregate level",
        ],
        "suggested_apis": [
            {
                "label":        "FAO FAOSTAT — Food price indices (FFPI)",
                "url":          "https://fenixservices.fao.org/faostat/api/v1/en/data/CP",
                "params":       {"element": "5532", "area": "5000", "year": "L", "output_type": "objects"},
                "key_required": False,
                "measures":     "FAO Food Price Index (FFPI) — composite commodity price signal",
            },
        ],
    },

    {
        "name":   "WATER_REVIEW",
        "label":  "Водни системи",
        "group":  "PLANET",
        "status": PARTIAL,
        "gi_sources": [
            "World Bank WDI — safe_water_access_pct (SH.H2O.SMDW.ZS)",
        ],
        "gi_keys": [
            "world_bank.safe_water_access_pct",
        ],
        "missing_signals": [
            "freshwater withdrawals as % of available resources (water stress)",
            "global sanitation access %",
            "number of people without safe sanitation",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — Annual freshwater withdrawals %",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/ER.H2O.FWTL.ZS",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Annual freshwater withdrawals as % of total freshwater resources",
            },
            {
                "label":        "World Bank WDI — Safely managed sanitation %",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/SH.STA.SMSS.ZS",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "% population using safely managed sanitation services",
            },
        ],
    },

    {
        "name":   "MATERIALS_WASTE_REVIEW",
        "label":  "Материали и отпадъци",
        "group":  "PLANET",
        "status": HAS_API,
        "gi_sources": [
            "World Bank WDI (fetch_waste) — resource_depletion_pct_gni (NY.ADJ.DRES.GN.ZS), "
            "natural_resources_rents_pct (NY.GDP.TOTL.RT.ZS), "
            "adjusted_net_savings_pct (NY.ADJ.SVNG.GN.ZS), "
            "fossil_fuel_consumption_pct (EG.USE.COMM.FO.ZS)",
        ],
        "gi_keys": [
            "waste.resource_depletion_pct_gni",
            "waste.natural_resources_rents_pct",
            "waste.adjusted_net_savings_pct",
            "waste.fossil_fuel_consumption_pct",
        ],
        "missing_signals": [
            "e-waste per capita (kg) — UN SDG series EN_EWT_ELECTR has no world "
            "aggregate in API; UNEP/ITU publish static annual reports only",
            "municipal solid waste per capita",
            "recycling rate %",
            "material footprint per capita (UNEP)",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — Adjusted net savings (pollution damage incl.)",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/NY.ADJ.SVNX.GN.ZS",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Adjusted net savings excl. particulate emission damage — complement to NY.ADJ.SVNG",
            },
        ],
    },

    {
        "name":   "ECOSYSTEMS_BIODIVERSITY_REVIEW",
        "label":  "Екосистеми и биоразнообразие",
        "group":  "PLANET",
        "status": HAS_API,
        "gi_sources": [
            "GBIF        — species_observations_30d",
            "World Bank  — forest_area_pct, threatened_mammals_no",
        ],
        "gi_keys": [
            "biodiversity.species_observations_30d",
            "world_bank.forest_area_pct",
            "world_bank.threatened_mammals_no",
        ],
        "missing_signals": [
            "Living Planet Index trend",
            "coral reef health index",
            "deforestation rate (ha/yr)",
        ],
        "suggested_apis": [
            {
                "label":        "GBIF — Endangered species records (last 30d)",
                "url":          "https://api.gbif.org/v1/occurrence/search",
                "params":       {
                    "threatStatus": "ENDANGERED",
                    "limit":        0,
                },
                "key_required": False,
                "measures":     "GBIF occurrence count for IUCN-Endangered species",
            },
        ],
    },

    {
        "name":   "PLANETARY_POTENTIAL_REVIEW",
        "label":  "Планетарен потенциал (мета-ос)",
        "group":  "PLANET",
        "status": PARTIAL,
        "gi_sources": [
            "Composite of CLIMATE, ENERGY, FOOD, WATER, MATERIALS_WASTE, ECOSYSTEMS sub-axes",
            "Proxy signal now available: waste.adjusted_net_savings_pct (NY.ADJ.SVNG.GN.ZS) "
            "and waste.resource_depletion_pct_gni (NY.ADJ.DRES.GN.ZS)",
        ],
        "gi_keys": [
            "waste.adjusted_net_savings_pct",
            "waste.resource_depletion_pct_gni",
        ],
        "missing_signals": [
            "Planetary Boundaries composite index (no public API — Stockholm Resilience Centre)",
            "Earth System Model state outputs (requires specialised scientific APIs)",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank — Adjusted net savings excl. particulate emission damage",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/NY.ADJ.SVNX.GN.ZS",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Complement to adjusted_net_savings — without particulate emission damage component",
            },
        ],
    },

    # ── CIVILIZATION ──────────────────────────────────────────────────────

    {
        "name":   "ECONOMY_WORK_REVIEW",
        "label":  "Икономика и труд",
        "group":  "CIVILIZATION",
        "status": HAS_API,
        "gi_sources": [
            "World Bank WDI (fetch_economy) — unemployment_pct (SL.UEM.TOTL.ZS), "
            "gdp_per_capita_ppp_usd (NY.GDP.PCAP.PP.KD), "
            "gdp_growth_annual_pct (NY.GDP.MKTP.KD.ZG), "
            "labour_force_participation_pct (SL.TLF.CACT.ZS), "
            "industry_value_added_pct_gdp (NV.IND.TOTL.ZS)",
        ],
        "gi_keys": [
            "economy.unemployment_pct",
            "economy.gdp_per_capita_ppp_usd",
            "economy.gdp_growth_annual_pct",
            "economy.labour_force_participation_pct",
            "economy.industry_value_added_pct_gdp",
        ],
        "missing_signals": [
            "labour share of income / GDP %",
            "informal employment % of total employment",
            "automation / robot adoption rate",
            "real wage growth index",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — Labour share of GDP (compensation of employees %)",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/SL.EMP.MPYR.ZS",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Employers as % of employment (proxy for labour market structure)",
            },
        ],
    },

    {
        "name":   "INEQUALITY_POVERTY_REVIEW",
        "label":  "Неравенства и бедност",
        "group":  "CIVILIZATION",
        "status": HAS_API,
        "gi_sources": [
            "World Bank WDI — poverty_190_pct (SI.POV.DDAY), gini_mean (SI.POV.GINI)",
            "UNHCR          — refugees_millions, idps_millions (as forced displacement signal)",
        ],
        "gi_keys": [
            "world_bank.poverty_190_pct",
            "world_bank.gini_mean",
            "displaced.refugees_millions",
        ],
        "missing_signals": [
            "top-1% wealth share",
            "multidimensional poverty index (MPI)",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — Multidimensional poverty headcount %",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/SI.POV.MDIM",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Multidimensional poverty headcount ratio (MPI method) %",
            },
        ],
    },

    {
        "name":   "INFRASTRUCTURE_CITIES_REVIEW",
        "label":  "Инфраструктура и градове",
        "group":  "CIVILIZATION",
        "status": HAS_API,
        "gi_sources": [
            "World Bank WDI (fetch_cities) — internet_users_pct (IT.NET.USER.ZS), "
            "electricity_access_pct (EG.ELC.ACCS.ZS), "
            "urban_population_pct (SP.URB.TOTL.IN.ZS), "
            "urban_growth_annual_pct (SP.URB.GROW), "
            "roads_paved_pct (IS.ROD.PAVE.ZS)",
        ],
        "gi_keys": [
            "cities.internet_users_pct",
            "cities.electricity_access_pct",
            "cities.urban_population_pct",
            "cities.urban_growth_annual_pct",
            "cities.roads_paved_pct",
        ],
        "missing_signals": [
            "public transport coverage / modal split",
            "air quality index (PM2.5 exposure)",
            "housing affordability index",
            "water and sanitation in cities %",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — PM2.5 air pollution mean annual exposure",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/EN.ATM.PM25.MC.M3",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Population-weighted mean annual exposure to PM2.5 (µg/m³)",
            },
        ],
    },

    {
        "name":   "GOVERNANCE_INSTITUTIONS_REVIEW",
        "label":  "Управление и институции",
        "group":  "CIVILIZATION",
        "status": PARTIAL,
        "gi_sources": [
            "UCDP — active_armed_conflicts (armed conflict as governance breakdown signal)",
        ],
        "gi_keys": [
            "conflicts.active_armed_conflicts",
        ],
        "missing_signals": [
            "rule of law index",
            "control of corruption estimate",
            "government effectiveness score",
            "press freedom index",
            "democracy score",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WGI — Control of Corruption estimate",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/CC.EST",
                "params":       {"format": "json", "mrv": 3},
                "key_required": False,
                "measures":     "Control of Corruption (−2.5 weak → +2.5 strong governance)",
            },
            {
                "label":        "World Bank WGI — Rule of Law estimate",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/RL.EST",
                "params":       {"format": "json", "mrv": 3},
                "key_required": False,
                "measures":     "Rule of Law estimate (−2.5 to +2.5)",
            },
            {
                "label":        "World Bank WGI — Government Effectiveness",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/GE.EST",
                "params":       {"format": "json", "mrv": 3},
                "key_required": False,
                "measures":     "Government Effectiveness estimate (−2.5 to +2.5)",
            },
        ],
    },

    {
        "name":   "EDUCATION_CULTURE_REVIEW",
        "label":  "Образование и култура",
        "group":  "CIVILIZATION",
        "status": PARTIAL,
        "gi_sources": [
            "World Bank WDI — literacy_rate_adult_pct (SE.ADT.LITR.ZS)",
        ],
        "gi_keys": [
            "world_bank.literacy_rate_adult_pct",
        ],
        "missing_signals": [
            "primary/secondary school enrollment ratio",
            "government education spending % of GDP",
            "mean years of schooling",
            "PISA average score",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — Primary school enrollment net %",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/SE.PRM.NENR",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Net enrollment ratio, primary (% of primary school-age children)",
            },
            {
                "label":        "World Bank WDI — Government education expenditure % of GDP",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/SE.XPD.TOTL.GD.ZS",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "Government expenditure on education as % of GDP",
            },
        ],
    },

    {
        "name":   "TECHNOLOGY_INFRA_REVIEW",
        "label":  "Технологични инфраструктури",
        "group":  "CIVILIZATION",
        "status": HAS_API,
        "gi_sources": [
            "World Bank WDI (fetch_tech_infra) — broadband_per100 (IT.NET.BBND.P2), "
            "mobile_subscriptions_per100 (IT.CEL.SETS.P2), "
            "secure_internet_servers_per1m (IT.NET.SECR.P6), "
            "high_tech_exports_pct_manuf (TX.VAL.TECH.MF.ZS)",
        ],
        "gi_keys": [
            "tech_infra.broadband_per100",
            "tech_infra.mobile_subscriptions_per100",
            "tech_infra.secure_internet_servers_per1m",
            "tech_infra.high_tech_exports_pct_manuf",
        ],
        "missing_signals": [
            "cloud infrastructure capacity / hyperscaler count",
            "cybersecurity incidents reported per year",
            "critical infrastructure resilience score",
            "5G coverage % of population",
        ],
        "suggested_apis": [
            {
                "label":        "World Bank WDI — ICT goods exports % of total goods exports",
                "url":          "https://api.worldbank.org/v2/country/WLD/indicator/TX.VAL.ICTG.ZS.UN",
                "params":       {"format": "json", "mrv": 5},
                "key_required": False,
                "measures":     "ICT goods exports as % of total goods exports",
            },
        ],
    },

    {
        "name":   "TECHNOLOGY_AI_REVIEW",
        "label":  "Технологии и AI/AGI",
        "group":  "CIVILIZATION",
        "status": HAS_API,
        "gi_sources": [
            "arXiv API (fetch_ai_activity) — arxiv_ai_papers_total: cumulative cs.AI paper count "
            "(Atom XML, opensearch:totalResults; max_results=1 required — 0 returns HTTP 500)",
            "GitHub Search API — github_ai_repos_total: repos tagged topic:artificial-intelligence "
            "(no auth, 10 req/min limit, uses /api/search/repositories total_count field)",
        ],
        "gi_keys": [
            "ai_activity.arxiv_ai_papers_total",
            "ai_activity.github_ai_repos_total",
        ],
        "missing_signals": [
            "AI safety incidents / near-misses (no public API)",
            "AI governance frameworks / regulations enacted count",
            "compute used for frontier model training (FLOP)",
            "Hugging Face public model count — X-Total-Count header removed from API",
        ],
        "suggested_apis": [
            {
                "label":        "arXiv API — AI safety papers (cs.AI+cs.LG, safety keywords)",
                "url":          "https://export.arxiv.org/api/query",
                "params":       {
                    "search_query": "cat:cs.AI AND ti:safety",
                    "max_results":  1,
                },
                "key_required": False,
                "measures":     "Count of AI safety-focused papers (title contains 'safety')",
            },
        ],
    },

    # ── COSMOS ────────────────────────────────────────────────────────────

    {
        "name":   "LONG_TERM_FUTURE_REVIEW",
        "label":  "Дългосрочно бъдеще и космически контекст",
        "group":  "COSMOS",
        "status": PARTIAL,
        "gi_sources": [
            "SIPRI 2024 (static) — nuclear_warheads_total, nuclear_warheads_on_alert",
            "UCDP              — active_armed_conflicts (conflict escalation risk proxy)",
        ],
        "gi_keys": [
            "nuclear.nuclear_warheads_total",
            "nuclear.nuclear_warheads_on_alert",
            "conflicts.active_armed_conflicts",
        ],
        "missing_signals": [
            "pandemic preparedness index",
            "biosecurity / dual-use research incidents",
            "existential risk composite signal",
        ],
        "suggested_apis": [
            {
                "label":        "USGS Earthquake API — Major earthquakes (M≥7) count",
                "url":          "https://earthquake.usgs.gov/fdsnws/event/1/count",
                "params":       {
                    "starttime":    "2025-01-01",
                    "minmagnitude": "7.0",
                    "format":       "geojson",
                },
                "key_required": False,
                "measures":     "Count of M≥7 earthquakes YTD (natural catastrophe monitoring proxy)",
            },
            {
                "label":        "NASA CNEOS — Close Approach NEOs (next 30 days)",
                "url":          "https://ssd-api.jpl.nasa.gov/cad.api",
                "params":       {
                    "dist-max":  "0.05",   # within 0.05 AU
                    "date-min":  "today",
                    "date-max":  "+30",
                },
                "key_required": False,
                "measures":     "Count of Near-Earth Object close approaches within 0.05 AU in next 30 days",
            },
        ],
    },

    {
        "name":   "SPACE_INFRASTRUCTURE_REVIEW",
        "label":  "Космическа инфраструктура",
        "group":  "COSMOS",
        "status": HAS_API,
        "gi_sources": [
            "CelesTrak SATCAT — active_satellites (payload objects, STATUS=A)",
        ],
        "gi_keys": [
            "satellites.active_satellites",
        ],
        "missing_signals": [
            "tracked orbital debris count",
            "active lunar / deep-space missions",
            "annual orbital launches count",
        ],
        "suggested_apis": [
            {
                "label":        "CelesTrak SATCAT — Orbital debris count",
                "url":          "https://celestrak.org/satcat/records.php",
                "params":       {"STATUS": "A", "OBJECT_TYPE": "DEBRIS", "FORMAT": "JSON"},
                "key_required": False,
                "measures":     "Count of tracked orbital debris objects (active status)",
            },
            {
                "label":        "NASA EONET — Active space-related natural events",
                "url":          "https://eonet.gsfc.nasa.gov/api/v3/events",
                "params":       {"status": "open", "limit": 50},
                "key_required": False,
                "measures":     "NASA Earth Observatory Natural Event Tracker — open events",
            },
        ],
    },

    {
        "name":   "COSMIC_RESOURCES_REVIEW",
        "label":  "Космически ресурси",
        "group":  "COSMOS",
        "status": HAS_API,
        "gi_sources": [
            "NASA JPL CNEOS CAD (fetch_neo) — neo_close_approaches_90d: NEOs within 0.1 AU "
            "in next 90 days, neo_within_lunar_dist_90d: subset within 1 Lunar Distance (≈0.00257 AU)",
            "NASA Exoplanet Archive TAP (fetch_exoplanets) — confirmed_exoplanets: "
            "total confirmed exoplanets (cosmic horizon context)",
        ],
        "gi_keys": [
            "neo.neo_close_approaches_90d",
            "neo.neo_within_lunar_dist_90d",
            "exoplanets.confirmed_exoplanets",
        ],
        "missing_signals": [
            "total catalogued Near-Earth Asteroids (NEA count from NASA SBDB)",
            "active asteroid/lunar resource missions count",
            "in-situ resource utilization (ISRU) technology readiness level",
        ],
        "suggested_apis": [
            {
                "label":        "NASA JPL Fireball API — Recent large bolide/impactor events",
                "url":          "https://ssd-api.jpl.nasa.gov/fireball.api",
                "params":       {"limit": 10, "sort": "date"},
                "key_required": False,
                "measures":     "10 most recent large fireball events (energy, lat/lon, altitude)",
            },
        ],
    },

    {
        "name":   "DEEP_TIME_RISKS_REVIEW",
        "label":  "Дълбоко-времеви рискове",
        "group":  "COSMOS",
        "status": PARTIAL,
        "gi_sources": [
            "SIPRI 2024 (static) — nuclear_warheads_total (existential risk proxy)",
            "UCDP              — active_armed_conflicts",
        ],
        "gi_keys": [
            "nuclear.nuclear_warheads_total",
        ],
        "missing_signals": [
            "major earthquake / supervolcano activity",
            "near-Earth object impact risk",
            "solar storm / geomagnetic activity (Kp index)",
            "pandemic / biorisks early warning",
        ],
        "suggested_apis": [
            {
                "label":        "USGS Earthquake API — Major earthquakes YTD (M≥7)",
                "url":          "https://earthquake.usgs.gov/fdsnws/event/1/count",
                "params":       {
                    "starttime":    "2025-01-01",
                    "minmagnitude": "7.0",
                    "format":       "geojson",
                },
                "key_required": False,
                "measures":     "Count of magnitude ≥7 earthquakes since start of year",
            },
            {
                "label":        "NASA CNEOS Fireballs — Recent large bolides",
                "url":          "https://ssd-api.jpl.nasa.gov/fireball.api",
                "params":       {"limit": 10, "sort": "date", "req-alt": "false"},
                "key_required": False,
                "measures":     "10 most recent fireball / bolide events reported to CNEOS",
            },
            {
                "label":        "NOAA SWPC — Current Kp geomagnetic index (SWEJSON)",
                "url":          "https://services.swpc.noaa.gov/json/planetary_k_index_1m.json",
                "params":       {},
                "key_required": False,
                "measures":     "Planetary K-index (geomagnetic storm level, 0=quiet, 9=extreme)",
            },
        ],
    },

    {
        "name":   "GENERAL_SELF_REVIEW",
        "label":  "Общ self-review на системата",
        "group":  "COSMOS",
        "status": NA,
        "gi_sources": ["Internal axis — no external API applicable"],
        "gi_keys":    [],
        "missing_signals": [],
        "suggested_apis": [],
    },

    {
        "name":   "GOAL_PROGRESS_REVIEW",
        "label":  "Прогрес към целта",
        "group":  "COSMOS",
        "status": NA,
        "gi_sources": ["Derived from all other axes — no external API applicable"],
        "gi_keys":    [],
        "missing_signals": [],
        "suggested_apis": [],
    },
]


# ── Formatting helpers ────────────────────────────────────────────────────────

_ANSI = {
    HAS_API: "\033[92m",   # green
    PARTIAL: "\033[93m",   # yellow
    MISSING: "\033[91m",   # red
    NA:      "\033[90m",   # grey
    "RESET": "\033[0m",
}

def _color(text: str, status: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{_ANSI.get(status, '')}{text}{_ANSI['RESET']}"


# ── Main report ───────────────────────────────────────────────────────────────

def print_coverage_table(missing_only: bool = False) -> None:
    groups: dict[str, list] = {}
    for ax in REGISTRY:
        groups.setdefault(ax["group"], []).append(ax)

    counts = {HAS_API: 0, PARTIAL: 0, MISSING: 0, NA: 0}
    for ax in REGISTRY:
        counts[ax["status"]] += 1

    print()
    print("═" * 72)
    print("  AGI AXES — DATA SOURCE COVERAGE AUDIT")
    print(f"  Total axes: {len(REGISTRY)}  │  "
          f"{_color('HAS_API', HAS_API)}: {counts[HAS_API]}  │  "
          f"{_color('PARTIAL', PARTIAL)}: {counts[PARTIAL]}  │  "
          f"{_color('MISSING', MISSING)}: {counts[MISSING]}  │  "
          f"{_color('N/A', NA)}: {counts[NA]}")
    print("═" * 72)

    for group, axes in groups.items():
        print(f"\n{'─' * 72}")
        print(f"  {group}")
        print(f"{'─' * 72}")

        for ax in axes:
            if missing_only and ax["status"] in (HAS_API, NA):
                continue

            status_tag = f"[{ax['status']:7s}]"
            print(f"\n  {_color(status_tag, ax['status'])}  {ax['name']}")
            print(f"             {ax['label']}")

            if ax["gi_sources"]:
                print(f"             ► Current coverage:")
                for src in ax["gi_sources"]:
                    print(f"               • {src}")

            if ax["status"] in (MISSING, PARTIAL) and ax["suggested_apis"]:
                print(f"             ► Suggested free API(s):")
                for api in ax["suggested_apis"]:
                    key_tag = " [FREE, no key]" if not api["key_required"] else " [free key req.]"
                    print(f"               ✦ {api['label']}{key_tag}")
                    print(f"                 URL: {api['url']}")
                    if api.get("params"):
                        param_str = "&".join(f"{k}={v}" for k, v in api["params"].items())
                        print(f"                 Params: {param_str}")
                    print(f"                 Measures: {api['measures']}")
                    if api.get("note"):
                        print(f"                 Note: {api['note']}")

    print()
    print("═" * 72)
    total_real = counts[HAS_API] + counts[PARTIAL] + counts[MISSING]
    pct_covered = round(100 * counts[HAS_API] / total_real) if total_real else 0
    pct_partial = round(100 * (counts[HAS_API] + counts[PARTIAL]) / total_real) if total_real else 0
    print(f"  SUMMARY: {counts[HAS_API]}/{total_real} axes fully covered ({pct_covered}%),  "
          f"{counts[HAS_API] + counts[PARTIAL]}/{total_real} incl. partial ({pct_partial}%)")
    missing_axes = [ax["name"] for ax in REGISTRY if ax["status"] == MISSING]
    if missing_axes:
        print(f"  MISSING:  {', '.join(missing_axes)}")
    print("═" * 72)
    print()


def as_json() -> str:
    return json.dumps(
        [
            {
                "name":          ax["name"],
                "label":         ax["label"],
                "group":         ax["group"],
                "status":        ax["status"],
                "gi_keys":       ax["gi_keys"],
                "missing_signals": ax["missing_signals"],
                "suggested_apis": ax["suggested_apis"],
            }
            for ax in REGISTRY
        ],
        ensure_ascii=False,
        indent=2,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AGI axes data-source coverage audit")
    parser.add_argument("--missing-only", action="store_true",
                        help="Print only PARTIAL and MISSING axes")
    parser.add_argument("--json", action="store_true",
                        help="Output full registry as JSON")
    args = parser.parse_args()

    if args.json:
        print(as_json())
    else:
        print_coverage_table(missing_only=args.missing_only)
