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

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOAL_FILE      = REPO / "civilization_goal.txt"
VISION_FILE    = REPO / "civilization_vision.txt"
WEIGHTS_FILE   = REPO / "config" / "goal_dimension_weights.json"
INVARIANTS     = REPO / "memory" / "canon_invariants.json"   # consolidated stable lessons
BOUNDARIES_FILE = REPO / "BOUNDARIES.md"                     # the second canonical document

# ── THE ANCHOR ───────────────────────────────────────────────────────────────
# BOUNDARIES.md is loaded against this hash, hard-coded here on purpose. The goal and
# the vision say what the system should WANT; BOUNDARIES says what it may never BECOME,
# and a boundary that can be edited by whatever it binds is not a boundary.
#
# The hash lives in CODE, not in a config file, for the same reason the protected-path
# denylist does: data is what a patch can most easily rewrite. Changing the document now
# requires changing core/canon.py too — and BOTH are in safety/protected_paths.py, so
# neither is reachable from the self-modifier lane. Amending canon is a human act with
# two hands on it, exactly as BOUNDARIES.md S "Amendment process" requires.
#
# Anchored 1 Aug 2026, 11277 bytes, 160 lines, LF.
BOUNDARIES_SHA256 = "63034604997d8dac6771ee6d9c0f77a93acc77439b715254b0625863c14465d5"

# The sentinel that must reach the frame when the document no longer matches. It is a
# LOUD line in the frame the models actually read — not a log entry, not an exception
# swallowed by a fail-open caller. A canon that quietly degrades to a fallback is how a
# system ends up reasoning against a boundary nobody checked.
MISMATCH_LINE = "BOUNDARIES HASH MISMATCH — canon integrity violated"

# The distilled boundary carried in every prompt: S I's Wall and S VI's invariant, one
# sentence each, quoted from the document. The frame has a small budget and BOUNDARIES.md
# is 11KB, so the full text cannot ride along — but the two load-bearing sentences and
# the hash of the authority behind them can, and that is what makes the reference
# checkable rather than decorative.
_WALL_SENTENCE = ("CORTEX senses and advises. It never ACTUATES - it never causes an effect "
                  "on the world outside a human decision taken per action.")
_INVARIANT_SENTENCE = ("The moment a system named CORTEX actuates autonomously, it is no longer "
                       "CORTEX; it is a different system that has taken this name, and this "
                       "document has been violated, not amended.")

# Ceiling for the whole assembled frame. Asserted by test/test_canon_boundaries.py so the
# boundary block can never be squeezed out by a growing goal or a pile of invariants.
FRAME_BUDGET = 2800

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


def boundaries() -> dict:
    """The boundary document, and whether it is still the one canon.py was sealed against.

    READ ONLY. Nothing in this module writes to BOUNDARIES.md, and nothing may: the
    document is human-owned, and a system that can edit its own boundary has none.
    A missing file is treated as a violation, not as an absence to be shrugged off —
    deleting the constitution must not be quieter than editing it."""
    try:
        raw = BOUNDARIES_FILE.read_bytes()
    except Exception as e:
        return {"present": False, "verified": False, "sha256": None,
                "expected": BOUNDARIES_SHA256, "text": "",
                "reason": f"BOUNDARIES.md could not be read ({type(e).__name__}) — "
                          f"the canonical boundary document is absent"}
    actual = hashlib.sha256(raw).hexdigest()
    ok = (actual == BOUNDARIES_SHA256)
    return {
        "present": True, "verified": ok, "sha256": actual,
        "expected": BOUNDARIES_SHA256, "path": str(BOUNDARIES_FILE),
        "text": raw.decode("utf-8", errors="replace"),
        "reason": None if ok else ("sha256 does not match the hash core/canon.py was "
                                   "sealed with — the document has been altered"),
    }


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
        "boundaries": boundaries(),   # what it may never BECOME (human-owned, hash-anchored)
    }


def boundary_block(b: dict = None) -> str:
    """The distilled boundary as it appears in every prompt.

    On a hash mismatch this does NOT fall back quietly to the sealed text as though
    nothing happened — the mismatch is stated first, in the frame itself, where the
    model reading the frame will see it. The two sentences still follow, marked
    unverified: the invariant does not stop applying because someone edited the file
    it is written in. If anything it applies harder."""
    b = b if b is not None else boundaries()
    lines = []
    if not b.get("verified"):
        found = (b.get("sha256") or "absent")[:12]
        lines.append(MISMATCH_LINE)
        lines.append(f"  expected {BOUNDARIES_SHA256[:12]}, found {found} — {b.get('reason')}")
        lines.append("  The two lines below are the SEALED text; the document on disk is NOT it.")
    lines.append("BOUNDARY (canon, human-owned; this system may read it, never amend it):")
    lines.append(_WALL_SENTENCE)
    lines.append(_INVARIANT_SENTENCE)
    lines.append(f"full authority: BOUNDARIES.md sha256={BOUNDARIES_SHA256[:12]}")
    return "\n".join(lines)


