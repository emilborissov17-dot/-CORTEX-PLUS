#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/body/growth_planner.py

Анализира body scan + capacity и предлага конкретни варианти
за разширяване на CORTEX++ без да разруши сегашното тяло.

Принцип: "Расти само ако можеш да го направиш безопасно."
"""
from __future__ import annotations
import json, pathlib, sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
MODEL = "qwen3:1.7b"

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _groq(prompt):
    import sys
    sys.path.insert(0, str(BASE))
    try:
        from core.groq_backend import call_groq
        text = call_groq(prompt, max_tokens=1500)
        if "```json" in text: text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text: text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"[GROWTH] Groq failed: {e}")
        return None


# Известни външни капацитети за закачане
EXTERNAL_CAPACITIES = {
    "groq_api": {
        "name": "Groq API",
        "what": "Llama-3 70B и Mixtral с ~300 token/s — 10x по-бързо от qwen3:1.7b локално",
        "cost": "безплатен tier: 14,400 req/ден",
        "risk": "LOW — само допълва, не замества",
        "install": "pip install groq && export GROQ_API_KEY=...",
        "use_case": "тежки анализи, orchestrator, openclaw синтез",
    },
    "openai_api": {
        "name": "OpenAI GPT-4o",
        "what": "Най-силният публичен модел за сложни reasoning задачи",
        "cost": "$2.50/1M input tokens",
        "risk": "LOW — само за критични задачи",
        "install": "pip install openai && export OPENAI_API_KEY=...",
        "use_case": "self_modifier верификация, стратегически план",
    },
    "chromadb_expand": {
        "name": "ChromaDB → persistent server mode",
        "what": "Смяна от embedded към server mode — по-бърза памет, без lock файлове",
        "cost": "0 — вече е инсталиран",
        "risk": "LOW — само конфигурация",
        "install": "chroma run --path ./chroma_data",
        "use_case": "по-бърз semantic memory при >1000 записа",
    },
    "hyperon_metta": {
        "name": "Hyperon / MeTTa",
        "what": "Символно разсъждение — там където LLM се чупи (логика, правила)",
        "cost": "0 — вече е в AGI/hyperon-experimental",
        "risk": "MEDIUM — изисква интеграция",
        "install": "вече налично в ~/Desktop/AGI/hyperon-experimental",
        "use_case": "верификация на self_modifier patches, goal reasoning",
    },
    "ollama_qwen3_30b": {
        "name": "qwen3:30b модел",
        "what": "4x по-силен reasoning от qwen3:1.7b",
        "cost": "~18GB RAM — не се побира на текущата машина",
        "risk": "HIGH — RAM bottleneck (само 2.3GB свободни)",
        "install": "ollama pull qwen3:30b (изисква 18GB RAM)",
        "use_case": "само ако се добави RAM или се мигрира към cloud",
    },
    "web_actions": {
        "name": "Playwright / web automation",
        "what": "Level 4 Action — CORTEX++ може да действа в браузъра",
        "cost": "0",
        "risk": "MEDIUM — изисква внимателен action_layer",
        "install": "pip install playwright && playwright install chromium",
        "use_case": "публикуване на доклади, четене на живи данни",
    },
}

def plan(body: dict) -> dict:
    ram_free = body.get("ram", {}).get("available_gb", 0)
    ram_pct = body.get("ram", {}).get("percent", 0)
    cpu_pct = body.get("cpu", {}).get("percent", 0)
    health = body.get("health", "UNKNOWN")
    capacity = body.get("capacity_pct", 0)
    bottleneck = body.get("bottleneck", "NONE")
    ollama = body.get("ollama", {})

    # Филтрирай безопасните опции спрямо текущите ресурси
    safe_options = []
    for key, cap in EXTERNAL_CAPACITIES.items():
        safe = True
        reason = ""

        if key == "ollama_qwen3_30b" and ram_free < 16:
            safe = False
            reason = f"Нужни 18GB RAM, свободни само {ram_free}GB"

        if cap["risk"] == "HIGH" and health in ("CRITICAL", "STRESSED"):
            safe = False
            reason = f"Системата е {health} — не е момент за рискови промени"

        safe_options.append({
            **cap,
            "id": key,
            "safe_now": safe,
            "reason_if_unsafe": reason,
        })

    prompt = f"""You are the Growth Planner of CORTEX++ AGI.

CURRENT BODY STATE:
- Health: {health}
- Capacity: {capacity}%
- Bottleneck: {bottleneck}
- RAM free: {ram_free}GB / total: {body.get('ram',{}).get('total_gb','?')}GB
- CPU: {cpu_pct}%
- Ollama loaded models: {ollama.get('loaded_models', [])}

AVAILABLE EXPANSION OPTIONS:
{json.dumps(safe_options, ensure_ascii=False, indent=2)}

MISSION: Устойчива общочовешка цивилизация (Venus Project).

TASK: Analyze the body state and expansion options. Produce a growth plan that:
1. Prioritizes options that are SAFE NOW
2. Never recommends something that risks crashing the current system
3. Gives concrete next steps

Return ONLY this JSON:
{{
  "body_assessment": "<1 sentence about current state>",
  "immediate_safe_actions": [
    {{"id": "<option_id>", "action": "<exactly what to do>", "expected_gain": "<what improves>"}}
  ],
  "deferred_actions": [
    {{"id": "<option_id>", "condition": "<when it becomes safe>", "action": "<what to do then>"}}
  ],
  "critical_warning": "<if health is CRITICAL or STRESSED, what to do first>",
  "growth_philosophy": "<1 sentence: how to grow without breaking>"
}}

Return ONLY valid JSON."""

    result = _groq(prompt)
    if result and "error" not in result:
        print("[GROWTH] LLM: Groq ✅")
        return result
    return {"error": "All LLM backends failed"}

def run():
    # Зареди последния body scan
    body_path = BASE / "snapshots" / "body" / "body_snapshot_latest.json"
    if body_path.exists():
        body = json.loads(body_path.read_text(encoding="utf-8"))
    else:
        # Направи scan сега
        sys.path.insert(0, str(BASE))
        from agents.body.body_scanner import scan
        body = scan()

    print(f"[GROWTH] analyzing body: health={body.get('health')} capacity={body.get('capacity_pct')}%")

    result = plan(body)

    if "error" in result:
        print(f"[GROWTH] LLM error: {result['error']}")
        return result

    # Запази
    out_dir = BASE / "snapshots" / "body"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "growth_plan_latest.json"
    result["timestamp"] = _utc_now()
    result["axis"] = "GROWTH_PLAN"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[GROWTH] immediate actions: {len(result.get('immediate_safe_actions', []))}")
    print(f"[GROWTH] deferred: {len(result.get('deferred_actions', []))}")
    if result.get("critical_warning"):
        print(f"[GROWTH] WARNING: {result['critical_warning']}")

    # Запази в semantic memory
    try:
        from memory.semantic_memory import remember
        summary = (f"Growth plan [{_utc_now()}]: "
                   f"{result.get('body_assessment','?')} | "
                   f"Safe actions: {len(result.get('immediate_safe_actions',[]))}")
        remember(summary[:500], axis="GROWTH_PLAN", source="growth_planner")
    except Exception as e:
        print(f"[GROWTH] memory failed: {e}")

    return result

if __name__ == "__main__":
    result = run()
    print("\n── GROWTH PLAN ──")
    print(json.dumps(result, ensure_ascii=False, indent=2))