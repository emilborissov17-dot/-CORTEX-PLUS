"""
wellbeing_globe.py — Merkle continent/globe aggregation tree.

Reads output/wellbeing_all_countries.json (217 countries, pre-computed dep/str/flo)
and builds a three-level Merkle tree:

  GLOBE (1 root hash)
  └── 7 WB region nodes (continent hashes)
      └── 217 country leaf hashes

Aggregation is population-weighted (SP.POP.TOTL from wb_cache/{ISO2}.json).
Countries missing population fall back to equal weight=1 and are flagged pop_estimated.

Outputs:
  output/wellbeing_continent.json  — 7 region nodes with dep/str/flo + hashes
  output/wellbeing_globe.json      — global aggregation + globe hash

The globe hash is also written to cortex_memory/abstractions/hashes.json so the
next MerkleMemory.commit() picks it up via _update_abs_hashes().

Usage:
  python wellbeing_globe.py              # compute and save
  python wellbeing_globe.py --verify     # recompute and check hashes match saved
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent
ALL_CTRY     = ROOT / "output" / "wellbeing_all_countries.json"
WB_CACHE_DIR = ROOT / "output" / "wb_cache"
OUT_CONT     = ROOT / "output" / "wellbeing_continent.json"
OUT_GLOBE    = ROOT / "output" / "wellbeing_globe.json"
ABS_HASHES   = ROOT / "cortex_memory" / "abstractions" / "hashes.json"

# WB region code → human-readable name
REGION_NAMES: dict[str, str] = {
    "EAS": "East Asia & Pacific",
    "ECS": "Europe & Central Asia",
    "LCN": "Latin America & Caribbean",
    "MEA": "Middle East & North Africa",
    "NAC": "North America",
    "SAS": "South Asia",
    "SSF": "Sub-Saharan Africa",
}


# ── Hashing ────────────────────────────────────────────────────────────────────

def _sha256(data: Any) -> str:
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Population loading ─────────────────────────────────────────────────────────

def _load_population(iso2: str) -> tuple[float, bool]:
    """Return (population, estimated). Falls back to 1.0 if not found."""
    cache = WB_CACHE_DIR / f"{iso2}.json"
    if cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8")).get("raw", {})
            pop = raw.get("SP.POP.TOTL")
            if pop and pop > 0:
                return float(pop), False
        except Exception:
            pass
    return 1.0, True


# ── Leaf hashing ───────────────────────────────────────────────────────────────

def _leaf_hash(c: dict, pop: float) -> str:
    """Canonical hash for one country — changing dep/str/flo/zone changes this."""
    return _sha256({
        "iso2":        c["iso2"],
        "dep":         round(c["deprivation"], 6),
        "str":         round(c["strain"], 6),
        "flo":         round(c["flourishing"], 6),
        "zone":        c["zone"],
        "confidence":  c["confidence"],
        "pop":         pop,
        "computed_at": c.get("computed_at", ""),
    })


# ── Population-weighted mean ───────────────────────────────────────────────────

def _pw_mean(values: list[float], weights: list[float]) -> float:
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    return round(sum(v * w for v, w in zip(values, weights)) / total_w, 6)


# ── Zone modal (by population) ─────────────────────────────────────────────────

def _modal_zone(zones: list[str], weights: list[float]) -> str:
    zone_pop: dict[str, float] = defaultdict(float)
    for z, w in zip(zones, weights):
        zone_pop[z] += w
    return max(zone_pop, key=lambda z: zone_pop[z])


def _zone_distribution(zones: list[str]) -> dict[str, int]:
    dist: dict[str, int] = defaultdict(int)
    for z in zones:
        dist[z] += 1
    return dict(dist)


# ── Confidence summary ─────────────────────────────────────────────────────────

def _confidence_summary(confidences: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for c in confidences:
        counts[c] += 1
    return dict(counts)


# ── Core aggregation ───────────────────────────────────────────────────────────

def build_tree(countries: list[dict]) -> tuple[dict, dict]:
    """
    Build the continent + globe nodes.
    Returns (continent_data, globe_data) — both include Merkle hashes.
    """
    # Group by WB region
    by_region: dict[str, list[dict]] = defaultdict(list)
    for c in countries:
        by_region[c.get("region", "UNKNOWN")].append(c)

    continent_nodes: list[dict] = []

    for region_id in sorted(by_region):
        region_countries = by_region[region_id]

        # Load population for each country in region
        pops: list[float] = []
        pop_estimated_flags: list[bool] = []
        for c in region_countries:
            pop, estimated = _load_population(c["iso2"])
            pops.append(pop)
            pop_estimated_flags.append(estimated)

        deps = [c["deprivation"] for c in region_countries]
        strs = [c["strain"]      for c in region_countries]
        flos = [c["flourishing"] for c in region_countries]
        zones = [c["zone"]       for c in region_countries]
        confs = [c["confidence"] for c in region_countries]

        dep_pw = _pw_mean(deps, pops)
        str_pw = _pw_mean(strs, pops)
        flo_pw = _pw_mean(flos, pops)

        # Leaf hashes (sorted for determinism)
        leaf_hashes = sorted(_leaf_hash(c, p) for c, p in zip(region_countries, pops))

        region_hash = _sha256({
            "region_id":     region_id,
            "dep":           dep_pw,
            "str":           str_pw,
            "flo":           flo_pw,
            "pop_total":     sum(pops),
            "country_count": len(region_countries),
            "leaf_hashes":   leaf_hashes,
        })

        continent_nodes.append({
            "region_id":        region_id,
            "region_name":      REGION_NAMES.get(region_id, region_id),
            "country_count":    len(region_countries),
            "pop_total":        round(sum(pops)),
            "pop_estimated_n":  sum(pop_estimated_flags),
            "dep":              dep_pw,
            "str":              str_pw,
            "flo":              flo_pw,
            "modal_zone":       _modal_zone(zones, pops),
            "zone_distribution": _zone_distribution(zones),
            "confidence_distribution": _confidence_summary(confs),
            "countries":        sorted(c["iso2"] for c in region_countries),
            "leaf_hashes":      leaf_hashes,
            "hash":             region_hash,
        })

    # Globe: pop-weighted across ALL countries (not continental means)
    all_pops: list[float] = []
    all_deps: list[float] = []
    all_strs: list[float] = []
    all_flos: list[float] = []
    all_zones: list[str] = []

    for node in continent_nodes:
        # Re-expand: use region's aggregate weighted by region pop
        # (equivalent to weighting all countries directly — verified by construction)
        all_pops.append(float(node["pop_total"]))
        all_deps.append(node["dep"])
        all_strs.append(node["str"])
        all_flos.append(node["flo"])
        all_zones.append(node["modal_zone"])

    globe_dep = _pw_mean(all_deps, all_pops)
    globe_str = _pw_mean(all_strs, all_pops)
    globe_flo = _pw_mean(all_flos, all_pops)

    region_hashes = sorted(n["hash"] for n in continent_nodes)

    globe_hash = _sha256({
        "dep":           globe_dep,
        "str":           globe_str,
        "flo":           globe_flo,
        "pop_total":     sum(all_pops),
        "country_count": len(countries),
        "region_hashes": region_hashes,
    })

    # Zone distribution across all countries
    all_country_zones = [c["zone"] for c in countries]
    all_country_confs = [c["confidence"] for c in countries]

    globe_data = {
        "globe_hash":     globe_hash,
        "computed_at":    datetime.now(timezone.utc).isoformat(),
        "country_count":  len(countries),
        "pop_total":      round(sum(all_pops)),
        "dep":            globe_dep,
        "str":            globe_str,
        "flo":            globe_flo,
        "modal_zone":     _modal_zone(all_country_zones, [_load_population(c["iso2"])[0] for c in countries]),
        "zone_distribution":       _zone_distribution(all_country_zones),
        "confidence_distribution": _confidence_summary(all_country_confs),
        "region_hashes":  region_hashes,
        "regions":        {n["region_id"]: n["hash"] for n in continent_nodes},
    }

    continent_data = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "globe_hash":  globe_hash,
        "regions":     continent_nodes,
    }

    return continent_data, globe_data


# ── Governance globals (from wb_cache, no network) ──────────────────────────────
# Population-weighted global scores for the two governance axes, computed directly
# from cached WB indicator data + local V-Dem lookup. No live WB fetch — WGI/V-Dem
# indicators update yearly, so cache staleness here is not a correctness issue
# (unlike dep/str/flo, which need current WB data and go through wellbeing_batch.py).
GOVERNANCE_AXES = ["GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL", "GOVERNANCE_INSTITUTIONS_REVIEW"]
GOVERNANCE_SOURCE_LABEL = "WGI+VDEM via wb_cache"


def compute_governance_globals() -> dict:
    """
    Returns:
      {
        "globals": {axis: pw_mean_score or None},
        "per_country": {iso2: {axis: score}},
        "country_count": int,
        "skipped": [{"iso2": str, "reason": str}],
      }
    """
    from wellbeing_country import _inject_vdem, _normalize, _axis_score, _IND

    per_country: dict[str, dict[str, float]] = {}
    pops: dict[str, float] = {}
    skipped: list[dict[str, str]] = []

    for f in sorted(WB_CACHE_DIR.glob("*.json")):
        iso2 = f.stem
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            skipped.append({"iso2": iso2, "reason": f"unreadable cache: {e}"})
            continue
        raw = data.get("raw", {})
        if not raw:
            skipped.append({"iso2": iso2, "reason": "empty cache"})
            continue

        _inject_vdem(iso2, raw)  # disk-only backfill of VDEM_FREEXP/VDEM_CORR/VDEM_RULE

        norm = {
            code: _normalize(code, v)
            for code, v in raw.items()
            if v is not None and code in _IND and _IND[code] is not None
        }

        scores = {}
        for axis in GOVERNANCE_AXES:
            s = _axis_score(axis, norm)
            if s is not None:
                scores[axis] = s

        if scores:
            per_country[iso2] = scores
            pop = raw.get("SP.POP.TOTL")
            pops[iso2] = float(pop) if pop and pop > 0 else 1.0
        else:
            skipped.append({"iso2": iso2, "reason": "no governance indicators (WGI+V-Dem both null)"})

    globals_out: dict[str, float | None] = {}
    for axis in GOVERNANCE_AXES:
        vals = [scores[axis] for scores in per_country.values() if axis in scores]
        wts  = [pops[iso2] for iso2, scores in per_country.items() if axis in scores]
        globals_out[axis] = _pw_mean(vals, wts) if vals else None

    return {
        "globals": globals_out,
        "per_country": per_country,
        "country_count": len(per_country),
        "skipped": skipped,
    }


def update_governance_output(result: dict) -> dict:
    """Merge governance globals + provenance into output/wellbeing_globe.json, save, return merged dict."""
    globe_data: dict = {}
    if OUT_GLOBE.exists():
        try:
            globe_data = json.loads(OUT_GLOBE.read_text(encoding="utf-8"))
        except Exception:
            globe_data = {}

    now = datetime.now(timezone.utc).isoformat()
    globe_data["governance_rights_score"]        = result["globals"].get("GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL")
    globe_data["governance_institutions_score"]   = result["globals"].get("GOVERNANCE_INSTITUTIONS_REVIEW")
    globe_data["governance_source"]               = GOVERNANCE_SOURCE_LABEL
    globe_data["governance_country_count"]        = result["country_count"]
    globe_data["governance_skipped_countries"]    = result["skipped"]
    globe_data["governance_computed_at"]          = now

    OUT_GLOBE.parent.mkdir(parents=True, exist_ok=True)
    OUT_GLOBE.write_text(json.dumps(globe_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return globe_data


# ── Verification ───────────────────────────────────────────────────────────────

def verify(countries: list[dict]) -> bool:
    """Recompute tree and compare hashes to saved output."""
    if not OUT_GLOBE.exists():
        print("ERROR: output/wellbeing_globe.json not found — run without --verify first")
        return False

    saved_globe = json.loads(OUT_GLOBE.read_text(encoding="utf-8"))
    saved_hash = saved_globe["globe_hash"]

    _, globe_data = build_tree(countries)
    recomputed = globe_data["globe_hash"]

    ok = saved_hash == recomputed
    status = "OK" if ok else "MISMATCH"
    print(f"Verification: {status}")
    print(f"  saved:      {saved_hash[:32]}...")
    print(f"  recomputed: {recomputed[:32]}...")
    return ok


# ── Update ABS_HASHES ──────────────────────────────────────────────────────────

def _update_abs_hashes(globe_hash: str):
    """Write globe hash into cortex_memory/abstractions/hashes.json."""
    ABS_HASHES.parent.mkdir(parents=True, exist_ok=True)
    hashes: dict = {}
    if ABS_HASHES.exists():
        try:
            hashes = json.loads(ABS_HASHES.read_text(encoding="utf-8"))
        except Exception:
            pass
    hashes["wellbeing_globe"] = globe_hash
    ABS_HASHES.write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def _run_governance_only():
    """Compute governance globals from wb_cache and merge into output/wellbeing_globe.json. No network."""
    result = compute_governance_globals()
    print(f"[governance] {result['country_count']} countries scored (from {WB_CACHE_DIR})")
    print()
    for axis, score in result["globals"].items():
        print(f"  GLOBAL {axis:<38} = {score}")
    print()
    print("  Sanity check — per-country scores:")
    for iso2 in ("DE", "BG", "RU"):
        scores = result["per_country"].get(iso2, {})
        print(f"    {iso2}: {scores}")

    if result["skipped"]:
        print(f"\n  Skipped {len(result['skipped'])} countries (no usable governance data):")
        for s in result["skipped"]:
            print(f"    {s['iso2']}: {s['reason']}")

    merged = update_governance_output(result)
    print(f"\nSaved governance fields to {OUT_GLOBE}")
    print(f"  governance_computed_at: {merged['governance_computed_at']}")


def main():
    parser = argparse.ArgumentParser(description="Build Merkle continent/globe tree")
    parser.add_argument("--verify", action="store_true", help="verify saved hashes match recomputed")
    parser.add_argument("--governance-only", action="store_true",
                         help="compute governance axis globals from wb_cache only (no network, no dep/str/flo rebuild)")
    args = parser.parse_args()

    if args.governance_only:
        _run_governance_only()
        return

    if not ALL_CTRY.exists():
        print(f"ERROR: {ALL_CTRY} not found — run wellbeing_batch.py first")
        sys.exit(1)

    raw = json.loads(ALL_CTRY.read_text(encoding="utf-8"))
    countries = raw["countries"]
    print(f"Loaded {len(countries)} countries (source computed_at: {raw.get('computed_at', '?')})")

    if args.verify:
        ok = verify(countries)
        sys.exit(0 if ok else 1)

    continent_data, globe_data = build_tree(countries)

    # Save outputs
    OUT_CONT.write_text(json.dumps(continent_data, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_GLOBE.write_text(json.dumps(globe_data,    ensure_ascii=False, indent=2), encoding="utf-8")
    _update_abs_hashes(globe_data["globe_hash"])

    # Print summary
    print(f"\nGlobe hash: {globe_data['globe_hash'][:32]}...")
    print(f"  dep={globe_data['dep']:.3f}  str={globe_data['str']:.3f}  flo={globe_data['flo']:.3f}")
    print(f"  pop_total={globe_data['pop_total']:,}  countries={globe_data['country_count']}")
    print(f"  modal_zone: {globe_data['modal_zone']}")
    print(f"  zones: {globe_data['zone_distribution']}")
    print(f"\nRegion breakdown:")
    for r in continent_data["regions"]:
        print(
            f"  {r['region_id']:3s}  {r['region_name']:35s}"
            f"  N={r['country_count']:3d}  dep={r['dep']:.3f}  str={r['str']:.3f}  flo={r['flo']:.3f}"
            f"  modal={r['modal_zone']}"
        )
    print(f"\nSaved:")
    print(f"  {OUT_CONT}")
    print(f"  {OUT_GLOBE}")
    print(f"  {ABS_HASHES}  (globe hash added)")


if __name__ == "__main__":
    main()
