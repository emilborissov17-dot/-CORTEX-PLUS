import os
import glob
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"

# Пътища за знание и история
FRESCO_BASE = os.path.join(BASE_DIR, "knowledge", "fresco_designing_future")
RAW_DIR = os.path.join(FRESCO_BASE, "01_raw")
SUMMARY_DIR = os.path.join(FRESCO_BASE, "02_summary_bg")
PRINCIPLES_FILE = os.path.join(FRESCO_BASE, "principles_ch01_03_bg.txt")

HISTORY_DIR = os.path.join(BASE_DIR, "history")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
SELF_IMPROVEMENT_FILE = os.path.join(CONFIG_DIR, "self_improvement_suggestions.txt")


def ensure_dirs():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(SUMMARY_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)


def write_file_safe(path: str, content: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[ERROR WRITE] {path} -> {e}")


def append_log(entry: str):
    """Пише лог за тази сесия в отделен файл в history/."""
    ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f"cortex4_v2_{ts}.log"
    log_path = os.path.join(HISTORY_DIR, log_name)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as e:
        print(f"[ERROR LOG] {log_path} -> {e}")


def list_raw_files():
    """Намира суровите файлове в 01_raw."""
    ensure_dirs()
    if not os.path.exists(RAW_DIR):
        return []
    files = [
        f
        for f in os.listdir(RAW_DIR)
        if os.path.isfile(os.path.join(RAW_DIR, f)) and f.endswith("_raw.txt")
    ]
    return sorted(files)


def auto_summarize(text: str) -> str:
    """
    Място за реална логика на резюме.
    Засега: връщаме първите ~500 символа като „авторезюме“.
    """
    text = text.strip()
    if len(text) <= 500:
        return text
    return text[:500] + "\n...\n[автоматично съкратено]"


def process_raw_files_and_summarize():
    """Чете суровите глави и прави авто-резюмета в 02_summary_bg, с логване."""
    files = list_raw_files()
    append_log("=== СТАРТ НА CORTEX4_V2 СЕСИЯ ===")
    append_log(f"Намерени сурови файлове в {RAW_DIR}: {files if files else '[]'}")

    if not files:
        msg = "Няма сурови файлове в 01_raw."
        print(msg)
        append_log(msg)
        append_log("=== КРАЙ НА СЕСИЯТА (НЯМА ФАЙЛОВЕ) ===")
        return

    print(f"Намерени са {len(files)} сурови файла в 01_raw.")
    append_log(f"Брой сурови файлове: {len(files)}")

    for fname in files:
        raw_path = os.path.join(RAW_DIR, fname)
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except Exception as e:
            msg = f"[ERROR READ RAW] {raw_path} -> {e}"
            print(msg)
            append_log(msg)
            continue

        base_name = fname.replace("_raw.txt", "")
        out_name = f"{base_name}_raw_auto_summary_bg.txt"
        out_path = os.path.join(SUMMARY_DIR, out_name)

        print(f"Обработвам: {fname} -> {out_name} ...")
        append_log(f"Обработвам суров файл: {raw_path} -> {out_path}")

        summary_text = auto_summarize(raw_text)

        try:
            write_file_safe(out_path, summary_text)
            append_log(f"[OK SUMMARY] {out_path}")
        except Exception as e:
            msg = f"[ERROR SUMMARY WRITE] {out_path} -> {e}"
            print(msg)
            append_log(msg)

    print(f"Готово с автоматичните резюмета в {SUMMARY_DIR}.")
    append_log(f"Завършена обработка на суровите файлове. Резюмета в: {SUMMARY_DIR}")
    append_log("=== КРАЙ НА ОБРАБОТКАТА НА ФАЙЛОВЕТЕ ===")


def pick_session_principle():
    """
    Символично място за изтегляне на „принцип за сесията“.
    Засега: просто твърд текст + лог.
    """
    principle = "ГЛАВА 1 – FROM YESTERDAY TO TOMORROW – ПРИНЦИПИ ЗА CORTEX"
    print("\nСЛУЧАЕН ПРИНЦИП ЗА ТАЗИ СЕСИЯ:")
    print(principle)
    append_log(f"Избран принцип за сесията: {principle}")


def get_latest_log_path():
    """Намира най-новия cortex4_v2_*.log в HISTORY_DIR."""
    pattern = os.path.join(HISTORY_DIR, "cortex4_v2_*.log")
    files = glob.glob(pattern)
    if not files:
        return None
    latest = max(files, key=os.path.getctime)  # най-скоро модифициран файл [web:645]
    return latest


def append_self_improvement_entry(source_log: str):
    """Добавя нов блок в self_improvement_suggestions.txt на база прост анализ на лога."""
    ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Четем лога и броим основни неща
    user_inputs = 0
    errors = 0
    summaries_ok = 0
    try:
        with open(source_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[USER INPUT]"):
                    user_inputs += 1
                if "[ERROR" in line:
                    errors += 1
                if "[OK SUMMARY]" in line:
                    summaries_ok += 1
    except Exception as e:
        print(f"[ERROR READ LOG FOR REFLECT] {source_log} -> {e}")
        append_log(f"[ERROR READ LOG FOR REFLECT] {source_log} -> {e}")
        return

    # Елементарни наблюдения
    strengths = []
    weaknesses = []
    proposed_rule_changes = []
    proposed_code_ideas = []

    if summaries_ok > 0:
        strengths.append(f"Успешно обработени сурови файлове и създадени резюмета: {summaries_ok}.")
    if user_inputs > 0:
        strengths.append(f"Интерактивният режим е използван (USER INPUT записите са {user_inputs}).")

    if errors > 0:
        weaknesses.append(f"Има {errors} грешки в лога (ERROR). Нужно е по-добро обработване на изключенията.")
        proposed_code_ideas.append(
            "Да се подобри обработката на грешки при четене/запис на файлове и да се дават по-ясни съобщения към потребителя."
        )

    if user_inputs == 0:
        weaknesses.append("В тази сесия няма интерактивни входове от човека.")
        proposed_rule_changes.append(
            "Да напомня по-ясно на човека за наличието на интерактивен режим, когато партидната част приключи."
        )

    if not strengths and not weaknesses:
        strengths.append("Логът е кратък и без очевидни проблеми. Няма достатъчно данни за по-дълбока рефлексия на този етап.")

    lines = []
    lines.append("=== SELF IMPROVEMENT ENTRY START ===")
    lines.append(f"TIMESTAMP: {ts}")
    lines.append(f"SOURCE_LOG: {source_log}")
    lines.append("OBSERVED_STRENGTHS:")
    for s in strengths:
        lines.append(f"- {s}")
    lines.append("OBSERVED_WEAKNESSES:")
    for w in weaknesses:
        lines.append(f"- {w}")
    lines.append("PROPOSED_RULE_CHANGES:")
    for r in proposed_rule_changes:
        lines.append(f"- {r}")
    lines.append("PROPOSED_CODE_IDEAS:")
    for c in proposed_code_ideas:
        lines.append(f"- {c}")
    lines.append("=== SELF IMPROVEMENT ENTRY END ===")
    lines.append("")  # празен ред

    try:
        with open(SELF_IMPROVEMENT_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"[REFLECT] Добавен е нов блок в {SELF_IMPROVEMENT_FILE}.")
        append_log(f"[REFLECT] Добавен self-improvement блок за лог: {source_log}")
    except Exception as e:
        print(f"[ERROR SELF IMPROVEMENT WRITE] {SELF_IMPROVEMENT_FILE} -> {e}")
        append_log(f"[ERROR SELF IMPROVEMENT WRITE] {SELF_IMPROVEMENT_FILE} -> {e}")


def handle_reflect_last_log():
    """Команда REFLECT LAST_LOG: намира последния лог и записва entry в self_improvement_suggestions."""
    latest_log = get_latest_log_path()
    if not latest_log:
        msg = "[REFLECT] Няма намерени cortex4_v2_*.log файлове в history/."
        print(msg)
        append_log(msg)
        return

    print(f"[REFLECT] Използвам последния лог файл: {latest_log}")
    append_log(f"[REFLECT] Използван лог за самоусъвършенстване: {latest_log}")
    append_self_improvement_entry(latest_log)


def interactive_loop():
    """
    Прост интерактивен цикъл: чете вход от потребителя, дава отговор
    и логва всяка стъпка в history/.
    """
    print("\nВлизам в интерактивен режим (CORTEX++ балон).")
    print("Напиши команда/въпрос или 'exit' за изход.")
    print("Специална команда: 'REFLECT LAST_LOG' за запис на self-improvement запис.\n")

    append_log("=== СТАРТ НА ИНТЕРАКТИВЕН РЕЖИМ ===")

    while True:
        try:
            user_input = input("CORTEX++> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[ИНФО] Прекъсване от потребителя. Излизам от интерактивен режим.")
            append_log("[ИНФО] Прекъсване от потребителя в интерактивен режим.")
            break

        if user_input.lower() in ("exit", "quit", "q"):
            print("Излизам от интерактивен режим.")
            append_log("Потребителят избра exit/quit. Край на интерактивния режим.")
            break

        if not user_input:
            continue

        append_log(f"[USER INPUT] {user_input}")

        # Специална команда
        if user_input.upper() == "REFLECT LAST_LOG":
            handle_reflect_last_log()
            continue()

        # Засега: символичен отговор за останалите входове
        response = (
            "Все още нямам реална логика за обработка на интерактивни задачи.\n"
            "На този етап само логвам входа ти и връщам това съобщение.\n"
            "Специално: можеш да използваш командата 'REFLECT LAST_LOG' за запис в self_improvement_suggestions."
        )

        print(response)
        append_log(f"[AGENT RESPONSE] {response.replace(os.linesep, ' ')}")

    append_log("=== КРАЙ НА ИНТЕРАКТИВЕН РЕЖИМ ===")


def main():
    ensure_dirs()
    print("Cortex 4 v2 – Fresco агент с локални файлове (AGI път) + лог в history.\n")

    # 1) Принцип за сесията
    print("1) Зареждам принципите от Jacque Fresco (глави 1–3)...")
    append_log("Стъпка 1: зареждане/избор на принцип за сесията.")
    pick_session_principle()

    # 2) Автоматични резюмета
    print("\n2) Генерирам автоматични резюмета за суровите глави в 01_raw...\n")
    append_log("Стъпка 2: започвам автоматично резюмиране на суровите глави в 01_raw.")
    process_raw_files_and_summarize()

    # Финал на партидната част
    print("\nКрай на партидната част на Cortex 4 v2.")
    print("Оригинални глави (01_raw): ", RAW_DIR)
    print("Ръчни/авто резюмета (02_summary_bg): ", SUMMARY_DIR)
    print("Файл с принципи (очакван): ", PRINCIPLES_FILE)

    append_log("Край на партидната част на Cortex 4 v2.")
    append_log(f"Папка сурови глави: {RAW_DIR}")
    append_log(f"Папка резюмета: {SUMMARY_DIR}")
    append_log(f"Очакван файл с принципи: {PRINCIPLES_FILE}")

    # 3) Интерактивен режим
    interactive_loop()

    append_log("Край на изпълнението на Cortex 4 v2 (вкл. интерактивен режим).")
    append_log("=== КРАЙ НА CORTEX4_V2 СЕСИЯ ===")


if __name__ == "__main__":
    main()
