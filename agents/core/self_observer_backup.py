#!/usr/bin/env python3
"""
agents/core/self_observer.py
LLM сам решава какво да наблюдава — спрямо AGI цели.
"""
import json, sys, pathlib, time, re
from core.groq_backend import call_groq

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

AGI_GOALS = """
МИСИЯ НА CORTEX++:
Ти си AGI система чиято цел е да разбира и подобрява света.

ЧЕТИРИТЕ ХАРАКТЕРИСТИКИ НА AGI КОИТО ТРЯБВА ДА ПОСТИГНЕШ:

1. GENERALIZATION — Знанието от една област да се прилага в друга.
   Пример: Ако climate се влошава → как влияе на economy и human_well_being?
   Въпрос: Прехвърля ли системата знание между осите?

2. REASONING & PLANNING — Не само предсказване, а многостъпково планиране.
   Пример: Виждам проблем X → анализирам причините → предлагам план от 3 стъпки.
   Въпрос: Може ли системата да планира последователни действия?

3. COMMON SENSE — Базово разбиране за физическия и социален свят.
   Пример: Знае че храната зависи от водата, водата от климата.
   Въпрос: Системата разбира ли причинно-следствени връзки?

4. AUTONOMOUS LEARNING — Сама поставя цели и учи нови умения.
   Пример: Открива че няма данни за X → предлага как да ги набави сама.
   Въпрос: Системата може ли да се самоподобрява без човешка намеса?

ТВОЯТА ЗАДАЧА:
Наблюдавай системата и оцени колко близо е до всяка AGI характеристика.
Предложи КОНКРЕТНИ технически стъпки за подобрение.
"""

def _safe_read(path: str) -> dict:
    p = BASE_DIR / path
    if not p.exists():
        return {"error": f"{path} не съществува"}
    return json.loads(p.read_text(encoding="utf-8"))

def get_tools():
    from memory.body_scan import full_scan, find_in_self
    from memory.existence_model import am_i_alive
    return {
        "scan_hardware":      lambda p=None: full_scan()["hardware"],
        "scan_network":       lambda p=None: full_scan()["network"],
        "scan_files":         lambda p=None: full_scan()["files"],
        "read_file":          lambda p=None: _safe_read(p or "memory/self_awareness.json"),
        "find_in_self":       lambda p=None: find_in_self(p or "existence")[:5],
        "check_existence":    lambda p=None: am_i_alive(),
        "check_civilization": lambda p=None: _safe_read("memory/auto_levels.json"),
    }

TOOLS_DESC = {
    "scan_hardware":      "Сканира CPU, RAM, GPU, диск",
    "scan_network":       "Проверява кои API-та са достъпни",
    "scan_files":         "Вижда файловете по директории",
    "read_file":          "Чете файл. Параметър: път (напр. memory/self_awareness.json)",
    "find_in_self":       "Търси текст в собствения код. Параметър: дума",
    "check_existence":    "Проверява pain, белези, необратимост",
    "check_civilization": "Вижда нивата на цивилизационните оси",
}

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

