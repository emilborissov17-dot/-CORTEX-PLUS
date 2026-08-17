"""CORTEX++ polyanka: k1_curve — the actual K1 measurement ('does it learn?') (isolated, stdlib, read-only).
Reads memory/predictions.json. Accuracy of VERIFIED predictions: overall / per-axis / early-vs-late.
Flags dead-scorer-era axes (CLIMATE/EDUCATION were DEAD facades until PR#2/#3) as fabricated ground and
reports the trustworthy accuracy EXCLUDING them. Also reports seal coverage (K1a tamper-evidence).
Pre-declared: accuracy trending UP (learning) or flat/down (K1 fail)? Honest about small-n + unsealed record."""
import json
from datetime import datetime
from collections import defaultdict
DEAD_ERA={"CLIMATE_GLOBAL_RISK_REVIEW","EDUCATION_CULTURE_REVIEW"}

def acc(rs):
    c=[bool(r.get('was_correct')) for r in rs]; return (sum(c)/len(c)) if c else None

def mt(r):
    try: return datetime.fromisoformat(r.get('made_at',''))
    except Exception: return None

def main(path="memory/predictions.json"):
    d=json.load(open(path,encoding="utf-8"))
    recs=[r for r in d if isinstance(r,dict) and "axis" in r]
    ver=[r for r in recs if r.get("verified")]
    sealed=sum(1 for r in recs if any(k in r for k in ("seal","sealed","hash","merkle","prev_hash")))
    print(f"[k1_curve] records: {len(recs)} | verified: {len(ver)} | pending: {len(recs)-len(ver)}")
    print(f"[k1_curve] sealed: {sealed}/{len(recs)} -> K1a tamper-evidence {'PRESENT' if recs and sealed==len(recs) else 'ABSENT'}")
    if not ver:
        print("[k1_curve] no verified predictions yet -> curve not computable. Instrument ready for when they verify."); return
    print(f"[k1_curve] overall accuracy: {acc(ver):.0%} (n={len(ver)})")
    byax=defaultdict(list)
    for r in ver: byax[r['axis']].append(r)
    for ax,rs in sorted(byax.items()):
        tag=" [DEAD-ERA: fabricated ground]" if ax in DEAD_ERA else ""
        print(f"    {ax}: {acc(rs):.0%} (n={len(rs)}){tag}")
    dated=sorted([r for r in ver if mt(r)], key=mt)
    if len(dated)>=4:
        h=len(dated)//2
        print(f"[k1_curve] learning signal: early {acc(dated[:h]):.0%} -> late {acc(dated[h:]):.0%}")
    clean=[r for r in ver if r['axis'] not in DEAD_ERA]
    if clean and len(clean)!=len(ver):
        print(f"[k1_curve] accuracy EXCLUDING dead-era ground: {acc(clean):.0%} (n={len(clean)}) <- trustworthy K1 number")

if __name__=="__main__":
    import sys; main(sys.argv[1] if len(sys.argv)>1 else "memory/predictions.json")
