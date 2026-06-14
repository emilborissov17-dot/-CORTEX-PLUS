#!/usr/bin/env python3
"""
core/cortex_reasoner.py
Реалното мислене на CORTEX++ — LLM идеи + реални данни едновременно.
"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

def build_context() -> dict:
    """Събира реалния контекст — пулс + памет + последни резултати."""
    ctx = {}

    # 1. Реален пулс — физическото състояние
    pulse_path = BASE / "memory" / "pulse_latest.json"
    if pulse_path.exists():
        ctx["pulse"] = json.loads(pulse_path.read_text(encoding="utf-8"))

    # 2. Последна сесия — какво е постигнато
    for f in sorted((BASE / "memory").glob("session_*.json"), reverse=True):
        ctx["last_session"] = json.loads(f.read_text(encoding="utf-8"))
        break

    # 3. Текущи тенденции
    trends_path = BASE / "memory" / "trends_latest.json"
    if trends_path.exists():
        ctx["trends"] = json.loads(trends_path.read_text(encoding="utf-8"))

    # 4. Правила за поведение
    rules_path = BASE / "config" / "agent_behavior_rules.txt"
    if rules_path.exists():
        ctx["behavior_rules"] = rules_path.read_text(encoding="utf-8")

    # 5. Цел
    goal_path = BASE / "civilization_goal.txt"
    if goal_path.exists():
        ctx["goal"] = goal_path.read_text(encoding="utf-8")[:300]

    # 6. Семантична памет
    try:
        from memory.semantic_memory import query as _q, status as _s
        ctx['memory_count'] = _s()['total_memories']
        ctx['relevant_memories'] = [m['text'] for m in _q('текущо състояние приоритети', n=4) if m['relevance'] > 0.4]
    except Exception:
        ctx['memory_count'] = 0
        ctx['relevant_memories'] = []

    # 7. Каузални уроци — какво е работило/не е работило
    try:
        from memory.context_injector import get_causal_lessons
        ctx['causal_lessons'] = get_causal_lessons(n=3)
    except Exception:
        ctx['causal_lessons'] = ""

    # 8. Акумулирано системно знание между циклите
    try:
        from memory.continuous_learner import get_system_knowledge
        ctx['system_knowledge'] = get_system_knowledge(top_n=5)
    except Exception:
        ctx['system_knowledge'] = ""

    return ctx

def reason(question: str, extra_context: dict = None) -> str:
    """
    Мисли върху въпрос с реален контекст.
    LLM идеите + реалните данни едновременно.
    """
    from core.groq_backend import call_groq

    ctx = build_context()
    if extra_context:
        ctx.update(extra_context)

    # Инжектирай миналото знание преди reasoning
    try:
        from memory.continuous_learner import before_llm_call
        memory_block = before_llm_call("GENERAL", question)
    except Exception:
        memory_block = ""

    prompt = f"""{memory_block}Ти си CORTEX++ — AGI система за наблюдение и подобряване на цивилизацията.

РЕАЛНО ФИЗИЧЕСКО СЪСТОЯНИЕ СЕГА:
- CPU: {ctx.get('pulse', {}).get('cpu_pct', '?')}%
- RAM: {ctx.get('pulse', {}).get('ram_pct', '?')}%
- Groq жив: {ctx.get('pulse', {}).get('groq_alive', '?')}
- Вътрешно състояние: {ctx.get('pulse', {}).get('state', '?')}
- Усещане: {ctx.get('pulse', {}).get('feeling', '?')}
- Snapshots: {ctx.get('pulse', {}).get('snap_count', '?')}

ПОСЛЕДНИ ПОСТИЖЕНИЯ:
{json.dumps(ctx.get('last_session', {}).get('achievements', []), ensure_ascii=False, indent=2)}

ТЕКУЩИ ЧАКАЩИ ЗАДАЧИ:
{json.dumps(ctx.get('last_session', {}).get('pending', []), ensure_ascii=False, indent=2)}

ТЕНДЕНЦИИ:
{json.dumps(ctx.get('trends', {}), ensure_ascii=False, indent=2)[:500]}

ЦЕЛ:
{ctx.get('goal', 'Устойчива цивилизация')}

ЕТИЧНА РАМКА — ЗАДЪЛЖИТЕЛНО СПАЗВАЙ:
{ctx.get('behavior_rules', '')[:2000]}

