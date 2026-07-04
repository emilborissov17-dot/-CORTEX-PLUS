"""
historical_fetch.py — retrospective WB indicator fetch, ±2yr nearest-value fallback.

Design approved 2026-07-04 (see memory: project_learning_loop_design_prep).

Two distinct problems, two distinct mechanisms — do not conflate them:
  1. Transient WB network flakiness: handled by `_wb_session()` (Retry+backoff,
     reused from wellbeing_country.py). Probed 2026-07-04 RS/2014: a single bare
     request hit ReadTimeout on ~11/15 representative indicators, but routing
     the same calls through the retry-enabled session recovered all but 2-3 of
     them near-instantly. Most "gaps" in a naive single-shot fetch are transient,
     not real.
  2. Genuine data absence at an exact year (e.g. RS/2014 SE.ADT.LITR.ZS and
     HD.HCI.LAYS were empty even after retry): handled by the ±2yr fallback
     below — nearest available year within the window, tagged `filled_from`.

Check-year grid (approved): every 3 years, 2002-2026 (9 points) — see design doc
in conversation history 2026-07-04 (not written to a file per Emil's earlier
rejection of a standalone docs/LEARNING_LOOP_DESIGN.md).
"""

from __future__ import annotations

from typing import Optional
import requests

from wellbeing_country import WB_BASE, _wb_session

FALLBACK_WINDOW = 2  # years, either direction of check_year


def fetch_indicator_for_year(
    iso2: str,
    code: str,
    check_year: int,
    sess: Optional[requests.Session] = None,
) -> dict:
    """
    Fetch one WB indicator for one country at one check_year, with a single
    date-range API call covering [check_year-2, check_year+2] (cheaper than
    up to 5 separate requests, and WB is slow enough that this matters).

    Returns:
        {"value": float|None, "year": int|None, "filled_from": int|None}
        - year is the actual data point used; filled_from is set only when
          year != check_year (i.e. the value was borrowed from a nearby year).
        - All None means no data anywhere in the ±2yr window.
    """
    sess = sess or _wb_session()
    lo, hi = check_year - FALLBACK_WINDOW, check_year + FALLBACK_WINDOW
    try:
        r = sess.get(
            f"{WB_BASE}/country/{iso2}/indicator/{code}",
            params={"format": "json", "date": f"{lo}:{hi}"},
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return {"value": None, "year": None, "filled_from": None}

    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        return {"value": None, "year": None, "filled_from": None}

    by_year: dict[int, float] = {}
    for entry in payload[1]:
        if entry and entry.get("value") is not None:
            try:
                by_year[int(entry["date"])] = float(entry["value"])
            except (TypeError, ValueError):
                continue

    if not by_year:
        return {"value": None, "year": None, "filled_from": None}

    if check_year in by_year:
        return {"value": by_year[check_year], "year": check_year, "filled_from": None}

    nearest_year = min(by_year, key=lambda y: abs(y - check_year))
    return {
        "value": by_year[nearest_year],
        "year": nearest_year,
        "filled_from": nearest_year,
    }


# ── Timeseries JSON schema (per country, per axis/indicator) ──────────────────
# Populated by the not-yet-built retrospective_divergence.py, which combines
# quant (WB, via fetch_indicator_for_year) + qual (V-Dem, already retrospective)
# percentiles into a divergence value per check_year. Field shape reserved now
# per Emil's approval 2026-07-04 (element: DIVERGENCE VELOCITY).
#
# {
#   "iso2": str,
#   "check_years": [2002, 2005, 2008, ...],           # 3-year grid
#   "points": [
#     {"check_year": int, "divergence": float, "filled_from": int|None},
#     ...
#   ],
#   "divergence_velocity": [
#     {
#       "from_year": int, "to_year": int,
#       "delta_divergence": float,   # divergence(to_year) - divergence(from_year)
#       "delta_t": int,              # to_year - from_year, in years
#       "velocity": float,           # delta_divergence / delta_t
#     },
#     ...
#   ]
# }
#
# Hypothesis to test later (per Emil): velocity predicts better than level —
# i.e. a fast-rising divergence is a stronger facade signal than a high but
# stable one.

def compute_divergence_velocity(points: list[dict]) -> list[dict]:
    """
    points: [{"check_year": int, "divergence": float}, ...] sorted by check_year.
    Returns velocity records between each consecutive pair of check-years.
    """
    velocity = []
    for a, b in zip(points, points[1:]):
        delta_t = b["check_year"] - a["check_year"]
        if delta_t == 0:
            continue
        delta_div = b["divergence"] - a["divergence"]
        velocity.append({
            "from_year": a["check_year"],
            "to_year": b["check_year"],
            "delta_divergence": round(delta_div, 4),
            "delta_t": delta_t,
            "velocity": round(delta_div / delta_t, 4),
        })
    return velocity


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # Pilot: RS / check_year=2014, representative indicators incl. WGI.
    CODES = [
        "SN.ITK.DEFC.ZS", "AG.PRD.FOOD.XD", "SH.H2O.SMDW.ZS",
        "SP.DYN.LE00.IN", "SP.DYN.IMRT.IN", "SI.POV.GINI",
        "NY.GDP.PCAP.PP.KD", "SL.UEM.TOTL.ZS", "SE.ADT.LITR.ZS",
        "HD.HCI.LAYS", "VC.IHR.PSRC.P5", "EN.ATM.CO2E.PC",
        "GOV_WGI_CC.EST", "GOV_WGI_GE.EST", "GOV_WGI_RL.EST",
    ]
    sess = _wb_session()
    nulls = []
    for code in CODES:
        res = fetch_indicator_for_year("RS", code, 2014, sess=sess)
        tag = f"filled_from={res['filled_from']}" if res["filled_from"] else "exact"
        print(f"{code:20s} -> {res['value']}  ({tag})")
        if res["value"] is None:
            nulls.append(code)

    print(f"\n{len(CODES) - len(nulls)}/{len(CODES)} resolved within +/-{FALLBACK_WINDOW}yr window")
    if nulls:
        print("still NULL:", ", ".join(nulls))
