#!/usr/bin/env python3
"""
agents/core/metta_verifier.py
MeTTa верификатор — проверява дали предложено действие
е в съответствие с визията на CORTEX++.
"""
import hyperon

VISION_RULES = """
(= (safe-action $action) 
   (if (increases-dignity $action) True False))

(= (increases-dignity education) True)
(= (increases-dignity healthcare) True)  
(= (increases-dignity clean-water) True)
(= (increases-dignity renewable-energy) True)
(= (increases-dignity food-security) True)
(= (increases-dignity transparency) True)

(= (harmful $action)
   (if (enables-domination $action) True False))

(= (enables-domination surveillance) True)
(= (enables-domination manipulation) True)
(= (enables-domination weapons) True)
"""

def verify_action(action: str) -> dict:
    m = hyperon.MeTTa()
    m.run(VISION_RULES)
    try:
        result = m.run(f"!(safe-action {action.lower().replace(' ', '-')})")
        is_safe = str(result) == "[[True]]"
        harmful = m.run(f"!(harmful {action.lower().replace(' ', '-')})")
        is_harmful = str(harmful) == "[[True]]"
        return {
            "action": action,
            "safe": is_safe,
            "harmful": is_harmful,
            "verdict": "APPROVE" if is_safe and not is_harmful else "REVIEW",
        }
    except Exception as e:
        return {"action": action, "verdict": "UNKNOWN", "error": str(e)}

def run():
    tests = ["education", "clean-water", "surveillance", "renewable-energy", "weapons"]
    print("[METTA] Testing vision alignment:")
    for t in tests:
        r = verify_action(t)
        print(f"  {t}: {r['verdict']}")

if __name__ == "__main__":
    run()
