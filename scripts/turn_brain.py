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
     sub-goals with no open parent, and the engine's needs from the space.
     The 3B is asked every brain turn, except after two agents' turns in a
     row that gained no statement (core.needs_gain; Perplexity 81E/81F under
     Emil R73, C-BRAIN-ASK-1, 8 Oct 2026) — the old one-turn rule (C-GW-1 1c,
     the brain's own counters) is gone;
  5. symbols for what it was shown (core.symbols, TEXT B per sentence, at most 20);
  6. what it expects back, per open need, into memory/expectations.jsonl, and
     one row per brain turn into memory/needs_filled.jsonl: per brain need its
     gain since the last brain turn, "stale" when that gain is 0, the review
     verdict, the status, would_change as INFORMATION only (81I F3: never a
     verdict), and the new needs and symbols of the turn;
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
FILLED = REPO / "memory" / "needs_filled.jsonl"    # one row per brain turn: what each brain need gained (81E point 2)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def gained_now(doc: dict) -> dict:
    return {n["id"]: int(n.get("gained_statements") or 0) for n in doc.get("needs", []) if n.get("origin") == "brain"}


def filled_rows(doc: dict, prev: Optional[dict], rv: Optional[dict]) -> list:
    """One row per brain need for memory/needs_filled.jsonl: the gain since the last brain
    turn (no record -> the whole count), "stale" when that gain is 0 (81I point 5: a need
    that gains nothing is marked, never retired — R24), the review verdict of this turn if
    any, the status, and would_change copied as information (81I F3).
    C-SHOWN-1 (Perplexity 82B) adds what the review did with that need this turn: how many
    statements it has of its own, how many context items it was shown instead, which item ids
    were shown, how many times the agents have searched it, and whether the 3B was not asked
    because there was nothing it had not already been shown."""
    verdict_of = {v.get("id"): v.get("verdict") for v in (rv or {}).get("verdicts") or []}
    per_need = (rv or {}).get("per_need") or {}
    out = []
    for n in doc.get("needs", []):
        if n.get("origin") != "brain":
            continue
        got = int(n.get("gained_statements") or 0)
        before = int((prev or {}).get(n["id"]) or 0)
        pn = per_need.get(n["id"]) or {}
        out.append({"id": n["id"], "gained_statements": got, "gained_since_last_brain_turn": got - before,
                    "stale": got - before <= 0, "review_verdict": verdict_of.get(n["id"]),
                    "status": n.get("status"), "would_change": n.get("would_change"),
                    "linked_count": pn.get("linked_count"), "context_count": pn.get("context_count"),
                    "shown_ids": pn.get("shown_ids"), "search_attempts": pn.get("search_attempts"),
                    "reviewed_no_new_context": pn.get("reviewed_no_new_context")})
    return out


SYMBOL_ITEMS = 20                # the cap on 3B symbol calls per turn (unchanged; Perplexity 82 В5 lists it
                                 # among the numbers that need a measurement before they are called right)


def round_robin(shown: dict, cap: int = SYMBOL_ITEMS) -> list:
    """The items for the symbol step, taken ONE PER NEED in turn until the cap (Perplexity 82
    В2.4 / В5 defect 3). Before 9 Oct the first `cap` items of the flattened dict were taken,
    which on the machine meant the first four needs in the file's order and nothing else: 190
    items shown, 20 asked, the same 13 sentences for a week."""
    lists = [[it for it in (v or []) if (it or {}).get("type") == "statement"] for v in (shown or {}).values()]
    out = []
    for i in range(max((len(x) for x in lists), default=0)):
        for xs in lists:
            if i < len(xs):
                out.append(xs[i])
                if len(out) >= cap:
                    return out
    return out


def _paths_of(mod, paths, keys) -> list:
    """The files a step is declared to read, for its narration row. Never raises."""
    out = []
    for k in keys:
        try:
            v = mod._p(paths, k)
        except Exception:                                                # noqa: BLE001
            continue
        if v and "*" not in str(v):
            out.append(v)
    return out


def _counted(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return out


def run(think: Optional[Callable] = None, engine: Optional[Callable] = None, busy: Optional[Callable] = None,
        bn_paths=None, space_paths=None, sym_paths=None, read=None, linked=None,
        result_path=None, expect_path=None, turn_path=None, records_dir=None, gained_path=None,
        turns_log=None, filled_path=None) -> dict:
    """Also keeps the WHOLE turn — raw replies, needs accepted and refused, verdicts,
    symbols — in memory/turns/brain_<started>.json, so a turn can be read back verbatim.
    Every step says what it does while it runs (core.narration, Emil R60); outside an
    open narration the steps are silent and the turn is the same."""
    from core import brain_needs as bn
    from core import narration as nr
    from core import needs_gain as ng
    from core import space as sp
    from core import symbols
    from core import turn
    turn.take(turn.BRAIN, turn_path, why="the brain's turn")
    t0 = time.time()
    out = {"started_utc": _now()}
    try:
        with nr.step("space.build", "turn what the system holds (atoms, targets, needs, labels, statements) into "
                                    "MeTTa expressions",
                     reads=_paths_of(sp, space_paths, ("target_config", "needs", "labels", "store", "obs_log",
                                                       "grounded", "atoms_root"))) as s:
            b0 = sp.build(space_paths)
            s.said(f"{b0['expressions']} expressions in {b0['seconds']} s")
        with nr.step("space.derive", "run the rules on the MeTTa engine: pre-flight against the arity budgets, "
                                     "then the witness cross-check",
                     reads=_paths_of(sp, space_paths, ("rules", "proposed")) + [sp.GUARD_CONFIG]) as s:
            d = sp.derive(space_paths, engine=engine)
            s.said(f"{d['derived']} derived {d['by_rule']}; state {d.get('state')}; engine {d['seconds']} s")
    except sp.SpaceEngineFailed as exc:
        res = {"utc": _now(), "summary": f"brain turn stopped: the space engine did not run ({exc})",
               "open_needs": None, "cause": f"hyperon did not run: {exc}", "seconds": round(time.time() - t0, 1)}
        _write(result_path or RESULT, res)
        return {**out, **res, "exit": 2}
    out["space"] = {"base": b0["expressions"], "build_seconds": b0["seconds"], "derived": d["derived"],
                    "by_rule": d["by_rule"], "engine_seconds": d["seconds"]}
    derived = d["expressions"]
    with nr.step("briefing", "what the brain is shown: its sub-goals, where it is furthest from its targets, "
                             "its open needs and what the space derived",
                 reads=_paths_of(bn, bn_paths, ("needs", "grounded", "obs_log"))) as s:
        b = bn.briefing(bn_paths, derived)
        s.said(f"{len(str((b or {}).get('text') or ''))} characters shown")
    why = (busy or bn.model_busy)()
    gp = Path(gained_path or GAINED)
    try:
        prev = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = None
    # C-BRAIN-ASK-1 (81F Q1 formulation A, counting (i)): the agents' last two turns, read
    # from the loop's log and the vertical ledger — not from the brain's own counters
    turns = ng.last_turns(ng.SKIP_AFTER_EMPTY_TURNS, turns_log or turn.LOG, bn._p(bn_paths, "ledger"))
    ask, ask_why = ng.ask_model(turns)
    out["ask_model"] = {"asked": ask, "why": ask_why, "agents_turns": turns}
    rv = None
    em = None
    sy = None
    if why:
        nr.note(f"the model is not asked this turn: {why}")
        with nr.step("emit", "record the engine's needs; the brain's own question was skipped") as s:
            em = bn.emit(b, {"raw": None, "parsed": [], "error": f"model step skipped: {why}"}, bn_paths,
                         sp.needs_from(derived))
            s.said(f"open {em.get('open')}")
        out.update({"model_skipped": why, "needs": em, "review": None, "symbols": None})
    elif not ask:
        nr.note(f"the model is not asked this turn: {ask_why}")
        bn._append(bn._p(bn_paths, "ledger"), {"event": "BRAIN_NOT_ASKED", "ts": _now(), "origin": "brain",
                                               "why": ask_why, "agents_turns": [t.get("seq") for t in turns]})
        with nr.step("emit", "record the engine's needs; the brain's own question waits for a gain") as s:
            em = bn.emit(b, None, bn_paths, sp.needs_from(derived))
            s.said(f"open {em.get('open')}")
        out.update({"needs": em, "review": None, "symbols": None})
    else:
        # C-BRAIN-1 Part 2: old needs get their role; review FIRST (TEXT C, one call per
        # question), so a parent it closes frees its sub-goal; then the needs question,
        # only for the sub-goals with no open parent; then TEXT B per sentence shown.
        out["roles_given"] = bn.adopt_roles(bn_paths)
        with nr.step("review", "for each open need it asked, the brain judges what came back "
                               "(TEXT C, one 3B call per need)",
                     reads=_paths_of(bn, bn_paths, ("needs",))) as s:
            rv = bn.review(think, bn_paths, read=read, linked=linked)
            for c in rv.get("calls") or []:
                nr.note(f"{c.get('need_id')}: {c.get('question')} -> "
                        f"{c.get('verdict') or 'UNREADABLE: ' + str(c.get('unreadable'))}")
            s.said(f"{rv.get('shown', 0)} need(s) shown; verdicts "
                   f"{_counted(v.get('verdict') for v in rv.get('verdicts') or [])}")
        with nr.step("ask", "the brain's own needs, asked only for the sub-goals with no open parent "
                            "(one 3B call)") as s:
            reply, free = bn.ask_free(b, think, bn_paths)
            s.said("not asked: every sub-goal has an open parent" if reply is None else
                   f"asked for {len(free)} free sub-goal(s); "
                   + ("reply read" if reply.get("parsed") is not None else f"reply unreadable: {reply.get('unreadable')}"))
        with nr.step("emit", "record the needs: the brain's accepted or refused, the engine's from the space",
                     reads=_paths_of(bn, bn_paths, ("needs",))) as s:
            em = bn.emit(b, reply, bn_paths, sp.needs_from(derived), free)
            s.said(f"accepted {len(em.get('accepted') or [])}, refused {len(em.get('refused') or [])}, "
                   f"open {em.get('open')}")
        items = [{"id": it.get("id"), "text": it.get("text"), "region": it.get("region")}
                 for it in round_robin(rv.get("items") or {})]
        with nr.step("symbols", "each sentence it was shown becomes one expression "
                                "(TEXT B, one 3B call per sentence, at most 20)") as s:
            sy = symbols.propose(items, think, engine=engine, paths=sym_paths)
            s.said(f"asked {sy.get('asked')}, accepted {len(sy.get('accepted') or [])}, "
                   f"refused {len(sy.get('refused') or [])}")
        out.update({"reply": reply, "free_subgoals": free, "needs": em, "review": rv, "symbols": sy})
    with nr.step("record", "what it expects back per open need, what each brain need gained "
                           "(memory/needs_filled.jsonl), and the turn's result for the loop") as s:
        doc = bn.load_needs(bn_paths)
        now = gained_now(doc)
        fp = Path(filled_path or FILLED)
        fp.parent.mkdir(parents=True, exist_ok=True)
        with fp.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"ts": _now(), "turn_seq": turn.state(turn_path).get("seq"),
                                 "started_utc": out["started_utc"], "asked": ask and not why,
                                 "not_asked_why": why or (None if ask else ask_why),
                                 "needs": filled_rows(doc, prev, rv),
                                 "new_needs": [a.get("id") for a in (em or {}).get("accepted") or []],
                                 "new_symbols": len((sy or {}).get("accepted") or [])},
                                ensure_ascii=False, default=str) + "\n")
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_text(json.dumps(now), encoding="utf-8")
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
        s.said(res["summary"])
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
    from core import narration as nr
    nr.open_turn("BRAIN")
    r = None
    try:
        r = run()
    finally:
        nr.close_turn(r["exit"] if r else "none (the turn raised; its traceback is in the turn's log)",
                      (r or {}).get("summary") or "")
    print(json.dumps({k: v for k, v in r.items() if k not in ("review", "reply", "symbols", "needs")},
                     indent=1, ensure_ascii=False, default=str))
    return r["exit"]


if __name__ == "__main__":
    sys.exit(main())
