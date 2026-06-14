import os
import shutil
import subprocess
from datetime import datetime

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"

CODE_FILE = os.path.join(BASE_DIR, "cortex4_v2.py")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
CODE_VERSIONS_DIR = os.path.join(HISTORY_DIR, "code_versions")

RESOURCE_POLICY_FILE = os.path.join(BASE_DIR, "resource_policy.txt")
SMOKE_TEST_FILE = os.path.join(BASE_DIR, "tests", "smoke_tests.py")


def ensure_dirs():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(CODE_VERSIONS_DIR, exist_ok=True)


def load_resource_policy():
    if not os.path.exists(RESOURCE_POLICY_FILE):
        print(f"[WARN] Няма resource_policy.txt в {BASE_DIR}.")
        return None, {}

    try:
        with open(RESOURCE_POLICY_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"[ERROR] Грешка при четене на resource_policy.txt: {e}")
        return None, {}

    policy = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            policy[key.strip().upper()] = value.strip()

    return content, policy


def check_basic_policy(policy: dict) -> bool:
    network = policy.get("NETWORK_ACCESS", "").upper()
    if network != "FORBIDDEN":
        print("[WARN] В resource_policy.txt NETWORK_ACCESS не е FORBIDDEN.")
        print("       За този етап на проекта се очаква: NETWORK_ACCESS: FORBIDDEN")
        return False

    root = policy.get("FILE_ACCESS_ROOT", "")
    if root and os.path.normpath(root) != os.path.normpath(BASE_DIR):
        print("[WARN] FILE_ACCESS_ROOT в resource_policy.txt не съвпада с BASE_DIR.")
        print(f"       FILE_ACCESS_ROOT: {root}")
        print(f"       BASE_DIR:         {BASE_DIR}")
        return False

    print("[INFO] Основните политики в resource_policy.txt изглеждат съвместими.")
    return True


def backup_code_file():
    ensure_dirs()

    if not os.path.exists(CODE_FILE):
        print(f"[ERROR] Няма файл за бекъп: {CODE_FILE}")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(CODE_FILE)
    name, ext = os.path.splitext(base_name)
    backup_name = f"{name}_{ts}{ext}"
    backup_path = os.path.join(CODE_VERSIONS_DIR, backup_name)

    try:
        shutil.copy2(CODE_FILE, backup_path)
        print(f"[OK] Направен е бекъп на {CODE_FILE} -> {backup_path}")
    except Exception as e:
        print(f"[ERROR] Грешка при бекъп на {CODE_FILE} -> {e}")


def run_smoke_tests():
    """Пуска tests/smoke_tests.py като отделен процес."""
    if not os.path.exists(SMOKE_TEST_FILE):
        print(f"[ERROR] Няма файл със smoke-тестове: {SMOKE_TEST_FILE}")
        return

    print("[INFO] Стартирам smoke-тестовете...")
    try:
        result = subprocess.run(
            ["python", SMOKE_TEST_FILE],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        print(f"[ERROR] Неуспешно стартиране на smoke-тестовете: {e}")
        return

    print("=== SMOKE TEST OUTPUT ===")
    print(result.stdout)
    if result.stderr:
        print("--- STDERR ---")
        print(result.stderr)
    print("=== END OF SMOKE TEST OUTPUT ===")

    if result.returncode == 0:
        print("[INFO] Smoke-тестовете МИНАХА (return code 0).")
    else:
        print(f"[WARN] Smoke-тестовете НЕ минаха (return code {result.returncode}).")


def show_menu():
    print("\n=== CORTEX5 CODE MANAGER ===")
    print("Този инструмент НЕ променя автоматично кода.")
    print("Целта му е да създаде безопасен слой за бекъпи и проверки преди бъдещи промени.\n")
    print("Налични действия:")
    print("1) Покажи и провери resource_policy.txt")
    print("2) Направи бекъп на cortex4_v2.py в history\\code_versions\\")
    print("3) Пусни smoke-тестовете (tests\\smoke_tests.py)")
    print("4) Изход")


def handle_option(option: str):
    if option == "1":
        content, policy = load_resource_policy()
        if content is None:
            return True
        print("\n=== RESOURCE POLICY CONTENT ===")
        print(content)
        print("=== END OF RESOURCE POLICY ===\n")
        check_basic_policy(policy)
    elif option == "2":
        backup_code_file()
    elif option == "3":
        run_smoke_tests()
    elif option == "4":
        print("Изход от cortex5_code_manager.")
        return False
    else:
        print("Неразпозната опция. Моля, избери 1, 2, 3 или 4.")
    return True


def main():
    ensure_dirs()
    while True:
        show_menu()
        try:
            choice = input("\nИзбери опция (1/2/3/4): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nПрекъсване от потребителя. Излизам от cortex5_code_manager.")
            break

        if not handle_option(choice):
            break


if __name__ == "__main__":
    main()
