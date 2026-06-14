#!/usr/bin/env python3
"""
agents/core/goal_planner.py
Чете civilization_goal.txt + predictor_memory + auto_levels
→ генерира конкретни реални задачи за self_modifier
→ записва в improvement_proposals.json
"""
import json, pathlib, sys, os
from datetime import datetime, timezone
from core.groq_backend import call_groq

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

GOAL_PATH      = BASE_DIR / "civilization_goal.txt"
LEVELS_PATH    = BASE_DIR / "memory" / "auto_levels.json"
PREDICTOR_PATH = BASE_DIR / "memory" / "predictor_memory.json"
PROPOSALS_PATH = BASE_DIR / "memory" / "improvement_proposals.json"
JOURNAL_PATH   = BASE_DIR / "memory" / "development_journal.json"
SCORE_LOG      = BASE_DIR / "memory" / "goal_score_history.json"

LEVEL_SCORE = {"HIGH": 100, "MEDIUM": 60, "LOW": 20, "UNKNOWN": 40}

AXIS_WEIGHTS = {
    "ENERGY_REVIEW":                  0.20,
    "CLIMATE_ENVIRONMENT_REVIEW":     0.20,
    "CLIMATE_GLOBAL_RISK_REVIEW":     0.20,
    "GOVERNANCE_INSTITUTIONS_REVIEW": 0.15,
    "INEQUALITY_POVERTY_REVIEW":      0.15,
    "ECOSYSTEMS_BIODIVERSITY_REVIEW": 0.10,
    "FOOD_REVIEW":                    0.10,
    "TECHNOLOGY_AI_REVIEW":           0.05,
    "ECONOMY_WORK_REVIEW":            0.05,
}


def compute_goal_score() -> dict:
    try:
        levels = json.loads(LEVELS_PATH.read_text(encoding="utf-8"))
    except:
        return {"score": 0, "breakdown": {}}

    weighted_sum, total_weight = 0.0, 0.0
    breakdown = {}

    for axis, weight in AXIS_WEIGHTS.items():
        data  = levels.get(axis, {})
        level = data.get("level", "UNKNOWN")
        score = LEVEL_SCORE.get(level, 40)
        breakdown[axis] = {"level": level, "score": score}
        weighted_sum += score * weight
        total_weight += weight

    for axis, data in levels.items():
        if axis not in AXIS_WEIGHTS:
            level = data.get("level", "UNKNOWN")
            score = LEVEL_SCORE.get(level, 40)
            w = 0.01
            breakdown[axis] = {"level": level, "score": score}
            weighted_sum += score * w
            total_weight += w

    final = round(weighted_sum / total_weight, 2) if total_weight > 0 else 0
    return {"score": final, "breakdown": breakdown}


def _read(path) -> dict:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except:
        return {}


def _log_score(score_data: dict):
    try:
        try:
            history = json.loads(SCORE_LOG.read_text(encoding="utf-8"))
        except:
            history = []
        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": score_data["score"],
            "source": "goal_planner"
        })
        history = history[-200:]
        SCORE_LOG.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except:
        pass


def _existing_problems() -> set:
    data = _read(PROPOSALS_PATH)
    proposals = data.get("proposals", data) if isinstance(data, dict) else data
    return {p.get("problem", "") for p in proposals if isinstance(p, dict)}


