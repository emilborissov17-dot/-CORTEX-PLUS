#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/data_scout.py
Autonomous data discovery loop.

За всяка ос с липсващи или слаби данни:
  1. LLM предлага 3 безплатни, публично достъпни URL-а
  2. Системата тества всеки URL (HTTP GET, timeout=12s)
  3. Валидира дали отговорът е реален JSON/CSV с числа
  4. Записва работещите в memory/discovered_data_sources.json
  5. Следващия цикъл — новите източници се включват в global_indicators

Ограничения (съзнателни):
  - Само auth-free sources (без API ключове)
  - Max 4 оси на цикъл (LLM rate limit)
  - Валидацията е HTTP-only, не семантична — LLM може да халюцинира URL
  - Семантична валидация (дали данните са ПРАВИЛНИ) е следващата стъпка
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BASE          = Path(__file__).resolve().parents[1]
DISCOVERED    = BASE / "memory" / "discovered_data_sources.json"
SNAPSHOT_ROOT = BASE / "snapshots"
AXES_SPEC     = BASE / "agi_axes_spec.txt"

# Оси без смисъл за external data discovery (системни/мета)
_SKIP_AXES = {
    "BODY_SCAN", "GENERAL_SELF_REVIEW", "GOAL_PROGRESS_REVIEW",
    "GOAL_SCORE", "master_snapshot_latest", "GENERAL_SELF_REVIEW",
}

