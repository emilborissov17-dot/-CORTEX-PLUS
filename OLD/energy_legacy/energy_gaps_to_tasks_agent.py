import json
from pathlib import Path
from datetime import datetime, UTC

import requests

ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge"

GAPS_JSON = KNOWLEDGE_DIR / "energy_data_gaps.json"
OUTPUT_TASKS = KNOWLEDGE_DIR / "energy_tasks_from_gaps.txt"

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL_NAME = "qwen3:8b"


def load_gaps() -> dict:
    if not GAPS_JSON.exists():
        raise FileNotFoundError(f"{GAPS_JSON} not found")
    data = json.loads(GAPS_JSON.read_text(encoding="utf-8"))
    return data


def build_messages(gaps_payload: dict) -> list[dict]:
    gaps_list = gaps_payload.get("gaps", [])
    gaps_json_str = json.dumps(gaps_list, ensure_ascii=False, indent=2)

    system_msg = {
        "role": "system",
        "content": (
            "Ти си AGI агент (Qwen) по ос ENERGY вътре в CORTEX++.\n"
            "Получаваш JSON списък от ENERGY DATA GAPS, вече структурирани.\n\n"
            "Твоята задача: да превърнеш всеки data gap в 1–2 конкретни задачи за действие\n"
            "в познатия на CORTEX++ формат за задачи.\n\n"
            "ФОРМАТ НА ИЗХОДА (ЗАДЪЛЖИТЕЛЕН, ПЛОСЪК ТЕКСТ):\n"
            "[AXIS: ENERGY]\n"
            "[TASK]: кратко, конкретно действие, свързано с gap-а.\n"
            "[WHY]: защо задачата е важна (връзка с gap-а и системната цел).\n"
            "[DATA_NEEDED]: какви данни трябва да се съберат/анализират.\n"
            "[DATA_SOURCES]: конкретни източници (институции, портали, API, мултимедия).\n"
            "--\n\n"
            "За всеки gap създай минимум 1 и максимум 2 задачи.\n"
            "В [DATA_SOURCES] винаги изреждай конкретни места от интернет/мрежата,\n"
            "например: IEA data portal, ENTSO-E Transparency Platform, NREL datasets,\n"
            "World Bank Open Data, IEF (ако стане достъпен), национални статистически портали, научни статии.\n\n"
            "Пиши на български (освен имената на институции/API/портали).\n"
            "НЕ добавяй нищо извън описания формат. Няма списъци, няма Markdown заглавия.\n"
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            "Това е списъкът от ENERGY DATA GAPS (JSON масив):\n\n"
            f"{gaps_json_str}\n\n"
            "Превърни всеки gap в 1–2 задачи в описания формат.\n"
            "Дръж се кратко и конкретно, така че задачите да са директно изпълними\n"
            "от други агенти или хора."
        ),
    }

    return [system_msg, user_msg]


def call_qwen(messages: list[dict]) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.3,
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def write_tasks_file(tasks_text: str):
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    header = f"=== ENERGY_TASKS_FROM_GAPS @ {ts} UTC ===\n\n"
    OUTPUT_TASKS.parent.mkdir(exist_ok=True)
    OUTPUT_TASKS.write_text(header + tasks_text.strip() + "\n", encoding="utf-8")


def main():
    print("[ENERGY_GAPS_TO_TASKS] loading energy_data_gaps.json...")
    gaps_payload = load_gaps()

    print("[ENERGY_GAPS_TO_TASKS] building prompt...")
    messages = build_messages(gaps_payload)

    print("[ENERGY_GAPS_TO_TASKS] calling Qwen via Ollama...")
    try:
        tasks_text = call_qwen(messages)
    except Exception as e:
        print(f"[ENERGY_GAPS_TO_TASKS][ERROR] {e}")
        return

    print("[ENERGY_GAPS_TO_TASKS] writing energy_tasks_from_gaps.txt...")
    write_tasks_file(tasks_text)

    print("[ENERGY_GAPS_TO_TASKS] done.")


if __name__ == "__main__":
    main()