def generate_tasks(goal: str, score_data: dict, predictor: dict, levels: dict) -> list:
    """LLM генерира конкретни задачи спрямо целта и текущото състояние."""

    critical = [a for a, d in score_data["breakdown"].items() if d["level"] == "LOW"]
    medium   = [a for a, d in score_data["breakdown"].items() if d["level"] == "MEDIUM"]
    critical_axes = predictor.get("critical_axes", [])

    prompt = f"""Ти си CORTEX++ goal planner. Задачата ти е да генерираш КОНКРЕТНИ и ИЗПЪЛНИМИ задачи за подобряване на цивилизационните показатели.

ГЛОБАЛНА ЦЕЛ:
{goal[:1000]}

ТЕКУЩО СЪСТОЯНИЕ:
- Goal score: {score_data['score']}/100
- Критични оси (LOW): {critical}
- Средни оси (MEDIUM): {medium[:5]}
- Predictor критични: {critical_axes}
- Среден predictor score: {predictor.get('avg_score', 'N/A')}

НАЛИЧНИ ИНСТРУМЕНТИ В СИСТЕМАТА:
- Четене на JSON файлове от memory/
- Извикване на World Bank API, NOAA API
- Записване на анализи в memory/
- Генериране на доклади в reports/
- Извикване на call_groq() за анализ

ПРАВИЛА:
1. Генерирай точно 3 задачи
2. Всяка задача трябва да е КОНКРЕТНА — не "подобри X" а "напиши модул който чете Y и записва Z"
3. Задачите трябва да използват само наличните инструменти
4. Приоритет към критичните оси
5. Отговори САМО с валиден JSON масив — без текст извън JSON

Формат:
[
  {{
    "component": "ИМЕ_НА_КОМПОНЕНТА",
    "problem": "Конкретен проблем който трябва да се реши",
    "solution": "Конкретно решение — какъв модул да се напише и какво да прави",
    "priority": "HIGH",
    "source": "goal_planner"
  }}
]"""

    try:
        raw = call_groq(prompt, max_tokens=1000)
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]
        raw = raw.strip()
        if "[" in raw:
            raw = raw[raw.index("["):raw.rindex("]")+1]
        tasks = json.loads(raw)
        return tasks if isinstance(tasks, list) else []
    except Exception as e:
        print(f"  [GOAL_PLANNER] LLM грешка: {e}")
        return []


def save_tasks(tasks: list) -> int:
    """Записва задачите в proposals след guard проверка."""
    sys.path.insert(0, str(BASE_DIR))
    from alignment.civilization_guard import evaluate_proposal_alignment

    data = _read(PROPOSALS_PATH)
    proposals = data.get("proposals", []) if isinstance(data, dict) else []
    existing = {p.get("problem", "") for p in proposals}

    added = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("problem", "") in existing:
            print(f"  [SKIP] Вече съществува: {task['problem'][:60]}")
            continue
        result = evaluate_proposal_alignment(task)
        if result["allowed"]:
            proposals.append(task)
            existing.add(task["problem"])
            added += 1
            print(f"  [ADD] ✅ {task['problem'][:70]}")
        else:
            print(f"  [BLOCK] ❌ {result['notes']}")

    if isinstance(data, dict):
        data["proposals"] = proposals
    else:
        data = {"proposals": proposals}

    PROPOSALS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return added


def run():
    print("[GOAL_PLANNER] ════════════════════════════════")
    print("[GOAL_PLANNER] АНАЛИЗ СПРЯМО ЦИВИЛИЗАЦИОННАТА ЦЕЛ")
    print("[GOAL_PLANNER] ════════════════════════════════")

    goal      = GOAL_PATH.read_text(encoding="utf-8") if GOAL_PATH.exists() else ""
    levels    = _read(LEVELS_PATH)
    predictor = _read(PREDICTOR_PATH)

    # Изчисляваме goal score
    score_data = compute_goal_score()
    print(f"  Goal Score: {score_data['score']}/100")

    critical = [a for a, d in score_data["breakdown"].items() if d["level"] == "LOW"]
    print(f"  Критични оси: {len(critical)}")
    for ax in critical:
        print(f"    ⚠️  {ax}")

    _log_score(score_data)

    print()
    print("  [GOAL_PLANNER] Генерирам задачи спрямо целта...")
    tasks = generate_tasks(goal, score_data, predictor, levels)
    print(f"  [GOAL_PLANNER] Генерирани: {len(tasks)} задачи")
    print()

    added = save_tasks(tasks)
    print()
    print(f"[GOAL_PLANNER] Добавени: {added} нови задачи в proposals")
    print(f"[GOAL_PLANNER] Goal Score: {score_data['score']}/100")
    print("[GOAL_PLANNER] Следваща стъпка: python3 -m agents.core.self_modifier")


if __name__ == "__main__":
    run()