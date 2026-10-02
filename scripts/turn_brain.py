# -*- coding: utf-8 -*-
"""scripts/turn_brain.py — the brain's turn (C-TURN-1 Part 3; Emil R31).

Run through tools/cycle_witness.ps1 by scripts/turns_loop.py. No network: while
the baton is BRAIN, core.fetch_standard refuses every fetch.

Order:
  1. build the space (core.space.build) and run the rules (core.space.derive);
  2. the briefing (core.brain_needs.briefing) with what the space derived, its
     fact lines numbered;
  3. its verdicts on its open parents and searched needs (TEXT C, one call per
     question), shown first what was fetched for each; STILL_OPEN with a narrower
     question makes a child need (C-BRAIN-1 Part 2);
  4. the brain's needs (cortex-l1b-3b, schema-bound), asked only for the
     sub-goals with no open parent, and the engine's needs from the space;
  5. symbols for what it was shown (core.symbols, TEXT B per sentence, at most 20);
  6. what it expects back, per open need, into memory/expectations.jsonl;
  7. memory/turn_result.json {summary, open_needs, cause} for the loop, which
     hands the baton to AGENTS once the witness has the exit row.

Exit codes: 0 done; 2 the space engine (hyperon) did not run — the cause is
named in turn_result.json, so the loop may hand over; anything else is
unexplained and the baton stays (core.turn.hand_over).

    venv\\Scripts\\python.exe scripts\\turn_brain.py
    venv\\Scripts\\python.exe scripts\\turn_brain.py --selftest
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
RESULT = REPO / "memory" / "turn_result.json"
RECORDS = REPO / "memory" / "turns"
EXPECT = REPO / "memory" / "expectations.jsonl"
GAINED = REPO / "memory" / "brain_gained.json"     # what each brain need had gained at the last brain turn


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def gained_now(doc: dict) -> dict:
    return {n["id"]: int(n.get("gained_statements") or 0) for n in doc.get("needs", []) if n.get("origin") == "brain"}


def nothing_new(prev: Optional[dict], now: dict) -> bool:
    """C-GW-1 1c: True when the brain's turn has a record of what its needs had gained
    last time and none of them has gained anything since. No record -> False (ask)."""
    if prev is None:
        return False
    return not any(v > int(prev.get(k) or 0) for k, v in now.items())


def run(think: Optional[Callable] = None, engine: Optional[Callable] = None, busy: Optional[Callable] = None,
        bn_paths=None, space_paths=None, sym_paths=None, read=None, linked=None,
        result_path=None, expect_path=None, turn_path=None, records_dir=None, gained_path=None) -> dict:
    """Also keeps the WHOLE turn — raw replies, needs accepted and refused, verdicts,
    symbols — in memory/turns/brain_<started>.json, so a turn can be read back verbatim."""
    from core import brain_needs as bn
    from core import space as sp
    from core import symbols
    from core import turn
    turn.take(turn.BRAIN, turn_path, why="the brain's turn")
    t0 = time.time()
    out = {"started_utc": _now()}
    try:
        b0 = sp.build(space_paths)
        d = sp.derive(space_paths, engine=engine)
    except sp.SpaceEngineFailed as exc:
        res = {"utc": _now(), "summary": f"brain turn stopped: the space engine did not run ({exc})",
               "open_needs": None, "cause": f"hyperon did not run: {exc}", "seconds": round(time.time() - t0, 1)}
        _write(result_path or RESULT, res)
        return {**out, **res, "exit": 2}
    out["space"] = {"base": b0["expressions"], "build_seconds": b0["seconds"], "derived": d["derived"],
                    "by_rule": d["by_rule"], "engine_seconds": d["seconds"]}
    derived = d["expressions"]
    b = bn.briefing(bn_paths, derived)
    why = (busy or bn.model_busy)()
    gp = Path(gained_path or GAINED)
    try:
        prev = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = None
    now = gained_now(bn.load_needs(bn_paths))
    out["nothing_new"] = nothing_new(prev, now)
    if why:
        em = bn.emit(b, {"raw": None, "parsed": [], "error": f"model step skipped: {why}"}, bn_paths, sp.needs_from(derived))
        out.update({"model_skipped": why, "needs": em, "review": None, "symbols": None})
    elif out["nothing_new"]:
        # C-GW-1 1c: nothing was gained for any of its needs since its last turn -> no model call
        bn._append(bn._p(bn_paths, "ledger"), {"event": "BRAIN_NOTHING_NEW", "ts": _now(), "origin": "brain",
                                               "needs": len(now)})
        em = bn.emit(b, None, bn_paths, sp.needs_from(derived))
        out.update({"needs": em, "review": None, "symbols": None})
    else:
        # C-BRAIN-1 Part 2: old needs get their role; review FIRST (TEXT C, one call per
        # question), so a parent it closes frees its sub-goal; then the needs question,
        # only for the sub-goals with no open parent; then TEXT B per sentence shown.
        out["roles_given"] = bn.adopt_roles(bn_paths)
        rv = bn.review(think, bn_paths, read=read, linked=linked)
        reply, free = bn.ask_free(b, think, bn_paths)
        em = bn.emit(b, reply, bn_paths, sp.needs_from(derived), free)
        items = [{"id": it.get("id"), "text": it.get("text")} for its in (rv.get("items") or {}).values()
                 for it in its if it.get("type") == "statement"]
        sy = symbols.propose(items, think, engine=engine, paths=sym_paths)
        out.update({"reply": reply, "free_subgoals": free, "needs": em, "review": rv, "symbols": sy})
    doc = bn.load_needs(bn_paths)
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text(json.dumps(gained_now(doc)), encoding="utf-8")
    open_ = [n for n in doc.get("needs", []) if n.get("status") in (bn.OPEN, bn.STILL_OPEN)]
    ep = Path(expect_path or EXPECT)
    ep.parent.mkdir(parents=True, exist_ok=True)
    with ep.open("a", encoding="utf-8", newline="\n") as fh:
        for n in open_:
            if n.get("origin") == "brain":
                fh.write(json.dumps({"ts": _now(), "need_id": n["id"], "expects": n.get("expects")},
                                    ensure_ascii=False) + "\n")
    res = {"utc": _now(), "open_needs": len(open_), "cause": None, "seconds": round(time.time() - t0, 1),
           "summary": f"brain turn: {len(open_)} open need(s) "
                      f"({sum(1 for n in open_ if n.get('origin') == 'brain')} brain, "
                      f"{sum(1 for n in open_ if n.get('origin') == 'engine')} engine); "
                      f"space {out['space']['base']} base / {out['space']['derived']} derived"}
    _write(result_path or RESULT, res)
    record = {**out, **res, "exit": 0}
    _write(Path(records_dir or RECORDS) / f"brain_{out['started_utc'].replace(':', '')}.json", record)
    return record


def _write(p, doc: dict) -> None:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def selftest() -> dict:
    from core import turn
    return {"integrations": {"core.turn baton": f"holder {turn.state().get('holder')}",
                             "memory/turn_result.json": "LIVE" if RESULT.exists() else "INERT (no brain turn yet)"},
            "ok": True}


def main() -> int:
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        return 0
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k not in ("review", "reply", "symbols", "needs")},
                     indent=1, ensure_ascii=False, default=str))
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
