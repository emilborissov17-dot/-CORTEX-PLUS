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


def _get_used_phrases(axis_name: str, media_seen: dict) -> set[str]:
    """
    Return the exact search phrases already used for this axis (any outcome).
    Used to avoid regenerating the exact same phrase on the next run.
    Phrase-level deduplication only — individual terms are never blacklisted,
    so a core rationale word (e.g. "ceiling") is not poisoned by one bad result.
    """
    used: set[str] = set()
    for record in media_seen.values():
        if record.get("axis") == axis_name:
            for phrase in record.get("keywords_used", []):
                used.add(phrase.lower().strip())
    return used


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
    # terms extraction is fully deterministic: same rationale → same list, always
    terms = _extract_key_terms(rationale)

    # phrase-level deduplication: avoid regenerating exact phrases already used
    used_phrases = _get_used_phrases(axis_name, media_seen)

    weak_domains = sorted(w.lower().replace("_", " ") for w in profile.get("weak_domains", []))
    known_gaps   = sorted(g.lower().replace("_", " ") for g in profile.get("known_gaps", []))

    # Human-readable base label — deterministic
    base_label = axis_name.replace("_REVIEW", "").replace("_", " ").lower()

    # Candidate phrases in fixed priority order
    candidates: list[str] = []

    # Phrase 1 — broad: top 2 rationale terms + axis label
    if len(terms) >= 2:
        candidates.append(f"{terms[0]} {terms[1]} {base_label} 2024")
    elif terms:
        candidates.append(f"{terms[0]} {base_label} 2024")
    else:
        candidates.append(f"{base_label} science 2024")

    # Phrase 2 — specific: terms[2]+[3] or terms[2] alone
    if len(terms) >= 4:
        candidates.append(f"{terms[2]} {terms[3]} science update")
    if len(terms) >= 3:
        candidates.append(f"{terms[2]} {base_label} explained")
        candidates.append(f"{base_label} {terms[2]} research")

    # Phrase 3 — domain gap
    if weak_domains:
        candidates.append(f"{base_label} {weak_domains[0]} research")
    if known_gaps:
        candidates.append(f"{known_gaps[0]} {base_label} explained")

    # Fallbacks
    candidates.append(f"{base_label} science lecture")
    candidates.append(f"{base_label} research overview")

    # Pick first 3 that haven't been used before
    unique: list[str] = []
    for p in candidates:
        if p not in used_phrases and p not in unique:
            unique.append(p)
        if len(unique) == 3:
            break

    print(f"[SEARCH] Axis '{axis_name}' -> phrases: {unique}")
    return unique
