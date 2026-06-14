#!/usr/bin/env python3
"""
memory/continuous_learner.py
REDESIGN: Акумулира ПРОБЛЕМИ, РЕШЕНИЯ и РЕЗУЛТАТИ между циклите.
НЕ акумулира score trends — акумулира "какво работи / какво не работи".
risk_level се запазва САМО за backward compat.
"""
import json, pathlib, os, hashlib
from datetime import datetime, timezone

BASE_DIR       = pathlib.Path(os.environ.get("CORTEX_BASE", pathlib.Path(__file__).resolve().parents[1])).resolve()
KNOWLEDGE_BASE = BASE_DIR / "memory" / "knowledge_base.json"
CYCLE_LOG      = BASE_DIR / "memory" / "cycle_knowledge_log.json"
PROBLEM_DB     = BASE_DIR / "memory" / "problem_solution_db.json"

def _now():   return datetime.now(timezone.utc).isoformat()
def _today(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _load(path, default):
    try:
        t = path.read_text(encoding="utf-8").strip()
        return json.loads(t) if t else default
    except Exception:
        return default

def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 1. ПРЕДИ LLM CALL ────────────────────────────────────────────────────────

def before_llm_call(axis: str, question: str = "") -> str:
    """
    Инжектира акумулираното знание в LLM prompt ПРЕДИ call.
    REDESIGN: Включва проблеми, решения и резултати — не само score trends.
    """
    parts = []

    # 1. Семантична памет
    try:
        from memory.semantic_memory import query
        q        = question or axis
        memories = query(q, n=5, axis=axis) or query(q, n=3)
        relevant = [m for m in memories if m.get("relevance", 0) > 0.35]
        if relevant:
            lines = [f"ПАМЕТ ОТ ПРЕДИШНИ ЦИКЛИ [{axis}]:"]
            for m in relevant[:4]:
                lines.append(f"  [{m.get('date', '?')}] {m['text'][:180]}")
            parts.append("\n".join(lines))
    except Exception:
        pass

    # 2. Каузални уроци — какво е работило/не е работило
    try:
        from memory.context_injector import get_causal_history
        history = get_causal_history(axis=axis, n=5) or get_causal_history(n=3)
        if history:
            lines = ["КАУЗАЛНИ УРОЦИ (action → ефект):"]
            for e in history[-3:]:
                verdict  = e.get("verdict", "NEUTRAL")
                action   = e.get("action", "")[:80]
                effect   = e.get("effect", "")[:80]
                delta    = e.get("delta")
                delta_s  = f" Δ{delta:+.1f}" if delta is not None else ""
                lines.append(f"  [{verdict}{delta_s}] {action} → {effect}")
            parts.append("\n".join(lines))
    except Exception:
        pass

    # 3. Problem-solution база — какво сме опитвали за този проблем
    try:
        pdb    = _load(PROBLEM_DB, {})
        axis_p = pdb.get(axis, {})
        if axis_p.get("attempted_solutions"):
            lines = [f"ОПИТАНИ РЕШЕНИЯ ЗА {axis}:"]
            for sol in axis_p["attempted_solutions"][-3:]:
                status = sol.get("status", "UNKNOWN")
                action = sol.get("action", "")[:80]
                result = sol.get("result", "")[:80]
                lines.append(f"  [{status}] {action} → {result}")
            parts.append("\n".join(lines))
        if axis_p.get("known_root_causes"):
            lines = [f"ИЗВЕСТНИ ROOT CAUSES ЗА {axis}:"]
            for rc in axis_p["known_root_causes"][-2:]:
                lines.append(f"  • {rc[:120]}")
            parts.append("\n".join(lines))
    except Exception:
        pass

    # 4. Тренд от knowledge base (backward compat)
    try:
        kb             = _load(KNOWLEDGE_BASE, {})
        axis_knowledge = kb.get(axis, {})
        cycle_count    = axis_knowledge.get("cycle_count", 0)
        if axis_knowledge.get("key_insights"):
            lines = [f"АКУМУЛИРАНО ЗНАНИЕ [{axis}] (от {cycle_count} цикъла):"]
            for ins in axis_knowledge.get("key_insights", [])[-2:]:
                lines.append(f"  Инсайт: {ins[:120]}")
            parts.append("\n".join(lines))
    except Exception:
        pass

    if not parts:
        return ""

    sep = "=" * 50
    return (
        f"{sep}\nНАТРУПАНО ЗНАНИЕ — ИЗПОЛЗВАЙ ЗА ПО-ДОБЪР АНАЛИЗ:\n{sep}\n"
        + "\n\n".join(parts)
        + f"\n{sep}\n"
    )


# ── 2. СЛЕД LLM CALL ─────────────────────────────────────────────────────────

def after_llm_call(axis: str, llm_output: str, score: float = None,
                   source: str = "agent") -> None:
    if not llm_output or len(llm_output) < 20:
        return

    kb = _load(KNOWLEDGE_BASE, {})
    if axis not in kb:
        kb[axis] = {"cycle_count": 0, "key_insights": [], "scores": [], "trend": ""}

    entry = kb[axis]
    entry["cycle_count"] = entry.get("cycle_count", 0) + 1
    entry["last_updated"] = _today()

    # Score tracking — само за dashboard, не е цел
    if score is not None:
        scores = entry.get("scores", [])
        scores.append({"date": _today(), "score": score})
        entry["scores"]     = scores[-30:]
        entry["last_score"] = score

    insight = llm_output.strip()[:200].replace("\n", " ")
    if insight:
        insights = entry.get("key_insights", [])
        h = hashlib.md5(insight.encode()).hexdigest()[:8]
        if h not in entry.get("insight_hashes", []):
            insights.append(insight)
            entry["key_insights"]   = insights[-10:]
            entry.setdefault("insight_hashes", []).append(h)
            entry["insight_hashes"] = entry["insight_hashes"][-10:]

    kb[axis] = entry
    _save(KNOWLEDGE_BASE, kb)

    try:
        from memory.semantic_memory import remember
        remember(insight, axis=axis, source=f"continuous_learner:{source}")
    except Exception:
        pass


# ── 3. RECORD PROBLEM SOLUTION ───────────────────────────────────────────────

def record_problem_solution(axis: str, problem: str, action: str,
                             result: str, status: str = "ATTEMPTED",
                             root_cause: str = "") -> None:
    """
    Записва опит за решаване на проблем.
    status: ATTEMPTED | SUCCESS | FAILED | PARTIAL
    """
    pdb = _load(PROBLEM_DB, {})
    if axis not in pdb:
        pdb[axis] = {"attempted_solutions": [], "known_root_causes": [], "solved_problems": []}

    entry = pdb[axis]

    # Запиши решението
    sol = {
        "date":       _today(),
        "problem":    problem[:150],
        "action":     action[:150],
        "result":     result[:150],
        "status":     status,
    }
    entry["attempted_solutions"].append(sol)
    entry["attempted_solutions"] = entry["attempted_solutions"][-20:]

    # Запиши root cause ако е нов
    if root_cause and root_cause not in entry.get("known_root_causes", []):
        entry.setdefault("known_root_causes", []).append(root_cause[:150])
        entry["known_root_causes"] = entry["known_root_causes"][-10:]

    # Ако е успешен — запиши в solved
    if status == "SUCCESS":
        entry.setdefault("solved_problems", []).append({
            "date":    _today(),
            "problem": problem[:150],
            "how":     action[:150],
        })
        entry["solved_problems"] = entry["solved_problems"][-10:]

    pdb[axis] = entry
    _save(PROBLEM_DB, pdb)


# ── 4. LEARN FROM CYCLE ───────────────────────────────────────────────────────

def learn_from_cycle(cycle_data: dict = None) -> dict:
    """
    Извиква се в края на fast_cycle_runner.
    REDESIGN: Акумулира проблеми и решения от web_intel.
    Score приоритет: web_intel analysis > snapshot > level_map (само за KB compat).
    """
    master_path = BASE_DIR / "snapshots" / "master" / "master_snapshot_latest.json"
    master      = _load(master_path, {})
    levels_path = BASE_DIR / "memory" / "auto_levels.json"
    levels      = _load(levels_path, {})

    # Зареди web intelligence
    web_intel_axes    = {}
    web_intel_problems = []
    try:
        wi_path = BASE_DIR / "memory" / "web_intelligence" / "latest.json"
        if wi_path.exists():
            wi_data            = _load(wi_path, {})
            web_intel_axes     = wi_data.get("axes", {})
            web_intel_problems = wi_data.get("problems_found", [])
    except Exception:
        pass

    updated   = 0
    level_map = {"HIGH": 85.0, "MEDIUM": 55.0, "LOW": 25.0}

    # Акумулирай проблеми от web_intel в problem_solution_db
    for p in web_intel_problems:
        axis     = p.get("axis", "UNKNOWN")
        problem  = p.get("problem", "")
        actions  = p.get("actions", [])
        severity = p.get("severity", "")

        if problem and actions:
            for a in actions[:1]:  # само първото действие
                record_problem_solution(
                    axis      = axis,
                    problem   = problem,
                    action    = a.get("action", ""),
                    result    = f"Предложено: {a.get('measurable_goal', '')}",
                    status    = "PROPOSED",
                    root_cause = p.get("root_cause", ""),
                )

    # Акумулирай insights от snapshots
    for axis, snap in master.get("snapshots", {}).items():
        if not isinstance(snap, dict):
            continue

        score = None

        # Score от web_intel analysis
        wi_axis  = web_intel_axes.get(axis, {})
        severity = wi_axis.get("severity", wi_axis.get("risk_level", ""))
        sev_map  = {"LOW": 80.0, "MEDIUM": 55.0, "HIGH": 30.0, "CRITICAL": 10.0}
        if severity in sev_map:
            score = sev_map[severity]

        # Fallback: snapshot score
        if score is None:
            for field in ("score", "overall_progress_pct"):
                val = snap.get(field)
                if val is not None:
                    try:
                        score = float(val)
                        break
                    except Exception:
                        pass

        # Fallback: level_map
        if score is None:
            level = levels.get(axis, {}).get("level", snap.get("current_level", ""))
            score = level_map.get(level)

        # Insight — проблем-ориентиран
        insight_parts = []
        problem = wi_axis.get("problem", "")
        if problem:
            insight_parts.append(f"Проблем: {problem[:100]}")
        root_cause = wi_axis.get("root_cause", "")
        if root_cause:
            insight_parts.append(f"Root cause: {root_cause[:80]}")
        for field in ("summary", "honest_assessment", "real_state"):
            val = snap.get(field, "")
            if val and isinstance(val, str):
                insight_parts.append(val[:100])
                break

        insight = f"{axis}: " + " | ".join(insight_parts) if insight_parts else ""

        if insight:
            after_llm_call(axis=axis, llm_output=insight, score=score,
                           source="learn_from_cycle")
            updated += 1

    # Ако cycle_data съдържа резултати от self_modifier — запиши ги
    if cycle_data and "executed" in cycle_data:
        for e in cycle_data.get("executed", []):
            component = "SELF_IMPROVEMENT"
            record_problem_solution(
                axis       = component,
                problem    = e.get("problem", ""),
                action     = e.get("action", ""),
                result     = f"score: {e.get('score_before')}→{e.get('score_after')}",
                status     = "SUCCESS",
                root_cause = "",
            )
        for f in cycle_data.get("failed", []):
            record_problem_solution(
                axis       = "SELF_IMPROVEMENT",
                problem    = f.get("problem", ""),
                action     = "attempted patch",
                result     = f.get("reason", ""),
                status     = "FAILED",
            )

    # Cycle log
    cycle_log = _load(CYCLE_LOG, [])
    kb        = _load(KNOWLEDGE_BASE, {})
    pdb       = _load(PROBLEM_DB, {})
    cycle_log.append({
        "timestamp":          _now(),
        "axes_updated":       updated,
        "total_axes_in_kb":   len(kb),
        "problems_tracked":   sum(len(v.get("attempted_solutions", [])) for v in pdb.values()),
        "web_intel_problems": len(web_intel_problems),
        "source":             cycle_data.get("source", "unknown") if cycle_data else "unknown",
    })
    _save(CYCLE_LOG, cycle_log[-100:])

    return {"axes_updated": updated, "total_in_kb": len(kb), "problems_in_db": len(pdb)}


# ── 5. GET SYSTEM KNOWLEDGE ───────────────────────────────────────────────────

def get_system_knowledge(top_n: int = 5) -> str:
    kb  = _load(KNOWLEDGE_BASE, {})
    pdb = _load(PROBLEM_DB, {})

    lines = []

    # Активни проблеми с предложени решения
    active_problems = []
    for axis, data in pdb.items():
        proposed = [s for s in data.get("attempted_solutions", []) if s.get("status") == "PROPOSED"]
        if proposed:
            active_problems.append((axis, proposed[-1]))

    if active_problems:
        lines.append(f"АКТИВНИ ПРОБЛЕМИ ({len(active_problems)} оси):")
        for axis, sol in active_problems[:top_n]:
            lines.append(f"  {axis}: {sol.get('problem', '')[:80]}")
            lines.append(f"    → {sol.get('action', '')[:80]}")

    # Успешни решения
    solved = []
    for axis, data in pdb.items():
        for s in data.get("solved_problems", []):
            solved.append((axis, s))
    if solved:
        lines.append(f"\nРЕШЕНИ ПРОБЛЕМИ ({len(solved)}):")
        for axis, s in solved[-3:]:
            lines.append(f"  ✅ {axis}: {s.get('problem', '')[:80]}")

    # KB trends (backward compat)
    if kb:
        sorted_axes = sorted(kb.items(), key=lambda x: x[1].get("cycle_count", 0), reverse=True)
        lines.append(f"\nЗНАНИЕ ({len(kb)} оси):")
        for axis, data in sorted_axes[:3]:
            cycles   = data.get("cycle_count", 0)
            last_ins = data.get("key_insights", [""])[-1][:80] if data.get("key_insights") else ""
            if last_ins:
                lines.append(f"  {axis} [{cycles} цикъла]: {last_ins}")

    return "\n".join(lines) if lines else ""


if __name__ == "__main__":
    print("=== CONTINUOUS LEARNER TEST ===")

    print("\n1. before_llm_call (ENERGY_REVIEW):")
    block = before_llm_call("ENERGY_REVIEW", "проблеми с енергийния сектор")
    print(block[:500] or "  (няма памет още)")

    print("\n2. record_problem_solution test:")
    record_problem_solution(
        axis       = "ENERGY_REVIEW",
        problem    = "74.8% от енергията идва от fossil fuels",
        action     = "Анализ на solar adoption политики в топ 10 emitters",
        result     = "Идентифицирани 3 политики с >5% потенциал за редукция",
        status     = "PROPOSED",
        root_cause = "Липса на икономически стимули за renewable transition",
    )
    print("  Записано.")

    print("\n3. learn_from_cycle:")
    result = learn_from_cycle()
    print(f"  Обновени: {result['axes_updated']} оси | KB: {result['total_in_kb']} | Problems: {result['problems_in_db']}")

    print("\n4. get_system_knowledge:")
    print(get_system_knowledge(top_n=3) or "  (няма данни още)")