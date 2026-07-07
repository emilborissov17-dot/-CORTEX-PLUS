#!/usr/bin/env python3
"""Build a boundary-case red-team fixture: 3 synthetic countries injected into a COPY
of the REAL ~175-country universe (not an isolated 4-country toy universe like the
previous test/redteam run). Percentiles are therefore computed against the real
distribution, which is what the production _divergence_pilot.py actually does.

Method: read the real V-Dem CSV (streamed, not copied — 212MB) and the real
output/wellbeing_all_countries.json with the exact same loaders as _divergence_pilot.py,
compute the real universe's quant_goodness / freexp_raw / corr_inv_raw / rule_raw
distributions, then use linear-interpolated percentile lookup to construct 3 synthetic
countries whose TRUE (by-construction) divergence sits just below, exactly at, and just
above FACADE_THRESHOLD=0.20:

  Y1  BELOW    quant_pct~0.53, qual_pct~0.35  -> divergence ~0.18
  Y2  EXACT    quant_pct~0.55, qual_pct~0.35  -> divergence ~0.20
  Y3  ABOVE    quant_pct~0.57, qual_pct~0.35  -> divergence ~0.22

quant_goodness is hit by construction (dep=strain=1-g, flo=g so goodness=g exactly).
qual axis is hit approximately: freexp/corr/rule are each set to the real value at the
target percentile in their OWN real distribution, so all three sub-percentiles land near
qual_pct independently. Exact post-insertion percentile is computed and reported by
run_boundary.py, not assumed here.

Not part of the production pipeline. Reads production files, writes only into test/redteam/.
"""
import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from wellbeing_country import _iso2_to_iso3  # noqa: E402

WELLBEING_SRC = BASE / "output" / "wellbeing_all_countries.json"
VDEM_SRC = BASE / "data" / "V-Dem-CY-Core-v16.csv"

PRACTICE_VARS = ["v2x_freexp_altinf", "v2x_corr", "v2x_rule"]


def load_vdem_practice() -> dict:
    best = {}
    with open(VDEM_SRC, encoding="utf-8", newline="") as f:
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
    data = json.loads(WELLBEING_SRC.read_text(encoding="utf-8"))
    out = {}
    for c in data["countries"]:
        if c.get("status") != "ok":
            continue
        dep, strain, flo = c.get("deprivation"), c.get("strain"), c.get("flourishing")
        if dep is None or strain is None or flo is None or dep < 0 or strain < 0 or flo < 0:
            continue
        out[c["iso2"]] = {"deprivation": dep, "strain": strain, "flourishing": flo, "name": c.get("name", c["iso2"])}
    return out


def interp_percentile(sorted_vals: list, p: float) -> float:
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = p * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


TARGETS = {
    "Y1": dict(label="BELOW 0.20", p_q=0.53, p_ql=0.35),
    "Y2": dict(label="EXACT 0.20", p_q=0.55, p_ql=0.35),
    "Y3": dict(label="ABOVE 0.20", p_q=0.57, p_ql=0.35),
}


