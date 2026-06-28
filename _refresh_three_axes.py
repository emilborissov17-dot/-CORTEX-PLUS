#!/usr/bin/env python3
"""Refresh SOCIAL_RELATIONS, MATERIALS_WASTE, CULTURE_MEDIA snapshots + rescore."""
from __future__ import annotations
import json, sys, io
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
SNAP = BASE / "snapshots"


def _write_human(axis: str, folder_name: str, raw: dict) -> Path:
    p = SNAP / "human" / folder_name / f"{folder_name}_snapshot_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "source_type": "REAL_DATA",
        "raw": raw,
        "snapshot_timestamp": datetime.now(timezone.utc).isoformat(),
        "axis": axis,
    }
    p.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _write_planet(axis: str, folder_name: str, raw: dict) -> Path:
    p = SNAP / "planet" / folder_name / f"{folder_name}_snapshot_latest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "axis": axis,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "MEDIUM",
        "signals": [],
        "key_metrics": [],
        "model": "WORLD_BANK_API+OWID+OECD",
        "source_type": "REAL_DATA",
        "metrics": raw.get("metrics", {}),
        "data_quality": raw.get("data_quality", ""),
        "fetched_date": raw.get("fetched_date", ""),
    }
    p.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ── 1. SOCIAL_RELATIONS — UNHCR + UCDP + WB ──────────────────────────────────
print("\n[1/3] Fetching SOCIAL_RELATIONS (UNHCR + UCDP + WB)...")
from data_providers.human.social_relations_provider import SocialRelationsProvider
try:
    sr_raw = SocialRelationsProvider().fetch()
    p = _write_human("SOCIAL_RELATIONS_REVIEW", "social_relations", sr_raw)
    m = sr_raw.get("metrics", {})
    print(f"  data_quality : {sr_raw.get('data_quality')}")
    print(f"  refugees_M   : {m.get('refugees_millions')}")
    print(f"  idps_M       : {m.get('idps_millions')}")
    print(f"  conflicts    : {m.get('active_armed_conflicts')}")
    print(f"  homicide/100k: {m.get('homicide_rate_per_100k')}")
    print(f"  -> wrote {p}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 2. MATERIALS_WASTE — fixed WB indicators ──────────────────────────────────
print("\n[2/3] Fetching MATERIALS_WASTE (fixed WB codes + OECD + OWID)...")
from data_providers.planet.materials_waste_review_provider import MaterialsWasteReviewProvider
try:
    mw_raw = MaterialsWasteReviewProvider().fetch()
    p = _write_planet("MATERIALS_WASTE_REVIEW", "materials_waste", mw_raw)
    m = mw_raw.get("metrics", {})
    print(f"  data_quality          : {mw_raw.get('data_quality')}")
    print(f"  resource_depletion_%  : {m.get('resource_depletion_pct_gni')}")
    print(f"  resource_rents_%      : {m.get('natural_resource_rents_pct_gdp')}")
    print(f"  forest_area_%         : {m.get('forest_area_pct')}")
    print(f"  protected_areas_%     : {m.get('protected_areas_pct')}")
    print(f"  recycling_%           : {m.get('recycling_rate_pct')}")
    print(f"  co2_total_kt          : {m.get('co2_emissions_total_kt')}")
    print(f"  -> wrote {p}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 3. CULTURE_MEDIA — add education spending ─────────────────────────────────
print("\n[3/3] Fetching CULTURE_MEDIA (+ education spending proxy)...")
from data_providers.human.culture_media_provider import CultureMediaProvider
try:
    cm_raw = CultureMediaProvider().fetch()
    p = _write_human("CULTURE_MEDIA_REVIEW", "culture_media", cm_raw)
    m = cm_raw.get("metrics", {})
    print(f"  data_quality         : {cm_raw.get('data_quality')}")
    print(f"  internet_users_%     : {m.get('internet_users_pct')}")
    print(f"  education_spend_% GDP: {m.get('education_spend_pct_gdp')}")
    print(f"  -> wrote {p}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 4. RESCORE ALL + show changes ────────────────────────────────────────────
print("\n[4/4] Rescoring all axes...")
from cortex_scoring_engine import score_all_snapshots, print_report, save_scores

scores = score_all_snapshots()

# Show just the three changed axes
print("\n── Changed axes ──")
for axis in ["SOCIAL_RELATIONS_REVIEW", "MATERIALS_WASTE_REVIEW", "CULTURE_MEDIA_REVIEW"]:
    r = scores.get(axis)
    if r:
        print(f"\n  {axis}")
        print(f"  score={r.score:.2f}  [{r.level}]")
        for sig in r.signals:
            print(f"    {sig}")
    else:
        print(f"\n  {axis} — NOT SCORED")

print("\n── Full report ──")
print_report(scores)
save_scores(scores)

# ── 5. Wellbeing profile with SOCIAL_RELATIONS now included ──────────────────
print("\n── Wellbeing Profile (global, SOCIAL_RELATIONS now in strain) ──")
from wellbeing_profile import load_scores_from_file, compute_wellbeing_profile
scores_dict = {axis: r.score for axis, r in scores.items()}
profile = compute_wellbeing_profile(scores_dict)
print(f"  deprivation  : {profile.deprivation:.3f}  (0=good, 1=severe)")
print(f"  strain       : {profile.strain:.3f}  (0=stable, 1=high)")
print(f"  flourishing  : {profile.flourishing:.3f}  (0=none, 1=full)")
print(f"  zone         : {profile.zone}")
if profile.missing_axes:
    print(f"  missing axes : {profile.missing_axes}")
