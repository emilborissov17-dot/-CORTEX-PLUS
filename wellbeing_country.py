"""
wellbeing_country.py — Phase 2a: per-country WellbeingProfile from World Bank data.

Fetches WB indicators for a single country (ISO2 code), normalizes to [0,1],
computes axis scores, and returns a WellbeingProfile with full decomposition.

LIMITATION (see docs/WELLBEING_PROFILE_DESIGN.md § Критично ограничение):
  WGI governance included (CC.EST, GE.EST, RL.EST via GOV_WGI_ prefix).
  Lived experience, quality of services, materials/waste, social relations still absent.
  Zone label may be INFLATED vs. lived reality — read with this explicitly in mind.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from wellbeing_profile import WellbeingProfile, compute_wellbeing_profile

# ── Paths ──────────────────────────────────────────────────────────────────────
CACHE_DIR = Path(__file__).parent / "output" / "wb_cache"
CACHE_TTL_SECONDS = 86_400   # 24h

WB_BASE = "https://api.worldbank.org/v2"

# ── Indicator normalization specs ──────────────────────────────────────────────
# Format: code → (worst, best, invert)
#   worst: raw value that maps to score 0.0
#   best:  raw value that maps to score 1.0
#   invert=True: lower raw → higher score  (e.g. poverty, mortality, emissions)
# Special sentinel "GDP_LOG": log-scale normalization (see _normalize).

_IND: dict[str, object] = {
    "SN.ITK.DEFC.ZS":    (60.0,    2.5,    True),   # Undernourishment %
    "AG.PRD.FOOD.XD":    (40.0,  200.0,   False),   # Food production index (2014-16=100)
    "AG.YLD.CREL.KG":    (400.0, 12000.0, False),   # Cereal yield kg/ha
    "SH.H2O.SMDW.ZS":   (0.0,   100.0,   False),   # Safe water access %
    "SP.DYN.LE00.IN":    (40.0,   85.0,   False),   # Life expectancy yr
    "SP.DYN.IMRT.IN":    (120.0,   2.0,    True),   # Infant mortality /1k live births
    "SI.POV.GINI":       (70.0,   20.0,    True),   # Gini index
    "SI.POV.DDAY":       (90.0,    0.0,    True),   # Poverty <$2.15/day %
    "EN.ATM.CO2E.PC":    (20.0,    0.0,    True),   # CO2 per capita metric tons
    "EG.USE.COMM.FO.ZS": (100.0,   0.0,    True),   # Fossil fuel % of total energy
    "NY.ADJ.DRES.GN.ZS": (30.0,    0.0,    True),   # Resource depletion % GNI
    "SE.ADT.LITR.ZS":    (0.0,   100.0,   False),   # Adult literacy rate %
    "IT.NET.USER.ZS":    (0.0,   100.0,   False),   # Internet users %
    "IT.NET.BBND.P2":    (0.0,    50.0,   False),   # Fixed broadband subscriptions /100
    "EG.ELC.ACCS.ZS":    (0.0,   100.0,   False),   # Electricity access %
    "IT.CEL.SETS.P2":    (0.0,   200.0,   False),   # Mobile subscriptions /100
    "SP.URB.TOTL.IN.ZS": (5.0,   100.0,   False),   # Urban population %
    "EG.ELC.RNEW.ZS":    (0.0,   100.0,   False),   # Renewable electricity % of total
    "SE.PRM.ENRR":       (0.0,   100.0,   False),   # Primary school enrollment % (gross, capped)
    "NY.GDP.PCAP.PP.KD": "GDP_LOG",                  # GDP per capita PPP 2017 USD (log-scale)
    "SL.UEM.TOTL.ZS":    (35.0,    2.0,    True),   # Unemployment % of labour force
    "NY.GDP.MKTP.KD.ZG": (-10.0,  10.0,   False),   # GDP growth annual %
    "AG.LND.FRST.ZS":    (0.0,    95.0,   False),   # Forest area % of land
    "NY.ADJ.SVNG.GN.ZS": (-30.0,  40.0,   False),   # Adjusted net savings % GNI
    "EG.FEC.RNEW.ZS":    (0.0,   100.0,   False),   # Renewable % of total final energy consumption
    # WGI governance indicators (GOV_WGI_ prefix required, range ≈ −2.5 to +2.5)
    "GOV_WGI_CC.EST":    (-2.5,   2.5,   False),   # Control of Corruption
    "GOV_WGI_GE.EST":    (-2.5,   2.5,   False),   # Government Effectiveness
    "GOV_WGI_RL.EST":    (-2.5,   2.5,   False),   # Rule of Law
}

_LABELS: dict[str, str] = {
    "SN.ITK.DEFC.ZS":    "Undernourishment %",
    "AG.PRD.FOOD.XD":    "Food production index",
    "AG.YLD.CREL.KG":    "Cereal yield kg/ha",
    "SH.H2O.SMDW.ZS":   "Safe water access %",
    "SP.DYN.LE00.IN":    "Life expectancy yr",
    "SP.DYN.IMRT.IN":    "Infant mortality /1k",
    "SI.POV.GINI":       "Gini index",
    "SI.POV.DDAY":       "Poverty <$2.15/day %",
    "EN.ATM.CO2E.PC":    "CO2 per capita tons",
    "EG.USE.COMM.FO.ZS": "Fossil fuel % energy",
    "NY.ADJ.DRES.GN.ZS": "Resource depletion %GNI",
    "SE.ADT.LITR.ZS":    "Adult literacy %",
    "IT.NET.USER.ZS":    "Internet users %",
    "IT.NET.BBND.P2":    "Fixed broadband /100",
    "EG.ELC.ACCS.ZS":    "Electricity access %",
    "IT.CEL.SETS.P2":    "Mobile subscriptions /100",
    "SP.URB.TOTL.IN.ZS": "Urban population %",
    "EG.ELC.RNEW.ZS":    "Renewable electricity %",
    "SE.PRM.ENRR":       "Primary school enrollment %",
    "NY.GDP.PCAP.PP.KD": "GDP per capita PPP (2017$)",
    "SL.UEM.TOTL.ZS":    "Unemployment %",
    "NY.GDP.MKTP.KD.ZG": "GDP growth annual %",
    "AG.LND.FRST.ZS":    "Forest area % of land",
    "NY.ADJ.SVNG.GN.ZS": "Adj net savings %GNI",
    "EG.FEC.RNEW.ZS":    "Renewable final energy %",
    "GOV_WGI_CC.EST":    "Corruption Control (WGI)",
    "GOV_WGI_GE.EST":   "Govt Effectiveness (WGI)",
    "GOV_WGI_RL.EST":   "Rule of Law (WGI)",
}

_GDP_LOG_WORST = math.log(500)
_GDP_LOG_BEST  = math.log(80_000)

# Indicators where WB returns exactly 0.00 as a discontinued/placeholder value
# (not a real zero — e.g. EU fossil fuel series was dropped in some WB updates)
_ZERO_IS_NULL = frozenset({"EG.USE.COMM.FO.ZS"})

# Indicators with long reporting lags — look back 10 years to find non-null
_MRV_LONG_CODES = frozenset({
    "EN.ATM.CO2E.PC",   # CO2 per capita: 3-5 year lag typical
    "SE.ADT.LITR.ZS",   # literacy: updated every few years
    "SI.POV.GINI",      # Gini: updated every 2-4 years
    "AG.LND.FRST.ZS",   # forest area: updated every 5 years (FAO)
})

# Fetched raw but NOT normalized — used only for derived computations
_FETCH_ALSO = ["EN.ATM.CO2E.KT", "SP.POP.TOTL"]


# ── Axis → indicator mapping ───────────────────────────────────────────────────
# Axis score = mean of normalized sub-indicator scores (nulls excluded from mean).
# Keys must match keys in wellbeing_profile.BUNDLES.

AXIS_INDICATORS: dict[str, list[str]] = {
    "FOOD_REVIEW":                      ["SN.ITK.DEFC.ZS", "AG.PRD.FOOD.XD", "AG.YLD.CREL.KG"],
    "WATER_REVIEW":                     ["SH.H2O.SMDW.ZS"],
    "HUMAN_WELL_BEING_REVIEW":          ["SP.DYN.LE00.IN", "SP.DYN.IMRT.IN"],
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": ["GOV_WGI_CC.EST", "GOV_WGI_RL.EST"],
    "INEQUALITY_POVERTY_REVIEW":        ["SI.POV.GINI", "SI.POV.DDAY"],
    "GOVERNANCE_INSTITUTIONS_REVIEW":   ["GOV_WGI_GE.EST", "GOV_WGI_RL.EST", "GOV_WGI_CC.EST"],
    "CLIMATE_GLOBAL_RISK_REVIEW":       ["EN.ATM.CO2E.PC", "EG.USE.COMM.FO.ZS", "NY.ADJ.DRES.GN.ZS", "EG.FEC.RNEW.ZS"],
    "COGNITION_LEARNING_REVIEW":        ["SE.ADT.LITR.ZS"],
    "TECHNOLOGY_AI_REVIEW":             ["IT.NET.USER.ZS", "IT.NET.BBND.P2"],
    "TECHNOLOGY_INFRA_REVIEW":          ["EG.ELC.ACCS.ZS", "IT.CEL.SETS.P2"],
    "INFRASTRUCTURE_CITIES_REVIEW":     ["SP.URB.TOTL.IN.ZS", "EG.ELC.ACCS.ZS"],
    "ENERGY_REVIEW":                    ["EG.ELC.ACCS.ZS", "EG.ELC.RNEW.ZS", "EG.USE.COMM.FO.ZS"],
    "EDUCATION_CULTURE_REVIEW":         ["SE.ADT.LITR.ZS", "SE.PRM.ENRR"],
    "ECONOMY_WORK_REVIEW":              ["NY.GDP.PCAP.PP.KD", "SL.UEM.TOTL.ZS", "NY.GDP.MKTP.KD.ZG"],
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":   ["AG.LND.FRST.ZS", "NY.ADJ.SVNG.GN.ZS", "NY.ADJ.DRES.GN.ZS"],
}

# Axes in BUNDLES with no adequate WB per-country indicator (structural absence)
STRUCTURAL_MISSING: list[str] = [
    "MATERIALS_WASTE_REVIEW",   # no WB country indicator
    "CULTURE_MEDIA_REVIEW",     # no WB country indicator
]

# ── Data quality constants ────────────────────────────────────────────────────
# Key deprivation axes — null here collapses confidence to LOW immediately
_KEY_DEP_AXES: frozenset[str] = frozenset({
    "FOOD_REVIEW",
    "WATER_REVIEW",
    "HUMAN_WELL_BEING_REVIEW",
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL",
})

# Axis-specific critical indicators: if ALL listed codes are absent the axis
# score is driven by weaker proxies and is likely inflated.
_CRITICAL_MISSING: dict[str, frozenset[str]] = {
    "CLIMATE_GLOBAL_RISK_REVIEW": frozenset({"EN.ATM.CO2E.PC", "EG.USE.COMM.FO.ZS"}),
    "ENERGY_REVIEW":              frozenset({"EG.ELC.RNEW.ZS"}),
}

# Dimension tags for display
_AXIS_DIM: dict[str, str] = {
    "FOOD_REVIEW":                      "dep",
    "WATER_REVIEW":                     "dep",
    "HUMAN_WELL_BEING_REVIEW":          "dep",
    "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL": "dep",
    "INEQUALITY_POVERTY_REVIEW":        "strain",
    "GOVERNANCE_INSTITUTIONS_REVIEW":   "strain",
    "CLIMATE_GLOBAL_RISK_REVIEW":       "strain",
    "COGNITION_LEARNING_REVIEW":        "flo",
    "TECHNOLOGY_AI_REVIEW":             "flo",
    "TECHNOLOGY_INFRA_REVIEW":          "flo",
    "INFRASTRUCTURE_CITIES_REVIEW":     "dep+flo",
    "ENERGY_REVIEW":                    "dep+strain",
    "EDUCATION_CULTURE_REVIEW":         "dep+flo",
    "ECONOMY_WORK_REVIEW":              "dep+strain+flo",
    "ECOSYSTEMS_BIODIVERSITY_REVIEW":   "dep+strain+flo",
}


# ── Normalization ─────────────────────────────────────────────────────────────
def _normalize(code: str, raw: float) -> float:
    """Map a raw WB value to [0, 1] where 1.0 = best possible state."""
    spec = _IND[code]
    if spec == "GDP_LOG":
        if raw <= 0:
            return 0.0
        score = (math.log(raw) - _GDP_LOG_WORST) / (_GDP_LOG_BEST - _GDP_LOG_WORST)
    else:
        worst, best, invert = spec  # type: ignore[misc]
        if code == "SE.PRM.ENRR":   # gross enrollment can exceed 100
            raw = min(raw, 100.0)
        if invert:
            score = (worst - raw) / (worst - best)
        else:
            score = (raw - worst) / (best - worst)
    return max(0.0, min(1.0, score))


def _axis_score(axis: str, norm: dict[str, float]) -> Optional[float]:
    values = [norm[c] for c in AXIS_INDICATORS[axis] if c in norm]
    return sum(values) / len(values) if values else None


# ── Cache ─────────────────────────────────────────────────────────────────────
def _cache_path(iso2: str) -> Path:
    return CACHE_DIR / f"{iso2.upper()}.json"


def _load_cache(iso2: str) -> Optional[dict]:
    p = _cache_path(iso2)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["fetched_at"])).total_seconds()
        if age >= CACHE_TTL_SECONDS:
            return None
        cached = {k: v for k, v in data["raw"].items()}
        # Invalidate cache if any required codes are absent (schema evolved)
        required = set(_IND) | set(_FETCH_ALSO)
        if not required.issubset(cached):
            return None
        return cached
    except Exception:
        pass
    return None


def _save_cache(iso2: str, raw: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(iso2).write_text(
        json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "raw": raw}, indent=2),
        encoding="utf-8",
    )


# ── Fetch ──────────────────────────────────────────────────────────────────────
def _fetch_one(iso2: str, code: str, sess: requests.Session, mrv: int = 5) -> Optional[float]:
    """Fetch most recent non-null value for one indicator."""
    try:
        r = sess.get(
            f"{WB_BASE}/country/{iso2}/indicator/{code}",
            params={"format": "json", "mrv": mrv},
            timeout=15,
        )
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
            return None
        for entry in payload[1]:
            if entry and entry.get("value") is not None:
                return float(entry["value"])
    except Exception as e:
        print(f"    [WB] {code}: {e}")
    return None


def fetch_country_raw(iso2: str) -> dict[str, Optional[float]]:
    """
    Return raw WB indicator values for iso2. Hits disk cache if < 24h old;
    otherwise fetches live and writes cache.

    Post-fetch fixes applied before caching:
    - Codes in _ZERO_IS_NULL with value == 0.0 → None
      (WB returns 0.00 as placeholder for discontinued series, not actual zero)
    - EN.ATM.CO2E.PC derived from EN.ATM.CO2E.KT / SP.POP.TOTL if null
    """
    cached = _load_cache(iso2)
    if cached is not None:
        print(f"  [cache] {iso2} — using cached data (< 24h old)")
        return cached

    all_codes = list(_IND) + _FETCH_ALSO
    print(f"  [WB] fetching {len(all_codes)} indicators for {iso2} ...")
    raw: dict[str, Optional[float]] = {}
    with requests.Session() as sess:
        for code in all_codes:
            mrv = 10 if code in _MRV_LONG_CODES else 5
            raw[code] = _fetch_one(iso2, code, sess, mrv=mrv)

    # Fix 1: treat exact 0.00 as None for known discontinued series
    for code in _ZERO_IS_NULL:
        if raw.get(code) == 0.0:
            print(f"  [fix] {code} = 0.00 → NULL (placeholder for discontinued WB series)")
            raw[code] = None

    # Fix 2: CO2 per capita fallback — derive from total KT + population
    if raw.get("EN.ATM.CO2E.PC") is None:
        kt  = raw.get("EN.ATM.CO2E.KT")
        pop = raw.get("SP.POP.TOTL")
        if kt and pop:
            co2_pc = (kt * 1_000) / pop   # KT × 1000 → metric tons total, ÷ population
            raw["EN.ATM.CO2E.PC"] = round(co2_pc, 3)
            print(f"  [fix] EN.ATM.CO2E.PC derived: {kt:.0f} kt / {pop:.0f} pop = {co2_pc:.2f} t/person")

    _save_cache(iso2, raw)
    return raw


# ── Profile computation ───────────────────────────────────────────────────────
def country_wellbeing(iso2: str) -> dict:
    """
    Fetch WB data for iso2, normalize, compute axis scores, and return a full
    decomposition dict including a WellbeingProfile.

    Result keys:
      iso2, raw_values, normalized, axis_scores, profile (WellbeingProfile),
      structural_missing, data_missing, computed_at
    """
    raw = fetch_country_raw(iso2)

    # Normalize available values
    norm: dict[str, float] = {
        code: _normalize(code, value)
        for code, value in raw.items()
        if value is not None and code in _IND and _IND[code] is not None
    }

    # Per-axis scores (None if all sub-indicators are null)
    axis_scores: dict[str, Optional[float]] = {
        axis: _axis_score(axis, norm) for axis in AXIS_INDICATORS
    }

    # Pass non-null axes to Phase 1 compute function
    scores_in = {axis: score for axis, score in axis_scores.items() if score is not None}
    profile = compute_wellbeing_profile(scores_in)

    data_missing = [a for a, s in axis_scores.items() if s is None]

    result = {
        "iso2":               iso2.upper(),
        "raw_values":         raw,
        "normalized":         norm,
        "axis_scores":        axis_scores,
        "profile":            profile,
        "structural_missing": STRUCTURAL_MISSING,
        "data_missing":       data_missing,
        "computed_at":        profile.computed_at,
    }
    result["data_quality"] = _data_quality(result)

    conf = result["data_quality"]["confidence"]
    zone = profile.zone
    result["zone_label"] = (
        zone                       if conf == "HIGH"   else
        f"{zone} (partial data)"   if conf == "MEDIUM" else
        f"{zone} (UNVERIFIED)"
    )
    return result


# ── Data quality assessment ───────────────────────────────────────────────────
def _data_quality(r: dict) -> dict:
    """
    Classify each mapped axis as real / null / suspect and derive a
    confidence level for the zone label.

    Suspect rules (applied in order, first match wins):
      1. Axis-specific critical codes all absent → score is proxy-only, likely inflated.
         (e.g. CLIMATE without CO2 or fossil-fuel data; ENERGY without renewables %)
      2. Axis has ≥3 indicators and fill rate < 0.5 → thin coverage.

    Confidence:
      LOW    — any key deprivation axis null, OR ≥2 null, OR ≥2 suspect
      MEDIUM — 1 null, OR 1 suspect, OR key dep axis suspect
      HIGH   — all axes real, no suspect flags
    """
    norm = r["normalized"]
    ax   = r["axis_scores"]

    real_axes:    list[str]        = []
    null_axes:    list[str]        = []
    suspect_axes: list[tuple[str, str]] = []   # (axis, reason)

    for axis, score in ax.items():
        inds        = AXIS_INDICATORS[axis]
        total_n     = len(inds)
        available_n = sum(1 for c in inds if c in norm)
        fill        = available_n / total_n if total_n else 0.0

        if score is None:
            null_axes.append(axis)
            continue

        critical = _CRITICAL_MISSING.get(axis, frozenset())
        if critical and critical.issubset(set(inds) - set(norm)):
            # all critical indicators for this axis are missing
            suspect_axes.append((axis, f"critical absent: {', '.join(sorted(critical))}"))
        elif total_n >= 3 and fill < 0.5:
            suspect_axes.append((axis, f"{available_n}/{total_n} indicators — thin"))
        else:
            real_axes.append(axis)

    n_null    = len(null_axes)
    n_suspect = len(suspect_axes)
    n_real    = len(real_axes)
    total     = len(ax)

    key_dep_null    = any(a in _KEY_DEP_AXES for a in null_axes)
    key_dep_suspect = any(a in _KEY_DEP_AXES for a, _ in suspect_axes)

    if key_dep_null or n_null >= 2 or n_suspect >= 2:
        confidence = "LOW"
    elif n_null >= 1 or n_suspect >= 1 or key_dep_suspect:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"

    return {
        "real":         n_real,
        "null":         n_null,
        "suspect":      n_suspect,
        "total":        total,
        "confidence":   confidence,
        "null_axes":    null_axes,
        "suspect_axes": suspect_axes,
        "summary":      f"{n_real}/{total} real, {n_null} null, {n_suspect} suspect",
    }


# ── CLI output ─────────────────────────────────────────────────────────────────
def _print_result(r: dict) -> None:
    p: WellbeingProfile = r["profile"]
    W = 70

    print(f"\n{'='*W}")
    print(f"  Wellbeing Profile — {r['iso2']}   ({p.computed_at[:10]})")
    print(f"{'='*W}")

    print(f"\n[!] CAVEAT: official WB quantitative data only.")
    print(f"    WGI governance included (CC, GE, RL) — lived experience, quality, materials still absent.")
    print(f"    Zone label may be INFLATED vs. lived reality.")

    # ── Data quality banner ──
    dq   = r.get("data_quality", {})
    conf = dq.get("confidence", "?")
    icon = {"HIGH": "✅", "MEDIUM": "⚡", "LOW": "⚠️ "}.get(conf, "?")
    print(f"\n{icon} Data completeness: {dq.get('summary', '?')}  [{conf} CONFIDENCE]")
    if conf == "LOW":
        print(f"    *** LOW CONFIDENCE — zone label unreliable ***")
    for axis, reason in dq.get("suspect_axes", []):
        print(f"    [suspect] {axis}: {reason}")

    # ── Raw → Normalized ──
    raw  = r["raw_values"]
    norm = r["normalized"]
    print(f"\n── Indicators: raw  →  normalized {'─'*35}")
    print(f"  {'WB code':<28} {'Description':<28} {'Raw':>10}  Norm")
    print(f"  {'─'*28} {'─'*28} {'─'*10}  {'─'*5}")
    for code in _IND:
        if _IND[code] is None:
            continue
        raw_v  = raw.get(code)
        raw_s  = f"{raw_v:.2f}" if raw_v is not None else "NULL"
        norm_s = f"{norm[code]:.3f}" if code in norm else " N/A"
        label  = _LABELS.get(code, "")
        print(f"  {code:<28} {label:<28} {raw_s:>10}  {norm_s}")

    # ── Axis scores ──
    ax = r["axis_scores"]
    print(f"\n── Axis scores  (15 mapped  |  2 structural missing) {'─'*17}")
    print(f"  {'Axis':<42} {'Score':>5}  Contributes to")
    print(f"  {'─'*42} {'─'*5}  {'─'*16}")
    for axis in AXIS_INDICATORS:
        score  = ax[axis]
        score_s = f"{score:.3f}" if score is not None else " NULL"
        dim    = _AXIS_DIM.get(axis, "")
        print(f"  {axis:<42} {score_s:>5}  {dim}")

    print(f"\n  ⚠  Structural missing (no adequate WB country indicator):")
    for m in r["structural_missing"]:
        print(f"       {m}")

    if r["data_missing"]:
        print(f"\n  ?  Data gaps (WB returned null across all recent years):")
        for m in r["data_missing"]:
            print(f"       {m}")

    # ── Dimensions + zone ──
    active_count = len(AXIS_INDICATORS) - len(r["data_missing"])
    print(f"\n── Profile dimensions {'─'*48}")
    print(f"  deprivation   {p.deprivation:>6.3f}   (0 = no deprivation,  1 = severe)")
    print(f"  strain        {p.strain:>6.3f}   (0 = stable,          1 = high pressure)")
    print(f"  flourishing   {p.flourishing:>6.3f}   (0 = no room,         1 = full)")
    print(f"\n  ZONE : {r['zone_label']}")
    print(f"\n  Coverage: {active_count} of 15 mapped axes active")
    print(f"            15 of 17 total BUNDLE axes (2 structural gaps above)")
    conf = r.get("data_quality", {}).get("confidence", "?")
    if conf == "LOW":
        print(f"\n  [!] Zone may be INFLATED — official data only, key gaps present")
    print(f"{'='*W}\n")


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    iso2 = sys.argv[1].upper() if len(sys.argv) > 1 else "BG"
    result = country_wellbeing(iso2)
    _print_result(result)
