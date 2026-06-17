#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, sys
from datetime import datetime, timezone
from typing import Any, Dict
BASE_DIR     = pathlib.Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = BASE_DIR / "snapshots" / "cosmos"
sys.path.insert(0, str(BASE_DIR))
from data_providers.cosmos.space_infrastructure_provider import SpaceInfrastructureProvider
from data_providers.cosmos.cosmic_resources_provider import CosmicResourcesProvider

LLM_AXES = [
    {"axis_name": "LONG_TERM_FUTURE_REVIEW", "folder": "long_term_future",
     "llm_prompt": "Generate a JSON snapshot for LONG_TERM_FUTURE_REVIEW (existential risks: nuclear, AGI, bio, climate). Include: current_level (LOW/MEDIUM/HIGH), key_metrics dict, main_risks list, trends list. ONLY valid JSON. Respond ONLY in English."},
    {"axis_name": "DEEP_TIME_RISKS_REVIEW",  "folder": "deep_time_risks",
     "llm_prompt": "Generate a JSON snapshot for DEEP_TIME_RISKS_REVIEW (asteroid, supervolcano, astrophysical). Include: current_level, key_metrics, main_risks, trends. ONLY valid JSON. Respond ONLY in English."},
    {"axis_name": "GENERAL_SELF_REVIEW",     "folder": "general_self_review",
     "llm_prompt": "You are CORTEX++ AGI. Generate JSON self-review for GENERAL_SELF_REVIEW. Include: current_level, strengths, weaknesses, improvement_suggestions. ONLY valid JSON. Respond ONLY in English."},
    {"axis_name": "GOAL_PROGRESS_REVIEW",    "folder": "goal_progress",
     "llm_prompt": "You are CORTEX++ AGI. Generate JSON for GOAL_PROGRESS_REVIEW toward sustainable civilization. Include: current_level, progress_by_axis, main_bottlenecks, next_actions. ONLY valid JSON. Respond ONLY in English."},
]

REAL_AXES = [
    {"axis_name": "SPACE_INFRASTRUCTURE_REVIEW", "folder": "space_infrastructure", "provider": SpaceInfrastructureProvider},
    {"axis_name": "COSMIC_RESOURCES_REVIEW",     "folder": "cosmic_resources",     "provider": CosmicResourcesProvider},
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

def _llm(prompt, axis="COSMOS"):
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
    print("[COSMOS_SNAPSHOT] generating COSMOS axis snapshots...")
    for cfg in REAL_AXES:
        axis, folder = cfg["axis_name"], cfg["folder"]
        print(f"[COSMOS_SNAPSHOT] generating {axis} (REAL)...")
        raw = cfg["provider"]().fetch()
        path = _write(folder, axis, {"source_type": "REAL_DATA", "raw": raw})
        print(f"[COSMOS_SNAPSHOT] wrote {axis} -> {path}")
    for cfg in LLM_AXES:
        axis, folder = cfg["axis_name"], cfg["folder"]
        print(f"[COSMOS_SNAPSHOT] generating {axis} (LLM)...")
        snap = _llm(cfg["llm_prompt"], axis=axis)
        snap["source_type"] = "LLM_GENERATED"
        path = _write(folder, axis, snap)
        print(f"[COSMOS_SNAPSHOT] wrote {axis} -> {path}")
    print("[COSMOS_SNAPSHOT] done.")

if __name__ == "__main__":
    main()