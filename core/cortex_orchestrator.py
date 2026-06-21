#!/usr/bin/env python3
"""
CORTEX++ Cognitive Orchestrator
Координира всички агенти и когнитивни процеси към общата цел.
Вдъхновен от HyperClaw / Attentional Meta Protocol (Ben Goertzel)
"""
import json
import sys
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.groq_backend import call_groq

def _read_file(path, default=""):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default

VISION = _read_file(BASE / "civilization_vision.txt", "Sustainable civilization for all.")
GOAL   = _read_file(BASE / "civilization_goal.txt",   "AGI in transparent service of humanity.")

def _utc_now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def load_latest_intelligence():
    """Зарежда последните данни от всички агенти."""
    state = {}
    
    # Internet intelligence
    news_file = BASE / "news" / "news_latest.json"
    if news_file.exists():
        state["internet"] = json.loads(news_file.read_text(encoding="utf-8"))
    
    # Pulse
    pulse_file = BASE / "memory" / "pulse_latest.json"
    if pulse_file.exists():
        state["pulse"] = json.loads(pulse_file.read_text(encoding="utf-8"))
    
    # Latest session
    today = datetime.utcnow().strftime("%Y-%m-%d")
    session_file = BASE / "memory" / f"session_{today}.json"
    if session_file.exists():
        state["session"] = json.loads(session_file.read_text(encoding="utf-8"))
    
    # Latest snapshots
    snapshots_dir = BASE / "snapshots"
    if snapshots_dir.exists():
        snaps = sorted(snapshots_dir.glob("*.json"))[-3:]
        state["recent_snapshots"] = [json.loads(s.read_text()) for s in snaps]
    
    return state

def _rule_based_attention(state: dict) -> dict:
    """
    Derive priority axes directly from snapshot data — no LLM needed.
    Rules: xrisk_score > 0.6, progress_pct < 20, trend DETERIORATING.
    """
    scored = []
    for snap in state.get("snapshots", {}).values():
        if not isinstance(snap, dict):
            continue
        axis  = snap.get("axis", "")
        xrisk = float(snap.get("xrisk_score") or 0)
        prog  = float(snap.get("progress_pct") or snap.get("overall_progress_pct") or 50)
        trend = snap.get("trend", snap.get("current_level", "STABLE"))
        score = 0
        if xrisk > 0.6:
            score += 3
        if xrisk > 0.4:
            score += 1
        if prog < 20:
            score += 3
        if prog < 40:
            score += 1
        if "DETERIOR" in str(trend).upper():
            score += 2
        if score > 0:
            scored.append((score, axis, xrisk, prog))

    scored.sort(reverse=True)
    priority_axes = [a for _, a, _, _ in scored[:3]]

    # Highest xrisk = main threat
    by_xrisk = sorted(
        ((float(s.get("xrisk_score") or 0), s.get("axis", ""))
         for s in state.get("snapshots", {}).values() if isinstance(s, dict)),
        reverse=True,
    )
    main_threat = (
        f"{by_xrisk[0][1]} (xrisk={by_xrisk[0][0]:.2f})" if by_xrisk else "unknown"
    )

    # Highest progress + positive trend = main opportunity
    by_prog = sorted(
        ((float(s.get("progress_pct") or s.get("overall_progress_pct") or 0),
          s.get("axis", ""))
         for s in state.get("snapshots", {}).values() if isinstance(s, dict)),
        reverse=True,
    )
    main_opportunity = by_prog[0][1] if by_prog else "unknown"

    action = (
        f"Focus on {priority_axes[0]}" if priority_axes else "Collect more real data"
    )

    return {
        "priority_axes":    priority_axes,
        "main_threat":      main_threat,
        "main_opportunity": main_opportunity,
        "immediate_action": action,
        "reasoning":        "Rule-based AMP (xrisk + progress + trend)",
        "method":           "rule-based",
    }


def assess_attention(state):
    """
    Attentional Meta Protocol.
    Step 1: rule-based priority from snapshot metrics (always works, no LLM).
    Step 2: LLM narrative enrichment (best-effort, skipped on rate limit).
    """
    # Load snapshots into state if not already there
    if "snapshots" not in state:
        snap_dir = BASE / "snapshots"
        state["snapshots"] = {}
        if snap_dir.exists():
            for jf in snap_dir.rglob("*_snapshot_latest.json"):
                try:
                    d = json.loads(jf.read_text(encoding="utf-8"))
                    state["snapshots"][d.get("axis", jf.stem)] = d
                except Exception:
                    pass

    base = _rule_based_attention(state)

    # Best-effort LLM enrichment — adds narrative context if LLM is available
    internet  = state.get("internet", {})
    axes_data = internet.get("axes", internet.get("results", {}))
    ctx = (
        f"PRIORITY AXES (rule-based): {base['priority_axes']}\n"
        f"MAIN THREAT: {base['main_threat']}\n"
        f"OPPORTUNITY: {base['main_opportunity']}\n\n"
    )
    for axis in base["priority_axes"]:
        if axis in axes_data:
            ctx += f"{axis}: {axes_data[axis].get('summary','')[:200]}\n"

    prompt = (
        f"You are CORTEX++ Attentional Meta Protocol.\n\n"
        f"Pre-computed priorities from snapshot data:\n{ctx}\n"
        f"VISION:\n{VISION[:400]}\n\n"
        "Enrich the analysis: why are these axes critical? What is the key threat "
        "and opportunity? Return JSON only:\n"
        '{"priority_axes": [...], "main_threat": "...", '
        '"main_opportunity": "...", "immediate_action": "...", "reasoning": "..."}'
    )
    try:
        response = call_groq(prompt, max_tokens=600)
        if 'done thinking.' in response:
            response = response.split('done thinking.')[-1].strip()
        if '</think>' in response:
            response = response.split('</think>')[-1].strip()
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        enriched = json.loads(response.strip())
        # Keep rule-based priority_axes if LLM returns empty list
        if not enriched.get("priority_axes"):
            enriched["priority_axes"] = base["priority_axes"]
        enriched["method"] = "llm-enriched"
        return enriched
    except Exception:
        # LLM unavailable — rule-based result is still useful
        return base

