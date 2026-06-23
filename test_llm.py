import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.groq_backend import call_groq, AllBackendsFailedError

def main():
    prompt = "Reply with exactly one word: OK"
    print("[TEST] call_groq(max_tokens=20) ...")
    try:
        result = call_groq(prompt, max_tokens=20)
    except AllBackendsFailedError as e:
        print(f"[FAIL] All backends failed: {e}")
        sys.exit(1)
    if not result or not result.strip():
        print("[FAIL] call_groq returned empty response")
        sys.exit(1)
    print(f"[PASS] Response: {result.strip()[:200]}")

if __name__ == "__main__":
    main()
