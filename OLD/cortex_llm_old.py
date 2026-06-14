import requests
import json
from pathlib import Path

# === Глобална цел на системата ===

GOAL_PATH = Path("civilization_goal.txt")

def load_global_goal():
    try:
        return GOAL_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return (
            "ГЛОБАЛНА ЦЕЛ: файл civilization_goal.txt липсва или не може да бъде прочетен. "
            "Действай максимално предпазливо."
        )

# === Настройки за Qwen / Ollama ===

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MODEL_NAME = "qwen3:8b"

def call_qwen(messages):
    """
    Извиква локалния Qwen модел през Ollama API
    и връща само текста на отговора.
    """
    data = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    resp = requests.post(OLLAMA_URL, headers=headers, data=json.dumps(data))
    resp.raise_for_status()
    j = resp.json()
    return j["choices"][0]["message"]["content"]

# === Главен CORTEX_CONTROL цикъл (мини версия) ===

def run_cortex_control(user_goal: str):
    """
    Минимален CORTEX_CONTROL:
    - чете глобалната цел
    - комбинира я с конкретната задача от човека
    - връща план на високо ниво
    """
    global_goal = load_global_goal()

    system_prompt = (
        global_goal + "\n\n"
        "Ти си CORTEX_CONTROL в системата CORTEX++. "
        "Координираш всички домейн-агенти (RESOURCE_AGENT, ECO_AGENT, ECON_AGENT, SOCIAL_AGENT и др.) "
        "и предлагаш планове, които са в съответствие с ГЛОБАЛНАТА ЦЕЛ по-горе. "
        "Мисли в рамките на устойчивост, дългосрочна жизнеспособност и минимизиране на риска от вреда.\n\n"
        "Когато получиш конкретна цел от човека, ти:\n"
        "- я свързваш с глобалната цел,\n"
        "- предлагаш стъпки и кои агенти да бъдат активирани,\n"
        "- избягваш опасни или необратими действия.\n\n"
        "Отговаряй кратко и структурирано."
    )

    user_content = (
        "Конкретна цел от човека:\n"
        f"{user_goal}\n\n"
        "Дай ми кратък план на високо ниво и кои агенти да включа."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    response = call_qwen(messages)
    return response

if __name__ == "__main__":
    # Примерен интерактивен режим
    print("CORTEX_CONTROL interactive shell. Напиши цел или 'exit' за край.")
    while True:
        try:
            user_goal = input("ЦЕЛ> ").strip()
        except EOFError:
            break

        if not user_goal:
            continue
        if user_goal.lower() in ("exit", "quit"):
            break

        plan = run_cortex_control(user_goal)
        print("\n=== CORTEX PLAN ===")
        print(plan)
        print("\n")
