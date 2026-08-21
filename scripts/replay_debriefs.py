#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/replay_debriefs.py — RE-JUDGE PAST DEBRIEFS THROUGH THE CURRENT GATE.

Point it at a memory/phase_debriefs/<cycle>/ directory (or let it find the most
recent one) and it re-runs every debrief in it through core/phase_debrief
.validate() as that function stands TODAY, including the swap test.

WHY THIS EXISTS AS A SCRIPT AND NOT AS A SENTENCE IN A COMMIT MESSAGE
----------------------------------------------------------------------
"Expect few or none to survive" is a prediction. This is the measurement. A gate
that is tightened without replaying what it used to accept is a gate whose
effect nobody knows: it might reject everything, which teaches the operator to
stop reading it (that already happened once here, on 21 Aug 2026, when six
debriefs were rejected six for six), or it might change nothing at all.

WHAT IS AND IS NOT HONEST ABOUT THE REPLAY
-------------------------------------------
Records written before 21 Aug 2026 do NOT store the evidence they were judged
against — that field was added in the same commit as the swap test, precisely
because its absence made this replay impossible to do exactly. For those, the
menu is rebuilt from the repo AS IT IS NOW. So the replay answers:

    "would this sentence pass the gate today?"

and not

    "would it have passed a gate that existed then?"

For SWAP_GENERIC the distinction barely matters — the failure is that the
sentence carries no phase-distinguishing number at all, which does not depend on
which day's numbers are in the menu. It is stated here anyway, because a replay
that quietly substitutes one question for another is the thing this repo is
against. Rows rebuilt this way are marked `evidence: rebuilt`.

    venv\\Scripts\\python.exe scripts/replay_debriefs.py
    venv\\Scripts\\python.exe scripts/replay_debriefs.py --dir memory/phase_debriefs/<cycle>
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import phase_debrief as pd        # noqa: E402
from core import phase_evidence as pe       # noqa: E402


def latest_dir() -> pathlib.Path | None:
    root = REPO / "memory" / "phase_debriefs"
    dirs = [d for d in root.glob("*") if d.is_dir()] if root.exists() else []
    if not dirs:
        return None
    # The newest directory that actually holds an ACCEPTED debrief: replaying a
    # directory of rejections proves nothing about a tightened gate.
    accepted = [d for d in dirs if list(d.glob("*.json"))
                and any(not f.name.endswith(".rejected.json") for f in d.glob("*.json"))]
    pool = accepted or dirs
    return sorted(pool, key=lambda d: d.stat().st_mtime)[-1]


def replay(d: pathlib.Path) -> dict:
    menus = pe.all_menus()
    rows = []
    for f in sorted(d.glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:                       # noqa: BLE001
            rows.append({"file": f.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        phase = rec.get("phase") or f.name.split(".")[0]
        debrief = rec.get("debrief")
        stored = rec.get("evidence")
        if isinstance(stored, dict) and stored:
            evidence, source = stored, "stored"
            own = set(rec.get("own_numbers") or []) or pe.own_numbers(phase, menus)
        else:
            evidence, source = menus.get(phase, {"phase": phase}), "rebuilt"
            own = pe.own_numbers(phase, menus)

        if not isinstance(debrief, dict):
            rows.append({"file": f.name, "phase": phase, "was": rec.get("accepted"),
                         "now": False, "evidence": source,
                         "why": ["no debrief object on the record"]})
            continue
        now, reasons = pd.validate(debrief, evidence, own)
        rows.append({
            "file": f.name, "phase": phase,
            "was": bool(rec.get("accepted")), "now": bool(now),
            "evidence": source,
            "what": str((debrief or {}).get("what") or "")[:160],
            "why": reasons,
        })
    return {"dir": str(d), "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    d = pathlib.Path(args.dir) if args.dir else latest_dir()
    if d is None or not d.exists():
        print("no debrief directory found")
        return 1

    out = replay(d)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    rows = out["rows"]
    was_ok = [r for r in rows if r.get("was")]
    survived = [r for r in was_ok if r.get("now")]
    print(f"replaying {out['dir']}")
    print(f"  {len(rows)} debrief(s); {len(was_ok)} were accepted at the time\n")
    for r in rows:
        flag = "SURVIVES" if r.get("now") else "REJECTED"
        print(f"  {r['phase']:<11} was={'ACCEPTED' if r.get('was') else 'rejected':<8} "
              f"now={flag:<8} evidence={r.get('evidence')}")
        if r.get("what"):
            print(f"      what: {r['what']}")
        for why in (r.get("why") or [])[:2]:
            print(f"      why:  {why[:200]}")
    print(f"\n  VERDICT: {len(survived)} of {len(was_ok)} previously accepted "
          f"debrief(s) survive the swap test.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
