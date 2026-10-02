# -*- coding: utf-8 -*-
"""core/turn.py — the baton: the brain's turn and the agents' turn alternate
(C-TURN-1 Part 2; Emil R31: "Cycles of the agents and cycles of the brain
alternate so they do not get in each other's way").

memory/turn.json = {holder: BRAIN | AGENTS, seq, since_utc, why, last_summary}.

take(holder)      the turn about to run claims the baton. REFUSED (TurnRefused)
                  while the other side holds it.
hand_over(to, …)  only after THIS turn's witness exit row exists (tools/cycle_witness.ps1,
                  memory/witness.jsonl, matched on cycle_id) with exit code 0 — or
                  with a non-zero code AND a named cause. An unexplained end (no
                  exit row, or a non-zero code with no cause) does NOT hand over:
                  the baton stays, memory/night_events.jsonl gets TURN_STUCK through
                  the existing alarm channel (supervisor.alarm_human), once per seq,
                  and nothing restarts by itself (R12).
blocked()         why no turn may start now, or None: the nightly cycle is live
                  (core.model_window.in_cycle, or scripts/micro_cycle.big_cycle_running),
                  or the body says no (core.homeostasis.assess can_start). No new
                  threshold is invented here. Waits are logged; the baton does not move.

    venv\\Scripts\\python.exe -m core.turn            # print the baton
    venv\\Scripts\\python.exe -m core.turn --selftest
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
STATE = REPO / "memory" / "turn.json"
LOG = REPO / "memory" / "turns_log.jsonl"
BRAIN, AGENTS = "BRAIN", "AGENTS"
HOLDERS = (BRAIN, AGENTS)


PORTION = REPO / "config" / "turn_portion.json"
PORTION_KEYS = ("verify_per_turn", "maintenance_cells_per_turn", "embed_min_free_gb", "extractor_min_free_gb")


class TurnRefused(RuntimeError):
    """The baton is held by the other side."""


class TurnNotWired(RuntimeError):
    """hand_over / blocked were called without their live checks. core.turn has none of
    its own (C-FIX-1): they are in core/turn_live.py, passed in by scripts/turns_loop.py."""


class PortionMissing(KeyError):
    """config/turn_portion.json lacks a number: refuse, never default."""


def portion(path=None) -> dict:
    """{key: value} from config/turn_portion.json (C-BRAIN-1 Part 5b)."""
    try:
        doc = json.loads(Path(path or PORTION).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PortionMissing(f"{path or PORTION} unreadable: {exc}") from exc
    out = {}
    for k in PORTION_KEYS:
        v = (doc.get(k) or {}).get("value") if isinstance(doc.get(k), dict) else None
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise PortionMissing(f"{k} has no numeric value in {path or PORTION}")
        out[k] = v
    return out


def free_gb() -> float:
    import psutil
    return psutil.virtual_memory().available / 2 ** 30


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def state(path=None) -> dict:
    try:
        return json.loads(Path(path or STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"holder": None, "seq": 0, "since_utc": None, "why": "no baton yet", "last_summary": None}


def _save(s: dict, path=None) -> None:
    p = Path(path or STATE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def log(row: dict, path=None) -> None:
    p = Path(path or LOG)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"ts": _now(), **row}, ensure_ascii=False) + "\n")


def take(holder: str, path=None, why: str = "") -> dict:
    if holder not in HOLDERS:
        raise ValueError(f"holder {holder!r} is not BRAIN or AGENTS")
    s = state(path)
    if s.get("holder") not in (None, holder):
        raise TurnRefused(f"the baton is held by {s['holder']} (seq {s.get('seq')}); {holder} may not start")
    if s.get("holder") is None:
        s.update({"holder": holder, "since_utc": _now(), "why": why or "first turn"})
        _save(s, path)
    return s


def hand_over(to: str, summary: str, cycle_id: str, cause: Optional[str] = None, path=None, log_path=None,
              witness: Optional[Callable] = None, alarm: Optional[Callable] = None) -> dict:
    """-> {"handed": bool, ...}. Never raises for a stuck turn: it records and waits."""
    if to not in HOLDERS:
        raise ValueError(f"cannot hand to {to!r}")
    if witness is None or alarm is None:
        raise TurnNotWired("hand_over needs witness= and alarm= (core.turn_live.witness / .alarm)")
    s = state(path)
    frm = s.get("holder")
    row = witness(cycle_id)
    why_stuck = None
    if row is None:
        why_stuck = f"no witness exit row for {cycle_id}"
    elif row.get("exit_code") != 0 and not (cause or "").strip():
        why_stuck = f"exit code {row.get('exit_code')} with no named cause (witness: {row.get('meaning')})"
    if why_stuck:
        detail = f"{frm} turn seq {s.get('seq')} ended unexplained: {why_stuck}. The baton stays with {frm}."
        log({"event": "TURN_STUCK", "holder": frm, "seq": s.get("seq"), "cycle_id": cycle_id, "why": why_stuck},
            log_path)
        delivered = alarm("TURN_STUCK", detail, f"TURN_STUCK:{s.get('seq')}")
        return {"handed": False, "stuck": why_stuck, "alarm": delivered, "holder": frm}
    s.update({"holder": to, "seq": int(s.get("seq") or 0) + 1, "since_utc": _now(),
              "why": f"{frm} turn finished (exit {row.get('exit_code')}{', cause: ' + cause if cause else ''})",
              "last_summary": summary})
    _save(s, path)
    log({"event": "HANDED_OVER", "from": frm, "to": to, "seq": s["seq"], "cycle_id": cycle_id,
         "exit_code": row.get("exit_code"), "cause": cause, "summary": summary}, log_path)
    return {"handed": True, "holder": to, "seq": s["seq"]}


TURN_SCRIPTS = ("turns_loop.py", "turn_agents.py", "turn_brain.py")


def _live_turn_processes(procs=None) -> list:
    """(pid, command-line argument) of every process running a turn or the turns loop."""
    if procs is None:
        import psutil
        procs = psutil.process_iter(["pid", "cmdline"])
    out = []
    for p in procs:
        for a in p.info.get("cmdline") or []:
            if str(a).replace(chr(92), "/").rsplit("/", 1)[-1] in TURN_SCRIPTS:
                out.append((p.info["pid"], str(a)))
                break
    return out


def by_hand(to: str, why: str, path=None, log_path=None, live: Optional[Callable] = None,
            _from_cli: bool = False) -> dict:
    """C-DOOR-2 Step 4: the baton moved by a human, said so in the log (BY_HAND); no witness
    row is invented. Decided: only the command line may move it (test/test_turn_by_hand.py)."""
    if not _from_cli:
        raise TurnRefused("the baton is moved by hand only from the command line: python -m core.turn --by-hand")
    if to not in HOLDERS:
        raise ValueError(f"holder {to!r} is not BRAIN or AGENTS")
    if not str(why or "").strip():
        raise TurnRefused("--why is required: a move by hand says why")
    alive = (live or _live_turn_processes)()
    if alive:
        raise TurnRefused("a turn or the turns loop is alive: "
                          + ", ".join(f"pid {pid} {cmd}" for pid, cmd in alive))
    s = state(path)
    frm = s.get("holder")
    if frm == to:
        raise TurnRefused(f"the baton is already with {to}")
    seq = int(s.get("seq") or 0) + 1
    s.update({"holder": to, "seq": seq, "since_utc": _now(), "why": f"BY_HAND from {frm}: {why}"})
    _save(s, path)
    log({"event": "BY_HAND", "from": frm, "to": to, "why": why, "seq": seq}, log_path)
    return {"moved": True, "holder": to, "seq": seq}


def main(argv=None, path=None, log_path=None, live: Optional[Callable] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        print(json.dumps(selftest(), indent=2))
        return 0
    if "--by-hand" in argv:
        i = argv.index("--by-hand")
        to = argv[i + 1] if i + 1 < len(argv) else ""
        why = argv[argv.index("--why") + 1] if "--why" in argv and argv.index("--why") + 1 < len(argv) else ""
        try:
            r = by_hand(to, why, path=path, log_path=log_path, live=live, _from_cli=True)
        except (TurnRefused, ValueError) as exc:
            print(f"REFUSED: {exc}")
            return 2
        print(json.dumps({**r, "state": state(path)}, ensure_ascii=False))
        return 0
    print(json.dumps(state(path), indent=1, ensure_ascii=False))
    return 0


def blocked(cycle: Optional[Callable] = None, body: Optional[Callable] = None, log_path=None) -> Optional[str]:
    """Why no turn may start now (logged), or None."""
    if cycle is None or body is None:
        raise TurnNotWired("blocked needs cycle= and body= (core.turn_live.cycle / .body)")
    why = cycle() or body()
    if why:
        log({"event": "WAIT", "why": why}, log_path)
    return why


def bat_steps(path) -> list:
    """The scripts a .bat file EXECUTES, in order: its `%PY% x.py` and `%PY% -m pkg.x`
    lines (as x.py), never its comments."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        tok = line.strip().split()
        if len(tok) < 2 or tok[0] != "%PY%":
            continue
        if tok[1] == "-m" and len(tok) > 2:
            out.append(tok[2].rsplit(".", 1)[-1] + ".py")
        else:
            out.append(tok[1].replace(chr(92), "/").rsplit("/", 1)[-1])
    return out


def selftest() -> dict:
    res = {"integrations": {
        "memory/turn.json": f"LIVE (holder {state().get('holder')}, seq {state().get('seq')})" if STATE.exists()
        else "INERT (no baton yet)",
        "memory/witness.jsonl": "LIVE" if (REPO / "memory" / "witness.jsonl").exists() else "INERT",
    }}
    loop = REPO / "scripts" / "turns_loop.py"
    res["integrations"]["scripts/turns_loop.py hands the baton"] = (
        "LIVE" if loop.exists() and "hand_over(" in loop.read_text(encoding="utf-8") else "INERT (no loop yet)")
    res["ok"] = True
    return res


if __name__ == "__main__":
    sys.exit(main())
