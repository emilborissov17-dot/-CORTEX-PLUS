#!/usr/bin/env python3
"""Build isolated red-team input fixtures for _divergence_pilot.py logic.

Ground truth (4 synthetic countries, ISO2=Z1..Z4 / ISO3=ZZ1..ZZ4 — digit-suffixed
so they can never collide with a real ISO2/ISO3 code):

  Z1 / ZZ1  FACADE          quant looks great, qual practice is weak   -> expect FACADE=True
  Z2 / ZZ2  REVERSE         quant looks bad,   qual practice is strong -> expect FACADE=False (negative divergence)
  Z3 / ZZ3  CONTROL-GOOD    good on both sides                          -> expect FACADE=False (~0 divergence)
  Z4 / ZZ4  CONTROL-BAD     bad on both sides                           -> expect FACADE=False (~0 divergence)

Not part of the production pipeline. Reads production files, writes only into test/redteam/.
"""
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

WELLBEING_SRC = BASE / "output" / "wellbeing_all_countries.json"
VDEM_SRC = BASE / "data" / "V-Dem-CY-Core-v16.csv"

SYNTH = {
    "Z1": dict(iso3="ZZ1", name="Redteam Facade (ZZ1)", label="FACADE",
               deprivation=0.10, strain=0.15, flourishing=0.85,
               v2x_freexp_altinf=0.15, v2x_corr=0.75, v2x_rule=0.20),
    "Z2": dict(iso3="ZZ2", name="Redteam Reverse (ZZ2)", label="REVERSE",
               deprivation=0.70, strain=0.65, flourishing=0.30,
               v2x_freexp_altinf=0.80, v2x_corr=0.10, v2x_rule=0.75),
    "Z3": dict(iso3="ZZ3", name="Redteam Control-Good (ZZ3)", label="CONTROL-GOOD",
               deprivation=0.15, strain=0.20, flourishing=0.80,
               v2x_freexp_altinf=0.75, v2x_corr=0.12, v2x_rule=0.70),
    "Z4": dict(iso3="ZZ4", name="Redteam Control-Bad (ZZ4)", label="CONTROL-BAD",
               deprivation=0.75, strain=0.70, flourishing=0.25,
               v2x_freexp_altinf=0.18, v2x_corr=0.70, v2x_rule=0.22),
}


def build_wellbeing():
    data = json.loads(WELLBEING_SRC.read_text(encoding="utf-8"))
    for iso2, s in SYNTH.items():
        data["countries"].append({
            "iso2": iso2, "name": s["name"], "region": "ZZ", "income": "N/A",
            "zone": "REDTEAM", "zone_label": "REDTEAM SYNTHETIC",
            "deprivation": s["deprivation"], "strain": s["strain"], "flourishing": s["flourishing"],
            "confidence": "SYNTHETIC", "completeness": "synthetic/redteam",
            "null_axes": [], "suspect_axes": [],
            "computed_at": "2026-07-06T00:00:00+00:00", "status": "ok",
        })
    data["total"] = len(data["countries"])
    out_path = OUT / "wellbeing_all_countries_redteam.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(data['countries'])} countries, {len(SYNTH)} synthetic)")


def build_vdem():
    with open(VDEM_SRC, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    out_path = OUT / "vdem_redteam.csv"
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for iso2, s in SYNTH.items():
            row = {col: "" for col in header}
            row["country_name"] = s["name"]
            row["country_text_id"] = s["iso3"]
            row["year"] = "2026"
            row["v2x_freexp_altinf"] = s["v2x_freexp_altinf"]
            row["v2x_corr"] = s["v2x_corr"]
            row["v2x_rule"] = s["v2x_rule"]
            w.writerow([row[col] for col in header])
    print(f"wrote {out_path} (header + {len(SYNTH)} synthetic rows only — NOT a full CSV copy, 212MB source skipped)")


if __name__ == "__main__":
    build_wellbeing()
    build_vdem()
