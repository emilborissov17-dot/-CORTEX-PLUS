"""
Wellbeing Profile — Phase 1: global profile from 17-axis scorer output.

Reads output/cortex_scores_latest.json and computes three independent dimensions:
  deprivation  (0=none, 1=severe)
  strain       (0=stable, 1=high)
  flourishing  (0=none,  1=full)

Then maps the triple to a human-readable zone via Maslow-hierarchical thresholds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

SCORES_PATH = Path(__file__).parent / "output" / "cortex_scores_latest.json"

# ── Bundle definitions ────────────────────────────────────────────────────────
# (axis_key, dep_weight, strain_weight, flourishing_weight)
# Weights per axis must sum to 1.0.
# [CAL] marks splits that are calibratable once country-level data arrives.

BUNDLES: list[tuple[str, float, float, float]] = [
    # Deprivation — full weight
    ("FOOD_REVIEW",                      1.0,  0.0,  0.0),
    ("WATER_REVIEW",                     1.0,  0.0,  0.0),
    ("HUMAN_WELL_BEING_REVIEW",          1.0,  0.0,  0.0),
    ("GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL", 1.0,  0.0,  0.0),
    # Strain — full weight
    ("INEQUALITY_POVERTY_REVIEW",        0.0,  1.0,  0.0),
    ("GOVERNANCE_INSTITUTIONS_REVIEW",   0.0,  1.0,  0.0),
    ("CLIMATE_GLOBAL_RISK_REVIEW",       0.0,  1.0,  0.0),
    ("MATERIALS_WASTE_REVIEW",           0.0,  1.0,  0.0),
    # Flourishing — full weight
    ("COGNITION_LEARNING_REVIEW",        0.0,  0.0,  1.0),
    ("TECHNOLOGY_AI_REVIEW",             0.0,  0.0,  1.0),
    ("TECHNOLOGY_INFRA_REVIEW",          0.0,  0.0,  1.0),
    ("CULTURE_MEDIA_REVIEW",             0.0,  0.0,  1.0),
    # Boundary axes — split weights [CAL]
    ("INFRASTRUCTURE_CITIES_REVIEW",     0.5,  0.0,  0.5),  # [CAL] dep/flourishing
    ("ENERGY_REVIEW",                    0.5,  0.5,  0.0),  # [CAL] dep/strain
    ("EDUCATION_CULTURE_REVIEW",         0.5,  0.0,  0.5),  # [CAL] dep/flourishing
    ("ECONOMY_WORK_REVIEW",              0.33, 0.33, 0.34), # [CAL] all three
    ("ECOSYSTEMS_BIODIVERSITY_REVIEW",   0.33, 0.33, 0.34), # [CAL] all three
    ("SOCIAL_RELATIONS_REVIEW",          0.0,  1.0,  0.0),  # strain: forced displacement + conflicts
]

BUNDLE_AXES = {ax for ax, *_ in BUNDLES}

# ── Zone thresholds (all calibratable) ───────────────────────────────────────
T_DEP_CRISIS     = 0.65   # deprivation above this → In Crisis regardless of rest
T_DEP_PRECARIOUS = 0.40   # deprivation above this → Precarious
T_STR_PRECARIOUS = 0.55   # strain above this → Precarious (even if needs covered)
T_FLO_SECURE     = 0.58   # flourishing below this → Secure  [CAL: raised from 0.35 after V-Dem; empirical min for dep<=0.40 is ~0.53]
T_FLO_THRIVING   = 0.70   # flourishing below this → Thriving [CAL: raised from 0.60; 62% Dignified Life was over-inflated]


# ── Output type ──────────────────────────────────────────────────────────────
@dataclass
class WellbeingProfile:
    deprivation:  float          # 0=no deprivation, 1=severe
    strain:       float          # 0=stable, 1=maximum strain
    flourishing:  float          # 0=no room, 1=full flourishing
    zone:         str            # "In Crisis" | "Precarious" | "Secure" | "Thriving" | "Dignified Life"
    missing_axes: list[str] = field(default_factory=list)   # axes in BUNDLES not found in scores
    computed_at:  str = ""


# ── Core computation ──────────────────────────────────────────────────────────
def _weighted_mean(pairs: list[tuple[float, float]]) -> Optional[float]:
    """Weighted mean of (value, weight) pairs; returns None if total weight == 0."""
    total_w = sum(w for _, w in pairs)
    if total_w == 0:
        return None
    return sum(v * w for v, w in pairs) / total_w


def _zone(dep: float, str_: float, flo: float) -> str:
    if dep > T_DEP_CRISIS:
        return "In Crisis"
    if dep > T_DEP_PRECARIOUS:
        return "Precarious"
    if str_ > T_STR_PRECARIOUS:
        return "Precarious"
    if flo < T_FLO_SECURE:
        return "Secure"
    if flo < T_FLO_THRIVING:
        return "Thriving"
    return "Dignified Life"


def compute_wellbeing_profile(
    scores: Dict[str, float],
    computed_at: Optional[str] = None,
) -> WellbeingProfile:
    """
    Compute a WellbeingProfile from a dict of {axis_key: score_0_to_1}.

    score 1.0 = best possible state for that axis.
    Returns a WellbeingProfile with deprivation/strain/flourishing in [0, 1]
    and a zone label.
    """
    dep_pairs: list[tuple[float, float]] = []
    str_pairs: list[tuple[float, float]] = []
    flo_pairs: list[tuple[float, float]] = []
    missing: list[str] = []

    for axis, dw, sw, fw in BUNDLES:
        if axis not in scores:
            missing.append(axis)
            continue
        s = scores[axis]
        if dw: dep_pairs.append((1.0 - s, dw))
        if sw: str_pairs.append((1.0 - s, sw))
        if fw: flo_pairs.append((s, fw))

    dep  = _weighted_mean(dep_pairs)
    str_ = _weighted_mean(str_pairs)
    flo  = _weighted_mean(flo_pairs)

    if dep is None or str_ is None or flo is None:
        zone = "UNKNOWN"
    else:
        zone = _zone(dep, str_, flo)

    return WellbeingProfile(
        deprivation  = round(dep,  3) if dep  is not None else -1.0,
        strain       = round(str_, 3) if str_ is not None else -1.0,
        flourishing  = round(flo,  3) if flo  is not None else -1.0,
        zone         = zone,
        missing_axes = missing,
        computed_at  = computed_at or datetime.now(timezone.utc).isoformat(),
    )


def load_scores_from_file(path: Path = SCORES_PATH) -> Dict[str, float]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    scores_dict = raw.get("scores", raw)
    result: Dict[str, float] = {}
    for axis, val in scores_dict.items():
        if isinstance(val, dict):
            s = val.get("score")
            if s is not None:
                result[axis] = float(s)
        elif isinstance(val, (int, float)):
            result[axis] = float(val)
    return result


def profile_from_file(path: Path = SCORES_PATH) -> WellbeingProfile:
    """Load scores from file and return a computed WellbeingProfile."""
    scores = load_scores_from_file(path)
    return compute_wellbeing_profile(scores)


# ── CLI / quick check ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    p = profile_from_file()
    print(f"Wellbeing Profile  ({p.computed_at[:10]})")
    print(f"  deprivation  : {p.deprivation:.3f}  (0=good, 1=severe)")
    print(f"  strain       : {p.strain:.3f}  (0=stable, 1=high)")
    print(f"  flourishing  : {p.flourishing:.3f}  (0=none, 1=full)")
    print(f"  zone         : {p.zone}")
    if p.missing_axes:
        print(f"  missing axes : {p.missing_axes}")
