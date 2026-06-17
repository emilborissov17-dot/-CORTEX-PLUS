#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, sys
from datetime import datetime, timezone
from typing import Any, Dict
BASE_DIR     = pathlib.Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = BASE_DIR / "snapshots" / "civilization"
sys.path.insert(0, str(BASE_DIR))
from data_providers.civilization.economy_work_provider import EconomyWorkProvider
from data_providers.civilization.governance_institutions_provider import GovernanceInstitutionsProvider
from data_providers.civilization.technology_ai_provider import TechnologyAIProvider
from data_providers.civilization.inequality_poverty_provider import InequalityPovertyProvider
from data_providers.civilization.infrastructure_cities_provider import InfrastructureCitiesProvider
from data_providers.civilization.education_culture_provider import EducationCultureProvider
from data_providers.civilization.technology_infra_provider import TechnologyInfraProvider

AXES = [
    {"axis_name": "ECONOMY_WORK_REVIEW",            "folder": "economy_work",            "provider": EconomyWorkProvider},
    {"axis_name": "INEQUALITY_POVERTY_REVIEW",      "folder": "inequality_poverty",      "provider": InequalityPovertyProvider},
    {"axis_name": "INFRASTRUCTURE_CITIES_REVIEW",   "folder": "infrastructure_cities",   "provider": InfrastructureCitiesProvider},
    {"axis_name": "GOVERNANCE_INSTITUTIONS_REVIEW", "folder": "governance_institutions", "provider": GovernanceInstitutionsProvider},
    {"axis_name": "EDUCATION_CULTURE_REVIEW",       "folder": "education_culture",       "provider": EducationCultureProvider},
    {"axis_name": "TECHNOLOGY_INFRA_REVIEW",        "folder": "technology_infra",        "provider": TechnologyInfraProvider},
    {"axis_name": "TECHNOLOGY_AI_REVIEW",           "folder": "technology_ai",           "provider": TechnologyAIProvider},
]

def _utc_now(): return datetime.now(timezone.utc).isoformat()

def _inject_memory(axis: str, prompt: str) -> str:
    try:
        from memory.continuous_learner import before_llm_call
        block = before_llm_call(axis)
        if block:
            prompt = block + "\n\n" + prompt
    except Exception:
        pass
    try:
        from media_transcript_injector import get_media_context_block
        media_block = get_media_context_block(axis)
        if media_block:
            prompt = media_block + "\n\n" + prompt
    except Exception:
        pass
    return prompt

def _llm_fallback(prompt, axis="CIVILIZATION"):
    prompt = _inject_memory(axis, prompt)
    try:
        from core.groq_backend import call_groq
        text = call_groq(prompt, max_tokens=1024)
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:   text = text.split("```")[1].split("```")[0].strip()
        if "</think>" in text: text = text.split("</think>")[-1].strip()
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

def _write(folder, axis_name, data):
    out_dir = SNAPSHOT_DIR / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{folder}_snapshot_latest.json"
    data["snapshot_timestamp"] = _utc_now()
    data["axis"] = axis_name
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

def main():
    print("[CIVILIZATION_SNAPSHOT] generating CIVILIZATION axis snapshots...")
    for cfg in AXES:
        axis, folder = cfg["axis_name"], cfg["folder"]
        print(f"[CIVILIZATION_SNAPSHOT] generating {axis}...")
        try:
            raw = cfg["provider"]().fetch()
            path = _write(folder, axis, {"source_type": "REAL_DATA", "metrics": raw, "raw": raw})
            print(f"[CIVILIZATION_SNAPSHOT] wrote {axis} -> {path}")
        except Exception as e:
            print(f"[CIVILIZATION_SNAPSHOT] fallback for {axis}: {e}")
            snap = _llm_fallback(
                f"Generate JSON snapshot for {axis}. Include current_level, key_metrics, main_risks, trends. ONLY JSON. Respond ONLY in English.",
                axis=axis
            )
            snap["source_type"] = "LLM_FALLBACK"
            path = _write(folder, axis, snap)
            print(f"[CIVILIZATION_SNAPSHOT] wrote {axis} (LLM) -> {path}")
    print("[CIVILIZATION_SNAPSHOT] done.")

if __name__ == "__main__":
    main()