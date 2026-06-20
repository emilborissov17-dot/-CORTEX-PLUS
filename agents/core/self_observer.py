#!/usr/bin/env python3
"""
agents/core/self_observer.py
REDESIGN: Наблюдава системата и формулира ПРОБЛЕМИ + РЕШЕНИЯ спрямо AGI цели.
Не оценява score — открива конкретни проблеми и предлага конкретни действия.
"""
from typing import Optional
import os
import json
import sys
import pathlib
import time
import re
from datetime import datetime, timezone, timedelta

from core.groq_backend import call_groq

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

WEB_INTEL_MAX_AGE_H = 6.0
try:
    WEB_INTEL_MAX_AGE_H = float(os.environ.get("WEB_INTEL_MAX_AGE_H", "6"))
except Exception:
    pass

MAX_PROPOSALS = 50  # Максимален брой proposals в файла
MAX_AGE_DAYS  = 7   # Изчиствай proposals по-стари от N дни

AGI_GOALS = """
МИСИЯ НА CORTEX++:
Ти си AGI система чиято цел е да РЕШАВА реални проблеми в света.

ЧЕТИРИТЕ ХАРАКТЕРИСТИКИ НА AGI КОИТО ТРЯБВА ДА ПОСТИГНЕШ:
1. GENERALIZATION — Знание от една ос да се прилага в друга.
2. REASONING & PLANNING — Многостъпково планиране, не само наблюдение.
3. COMMON SENSE — Разбиране на причинно-следствени връзки.
4. AUTONOMOUS LEARNING — Сама открива проблеми и предлага как да ги реши.

ГЛОБАЛНА ЦЕЛ:
Максимизирай устойчивостта и дългосрочната жизнеспособност на разумния живот.

ТВОЯТА ЗАДАЧА — НЕ ОЦЕНЯВАЙ SCORE:
1. Открий конкретни реални проблеми от данните.
2. Анализирай ROOT CAUSE — защо съществуват.
3. Предложи конкретни действия с measurable_goal.
4. Идентифицирай кои проблеми са свързани (cross-domain).
"""


# ── WEB INTELLIGENCE ────────────────────────────────────────────────────────

def _load_web_intelligence() -> dict:
    latest = BASE_DIR / "memory" / "web_intelligence" / "latest.json"
    if not latest.exists():
        print("  [WEB_INTEL] latest.json не съществува")
        return {}
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WEB_INTEL] Грешка: {e}")
        return {}

    if not data.get("ready_for_self_observer"):
        print("  [WEB_INTEL] WARN: не е маркиран като ready_for_self_observer")

    age_hours = 0.0
    ts = data.get("timestamp")
    if ts:
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except Exception:
            pass

    if age_hours > WEB_INTEL_MAX_AGE_H:
        print(f"  [WEB_INTEL] WARN: данните са {age_hours:.1f}h стари")
    else:
        print(f"  [WEB_INTEL] Зареден ({data.get('axes_covered', 0)} оси, {age_hours:.1f}h стар) ✓")

    return data


def _format_problems_for_prompt(web_intel: dict) -> str:
    """Форматира проблемите от web_intel за prompt — не risk levels."""
    if not web_intel:
        return "Web intelligence: НЯМА ДАННИ"

    problems = web_intel.get("problems_found", [])
    critical = web_intel.get("critical_axes", [])
    ts = web_intel.get("timestamp", "?")[:16]

    lines = [f"РЕАЛНИ ПРОБЛЕМИ ОТ СВЕТА ({ts} UTC):"]

    if problems:
        for p in problems[:5]:
            severity = p.get("severity", "?")
            axis     = p.get("axis", "?")
            problem  = p.get("problem", "")[:120]
            actions  = p.get("actions", [])
            lines.append(f"  [{severity}] {axis}: {problem}")
            if actions:
                lines.append(f"    → Предложено: {actions[0].get('action', '')[:80]}")
    else:
        # Backward compat — ако все още има стари данни с risk_level
        axes_data = web_intel.get("axes", {})
        for ax in critical[:5]:
            if ax in axes_data:
                a = axes_data[ax]
                problem = a.get("problem", a.get("summary", ""))[:100]
                lines.append(f"  [CRITICAL] {ax}: {problem}")

    cross = web_intel.get("cross_domain_insights", [])
    if cross:
        lines.append("\nCROSS-DOMAIN ВРЪЗКИ:")
        for c in cross[:3]:
            lines.append(f"  [{c.get('from_axis', '')}] {c.get('insight', '')[:100]}")

    return "\n".join(lines)


