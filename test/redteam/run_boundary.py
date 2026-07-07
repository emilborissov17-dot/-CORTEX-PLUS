#!/usr/bin/env python3
"""Run _divergence_pilot.py's exact detection logic over the REAL universe
(~175 countries) + 3 synthetic boundary countries injected by build_boundary_inputs.py.
Reads only the fixtures in this directory (vdem_boundary_real.csv,
wellbeing_boundary_real.json). Not part of the production pipeline.
"""
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
VDEM_CSV = HERE / "vdem_boundary_real.csv"
WELLBEING_JSON = HERE / "wellbeing_boundary_real.json"
GROUND_TRUTH = HERE / "boundary_ground_truth.json"

FACADE_THRESHOLD = 0.20
PRACTICE_VARS = ["v2x_freexp_altinf", "v2x_corr", "v2x_rule"]

SYNTH_ISO2 = {"Y1", "Y2", "Y3"}
SYNTH_ISO3 = {"YY1", "YY2", "YY3"}
ISO2_TO_SYNTH_ISO3 = {"Y1": "YY1", "Y2": "YY2", "Y3": "YY3"}


def load_vdem_practice() -> dict:
    """Mirrors _divergence_pilot.load_vdem_practice(), but rows here already are
    one-per-country (real MRV + synthetic), so no reduction logic needed beyond
    the same year>=2018 / complete-3-vars filter for parity with production."""
    best = {}
    with open(VDEM_CSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            iso3 = row.get("country_text_id", "").strip()
            yr_s = row.get("year", "")
            if not iso3 or not yr_s:
                continue
            try:
                yr = int(yr_s)
            except ValueError:
                continue
            if yr < 2018:
                continue
            vals = {}
            ok = True
            for v in PRACTICE_VARS:
                raw = row.get(v, "")
                if not raw:
                    ok = False
                    break
                try:
                    vals[v] = float(raw)
                except ValueError:
                    ok = False
                    break
            if not ok:
                continue
            if iso3 not in best or yr > best[iso3]["_year"]:
                vals["_year"] = yr
                best[iso3] = vals
    return best


def load_wellbeing_quant() -> dict:
    data = json.loads(WELLBEING_JSON.read_text(encoding="utf-8"))
    out = {}
    for c in data["countries"]:
        if c.get("status") != "ok":
            continue
        dep, strain, flo = c.get("deprivation"), c.get("strain"), c.get("flourishing")
        if dep is None or strain is None or flo is None or dep < 0 or strain < 0 or flo < 0:
            continue
        out[c["iso2"]] = {"deprivation": dep, "strain": strain, "flourishing": flo, "name": c.get("name", c["iso2"])}
    return out


def percentile_rank(values: dict) -> dict:
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(ordered)}


def iso2_to_iso3_for_universe(iso2: str, real_map) -> str | None:
    if iso2 in ISO2_TO_SYNTH_ISO3:
        return ISO2_TO_SYNTH_ISO3[iso2]
    return real_map(iso2)


def main():
    import sys
    BASE = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(BASE))
    from wellbeing_country import _iso2_to_iso3

    vdem = load_vdem_practice()
    quant = load_wellbeing_quant()

    universe = [iso2 for iso2 in quant
                if (iso3 := iso2_to_iso3_for_universe(iso2, _iso2_to_iso3)) and iso3 in vdem]
    print(f"[BOUNDARY] full universe (real + synthetic): {len(universe)} countries "
          f"({len(universe) - 3} real + 3 synthetic)\n")

    quant_goodness = {
        iso2: (1 - quant[iso2]["deprivation"] + 1 - quant[iso2]["strain"] + quant[iso2]["flourishing"]) / 3
        for iso2 in universe
    }
    quant_pct = percentile_rank(quant_goodness)

    def iso3_of(iso2):
        return iso2_to_iso3_for_universe(iso2, _iso2_to_iso3)

    freexp_raw = {iso2: vdem[iso3_of(iso2)]["v2x_freexp_altinf"] for iso2 in universe}
    corr_inv_raw = {iso2: 1.0 - vdem[iso3_of(iso2)]["v2x_corr"] for iso2 in universe}
    rule_raw = {iso2: vdem[iso3_of(iso2)]["v2x_rule"] for iso2 in universe}
    freexp_pct = percentile_rank(freexp_raw)
    corr_pct = percentile_rank(corr_inv_raw)
    rule_pct = percentile_rank(rule_raw)

    ground_truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8")) if GROUND_TRUTH.exists() else {}

    print(f"{'ISO':4} {'label':14} {'quant_pct':>10} {'qual_pct':>9} {'divergence':>11} {'FACADE?':>8} {'side of 0.20':>14}")
    print("-" * 80)
    for iso2 in sorted(SYNTH_ISO2):
        if iso2 not in universe:
            print(f"{iso2:4}  MISSING FROM UNIVERSE")
            continue
        qs = quant_pct[iso2]
        ql = (freexp_pct[iso2] + corr_pct[iso2] + rule_pct[iso2]) / 3
        div = qs - ql
        facade = div >= FACADE_THRESHOLD
        side = "ABOVE (facade)" if div > FACADE_THRESHOLD else ("BELOW (not facade)" if div < FACADE_THRESHOLD else "EXACTLY ON")
        label = ground_truth.get(iso2, {}).get("label", "?")
        print(f"{iso2:4} {label:14} {qs:10.3f} {ql:9.3f} {div:11.3f} {str(facade):>8} {side:>14}")

    print("\n[input values used]")
    for iso2 in sorted(SYNTH_ISO2):
        d = quant[iso2]
        v = vdem[iso3_of(iso2)]
        gt = ground_truth.get(iso2, {})
        print(f"  {iso2} ({gt.get('label','?')}): "
              f"dep={d['deprivation']:.4f} strain={d['strain']:.4f} flo={d['flourishing']:.4f}  |  "
              f"freexp={v['v2x_freexp_altinf']:.4f} corr={v['v2x_corr']:.4f} rule={v['v2x_rule']:.4f}  "
              f"(target quant_pct={gt.get('target_p_q')}, target qual_pct={gt.get('target_p_ql')})")

    print("\n[ground truth check]")
    expectations = {"Y1": ("BELOW", lambda d: d < FACADE_THRESHOLD),
                     "Y2": ("EXACT", lambda d: abs(d - FACADE_THRESHOLD) < 0.03),
                     "Y3": ("ABOVE", lambda d: d > FACADE_THRESHOLD)}
    for iso2, (label, check) in expectations.items():
        if iso2 not in universe:
            continue
        qs = quant_pct[iso2]
        ql = (freexp_pct[iso2] + corr_pct[iso2] + rule_pct[iso2]) / 3
        div = qs - ql
        ok = check(div)
        print(f"  {iso2} ({label}): divergence={div:.4f} -> {'MATCHES ground truth' if ok else 'MISMATCH vs ground truth'}")


if __name__ == "__main__":
    main()
