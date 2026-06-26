#!/usr/bin/env python3
"""
data_providers/civilization/governance_institutions_provider.py
WGI — претеглено по население, от гледна точка на най-уязвимите.
Индикаторни кодове: GOV_WGI_*.EST (World Bank source 3, v2 API).
"""
import json, urllib.request, pathlib
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]

WGI_INDICATORS = {
    "rule_of_law":              "GOV_WGI_RL.EST",
    "control_of_corruption":    "GOV_WGI_CC.EST",
    "government_effectiveness": "GOV_WGI_GE.EST",
    "voice_accountability":     "GOV_WGI_VA.EST",
    "political_stability":      "GOV_WGI_PV.EST",
    "regulatory_quality":       "GOV_WGI_RQ.EST",
}

def fetch_indicator_weighted(indicator_code: str) -> dict:
    """Вземи индикатор за всички държави + население, изчисли претеглено."""
    url = (
        f"https://api.worldbank.org/v2/country/all/indicator/{indicator_code}"
        f"?format=json&mrv=1&per_page=300"
    )
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read())

    scores = {}
    year = None
    for d in (data[1] or []):
        iso3 = d.get("countryiso3code")
        if d.get("value") is not None and iso3:
            scores[iso3] = float(d["value"])
            if not year:
                year = d.get("date")

    pop_url = (
        "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL"
        "?format=json&mrv=1&per_page=300"
    )
    with urllib.request.urlopen(pop_url, timeout=20) as r:
        pop_data = json.loads(r.read())

    population = {}
    for d in (pop_data[1] or []):
        iso3 = d.get("countryiso3code")
        if d.get("value") and iso3:
            population[iso3] = float(d["value"])

    total_pop = 0
    weighted_sum = 0
    values_weighted = []
    pop_below_minus05 = 0
    pop_above_05 = 0

    for country, score in scores.items():
        pop = population.get(country, 0)
        if pop > 0:
            weighted_sum += score * pop
            total_pop += pop
            values_weighted.append((score, pop))
            if score < -0.5:
                pop_below_minus05 += pop
            if score > 0.5:
                pop_above_05 += pop

    if not total_pop:
        return {}

    weighted_mean = weighted_sum / total_pop

    values_weighted.sort(key=lambda x: x[0])
    cumulative = 0
    median = values_weighted[0][0]
    for score, pop in values_weighted:
        cumulative += pop
        if cumulative >= total_pop / 2:
            median = score
            break

    return {
        "weighted_mean":                round(weighted_mean, 3),
        "weighted_median":              round(median, 3),
        "pct_population_below_minus05": round(100 * pop_below_minus05 / total_pop, 1),
        "pct_population_above_05":      round(100 * pop_above_05 / total_pop, 1),
        "countries_covered":            len(scores),
        "year":                         year,
    }


def fetch() -> dict:
    """Връща претеглени метрики — използва се от civilization_snapshots_agent_qwen."""
    metrics = {}
    for name, code in WGI_INDICATORS.items():
        try:
            result = fetch_indicator_weighted(code)
            if result:
                metrics[f"{name}_weighted_mean"]             = result["weighted_mean"]
                metrics[f"{name}_weighted_median"]           = result["weighted_median"]
                metrics[f"{name}_pct_pop_below_minus05"]     = result["pct_population_below_minus05"]
        except Exception:
            pass
    return metrics


def normalize(metrics: dict) -> dict:
    return metrics


class GovernanceInstitutionsProvider:
    def fetch(self) -> dict:
        return fetch()
    def normalize(self, metrics: dict) -> dict:
        return metrics


def run():
    """Standalone: fetch + save to canonical snapshot path."""
    print("[GOVERNANCE] Зареждам WGI данни претеглени по население...")
    metrics = {}
    for name, code in WGI_INDICATORS.items():
        try:
            result = fetch_indicator_weighted(code)
            if result:
                metrics[f"{name}_weighted_mean"]             = result["weighted_mean"]
                metrics[f"{name}_weighted_median"]           = result["weighted_median"]
                metrics[f"{name}_pct_pop_below_minus05"]     = result["pct_population_below_minus05"]
                print(f"  {name}: mean={result['weighted_mean']}  median={result['weighted_median']}")
        except Exception as e:
            print(f"  {name}: ГРЕШКА — {e}")

    out = {
        "axis":             "GOVERNANCE_INSTITUTIONS_REVIEW",
        "source_type":      "WORLD_BANK_WGI",
        "metrics":          metrics,
        "raw":              metrics,
        "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    out_path = (
        BASE_DIR / "snapshots" / "civilization"
        / "governance_institutions" / "governance_institutions_snapshot_latest.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[GOVERNANCE] Записан -> {out_path}")
    return metrics


if __name__ == "__main__":
    run()