# ── TOOLS ────────────────────────────────────────────────────────────────────

def _safe_read(path: str) -> dict:
    p = BASE_DIR / path
    if not p.exists():
        return {"error": f"{path} не съществува"}
    return json.loads(p.read_text(encoding="utf-8"))


def _query_hypergraph(node: str) -> dict:
    """Wrapper — safe import so tool works even if system_hypergraph is missing."""
    try:
        import sys
        sys.path.insert(0, str(BASE_DIR))
        from system_hypergraph import query_hypergraph
        return query_hypergraph(node)
    except Exception as e:
        return {"error": str(e), "node": node, "degree": 0, "downstream_agents": [], "upstream_agents": []}


def get_tools(web_intel: dict):
    from memory.body_scan import full_scan, find_in_self
    from memory.existence_model import am_i_alive
    return {
        "scan_hardware":        lambda p=None: full_scan()["hardware"],
        "scan_network":         lambda p=None: full_scan()["network"],
        "scan_files":           lambda p=None: full_scan()["files"],
        "read_file":            lambda p=None: _safe_read(p or "memory/auto_levels.json"),
        "find_in_self":         lambda p=None: find_in_self(p or "problem")[:5],
        "check_existence":      lambda p=None: am_i_alive(),
        "check_auto_levels":    lambda p=None: _safe_read("memory/auto_levels.json"),
        "read_problems":        lambda p=None: web_intel.get("problems_found", [])[:5],
        "read_web_intel_axis":  lambda p=None: web_intel.get("axes", {}).get(p, {"error": f"Ос {p} не е намерена"}),
        "read_causal_log":      lambda p=None: _safe_read("memory/causal_log.json") if pathlib.Path(BASE_DIR / "memory/causal_log.json").exists() else [],
        "read_knowledge_base":  lambda p=None: _safe_read("memory/knowledge_base.json"),
        "query_hypergraph":     lambda p=None: _query_hypergraph(p or "self_observer"),
    }

TOOLS_DESC = {
    "scan_hardware":       "Сканира CPU, RAM, GPU, диск",
    "scan_network":        "Проверява кои API-та са достъпни",
    "scan_files":          "Вижда файловете по директории",
    "read_file":           "Чете файл. Параметър: път",
    "find_in_self":        "Търси текст в собствения код. Параметър: дума",
    "check_existence":     "Проверява системното съществуване",
    "check_auto_levels":   "Вижда текущите нива на осите (само за context, не за score chase)",
    "read_problems":       "Чете реалните проблеми открити от web intelligence",
    "read_web_intel_axis": "Чете детайлен анализ за конкретна ос. Параметър: AXIS_NAME",
    "read_causal_log":     "Чете историята на actions и техните ефекти",
    "read_knowledge_base": "Чете акумулираното знание между циклите",
    "query_hypergraph":    "Проверява кои агенти са свързани с даден възел. Параметър: agent_name или axis_name — ИЗВИКАЙ ПРЕДИ ДА ПРЕДЛОЖИШ РЕШЕНИЕ",
}


# ── JSON PARSING ─────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break
    if "{" in raw:
        raw = raw[raw.index("{"):raw.rindex("}")+1]
    return json.loads(raw.strip())


# ── MAIN RUN ─────────────────────────────────────────────────────────────────