def main():
    print("Loading real V-Dem CSV (streaming 212MB, not copying)...")
    vdem = load_vdem_practice()
    print(f"  -> {len(vdem)} real countries with complete 2018+ practice vars")

    print("Loading real wellbeing_all_countries.json...")
    quant = load_wellbeing_quant()
    print(f"  -> {len(quant)} real countries with status=ok wellbeing data")

    universe = [iso2 for iso2 in quant if (iso3 := _iso2_to_iso3(iso2)) and iso3 in vdem]
    print(f"  -> real universe (WB wellbeing quant/qual intersection): {len(universe)} countries\n")

    quant_goodness = {
        iso2: (1 - quant[iso2]["deprivation"] + 1 - quant[iso2]["strain"] + quant[iso2]["flourishing"]) / 3
        for iso2 in universe
    }
    freexp_raw = {iso2: vdem[_iso2_to_iso3(iso2)]["v2x_freexp_altinf"] for iso2 in universe}
    corr_inv_raw = {iso2: 1.0 - vdem[_iso2_to_iso3(iso2)]["v2x_corr"] for iso2 in universe}
    rule_raw = {iso2: vdem[_iso2_to_iso3(iso2)]["v2x_rule"] for iso2 in universe}

    qg_sorted = sorted(quant_goodness.values())
    fx_sorted = sorted(freexp_raw.values())
    ci_sorted = sorted(corr_inv_raw.values())
    ru_sorted = sorted(rule_raw.values())

    synth = {}
    for iso2, t in TARGETS.items():
        g = interp_percentile(qg_sorted, t["p_q"])
        dep = strain = round(1 - g, 4)
        flo = round(g, 4)
        freexp = round(interp_percentile(fx_sorted, t["p_ql"]), 4)
        corr_inv = interp_percentile(ci_sorted, t["p_ql"])
        corr = round(1 - corr_inv, 4)
        rule = round(interp_percentile(ru_sorted, t["p_ql"]), 4)
        synth[iso2] = dict(iso3="Y" + iso2, name=f"Redteam Boundary {t['label']} ({iso2})",
                            label=t["label"], target_p_q=t["p_q"], target_p_ql=t["p_ql"],
                            deprivation=dep, strain=strain, flourishing=flo,
                            v2x_freexp_altinf=freexp, v2x_corr=corr, v2x_rule=rule)
        print(f"  {iso2} ({t['label']}): target quant_pct={t['p_q']} -> g={g:.4f} "
              f"(dep=strain={dep}, flo={flo}) | target qual_pct={t['p_ql']} -> "
              f"freexp={freexp} corr={corr} rule={rule}")

    # ── write wellbeing fixture: full real copy (217) + 3 synthetic ──
    real_data = json.loads(WELLBEING_SRC.read_text(encoding="utf-8"))
    for iso2, s in synth.items():
        real_data["countries"].append({
            "iso2": iso2, "name": s["name"], "region": "ZZ", "income": "N/A",
            "zone": "REDTEAM", "zone_label": "REDTEAM BOUNDARY SYNTHETIC",
            "deprivation": s["deprivation"], "strain": s["strain"], "flourishing": s["flourishing"],
            "confidence": "SYNTHETIC", "completeness": "synthetic/redteam-boundary",
            "null_axes": [], "suspect_axes": [],
            "computed_at": "2026-07-06T00:00:00+00:00", "status": "ok",
        })
    real_data["total"] = len(real_data["countries"])
    (OUT / "wellbeing_boundary_real.json").write_text(
        json.dumps(real_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote wellbeing_boundary_real.json ({len(real_data['countries'])} countries, "
          f"{len(quant)} real + {len(synth)} synthetic)")

    # ── write V-Dem fixture: one row per REAL universe country (their actual MRV
    #    practice row, reduced) + 3 synthetic rows. NOT the raw 212MB multi-year file --
    #    this reproduces exactly what load_vdem_practice() would already reduce it to. ──
    with open(VDEM_SRC, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    with open(OUT / "vdem_boundary_real.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for iso2 in universe:
            iso3 = _iso2_to_iso3(iso2)
            row = {col: "" for col in header}
            row["country_name"] = quant[iso2]["name"]
            row["country_text_id"] = iso3
            row["year"] = str(vdem[iso3]["_year"])
            row["v2x_freexp_altinf"] = vdem[iso3]["v2x_freexp_altinf"]
            row["v2x_corr"] = vdem[iso3]["v2x_corr"]
            row["v2x_rule"] = vdem[iso3]["v2x_rule"]
            w.writerow([row[col] for col in header])
        for iso2, s in synth.items():
            row = {col: "" for col in header}
            row["country_name"] = s["name"]
            row["country_text_id"] = s["iso3"]
            row["year"] = "2026"
            row["v2x_freexp_altinf"] = s["v2x_freexp_altinf"]
            row["v2x_corr"] = s["v2x_corr"]
            row["v2x_rule"] = s["v2x_rule"]
            w.writerow([row[col] for col in header])
    print(f"wrote vdem_boundary_real.csv (header + {len(universe)} real MRV rows + {len(synth)} synthetic rows)")

    (OUT / "boundary_ground_truth.json").write_text(
        json.dumps(synth, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
