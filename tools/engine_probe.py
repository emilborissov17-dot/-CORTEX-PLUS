# -*- coding: utf-8 -*-
"""tools/engine_probe.py — the arity probe of the symbolic engine (C-GUARD-4 Step 3,
Kimi round 76 B1 / round 77 B2).

For an arity, ONE real head of that arity, alone in its own space: K atoms (head "k<i>" with
arity-1 further string arguments) plus one more that shares the first argument "k7", so the query
on "k7" has exactly two answers (arity 1: the extra atom duplicates atom 7, and hyperon returns a
duplicate twice). Each (size, repetition) runs in its OWN subprocess through venv312_metta, the way
core/space runs the engine, with a 60 s timeout. Ladder 100 / 250 / 390, three repetitions each;
a size passes only if all three exit 0 with exactly the two known answers. On a failing size the
probe steps down 300 / 200 / 100; budget = the largest wholly clean size tried; 100 failing =
the arity is forbidden. A panic is a result.

    venv\\Scripts\\python.exe tools\\engine_probe.py --arities 1 2 3 4 5 6 7 8 --write
    venv\\Scripts\\python.exe tools\\engine_probe.py --mixed
    venv\\Scripts\\python.exe tools\\engine_probe.py --realistic [--write]   # obs/8 with its real content (81B В6)
    venv\\Scripts\\python.exe tools\\engine_probe.py --selftest

REALISTIC (Perplexity round 81B В6 / 81C В4, 8 Oct 2026, under Emil R73): the ladder above varies
every column, and arity 8 was clean at 390 with it (4 Oct). The REAL obs/8 atoms repeat constant
columns (subcategory, key, period, unit, source), and that content panicked at 341 atoms and was
clean at 340 on 3 Oct (claude/reports/GUARD_2026-10-03.md). So every form of an arity gets its
own probe with its real content, and the ceiling of the arity is the MINIMUM over its forms of
the largest wholly clean size. --realistic measures the obs/8 form at 300 / 340 / 341 / 390
total atoms, three repetitions each, every size (no early stop); --write puts
min(ladder budget, realistic budget) into budgets["8"] and the measurement under probed["8"].
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import space as sp  # noqa: E402

LADDER = (100, 250, 390)
STEP_DOWN = (300, 200, 100)
REPS = 3
TIMEOUT = 60
REAL_HEADS = {1: "stale", 2: "subcategory", 3: "gap", 4: "unverified", 5: "contradiction",
              6: "need-derived", 7: "need-derived", 8: "obs"}
# The real obs/8 content: (obs id subcategory key place period value unit source) with the
# subcategory, key, period, unit and source repeating across atoms (the 3 Oct canary-obs shape).
REALISTIC_CONSTANTS = ("C0", "key", "2023", "u", "src")
REALISTIC_SIZES = (300, 340, 341, 390)          # TOTAL obs/8 atoms in the space, extra included
REALISTIC_FORM = "obs/8 realistic: constant columns C0/key/2023/u/src, varying id/place/value"


def realistic_family(total: int) -> tuple:
    """(atoms, query, the two known answers): total-1 atoms (obs "k<i>" "C0" "key" "P<i>" "2023"
    "v<i>" "u" "src") plus one that shares "k7" with ("P107", "v507"); the query on "k7" binds
    the place and the value and has exactly two answers."""
    c0, key, period, unit, src = REALISTIC_CONSTANTS

    def atom(i, place, value):
        return f'(obs "k{i}" "{c0}" "{key}" "{place}" "{period}" "{value}" "{unit}" "{src}")'
    atoms = [atom(i, f"P{i}", f"v{i}") for i in range(total - 1)]
    atoms.append(atom(7, "P107", "v507"))
    query = '!(match &self (obs "k7" $a $b $p $c $v $d $e) (hit $p $v))'
    return atoms, query, sorted(['(hit "P7" "v7")', '(hit "P107" "v507")'])


def run_realistic_case(total: int, rep: int) -> tuple:
    atoms, query, want = realistic_family(total)
    t = time.time()
    try:
        out = classify(sp.hyperon_engine("\n".join(atoms + [query]) + "\n", timeout=TIMEOUT), want)
    except sp.SpaceEngineFailed as exc:
        if "sidecar not found" in str(exc):
            raise                                  # no engine is no measurement, never a PANIC row
        out = "TIMEOUT" if "timed out" in str(exc) else "PANIC"
    return out, round(time.time() - t, 2)


def probe_realistic(sizes=REALISTIC_SIZES, runner=run_realistic_case, log=None) -> dict:
    """Every size, three repetitions, one engine process each; a size is clean only when all
    three are CLEAN; budget = the largest wholly clean size, or "forbidden" when none is."""
    runs, clean = [], []
    for size in sizes:
        ok = True
        for rep in range(1, REPS + 1):
            out, secs = runner(size, rep)
            runs.append({"size": size, "rep": rep, "outcome": out, "seconds": secs})
            if log:
                log(f"realistic obs/8 total {size} rep {rep}: {out} {secs}s")
            ok = ok and out == "CLEAN"
        if ok:
            clean.append(size)
    return {"arity": 8, "head": "obs", "form": REALISTIC_FORM, "budget": max(clean) if clean else "forbidden",
            "sizes_tried": list(sizes), "runs": runs}


def ladder_budget(rec: dict):
    """The 4 Oct ladder record carries clean_sizes (budget = the largest); a later record may carry
    budget itself; neither -> forbidden."""
    if rec.get("budget") not in (None, ""):
        return rec["budget"]
    sizes = [int(x) for x in rec.get("clean_sizes") or []]
    return max(sizes) if sizes else "forbidden"


def ceiling_for_arity8(ladder_budget, realistic_budget) -> int:
    """81B В6.2: the ceiling of an arity is the minimum over its forms; a forbidden form is 0."""
    vals = [0 if b == "forbidden" else int(b) for b in (ladder_budget, realistic_budget)]
    return min(vals)


def write_realistic(record: dict, path=None) -> int:
    """budgets["8"] = min(ladder, realistic); the measurement under probed["8"]["realistic"]; the
    4 Oct ladder record stays. Returns the ceiling written."""
    path = Path(path or sp.GUARD_CONFIG)
    d = json.loads(path.read_text(encoding="utf-8"))
    ladder = ladder_budget(d["probed"].get("8", {}))
    ceiling = ceiling_for_arity8(ladder, record["budget"])
    d["probed"].setdefault("8", {})["realistic"] = {
        **record, "hyperon": sp_hyperon_version(), "utc_date": datetime.now(timezone.utc).date().isoformat(),
        "reason": "Perplexity round 81B В6 / 81C В4 (8 Oct 2026, Emil R73): per-form probe with the real content; "
                  "ceiling = minimum over the forms of the arity"}
    d["budgets"]["8"] = ceiling
    outcomes = ", ".join(f"{s}: {sum(1 for r in record['runs'] if r['size'] == s and r['outcome'] == 'CLEAN')}/{REPS} clean"
                         for s in record["sizes_tried"])
    d["_budgets_why"]["8"] = (f"Perplexity round 81B В6 / 81C В4 (8 Oct 2026): ceiling = min over the forms of arity 8: "
                             f"all-distinct ladder {ladder} (4 Oct); realistic obs/8 with constant columns measured "
                             f"{outcomes} -> {record['budget']}; ceiling {ceiling}. Earlier: Kimi round 75 Q4 / 77 B2: 300 "
                             f"(341 atoms panic on this machine, 340 clean, 3 Oct).")
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return ceiling


def family(arity: int, head: str, k: int) -> tuple:
    """(atoms, query, the two known answers, sorted)."""
    def atom(i, second):
        rest = [f'"{second}"'] + [f'"c{j}-{i}"' for j in range(3, arity + 1)]
        return f'({head} "k{i}" ' + " ".join(rest[:arity - 1]) + ")" if arity > 1 else f'({head} "k{i}")'
    atoms = [atom(i, f"b{i}") for i in range(k)]
    if arity == 1:
        atoms.append(f'({head} "k7")')
        query = f'!(match &self ({head} "k7") (hit "k7"))'
        want = ['(hit "k7")', '(hit "k7")']
    else:
        atoms.append(atom(7, "b107"))
        holes = " ".join(["$b"] + [f"$x{j}" for j in range(3, arity + 1)])
        query = f'!(match &self ({head} "k7" {holes}) (hit $b))'
        want = sorted(['(hit "b7")', '(hit "b107")'])
    return atoms, query, sorted(want)


def classify(raw: list, want: list) -> str:
    return "CLEAN" if sorted(raw) == sorted(want) else "WRONG"


def run_case(arity: int, head: str, size: int, rep: int) -> tuple:
    atoms, query, want = family(arity, head, size)
    t = time.time()
    try:
        raw = sp.hyperon_engine("\n".join(atoms + [query]) + "\n", timeout=TIMEOUT)
        out = classify(raw, want)
    except sp.SpaceEngineFailed as exc:
        out = "TIMEOUT" if "timed out" in str(exc) else "PANIC"
    return out, round(time.time() - t, 2)


def probe_arity(arity: int, head: str, runner=run_case, log=None) -> dict:
    runs, tried, clean = [], [], []

    def size_ok(size):
        tried.append(size)
        ok = True
        for rep in range(1, REPS + 1):
            out, secs = runner(arity, head, size, rep)
            runs.append({"size": size, "rep": rep, "outcome": out, "seconds": secs})
            if log:
                log(f"arity {arity} {head} size {size} rep {rep}: {out} {secs}s")
            ok = ok and out == "CLEAN"
        if ok:
            clean.append(size)
        return ok

    failed_at = None
    for size in LADDER:
        if not size_ok(size):
            failed_at = size
            break
    if failed_at is not None and failed_at != LADDER[0]:
        for size in STEP_DOWN:
            if max(clean) < size < failed_at:
                if size_ok(size):
                    break
    budget = max(clean) if clean else "forbidden"
    return {"arity": arity, "head": head, "budget": budget, "sizes_tried": tried, "runs": runs}


def mixed(log=print) -> list:
    """The mixed case of C-GUARD-1/2 (four families, obs- and sub-shaped at 150 and 300, distinct
    heads) three times, and real-head pairs obs/8 + subcategory/2 as plain measurements."""
    def run(label, fams, reps):
        rows = []
        for rep in range(1, reps + 1):
            atoms, queries, want = [], [], []
            for arity, head, k in fams:
                a, q, w = family(arity, head, k)
                atoms += a
                queries.append(q.replace("(hit", f'(hit "{head}"'))
                want += [x.replace("(hit", f'(hit "{head}"') for x in w]
            t = time.time()
            try:
                out = classify(sp.hyperon_engine("\n".join(atoms + queries) + "\n", timeout=TIMEOUT), want)
            except sp.SpaceEngineFailed as exc:
                out = "TIMEOUT" if "timed out" in str(exc) else "PANIC"
            rows.append({"case": label, "rep": rep, "outcome": out, "seconds": round(time.time() - t, 2)})
            log(f"{label} rep {rep}: {out} {rows[-1]['seconds']}s")
        return rows
    out = run("four families obs-150 sub-150 obs-300 sub-300",
              [(8, "canary-obs-150", 150), (2, "canary-sub-150", 150),
               (8, "canary-obs-300", 300), (2, "canary-sub-300", 300)], 3)
    out += run("real heads obs/8 150 + subcategory/2 300", [(8, "obs", 150), (2, "subcategory", 300)], 3)
    out += run("real heads obs/8 100 + subcategory/2 100", [(8, "obs", 100), (2, "subcategory", 100)], 1)
    out += run("real heads obs/8 100 + subcategory/2 250", [(8, "obs", 100), (2, "subcategory", 250)], 1)
    return out


def write_config(records: list, path=None) -> None:
    path = Path(path or sp.GUARD_CONFIG)
    d = json.loads(path.read_text(encoding="utf-8"))
    ver, day = sp_hyperon_version(), datetime.now(timezone.utc).date().isoformat()
    for r in records:
        d["probed"][str(r["arity"])] = {**r, "hyperon": ver, "utc_date": day, "reason": "Kimi round 77 B2"}
        d["budgets"][str(r["arity"])] = 0 if r["budget"] == "forbidden" else r["budget"]
    path.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sp_hyperon_version() -> str:
    found = sorted((REPO / "venv312_metta" / "Lib" / "site-packages").glob("hyperon-*.dist-info"))
    return found[-1].name[len("hyperon-"):-len(".dist-info")] if found else "unknown"


def selftest() -> int:
    print(json.dumps({"integrations": {
        "venv312_metta sidecar": "LIVE" if sp.SIDECAR_PY.exists() else "INERT (missing)",
        "config/engine_guard.json": "LIVE" if sp.GUARD_CONFIG.exists() else "INERT (missing)",
        "hyperon version": sp_hyperon_version()}}, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arities", type=int, nargs="*", default=[])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--mixed", action="store_true")
    ap.add_argument("--realistic", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    records = [probe_arity(ar, REAL_HEADS[ar], log=lambda m: print(m, flush=True)) for ar in a.arities]
    for r in records:
        print(f"RESULT arity {r['arity']} ({r['head']}): budget {r['budget']}, tried {r['sizes_tried']}", flush=True)
    if a.mixed:
        print("MIXED " + json.dumps(mixed(log=lambda m: print(m, flush=True))), flush=True)
    if a.write and records:
        write_config(records)
        print("written to config/engine_guard.json", flush=True)
    if a.realistic:
        if not sp.SIDECAR_PY.exists():
            print(f"STOP: hyperon sidecar not found at {sp.SIDECAR_PY}; nothing measured, nothing written", flush=True)
            return 2
        rec = probe_realistic(log=lambda m: print(m, flush=True))
        print(f"RESULT realistic obs/8: budget {rec['budget']}, tried {rec['sizes_tried']}", flush=True)
        if a.write:
            ceiling = write_realistic(rec)
            print(f"written to config/engine_guard.json: budgets[8] = {ceiling}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
