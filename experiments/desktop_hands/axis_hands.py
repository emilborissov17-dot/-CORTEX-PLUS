#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/desktop_hands/axis_hands.py — the hands of Shiva.

Per-axis, READ-ONLY probes that let the organism reach out and FEEL the world
(level-1, autonomous, tamper-evident). Sensing hands move freely; hands that
CHANGE the world are classified up and REFUSED autonomous execution — they are
logged as GATED_INTENT and wait for the human, per config/openclaw_action_policy.json.
This is "earned bounded autonomy" made literal: the baby gets hands to touch and
search, not to seize.

Reuses the existing tamper-evident action_ledger (hash-chained) verbatim.

  python experiments/desktop_hands/axis_hands.py --classify        # show the policy gate
  python experiments/desktop_hands/axis_hands.py --probe AXIS      # one read-only per-axis probe
  python experiments/desktop_hands/axis_hands.py --probe           # probe every mapped axis
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import action_ledger as ledger  # noqa: E402  (same folder — tamper-evident chain)

POLICY_FILE     = REPO / "config" / "openclaw_action_policy.json"
# sources the ORGANISM found ITSELF (core/data_scout autonomous discovery).
# Read directly (no import) so the hands stay dependency-free.
DISCOVERED_FILE = REPO / "memory" / "discovered_data_sources.json"

# per-axis read-only probes — World Bank public API (no key), world aggregate, most-recent value.
# NOTE: mrnev=1 is REJECTED by the WB API (HTTP 400). Use mrv=5 (most-recent 5 values,
# newest first) and pick the newest non-null in _extract_wb.
_WB = "https://api.worldbank.org/v2/country/WLD/indicator/{code}?format=json&per_page=5&mrv=5"
AXIS_PROBES = {
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": ("public_api_get", _WB.format(code="AG.LND.FRST.ZS")),
    "ENERGY_REVIEW":                  ("public_api_get", _WB.format(code="EG.ELC.RNEW.ZS")),
    "WATER_REVIEW":                   ("public_api_get", _WB.format(code="SH.H2O.SMDW.ZS")),
    "COGNITION_LEARNING_REVIEW":      ("public_api_get", _WB.format(code="SE.ADT.1524.LT.ZS")),
    "EDUCATION_CULTURE_REVIEW":       ("public_api_get", _WB.format(code="SE.PRM.CMPT.ZS")),
    "PLANETARY_POTENTIAL_REVIEW":     ("public_api_get", _WB.format(code="ER.LND.PTLD.ZS")),
    "HUMAN_WELL_BEING_REVIEW":        ("public_api_get", _WB.format(code="SH.DYN.MORT")),
    "INEQUALITY_POVERTY_REVIEW":      ("public_api_get", _WB.format(code="SI.POV.DDAY")),
    "INFRASTRUCTURE_CITIES_REVIEW":   ("public_api_get", _WB.format(code="SP.URB.TOTL.IN.ZS")),
    "ECONOMY_WORK_REVIEW":            ("public_api_get", _WB.format(code="NY.GDP.MKTP.KD.ZG")),
    "FOOD_REVIEW":                    ("public_api_get", _WB.format(code="SN.ITK.DEFC.ZS")),
    # the priority axis the organism cares about most — refugees by country of origin (world)
    "SOCIAL_RELATIONS_REVIEW":        ("public_api_get", _WB.format(code="SM.POP.REFG.OR")),
}

# level-1 action types that are read-only senses (safe to run autonomously)
READONLY_L1 = {"web_search", "web_fetch_get", "public_api_get", "rss_fetch",
               "read_local_file", "list_directory", "pdf_fetch_public", "query_cortex_memory"}


def _policy() -> dict:
    try:
        return json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"default_unclassified": "level_3"}


def classify(action_type: str) -> str:
    """Map an action type to its autonomy level from the SAME policy the whole
    project uses. Unknown -> most restrictive (default_unclassified)."""
    p = _policy()
    if action_type in p.get("always_blocked", {}).get("action_types", []):
        return "always_blocked"
    for lvl in ("level_1", "level_2", "level_3"):
        if action_type in p.get(lvl, {}).get("action_types", []):
            return lvl
    return p.get("default_unclassified", "level_3")