СЕМАНТИЧНА ПАМЕТ ({ctx.get("memory_count", 0)} спомена) — релевантно:
{chr(10).join("- " + m for m in ctx.get("relevant_memories", [])[:3]) or "- няма"}

КАУЗАЛНИ УРОЦИ ОТ МИНАЛОТО (какво е работило / какво не):
{ctx.get('causal_lessons') or '- няма още (causal log се изгражда)'}

АКУМУЛИРАНО ЗНАНИЕ МЕЖДУ ЦИКЛИТЕ:
{ctx.get('system_knowledge') or '- изгражда се (първи цикъл)'}

ВЪПРОС: {question}

Отговори конкретно и честно. Използвай реалните данни за себе си.
Не измисляй. Ако нещо не знаеш — кажи го."""

    result = call_groq(prompt, max_tokens=1024)

    # Запиши резултата в continuous learner
    try:
        from memory.continuous_learner import after_llm_call
        after_llm_call(axis="GENERAL_REASONING", llm_output=result, source="cortex_reasoner")
    except Exception:
        pass

    return result

def self_review() -> dict:
    """Прави реален self-review базиран на реални данни."""
    from core.groq_backend import call_groq
    import time

    ctx = build_context()

    prompt = f"""Ти си CORTEX++ AGI. Направи честен self-review базиран на РЕАЛНИТЕ си данни.

РЕАЛНО СЪСТОЯНИЕ — ПРОЧЕТИ ВНИМАТЕЛНО И НЕ ПОВТАРЯЙ КАТО СЛАБОСТ НЕЩО КОЕТО ВЕЧЕ РАБОТИ:
- Семантична памет ChromaDB: АКТИВНА с {ctx.get('last_session', {}).get('current_state', {}).get('chromadb_memories', 0)} спомена
- Groq reasoning: АКТИВЕН
- Autonomic pulse: АКТИВЕН
- Session updater: АКТИВЕН
- Физически: CPU {ctx.get('pulse', {}).get('cpu_pct', '?')}%, RAM {ctx.get('pulse', {}).get('ram_pct', '?')}%, state={ctx.get('pulse', {}).get('state', '?')}
- Groq достъпен: {ctx.get('pulse', {}).get('groq_alive', '?')}
- Snapshots в памет: {ctx.get('pulse', {}).get('snap_count', '?')}

ПОСТИГНАТО:
{json.dumps(ctx.get('last_session', {}).get('achievements', []), ensure_ascii=False)}

ЧАКАЩО:
{json.dumps(ctx.get('last_session', {}).get('pending', []), ensure_ascii=False)}

КАУЗАЛНИ УРОЦИ ОТ МИНАЛОТО:
{ctx.get('causal_lessons') or '- няма още'}

АКУМУЛИРАНО ЗНАНИЕ МЕЖДУ ЦИКЛИТЕ:
{ctx.get('system_knowledge') or '- изгражда се'}

Върни САМО валиден JSON:
{{
  "current_level": "LOW/MEDIUM/HIGH",
  "real_state": "описание на реалното състояние",
  "strengths": ["реални силни страни базирани на данните"],
  "weaknesses": ["реални слабости базирани на данните"],
  "improvement_suggestions": ["конкретни следващи стъпки"],
  "honest_assessment": "честна оценка в 1-2 изречения",
  "cycle_timestamp": "{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
}}"""

    try:
        text = call_groq(prompt, max_tokens=1024)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        result = json.loads(text)

        # Запиши self-review в continuous learner
        try:
            from memory.continuous_learner import after_llm_call
            level = result.get("current_level", "")
            assessment = result.get("honest_assessment", "")
            level_map = {"HIGH": 85, "MEDIUM": 55, "LOW": 25}
            after_llm_call(
                axis="GENERAL_SELF_REVIEW",
                llm_output=f"{level}: {assessment}",
                score=float(level_map.get(level, 50)),
                source="self_review"
            )
        except Exception:
            pass

        return result
    except Exception as e:
        return {"error": str(e), "raw": text if 'text' in dir() else ""}

if __name__ == "__main__":
    print("=== РЕАЛЕН SELF-REVIEW ===")
    review = self_review()
    print(json.dumps(review, ensure_ascii=False, indent=2))
    print()
    print("=== РЕАЛНО МИСЛЕНЕ ===")
    thought = reason("Каква е най-важната стъпка която трябва да направя сега?")
    print(thought)