def generate_strategic_plan(attention, state):
    """
    На база attentional assessment — генерира конкретен стратегически план.
    """
    prompt = f"""
Ти си CORTEX++ стратегически планировчик.

ТЕКУЩО ВНИМАНИЕ:
- Приоритетни оси: {attention.get('priority_axes')}
- Основна заплаха: {attention.get('main_threat')}
- Основна възможност: {attention.get('main_opportunity')}
- Препоръчано действие: {attention.get('immediate_action')}

ЦЕЛ:
{GOAL[:400]}

ЗАДАЧА:
Създай конкретен план за следващите 24 часа.
За всяка приоритетна ос — какво конкретно трябва да се направи?
Кои са реалните лостове за промяна?
Кои организации, хора, движения са съюзници?

Отговори като JSON:
{{"plan_24h": [{{"axis": "...", "action": "...", "lever": "...", "allies": ["..."]}}],
  "key_insight": "...",
  "civilization_impact": "POSITIVE|NEUTRAL|NEGATIVE",
  "next_evolution_step": "..."}}
"""
    try:
        response = call_groq(prompt, max_tokens=1500)
        if 'done thinking.' in response:
            response = response.split('done thinking.')[-1].strip()
        if '</think>' in response:
            response = response.split('</think>')[-1].strip()
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        return json.loads(response.strip())
    except Exception as e:
        # Minimal rule-based plan when LLM unavailable
        axes = attention.get("priority_axes", [])
        return {
            "plan_24h": [
                {"axis": ax, "action": f"Collect real metrics for {ax}",
                 "lever": "data_providers", "allies": []}
                for ax in axes
            ],
            "key_insight": f"Focus on {axes[0] if axes else 'data collection'}",
            "civilization_impact": "NEUTRAL",
            "next_evolution_step": "Improve real data coverage for priority axes",
            "method": "rule-based-fallback",
        }

def save_orchestration_result(attention, plan, state={}):
    """Записва резултата от оркестрацията."""
    result = {
        "timestamp": _utc_now(),
        "attention": attention,
        "strategic_plan": plan
    }
    
    out_file = BASE / "memory" / "orchestration_latest.json"
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Също запис в ChromaDB
    try:
        from memory.semantic_memory import remember
        remember(
            text=f"Orchestration: {attention.get('main_threat')} | Action: {attention.get('immediate_action')} | Plan: {plan.get('key_insight','')}",
            axis="ORCHESTRATION",
            source="cortex_orchestrator",
        )
    except Exception:
        pass
    
    return result

def run():
    print("\n🧠 CORTEX++ COGNITIVE ORCHESTRATOR")
    print("=" * 50)
    
    # 1. Зареди данни
    print("📡 Зареждам intelligence...")
    state = load_latest_intelligence()
    
    internet = state.get("internet", {})
    critical = internet.get("critical_axes", [])
    high = internet.get("high_axes", [])
    print(f"  Критични: {critical}")
    print(f"  Високи: {high}")
    
    # 2. Attentional Assessment
    print("\n🎯 Attentional Protocol — оценявам приоритети...")
    attention = assess_attention(state)
    print(f"  Приоритетни оси: {attention.get('priority_axes')}")
    print(f"  Основна заплаха: {attention.get('main_threat')}")
    print(f"  Основна възможност: {attention.get('main_opportunity')}")
    print(f"  Незабавно действие: {attention.get('immediate_action')}")
    
    # 3. Стратегически план
    print("\n📋 Генерирам стратегически план...")
    plan = generate_strategic_plan(attention, state)
    print(f"  Ключово прозрение: {plan.get('key_insight','')}")
    print(f"  Цивилизационен импакт: {plan.get('civilization_impact','')}")
    print(f"  Следваща еволюция: {plan.get('next_evolution_step','')}")
    
    for item in plan.get("plan_24h", []):
        print(f"\n  [{item.get('axis')}]")
        print(f"    Действие: {item.get('action','')}")
        print(f"    Лост: {item.get('lever','')}")
        print(f"    Съюзници: {item.get('allies',[])}")
    
    # 4. Запис
    # Предсказания директно тук
    try:
        from memory.prediction_tracker import make_prediction, verify_and_learn
        axes_data = state.get("internet", {}).get("results", {})
        verify_and_learn(axes_data)
        for ax in attention.get("priority_axes", [])[:3]:
            if ax in axes_data:
                make_prediction(ax, "ситуацията ще продължи", axes_data[ax].get("urgency","LOW"))
        print(f"[FEEDBACK] Предсказания записани")
    except Exception as e:
        print(f"[FEEDBACK] Error: {e}")
    result = save_orchestration_result(attention, plan, state)
    print("\n✅ Оркестрацията записана!")
    
    return result

if __name__ == "__main__":
    run()
