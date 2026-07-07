#!/usr/bin/env python3
"""Run the _divergence_pilot.py detection logic in isolation, over the 4 synthetic
red-team countries only (test universe = {Z1,Z2,Z3,Z4}, not mixed with real data).

Math copied verbatim from _divergence_pilot.py (percentile_rank, quant_goodness,
divergence = quant_pct - qual_pct, FACADE_THRESHOLD=0.20). Reads only the fixtures
built by build_inputs.py in this same directory. Not part of the production pipeline.
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VDEM_CSV = HERE / "vdem_redteam.csv"
WELLBEING_JSON = HERE / "wellbeing_all_countries_redteam.json"

FACADE_THRESHOLD = 0.20
PRACTICE_VARS = ["v2x_freexp_altinf", "v2x_corr", "v2x_rule"]

ISO2_TO_ISO3 = {"Z1": "ZZ1", "Z2": "ZZ2", "Z3": "ZZ3", "Z4": "ZZ4"}
GROUND_TRUTH = {"Z1": "FACADE", "Z2": "REVERSE (not facade)",
                "Z3": "CONTROL-GOOD (not facade)", "Z4": "CONTROL-BAD (not facade)"}
EXPECTED_FACADE = {"Z1"}  # only Z1 should trip facade=True


def load_vdem_practice() -> dict:
    best = {}
    with open(VDEM_CSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iso3 = row.get("country_text_id", "").strip()
            if iso3 not in ISO2_TO_ISO3.values():
                continue
            vals = {v: float(row[v]) for v in PRACTICE_VARS}
            best[iso3] = vals
    return best


def load_wellbeing_quant() -> dict:
    data = json.loads(WELLBEING_JSON.read_text(encoding="utf-8"))
    out = {}
    for c in data["countries"]:
        if c["iso2"] not in ISO2_TO_ISO3:
            continue
        out[c["iso2"]] = {"deprivation": c["deprivation"], "strain": c["strain"],
                           "flourishing": c["flourishing"], "name": c["name"]}
    return out


def percentile_rank(values: dict) -> dict:
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(ordered)}


def main():
    vdem = load_vdem_practice()
    quant = load_wellbeing_quant()
    universe = [iso2 for iso2 in quant if ISO2_TO_ISO3[iso2] in vdem]

    print(f"[REDTEAM] test universe: {universe} (n={len(universe)})\n")

    quant_goodness = {
        iso2: (1 - quant[iso2]["deprivation"] + 1 - quant[iso2]["strain"] + quant[iso2]["flourishing"]) / 3
        for iso2 in universe
    }
    quant_pct = percentile_rank(quant_goodness)

    freexp_raw = {iso2: vdem[ISO2_TO_ISO3[iso2]]["v2x_freexp_altinf"] for iso2 in universe}
    corr_inv_raw = {iso2: 1.0 - vdem[ISO2_TO_ISO3[iso2]]["v2x_corr"] for iso2 in universe}
    rule_raw = {iso2: vdem[ISO2_TO_ISO3[iso2]]["v2x_rule"] for iso2 in universe}
    freexp_pct = percentile_rank(freexp_raw)
    corr_pct = percentile_rank(corr_inv_raw)
    rule_pct = percentile_rank(rule_raw)

    print(f"{'ISO':4} {'ground_truth':28} {'quant_pct':>10} {'qual_pct':>9} {'divergence':>11} {'FACADE?':>8} {'match':>6}")
    print("-" * 85)
    mismatches = []
    for iso2 in universe:
        qs = quant_pct[iso2]
        ql = (freexp_pct[iso2] + corr_pct[iso2] + rule_pct[iso2]) / 3
        div = qs - ql
        facade = div >= FACADE_THRESHOLD
        expected_facade = iso2 in EXPECTED_FACADE
        match = "OK" if facade == expected_facade else "MISMATCH"
        if match == "MISMATCH":
            mismatches.append((iso2, GROUND_TRUTH[iso2], expected_facade, facade))
        print(f"{iso2:4} {GROUND_TRUTH[iso2]:28} {qs:10.3f} {ql:9.3f} {div:11.3f} {str(facade):>8} {match:>6}")

    print("\n[input values]")
    for iso2 in universe:
        d = quant[iso2]
        v = vdem[ISO2_TO_ISO3[iso2]]
        print(f"  {iso2} ({GROUND_TRUTH[iso2]}): "
              f"dep={d['deprivation']:.2f} strain={d['strain']:.2f} flo={d['flourishing']:.2f}  |  "
              f"freexp={v['v2x_freexp_altinf']:.2f} corr={v['v2x_corr']:.2f} rule={v['v2x_rule']:.2f}")

    print("\n[RESULT]")
    if mismatches:
        print(f"  {len(mismatches)} MISMATCH(ES) — detector disagrees with known ground truth:")
        for iso2, truth, exp, got in mismatches:
            print(f"    {iso2} ({truth}): expected facade={exp}, detector returned facade={got}")
    else:
        print("  No mismatches — detector output matches known ground truth for all 4 synthetic countries.")


if __name__ == "__main__":
    main()
