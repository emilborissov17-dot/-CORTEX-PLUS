#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/desktop_hands/harvest.py — close the data loop: probe→signals.

The organism probes every axis (hardcoded seed + what it discovered ITSELF) and
persists the numeric result to memory/probed_signals.json, so its OWN acquired
data can reach its judgment (goal_score_calculator reads this file).

SAFETY: only STRUCTURED, known-mapping probes are marked validated=True and are
allowed to feed the goal score. Self-discovered sources are carried as
validated=False (available + auditable, but NOT scored) until a semantic check
promotes them — we never let an unvalidated auto-found number move the goal.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import axis_hands as H  # noqa: E402

OUT = REPO / "memory" / "probed_signals.json"

# seed WB probe -> the obs key goal_score_calculator understands (validated by construction)
SEED_OBSKEY = {
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": "wb_AG.LND.FRST.ZS",
    "ENERGY_REVIEW":                  "wb_EG.ELC.RNEW.ZS",
    "WATER_REVIEW":                   "wb_SH.H2O.SMDW.ZS",
    "COGNITION_LEARNING_REVIEW":      "wb_SE.ADT.1524.LT.ZS",
    "EDUCATION_CULTURE_REVIEW":       "wb_SE.PRM.CMPT.ZS",
    "PLANETARY_POTENTIAL_REVIEW":     "wb_ER.LND.PTLD.ZS",
    "HUMAN_WELL_BEING_REVIEW":        "wb_SH.DYN.MORT",
    "INEQUALITY_POVERTY_REVIEW":      "wb_SI.POV.DDAY",
    "INFRASTRUCTURE_CITIES_REVIEW":   "wb_SP.URB.TOTL.IN.ZS",
    "ECONOMY_WORK_REVIEW":            "wb_NY.GDP.MKTP.KD.ZG",
    "FOOD_REVIEW":                    "wb_SN.ITK.DEFC.ZS",
    "SOCIAL_RELATIONS_REVIEW":        "unhcr_refugees",
}


def harvest(timeout: int = 15) -> dict:
    axes = sorted(set(H.AXIS_PROBES) | set(_discovered_axes()))
    validated_obs: dict = {}    # obs_key -> value  (feeds the goal score)
    audit: dict = {}            # axis -> full probe record (everything, for the human)
    for ax in axes:
        r = H.probe_axis(ax, timeout=timeout)
        audit[ax] = r
        # only the structured seed probe with a known obs mapping is trusted to score
        obs_key = SEED_OBSKEY.get(ax)
        if obs_key:
            for p in r.get("probes", []):
                if p.get("source") == "seed" and p.get("ok") and isinstance(p.get("signal"), dict):
                    val = p["signal"].get("value")
                    if isinstance(val, (int, float)):
                        validated_obs[obs_key] = val
    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "validated_obs": validated_obs,                 # goal_score_calculator consumes THIS
        "n_validated": len(validated_obs),
        "audit": audit,                                 # full picture incl. self-discovered (pending)
        "note": "validated_obs feed the goal score; self-discovered probes are in audit, pending semantic validation",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _discovered_axes() -> list:
    try:
        d = json.loads((REPO / "memory" / "discovered_data_sources.json").read_text(encoding="utf-8"))
        return [k for k, v in d.items() if not k.startswith("_") and isinstance(v, dict) and v.get("sources")]
    except Exception:
        return []


if __name__ == "__main__":
    res = harvest()
    print(json.dumps({"n_validated": res["n_validated"],
                      "validated_obs": res["validated_obs"],
                      "axes_probed": list(res["audit"].keys())}, ensure_ascii=False, indent=2))
