"""MeTTa cross-axis consistency audit over LIVE CORTEX scores.
Reads output/cortex_scores_latest.json, maps score->concern (0=low..3=critical),
encodes cross-axis rules, lets MeTTa derive implied floors TRANSITIVELY, and flags any
axis scored BELOW what the others imply -- with proof. Requires: pip install hyperon.

Run:  venv/Scripts/python.exe -m pip install hyperon
      venv/Scripts/python.exe experiments/symbolic_duel/metta_reason_live.py
"""
import json, sys
from hyperon import MeTTa

PATH = sys.argv[1] if len(sys.argv) > 1 else "output/cortex_scores_latest.json"
scores = json.load(open(PATH, encoding="utf-8"))["scores"]

def concern(score):
    if score is None: return None
    if score >= 0.75: return 0
    if score >= 0.55: return 1
    if score >= 0.35: return 2
    return 3

levels = {ax: concern(v.get("score")) for ax, v in scores.items() if v.get("score") is not None}

# Cross-axis rules: (id src need target floor) in concern units. SEED SET -- expand this
# into a real rulebook grounded in cortex_scoring_engine.CORRELATION_MATRIX + domain logic.
RULES = [
    ("R1", "CLIMATE_GLOBAL_RISK_REVIEW", 2, "MATERIALS_WASTE_REVIEW", 2),
    ("R2", "CLIMATE_GLOBAL_RISK_REVIEW", 2, "FOOD_REVIEW", 2),
    ("R3", "FOOD_REVIEW", 2, "SOCIAL_RELATIONS_REVIEW", 2),
    ("R4", "INEQUALITY_POVERTY_REVIEW", 2, "SOCIAL_RELATIONS_REVIEW", 2),
    ("R5", "WATER_REVIEW", 2, "HUMAN_WELL_BEING_REVIEW", 2),
    ("R6", "ENERGY_REVIEW", 2, "PLANETARY_POTENTIAL_REVIEW", 2),
]

m = MeTTa(); prog = []
for ax, c in levels.items(): prog.append(f"(concern {ax} {c})")
for rid, src, need, tgt, fl in RULES: prog.append(f"(rule {rid} {src} {need} {tgt} {fl})")
prog.append("(= (eff $ax) (match &self (concern $ax $v) $v))")
prog.append("(= (eff $ax) (match &self (rule $r $src $need $ax $fl) (if (>= (eff $src) $need) $fl (empty))))")
prog.append("(= (why $ax) (match &self (rule $r $src $need $ax $fl) (if (>= (eff $src) $need) (fired $r from $src floor $fl) (empty))))")
m.run("\n".join(prog))
_vals = lambda res: [a for g in res for a in g]
NAMES = {0: "LOW", 1: "MOD", 2: "HIGH", 3: "CRIT"}

print("=== LIVE concern levels (from today's real scores) ===")
for ax in sorted(levels): print(f"  {NAMES[levels[ax]]:4} ({levels[ax]})  {ax}  score={scores[ax]['score']}")

print("\n=== MeTTa cross-axis consistency audit ===")
found = 0
for ax in sorted({r[3] for r in RULES}):
    if ax not in levels: continue
    derived = [int(str(x)) for x in _vals(m.run(f"!(eff {ax})"))]
    floor = max(derived) if derived else levels[ax]
    if floor > levels[ax]:
        found += 1
        print(f"  INCONSISTENCY: {ax} scored {NAMES[levels[ax]]} but rules imply >= {NAMES[floor]}")
        for w in _vals(m.run(f"!(why {ax})")): print(f"      proof: {w}")
if not found:
    print("  none under the current seed rules. Grow the rulebook to make it bite.")
