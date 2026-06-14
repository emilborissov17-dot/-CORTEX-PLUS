#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/core/daily_analysis_agent.py

Чете master_snapshot_latest.json, анализира всяка ос с LLM
и записва препоръки в notes/next_actions.txt и daily/YYYY-MM-DD_analysis.json
"""
from __future__ import annotations
import json, pathlib, subprocess, sys
from datetime import datetime, date, timezone

BASE_DIR     = pathlib.Path(__file__).resolve().parents[2]
MASTER_PATH  = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"
NOTES_DIR    = BASE_DIR / "notes"
DAILY_DIR    = BASE_DIR / "daily"
MODEL        = "qwen3:8b"
sys.path.insert(0, str(BASE_DIR))

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def _llm(prompt: str) -> str:
    try:
        r = subprocess.run(
            ["ollama", "run", MODEL],
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        return r.stdout.decode("utf-8", errors="ignore").strip()
    except Exception as e:
        return f"[LLM ERROR: {e}]"

def _clean_llm(text: str) -> str:
    """Премахва Thinking блокове и markdown fences."""
    if "...done thinking." in text:
        text = text.split("...done thinking.")[-1].strip()
    elif "</think>" in text:
        text = text.split("</think>")[-1].strip()
    elif "Thinking..." in text:
        text = text.split("Thinking...")[-1].strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return text.strip()

def _analyze_axis(axis_name: str, snapshot: dict) -> dict:
    raw = json.dumps(snapshot, ensure_ascii=False, indent=2)[:2000]
    prompt = f"""You are CORTEX++ AGI analyzing civilization data.

AXIS: {axis_name}
DATA: {raw}

Analyze this axis snapshot and return ONLY a JSON object with:
- current_level: LOW / MEDIUM / HIGH
- summary: 2-3 sentences in Bulgarian describing the current state
- main_risks: list of 3 biggest risks
- recommended_actions: list of 3 concrete actions to improve this axis
- trend: IMPROVING / STABLE / DETERIORATING

Return ONLY valid JSON, no explanation."""

    text = _llm(prompt)
    try:
        text = _clean_llm(text)
        return json.loads(text)
    except Exception:
        return {"current_level": "UNKNOWN", "summary": text[:300], "error": "parse_failed"}

def _generate_overall_assessment(analyses: dict) -> str:
    levels = [a.get("current_level", "UNKNOWN") for a in analyses.values()]
    low    = levels.count("LOW")
    medium = levels.count("MEDIUM")
    high   = levels.count("HIGH")

    prompt = f"""You are CORTEX++ AGI. Based on analysis of {len(analyses)} civilization axes:
- LOW level axes: {low}
- MEDIUM level axes: {medium}
- HIGH level axes: {high}

Axes analyzed: {list(analyses.keys())}

Write a concise overall assessment in Bulgarian (5-7 sentences):
1. Overall civilization state
2. Most critical bottlenecks
3. Most urgent next actions toward: sustainable civilization, dignity for all, AGI in service of humanity

Be concrete and actionable."""

    return _llm(prompt)

def main():
    print("[DAILY_ANALYSIS] starting daily analysis...")

    if not MASTER_PATH.exists():
        print(f"[DAILY_ANALYSIS] ERROR: {MASTER_PATH} not found. Run hypercortex_runner.py first.")
        return

    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    snapshots = master.get("snapshots", {})
    print(f"[DAILY_ANALYSIS] analyzing {len(snapshots)} axes...")

    analyses = {}
    for axis_name, snapshot in snapshots.items():
        print(f"[DAILY_ANALYSIS] analyzing {axis_name}...")
        analyses[axis_name] = _analyze_axis(axis_name, snapshot)
        level = analyses[axis_name].get("current_level", "?")
        print(f"[DAILY_ANALYSIS] {axis_name} -> {level}")

    print("[DAILY_ANALYSIS] generating overall assessment...")
    overall = _generate_overall_assessment(analyses)

    # Build daily report
    today = date.today().isoformat()
    report = {
        "date": today,
        "timestamp": _utc_now(),
        "axes_analyzed": len(analyses),
        "analyses": analyses,
        "overall_assessment": overall,
    }

    # Save daily report
    DAILY_DIR.mkdir(exist_ok=True)
    daily_path = DAILY_DIR / f"{today}_analysis.json"
    daily_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DAILY_ANALYSIS] daily report -> {daily_path}")

    # Update next_actions.txt
    NOTES_DIR.mkdir(exist_ok=True)
    next_actions_lines = [f"DAILY ANALYSIS — {today}\n", "=" * 50 + "\n\n"]
    next_actions_lines.append("OVERALL ASSESSMENT:\n")
    next_actions_lines.append(overall + "\n\n")
    next_actions_lines.append("RECOMMENDED ACTIONS BY AXIS:\n")
    next_actions_lines.append("-" * 40 + "\n")
    for axis, analysis in analyses.items():
        level = analysis.get("current_level", "?")
        actions = analysis.get("recommended_actions", [])
        next_actions_lines.append(f"\n[{level}] {axis}:\n")
        for i, action in enumerate(actions, 1):
            next_actions_lines.append(f"  {i}. {action}\n")

    next_actions_path = NOTES_DIR / "next_actions.txt"
    next_actions_path.write_text("".join(next_actions_lines), encoding="utf-8")
    print(f"[DAILY_ANALYSIS] next_actions.txt updated -> {next_actions_path}")
    print("[DAILY_ANALYSIS] done.")

if __name__ == "__main__":
    main()