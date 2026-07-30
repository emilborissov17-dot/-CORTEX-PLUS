#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/browser_scout/goal_impact.py — turn a read page into a GOAL-IMPACT vector.

One measure for numbers AND meaning (Emil, 30 Jul 2026). Every observation becomes a
signed, weighted component relative to CORTEX's vision/goal: does it HELP or HARM, by how
much, on which goal-dimension, and why. An axis becomes a VECTOR of such components, not a
scalar. sign*magnitude feeds the statistics; the rationale/dimension feed the brain.
(See claude/GOAL_IMPACT_VECTOR_DESIGN_30JUL.md.)

Discipline: observation+evidence must be VERBATIM from the page (anti-fabrication). The
sign/magnitude/rationale are an explicit ASSESSMENT against the goal frame — not a verdict;
contested dimensions carry a counter-reading. Grounded facts, assessed impact, kept apart.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from autonomous_scout import _local, _json_from, _digits  # sovereign local model + helpers

# The reference frame — the sign/weight are RELATIVE to this, not an arbitrary scale.
GOAL_FRAME = (
    "CORTEX goal — a sustainable, dignified civilization: peace, human dignity, ecological "
    "sustainability within planetary limits, freedom of mind/spirit/body, truth and "
    "transparency, shared abundance, and food/water/health/education/home/energy for every "
    "person, life extended beyond one planet. POSITIVE = moves toward this. NEGATIVE = "
    "design failures: war, poverty, engineered scarcity, domination, deception, ecological "
    "overshoot, loss of dignity."
)

_DIMENSIONS = ["peace", "dignity", "sustainability", "freedom", "health", "truth",
               "prosperity", "knowledge", "resilience"]

# The goal frame is the ONE always-loaded canon (core/canon.py) — every judgment measured
# against the same center, dynamically (incl. consolidated invariants). Falls back to the
# local GOAL_FRAME string only if canon can't be imported.
REPO = HERE.parents[1]
DIM_WEIGHTS_FILE = REPO / "config" / "goal_dimension_weights.json"  # human-owned, versioned
try:
    sys.path.insert(0, str(REPO))
    from core.canon import as_frame as _canon_frame
except Exception:
    _canon_frame = None


def _frame() -> str:
    if _canon_frame:
        try:
            f = _canon_frame()
            if f:
                return f
        except Exception:
            pass
    return GOAL_FRAME


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _dim_weights():
    w = _load(DIM_WEIGHTS_FILE, {})
    return {d: float(w.get(d, 1.0)) for d in _DIMENSIONS}  # default 1.0 until Emil sets them


def extract_goal_impact(text: str, axis: str, need: str, url: str) -> tuple:
    """Read page text -> one goal-impact observation. Returns (obs, why). obs is None when
    nothing groundable is found (never fabricated)."""
    if not text:
        return None, "empty page text"
    prompt = (
        f"{_frame()}\n\n"
        f"You are measuring the axis '{axis}' (need: {need}) by reading a web page.\n"
        f"Find the SINGLE most relevant observation for it (a number or a stated fact), and "
        f"assess its impact RELATIVE TO THE GOAL ABOVE.\n"
        f"Reply ONLY JSON:\n"
        f'{{"observation": "<what the page states>", '
        f'"evidence": "<the exact phrase copied verbatim from the page, AT MOST 200 characters>", '
        f'"value": <number or null>, "unit": "<unit or empty>", '
        f'"sign": "+"|"-"|"0", "magnitude": <0.0-1.0>, '
        f'"dimension": "<one of: {", ".join(_DIMENSIONS)}>", '
        f'"rationale": "<why this sign and weight, referring to the goal>", '
        f'"contested": true|false, '
        f'"counterview": "<the strongest opposing reading — required if contested, else empty>"}}\n'
        f"If the page has nothing relevant, set observation to \"\" and value null.\n\n"
        f"PAGE TEXT (truncated):\n{text[:6500]}")
    try:
        got = _json_from(_local(prompt, num_predict=900))
    except Exception as e:
        return None, f"model output unparseable — rejected ({type(e).__name__})"

    obs, ev = str(got.get("observation", "")).strip(), str(got.get("evidence", "")).strip()
    if not obs and got.get("value") is None:
        return None, "nothing relevant found"
    # GUARD 1 (grounding): the evidence must be a verbatim span of the page text; and if a
    # number is claimed, its digits must be in the evidence. Facts must be locatable.
    def _norm(s):
        return re.sub(r"\s+", " ", s).strip().lower()
    if not ev or _norm(ev)[:40] not in _norm(text):
        return None, "evidence not grounded verbatim in page — rejected"
    val = got.get("value")
    if val is not None:
        d = _digits(val)
        if not d or d not in _digits(ev):
            return None, "claimed number not present in the evidence — rejected"
    # GUARD 1c: any number stated in the free-text OBSERVATION must also be grounded in the
    # evidence span. Without this, the model can quote a contentless verbatim sentence (which
    # passes GUARD 1) while smuggling a FABRICATED count into the observation (e.g. "33
    # conflicts" on a page that says 48). value-only checking misses it because value is null.
    for _m in re.findall(r"[0-9][0-9,\.]*", obs):
        _dn = _digits(_m)
        if _dn and _dn not in _digits(ev):
            return None, f"observation states a number ({_m}) not present in the evidence — rejected"
    # GUARD 2 (assessment hygiene): a contested reading MUST carry a counter-view.
    sign = got.get("sign") if got.get("sign") in ("+", "-", "0") else "0"
    try:
        mag = max(0.0, min(1.0, float(got.get("magnitude", 0.0))))
    except Exception:
        mag = 0.0
    cv = str(got.get("counterview", "")).strip()
    if got.get("contested") and len(cv) < 15:
        return None, "contested impact without a counter-reading — rejected"

    return {
        "axis": axis, "url": url,
        "observation": obs, "evidence": ev[:200],
        "value": val, "unit": str(got.get("unit", "")).strip(),
        "sign": sign, "magnitude": round(mag, 3),
        "signed_scalar": round((1 if sign == "+" else -1 if sign == "-" else 0) * mag, 3),
        "dimension": got.get("dimension"),
        "rationale": str(got.get("rationale", "")).strip()[:300],
        "contested": bool(got.get("contested", False)),
        "counterview": cv[:300],
    }, "ok"


