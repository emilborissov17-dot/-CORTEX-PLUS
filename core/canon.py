#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canon.py — the ALWAYS-LOADED conceptual frame (permanent layer, one source of truth).

Emil's memory architecture (30 Jul 2026): "always-loaded canon + working context +
consolidation" — the practical, non-quantum form of a stable identity present WHILE
reacting. This module is the CANON: the goal, the vision, the goal-dimensions and their
HUMAN weights, plus consolidated INVARIANTS (stable lessons promoted from experience).
It was scattered — merkle_memory, goal_prophecy and goal_impact each loaded the goal/vision
or hard-coded a frame. Now every reasoning step reads ONE canon, so the center of gravity
can't drift (the recurring failure the norms guard against).

  canon = load_canon()          # the full permanent frame (dict)
  frame = as_frame()            # a compact text block to inject into any LLM prompt
  consolidate_invariant(text)   # promote a stable lesson into the always-loaded canon
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOAL_FILE      = REPO / "civilization_goal.txt"
VISION_FILE    = REPO / "civilization_vision.txt"
WEIGHTS_FILE   = REPO / "config" / "goal_dimension_weights.json"
INVARIANTS     = REPO / "memory" / "canon_invariants.json"   # consolidated stable lessons

# The goal-dimensions the impact vector is scored on (kept here so canon owns them).
DIMENSIONS = ["peace", "dignity", "sustainability", "freedom", "health", "truth",
              "prosperity", "knowledge", "resilience"]

# Fallback frame if the permanent files are missing — grounded in TRUE_GOAL_CANON so the
# system is NEVER without its center, even on a fresh/partial checkout.
_FALLBACK = (
    "GOAL: a sustainable, dignified civilization — peace, human dignity, ecological "
    "sustainability within planetary limits, freedom of mind/spirit/body, truth and "
    "transparency, shared abundance, and food/water/health/education/home/energy for every "
    "person; life extended beyond one planet. War, poverty, engineered scarcity, domination, "
    "deception, ecological overshoot and loss of dignity are DESIGN FAILURES, not normal "
    "states. CORTEX is a human-supervised, transparent organ IN SERVICE of this goal — not "
    "the goal itself; it reveals lies and unsustainable patterns and proposes alternatives "
    "that increase freedom and dignity without breaching ecological limits."
)


def _read(p) -> str:
    try:
        return Path(p).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def load_canon() -> dict:
    """The full permanent frame. Missing pieces fall back safely — the center is never lost."""
    weights = _load(WEIGHTS_FILE, {})
    inv = _load(INVARIANTS, {"invariants": []}).get("invariants", [])
    return {
        "goal": _read(GOAL_FILE),
        "vision": _read(VISION_FILE),
        "dimensions": DIMENSIONS,
        "dimension_weights": {d: float(weights.get(d, 1.0)) for d in DIMENSIONS},
        "invariants": inv,   # stable lessons consolidated from experience
    }


def as_frame(max_chars: int = 1400) -> str:
    """A compact text block for injecting the canon into ANY LLM prompt — the always-loaded
    reference every judgment is made against."""
    c = load_canon()
    goal = c["goal"] or c["vision"] or _FALLBACK
    parts = [goal[:max_chars]]
    if c["invariants"]:
        parts.append("Consolidated invariants (learned, stable): "
                     + "; ".join(i.get("lesson", str(i)) if isinstance(i, dict) else str(i)
                                 for i in c["invariants"][:8]))
    return "\n".join(parts).strip() or _FALLBACK


def consolidate_invariant(lesson: str, evidence: str = "", source: str = "consolidation") -> dict:
    """Promote a stable lesson into the always-loaded canon — the working->permanent step of
    consolidation. Append-only, timestamped; deduped by lesson text. This is how experience
    becomes part of the frame that future cycles are always reasoning against."""
    doc = _load(INVARIANTS, {"invariants": []})
    inv = doc.get("invariants", [])
    if any((i.get("lesson") if isinstance(i, dict) else i) == lesson for i in inv):
        return {"added": False, "reason": "already present"}
    inv.append({"lesson": lesson.strip(), "evidence": evidence.strip()[:300],
                "source": source, "ts": datetime.now(timezone.utc).isoformat()})
    try:
        INVARIANTS.parent.mkdir(parents=True, exist_ok=True)
        INVARIANTS.write_text(json.dumps({"invariants": inv}, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception:
        return {"added": False, "reason": "write failed"}
    return {"added": True, "n": len(inv)}


if __name__ == "__main__":
    import sys
    if "--frame" in sys.argv:
        print(as_frame())
    else:
        print(json.dumps(load_canon(), ensure_ascii=False, indent=2)[:2000])
