#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/data_scout.py
Autonomous data discovery loop.

За всяка ос с липсващи или слаби данни:
  1. LLM предлага 3 безплатни, публично достъпни URL-а
  2. Системата тества всеки URL (HTTP GET, timeout=12s)
  3. Валидира дали отговорът е реален JSON/CSV с числа
  4. Derives the PARSING RULE from that same payload (core/source_registration.py) —
     a candidate without one is NOT registered and never reaches Telegram
  5. Записва работещите в memory/discovered_data_sources.json
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

from core import source_registration as _sr   # the registration schema wall

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

def _suggest_sources(axis: str, already_known: list[str],
                     slot_requirement: str = "") -> list[dict]:
    """
    Ask the LLM to suggest 3 free, auth-free URLs for this axis.
    Returns list of {url, description, format, why}.
    slot_requirement: extra constraint when searching for a specific composer
    slot class (e.g. "must update at least daily").
    """
    spec_excerpt = ""
    if AXES_SPEC.exists():
        text = AXES_SPEC.read_text(encoding="utf-8")
        idx  = text.find(f"AXIS_NAME: {axis}")
        if idx != -1:
            spec_excerpt = text[idx: idx + 600]

    known_str = "\n".join(f"  - {u}" for u in already_known) or "  (none yet)"
    req_line = f"SPECIFIC REQUIREMENT: {slot_requirement}\n\n" if slot_requirement else ""

    prompt = (
        f"You are a data scientist helping the CORTEX++ civilization-monitoring AI.\n\n"
        f"AXIS: {axis}\n"
        f"AXIS DESCRIPTION:\n{spec_excerpt}\n\n"
        f"{req_line}"
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
        from core.llm_json import call_llm_json
        # call_llm_json прави самото извикване + parse, и при отрязан отговор
        # ретрайва веднъж с двоен token budget (600 е тесен за 3 URL-а).
        data = call_llm_json(
            prompt,
            max_tokens=600,
            expect=dict,
            label=f"SCOUT/{axis}",
        )
        srcs = data.get("sources", [])
        if srcs:
            return srcs
        raise RuntimeError("cloud LLM returned no sources")
    except Exception as e:
        # Cloud backends busy/rate-limited (снощи: всички 4 -> 0 нови източника).
        # SOVEREIGN FALLBACK: питаме локалния мозък (Ollama qwen), за да НЕ спира
        # набавянето на данни само защото наетите модели са заети.
        print(f"  [SCOUT] cloud LLM failed for {axis} ({type(e).__name__}) -> local brain")
        try:
            local = _suggest_via_local_brain(prompt)
            if local:
                print(f"  [SCOUT] local brain suggested {len(local)} source(s) for {axis}")
                return local
        except Exception as le:
            print(f"  [SCOUT] local brain also failed for {axis}: {type(le).__name__}")
        return []


# Sovereign source-suggestion — the organism's OWN local brain, zero external API.
_OLLAMA_URL  = "http://localhost:11434"
_LOCAL_MODEL = "qwen2.5:3b"


def _suggest_via_local_brain(prompt: str, timeout: int = 45) -> list[dict]:
    """Ask the LOCAL model (same channel as PULSE/goal_prophecy) for data sources.
    Sovereign — never touches a paid/cloud API. Lenient JSON extraction."""
    import urllib.request
    body = json.dumps({
        "model": _LOCAL_MODEL, "stream": False,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0.3, "num_predict": 400},
    }).encode("utf-8")
    req = urllib.request.Request(_OLLAMA_URL + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = ((json.loads(r.read().decode("utf-8")).get("message") or {}).get("content") or "")
    i, j = raw.find("{"), raw.rfind("}")
    if i < 0 or j <= i:
        return []
    data = json.loads(raw[i:j + 1])
    return data.get("sources", []) if isinstance(data, dict) else []


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def _validate(url: str, fmt: str) -> tuple[bool, str, object]:
    """
    Tests a URL: returns (is_valid, reason, payload).

    The PAYLOAD is returned, not discarded. This function already parses the response to
    prove it carries numbers; the parsing rule a composer source needs in order to be
    fetchable is derivable from that very structure. Throwing it away here is what
    produced candidates that could never be promoted — and then blacklisted the sources
    for it (see core/source_registration.py). One fetch, one parse, rule included.
    """
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "CORTEX-DataScout/1.0"})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", None

        body = r.text
        if len(body) < 100:
            return False, "response too short", None

        if fmt == "json":
            try:
                data = r.json()
                # Must contain at least one numeric value somewhere
                text = json.dumps(data)
                has_numbers = any(c.isdigit() for c in text)
                return has_numbers, ("ok" if has_numbers else "no numeric data"), data
            except Exception:
                return False, "not valid JSON", None

        if fmt == "csv":
            lines = [l for l in body.splitlines() if l.strip() and not l.startswith("#")]
            if len(lines) < 3:
                return False, "too few CSV rows", None
            has_numbers = any(
                any(c.isdigit() for c in line)
                for line in lines[:10]
            )
            return has_numbers, ("ok" if has_numbers else "no numeric data in CSV"), body

        return True, "unknown format — accepted", body
    except requests.exceptions.Timeout:
        return False, "timeout", None
    except Exception as e:
        return False, str(e)[:80], None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Composer NEEDs -> targeted discovery (the system searches for what IT declared missing)
# ---------------------------------------------------------------------------