# LLM предложения се кешират 7 дни — не питаме LLM всеки цикъл
_SUGGESTION_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_discovered() -> dict:
    if DISCOVERED.exists():
        try:
            return json.loads(DISCOVERED.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_discovered(data: dict) -> None:
    DISCOVERED.parent.mkdir(parents=True, exist_ok=True)
    data["_updated"] = datetime.now(timezone.utc).isoformat()
    DISCOVERED.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def _find_gaps(max_gaps: int = 4) -> list[dict]:
    """
    Оси без реални данни = source_type != REAL_DATA или metrics == {}.
    Чете всички *_snapshot_latest.json и сортира по качество.
    """
    discovered = _load_discovered()
    gaps = []
    for snap in sorted(SNAPSHOT_ROOT.rglob("*_snapshot_latest.json")):
        try:
            d = json.loads(snap.read_text(encoding="utf-8"))
        except Exception:
            continue
        axis = d.get("axis", "")
        if not axis or axis in _SKIP_AXES:
            continue
        st      = d.get("source_type", "LLM")
        metrics = d.get("metrics", {})
        real_vals = sum(1 for v in metrics.values() if v is not None) if metrics else 0

        if "LLM" in st.upper() or real_vals == 0:
            # Check if we already have recent suggestions (use cache, skip LLM)
            existing = discovered.get(axis, {})
            last_asked = existing.get("last_asked_llm")
            if last_asked:
                try:
                    from datetime import timedelta
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(last_asked)
                    if age.days < _SUGGESTION_TTL_DAYS:
                        continue  # Cache still fresh — skip this axis
                except Exception:
                    pass

            gaps.append({
                "axis":        axis,
                "source_type": st,
                "real_metrics": real_vals,
                "snapshot":    str(snap),
            })

    # Prioritise: fewest real metrics first
    gaps.sort(key=lambda g: g["real_metrics"])
    return gaps[:max_gaps]


# ---------------------------------------------------------------------------
# LLM-driven source suggestion
# ---------------------------------------------------------------------------

def _suggest_sources(axis: str, already_known: list[str]) -> list[dict]:
    """
    Ask the LLM to suggest 3 free, auth-free URLs for this axis.
    Returns list of {url, description, format, why}.
    """
    spec_excerpt = ""
    if AXES_SPEC.exists():
        text = AXES_SPEC.read_text(encoding="utf-8")
        idx  = text.find(f"AXIS_NAME: {axis}")
        if idx != -1:
            spec_excerpt = text[idx: idx + 600]

    known_str = "\n".join(f"  - {u}" for u in already_known) or "  (none yet)"

    prompt = (
        f"You are a data scientist helping the CORTEX++ civilization-monitoring AI.\n\n"
        f"AXIS: {axis}\n"
        f"AXIS DESCRIPTION:\n{spec_excerpt}\n\n"
        f"ALREADY KNOWN SOURCES (do NOT repeat these):\n{known_str}\n\n"
        "Suggest exactly 3 FREE, publicly accessible data endpoints that:\n"
        "  - require NO API key or registration\n"
        "  - return JSON or CSV directly (not HTML pages)\n"
        "  - contain NUMERICAL measurements relevant to this axis\n"
        "  - are from authoritative organisations (UN, World Bank, NASA, NOAA, "
        "WHO, GBIF, IUCN, IEA, FAO, SIPRI, EMBER, UCDP, etc.)\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{"sources": [\n'
        '  {"url": "<exact URL>", "format": "json|csv", '
        '"metric": "<what it measures>", "org": "<who publishes it>"}\n'
        "]}"
    )

    try:
        from core.groq_backend import call_groq
        raw = call_groq(prompt, max_tokens=600)
        # Strip markdown fences
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]
        if "</think>" in raw:
            raw = raw.split("</think>")[-1]
        return json.loads(raw.strip()).get("sources", [])
    except Exception as e:
        print(f"  [SCOUT] LLM suggestion failed for {axis}: {e}")
        return []


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def _validate(url: str, fmt: str) -> tuple[bool, str]:
    """
    Tests a URL: returns (is_valid, reason).
    is_valid = True if: 200, response > 200 chars, has numbers for JSON/CSV.
    """
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "CORTEX-DataScout/1.0"})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"

        body = r.text
        if len(body) < 100:
            return False, "response too short"

        if fmt == "json":
            try:
                data = r.json()
                # Must contain at least one numeric value somewhere
                text = json.dumps(data)
                has_numbers = any(c.isdigit() for c in text)
                return has_numbers, "ok" if has_numbers else "no numeric data"
            except Exception:
                return False, "not valid JSON"

        if fmt == "csv":
            lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
            if len(lines) < 3:
                return False, "too few CSV rows"
            has_numbers = any(
                any(c.isdigit() for c in line)
                for line in lines[:10]
            )
            return has_numbers, "ok" if has_numbers else "no numeric data in CSV"

        return True, "unknown format — accepted"
    except requests.exceptions.Timeout:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:80]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(max_axes: int = 4) -> dict:
    """
    Full discovery cycle.
    Returns summary dict with axes scanned, sources found, sources validated.
    """
    print("[SCOUT] Starting autonomous data discovery...")
    discovered = _load_discovered()
    gaps       = _find_gaps(max_gaps=max_axes)
    summary    = {"scanned": 0, "suggested": 0, "validated": 0, "axes": {}}

    if not gaps:
        print("[SCOUT] No data gaps found — all axes have real data.")
        return summary

    print(f"[SCOUT] {len(gaps)} axes need real data: {[g['axis'] for g in gaps]}")

    for gap in gaps:
        axis = gap["axis"]
        summary["scanned"] += 1
        summary["axes"][axis] = {"suggested": [], "validated": []}

        # Already validated URLs for this axis
        existing = [s["url"] for s in discovered.get(axis, {}).get("sources", [])]

        suggestions = _suggest_sources(axis, existing)
        summary["suggested"] += len(suggestions)
        # Mark that we asked the LLM for this axis today
        if axis not in discovered:
            discovered[axis] = {"sources": []}
        discovered[axis]["last_asked_llm"] = datetime.now(timezone.utc).isoformat()
        # groq_backend sleeps _SLEEP_SECS internally before each call

        for s in suggestions:
            url = s.get("url", "").strip()
            fmt = s.get("format", "json").lower()
            if not url or not url.startswith("http"):
                continue

            summary["axes"][axis]["suggested"].append(url)
            print(f"  [SCOUT] Testing {axis}: {url[:70]}")
            ok, reason = _validate(url, fmt)

            if ok:
                print(f"  [SCOUT] VALID   {url[:70]} ({s.get('metric','')})")
                summary["validated"] += 1
                summary["axes"][axis]["validated"].append(url)

                if axis not in discovered:
                    discovered[axis] = {"sources": []}
                # Avoid duplicates
                existing_urls = {src["url"] for src in discovered[axis]["sources"]}
                if url not in existing_urls:
                    discovered[axis]["sources"].append({
                        "url":          url,
                        "format":       fmt,
                        "metric":       s.get("metric", ""),
                        "org":          s.get("org", ""),
                        "discovered_at": datetime.now(timezone.utc).isoformat(),
                        "status":       "active",
                    })
            else:
                print(f"  [SCOUT] INVALID {url[:70]} — {reason}")

    _save_discovered(discovered)

    total_known = sum(
        len(v.get("sources", [])) for v in discovered.values() if isinstance(v, dict)
    )
    print(
        f"[SCOUT] Done — {summary['validated']} new sources validated | "
        f"{total_known} total in memory"
    )
    return summary


# ---------------------------------------------------------------------------
# Read validated sources for use in other modules
# ---------------------------------------------------------------------------

def get_sources_for_axis(axis: str) -> list[dict]:
    """Return validated sources for a given axis."""
    d = _load_discovered()
    return [
        s for s in d.get(axis, {}).get("sources", [])
        if s.get("status") == "active"
    ]


def get_all_sources() -> dict:
    """Return all discovered sources grouped by axis."""
    return _load_discovered()
