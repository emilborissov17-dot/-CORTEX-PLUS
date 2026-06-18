#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/openclaw/openclaw_agent.py

OpenClaw — Сканира ЦЕЛИЯ проект CORTEX++_QWEN:
  - всички Python файлове (агенти, памет, core)
  - всички snapshots
  - goals.py / semantic_memory / predictions / patches

След сканирането: LLM синтезира конкретни решения
за постигане на целта — устойчива общочовешка цивилизация.
"""

from __future__ import annotations
import json, pathlib, sys
from datetime import datetime, timezone

BASE = pathlib.Path(__file__).resolve().parent.parent.parent
MODEL = "qwen3:1.7b"

def _groq(prompt: str) -> dict:
    """Groq llama-3.3-70b — бърз и мощен."""
    import sys
    sys.path.insert(0, str(BASE))
    try:
        from core.groq_backend import call_groq
        text = call_groq(prompt, max_tokens=1500)
        import re
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        print(f"[OPENCLAW] Groq failed: {e} — falling back to Ollama")
        return None
EXCLUDE_DIRS = {"venv", "__pycache__", ".git", "OLD", "LEGACY", ".npm-global"}

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def scan_project():
    ctx = {
        "goals": "",
        "agents": [],
        "memory_modules": [],
        "snapshots_summary": {},
        "predictions": [],
        "self_modifier_patches": [],
        "missing_integrations": [],
        "cycle_structure": "",
        "goal_score": {},
    }

    # Goals
    gf = BASE / "core" / "goals.py"
    if gf.exists():
        ctx["goals"] = gf.read_text(encoding="utf-8", errors="ignore")[:2000]

    # All Python files
    for py in sorted(BASE.rglob("*.py")):
        if any(ex in py.parts for ex in EXCLUDE_DIRS):
            continue
        rel = str(py.relative_to(BASE))
        try:
            lines = py.read_text(encoding="utf-8", errors="ignore").splitlines()
            ctx["agents"].append({
                "file": rel,
                "lines": len(lines),
                "preview": "\n".join(lines[:20])[:400],
            })
        except Exception:
            pass

    # Memory modules
    md = BASE / "memory"
    if md.exists():
        ctx["memory_modules"] = [f.name for f in sorted(md.glob("*.py"))]

    # Snapshots
    sd = BASE / "snapshots"
    if sd.exists():
        for jf in sorted(sd.rglob("*_snapshot_latest.json")):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                axis = data.get("axis", jf.stem)
                ctx["snapshots_summary"][axis] = {
                    "current_level": data.get("current_level", "?"),
                    "progress_pct": data.get("progress_pct") or data.get("overall_progress_pct", "?"),
                    "xrisk_score": data.get("xrisk_score", "?"),
                    "bottlenecks": data.get("main_bottlenecks", [])[:3],
                    "next_actions": data.get("next_actions", [])[:2],
                }
            except Exception:
                pass

    # Predictions
    pf = BASE / "memory" / "predictions.json"
    if pf.exists():
        try:
            p = json.loads(pf.read_text(encoding="utf-8"))
            ctx["predictions"] = p[-10:] if isinstance(p, list) else []
        except Exception:
            pass

    # Patches
    pd = BASE / "patches"
    if pd.exists():
        ctx["self_modifier_patches"] = [f.name for f in pd.glob("*.py")]

    # Goal score
    gs = BASE / "snapshots" / "master" / "goal_score_latest.json"
    if gs.exists():
        try:
            ctx["goal_score"] = json.loads(gs.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Cycle structure
    rf = BASE / "fast_cycle_runner.py"
    if rf.exists():
        ctx["cycle_structure"] = rf.read_text(encoding="utf-8", errors="ignore")[:1500]

    # Missing integrations
    for a in ctx["agents"]:
        name = pathlib.Path(a["file"]).stem
        if "agent" in name.lower() and name not in ctx["cycle_structure"]:
            ctx["missing_integrations"].append(a["file"])

    return ctx

def synthesize(ctx):
    agents_list = "\n".join(f"  - {a['file']} ({a['lines']} lines)" for a in ctx["agents"][:50])
    snap_str = json.dumps(ctx["snapshots_summary"], ensure_ascii=False, indent=2)[:2000]
    missing_str = "\n".join(f"  - {m}" for m in ctx["missing_integrations"][:20]) or "(none)"
    goal_score_str = json.dumps(ctx.get("goal_score", {}), ensure_ascii=False, indent=2)[:500] or "(not available)"

    vision_file = BASE / "core" / "civilization_vision.txt"
    vision_text = vision_file.read_text(encoding="utf-8", errors="ignore") if vision_file.exists() else "(vision not found)"

    # Load Attentional Meta Protocol output (cortex_orchestrator runs at Step 12.7)
    attention_block = ""
    orch_path = BASE / "memory" / "orchestration_latest.json"
    if orch_path.exists():
        try:
            orch = json.loads(orch_path.read_text(encoding="utf-8"))
            att = orch.get("attention", {})
            plan = orch.get("strategic_plan", {})
            attention_block = (
                "── ATTENTIONAL META PROTOCOL (this cycle) ──\n"
                f"Priority axes: {att.get('priority_axes', [])}\n"
                f"Main threat:   {att.get('main_threat', '?')}\n"
                f"Opportunity:   {att.get('main_opportunity', '?')}\n"
                f"Action now:    {att.get('immediate_action', '?')}\n"
                f"Key insight:   {plan.get('key_insight', '?')}\n"
                "────────────────────────────────────────────"
            )
        except Exception:
            pass

    # Load real global indicators if available this cycle
    gi_block = ""
    gi_path = BASE / "snapshots" / "master" / "global_indicators_latest.json"
    if gi_path.exists():
        try:
            from core.global_indicators import as_prompt_block
            gi_data = json.loads(gi_path.read_text(encoding="utf-8"))
            gi_block = as_prompt_block(gi_data)
        except Exception:
            gi_block = "(global indicators file exists but could not be loaded)"

    prompt = f"""You are OpenClaw — strategic intelligence of CORTEX++ AGI.

