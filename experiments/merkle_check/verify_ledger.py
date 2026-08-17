"""CORTEX++ polyanka: verify_ledger — auditability-moat integrity check (isolated, stdlib, read-only).
Reads memory/existence_ledger.jsonl and verifies hash-chain LINKAGE: prev_hash[i]==hash[i-1] for all i,
and seq increments by 1. A linkage break = insertion/deletion/reorder. Does NOT recompute content hashes
(that needs existence_ledger.py's exact hash fn -> next step). Pre-declared: chain intact?"""
import json

def main(path="memory/existence_ledger.jsonl"):
    rows=[]
    for line in open(path,encoding="utf-8"):
        line=line.strip()
        if line:
            try: rows.append(json.loads(line))
            except Exception: pass
    print(f"[verify_ledger] entries: {len(rows)}")
    breaks=[]; seqbreaks=[]
    for i in range(1,len(rows)):
        if rows[i].get("prev_hash")!=rows[i-1].get("hash"): breaks.append(i)
        s0,s1=rows[i-1].get("seq"),rows[i].get("seq")
        if isinstance(s0,int) and isinstance(s1,int) and s1!=s0+1: seqbreaks.append((i,s0,s1))
    missing=sum(1 for r in rows if not r.get("hash"))
    print(f"[verify_ledger] missing hash: {missing}")
    print(f"[verify_ledger] linkage breaks: {len(breaks)} {breaks[:5]}")
    print(f"[verify_ledger] seq gaps: {len(seqbreaks)} {seqbreaks[:5]}")
    ok = not breaks and not seqbreaks and missing==0
    print(f"[verify_ledger] CHAIN LINKAGE {'INTACT' if ok else 'BROKEN'} (linkage only; content-hash recompute is next step)")

if __name__=="__main__":
    import sys; main(sys.argv[1] if len(sys.argv)>1 else "memory/existence_ledger.jsonl")
