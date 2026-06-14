"""
Simple smoke tests for CORTEX++.

Goal:
- check that cortex4_v2.py can be imported/executed without error;
- check that the main directories exist.
"""

import os
import importlib.util

BASE_DIR = r"C:\Users\emilb\Desktop\AGI\CORTEX++"
CODE_FILE = os.path.join(BASE_DIR, "cortex4_v2.py")

REQUIRED_DIRS = [
    os.path.join(BASE_DIR, "history"),
    os.path.join(BASE_DIR, "knowledge"),
    os.path.join(BASE_DIR, "config"),
]


def check_required_dirs():
    missing = [d for d in REQUIRED_DIRS if not os.path.isdir(d)]
    if missing:
        print("[SMOKE] Missing required directories:")
        for d in missing:
            print(" -", d)
        return False
    print("[SMOKE] All required directories exist.")
    return True


def check_import_cortex():
    if not os.path.exists(CODE_FILE):
        print(f"[SMOKE] cortex4_v2.py not found at expected path: {CODE_FILE}")
        return False

    try:
        spec = importlib.util.spec_from_file_location("cortex4_v2", CODE_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[SMOKE] Error importing/executing cortex4_v2.py: {e}")
        return False

    print("[SMOKE] cortex4_v2.py loads without errors.")
    return True


def run_all_smoke_tests():
    print("=== RUNNING CORTEX++ SMOKE TESTS ===")
    ok_dirs = check_required_dirs()
    ok_import = check_import_cortex()
    all_ok = ok_dirs and ok_import
    if all_ok:
        print("[SMOKE] All smoke tests PASSED.")
    else:
        print("[SMOKE] Some smoke tests FAILED.")
    return all_ok


if __name__ == "__main__":
    success = run_all_smoke_tests()
    if not success:
        raise SystemExit(1)
