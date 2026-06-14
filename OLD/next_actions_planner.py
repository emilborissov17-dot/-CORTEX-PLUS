import os
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"
GOAL_SUMMARY_FILE = os.path.join(BASE_DIR, "goal_summary.txt")
SELF_SUMMARY_FILE = os.path.join(BASE_DIR, "self_summary.txt")
NEXT_ACTIONS_FILE = os.path.join(BASE_DIR, "next_actions.txt")
HISTORY_DIR = os.path.join(BASE_DIR, "history")


def read_file_safe(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        return f"[ERROR READING {path}: {e}]"


def write_file_safe(path: str, content: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[ERROR WRITE] {path} -> {e}")


def append_history_log(entry: str):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"next_actions_{ts}.log"
    full_path = os.path.join(HISTORY_DIR, filename)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(entry)
        print(f"[HISTORY] Записах лог: {full_path}")
    except Exception as e:
        print(f"[ERROR HISTORY] {full_path} -> {e}")


def main():
    print("=== CORTEX++ Next Actions Planner ===")

    goal_text = read_file_safe(GOAL_SUMMARY_FILE)
    self_text = read_file_safe(SELF_SUMMARY_FILE)

    if not goal_text and not self_text:
        print("Няма нито goal_summary.txt, нито self_summary.txt. Нищо за планиране.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Това НЕ е „умно мислене“, а структурирано обобщение,
    # върху което после ти и/или друг код можете да стъпите.
    next_actions_content = []
    next_actions_content.append("=== CORTEX++ NEXT ACTIONS ===")
    next_actions_content.append(f"Генерирано на: {timestamp}")
    next_actions_content.append("")
    next_actions_content.append("---- 1) КОНТЕКСТ: ЦЕЛИ (goal_summary.txt) ----")
    next_actions_content.append(goal_text or "[няма съдържание]")
    next_actions_content.append("")
    next_actions_content.append("---- 2) КОНТЕКСТ: САМО-ОПИСАНИЕ (self_summary.txt) ----")
    next_actions_content.append(self_text or "[няма съдържание]")
    next_actions_content.append("")
    next_actions_content.append("---- 3) ПРЕДЛОЖЕНИ СЛЕДВАЩИ СТЪПКИ ----")
    next_actions_content.append(
        "- Прегледай дали текущите действия (скриптове, файлове) реално служат на описаните цели."
    )
    next_actions_content.append(
        "- Ако има несъответствия между цели и самоописание, отбележи ги в самия self_summary.txt като 'конфликти'."
    )
    next_actions_content.append(
        "- Предложи 1–3 конкретни технически стъпки (нови скриптове, промени по файлове), които да намалят тези конфликти."
    )
    next_actions_content.append(
        "- Определи приоритет: коя стъпка да се направи първа и защо."
    )
    next_actions_content.append("")
    next_actions_content.append(
        "Забележка: Този файл е начална рамка. Човекът и/или по-интелигентен модел може да го допълни "
        "с по-конкретни действия, базирани на реалното съдържание."
    )

    full_text = "\n".join(next_actions_content)

    write_file_safe(NEXT_ACTIONS_FILE, full_text)
    print(f"[OK] Записах план за следващи стъпки в: {NEXT_ACTIONS_FILE}")

    history_entry = (
        f"--- NEXT ACTIONS SNAPSHOT ---\n"
        f"Време: {timestamp}\n\n"
        f"Цели (goal_summary.txt):\n{goal_text or '[няма]'}\n\n"
        f"Самоописание (self_summary.txt):\n{self_text or '[няма]'}\n\n"
        f"Файл с план: {NEXT_ACTIONS_FILE}\n"
    )
    append_history_log(history_entry)

    print("Край на Next Actions Planner.")


if __name__ == "__main__":
    main()
