"""
CORTEX++ | Side-experiment polyanka: cross_check (deductive contradiction oracle)
================================================================================
ISOLATED, NON-INVASIVE, FAIL-OPEN. Imports nothing from the repo, touches no
running state. Pure stdlib -> runs anywhere (incl. Linux CI), no dependency.

WHY (decision 21 Jul 2026)
--------------------------
Proposed stack put MeTTa/PeTTa+SWI-Prolog as a LAYER the balloon speaks through.
Audit of the REAL rules said otherwise:
  - target_config.json is FLAT per-axis thresholds -> plain Python.
  - the wanted cross-check ("LLM says LOW while data says +1.19C") is a per-axis
    two-source comparison -> plain Python.
  - the only genuinely relational spot is cortex_scoring_engine.CORRELATION_MATRIX
    (inter-axis). Prolog/PeTTa earns its dependency ONLY when that becomes
    conditional + multi-hop (contradictions spanning >=3 axes, with a proof
    trace). Until then: no new dependency.

WHAT THIS IS
------------
The cross-check / judge layer (roadmap NEXT #3) as a fail-open Python verifier:
for each numeric axis it derives the DATA-implied concern band from the hard
thresholds and compares it to the LLM's stated verdict. A large disagreement is
a PROVABLE contradiction -- no LLM in the loop, fully auditable. Verification
over assertion, in ~130 lines and zero dependencies.

Intended production use (later, held for review): call cross_check() as a step
after llm_self_review_axes; attach any contradictions to the cycle report. If
this module is absent or errors, the caller degrades to current behavior
(fail-open) -- never on the critical path.
"""
from __future__ import annotations

import json
import os
import sys

# concern scale: 0 = on-track/good, 3 = critical
_BANDS = ["LOW", "MODERATE", "HIGH", "CRITICAL"]

# map an LLM qualitative verdict -> concern level (RISK axes: "LOW risk" = good)
_LLM_MAP = {
    "LOW": 0, "GOOD": 0, "ON_TRACK": 0, "OK": 0, "SAFE": 0,
    "MODERATE": 1, "MEDIUM": 1, "WATCH": 1,
    "HIGH": 2, "BAD": 2, "ELEVATED": 2,
    "CRITICAL": 3, "SEVERE": 3, "ALARM": 3,
}

CONTRADICTION_GAP = 2  # flag only when data vs LLM differ by >= 2 bands


def _progress(value, target, direction, reference_worst):
    """Return fraction in [0,1]: 1 = at/better than target, 0 = at worst.
    reference_worst is used when present; else a v0 heuristic fallback."""
    if direction == "lower_better":
        worst = reference_worst if reference_worst is not None else target * 1.5
        if worst == target:
            return 1.0
        return max(0.0, min(1.0, (worst - value) / (worst - target)))
    if direction == "higher_better":
        worst = reference_worst if reference_worst is not None else 0.0
        if target == worst:
            return 1.0
        return max(0.0, min(1.0, (value - worst) / (target - worst)))
    return None  # stable_better / qualitative -> no numeric band


def _band(p):
    if p >= 0.80:
        return 0
    if p >= 0.60:
        return 1
    if p >= 0.30:
        return 2
    return 3


def data_concern(axis_cfg, value):
    """Deductive concern band from the hard thresholds. None if not numeric."""
    if value is None:
        return None
    tv = axis_cfg.get("target_value")
    if tv is None:
        return None
    p = _progress(float(value), float(tv), axis_cfg.get("direction"),
                  axis_cfg.get("reference_worst"))
    if p is None:
        return None
    return _band(p)


def _flatten(config):
    """target_config.json is nested by domain -> axis -> cfg. Flatten to axis->cfg."""
    out = {}
    for domain, axes in config.items():
        if domain.startswith("_") or not isinstance(axes, dict):
            continue
        for axis, cfg in axes.items():
            if isinstance(cfg, dict):
                out[axis] = cfg
    return out


def cross_check(observations, config):
    """observations: list of {axis, value, llm_verdict}. FAIL-OPEN: never raises.
    Returns list of contradiction findings (auditable, with the actual numbers)."""
    findings = []
    axes = _flatten(config)
    for obs in observations:
        try:
            axis = obs.get("axis")
            cfg = axes.get(axis)
            if not cfg:
                continue
            dc = data_concern(cfg, obs.get("value"))
            if dc is None:
                continue
            lv = _LLM_MAP.get(str(obs.get("llm_verdict", "")).strip().upper())
            if lv is None:
                continue
            if abs(dc - lv) >= CONTRADICTION_GAP:
                findings.append({
                    "axis": axis,
                    "metric": cfg.get("primary_metric"),
                    "value": obs.get("value"),
                    "target": cfg.get("target_value"),
                    "direction": cfg.get("direction"),
                    "data_says": _BANDS[dc],
                    "llm_said": _BANDS[lv],
                    "proof": (f"{cfg.get('primary_metric')}={obs.get('value')} "
                              f"vs target {cfg.get('target_value')} "
                              f"({cfg.get('direction')}) => data concern {_BANDS[dc]}; "
                              f"LLM asserted {_BANDS[lv]} -> gap {abs(dc - lv)} bands"),
                })
        except Exception as e:  # fail-open: one bad obs never breaks the check
            findings.append({"axis": obs.get("axis"), "error": str(e)})
    return findings


# ---- self-test (pre-declared pass/fail) -------------------------------------
# EXPECT: case 1 (CO2 424 vs 350, LLM LOW)      -> CONTRADICTION
#         case 2 (FOOD 10% vs 2.5%, LLM LOW)    -> CONTRADICTION
#         case 3 (WATER 74% vs 100%, LLM LOW)   -> no flag (1-band gap)
#         case 4 (CO2 360 vs 350, LLM LOW)      -> no flag (control, agree)
_CASES = [
    {"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "value": 424.0, "llm_verdict": "LOW"},
    {"axis": "FOOD_REVIEW",                "value": 10.0,  "llm_verdict": "LOW"},
    {"axis": "WATER_REVIEW",               "value": 74.0,  "llm_verdict": "LOW"},
    {"axis": "CLIMATE_GLOBAL_RISK_REVIEW", "value": 360.0, "llm_verdict": "LOW"},
]


def _load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "config/target_config.json"
    if not os.path.exists(path):
        print(f"[cross_check] config not found at {path}", file=sys.stderr)
        sys.exit(2)
    cfg = _load_config(path)
    print(f"[cross_check] loaded {path} | axes flattened: {len(_flatten(cfg))}")
    findings = cross_check(_CASES, cfg)
    print(f"[cross_check] contradictions found: {len(findings)}")
    for f in findings:
        if "error" in f:
            print(f"  [ERR] {f['axis']}: {f['error']}")
        else:
            print(f"  [!] {f['axis']}: {f['proof']}")
    # pass/fail: expect exactly the two hard contradictions (CO2 424, FOOD 10)
    axes_flagged = sorted({f.get("axis") for f in findings if "proof" in f})
    ok = axes_flagged == ["CLIMATE_GLOBAL_RISK_REVIEW", "FOOD_REVIEW"]
    print(f"[cross_check] SELF-TEST {'PASS' if ok else 'REVIEW'} "
          f"(flagged axes: {axes_flagged})")
