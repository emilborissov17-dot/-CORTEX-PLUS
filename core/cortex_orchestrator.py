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

def assess_attention(state):
    """
    Attentional Meta Protocol:
    Решава кои оси изискват внимание и с какъв приоритет.
    """
    internet = state.get("internet", {})
    
    critical = internet.get("critical_axes", [])
    high     = internet.get("high_urgency_axes", internet.get("high_axes", []))
    
    # Изгради контекст за Groq
    ctx = f"КРИТИЧНИ ОСИ: {critical}\nВИСОКИ ОСИ: {high}\n\n"
    try:
        from memory.semantic_memory import query as mem_query
        past = mem_query("критични оси заплахи стратегия", n=5)
        if past:
            ctx += "\nМИНАЛИ РЕШЕНИЯ:\n"
            for m in past:
                ctx += f"[{m.get('date','')}] {m.get('text','')[:150]}\n"
    except Exception:
        pass
    
    # Добави последни новини
    axes_data = internet.get("axes", internet.get("results", {}))
    for axis in (critical + high)[:5]:
        if axis in axes_data:
            summary = axes_data[axis].get("summary", "")
            ctx += f"{axis}: {summary[:200]}\n"
    
    prompt = f"""
Анализирай текущото състояние на CORTEX++ системата.

ДАННИ:
{ctx}

ВИЗИЯ:
{VISION[:500]}

ЗАДАЧА — Attentional Protocol:
1. Кои 3 оси изискват НЕЗАБАВНО внимание и защо?
2. Каква е ОСНОВНАТА заплаха за визията в момента?
3. Каква е ОСНОВНАТА възможност за напредък?
4. Какво трябва да направи CORTEX++ СЕГА?

Отговори като JSON:
{{"priority_axes": ["ос1", "ос2", "ос3"],
  "main_threat": "...",
  "main_opportunity": "...", 
  "immediate_action": "...",
  "reasoning": "..."}}
"""
    try:
        response = call_groq(prompt, max_tokens=1500)
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        return json.loads(response.strip())
    except Exception as e:
        return {
            "priority_axes": critical[:3] or high[:3],
            "main_threat": "Insufficient data",
            "main_opportunity": "Continue monitoring",
            "immediate_action": "Gather more data",
            "reasoning": str(e)
        }

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
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        return json.loads(response.strip())
    except Exception as e:
        print(f"[ORCHESTRATOR] Plan error: {e}"); return {"error": str(e), "plan_24h": [], "key_insight": "Planning failed"}

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
