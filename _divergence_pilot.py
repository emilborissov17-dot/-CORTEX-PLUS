#!/usr/bin/env python3
"""
_divergence_pilot.py — scratch: Variant B — the project's actual thesis.
Quantitative access/infrastructure picture (WB wellbeing profile) vs
qualitative political-practice picture (V-Dem freexp/corruption/rule-of-law).

Lessons from prior attempts (kept for honesty, not deleted from history):
  - WGI-vs-V-Dem: WGI already "sees" overt autocracy (RU) -> too much overlap
    with the practice side to isolate a facade signal for RU specifically.
  - V-Dem norm-vs-practice (v2clacfree/v2mecenefm vs v2x_*): direction was not
    predictable -- those two vars are not a clean de-jure/de-facto split,
    V-Dem codes most variables from observed behavior either way.

Variant B directly matches the project's north star (WELLBEING_PROFILE_DESIGN.md
Critical Limitation section): does a country LOOK good on quantitative
access/infrastructure metrics while FUNCTIONING poorly on political practice?

  quantitative_score = mean(1-deprivation, 1-strain, flourishing) from
                        output/wellbeing_all_countries.json (WB-sourced wellbeing profile)
  qualitative_score  = mean of percentile(v2x_freexp_altinf), percentile(1-v2x_corr),
                        percentile(v2x_rule) -- V-Dem observed political practice

Known dilution (flagged, not hidden): CULTURE_MEDIA_REVIEW inside the quantitative
profile already includes v2x_freexp_altinf (V-Dem Phase A). That's 1 of ~16 axes
inside 1 of 3 dimensions (flourishing) -- small overlap, not the dominant same-construct
circularity that broke the WGI attempt, but real and worth watching in the results.

Both sides percentile-ranked across the intersection universe (WB wellbeing data ∩
V-Dem coverage), not just the 4 pilot countries.

Pre-registered test: BG/HU/RU facade (look good quantitatively, weak qualitatively),
DE not facade (good on both).

Not part of the production pipeline. Does not touch wellbeing_country.py.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
from wellbeing_country import _iso2_to_iso3  # noqa: E402

VDEM_CSV = BASE / "data" / "V-Dem-CY-Core-v16.csv"
WELLBEING_ALL = BASE / "output" / "wellbeing_all_countries.json"

PILOT_COUNTRIES = ["BG", "HU", "RU", "DE"]
FACADE_THRESHOLD = 0.20   # [CAL] provisional, same as prior attempts for continuity

PRACTICE_VARS = ["v2x_freexp_altinf", "v2x_corr", "v2x_rule"]  # v2x_corr inverted below


def load_vdem_practice() -> dict[str, dict]:
    """iso3 -> {var: value}, most-recent-year >= 2018, only rows with all 3 vars."""
    best: dict[str, dict] = {}
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


def load_wellbeing_quant() -> dict[str, dict]:
    """iso2 -> {deprivation, strain, flourishing, name} from the production batch output."""
    data = json.loads(WELLBEING_ALL.read_text(encoding="utf-8"))
    out = {}
    for c in data["countries"]:
        if c.get("status") != "ok":
            continue
        dep, strain, flo = c.get("deprivation"), c.get("strain"), c.get("flourishing")
        if dep is None or strain is None or flo is None or dep < 0 or strain < 0 or flo < 0:
            continue
        out[c["iso2"]] = {"deprivation": dep, "strain": strain, "flourishing": flo, "name": c.get("name", c["iso2"])}
    return out


def percentile_rank(values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    n = len(ordered)
    return {k: (i / (n - 1) if n > 1 else 0.5) for i, (k, _) in enumerate(ordered)}


def main() -> None:
    vdem = load_vdem_practice()
    quant = load_wellbeing_quant()

    print("=" * 76)
    print("DIRECTION CHECK — quantitative composite: higher = looks better")
    print("=" * 76)
    for iso2, label in [("DE", "Germany, expect HIGH"), ("SO", "Somalia, expect LOW"),
                         ("YE", "Yemen, expect LOW")]:
        d = quant.get(iso2)
        if d:
            goodness = (1 - d["deprivation"] + 1 - d["strain"] + d["flourishing"]) / 3
            print(f"  {iso2:4} ({label}): dep={d['deprivation']:.3f} strain={d['strain']:.3f} "
                  f"flo={d['flourishing']:.3f}  -> goodness={goodness:.3f}")
        else:
            print(f"  {iso2}: no data")
    print()

    # ── Universe: WB wellbeing data ∩ V-Dem coverage ──
    universe = [iso2 for iso2 in quant if (iso3 := _iso2_to_iso3(iso2)) and iso3 in vdem]
    print(f"[PILOT] universe size (WB wellbeing ∩ V-Dem coverage): {len(universe)}\n")

    quant_goodness = {
        iso2: (1 - quant[iso2]["deprivation"] + 1 - quant[iso2]["strain"] + quant[iso2]["flourishing"]) / 3
        for iso2 in universe
    }
    quant_pct = percentile_rank(quant_goodness)

    freexp_raw = {iso2: vdem[_iso2_to_iso3(iso2)]["v2x_freexp_altinf"] for iso2 in universe}
    corr_inv_raw = {iso2: 1.0 - vdem[_iso2_to_iso3(iso2)]["v2x_corr"] for iso2 in universe}
    rule_raw = {iso2: vdem[_iso2_to_iso3(iso2)]["v2x_rule"] for iso2 in universe}
    freexp_pct, corr_pct, rule_pct = (percentile_rank(freexp_raw), percentile_rank(corr_inv_raw),
                                       percentile_rank(rule_raw))

    print(f"{'ISO':4} {'quant_pct':>10} {'qual_pct':>10} {'divergence':>11}  FACADE")
    print("-" * 55)
    results = []
    for iso2 in PILOT_COUNTRIES:
        if iso2 not in universe:
            print(f"{iso2:4}  MISSING FROM UNIVERSE")
            continue
        quantitative_score = quant_pct[iso2]
        qualitative_score = (freexp_pct[iso2] + corr_pct[iso2] + rule_pct[iso2]) / 3
        divergence = quantitative_score - qualitative_score
        facade = divergence >= FACADE_THRESHOLD
        results.append((iso2, quantitative_score, qualitative_score, divergence, facade))
        print(f"{iso2:4} {quantitative_score:10.3f} {qualitative_score:10.3f} {divergence:11.3f}  "
              f"{'FACADE' if facade else '-'}")

    print(f"\n[component breakdown]")
    for iso2 in PILOT_COUNTRIES:
        if iso2 not in universe:
            continue
        d = quant[iso2]
        print(f"  {iso2}: dep={d['deprivation']:.3f} strain={d['strain']:.3f} flo={d['flourishing']:.3f}"
              f"  (quant_goodness={quant_goodness[iso2]:.3f}, pct={quant_pct[iso2]:.3f})  |  "
              f"freexp_pct={freexp_pct[iso2]:.3f} corr_inv_pct={corr_pct[iso2]:.3f} rule_pct={rule_pct[iso2]:.3f}")

    print(f"\n[PRE-REGISTERED TEST] BG/HU/RU facade=True, DE facade=False  (threshold={FACADE_THRESHOLD})")
    by_iso = {r[0]: r for r in results}
    passed = True
    for iso2 in ["BG", "HU", "RU"]:
        if iso2 not in by_iso:
            print(f"  SKIP: {iso2} not in universe")
            continue
        if not by_iso[iso2][4]:
            print(f"  FAIL: {iso2} expected FACADE, got not-facade (divergence={by_iso[iso2][3]:.3f})")
            passed = False
    if "DE" in by_iso and by_iso["DE"][4]:
        print(f"  FAIL: DE expected NOT facade, got FACADE (divergence={by_iso['DE'][3]:.3f})")
        passed = False
    print("  RESULT:", "TEST PASSED -- mechanism demonstrated" if passed else "TEST FAILED -- inspect metric")

    # ══════════════════════════════════════════════════════════════════════
    # FULL-UNIVERSE RUN — no predictions, just the numbers for every country
    # ══════════════════════════════════════════════════════════════════════
    all_results = []
    for iso2 in universe:
        quantitative_score = quant_pct[iso2]
        qualitative_score = (freexp_pct[iso2] + corr_pct[iso2] + rule_pct[iso2]) / 3
        divergence = quantitative_score - qualitative_score
        all_results.append((iso2, quant[iso2]["name"], quantitative_score, qualitative_score, divergence))

    all_results.sort(key=lambda r: -r[4])

    print("\n" + "=" * 76)
    print(f"FULL UNIVERSE RUN — {len(all_results)} countries with complete WB + V-Dem data")
    print("=" * 76)

    facade_list = [r for r in all_results if r[4] >= FACADE_THRESHOLD]
    total_wb_countries = len(quant)
    no_data = total_wb_countries - len(all_results)

    print(f"\n[DISTRIBUTION]")
    print(f"  Total WB wellbeing countries : {total_wb_countries}")
    print(f"  In universe (has V-Dem too)  : {len(all_results)}")
    print(f"  No V-Dem data (excluded)     : {no_data}")
    print(f"  FACADE (divergence >= {FACADE_THRESHOLD})     : {len(facade_list)}  "
          f"({100*len(facade_list)/len(all_results):.1f}% of universe)")
    print(f"  Clean (divergence < {FACADE_THRESHOLD})       : {len(all_results)-len(facade_list)}")

    print(f"\n[ALL FACADE COUNTRIES, sorted by divergence desc — {len(facade_list)} total]")
    print(f"  {'ISO':4} {'Name':32} {'quant':>7} {'qual':>7} {'div':>7}")
    for iso2, name, q, ql, div in facade_list:
        print(f"  {iso2:4} {name:32} {q:7.3f} {ql:7.3f} {div:7.3f}")

    print(f"\n[TOP 10 LARGEST DIVERGENCE]")
    print(f"  {'ISO':4} {'Name':32} {'quant':>7} {'qual':>7} {'div':>7}")
    for iso2, name, q, ql, div in all_results[:10]:
        print(f"  {iso2:4} {name:32} {q:7.3f} {ql:7.3f} {div:7.3f}")

    print(f"\n[TOP 10 SMALLEST DIVERGENCE — most 'honest' / aligned]")
    print(f"  {'ISO':4} {'Name':32} {'quant':>7} {'qual':>7} {'div':>7}")
    for iso2, name, q, ql, div in all_results[-10:][::-1]:
        print(f"  {iso2:4} {name:32} {q:7.3f} {ql:7.3f} {div:7.3f}")


if __name__ == "__main__":
    main()
