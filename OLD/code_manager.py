import os
import shutil
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"

CODE_DIR = BASE_DIR  # за сега .py файловете са директно в CORTEX++
HISTORY_DIR = os.path.join(BASE_DIR, "history")
CODE_BACKUPS_DIR = os.path.join(HISTORY_DIR, "code_backups")
CODE_DIFFS_DIR = os.path.join(HISTORY_DIR, "code_diffs")

# Файл, от който по-късно агентът може да пише предложения
CODE_SUGGESTIONS_FILE = os.path.join(BASE_DIR, "code_suggestions.txt")


def ensure_dirs():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(CODE_BACKUPS_DIR, exist_ok=True)
    os.makedirs(CODE_DIFFS_DIR, exist_ok=True)


def read_file_safe(path: str) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[ERROR READING {path}: {e}]"


def write_file_safe(path: str, content: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"[ERROR WRITE] {path} -> {e}")


def backup_file(src_path: str) -> str:
    """Прави копие на даден .py файл в history/code_backups с timestamp."""
    ensure_dirs()
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Няма такъв файл за backup: {src_path}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(src_path)
    backup_name = f"{base_name}.{ts}.bak"
    backup_path = os.path.join(CODE_BACKUPS_DIR, backup_name)

    shutil.copy2(src_path, backup_path)
    print(f"[BACKUP] {src_path} -> {backup_path}")
    return backup_path


def simple_diff(old_text: str, new_text: str) -> str:
    """Много прост diff: показва стария и новия текст един под друг."""
    diff_lines = []
    diff_lines.append("=== OLD VERSION ===")
    diff_lines.append(old_text)
    diff_lines.append("")
    diff_lines.append("=== NEW VERSION ===")
    diff_lines.append(new_text)
    return "\n".join(diff_lines)


def save_diff(original_name: str, diff_text: str) -> str:
    ensure_dirs()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    diff_name = f"{original_name}.{ts}.diff.txt"
    diff_path = os.path.join(CODE_DIFFS_DIR, diff_name)
    write_file_safe(diff_path, diff_text)
    print(f"[DIFF] Записан diff: {diff_path}")
    return diff_path


def create_variant(original_filename: str, new_suffix: str = "_v2") -> str:
    """
    Създава нов .py файл на база съществуващ, без да пипа оригинала.
    Засега: копира 1:1 и добавя кратък коментар най-отгоре, че е variant.
    После agent-ът може да предлага реални промени по този нов файл.
    """
    ensure_dirs()

    original_path = os.path.join(CODE_DIR, original_filename)
    if not os.path.exists(original_path):
        print(f"[ERROR] Няма такъв файл: {original_path}")
        return ""

    original_code = read_file_safe(original_path)
    if not original_code:
        print(f"[ERROR] Празен или нечетим файл: {original_path}")
        return ""

    name, ext = os.path.splitext(original_filename)
    new_filename = f"{name}{new_suffix}{ext}"
    new_path = os.path.join(CODE_DIR, new_filename)

    header = (
        f"# AUTO-GENERATED VARIANT BY code_manager.py\n"
        f"# Original: {original_filename}\n"
        f"# Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    new_code = header + original_code

    # backup на оригинала (за история)
    backup_file(original_path)

    # запис на новия файл
    write_file_safe(new_path, new_code)
    print(f"[NEW VARIANT] {new_path}")

    # прост diff (тук още няма реални разлики, освен header-а, но логиката е готова)
    diff_text = simple_diff(original_code, new_code)
    save_diff(original_filename, diff_text)

    return new_path


def main():
    ensure_dirs()
    print("=== CORTEX++ CODE MANAGER ===")
    print("Тази първа версия НЕ променя директно нито един .py файл.")
    print("Тя само създава нови варианти и пази backup + diff.")

    print("\nПримерно действие:")
    print("- Създаваме variant на cortex4.py -> cortex4_v2.py\n")

    new_path = create_variant("cortex4.py", "_v2")
    if new_path:
        print(f"\nГотово. Новият файл е: {new_path}")
        print("Можеш да го редактираш ръчно или по-късно agent-ът да предлага промени по него.")
    else:
        print("\nНе успях да създам нов variant.")

    print("\nКрай на code_manager.")


if __name__ == "__main__":
    main()