COMPOSER_NEEDS = BASE / "memory" / "composer_needs.json"
_NEED_ASK_TTL_DAYS = 2   # a hungry slot is re-searched every 2 days, not every cycle

_SLOT_CLASS_DESC = {
    "anchor_annual":     "an authoritative OFFICIAL statistic for this axis (annual/quarterly cadence acceptable)",
    "measurement_daily": "a DIRECT measurement of the axis quantity that UPDATES AT LEAST DAILY or weekly",
    "event_daily":       "a DAILY-updating event/news-derived numeric signal (counts, tone, index) for this axis",
    "indirect_proxy":    "a related quantity that constrains or confirms the axis (any cadence)",
}


def _composer_gaps(max_gaps: int = 3) -> list[dict]:
    """Slots the composers declared unfilled or dead (memory/composer_needs.json)
    — the system's OWN declared hunger, turned into search targets."""
    try:
        needs = json.loads(COMPOSER_NEEDS.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for axis, entry in (needs or {}).items():
        for item in (entry or {}).get("items", []):
            # human_sense_request: Emil demanded this axis be sensed via
            # scripts/cortex_query.py, bypassing the system's own salience ranking.
            # It is drained here exactly like the system's own declared hunger — the
            # human's demand is not a lower class of need than the machine's.
            if item.get("kind") in ("slot_unfilled", "source_dead", "human_sense_request"):
                slot = item.get("slot", "?")
                out.append({"axis": axis, "slot": slot,
                            "requirement": _SLOT_CLASS_DESC.get(slot, "a relevant numeric data source"),
                            "detail": item.get("detail", "")[:100]})
    return out[:max_gaps]


def run(max_axes: int = 4) -> dict:
    """
    Full discovery cycle.
    Returns summary dict with axes scanned, sources found, sources validated.
    """
    print("[SCOUT] Starting autonomous data discovery...")
    discovered = _load_discovered()
    gaps       = _find_gaps(max_gaps=max_axes)
    summary    = {"scanned": 0, "suggested": 0, "validated": 0, "axes": {}}

    # composer hunger first — these are DECLARED needs, not inferred gaps
    composer_gaps = _composer_gaps()
    if composer_gaps:
        print(f"[SCOUT] {len(composer_gaps)} composer NEED(s): "
              f"{[(g['axis'][:20], g['slot']) for g in composer_gaps]}")
        for g in composer_gaps:
            axis, slot = g["axis"], g["slot"]
            entry = discovered.setdefault(axis, {"sources": []})
            asks = entry.setdefault("slot_asks", {})
            last = asks.get(slot)
            if last:
                try:
                    age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
                    if age.days < _NEED_ASK_TTL_DAYS:
                        continue  # asked recently — don't burn LLM budget every cycle
                except Exception:
                    pass
            asks[slot] = datetime.now(timezone.utc).isoformat()
            existing = [s["url"] for s in entry.get("sources", [])]
            suggestions = _suggest_sources(axis, existing, slot_requirement=g["requirement"])
            summary["suggested"] += len(suggestions)
            for s in suggestions:
                url = s.get("url", "").strip()
                fmt = s.get("format", "json").lower()
                if not url.startswith("http"):
                    continue
                print(f"  [SCOUT/NEED] Testing {axis}/{slot}: {url[:65]}")
                ok, reason, payload = _validate(url, fmt)
                if ok:
                    # THE REGISTRATION WALL. A candidate without a parsing rule is not a
                    # candidate — it is an approval Emil cannot spend usefully. Derived
                    # here, from the payload just fetched, or the candidate is dropped
                    # with a named reason and never offered.
                    rec, why = _sr.build_candidate(url, fmt, payload,
                                                   metric=s.get("metric", ""),
                                                   org=s.get("org", ""),
                                                   slot_hint=slot, axis=axis)
                    if rec is None:
                        print(f"  [SCOUT/NEED] DROPPED {url[:65]} — {why}")
                        _sr.discard(axis, url, why, stage="registration",
                                    fmt=fmt, slot_hint=slot)
                        continue
                    print(f"  [SCOUT/NEED] VALID {url[:65]} — candidate for slot '{slot}' "
                          f"[{rec['kind']}] {why}")
                    summary["validated"] += 1
                    if url not in {x["url"] for x in entry["sources"]}:
                        entry["sources"].append(rec)
                else:
                    print(f"  [SCOUT/NEED] INVALID {url[:65]} — {reason}")

    if not gaps:
        print("[SCOUT] No data gaps found — all axes have real data.")
        _save_discovered(discovered)
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
            ok, reason, payload = _validate(url, fmt)

            if ok:
                # the same wall as the composer-need path above: no rule, no registration
                rec, why = _sr.build_candidate(url, fmt, payload,
                                               metric=s.get("metric", ""),
                                               org=s.get("org", ""), axis=axis)
                if rec is None:
                    print(f"  [SCOUT] DROPPED {url[:70]} — {why}")
                    _sr.discard(axis, url, why, stage="registration", fmt=fmt)
                    continue
                print(f"  [SCOUT] VALID   {url[:70]} ({s.get('metric','')}) "
                      f"[{rec['kind']}] {why}")
                summary["validated"] += 1
                summary["axes"][axis]["validated"].append(url)

                if axis not in discovered:
                    discovered[axis] = {"sources": []}
                # Avoid duplicates
                existing_urls = {src["url"] for src in discovered[axis]["sources"]}
                if url not in existing_urls:
                    discovered[axis]["sources"].append(rec)
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
