#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/build_taxonomy_key_map.py — writes config/taxonomy_key_map.json (1 Oct 2026).

Every LIVE key the repo measures today, mapped to exactly ONE subcategory of
config/taxonomy.json by the explicit rule table RULES below. No model call, no
fuzzy match, no similarity: a key is mapped only if RULES names it.

THE LIVE KEYS, from six places, each read from disk at run time:
  target_config   primary_metric of every axis in config/target_config.json
  metric_details  keys of metric_details in snapshots/master/goal_score_latest.json
  daily_tier      distinct `indicator` values in memory/daily_tier.jsonl
  composed        series ids in memory/composed_indicators.json (the id of every
                  composed slot and of every live source in every slot). The
                  top-level keys of that file are AXIS names, not measured keys,
                  and are not enumerated.
  openclaw        `key` of every entry in config/data_feeds.json "sources"
  somatic         VECTOR_FIELDS of cockpit/somatic.py, read by AST (the module is
                  not imported: importing it would start nothing, but it would
                  also prove nothing about the literal)

REFUSAL: a source file that is missing or unreadable aborts the run (exit 2) —
a smaller key list is a wrong answer that looks like a right one. A key RULES
does not name goes to UNMAPPED, which is printed and written. When in doubt the
rule table says nothing, and the key is UNMAPPED.

Usage:
  venv\\Scripts\\python.exe tools/build_taxonomy_key_map.py            # write
  venv\\Scripts\\python.exe tools/build_taxonomy_key_map.py --dry      # print only
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from core import taxonomy as tx  # noqa: E402

OUT = REPO / "config" / "taxonomy_key_map.json"
SRC = {
    "target_config": REPO / "config" / "target_config.json",
    "metric_details": REPO / "snapshots" / "master" / "goal_score_latest.json",
    "daily_tier": REPO / "memory" / "daily_tier.jsonl",
    "composed": REPO / "memory" / "composed_indicators.json",
    "openclaw": REPO / "config" / "data_feeds.json",
    "somatic": REPO / "cockpit" / "somatic.py",
}

# Reasons, named once. A rule cites one of these or its own sentence.
LIT = "the subcategory's own wanted_keys names this indicator"
SAME = "same indicator as {}, under another name"
GOV = ("CORTEX composite of WGI RL/CC(/GE) and V-Dem corr/rule (wellbeing_country.py); rule of "
       "law is the one component present in BOTH governance composites and in BOTH sources. "
       "JUDGEMENT CALL, flagged: the composite also carries corruption, and the 'rights' axis "
       "carries no rights indicator at all")