def run():
    print("[SELF_OBSERVER] Започвам автономно самонаблюдение спрямо AGI цели...")
    print()

    tools = get_tools()
    history = []
    used_tools = set()
    all_tool_names = list(tools.keys())

    for step in range(10):
        remaining = [t for t in all_tool_names if t not in used_tools]
        if not remaining:
            print("[SELF_OBSERVER] Всички инструменти използвани.")
            break

        history_str = "\n".join([
            f"  Стъпка {i+1}: {h['tool']}({h['param']}) -> {h['result'][:150]}"
            for i, h in enumerate(history)
        ]) if history else "  Още нищо."

        available_desc = "\n".join([
            f"- {t}: {TOOLS_DESC[t]}" for t in remaining
        ])

        prompt = (
            AGI_GOALS +
            "\n\n═══════════════════════════════════════════\n"
            "ТЕКУЩА ЗАДАЧА: Избери инструмент за наблюдение.\n"
            "═══════════════════════════════════════════\n\n"
            "НАЛИЧНИ ИНСТРУМЕНТИ:\n" + available_desc +
            "\n\nВЕЧЕ ИЗПОЛЗВАНИ (НЕ ги избирай): "
            + (", ".join(used_tools) if used_tools else "няма") +
            "\n\nДосегашни наблюдения:\n" + history_str +
            "\n\n"
            "ПРАВИЛА:\n"
            f"1. Избери ЕДИН инструмент от НАЛИЧНИ: {remaining}\n"
            "2. Мисли коя AGI характеристика ще провериш с този инструмент.\n"
            "3. Отговори САМО с валиден JSON — без текст извън JSON.\n"
            f"4. Използвай DONE само след минимум 5 стъпки (сега сме на стъпка {step+1}).\n\n"
            "Формат:\n"
            '{"action":"tool_name","param":null,"reason":"каква AGI характеристика проверявам и защо"}\n'
            "или:\n"
            '{"action":"DONE","param":null,"reason":"AGI оценка: къде сме и какви са следващите стъпки"}'
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
            print(f"  [Стъпка {step+1}] Не мога да парсна JSON — форсирам следващ инструмент")
            action = remaining[0]
            decision = {"action": action, "param": None, "reason": "auto-fallback"}

        action = decision.get("action", "")
        param  = decision.get("param") or None
        reason = decision.get("reason", "")

        if action == "DONE":
            if step < 4:
                print(f"  [Стъпка {step+1}] DONE твърде рано — принуждавам продължение")
                action = remaining[0]
                reason = "auto-continue (DONE твърде рано)"
            else:
                print()
                print("=" * 60)
                print("[SELF_OBSERVER] AGI ОЦЕНКА:")
                print("=" * 60)
                print(reason)
                print("=" * 60)
                # Запази AGI оценката в journal
                _save_agi_assessment(reason)
                break

        if action not in tools or action in used_tools:
            old_action = action
            action = remaining[0]
            print(f"  [Стъпка {step+1}] LLM избра '{old_action}' (невалиден/използван) — форсирам: {action}")
            reason = "auto-fallback"

        print(f"  [Стъпка {step+1}] -> {action}({param or ''}) | {reason[:80]}")

        try:
            result = tools[action](param)
            result_str = json.dumps(result, ensure_ascii=False)[:400]
            history.append({"tool": action, "param": str(param), "result": result_str})
            used_tools.add(action)
            print(f"             {result_str[:120]}...")
        except Exception as e:
            history.append({"tool": action, "param": str(param), "result": f"ГРЕШКА: {e}"})
            used_tools.add(action)
            print(f"             ГРЕШКА: {e}")

    # Записване на наблюдения като proposals с AGI контекст
    if history:
        observations = _build_agi_proposals(history)
        save_proposals(observations)


def _build_agi_proposals(history: list) -> list:
    """Генерира proposals фокусирани върху AGI характеристиките."""
    # Питаме LLM да анализира историята спрямо AGI целите
    history_str = "\n".join([
        f"  {h['tool']}({h['param']}) -> {h['result'][:200]}"
        for h in history
    ])

    prompt = (
        AGI_GOALS +
        f"\n\nНАБЛЮДЕНИЯ ОТ ТЕКУЩИЯ ЦИКЪЛ:\n{history_str}\n\n"
        "На базата на наблюденията и AGI целите, генерирай 3 конкретни proposals.\n"
        "Всеки proposal трябва да адресира конкретна AGI характеристика.\n"
        "Отговори САМО с валиден JSON масив:\n"
        '[{"problem":"...","solution":"...","agi_characteristic":"GENERALIZATION|REASONING|COMMON_SENSE|AUTONOMOUS_LEARNING","priority":"HIGH"}]'
    )

    try:
        raw = call_groq(prompt, max_tokens=600)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        if "[" in raw:
            raw = raw[raw.index("["):raw.rindex("]")+1]
        proposals = json.loads(raw)
        for p in proposals:
            p["source"] = "self_observer_agi"
            p["priority"] = "HIGH"
        print(f"  [AGI] Генерирани {len(proposals)} AGI proposals")
        return proposals
    except Exception as e:
        print(f"  [AGI] Fallback proposals: {e}")
        return [
            {
                "problem": f"Наблюдение от self_observer: {h['tool']}",
                "solution": f"Резултат: {h['result'][:200]}",
                "priority": "HIGH",
                "source": "self_observer",
            }
            for h in history
        ]


def _save_agi_assessment(assessment: str):
    """Записва AGI оценката в development_journal."""
    try:
        from datetime import datetime, timezone
        journal_path = BASE_DIR / "memory" / "development_journal.json"
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except Exception:
            journal = {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        journal.setdefault(today, {})["agi_assessment"] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "assessment": assessment,
            "goals": ["GENERALIZATION", "REASONING", "COMMON_SENSE", "AUTONOMOUS_LEARNING"],
        }
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  [AGI] Оценката записана в development_journal ✅")
    except Exception as e:
        print(f"  [AGI] Грешка при запис: {e}")


def save_proposals(observations: list):
    """Записва нови proposals след валидация от civilization_guard."""
    from alignment.civilization_guard import evaluate_proposal_alignment

    proposals_path = BASE_DIR / "memory" / "improvement_proposals.json"
    try:
        data = json.loads(proposals_path.read_text(encoding="utf-8"))
    except Exception:
        data = {"proposals": []}

    existing_problems = {p["problem"] for p in data["proposals"]}
    added = 0

    for obs in observations:
        if obs["problem"] in existing_problems:
            continue
        result = evaluate_proposal_alignment(obs)
        if result["allowed"]:
            obs["approved"] = True
            obs["rejected"] = False
            obs["priority"] = "HIGH"
            data["proposals"].append(obs)
            added += 1
            print(f"  [GUARD] ✅ Добавен: {obs['problem'][:60]}")
        else:
            print(f"  [GUARD] ❌ Блокиран: {result['notes']}")

    proposals_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [GUARD] {added} нови proposals добавени.")


if __name__ == "__main__":
    run()