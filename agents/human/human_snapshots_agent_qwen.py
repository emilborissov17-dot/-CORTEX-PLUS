#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, sys
from datetime import datetime, timezone
from typing import Any, Dict
BASE_DIR     = pathlib.Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = BASE_DIR / "snapshots" / "human"
sys.path.insert(0, str(BASE_DIR))
from data_providers.human.human_well_being_provider import HumanWellBeingProvider
from data_providers.human.culture_media_provider import CultureMediaProvider
from data_providers.human.cognition_learning_provider import CognitionLearningProvider
from data_providers.human.social_relations_provider import SocialRelationsProvider
from data_providers.human.governance_rights_human_provider import GovernanceRightsHumanProvider

AXES = [
    {"axis_name": "HUMAN_WELL_BEING_REVIEW",          "folder": "human_well_being",        "provider": HumanWellBeingProvider},
    {"axis_name": "CULTURE_MEDIA_REVIEW",             "folder": "culture_media",           "provider": CultureMediaProvider},
    {"axis_name": "COGNITION_LEARNING_REVIEW",        "folder": "cognition_learning",      "provider": CognitionLearningProvider},
    {"axis_name": "SOCIAL_RELATIONS_REVIEW",          "folder": "social_relations",        "provider": SocialRelationsProvider},
    {"axis_name": "GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL", "folder": "governance_rights_human", "provider": GovernanceRightsHumanProvider},
]

def _utc_now(): return datetime.now(timezone.utc).isoformat()

def _inject_memory(axis: str, prompt: str) -> str:
    try:
        from memory.continuous_learner import before_llm_call
        block = before_llm_call(axis)
        if block:
            return block + "\n\n" + prompt
    except Exception:
        pass
    return prompt

def _llm_fallback(prompt, axis="HUMAN"):
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
    print("[HUMAN_SNAPSHOT] generating HUMAN axis snapshots...")
    for cfg in AXES:
        axis, folder = cfg["axis_name"], cfg["folder"]
        print(f"[HUMAN_SNAPSHOT] generating {axis}...")
        try:
            raw = cfg["provider"]().fetch()
            path = _write(folder, axis, {"source_type": "REAL_DATA", "raw": raw})
            print(f"[HUMAN_SNAPSHOT] wrote {axis} -> {path}")
        except Exception as e:
            print(f"[HUMAN_SNAPSHOT] fallback for {axis}: {e}")
            snap = _llm_fallback(
                f"Generate JSON snapshot for {axis}. Include current_level, key_metrics, main_risks, trends. ONLY JSON. Respond ONLY in English.",
                axis=axis
            )
            snap["source_type"] = "LLM_FALLBACK"
            path = _write(folder, axis, snap)
            print(f"[HUMAN_SNAPSHOT] wrote {axis} (LLM) -> {path}")
    print("[HUMAN_SNAPSHOT] done.")

if __name__ == "__main__":
    main()