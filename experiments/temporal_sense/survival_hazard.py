"""CORTEX++ polyanka: survival_hazard — chain-1 anticipation input (isolated, stdlib, read-only).
Reads memory/existence_ledger.jsonl. Per cycle (matched by cycle_id): FINISHED(duration) or
DIED(elapsed = died_ts - started_ts). Builds P(reach T | started) so a bounded instinct can read
'at elapsed E, historical P(finish)=p -> if low, checkpoint now'.
Pre-declared: do deaths cluster in elapsed time (hazard signal) or spread (window is exogenous
human lid-close -> policy = always-checkpoint, not predict-death-from-start)."""
import json
from datetime import datetime

def load(p):
    rows=[]
    for line in open(p,encoding="utf-8"):
        line=line.strip()
        if line:
            try: rows.append(json.loads(line))
            except: pass
    return rows

def dt(ts):
    try: return datetime.fromisoformat(ts)
    except: return None

def cycles(rows):
    starts={}; out=[]
    for r in rows:
        cid=r.get("cycle_id"); ev=r.get("event")
        if ev=="CYCLE_STARTED" and cid: starts[cid]=dt(r.get("ts"))
        elif ev=="CYCLE_FINISHED" and cid:
            d=r.get("duration_sec")
            if d is None and cid in starts and dt(r.get("ts")): d=(dt(r.get("ts"))-starts[cid]).total_seconds()
            out.append(("FINISHED",d,None))
        elif ev=="CYCLE_DIED" and cid and cid in starts:
            end=dt(r.get("ts"))
            if end: out.append(("DIED",(end-starts[cid]).total_seconds(),r.get("last_step")))
    return out

def main(path="memory/existence_ledger.jsonl"):
    cy=cycles(load(path))
    fin=[c for c in cy if c[0]=="FINISHED" and c[1]]
    died=[c for c in cy if c[0]=="DIED" and c[1] is not None]
    print(f"[survival_hazard] resolved cycles: {len(cy)} | finished: {len(fin)} | died: {len(died)}")
    if fin:
        ds=sorted(c[1] for c in fin); print(f"  finish dur sec: min {ds[0]:.0f} med {ds[len(ds)//2]:.0f} max {ds[-1]:.0f}")
    if died:
        es=sorted(c[1] for c in died)
        print("  DIED elapsed sec:", [round(x) for x in es])
        print("  DIED last steps :", [c[2] for c in died])
    allc=[c[1] for c in cy if c[1] is not None]; n=len(allc)
    print("  P(survive >= T | started):")
    for t in [300,600,1200,1800,2400,3000,3600,3780]:
        reached=sum(1 for v in allc if v>=t)
        print(f"    T={t/60:4.0f}min : {reached}/{n} = {reached/n:.0%}" if n else "    n/a")
    print("[survival_hazard] read: if deaths spread across elapsed, window is exogenous (lid-close)")
    print("  -> bounded instinct = checkpoint-frequent ALWAYS, not predict-death; confirms reflex+recovery > prediction.")

if __name__=="__main__":
    import sys; main(sys.argv[1] if len(sys.argv)>1 else "memory/existence_ledger.jsonl")