# (key, subcategory, why). A LIST, so a duplicated key is detected rather than
# silently overriding an earlier rule as a dict literal would.
RULES: list = [
    # ── primary metrics / metric_details ─────────────────────────────────────
    ("renewable_energy_pct", "C3.3", LIT),
    ("safe_water_access_pct", "A1.2", LIT),
    ("food_insecurity_pct", "A1.1", "food insecurity prevalence; A1.1 wants severe_food_insecurity_pct"),
    ("adjusted_net_savings_pct", "B3.7", LIT),
    ("co2_ppm_mauna_loa", "C1.1", LIT),
    ("forest_area_pct", "C2.1", LIT),
    ("protected_terrestrial_area_pct", "C2.5", LIT),
    ("gdp_growth_pct", "B3.1", LIT),
    ("extreme_poverty_rate_pct", "A2.3", LIT),
    ("urbanization_pct", "B4.6", LIT),
    ("governance_institutions_score_global", "B2.1", GOV),
    ("child_mortality_per_1000", "A1.5", LIT),
    ("refugee_population", "A2.2", LIT),
    ("governance_rights_score_global", "B2.1", GOV),
    ("primary_completion_rate", "A5.1", LIT),
    ("literacy_rate_youth_pct", "A5.1", LIT),
    ("goal_score", "E3.1", "the system's own composite distance to the goal; E3.1 wants goal_distance"),
    # ── daily_tier (dotted paths into snapshots/master/global_indicators_latest.json) ──
    ("ai_activity.arxiv_ai_papers_total", "B6.2", "count of AI research papers: activity in AI"),
    ("ai_activity.github_ai_repos_total", "B6.2", "count of public AI repositories: activity in AI"),
    ("cities.electricity_access_pct", "A1.4", "electricity access; A1.4 wants electricity_access_pct"),
    ("cities.internet_users_pct", "A5.2", "internet users; A5.2 wants internet_access_pct"),
    ("cities.roads_paved_pct", "B4.1", "paved roads share: transport infrastructure"),
    ("cities.urban_growth_annual_pct", "B7.4", "urban population growth: urbanization of population"),
    ("cities.urban_population_pct", "B7.4", "urban population share; B7.4 wants urban_population_pct"),
    ("co2.co2_annual_increase", "C1.1", "annual increase of atmospheric CO2"),
    ("co2.co2_ppm", "C1.1", "atmospheric CO2 concentration"),
    ("co2.co2_ppm_1yr_ago", "C1.1", "atmospheric CO2 concentration, one year earlier"),
    ("conflicts.active_armed_conflicts", "B1.1", "UCDP count of active armed conflicts"),
    ("displaced.asylum_seekers_millions", "A2.2", "UNHCR displacement stock"),
    ("displaced.idps_millions", "A2.2", "internally displaced; A2.2 wants internally_displaced"),
    ("displaced.refugees_millions", "A2.2", "refugees; A2.2 wants refugee_population"),
    ("displaced.stateless_millions", "A2.2", "stateless; A2.2 wants stateless_population"),
    ("economy.gdp_growth_annual_pct", "B3.1", SAME.format("gdp_growth_pct")),
    ("economy.gdp_per_capita_ppp_usd", "B3.1", "output per person: production"),
    ("economy.industry_value_added_pct_gdp", "B3.1", "industry share of output: production"),
    ("economy.labour_force_participation_pct", "B3.1", "labour force participation: employment"),
    ("economy.unemployment_pct", "A2.3", "unemployment; A2.3 wants unemployment_pct"),
    ("food.food_insecurity_moderate_severe_pct", "A1.1", "food insecurity prevalence"),
    ("food.food_insecurity_severe_pct", "A1.1", "severe food insecurity; A1.1 wants severe_food_insecurity_pct"),
    ("food.undernourishment_pct", "A1.1", "undernourishment; A1.1 wants undernourishment_pct"),
    ("governance.cc_est", "B2.2", "WGI Control of Corruption estimate"),
    ("governance.ge_est", "B2.5", "WGI Government Effectiveness estimate: state capacity and services"),
    ("governance.rl_est", "B2.1", "WGI Rule of Law estimate"),
    ("neo.neo_close_approaches_90d", "D1.5", "near-Earth object close approaches; D1.5 wants near_earth_object_close_approaches"),
    ("neo.neo_within_lunar_dist_90d", "D1.5", "near-Earth objects within lunar distance"),
    ("nuclear.nuclear_warheads_deployed", "D1.1", "deployed warheads; D1.1 wants nuclear_warheads_deployed"),
    ("nuclear.nuclear_warheads_on_alert", "D1.1", "warheads on high alert: nuclear existential risk posture"),
    ("nuclear.nuclear_warheads_total", "B1.4", "total warheads; B1.4 wants nuclear_warheads"),
    ("quakes.quake_m45_count", "C5.1", "M4.5+ earthquakes; C5.1 wants quake_m45_count"),
    ("sea_level.sea_level_rise_mm", "C1.4", "sea level rise; C1.4 wants sea_level_rise_mm"),
    ("tech_infra.broadband_per100", "B4.3", "fixed broadband subscriptions; B4.3 wants broadband_access_pct"),
    ("tech_infra.mobile_subscriptions_per100", "B4.3", "mobile subscriptions; B4.3 wants mobile_coverage_pct"),
    ("tech_infra.secure_internet_servers_per1m", "B4.3", "secure internet servers: digital infrastructure"),
    ("temperature.temp_anomaly_c", "C1.3", "global temperature anomaly; C1.3 wants global_temp_anomaly"),
    ("waste.adjusted_net_savings_pct", "B3.7", SAME.format("adjusted_net_savings_pct")),
    ("waste.fossil_fuel_consumption_pct", "C3.3", "fossil share of energy consumption"),
    ("waste.natural_resources_rents_pct", "B3.7", "natural resource rents: a resource-based indicator"),
    ("waste.resource_depletion_pct_gni", "B3.7", "resource depletion: a resource-based indicator"),
    ("world_bank.forest_area_pct", "C2.1", SAME.format("forest_area_pct")),
    ("world_bank.gini_mean", "A4.5", "Gini; A4.5 wants gini"),
    ("world_bank.infant_mortality_per1k", "A1.5", "infant mortality: staying alive"),
    ("world_bank.life_expectancy", "A1.5", "life expectancy; A1.5 wants life_expectancy"),
    ("world_bank.literacy_rate_adult_pct", "A5.1", "adult literacy: education"),
    ("world_bank.literacy_rate_youth_pct", "A5.1", SAME.format("literacy_rate_youth_pct")),
    ("world_bank.population_billions", "B7.1", "population size; B7.1 wants population"),
    ("world_bank.poverty_190_pct", "A2.3", "extreme poverty headcount"),
    ("world_bank.poverty_intl_line_pct", "A2.3", "extreme poverty headcount at the international line"),
    ("world_bank.primary_completion_rate", "A5.1", SAME.format("primary_completion_rate")),
    ("world_bank.protected_terrestrial_area_pct", "C2.5", SAME.format("protected_terrestrial_area_pct")),
    ("world_bank.renewable_elec_pct", "C3.3", "renewable share of electricity"),
    ("world_bank.renewable_energy_pct", "C3.3", SAME.format("renewable_energy_pct")),
    ("world_bank.safe_water_access_pct", "A1.2", SAME.format("safe_water_access_pct")),
    ("world_bank.threatened_mammals_no", "C2.2", "threatened species count; C2.2 wants threatened_species"),
    ("world_bank.under5_mortality_per1k", "A1.5", "under-5 mortality; A1.5 wants child_mortality_per_1000"),
    # ── composed series ids (config/composer_specs.json says what each one reads) ──
    ("celestrak_geostationary", "D2.2", "objects in geostationary orbit: orbital infrastructure"),
    ("celestrak_launched_last_30d", "D2.1", "objects launched in the last 30 days: access to space"),
    ("gdacs_orange_red_current", "A2.5", "GDACS orange/red disaster alerts: disasters affecting people"),
    ("gi_adjusted_net_savings", "B3.7", SAME.format("waste.adjusted_net_savings_pct")),
    ("gi_arxiv_ai_papers", "B6.2", SAME.format("ai_activity.arxiv_ai_papers_total")),
    ("gi_asylum_millions", "A2.2", SAME.format("displaced.asylum_seekers_millions")),
    ("gi_broadband", "B4.3", SAME.format("tech_infra.broadband_per100")),
    ("gi_control_corruption", "B2.2", SAME.format("governance.cc_est")),
    ("gi_electricity_access", "A1.4", SAME.format("cities.electricity_access_pct")),
    ("gi_food_insecurity_severe_pct", "A1.1", SAME.format("food.food_insecurity_severe_pct")),
    ("gi_forest_area", "C2.1", SAME.format("world_bank.forest_area_pct")),
    ("gi_forest_area_potential", "C2.1", SAME.format("world_bank.forest_area_pct")),
    ("gi_fossil_fuel_consumption_pct", "C3.3", SAME.format("waste.fossil_fuel_consumption_pct")),
    ("gi_gdp_growth", "B3.1", SAME.format("economy.gdp_growth_annual_pct")),
    ("gi_gdp_per_capita", "B3.1", SAME.format("economy.gdp_per_capita_ppp_usd")),
    ("gi_gini", "A4.5", SAME.format("world_bank.gini_mean")),
    ("gi_github_ai_repos", "B6.2", SAME.format("ai_activity.github_ai_repos_total")),
    ("gi_gov_effectiveness", "B2.5", SAME.format("governance.ge_est")),
    ("gi_idps_millions", "A2.2", SAME.format("displaced.idps_millions")),
    ("gi_internet_users", "A5.2", SAME.format("cities.internet_users_pct")),
    ("gi_life_expectancy", "A1.5", SAME.format("world_bank.life_expectancy")),
    ("gi_literacy_adult_edu", "A5.1", SAME.format("world_bank.literacy_rate_adult_pct")),
    ("gi_literacy_youth", "A5.1", SAME.format("world_bank.literacy_rate_youth_pct")),
    ("gi_mobile_subs", "B4.3", SAME.format("tech_infra.mobile_subscriptions_per100")),
    ("gi_neo_close_approaches", "D1.5", SAME.format("neo.neo_close_approaches_90d")),
    ("gi_neo_lunar_dist", "D1.5", SAME.format("neo.neo_within_lunar_dist_90d")),
    ("gi_noaa_co2", "C1.1", SAME.format("co2.co2_ppm")),
    ("gi_nuclear_deployed", "D1.1", SAME.format("nuclear.nuclear_warheads_deployed")),
    ("gi_nuclear_on_alert", "D1.1", SAME.format("nuclear.nuclear_warheads_on_alert")),
    ("gi_nuclear_total", "B1.4", SAME.format("nuclear.nuclear_warheads_total")),
    ("gi_poverty_intl_line", "A2.3", SAME.format("world_bank.poverty_intl_line_pct")),
    ("gi_refugees_millions", "A2.2", SAME.format("displaced.refugees_millions")),
    ("gi_renewable_energy_pct", "C3.3", SAME.format("world_bank.renewable_energy_pct")),
    ("gi_resource_depletion", "B3.7", SAME.format("waste.resource_depletion_pct_gni")),
    ("gi_rule_of_law", "B2.1", SAME.format("governance.rl_est")),
    ("gi_safe_water_access_pct", "A1.2", SAME.format("world_bank.safe_water_access_pct")),
    ("gi_sea_level", "C1.4", SAME.format("sea_level.sea_level_rise_mm")),
    ("gi_secure_servers", "B4.3", SAME.format("tech_infra.secure_internet_servers_per1m")),
    ("gi_temp_anomaly", "C1.3", SAME.format("temperature.temp_anomaly_c")),
    ("gi_threatened_mammals", "C2.2", SAME.format("world_bank.threatened_mammals_no")),
    ("gi_under5_mortality", "A1.5", SAME.format("world_bank.under5_mortality_per1k")),
    ("gi_undernourishment_pct", "A1.1", SAME.format("food.undernourishment_pct")),
    ("gi_unemployment", "A2.3", SAME.format("economy.unemployment_pct")),
    ("gi_urban_pct", "B7.4", SAME.format("cities.urban_population_pct")),
    ("noaa_gml_daily", "C1.1", "NOAA GML global daily CO2 trend"),
    ("promoted_27965", "C3.1", "World Bank ER.H2O.INTR.PC; C3.1 wants freshwater_per_capita"),
    ("promoted_39428", "C5.1", "USGS M4.5+ earthquakes, past day"),
    ("promoted_40653", "C5.2", "NASA EONET severeStorms events; C5.2 wants severe_storm_events"),
    ("promoted_54947", "C5.3", "NASA EONET wildfires events; C5.3 wants wildfire_events"),
    ("promoted_60365", "C5.2", "NASA EONET floods events; C5.2 wants flood_events"),
    ("promoted_69607", "C5.2", "NASA EONET severeStorms events (same URL as promoted_40653)"),
    ("promoted_96302", "B1.1", SAME.format("conflicts.active_armed_conflicts")),
    ("swpc_kp_daily_max", "D1.5", "NOAA SWPC planetary Kp: geomagnetic storms; D1.5 wants solar_storm_events"),
    ("usgs_quakes_daily", "C5.1", "USGS all earthquakes, past day"),
    ("wbg_institutions_score", "B2.1", SAME.format("governance_institutions_score_global") + "; " + GOV),
    ("wbg_rights_score", "B2.1", SAME.format("governance_rights_score_global") + "; " + GOV),
    # ── openclaw seed sources ────────────────────────────────────────────────
    ("quakes_m45_last_24h", "C5.1", "USGS M4.5+ count, last 24 h"),
    ("objects_launched_last_30d", "D2.1", SAME.format("celestrak_launched_last_30d")),
    # ── cockpit/somatic.py VECTOR_FIELDS (domain E: the machine itself) ───────
    ("battery_percent", "E1.1", "battery charge"),
    ("power_plugged", "E1.1", "on mains power or not"),
    ("gpu_power_w", "E1.1", "GPU power draw"),
    ("gpu_temp_c", "E1.2", "GPU temperature"),
    ("gpu_util_pct", "E1.3", "GPU utilisation"),
    ("cpu_percent", "E1.3", "CPU utilisation"),
    ("cpu_freq_mhz", "E1.3", "CPU clock"),
    ("load_1", "E1.3", "1-minute load"),
    ("gpu_mem_used_mb", "E1.4", "GPU memory used"),
    ("ram_percent", "E1.4", "RAM used share"),
    ("ram_used_gb", "E1.4", "RAM used"),
    ("swap_percent", "E1.4", "swap used share"),
    ("page_faults", "E1.4", "page faults"),
    ("disk_read_mb", "E1.5", "disk read volume"),
    ("disk_write_mb", "E1.5", "disk write volume"),
    ("net_sent_mb", "E1.6", "network bytes sent"),
    ("net_recv_mb", "E1.6", "network bytes received"),
    ("wifi_signal_pct", "E1.6", "Wi-Fi signal"),
    ("gateway_ping_ms", "E1.6", "gateway round trip"),
    ("connections", "E1.6", "open network connections"),
    ("event_log_errors_24h", "E1.10", "Windows event-log errors, 24 h"),
]