def compose_vector(observations: list) -> dict:
    """Aggregate goal-impact components into the axis vector the system consumes — WITHOUT
    hiding the disagreement (Emil's rule: the aggregate never discards the components, and
    where sources conflict, the conflict is itself signal). Cross-dimension overall uses the
    HUMAN dimension weights, not model-invented ones."""
    obs = [o for o in observations if o]
    weights = _dim_weights()
    by_dim = {}
    signs_by_dim = {}
    for o in obs:
        d = o.get("dimension") or "unspecified"
        by_dim[d] = round(by_dim.get(d, 0.0) + o.get("signed_scalar", 0.0), 3)
        signs_by_dim.setdefault(d, set()).add(o.get("sign", "0"))
    # DISAGREEMENT is signal: same dimension, both + and - present -> flag, don't average away
    disagreements = [{"dimension": d, "signs": sorted(s),
                      "sources": [o.get("url") for o in obs if o.get("dimension") == d]}
                     for d, s in signs_by_dim.items() if "+" in s and "-" in s]
    overall_weighted = round(sum(o.get("signed_scalar", 0.0) * weights.get(o.get("dimension"), 1.0)
                                 for o in obs), 3)
    return {"n": len(obs),
            "overall_signed_weighted": overall_weighted,
            "by_dimension": by_dim,
            "disagreements": disagreements,     # kept, never averaged away
            "dim_weights_used": weights,
            "components": obs}                   # full detail always preserved


def extract_calibrated(text: str, axis: str, need: str, url: str, votes: int = 2) -> tuple:
    """Calibrate the SIGN/WEIGHT (the model's value-judgment, the soft dangerous part).
    Run the impact read `votes` times; the FACT is already grounded, but the impact is only
    trusted if the sign is CONSISTENT across votes. Disagreeing votes -> the observation is
    kept but marked impact_unstable (sign 0, low confidence) rather than asserting a
    confident vector we didn't actually verify. Verification over assertion, for the weight."""
    reads = []
    for _ in range(max(1, votes)):
        o, why = extract_goal_impact(text, axis, need, url)
        if o:
            reads.append(o)
    if not reads:
        return None, "nothing groundable"
    signs = {o["sign"] for o in reads}
    base = reads[0]
    if len(signs) == 1:                          # consistent judgment -> trust it
        mags = sorted(o["magnitude"] for o in reads)
        base["magnitude"] = mags[len(mags) // 2]  # median
        base["signed_scalar"] = round((1 if base["sign"] == "+" else -1 if base["sign"] == "-" else 0)
                                       * base["magnitude"], 3)
        base["impact_confidence"] = "calibrated" if len(reads) > 1 else "single"
        return base, "ok"
    # signs disagree across votes -> do NOT assert an impact we can't verify
    base["sign"], base["signed_scalar"] = "0", 0.0
    base["impact_confidence"] = "unstable"
    base["impact_note"] = f"sign varied across {len(reads)} reads ({sorted(signs)}) — impact not trusted"
    return base, "ok:unstable_impact"
