"""experiments/symbolic_duel — PRE-REGISTERED falsifiable test.
Does a symbolic layer (MeTTa / PeTTa+SWI-Prolog) EARN its dependency over plain
Python, for cross-axis contradiction detection? NOT 'wire the stack' (presumes the
answer; needs SWI/hyperon/Perplexity not installed). This is the DUEL, per the named
trigger in CHAIN_EXPERIMENT_PLAN sec.5: symbolic earns its place only when inter-axis
rules become conditional + MULTI-HOP.

PRE-REGISTERED CRITERION (fixed before results):
  Give Python its BEST shot: NAIVE (one pass) AND TRANSITIVE-CLOSURE (fixpoint).
  Symbolic EARNS the dependency iff ALL hold:
    (A) multi-hop contradictions exist that NAIVE python misses (else no relational need);
    (B) TRANSITIVE-CLOSURE python (a few lines) also FAILS to catch them (else Python wins);
    (C) adding a new k-axis rule costs one declarative clause vs combinatorial python.
  If closure-python catches the multi-hop cases -> Python WINS, no dependency. That is
  the likely null, and it is a real result. Symbolic then must justify on proof-trace /
  maintainability ALONE -> weak grounds for a heavy runtime on a survival-fragile system.

Symbolic arm (rules mirrored below in MeTTa syntax) is STUBBED: run once hyperon (pip
install hyperon) or SWI-Prolog+PeTTa is on the machine. Until then this reports the bar
symbolic must clear."""
from __future__ import annotations

# concern levels 0=LOW(good) .. 3=CRITICAL
RULES = [
    # cond: list of (axis, min_level); imp: (axis, min_level)
    {"cond": [("CLIM", 2), ("FOOD", 2), ("GOV", 2)], "imp": ("SOC", 2)},   # R1 flat
    {"cond": [("CLIM", 3)], "imp": ("FOOD", 2)},                            # R2 chaining
    {"cond": [("FOOD", 2), ("POV", 2)], "imp": ("SOC", 3)},                 # R3 chaining
    {"cond": [("ENER", 2), ("CLIM", 2)], "imp": ("MAT", 2)},                # R4 flat
    {"cond": [("WAT", 2), ("HEALTH", 2)], "imp": ("POV", 1)},               # R5 flat
]

# same rules a symbolic engine would consume (MeTTa-ish); mirror kept for the symbolic arm
METTA_RULES = """
(= (implies (and (>= CLIM 2) (>= FOOD 2) (>= GOV 2))) (>= SOC 2))
(= (implies (>= CLIM 3)) (>= FOOD 2))
(= (implies (and (>= FOOD 2) (>= POV 2))) (>= SOC 3))
(= (implies (and (>= ENER 2) (>= CLIM 2))) (>= MAT 2))
(= (implies (and (>= WAT 2) (>= HEALTH 2))) (>= POV 1))
"""

def naive(a):
    v = []
    for r in RULES:
        if all(a.get(ax, 0) >= lv for ax, lv in r["cond"]):
            ax, lv = r["imp"]
            if a.get(ax, 0) < lv:
                v.append((ax, a.get(ax, 0), lv))
    return sorted(set(v))

def closure(a):
    d = dict(a)
    changed = True
    while changed:
        changed = False
        for r in RULES:
            if all(d.get(ax, 0) >= lv for ax, lv in r["cond"]):
                ax, lv = r["imp"]
                if d.get(ax, 0) < lv:
                    d[ax] = lv; changed = True
    return sorted((ax, a.get(ax, 0), d[ax]) for ax in d if d[ax] > a.get(ax, 0))

def symbolic(a):
    try:
        import hyperon  # noqa
    except Exception:
        return None  # symbolic arm unavailable (needs hyperon / SWI-Prolog+PeTTa)
    raise NotImplementedError("symbolic arm scaffolded; wire hyperon runner over METTA_RULES")

CASES = [
    ("flat_contradiction",  {"CLIM": 2, "FOOD": 2, "GOV": 2, "SOC": 0}),               # naive catches
    ("multi_hop",           {"CLIM": 3, "POV": 2, "FOOD": 0, "SOC": 0}),               # only closure catches
    ("clean",               {"CLIM": 1, "FOOD": 1, "GOV": 1, "SOC": 1, "POV": 1}),     # no contradiction
]

if __name__ == "__main__":
    naive_only_miss = 0
    closure_catches_extra = 0
    for name, a in CASES:
        n, c = naive(a), closure(a)
        sym = symbolic(a)
        extra = [x for x in c if x not in n]
        if extra: naive_only_miss += 1; closure_catches_extra += 1
        print(f"[{name}] naive={len(n)} closure={len(c)} symbolic={'N/A(not installed)' if sym is None else len(sym)}")
        if n: print(f"    naive   viol: {n}")
        if c: print(f"    closure viol: {c}")
        if extra: print(f"    >>> MULTI-HOP caught only by closure: {extra}")
    print()
    print("=== PRE-REGISTERED VERDICT (Python arms only; symbolic arm pending install) ===")
    print(f"(A) multi-hop contradictions naive misses : {'YES' if naive_only_miss else 'no'}")
    print(f"(B) transitive-closure python catches them: {'YES' if closure_catches_extra else 'no'}")
    if naive_only_miss and closure_catches_extra:
        print("PROVISIONAL: relational need is REAL, but ~15 lines of closure-Python already")
        print("captures it. Symbolic (SWI/MeTTa) must beat closure on proof-trace/maintainability")
        print("ALONE -> does NOT yet earn a heavy runtime dependency. Re-run symbolic arm to test")
        print("the proof-trace + rule-add-cost claims before adopting.")
    else:
        print("PROVISIONAL: no multi-hop gap in this rule set -> Python suffices, symbolic unjustified.")