# Keys deliberately NOT mapped, each with the doubt that keeps it out. These are
# not rules; they only make the UNMAPPED list explain itself.
DOUBT = {
    "biodiversity.species_observations_30d": "GBIF observation count measures observer effort, not species state",
    "gi_species_observations": "GBIF observation count measures observer effort, not species state",
    "exoplanets.confirmed_exoplanets": "no subcategory measures astronomy discovery",
    "gi_confirmed_exoplanets": "no subcategory measures astronomy discovery",
    "food.agriculture_pct_gdp": "economic structure; no subcategory wants it",
    "food.cereal_yield_kg_per_ha": "productivity, not food security, land or prices",
    "gi_cereal_yield_kg_per_ha": "productivity, not food security, land or prices",
    "food.food_production_index": "an index of output; A1.1 wants a price index, not production",
    "gi_food_production_index": "an index of output; A1.1 wants a price index, not production",
    "markets.spy_adjclose": "an equity fund price; no subcategory measures equity markets",
    "markets.gld_adjclose": "a gold fund price; no subcategory wants it",
    "markets.uup_adjclose": "a dollar-index fund price; no subcategory wants it",
    "ecb_eurusd": "an exchange rate; no subcategory wants it",
    "fred_dgs10": "a sovereign bond yield; B3.3 wants public debt and debt distress, not yields",
    "media.news_tone_avg_1month": "GDELT tone of coverage is not press freedom, ownership, censorship or disinformation",
    "media.news_tone_latest": "GDELT tone of coverage is not press freedom, ownership, censorship or disinformation",
    "media.news_tone_min": "GDELT tone of coverage is not press freedom, ownership, censorship or disinformation",
    "media.news_tone_max": "GDELT tone of coverage is not press freedom, ownership, censorship or disinformation",
    "tech_infra.high_tech_exports_pct_manuf": "trade composition; B3.4 wants balance and dependency",
    "eonet_sealakeice": "a count of sea/lake ice EVENTS is not sea-ice extent",
    "promoted_11883": "discharge of one US river gauge measures no global subcategory",
    "promoted_34826": "solar radiation over one point in Germany measures no subcategory",
    "promoted_35258": "evapotranspiration over one point in the US corn belt measures no subcategory",
    "promoted_40232": "a COUNT of WHO GHE indicator codes in a catalogue, not a health measurement",
    "promoted_61568": "a COUNT of WHO HIV indicator codes in a catalogue, not a health measurement",
    "promoted_78396": "a metadata count from the Nobel API, not a measurement of rights",
    "promoted_84957": "a row count of an OWID vaccination file, not a vaccination rate",
    "gi_self_carried_metrics": "the system's own carry count; E2.1 wants subcategories_seen, not this",
    "gi_self_fresh_metrics": "the system's own refresh count; E2.1 wants subcategories_seen, not this",
    "surface_temp_c_sofia": "weather at one city measures no global subcategory",
    "this_path_does_not_exist": "a deliberately broken seed source",
    "uptime_hours": "machine uptime fits no E1 subcategory by name",
    "open_handles": "OS handle count fits no E1 subcategory by name",
    "idle_seconds": "user idle time: Periphery is not defined precisely enough to claim it",
    "brightness_pct": "screen brightness: 'Optic' is not defined precisely enough to claim it",
}


