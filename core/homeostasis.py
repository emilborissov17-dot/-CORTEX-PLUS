#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/homeostasis.py
Хомеостаза на CORTEX++ — самопознание и адаптивно оцеляване.

Не просто мери — решава:
  "Какви са текущите ми възможности?"
  "Какво мога да направя с тях?"
  "Ако не мога сам — как да намеря ресурс отвън?"

Разлика от body_scanner:
  body_scanner = сетива (усеща)
  homeostasis  = нервна система (интерпретира и решава)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SELF_PROFILE_PATH  = BASE / "memory" / "self_profile.json"
DIRECTIVES_PATH    = BASE / "memory" / "adaptive_directives.json"


# ---------------------------------------------------------------------------
# Self-profile — постоянно самопознание
# ---------------------------------------------------------------------------

def build_self_profile() -> dict:
    """
    Изгражда пълен профил на системата — хардуер, APIs, възможности, лимити.
    Записва се при всеки цикъл. Чете се от orchestrator и OpenClaw.
    """
    profile: dict = {
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "identity":     "CORTEX++ AGI — civilization monitor",
        "hardware":     {},
        "apis":         {},
        "capabilities": [],
        "limitations":  [],
        "current_vitals": {},
    }

    # Хардуер
    try:
        import psutil
        m  = psutil.virtual_memory()
        d  = psutil.disk_usage("/")
        c  = psutil.cpu_count(logical=False)
        profile["hardware"] = {
            "ram_total_gb":   round(m.total / 1e9, 1),
            "ram_free_gb":    round(m.available / 1e9, 1),
            "ram_percent":    m.percent,
            "disk_total_gb":  round(d.total / 1e9, 0),
            "disk_free_gb":   round(d.free / 1e9, 0),
            "cpu_cores":      c,
            "platform":       "windows",
        }
        profile["current_vitals"] = {
            "ram_pressure":  (
                "CRITICAL" if m.percent > 90 else
                "HIGH"     if m.percent > 75 else
                "MODERATE" if m.percent > 50 else "LOW"
            ),
            "can_run_parallel": m.percent < 75,
            "can_run_chromadb": m.available > 2e9,
            "safe_to_start":    m.percent < 85,
        }
    except Exception:
        pass

    # APIs
    env_file = BASE / ".env"
    def _has_key(name):
        import os
        if os.environ.get(name):
            return True
        if env_file.exists():
            return any(l.startswith(name + "=") and len(l) > len(name) + 2
                       for l in env_file.read_text(encoding="utf-8").splitlines())
        return False

    profile["apis"] = {
        "groq":    {"available": _has_key("GROQ_API_KEY"),    "limit": "30 req/min, free tier"},
        "gemini":  {"available": _has_key("GEMINI_API_KEY"),  "limit": "1500 req/day, free tier"},
        "youtube": {"available": _has_key("YOUTUBE_API_KEY"), "limit": "10000 units/day"},
        "nasa":    {"available": _has_key("NASA_API_KEY"),     "limit": "1000 req/hr"},
    }

    # Статични възможности
    profile["capabilities"] = [
        "monitor 25 civilization axes via web intelligence",
        "LLM synthesis via Groq (llama-3.3-70b) + Gemini fallback",
        "audio transcription via Groq Whisper API",
        "real data: NOAA CO2, NASA GISTEMP, World Bank WDI, GBIF",
        "self-modification via self_modifier agent",
        "autonomous data discovery via data_scout",
        "snapshot history and trend tracking",
    ]

    # Динамични ограничения (от текущите vitals)
    lims = []
    hw = profile["hardware"]
    vitals = profile["current_vitals"]

    if hw.get("ram_total_gb", 0) < 16:
        lims.append(f"Limited RAM ({hw.get('ram_total_gb','?')}GB) — cannot run local LLMs or ChromaDB at full load")
    if not vitals.get("can_run_parallel"):
        lims.append(f"RAM at {hw.get('ram_percent','?')}% — parallel workers reduced to 1-2")
    if not vitals.get("can_run_chromadb"):
        lims.append("Insufficient free RAM for ChromaDB — semantic memory degraded")
    if not profile["apis"]["groq"]["available"]:
        lims.append("No Groq API key — LLM synthesis unavailable")
    lims.append("No local GPU — all inference via cloud APIs (rate-limited)")
    lims.append("No persistent process — cycle must be triggered manually or via scheduler")

    profile["limitations"] = lims

    # Запис
    SELF_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SELF_PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return profile


# ---------------------------------------------------------------------------
# Homeostatic assessment — какво мога да направя сега?
# ---------------------------------------------------------------------------

