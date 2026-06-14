#!/usr/bin/env python3
"""
data_providers/civilization/governance_provider.py
WGI — претеглено по население, от гледна точка на най-уязвимите
"""
import json, urllib.request, pathlib
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parents[3]

WGI_INDICATORS = {
    "rule_of_law":              "RL.EST",
    "control_of_corruption":    "CC.EST",
    "government_effectiveness": "GE.EST",
    "voice_accountability":     "VA.EST",
    "political_stability":      "PV.EST",
    "regulatory_quality":       "RQ.EST",
}

def fetch_indicator_weighted(indicator_code: str) -> dict:
    """Вземи индикатор за всички държави + население, изчисли претеглено."""
    # 1. Вземи WGI стойности
    url = f"https://api.worldbank.org/v2/country/all/indicator/{indicator_code}?format=json&mrv=1&per_page=300"
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read())
    
    scores = {}  # country_code -> score
    year = None
    for d in (data[1] or []):
        if d.get("value") is not None and d.get("countryiso3code"):
            scores[d["countryiso3code"]] = float(d["value"])
            if not year:
                year = d.get("date")

    # 2. Вземи население за същите държави
    pop_url = "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&mrv=1&per_page=300"
    with urllib.request.urlopen(pop_url, timeout=20) as r:
        pop_data = json.loads(r.read())
    
    population = {}
    for d in (pop_data[1] or []):
        if d.get("value") and d.get("countryiso3code"):
            population[d["countryiso3code"]] = float(d["value"])

    # 3. Претеглено по население
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

    # Медиана претеглена
    values_weighted.sort(key=lambda x: x[0])
    cumulative = 0
    median = values_weighted[0][0]
    for score, pop in values_weighted:
        cumulative += pop
        if cumulative >= total_pop / 2:
            median = score
            break

    return {
        "weighted_mean":           round(weighted_mean, 3),
        "weighted_median":         round(median, 3),
        "pct_population_below_minus05": round(100 * pop_below_minus05 / total_pop, 1),
        "pct_population_above_05":      round(100 * pop_above_05 / total_pop, 1),
        "countries_covered":       len(scores),
        "year":                    year,
    }

def run():
    print("[GOVERNANCE] Зареждам WGI данни претеглени по население...")
    metrics = {}
    for name, code in WGI_INDICATORS.items():
        try:
            result = fetch_indicator_weighted(code)
            if result:
                metrics[f"{name}_weighted_mean"]    = result["weighted_mean"]
                metrics[f"{name}_weighted_median"]  = result["weighted_median"]
                metrics[f"{name}_pct_pop_below_minus05"] = result["pct_population_below_minus05"]
                print(f"  {name}:")
                print(f"    preteglen mean:   {result['weighted_mean']}")
                print(f"    preteglen median: {result['weighted_median']}")
                print(f"    % население под -0.5: {result['pct_population_below_minus05']}%")
                print(f"    % население над +0.5: {result['pct_population_above_05']}%")
        except Exception as e:
            print(f"  {name}: ГРЕШКА — {e}")

    out = {
        "axis": "GOVERNANCE_INSTITUTIONS_REVIEW",
        "metrics": metrics,
        "data_quality": "REAL_POPULATION_WEIGHTED",
        "source_type": "WORLD_BANK_WGI",
        "methodology": "population_weighted_mean_and_median",
        "fetched_date": datetime.now(timezone.utc).isoformat()[:10],
    }
    out_path = BASE_DIR / "snapshots" / "civilization" / "governance_institutions_review_snapshot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[GOVERNANCE] Записан → {out_path.name}")
    return metrics

if __name__ == "__main__":
    run()
