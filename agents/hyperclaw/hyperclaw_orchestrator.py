#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/hyperclaw/hyperclaw_orchestrator.py
HyperClaw — генерира глобален 24-72h план по четирите оси:
HUMAN / PLANET / CIVILIZATION / COSMOS
Чете master_snapshot_latest.json (dailyreview-*.md като fallback).
"""
from __future__ import annotations
import json, pathlib
from datetime import datetime, timezone

BASE      = pathlib.Path(__file__).resolve().parents[2]
PLAN_DIR  = BASE / "plans"
AXES_SPEC = BASE / "agi_axes_spec.txt"
PLAN_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _read_context() -> str:
    master = BASE / "snapshots" / "master" / "master_snapshot_latest.json"
    if master.exists():
        try:
            data = json.loads(master.read_text(encoding="utf-8"))
            summary = {
                "axes_count": data.get("axes_count", 0),
                "timestamp":  data.get("timestamp"),
            }
            for axis, d in data.get("snapshots", {}).items():
                summary[axis] = {
                    "current_level": d.get("current_level", "?"),
                    "xrisk_score":   d.get("xrisk_score", "?"),
                    "progress_pct":  d.get("progress_pct") or d.get("overall_progress_pct", "?"),
                    "bottlenecks":   d.get("main_bottlenecks", [])[:2],
                    "next_actions":  d.get("next_actions", [])[:2],
                }
            return json.dumps(summary, ensure_ascii=False, indent=2)[:4000]
        except Exception:
            pass
    # Fallback: most recent dailyreview
    daily = BASE / "daily"
    if daily.exists():
        files = sorted(daily.glob("dailyreview-*.md"), key=lambda p: p.name, reverse=True)
        if files:
            return files[0].read_text(encoding="utf-8", errors="ignore")[:4000]
    return "(no snapshot data available)"


def _build_prompt(context: str, axes_spec: str, today: str) -> str:
    return (
        "Ти си CORTEX++ в ролята на HYPERCLAW_ORCHESTRATOR.\n"
        "Имаш достъп до текущото състояние на системата по всички оси.\n\n"
        "ЗАДАЧА: Генерирай глобален план `plan-{today}.md` с конкретни стъпки\n"
        "за следващите 24-72 часа по всяка от четирите оси.\n"
        "За всяка ос избери под-оси с нисък прогрес или висок риск.\n\n"
        "ИЗХОД: САМО Markdown съдържание. Без meta-коментари.\n\n"
        f"# HYPERCLAW MULTI-AXIS PLAN – {today}\n\n"
        "META:\n"
        f"  DATE: {today}\n"
        "  ORCHESTRATOR: HYPERCLAW\n"
        "  SOURCE: master_snapshot_latest.json\n\n"
        "HUMAN_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [<под-ос с нисък прогрес>]\n"
        "  OBJECTIVE: <целево подобрение за 24-72h>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <конкретно действие>\n"
        "    - STEP 2: <конкретно действие>\n"
        "  CROSS_AXIS_EFFECTS: <ефект върху PLANET/CIVILIZATION/COSMOS>\n\n"
        "PLANET_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [<под-ос>]\n"
        "  OBJECTIVE: <цел>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <действие>\n"
        "    - STEP 2: <действие>\n"
        "  CROSS_AXIS_EFFECTS: <ефект>\n\n"
        "CIVILIZATION_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [<под-ос>]\n"
        "  OBJECTIVE: <цел>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <действие>\n"
        "    - STEP 2: <действие>\n"
        "  CROSS_AXIS_EFFECTS: <ефект>\n\n"
        "COSMOS_AXIS_FOCUS:\n"
        "  SELECTED_SUBAXES: [LONG_TERM_FUTURE_REVIEW]\n"
        "  OBJECTIVE: <намаляване на екзистенциален риск>\n"
        "  PLAN_STEPS:\n"
        "    - STEP 1: <действие>\n"
        "    - STEP 2: <действие>\n"
        "  CROSS_AXIS_EFFECTS: <ефект>\n\n"
        "GLOBAL_RISKS_AND_CHECKS:\n"
        "  - <риск>: check: <метрика>\n\n"
        "NEXT_REVIEW_SIGNALS:\n"
        "  HUMAN: <индикатор>\n"
        "  PLANET: <индикатор>\n"
        "  CIVILIZATION: <индикатор>\n"
        "  COSMOS: <индикатор>\n\n"
        f"── AGI AXES SPEC ──\n{axes_spec[:1000]}\n\n"
        f"── ТЕКУЩО СЪСТОЯНИЕ ──\n{context}\n\n"
        f"Генерирай plan-{today}.md по горния формат. Само Markdown."
    ).replace("{today}", today)


def main() -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"[HYPERCLAW] started at {_utc_now()}")

    context   = _read_context()
    axes_spec = AXES_SPEC.read_text(encoding="utf-8", errors="ignore") if AXES_SPEC.exists() else ""
    prompt    = _build_prompt(context, axes_spec, today)

    try:
        from core.groq_backend import call_groq
        plan_md = call_groq(prompt, max_tokens=2000)
    except Exception as e:
        print(f"[HYPERCLAW] LLM error: {e}")
        return

    out_path = PLAN_DIR / f"plan-{today}.md"
    out_path.write_text(plan_md, encoding="utf-8")
    print(f"[HYPERCLAW] plan written -> {out_path}")


if __name__ == "__main__":
    main()