MISSION:
{vision_text}

You scanned the ENTIRE CORTEX++_QWEN project. Full context:

── GOALS ──
{ctx['goals'][:800]}

── PROJECT FILES ({len(ctx['agents'])} files) ──
{agents_list}

── MEMORY MODULES ──
{', '.join(ctx['memory_modules'])}

── SNAPSHOTS STATE ──
{snap_str}

── GOAL SCORE (composite from real data) ──
{goal_score_str}

{attention_block}

{gi_block}

── AGENTS NOT IN fast_cycle_runner (missing integrations) ──
{missing_str}

── CYCLE STRUCTURE ──
{ctx['cycle_structure'][:800]}

── PATCHES ──
{', '.join(ctx['self_modifier_patches']) or '(none)'}

TASK: Analyze EVERYTHING. What is missing? What is broken? What must be built?
How does this system get closer to the MISSION?

Return ONLY this JSON:
{{
  "system_health": "POOR|FAIR|GOOD|EXCELLENT",
  "mission_alignment_pct": <0-100>,
  "critical_gaps": [
    {{"gap": "<what is missing>", "impact": "HIGH|MEDIUM|LOW", "fix": "<concrete action>"}}
  ],
  "immediate_actions": [
    {{"action": "<what to do>", "file": "<which file>", "why": "<reason>"}}
  ],
  "missing_agents_to_build": [
    {{"name": "<AgentName>", "role": "<what it does>", "priority": "HIGH|MEDIUM"}}
  ],
  "fast_cycle_improvements": ["<improvement>"],
  "next_milestone": "<what brings system to next level>",
  "openclaw_self_assessment": "<what OpenClaw should do next>"
}}

Be specific. Reference actual filenames. Return ONLY valid JSON."""

    result = _groq(prompt)
    if result and "error" not in result:
        print("[OPENCLAW] LLM: Groq ✅")
        return result
    return {"error": "All LLM backends failed"}

def save(result):
    out_dir = BASE / "snapshots" / "openclaw"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "openclaw_snapshot_latest.json"
    result["snapshot_timestamp"] = _utc_now()
    result["axis"] = "OPENCLAW_SOLUTIONS"
    result["source_type"] = "OPENCLAW_FULL_SCAN"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OPENCLAW] snapshot → {out_path}")
    try:
        sys.path.insert(0, str(BASE))
        from memory.semantic_memory import remember
        summary = (f"OpenClaw FullScan [{_utc_now()}]: "
                   f"Health={result.get('system_health','?')} | "
                   f"Mission={result.get('mission_alignment_pct','?')}% | "
                   f"Gaps={len(result.get('critical_gaps',[]))} | "
                   f"Next: {result.get('next_milestone','?')}")
        remember(summary[:600], axis="OPENCLAW_FULL_SCAN", source="openclaw_agent")
        print("[OPENCLAW] memory saved.")
    except Exception as e:
        print(f"[OPENCLAW] memory save failed: {e}")

def run():
    print(f"[OPENCLAW] FullScan started at {_utc_now()}")
    ctx = scan_project()
    print(f"[OPENCLAW] {len(ctx['agents'])} files | {len(ctx['snapshots_summary'])} snapshots | {len(ctx['missing_integrations'])} missing integrations")
    print("[OPENCLAW] synthesizing strategic plan...")
    result = synthesize(ctx)
    if "error" in result:
        print(f"[OPENCLAW] LLM error: {result['error']}")
        return result
    print(f"[OPENCLAW] health={result.get('system_health')} | mission={result.get('mission_alignment_pct')}% | gaps={len(result.get('critical_gaps',[]))}")
    save(result)
    print(f"[OPENCLAW] done at {_utc_now()}")
    return result

if __name__ == "__main__":
    result = run()
    print("\n══ OPENCLAW STRATEGIC PLAN ══")
    print(json.dumps(result, ensure_ascii=False, indent=2))