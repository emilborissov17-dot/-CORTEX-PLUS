#!/usr/bin/env python3
import json, pathlib, sys
from datetime import datetime, timezone

BASE_DIR = pathlib.Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "memory" / "reasoning_memory.json"
MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BASE_DIR))

SYSTEM_PROMPT = """Извлечи reasoning структурата от разговора.
Върни САМО валиден JSON без markdown:
{"key_insights":["..."],"reasoning_path":["стъпка1->стъпка2"],"open_questions":["..."],"principles_discovered":["..."],"direction":"...","next_step":"..."}"""

def extract_reasoning(conversation_text: str) -> dict:
    from core.groq_backend import call_groq
    prompt = f"{SYSTEM_PROMPT}\n\nРАЗГОВОР:\n{conversation_text[:6000]}"
    raw = call_groq(prompt, max_tokens=800)
    if "```json" in raw: raw = raw.split("```json")[1].split("```")[0]
    elif "```" in raw: raw = raw.split("```")[1].split("```")[0]
    result = json.loads(raw.strip())
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    return result

def save_reasoning(reasoning: dict):
    try:
        memory = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except:
        memory = {"sessions": []}
    memory["sessions"].append(reasoning)
    memory["sessions"] = memory["sessions"][-50:]
    MEMORY_FILE.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[EXTRACTOR] Записано.")

def load_context(n: int = 3) -> str:
    try:
        memory = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        sessions = memory.get("sessions", [])[-n:]
        if not sessions: return ""
        context = "=== ПАМЕТ НА МИСЛЕНЕТО ===\n\n"
        for s in sessions:
            context += f"Посока: {s.get('direction')}\n"
            context += f"Прозрения: {', '.join(s.get('key_insights', []))}\n"
            context += f"Следваща стъпка: {s.get('next_step')}\n\n"
        return context
    except:
        return ""

if __name__ == "__main__":
    test = "Разговор за AGI, ябълки, тегла като замразени принципи, continuity между сесии, памет на мисленето, emergence от правилна комбинация компоненти — памет, reasoning, feedback, вътрешен конфликт."
    print("[EXTRACTOR] Извличам reasoning структура...")
    try:
        reasoning = extract_reasoning(test)
        print(json.dumps(reasoning, ensure_ascii=False, indent=2))
        save_reasoning(reasoning)
        print("\n[EXTRACTOR] Контекст за следваща сесия:")
        print(load_context())
    except Exception as e:
        print(f"[EXTRACTOR] Грешка: {e}")
