"""What the agents' turns gained, read from the two files that witness them (C-BRAIN-ASK-1, 8 Oct 2026).

Perplexity 81E/81F under Emil R73, carried out as written:
  * the brain's 3B is asked EVERY brain turn, except when the last TWO agents' turns in a
    row gained nothing (81F question 1, formulation A);
  * "gained nothing" is counted one way only (81F question 3, counting (i)): no NEED of the
    turn has a GAINED row in memory/vertical_ledger.jsonl with statements > 0. A need is what
    the turn TOOK (its TAKEN row); the maintenance cells (sub:…, src:…) that the same turn
    searches by age write GAINED rows too, and those are not needs, so they do not count. A
    dead searcher or a dead gateway leaves no GAINED row at all, so it falls under the same
    count — no second rule for it;
  * five agents' turns in a row that gained nothing are the one alarm (81E point 4, 81I F5:
    no second threshold).

An agents' turn is delimited by memory/turns_log.jsonl: its TURN_START row (holder AGENTS)
opens it, and the next row of that log closes it (HANDED_OVER, TURN_STUCK, BY_HAND, or the
next TURN_START). A turn still running has no closing row and runs to now. The GAINED rows
of memory/vertical_ledger.jsonl are placed in the turn whose window holds their ts; both
files write the same UTC format, so the comparison is on the strings.

The old rule this replaces (C-GW-1 1c, scripts/turn_brain.py nothing_new) compared the
needs' gained_statements counters against one record from the last BRAIN turn. That is a
one-turn rule on a counter the brain's own file keeps; this one reads the agents' witness
rows. test/test_brain_ask_model.py pins the formulation.

Failure paths first: a missing or unreadable file is an EMPTY list of turns, which means
"ask" (nothing is known) and "not stalled" (nothing is counted) — never a guessed turn.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
TURNS_LOG = REPO / "memory" / "turns_log.jsonl"
LEDGER = REPO / "memory" / "vertical_ledger.jsonl"

SKIP_AFTER_EMPTY_TURNS = 2     # 81F Q1 (A): the 3B is skipped only after two empty agents' turns in a row
ALARM_AFTER_EMPTY_TURNS = 5    # 81E point 4: the one alarm


def _rows(path) -> list:
    p = Path(path)
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out


def agents_turns(n: int, turns_log=None) -> list:
    """The last n agents' turns, OLDEST first: {"seq", "cycle_id", "start", "end"}; "end" is
    None for a turn with no closing row yet (the one running now)."""
    rows = _rows(turns_log or TURNS_LOG)
    out = []
    for i, r in enumerate(rows):
        if r.get("event") != "TURN_START" or r.get("holder") != "AGENTS":
            continue
        end = rows[i + 1].get("ts") if i + 1 < len(rows) else None
        out.append({"seq": r.get("seq"), "cycle_id": r.get("cycle_id"), "start": r.get("ts"), "end": end})
    return out[-n:] if n > 0 else []


CAUSES = ("SEARCHER_DEAD", "GATEWAY_TIMEOUT", "GATEWAY_DEAD", "PROFILE_DEAD", "BROWSER_DEAD",
          "SEARCHER_FAILING", "BROWSER_START_FAILED")


def gained_in(start: str, end: Optional[str], ledger=None, rows: Optional[list] = None) -> dict:
    """One turn's window of the ledger: how many of the NEEDS the turn took (TAKEN rows) have
    a GAINED row with statements > 0, their sum, the number of needs taken, the GAINED rows
    that belonged to no need (maintenance cells; not counted), and the named causes seen in
    the window (SEARCHER_DEAD, GATEWAY_TIMEOUT, ...) for the report."""
    rows = _rows(ledger or LEDGER) if rows is None else rows
    window = [r for r in rows if isinstance(r.get("ts"), str) and start and r["ts"] >= start
              and (end is None or r["ts"] < end)]
    taken = {r.get("need_id") for r in window if r.get("event") == "TAKEN"}
    gained = 0
    statements = 0
    cells = 0
    causes: list = []
    for r in window:
        ev = r.get("event")
        if ev == "GAINED":
            try:
                s = int(r.get("statements") or 0)
            except (TypeError, ValueError):
                s = 0
            if r.get("need_id") not in taken:
                cells += 1
            elif s > 0:
                gained += 1
                statements += s
        elif ev in CAUSES and ev not in causes:
            causes.append(ev)
    return {"gained_rows": gained, "statements": statements, "needs_taken": len(taken), "cell_rows": cells,
            "causes": causes}


def last_turns(n: int, turns_log=None, ledger=None) -> list:
    """The last n agents' turns, oldest first, each with its gain: {"seq", "start", "end",
    "gained_rows", "statements", "needs_taken", "cell_rows", "causes", "empty"}. "empty" is
    counting (i): no need of the turn has a GAINED row with statements > 0. The ledger is
    read once."""
    rows = _rows(ledger or LEDGER)
    out = []
    for t in agents_turns(n, turns_log):
        g = gained_in(t["start"], t["end"], rows=rows)
        out.append({**t, **g, "empty": g["gained_rows"] == 0})
    return out


def ask_model(turns: list) -> tuple:
    """-> (ask: bool, why: str). The 3B is asked unless the last SKIP_AFTER_EMPTY_TURNS
    agents' turns are all empty. Fewer turns than that on record: asked."""
    tail = turns[-SKIP_AFTER_EMPTY_TURNS:]
    if len(tail) < SKIP_AFTER_EMPTY_TURNS:
        return True, f"{len(tail)} agents' turn(s) on record (fewer than {SKIP_AFTER_EMPTY_TURNS}): asked"
    if all(t["empty"] for t in tail):
        return False, (f"the last {SKIP_AFTER_EMPTY_TURNS} agents' turns (seq {[t['seq'] for t in tail]}) "
                       f"gained no statement; causes seen: {sorted({c for t in tail for c in t['causes']})}")
    gained = [t["seq"] for t in tail if not t["empty"]]
    return True, f"agents' turn(s) seq {gained} gained statements: asked"