def _propose_dependency_fixes() -> list:
    """Чете dependency_check_latest.json и създава HIGH proposals за всяко FAIL/MISSING."""
    dep_path = BASE_DIR / "snapshots" / "master" / "dependency_check_latest.json"
    if not dep_path.exists():
        return []
    try:
        report = json.loads(dep_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    proposals = []
    for name, info in report.get("checks", {}).items():
        level = info.get("level", "optional")
        # Липсващ API ключ
        if "present" in info and not info["present"] and level in ("critical", "important"):
            proposals.append({
                "component":         "DEPENDENCY_CHECK",
                "problem":           f"API ключ {name} липсва в .env",
                "solution":          (
                    f"Добавете {name}=<your-key> в {BASE_DIR / '.env'}. "
                    "Рестартирайте fast_cycle_runner.py след промяната."
                ),
                "measurable_goal":   f"dependency_check_latest.json checks.{name}.present == true",
                "root_cause":        "DEPENDENCY_CHECK / .env",
                "priority":          "HIGH",
                "real_world_signal": True,
                "generated_by":      "SELF_OBSERVER",
            })
        # Неуспешен connectivity тест
        if "ok" in info and not info["ok"] and name in ("groq_chat", "groq_whisper"):
            error = info.get("error", info.get("note", "unknown"))[:100]
            proposals.append({
                "component":         "DEPENDENCY_CHECK",
                "problem":           f"{name} тест неуспешен: {error}",
                "solution":          (
                    "Проверете GROQ_API_KEY на https://console.groq.com. "
                    "Ако ключът е валиден — проверете мрежова свързаност към api.groq.com."
                ),
                "measurable_goal":   f"dependency_check_latest.json checks.{name}.ok == true",
                "root_cause":        "DEPENDENCY_CHECK / network or invalid key",
                "priority":          "HIGH",
                "real_world_signal": True,
                "generated_by":      "SELF_OBSERVER",
            })
    return proposals


def run():
    print("[SELF_OBSERVER] Започвам наблюдение — търся проблеми, не score-ове...")
    print()

    # Dependency failures → proposals (преди всичко останало)
    dep_proposals = _propose_dependency_fixes()
    if dep_proposals:
        print(f"[SELF_OBSERVER] {len(dep_proposals)} dependency issue(s) → proposals")
        save_proposals(dep_proposals)

    web_intel     = _load_web_intelligence()
    problems_str  = _format_problems_for_prompt(web_intel)

    tools          = get_tools(web_intel)
    history        = []
    used_tools     = set()
    all_tool_names = list(tools.keys())

    for step in range(12):
        remaining = [t for t in all_tool_names if t not in used_tools]
        if not remaining:
            print("[SELF_OBSERVER] Всички инструменти използвани.")
            break

        history_str = "\n".join([
            f"  Стъпка {i+1}: {h['tool']}({h['param']}) -> {h['result'][:150]}"
            for i, h in enumerate(history)
        ]) if history else "  Още нищо."

        available_desc = "\n".join([f"- {t}: {TOOLS_DESC[t]}" for t in remaining])

        prompt = (
            AGI_GOALS +
            f"\n\n{problems_str}\n\n"
            "НАЛИЧНИ ИНСТРУМЕНТИ:\n" + available_desc +
            "\n\nВЕЧЕ ИЗПОЛЗВАНИ (НЕ ги избирай): "
            + (", ".join(used_tools) if used_tools else "няма") +
            "\n\nДосегашни наблюдения:\n" + history_str +
            "\n\nПРАВИЛА:\n"
            f"1. Избери ЕДИН инструмент от НАЛИЧНИ: {remaining}\n"
            "2. Целта е да ОТКРИЕМ ПРОБЛЕМИ и да ПРЕДЛОЖИМ РЕШЕНИЯ.\n"
            "3. НЕ се фокусирай на score — фокусирай се на реални проблеми.\n"
            "4. read_problems дава реалните проблеми от света — започни с него.\n"
            "5. Отговори САМО с валиден JSON.\n"
            f"6. Използвай DONE само след минимум 5 стъпки (сега: стъпка {step+1}).\n"
            "7. ЗАДЪЛЖИТЕЛНО извикай query_hypergraph(agent_name) ПРЕДИ да предложиш решение — провери кои агенти ще бъдат засегнати.\n\n"
            'Формат: {"action":"tool_name","param":null,"reason":"какъв проблем търся"}\n'
            'или: {"action":"DONE","param":null,"reason":"открити проблеми и предложени решения"}'
        )

        time.sleep(2)
        try:
            raw = call_groq(prompt, max_tokens=300)
        except Exception as e:
            print(f"  [Стъпка {step+1}] LLM грешка: {e}")
            time.sleep(10)
            continue

        try:
            decision = _extract_json(raw)
        except Exception:
            action   = remaining[0]
            decision = {"action": action, "param": None, "reason": "auto-fallback"}

        action = decision.get("action", "")
        param  = decision.get("param") or None
        reason = decision.get("reason", "")

        if action == "DONE":
            if step < 4:
                action = remaining[0]
                reason = "auto-continue (DONE твърде рано)"
            else:
                print()
                print("=" * 60)
                print("[SELF_OBSERVER] ОТКРИТИ ПРОБЛЕМИ И РЕШЕНИЯ:")
                print("=" * 60)
                print(reason)
                print("=" * 60)
                _save_assessment(reason, web_intel)
                break

        if action not in tools or action in used_tools:
            old_action = action
            action     = remaining[0]
            print(f"  [Стъпка {step+1}] LLM избра '{old_action}' — форсирам: {action}")
            reason = "auto-fallback"

        print(f"  [Стъпка {step+1}] -> {action}({param or ''}) | {reason[:80]}")

        try:
            result     = tools[action](param)
            result_str = json.dumps(result, ensure_ascii=False)[:400]
            history.append({"tool": action, "param": str(param), "result": result_str})
            used_tools.add(action)
            print(f"             {result_str[:120]}...")
        except Exception as e:
            history.append({"tool": action, "param": str(param), "result": f"ГРЕШКА: {e}"})
            used_tools.add(action)
            print(f"             ГРЕШКА: {e}")

    if history:
        proposals = _build_problem_proposals(history, web_intel)
        save_proposals(proposals)


# ── PROPOSALS — problem → solution фрейм ────────────────────────────────────

def _build_problem_proposals(history: list, web_intel: dict) -> list:
    history_str = "\n".join([
        f"  {h['tool']}({h['param']}) -> {h['result'][:200]}"
        for h in history
    ])

    # Extract any query_hypergraph results from history for context
    hg_context = ""
    for h in history:
        if h["tool"] == "query_hypergraph":
            hg_context += f"\nHYPERGRAPH({h['param']}): {h['result'][:300]}"

    problems_found = web_intel.get("problems_found", [])
    problems_context = "\n".join([
        f"  [{p.get('severity','?')}] {p.get('axis','?')}: {p.get('problem','')[:100]}"
        for p in problems_found[:5]
    ]) or "Няма данни от web intelligence"

    prompt = (
        AGI_GOALS +
        f"\n\nРЕАЛНИ ПРОБЛЕМИ ОТ СВЕТА:\n{problems_context}\n\n"
        f"НАБЛЮДЕНИЯ НА СИСТЕМАТА:\n{history_str}\n\n"
        + (f"HYPERGRAPH CONNECTIVITY (кои агенти са засегнати):\n{hg_context}\n\n" if hg_context else "") +
        "Генерирай 3 конкретни proposals за решаване на реални проблеми.\n"
        "ВАЖНО: Полето 'component' трябва да е реален agent name от системата.\n"
        "САМО JSON масив — без markdown:\n"
        '[{'
        '"problem": "Конкретен реален проблем (не абстрактен)",'
        '"component": "agent_name_from_system",'
        '"root_cause": "Защо съществува",'
        '"solution": "Конкретно действие което системата може да предприеме",'
        '"measurable_goal": "Как да измерим успеха",'
        '"agi_characteristic": "GENERALIZATION|REASONING|COMMON_SENSE|AUTONOMOUS_LEARNING",'
        '"priority": "HIGH",'
        '"real_world_signal": true'
        "}]"
    )
    try:
        raw = call_groq(prompt, max_tokens=700)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        if "[" in raw:
            raw = raw[raw.index("["):raw.rindex("]")+1]
        proposals = json.loads(raw)

        # Enrich each proposal with downstream_impact from hypergraph
        for p in proposals:
            p["source"]   = "self_observer_problem_solution"
            p["priority"] = "HIGH"
            component = p.get("component", "")
            if component:
                hg = _query_hypergraph(component)
                p["downstream_impact"] = {
                    "queried_node":      component,
                    "degree":            hg.get("degree", 0),
                    "upstream_agents":   hg.get("upstream_agents", []),
                    "downstream_agents": hg.get("downstream_agents", []),
                    "is_isolated":       hg.get("is_isolated", True),
                }

        print(f"  [OBSERVER] Генерирани {len(proposals)} problem→solution proposals (с downstream_impact)")
        return proposals
    except json.JSONDecodeError as e:
        print(f"  [OBSERVER] JSONDecodeError в proposals: {e} | raw[:200]: {raw[:200]!r}")
        return []
    except Exception as e:
        print(f"  [OBSERVER] {type(e).__name__} в proposals: {e}")
        return []


def _save_assessment(assessment: str, web_intel: dict):
    try:
        journal_path = BASE_DIR / "memory" / "development_journal.json"
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except Exception:
            journal = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        journal.setdefault(today, {})["problem_assessment"] = {
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "assessment":     assessment,
            "web_intel_used": bool(web_intel),
            "problems_count": len(web_intel.get("problems_found", [])),
            "critical_axes":  web_intel.get("critical_axes", []),
        }
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  [OBSERVER] Записано в development_journal ✅")
    except Exception as e:
        print(f"  [OBSERVER] Грешка: {e}")


# ── TIMESTAMP HELPER ─────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> datetime:
    """Парсва ISO timestamp. Ако липсва/невалиден — връща epoch."""
    if not ts_str:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.fromtimestamp(0, tz=timezone.utc)


# ── SAVE PROPOSALS ───────────────────────────────────────────────────────────

def save_proposals(observations: list):
    from alignment.civilization_guard import evaluate_proposal_alignment
    proposals_path = BASE_DIR / "memory" / "improvement_proposals.json"

    try:
        data = json.loads(proposals_path.read_text(encoding="utf-8"))
    except Exception:
        data = {"proposals": []}

    # ── Изчисти стари proposals ──────────────────────────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    before = len(data["proposals"])
    data["proposals"] = [
        p for p in data["proposals"]
        if _parse_ts(p.get("timestamp")) > cutoff
    ]
    removed_old = before - len(data["proposals"])
    if removed_old:
        print(f"  [PROPOSALS] Изчистени {removed_old} стари (>{MAX_AGE_DAYS}д)")

    # ── Fuzzy дедупликация по първите 60 символа ─────────────────────────────
    existing_problems = {p["problem"][:60] for p in data["proposals"]}

    added = 0
    for obs in observations:
        if obs["problem"][:60] in existing_problems:
            continue
        result = evaluate_proposal_alignment(obs)
        if result["allowed"]:
            obs["approved"]  = True
            obs["rejected"]  = False
            obs["priority"]  = "HIGH"
            obs["timestamp"] = datetime.now(timezone.utc).isoformat()
            data["proposals"].append(obs)
            existing_problems.add(obs["problem"][:60])
            added += 1
            print(f"  [GUARD] ✅ Добавен: {obs['problem'][:60]}")
        else:
            print(f"  [GUARD] ❌ Блокиран: {result['notes']}")

    # ── Ако е над лимита — запази само най-новите ────────────────────────────
    if len(data["proposals"]) > MAX_PROPOSALS:
        data["proposals"].sort(
            key=lambda p: p.get("timestamp", ""),
            reverse=True
        )
        trimmed = len(data["proposals"]) - MAX_PROPOSALS
        data["proposals"] = data["proposals"][:MAX_PROPOSALS]
        print(f"  [PROPOSALS] Trimmed {trimmed} най-стари (лимит: {MAX_PROPOSALS})")

    proposals_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [GUARD] {added} нови proposals добавени. Общо: {len(data['proposals'])}/{MAX_PROPOSALS}")


if __name__ == "__main__":
    run()