#!/usr/bin/env python3
"""
memory/context_injector.py
Инжектира релевантна памет от ChromaDB в LLM промптове.
Това е липсващата връзка за непрекъснато учене.
"""
import json, pathlib, os
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(os.environ.get("CORTEX_BASE", pathlib.Path(__file__).resolve().parents[1])).resolve()
CAUSAL_LOG = BASE_DIR / "memory" / "causal_log.json"

def _now(): return datetime.now(timezone.utc).isoformat()

def _load_json(path, default):
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else default
    except Exception: return default

def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 1. Извлича релевантна памет за даден axis/въпрос ─────────────────────────
def get_relevant_memory(question: str, axis: str = None, n: int = 5) -> str:
    try:
        from memory.semantic_memory import query
        mems = query(question, n=n, axis=axis)
        if not mems:
            mems = query(question, n=n)
        if not mems:
            return ""
        lines = ["РЕЛЕВАНТНА ПАМЕТ ОТ ПРЕДИШНИ ЦИКЛИ:"]
        for m in mems:
            relevance = m.get("relevance", 0)
            if relevance < 0.3:
                continue
            date = m.get("date", "?")
            ax   = m.get("axis", "?")
            text = m.get("text", "")[:200]
            lines.append(f"  [{date}][{ax}] {text}")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception as e:
        return ""

# ── 2. Извлича каузални уроци — какво е работило/не е работило ───────────────
def get_causal_lessons(axis: str = None, n: int = 5) -> str:
    try:
        from memory.semantic_memory import query
        q = f"what worked what failed lesson learned {axis or ''}"
        mems = query(q, n=n, axis="FEEDBACK_LOOP")
        mems += query(q, n=n, axis="SELF_IMPROVEMENT")
        mems += query(q, n=n, axis="CAUSAL")
        if not mems:
            return ""
        lines = ["КАУЗАЛНИ УРОЦИ (какво работи / какво не):"]
        seen = set()
        for m in mems[:6]:
            text = m.get("text", "")[:200]
            if text in seen: continue
            seen.add(text)
            lines.append(f"  {text}")
        return "\n".join(lines) if len(lines) > 1 else ""
    except Exception:
        return ""

# ── 3. Инжектира памет в промпт ───────────────────────────────────────────────
def inject_memory(base_prompt: str, axis: str = None, question: str = None) -> str:
    q = question or axis or base_prompt[:100]
    memory_block = get_relevant_memory(q, axis=axis)
    causal_block = get_causal_lessons(axis=axis)
    parts = []
    if memory_block:
        parts.append(memory_block)
    if causal_block:
        parts.append(causal_block)
    if not parts:
        return base_prompt
    context = "\n\n".join(parts)
    return f"{context}\n\n{base_prompt}"

# ── 4. Записва каузална връзка: action → ефект → защо ─────────────────────────
def record_causal(action: str, effect: str, why: str, axis: str = "GENERAL",
                  score_before: float = None, score_after: float = None) -> None:
    log = _load_json(CAUSAL_LOG, [])
    delta = round(score_after - score_before, 2) if score_before is not None and score_after is not None else None
    entry = {
        "timestamp": _now(),
        "axis": axis,
        "action": action[:200],
        "effect": effect[:200],
        "why": why[:300],
        "score_before": score_before,
        "score_after": score_after,
        "delta": delta,
        "verdict": "BENEFICIAL" if (delta or 0) > 0.5 else "HARMFUL" if (delta or 0) < -0.5 else "NEUTRAL",
    }
    log.append(entry)
    _save_json(CAUSAL_LOG, log[-500:])
    # Запомни в semantic memory за бъдещи цикли
    try:
        from memory.semantic_memory import remember
        text = f"CAUSAL: {action[:100]} -> {effect[:100]} (delta={delta}, why={why[:100]})"
        remember(text, axis="CAUSAL", source="context_injector")
    except Exception:
        pass

# ── 5. Записва урок директно в semantic memory ────────────────────────────────
def learn(lesson: str, axis: str = "SELF_IMPROVEMENT", source: str = "agent") -> None:
    try:
        from memory.semantic_memory import remember
        remember(f"LESSON [{_now()[:10]}]: {lesson}", axis=axis, source=source)
    except Exception as e:
        print(f"[CONTEXT_INJECTOR] learn() грешка: {e}")

# ── 6. Прочита всички каузални записи за даден axis ──────────────────────────
def get_causal_history(axis: str = None, n: int = 10) -> list:
    log = _load_json(CAUSAL_LOG, [])
    if axis:
        log = [e for e in log if e.get("axis") == axis]
    return log[-n:]

if __name__ == "__main__":
    print("ChromaDB спомени:", end=" ")
    try:
        from memory.semantic_memory import _get_collection
        print(_get_collection().count())
    except Exception as e:
        print(f"грешка: {e}")
    print("\nТест inject_memory:")
    result = inject_memory("Анализирай текущото ниво на енергийния сектор.", axis="ENERGY_REVIEW")
    print(result[:500])
    print("\nТест record_causal:")
    record_causal(
        action="Увеличихме L2 regularisation на layer 3",
        effect="Entropy намаля от 0.72 до 0.43",
        why="L2 penalty намалява сложността на теглата",
        axis="SELF_IMPROVEMENT",
        score_before=45.0,
        score_after=62.0
    )
    print("Каузален запис записан.")
    print("\nКаузална история:")
    for e in get_causal_history(n=3):
        print(f"  [{e['axis']}] {e['action'][:50]} -> delta={e['delta']}")
