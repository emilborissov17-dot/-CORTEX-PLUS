import os
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"

GOAL_SUMMARY_FILE = os.path.join(BASE_DIR, "goal_summary.txt")
SELF_SUMMARY_FILE = os.path.join(BASE_DIR, "self_summary.txt")
CODE_SUGGESTIONS_FILE = os.path.join(BASE_DIR, "code_suggestions.txt")
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
    filename = f"code_suggestions_{ts}.log"
    full_path = os.path.join(HISTORY_DIR, filename)
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(entry)
        print(f"[HISTORY] Записах лог: {full_path}")
    except Exception as e:
        print(f"[ERROR HISTORY] {full_path} -> {e}")


def main():
    print("=== CORTEX++ CODE SUGGESTIONS ===")

    goal_text = read_file_safe(GOAL_SUMMARY_FILE)
    self_text = read_file_safe(SELF_SUMMARY_FILE)

    if not goal_text and not self_text:
        print("Няма нито goal_summary.txt, нито self_summary.txt. Няма база за предложения.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    suggestions = []
    suggestions.append("=== CORTEX++ CODE SUGGESTIONS ===")
    suggestions.append(f"Генерирано на: {timestamp}")
    suggestions.append("")
    suggestions.append("---- 1) КОНТЕКСТ: ЦЕЛИ (goal_summary.txt) ----")
    suggestions.append(goal_text or "[няма съдържание]")
    suggestions.append("")
    suggestions.append("---- 2) КОНТЕКСТ: САМО-ОПИСАНИЕ (self_summary.txt) ----")
    suggestions.append(self_text or "[няма съдържание]")
    suggestions.append("")
    suggestions.append("---- 3) ПРЕДЛОЖЕНИЯ ЗА ПРОМЕНИ В КОДА ----")

    # Това са първоначални, общи предложения, извлечени от очевидните разминавания
    suggestions.append(
        "- Добави по-подробно логване в cortex4 (и/или cortex4_v2): "
        "какви файлове чете, какви изходи генерира, в кой history лог пише."
    )
    suggestions.append(
        "- Създай отделен модул за работа с Wikipedia HTML (например cortex4_wiki), "
        "вместо логиката да е вмъкната директно в cortex4."
    )
    suggestions.append(
        "- Добави централизирано четене на resource_policy.txt, така че всички скриптове "
        "да спазват едни и същи ограничения за файлов достъп и мрежа."
    )
    suggestions.append(
        "- Подготви структура в history/code_diffs за бъдещи автоматични промени по кода "
        "(така че всяка промяна да е проследима и обръщаема)."
    )

    suggestions.append("")
    suggestions.append(
        "Забележка: Този файл е начална рамка. Човекът и/или по-интелигентен модел може да я "
        "замени по-късно с по-конкретни, автоматично генерирани предложения."
    )

    full_text = "\n".join(suggestions)
    write_file_safe(CODE_SUGGESTIONS_FILE, full_text)
    print(f"[OK] Записах предложения за код в: {CODE_SUGGESTIONS_FILE}")

    history_entry = (
        f"--- CODE SUGGESTIONS SNAPSHOT ---\n"
        f"Време: {timestamp}\n\n"
        f"Цели (goal_summary.txt):\n{goal_text or '[няма]'}\n\n"
        f"Самоописание (self_summary.txt):\n{self_text or '[няма]'}\n\n"
        f"Файл с предложения: {CODE_SUGGESTIONS_FILE}\n"
    )
    append_history_log(history_entry)

    print("Край на Code Suggestions.")


if __name__ == "__main__":
    main()
