"""
search_logic.py
Generates YouTube search phrases for a CORTEX++ axis.
Pulls terms from: target_config.json rationale + self_profile.json + past low-relevance history.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BASE          = Path(__file__).resolve().parent
TARGET_CONFIG = BASE / "config" / "target_config.json"
SELF_PROFILE  = BASE / "cortex_memory" / "abstractions" / "self_profile.json"
MEDIA_SEEN    = BASE / "cortex_memory" / "media_seen.json"

_STOP_WORDS = {
    "that", "this", "with", "from", "have", "been", "more", "than",
    "below", "safe", "above", "current", "requires", "higher", "lower",
    "near", "zero", "target", "global", "single", "applicable", "level",
    "scale", "percent", "rate", "data", "value", "metric", "score",
    "better", "higher", "lower", "limit", "index", "threshold", "measure",
}


def _load_json(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _find_axis_config(axis_name: str, config: dict) -> dict:
    for domain_block in config.values():
        if isinstance(domain_block, dict) and axis_name in domain_block:
            return domain_block[axis_name]
    return {}


def _extract_key_terms(text: str) -> list[str]:
    """Pull meaningful nouns/adjectives from rationale, drop citations and numbers."""
    text = re.sub(r"\([^)]+\)", "", text)        # drop (citation ...)
    text = re.sub(r"\d+\.?\d*", "", text)         # drop numbers
    words = re.findall(r"\b[A-Za-z][a-z]{3,}\b", text)
    terms = [w.lower() for w in words if w.lower() not in _STOP_WORDS]
    return list(dict.fromkeys(terms))[:10]         # deduplicated, order-preserved


def _get_low_relevance_terms(axis_name: str, media_seen: dict) -> set[str]:
    """Collect individual words from keyword phrases that repeatedly returned low relevance."""
    bad: set[str] = set()
    for record in media_seen.values():
        if record.get("axis") == axis_name and record.get("relevance_score", 1.0) < 0.35:
            for phrase in record.get("keywords_used", []):
                bad.update(phrase.lower().split())
    return bad


def generate_search_keywords(axis_name: str) -> list[str]:
    """
    Returns 2-3 YouTube search phrase strings for the given CORTEX++ axis.

    Strategy:
      1. Extract meaningful terms from the axis rationale.
      2. Supplement with weak_domains / known_gaps from self_profile.
      3. Remove any terms associated with past low-relevance searches.
      4. Build diverse 2-3 phrases (broad / specific / domain-gap variant).
    """
    config     = _load_json(TARGET_CONFIG)
    profile    = _load_json(SELF_PROFILE)
    media_seen = _load_json(MEDIA_SEEN)

    axis_cfg  = _find_axis_config(axis_name, config)
    rationale = axis_cfg.get("rationale", "")
    terms     = _extract_key_terms(rationale)

    bad_terms = _get_low_relevance_terms(axis_name, media_seen)
    terms     = [t for t in terms if t not in bad_terms]

    weak_domains = [w.lower().replace("_", " ") for w in profile.get("weak_domains", [])]
    known_gaps   = [g.lower().replace("_", " ") for g in profile.get("known_gaps", [])]

    # Human-readable base label from axis name
    base_label = axis_name.replace("_REVIEW", "").replace("_", " ").lower()

    phrases: list[str] = []

    # Phrase 1 — broad: top 2 rationale terms + axis label
    if len(terms) >= 2:
        phrases.append(f"{terms[0]} {terms[1]} {base_label} 2024")
    elif terms:
        phrases.append(f"{terms[0]} {base_label} 2024")
    else:
        phrases.append(f"{base_label} science 2024")

    # Phrase 2 — specific: next rationale terms + "science update"
    if len(terms) >= 4:
        phrases.append(f"{terms[2]} {terms[3]} science update")
    elif len(terms) >= 3:
        phrases.append(f"{terms[2]} {base_label} explained")

    # Phrase 3 — domain gap or fallback
    if weak_domains:
        phrases.append(f"{base_label} {weak_domains[0]} research")
    elif known_gaps:
        phrases.append(f"{known_gaps[0]} {base_label} explained")
    elif len(terms) >= 3:
        phrases.append(f"{base_label} {terms[2]} latest")
    else:
        phrases.append(f"{base_label} research overview")

    # Deduplicate and cap at 3
    seen: set[str] = set()
    unique: list[str] = []
    for p in phrases:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    print(f"[SEARCH] Axis '{axis_name}' -> phrases: {unique}")
    return unique[:3]