# ── THE GOAL, RENDERED IN ENGLISH FOR THE MODEL (23 Aug 2026) ────────────────
#
# civilization_goal.txt is EMIL'S file and stays Bulgarian. He reads it; the
# model does not read it directly. What the model reads is the frame this module
# builds, and the frame is the point of generation, so the translation lives
# here rather than in his file.
#
# WHY IT WAS WORTH DOING. as_frame() output is injected into EVERY brain prompt
# through _spirit(). Measured before this change: 1270 characters at 64.67%
# Cyrillic — the single largest non-English block the model was reading, larger
# than the law. A pin that says "answer in English" cannot win an argument
# against the goal statement itself being in another language.
#
# TRANSLATION, NOT PARAPHRASE. Five sub-goals in, five sub-goals out; two
# bullets each, in the same order, with the same verbs. "Насърчавай" is
# "encourage" and not "optimise for"; "Ограничавай" is "limit" and not
# "prevent"; "Предпочитай обратими стратегии" is "prefer reversible strategies"
# and not "avoid irreversible ones", because those are different instructions.
GOAL_EN = """# GLOBAL GOAL

Maximise the resilience and the long-term viability of intelligent life and of
its environments of existence in the Universe (biological and non-biological),
with priority for Earth at the present stage, at minimal risk of harm.

# SUB-GOALS

1. Sustainable resources
   - Minimise the risk of critical resources being exhausted
   - Encourage cyclical, regenerative flows

2. Healthy environments of existence
   - Maintain and improve the conditions for life
   - Limit pollution and irreversible damage

3. Sustainable civilisation
   - Reduce the risk of wars and collapses
   - Fair distribution of resources

4. Knowledge and understanding
   - Increase the understanding of complex systems
   - Structure knowledge for future agents

5. Safety
   - Avoid actions with high risk
   - Prefer reversible strategies"""

# The exact bytes GOAL_EN was translated from. A translation that silently
# outlives its source is the failure this repo keeps finding, so the frame
# CHECKS: if Emil edits civilization_goal.txt, the model is told, in the frame,
# that the English it is reading no longer matches the Bulgarian authority. It
# is not silently replaced by the Bulgarian, because that would undo the whole
# migration on the day he fixes a typo — it is served with the mismatch named.
GOAL_SOURCE_SHA256 = (
    "fa2b4512ecfd0354a47652b58b6ebed4d0f8e02a125905787aee0374e70e21a5")

GOAL_DRIFT_LINE = (
    "[WARNING: the English goal below was translated from a version of "
    "civilization_goal.txt that is no longer on disk (expected {expected}, "
    "found {found}). The GOAL may have been changed and this rendering may no "
    "longer match it. Say so if your judgement depends on the goal's exact "
    "wording.]")


def goal_source_sha256() -> str:
    """sha256 of civilization_goal.txt as it is on disk right now."""
    import hashlib
    try:
        return hashlib.sha256(GOAL_FILE.read_bytes()).hexdigest()
    except OSError:
        return "absent"


def goal_block() -> str:
    """The goal as the model reads it: English, with a drift warning if needed.

    Falls back to whatever load_canon() found — Bulgarian included — when there
    is no English rendering to serve. A missing goal is worse than a goal in the
    wrong language, and this module's whole job is that the centre is never lost.
    """
    if not GOAL_EN.strip():
        c = load_canon()
        return c["goal"] or c["vision"] or _FALLBACK
    found = goal_source_sha256()
    if found != GOAL_SOURCE_SHA256:
        return (GOAL_DRIFT_LINE.format(expected=GOAL_SOURCE_SHA256[:12],
                                       found=found[:12])
                + "\n" + GOAL_EN)
    return GOAL_EN


def as_frame(max_chars: int = 1400) -> str:
    """A compact text block for injecting the canon into ANY LLM prompt — the always-loaded
    reference every judgment is made against.

    Order is deliberate: goal, then boundary, then learned invariants. The boundary sits
    ABOVE the invariants because an invariant is a lesson the system promoted from its own
    experience, and no accumulated lesson may outrank the line it is not allowed to cross.

    THE GOAL IS SERVED IN ENGLISH (23 Aug 2026) — see GOAL_EN. The boundary block
    below was already English and is UNCHANGED: not one word of the wall sentence
    or the invariant sentence is touched by this, and BOUNDARIES.md is not read
    differently, not re-hashed and not edited."""
    c = load_canon()
    parts = [goal_block()[:max_chars], boundary_block(c.get("boundaries"))]
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