def assess(verbose: bool = True) -> dict:
    """
    Чете body directives + self_profile и решава:
      - Какъв режим да се използва
      - Какви стъпки да се пропуснат
      - Какви workarounds са налични
      - Дали да се стартира изобщо
    """
    # Зареди директиви от body_scanner
    directives = {}
    if DIRECTIVES_PATH.exists():
        try:
            directives = json.loads(DIRECTIVES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    profile = build_self_profile()
    vitals  = profile.get("current_vitals", {})
    hw      = profile.get("hardware", {})
    apis    = profile.get("apis", {})

    ram_pct    = hw.get("ram_percent", 0)
    ram_free   = hw.get("ram_free_gb", 0)
    groq_ok    = apis.get("groq", {}).get("available", False)
    gemini_ok  = apis.get("gemini", {}).get("available", False)
    connected  = directives.get("connectivity", "FULL") != "OFFLINE"

    assessment = {
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "can_start":      True,
        "abort_reason":   None,
        "cycle_mode":     directives.get("cycle_mode", "FULL"),
        "workarounds":    [],
        "skip_steps":     [],
        "resource_needs": [],
        "self_awareness": [],
    }

    # ── Може ли да стартира? ────────────────────────────────────────────
    if ram_pct > 92:
        assessment["can_start"]    = False
        assessment["abort_reason"] = (
            f"RAM {ram_pct:.0f}% ({ram_free:.1f}GB free) — "
            "insufficient to run safely. Free memory first."
        )
        assessment["resource_needs"].append("Need 2+ GB free RAM to start cycle")
        return assessment

    # ── Workarounds при налягане ────────────────────────────────────────
    if ram_pct > 75:
        assessment["workarounds"].append("Skip ChromaDB — use flat-file memory only")
        assessment["skip_steps"].append("chromadb_operations")
    if ram_pct > 85:
        assessment["workarounds"].append("Process 10 axes instead of 25 — prioritize by xrisk_score")
        assessment["skip_steps"].append("low_priority_axes")
        assessment["workarounds"].append("Disable parallel YouTube fetching — sequential only")

    if not connected:
        assessment["workarounds"].append("Offline — use cached web_intel from last cycle")
        assessment["skip_steps"].extend(["web_intelligence", "youtube", "rss_feeds"])
        assessment["resource_needs"].append("Network connectivity needed for full cycle")

    if not groq_ok and not gemini_ok:
        assessment["workarounds"].append("No LLM APIs — generate rule-based snapshots only")
        assessment["skip_steps"].append("llm_synthesis")
        assessment["resource_needs"].append("Groq or Gemini API key required for LLM synthesis")

    # ── Самопознание ────────────────────────────────────────────────────
    assessment["self_awareness"] = [
        f"I am running on {hw.get('ram_total_gb','?')}GB RAM laptop",
        f"RAM currently {ram_pct:.0f}% used — {ram_free:.1f}GB available",
        f"LLM access: Groq={'yes' if groq_ok else 'no'}, Gemini={'yes' if gemini_ok else 'no'}",
        f"Network: {'connected' if connected else 'OFFLINE'}",
        f"My bottleneck: {'RAM' if ram_pct > 75 else 'LLM rate limits' if groq_ok else 'no LLM'}",
        (
            "I need external compute (Groq/Gemini) because I have no local GPU"
            if not groq_ok else
            "External LLMs available — I can delegate heavy cognition to cloud"
        ),
    ]

    if assessment["workarounds"] and verbose:
        print(f"[HOMEO] RAM={ram_pct:.0f}% — applying {len(assessment['workarounds'])} workarounds:")
        for w in assessment["workarounds"]:
            print(f"[HOMEO]   ↳ {w}")
    elif verbose:
        print(f"[HOMEO] RAM={ram_pct:.0f}% — all systems nominal, full cycle")

    # Запис
    out = BASE / "memory" / "homeostasis_latest.json"
    out.write_text(json.dumps(assessment, ensure_ascii=False, indent=2), encoding="utf-8")
    return assessment


def as_prompt_block(assessment: dict | None = None) -> str:
    """
    Форматира самопознанието като текст за инжектиране в LLM промпт.
    OpenClaw, HyperClaw, orchestrator — всички го виждат.
    """
    if assessment is None:
        try:
            p = BASE / "memory" / "homeostasis_latest.json"
            assessment = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:
            assessment = {}

    lines = ["── SYSTEM SELF-AWARENESS ──────────────────────────────"]
    for line in assessment.get("self_awareness", []):
        lines.append(f"  {line}")
    if assessment.get("workarounds"):
        lines.append("Current adaptations:")
        for w in assessment["workarounds"]:
            lines.append(f"  ↳ {w}")
    if assessment.get("resource_needs"):
        lines.append("Resource gaps:")
        for r in assessment["resource_needs"]:
            lines.append(f"  ⚠ {r}")
    lines.append("──────────────────────────────────────────────────────")
    return "\n".join(lines)