def stalled(turns: list) -> Optional[dict]:
    """The alarm's fact when the last ALARM_AFTER_EMPTY_TURNS agents' turns are all empty,
    else None. Fewer turns on record than that: None (nothing is counted). "run_start_seq"
    is the seq of the first turn of the whole run of empty turns ending now (as far back as
    `turns` reaches), so a stall that goes on keeps one dedup key and is told once."""
    tail = turns[-ALARM_AFTER_EMPTY_TURNS:]
    if len(tail) < ALARM_AFTER_EMPTY_TURNS or not all(t["empty"] for t in tail):
        return None
    run = []
    for t in reversed(turns):
        if not t["empty"]:
            break
        run.append(t)
    return {"turns": ALARM_AFTER_EMPTY_TURNS, "seqs": [t["seq"] for t in tail], "run_length": len(run),
            "run_start_seq": run[-1]["seq"], "first_start": tail[0]["start"], "last_start": tail[-1]["start"],
            "causes": sorted({c for t in tail for c in t["causes"]})}


STALL_LOOKBACK = 50            # turns read to find where a run of empty turns began (the dedup key)
ALL_TURNS = 10 ** 9            # last_turns(ALL_TURNS): every agents' turn on record


def selftest() -> dict:
    turns = last_turns(STALL_LOOKBACK)
    ask, why = ask_model(turns)
    return {"integrations": {"memory/turns_log.jsonl": "LIVE" if Path(TURNS_LOG).exists() else "INERT (no file)",
                             "memory/vertical_ledger.jsonl": "LIVE" if Path(LEDGER).exists() else "INERT (no file)"},
            "last_turns": turns, "ask_model": ask, "why": why, "stalled": stalled(turns), "ok": True}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2, ensure_ascii=False))
        sys.exit(0)
    print(__doc__)