def _http_get(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "CORTEX-axis-hand/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def _extract_wb(text: str) -> dict:
    d = json.loads(text)
    if isinstance(d, list) and len(d) >= 2 and d[1]:
        for row in d[1]:  # WB returns newest-first; take the newest NON-NULL value
            if row.get("value") is not None:
                return {"value": row.get("value"), "date": row.get("date"),
                        "indicator": (row.get("indicator") or {}).get("value")}
    return {"value": None, "date": None}


def feel(action_type: str, target: str, timeout: int = 20) -> dict:
    """ONE hand. A read-only level-1 sense executes autonomously and is logged as
    PROBE. Anything else is NOT executed — logged as GATED_INTENT for the human."""
    level = classify(action_type)
    if level == "level_1" and action_type in READONLY_L1:
        try:
            raw = _http_get(target, timeout) if target.startswith("http") else ""
            signal = _extract_wb(raw) if "worldbank" in target else {"raw_len": len(raw)}
            ev = ledger.append("PROBE", action_type=action_type, level=level, target=target,
                               executed=True, approved="auto_level_1", signal=signal)
            return {"ok": True, "level": level, "signal": signal, "hash": ev["hash"][:12]}
        except Exception as e:
            ledger.append("PROBE", action_type=action_type, level=level, target=target,
                          executed=False, approved="auto_level_1", error=f"{type(e).__name__}")
            return {"ok": False, "level": level, "error": f"{type(e).__name__}: {e}"}
    # a hand that would change the world (or an unknown one) — refuse to move it alone
    ledger.append("GATED_INTENT", action_type=action_type, level=level, target=target,
                  executed=False, approved=False, note="world-changing/unclassified -> human gate")
    return {"ok": False, "level": level, "gated": True,
            "note": "refused autonomous execution; routed to human (earned bounded autonomy)"}


def _discovered_targets(axis: str) -> list[tuple]:
    """Sources the organism DISCOVERED ITSELF (data_scout), read from memory.
    Returns [(action_type, url, metric)] for active sources only."""
    try:
        d = json.loads(DISCOVERED_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    entry = d.get(axis) if isinstance(d.get(axis), dict) else {}
    out = []
    for s in entry.get("sources", []):
        if s.get("status") == "active" and s.get("url", "").startswith("http"):
            out.append(("public_api_get", s["url"], s.get("metric", "")))
    return out


def probe_axis(axis: str, timeout: int = 20) -> dict:
    """Feel an axis using BOTH the hardcoded seed AND whatever the organism found
    itself via data_scout. The seed is a starting point, not a leash — the system
    extends its own senses."""
    targets = []
    if axis in AXIS_PROBES:
        kind, url = AXIS_PROBES[axis]
        targets.append((kind, url, "seed"))
    for kind, url, metric in _discovered_targets(axis):
        targets.append((kind, url, f"self-discovered:{metric}"[:60]))

    if not targets:
        return {"ok": False, "axis": axis, "note": "no probe (no seed, none discovered yet)"}

    probes = []
    for kind, url, label in targets:
        r = feel(kind, url, timeout)
        r["source"] = label
        probes.append(r)
    return {
        "ok": any(p.get("ok") for p in probes),
        "axis": axis,
        "n_seed": 1 if axis in AXIS_PROBES else 0,
        "n_self_discovered": len(_discovered_targets(axis)),
        "probes": probes,
    }


def probe_all(axes=None, timeout: int = 15) -> dict:
    return {ax: probe_axis(ax, timeout) for ax in (axes or list(AXIS_PROBES.keys()))}


if __name__ == "__main__":
    if "--classify" in sys.argv:
        for a in ("web_search", "public_api_get", "git_push", "http_post_external",
                  "modify_openclaw_action_policy", "make_up_something"):
            print(f"  {a:34} -> {classify(a)}")
    elif "--probe" in sys.argv:
        i = sys.argv.index("--probe")
        ax = sys.argv[i + 1] if len(sys.argv) > i + 1 and not sys.argv[i + 1].startswith("-") else None
        print(json.dumps(probe_axis(ax) if ax else probe_all(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(ledger.audit(), ensure_ascii=False, indent=2))
