import os
from pathlib import Path
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"
LOGS_DIR = Path(BASE_DIR) / "logs"
AXIS_EXECUTOR_LOG = LOGS_DIR / "AXIS_TASK_EXECUTOR_LOG.txt"
QUERIES_FILE = Path(BASE_DIR) / "internet_queries.txt"


def read_axis_executor_steps() -> list[str]:
    if not AXIS_EXECUTOR_LOG.exists():
        print(f"[INET BRIDGE] Няма AXIS_TASK_EXECUTOR_LOG.txt в {LOGS_DIR}")
        return []

    try:
        text = AXIS_EXECUTOR_LOG.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[INET BRIDGE] Грешка при четене на {AXIS_EXECUTOR_LOG}: {e}")
        return []

    blocks = text.split("=== AXIS TASK EXECUTION STEP START ===")
    steps = []
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        steps.append("=== AXIS TASK EXECUTION STEP START ===\n" + b)

    return steps


def parse_tasks_from_step(step_text: str) -> list[dict]:
    """
    Чете един блок 'AXIS TASK EXECUTION STEP' и вади списък от задачи
    със структура:
      {
        "TASK_ID": ...,
        "AXIS_NAME": ...,
        "PRIORITY": ...,
        "ALIGNMENT_SCORE": ...,
        "TASK_DESCRIPTION": ...,
      }
    """
    lines = step_text.splitlines()
    tasks = []
    current = {}

    in_tasks = False
    for line in lines:
        s = line.rstrip()

        if s.strip().startswith("TASKS_PICKED:"):
            in_tasks = True
            continue

        if in_tasks:
            t = s.strip()
            if t.startswith("- TASK_ID:"):
                if current:
                    tasks.append(current)
                    current = {}
                current["TASK_ID"] = t.split(":", 1)[1].strip()
            elif t.startswith("AXIS_NAME:"):
                current["AXIS_NAME"] = t.split(":", 1)[1].strip()
            elif t.startswith("PRIORITY:"):
                current["PRIORITY"] = t.split(":", 1)[1].strip()
            elif t.startswith("ALIGNMENT_SCORE:"):
                current["ALIGNMENT_SCORE"] = t.split(":", 1)[1].strip()
            elif t.startswith("TASK_DESCRIPTION:"):
                current["TASK_DESCRIPTION"] = t.split(":", 1)[1].strip()

    if current:
        tasks.append(current)

    return tasks