class Refused(SystemExit):
    def __init__(self, why: str):
        super().__init__(2)
        self.why = why

    def __str__(self) -> str:
        return f"REFUSED: {self.why}"


def _need(p: Path) -> Path:
    if not p.is_file():
        raise Refused(f"missing source {p.relative_to(REPO).as_posix()}")
    return p


def _json(p: Path):
    try:
        return json.loads(_need(p).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise Refused(f"unreadable source {p.relative_to(REPO).as_posix()}: {type(e).__name__}")


def rule_table(rules: list | None = None) -> dict:
    """{key: (subcategory, why)}. Raises on a key ruled twice."""
    out = {}
    for key, sub, why in (rules if rules is not None else RULES):
        if key in out:
            raise Refused(f"rule table names {key!r} twice")
        out[key] = (sub, why)
    return out


def declared_rules(sources: list, rules: dict) -> dict:
    """{key: (subcategory, why)} from openclaw seed entries that DECLARE a
    subcategory (C-OC-1 Part 3). A declaration is an explicit rule written by a
    human into config/data_feeds.json, not a guess. Refused when it
    contradicts RULES for the same key, or when two seeds declare one key
    differently."""
    out: dict = {}
    for src in sources:
        key, sub = src.get("key"), src.get("subcategory")
        if not key or not sub:
            continue
        if key in rules and rules[key][0] != sub:
            raise Refused(f"seed {src.get('id')!r} declares {key!r} -> {sub}, which contradicts "
                          f"RULES ({rules[key][0]})")
        if key in out and out[key][0] != sub:
            raise Refused(f"key {key!r} is declared into two subcategories ({out[key][0]}, {sub})")
        out[key] = (sub, f"declared by seed {src.get('id')} in config/data_feeds.json")
    return out


# ── the six enumerations ─────────────────────────────────────────────────────
def keys_target_config(p: Path = SRC["target_config"]) -> list:
    doc = _json(p)
    out = []
    for sg, axes in doc.items():
        if sg.startswith("_") or not isinstance(axes, dict):
            continue
        for _ax, spec in axes.items():
            if isinstance(spec, dict) and spec.get("primary_metric"):
                out.append(spec["primary_metric"])
    return out


def keys_metric_details(p: Path = SRC["metric_details"]) -> list:
    md = _json(p).get("metric_details")
    if not isinstance(md, dict):
        raise Refused(f"{p.name} has no metric_details object")
    return list(md.keys())


def keys_daily_tier(p: Path = SRC["daily_tier"]) -> list:
    seen = []
    for line in _need(p).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ind = json.loads(line).get("indicator")
        except json.JSONDecodeError:
            continue
        if ind and ind not in seen:
            seen.append(ind)
    if not seen:
        raise Refused(f"{p.name} has no readable indicator")
    return seen


def keys_composed(p: Path = SRC["composed"]) -> list:
    out = []
    for _ax, v in _json(p).items():
        if not isinstance(v, dict):
            continue
        for _slot, s in (v.get("composed") or {}).items():
            if isinstance(s, dict) and s.get("id") and s["id"] not in out:
                out.append(s["id"])
        for _slot, s in (v.get("slots") or {}).items():
            for e in (s.get("live") or []) if isinstance(s, dict) else []:
                if e.get("id") and e["id"] not in out:
                    out.append(e["id"])
    return out


def keys_openclaw(p: Path = SRC["openclaw"]) -> list:
    return [s["key"] for s in (_json(p).get("sources") or []) if s.get("key")]


def keys_somatic(p: Path = SRC["somatic"]) -> list:
    tree = ast.parse(_need(p).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "VECTOR_FIELDS" for t in n.targets):
            return list(ast.literal_eval(n.value))
    raise Refused("cockpit/somatic.py defines no literal VECTOR_FIELDS")


ENUMERATORS = [("target_config", keys_target_config), ("metric_details", keys_metric_details),
               ("daily_tier", keys_daily_tier), ("composed", keys_composed),
               ("openclaw", keys_openclaw), ("somatic", keys_somatic)]


def live_keys() -> dict:
    """{key: [source names]} in first-seen order."""
    out: dict = {}
    for name, fn in ENUMERATORS:
        for k in fn():
            out.setdefault(k, [])
            if name not in out[k]:
                out[k].append(name)
    return out


def build(dry: bool = False) -> dict:
    tree = tx.load()
    rules = rule_table()
    seeds = _json(SRC["openclaw"]).get("sources") or []
    for key, rule in declared_rules(seeds, rules).items():
        rules.setdefault(key, rule)
    for key, (sub, _why) in rules.items():
        tx.subcategory(sub, tree)            # an unknown target id is a refusal, not a skip
    live = live_keys()
    mapped, unmapped = {}, []
    for key, sources in live.items():
        if key in rules:
            sub, why = rules[key]
            mapped[key] = {"subcategory": sub, "rule": why, "sources": sources}
        else:
            unmapped.append({"key": key, "sources": sources,
                             "why": DOUBT.get(key, "no rule names this key")})
    dead_rules = sorted(k for k in rules if k not in live)
    doc = {
        "_meta": {
            "what": "Every live key the repo measures, mapped to ONE subcategory of config/taxonomy.json.",
            "generated_by": "tools/build_taxonomy_key_map.py (explicit rule table RULES; no model call)",
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "taxonomy_counts": tree["counts"],
            "sources": {n: {"path": SRC[n].relative_to(REPO).as_posix(),
                            "keys": sum(1 for s in live.values() if n in s)} for n, _ in ENUMERATORS},
            "live_keys": len(live), "mapped": len(mapped), "unmapped": len(unmapped),
            "rules_for_keys_not_live_today": dead_rules,
        },
        "keys": mapped,
        "unmapped": unmapped,
    }
    if not dry:
        OUT.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return doc


if __name__ == "__main__":
    try:
        d = build(dry="--dry" in sys.argv)
    except Refused as e:
        print(str(e))
        sys.exit(2)
    m = d["_meta"]
    print(f"live keys {m['live_keys']} · mapped {m['mapped']} · UNMAPPED {m['unmapped']}")
    for n, s in m["sources"].items():
        print(f"  {n:<15} {s['keys']:>4} key(s)  {s['path']}")
    print("UNMAPPED:")
    for u in d["unmapped"]:
        print(f"  {u['key']:<45} [{','.join(u['sources'])}]  {u['why']}")
    if m["rules_for_keys_not_live_today"]:
        print("rules for keys not live today:", ", ".join(m["rules_for_keys_not_live_today"]))
