#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/morning_read.py — read what the machines already wrote.

WHY THIS EXISTS, AND IT IS THE ONLY REASON.

On 13 September 2026 six machines honestly recorded their own failure and nobody
read any of them. The collector wrote "search returned 0 pages — the eye failed,
not the world" on 41 of its last 42 runs. The source ledger wrote 326 refusals.
The existence ledger wrote CYCLE_KILLED. The contracts wrote their violations. The
black box wrote its first error in its life. Every one of those sentences was
correct, timestamped, and unread.

Without a reader, in a year we will have sixty machines honestly recording that
nobody reads them.

THE SEVENTH MACHINE. claude/CLAUDE_ERRORS.md is Claude's own register of its own
mistakes, kept by hand, and it is here under exactly the same rule as the other
six: a machine that records its failure and is not read has recorded nothing. Its
newest row is printed unconditionally, beside the three worst sentences rather
than competing with them — the other five are ranked against each other because
only one of them can be the worst thing that happened last night, while this one
is not that kind of claim. Its contents are not this program's business: it reads
the last row of the table and prints it verbatim.

So: no judgement, no summary, no scoring. The three worst sentences, verbatim, in
a declared severity order — a cycle killed outranks a contract violated, which
outranks an internal error, which outranks a blind eye, which outranks one
refused source. The ordering is the only opinion in the file and it is stated
once, here, rather than computed per sentence.

TWO HONEST LIMITS.
  * It reads the NEWEST matching entry in each file, not "yesterday's". These logs
    are append-only, so the newest failure is the one that matters this morning;
    date filtering would cost more lines than the whole file has.
  * Twenty-five lines of code. Twenty was the budget for five sources; the sixth
    cost five, counted after the fact rather than claimed before it. This docstring is not code — the reason had to
    live at the head of the file, and it is longer than the program. That is the
    correct proportion for a thing whose entire purpose is that somebody reads it.

    venv\\Scripts\\python.exe tools\\morning_read.py
"""
import json, pathlib
MEM = pathlib.Path(__file__).resolve().parents[1] / "memory"
SPEC = [("existence_ledger.jsonl", "CYCLE KILLED", lambda d: d.get("event") == "CYCLE_KILLED", "reason"),
        ("output_contracts_latest.json", "CONTRACT VIOLATED", lambda d: True, "why"),
        ("blackbox.jsonl", "BLACKBOX ERROR", lambda d: d.get("phase") == "error", None),
        ("collector_runs.jsonl", "COLLECTOR BLIND", lambda d: bool(d.get("browse_failed")), "browse_failed"),
        ("source_lifecycle_ledger.jsonl", "SOURCE REFUSED", lambda d: d.get("event") == "refusal", "reason")]
REG = MEM.parent / "claude" / "CLAUDE_ERRORS.md"
_reg = [[c.strip() for c in l.strip().strip("|").split("|")]
        for l in (REG.read_text(encoding="utf-8", errors="replace") if REG.is_file() else "").splitlines()
        if l.startswith("|") and "твърдях" not in l and set(l.strip()) - set("|- ")]
def _j(line):
    try: return json.loads(line)
    except Exception: return None
def _rows(name):
    text = (MEM / name).read_text(encoding="utf-8", errors="replace") if (MEM / name).is_file() else ""
    if name.endswith(".json"):
        return [v for v in ((_j(text) or {}).get("violations") or []) if v.get("severity") != "note"]
    return [d for d in (_j(l) for l in text.splitlines()) if isinstance(d, dict)]
found = [(lab, str(r[-1].get(f) if f else r[-1])[:300]) for n, lab, hit, f in SPEC
         for r in [[d for d in _rows(n) if hit(d)]] if r]
print("MORNING READ — the machines wrote these; until now nobody read them." + ("" if found else "  (nothing recorded)"))
for label, sentence in found[:3]:
    print(f"  {label}: {sentence}")
if _reg: print("  CLAUDE ERROR: " + " — ".join(_reg[-1][:3])[:300])