def make_query_cards(tasks: list[dict]) -> list[str]:
    """
    За всяка задача прави по 1 "картичка" за външен мултимодален интернет агент:
    - контекст (axis, alignment, priority, task_id)
    - конкретна заявка към агента
    - указания за използване на текст/видео/данни
    - очакван JSON формат за изхода
    - препоръчан път за запис на резултата
    """
    cards = []
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for t in tasks:
        tid = t.get("TASK_ID", "?")
        axis = t.get("AXIS_NAME", "?")
        pr = t.get("PRIORITY", "?")
        sc = t.get("ALIGNMENT_SCORE", "?")
        desc = t.get("TASK_DESCRIPTION", "")

        axis_safe = axis.replace(" ", "_")
        out_dir = Path(BASE_DIR) / "knowledge" / "internet_snapshots" / axis_safe
        # очакваме JSON файл за директен ingest
        out_path = out_dir / f"{tid}_snapshot.json"

        card_lines = []
        card_lines.append("=== INTERNET QUERY CARD START ===")
        card_lines.append(f"TIMESTAMP_LOCAL: {ts}")
        card_lines.append(f"AXIS_NAME: {axis}")
        card_lines.append(f"TASK_ID: {tid}")
        card_lines.append(f"PRIORITY: {pr}")
        card_lines.append(f"ALIGNMENT_SCORE: {sc}")
        card_lines.append(f"TASK_DESCRIPTION: {desc}")
        card_lines.append("")
        card_lines.append("INSTRUCTIONS_FOR_HUMAN_AND_EXTERNAL_AGENT:")
        card_lines.append("- ЧОВЕК: копирай целия този блок и го пусни към външен мултимодален интернет агент (например Perplexity).")
        card_lines.append("- ВЪНШЕН АГЕНТ: използвай уеб търсене, статии, доклади, видеа, подкасти и публични данни,")
        card_lines.append("  за да изпълниш TASK_DESCRIPTION по оста/домейна AXIS_NAME / TASK_ID.")
        card_lines.append("- Фокусирай се върху реални политики, проекти, технологии, данни и действия, а не абстрактни разсъждения.")
        card_lines.append("")
        card_lines.append("EXPECTED_OUTPUT_FORMAT (много важно):")
        card_lines.append("ВЪРНИ САМО ЕДИН ВАЛИДЕН JSON ОБЕКТ със следните полета (без обяснения извън JSON):")
        card_lines.append("{")
        card_lines.append('  "summary_bg": "кратко резюме на български",')
        card_lines.append('  "key_findings_bg": ["основни факти и изводи"],')
        card_lines.append('  "sources": [')
        card_lines.append('    {')
        card_lines.append('      "url": "https://...",')
        card_lines.append('      "type": "article | video | report | dataset | other",')
        card_lines.append('      "title": "заглавие или кратко описание",')
        card_lines.append('      "reliability_note_bg": "кратка оценка за достоверност / ограничения"')
        card_lines.append("    }")
        card_lines.append("  ],")
        card_lines.append('  "proposed_actions": [')
        card_lines.append("    {")
        card_lines.append('      "id": "TACTIC-001",')
        card_lines.append('      "level": "TECHNICAL | ORGANIZATIONAL | POLITICAL | CIVILIZATIONAL",')
        card_lines.append('      "actor": "кой реално трябва да действа (CORTEX++ | human_individual | human_collective | diplomacy_agent)",')
        card_lines.append('      "time_horizon": "short | medium | long",')
        card_lines.append('      "description_bg": "конкретна изпълнима стъпка на български",')
        card_lines.append('      "expected_effect_bg": "как това придвижва системата по конституционните оси"')
        card_lines.append("    }")
        card_lines.append("  ],")
        card_lines.append('  "risks_bg": ["рискове и нежелани ефекти"],')
        card_lines.append('  "alignment_explanation_bg": "обяснение как предложените действия служат на целта и осите"')
        card_lines.append("}")
        card_lines.append("")
        card_lines.append("SUGGESTED_OUTPUT_PATH (локално при AGI балона):")
        card_lines.append(str(out_path))
        card_lines.append("")
        card_lines.append("QUERY_FOR_EXTERNAL_AGENT_BG:")
        card_lines.append(
            f"Ти си външен мултимодален AGI/LLM агент с достъп до интернет, текст, видео, аудио и данни. "
            f"Помогни на вътрешния AGI балон по оста '{axis}' със задача '{tid}' "
            f"(PRIORITY={pr}, ALIGNMENT_SCORE={sc}). "
            f"Задачата е: {desc} "
            f"Използвай актуални и надеждни източници. Пиши на български. "
            f"Съобрази се със схемата EXPECTED_OUTPUT_FORMAT по-горе и върни САМО един JSON обект в този формат."
        )
        card_lines.append("=== INTERNET QUERY CARD END ===")
        card_lines.append("")

        cards.append("\n".join(card_lines))

    return cards


def write_queries_file(cards: list[str]):
    if not cards:
        print("[INET BRIDGE] Няма задачи -> няма заявки към интернет.")
        return

    try:
        QUERIES_FILE.write_text("\n".join(cards), encoding="utf-8")
    except Exception as e:
        print(f"[INET BRIDGE] Грешка при писане в {QUERIES_FILE}: {e}")
        return

    print(f"[INET BRIDGE] Записани са {len(cards)} INTERNET QUERY CARD блока в {QUERIES_FILE}.")


def main():
    steps = read_axis_executor_steps()
    if not steps:
        return

    # взимаме само последната стъпка (най-новото изпълнение)
    last_step = steps[-1]
    tasks = parse_tasks_from_step(last_step)
    if not tasks:
        print("[INET BRIDGE] В последната стъпка няма намерени задачи.")
        return

    cards = make_query_cards(tasks)
    write_queries_file(cards)


if __name__ == "__main__":
    main()
