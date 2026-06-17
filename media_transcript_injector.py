"""
media_transcript_injector.py
Reads cortex_memory/media_seen.json and returns recent high-relevance
media intelligence for a given axis, formatted for LLM prompt injection.

Two public functions:
  get_media_context_block(axis) -> str   — formatted block for prepending to prompts
  get_media_signals(axis)       -> list  — list of signal strings for snapshot signals[]
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE       = Path(__file__).resolve().parent
MEDIA_SEEN = BASE / "cortex_memory" / "media_seen.json"

_MAX_AGE_DAYS  = 7    # ignore insights older than this
_MIN_RELEVANCE = 0.60 # minimum post-score to include
_MAX_ITEMS     = 3    # cap injected items per axis (avoid prompt bloat)


def _recent_insights(axis: str) -> list[dict]:
    """Return records from media_seen that are recent, transcribed, and relevant."""
    if not MEDIA_SEEN.exists():
        return []
    try:
        seen = json.loads(MEDIA_SEEN.read_text(encoding="utf-8"))
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=_MAX_AGE_DAYS)
    results = []

    for record in seen.values():
        if record.get("axis") != axis:
            continue
        if record.get("stage") != "transcribed":
            continue
        if record.get("relevance_score", 0) < _MIN_RELEVANCE:
            continue
        try:
            ts = datetime.fromisoformat(record["timestamp"])
            if ts < cutoff:
                continue
        except Exception:
            continue
        if record.get("key_insights"):
            results.append(record)

    # Sort by relevance desc, take top N
    results.sort(key=lambda r: r.get("relevance_score", 0), reverse=True)
    return results[:_MAX_ITEMS]


def get_media_context_block(axis: str) -> str:
    """
    Returns a formatted string with recent media intelligence for axis,
    ready to prepend to an LLM snapshot prompt. Returns "" if nothing relevant.

    Example output:
        Recent media intelligence for CLIMATE_GLOBAL_RISK_REVIEW (last 7 days):
        - [1.0] Earth's Carbon Storage Is Far Smaller Than We Thought: Safe storage 10x smaller than estimated.
        - [0.9] Earth in Danger: Planetary Boundaries Crossed: Earth crossed 7/8 critical boundaries.
    """
    records = _recent_insights(axis)
    if not records:
        return ""

    lines = [f"Recent media intelligence for {axis} (last 7 days):"]
    for r in records:
        score    = r.get("relevance_score", 0)
        title    = r.get("title", "unknown")[:80]
        insights = r.get("key_insights", "")
        lines.append(f"- [{score:.1f}] {title}: {insights}")

    return "\n".join(lines)


def get_media_signals(axis: str) -> list[str]:
    """
    Returns list of short signal strings derived from media intelligence,
    suitable for appending to snapshot['signals']. Returns [] if nothing relevant.

    Example output:
        ["[Media] Earth's carbon storage is 10x smaller than estimated.",
         "[Media] 7/8 planetary boundaries now crossed."]
    """
    records = _recent_insights(axis)
    signals = []
    for r in records:
        insight = r.get("key_insights", "").strip()
        if insight:
            signals.append(f"[Media] {insight}")
    return signals
