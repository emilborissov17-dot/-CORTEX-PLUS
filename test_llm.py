import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.local_llm import call_local_llm, AllBackendsFailedError

def main():
    prompt = "Reply with exactly one word: OK"
    print("[TEST] call_local_llm(max_tokens=20) ...")
    try:
        result = call_local_llm(prompt, max_tokens=20)
    except AllBackendsFailedError as e:
        print(f"[FAIL] All backends failed: {e}")
        sys.exit(1)
    if not result or not result.strip():
        print("[FAIL] call_local_llm returned empty response")
        sys.exit(1)
    print(f"[PASS] Response: {result.strip()[:200]}")

if __name__ == "__main__":
    main()
