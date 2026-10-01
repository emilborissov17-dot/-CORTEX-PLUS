# -*- coding: utf-8 -*-
"""scripts/turns_loop.py — the turns alternate by baton, not by clock (C-TURN-1
Part 5; Emil R31: "When it issues its needs, the agents' cycle switches on. And so
they alternate.").

BRAIN -> AGENTS -> BRAIN -> ... Each turn runs through tools/cycle_witness.ps1
(the witness writes its start and exit rows to memory/witness.jsonl); the baton
moves only through core.turn.hand_over, i.e. only after a finished turn. While
the nightly cycle is live or the body says no (core.turn.blocked), the loop waits
and logs why. A stuck turn (unexplained end) stops the loop: TURN_STUCK is
recorded through the alarm channel and nothing restarts by itself (R12).

Started detached by tools/turns.bat (tools/launch_detached.ps1), at logon by the
scheduled task CORTEX_Turns. One loop at a time (memory/turns_loop.pid).

    venv\\Scripts\\python.exe scripts\\turns_loop.py            # run (normally via tools\\turns.bat)
    venv\\Scripts\\python.exe scripts\\turns_loop.py --stop     # stop after the current turn
    venv\\Scripts\\python.exe -m core.turn                      # the baton's state
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
PID = REPO / "memory" / "turns_loop.pid"
STOP = REPO / "memory" / "turns_loop.stop"
RESULT = REPO / "memory" / "turn_result.json"
LOGS = REPO / "logs" / "turns"
WITNESS = REPO / "tools" / "cycle_witness.ps1"
PY = REPO / "venv" / "Scripts" / "python.exe"
SCRIPTS = {"BRAIN": REPO / "scripts" / "turn_brain.py", "AGENTS": REPO / "scripts" / "turn_agents.py"}
WAIT_S = 300


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def witnessed(holder: str, cycle_id: str) -> int:
    """Run the holder's turn through tools/cycle_witness.ps1 and wait for it."""
    LOGS.mkdir(parents=True, exist_ok=True)
    args_b64 = base64.b64encode(json.dumps([str(SCRIPTS[holder])]).encode("utf-8")).decode("ascii")
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WITNESS),
            "-Exe", str(PY), "-ArgsB64", args_b64, "-Log", str(LOGS / f"{cycle_id.replace(':', '')}.log"),
            "-WitnessLog", str(REPO / "memory" / "witness.jsonl"), "-CycleId", cycle_id, "-WorkDir", str(REPO),
            "-Role", f"turn-{holder.lower()}"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(argv, cwd=str(REPO), env=env, stdin=subprocess.DEVNULL).returncode


def _result_since(started: str, path=None) -> dict:
    try:
        r = json.loads(Path(path or RESULT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return r if str(r.get("utc") or "") >= started else {}


def loop(max_turns: Optional[int] = None, run_turn: Optional[Callable] = None, blocked: Optional[Callable] = None,
         sleep: Callable = time.sleep, turn_path=None, result_path=None, stop_path=None, hand=None,
         log_path=None) -> dict:
    from core import turn
    run_turn = run_turn or witnessed
    stop = Path(stop_path or STOP)
    done = []
    while max_turns is None or len(done) < max_turns:
        if stop.exists():
            stop.unlink()
            turn.log({"event": "LOOP_STOPPED", "why": "stop flag"}, log_path)
            return {"stopped": "stop flag", "turns": done}
        why = blocked() if blocked else turn.blocked(log_path=log_path)
        if why:
            sleep(WAIT_S)
            continue
        s = turn.state(turn_path)
        holder = s.get("holder") or turn.BRAIN
        nxt = turn.AGENTS if holder == turn.BRAIN else turn.BRAIN
        cycle_id = f"turn-{holder.lower()}-{int(s.get('seq') or 0)}-{_now()}"
        started = _now()
        t0 = time.time()
        turn.log({"event": "TURN_START", "holder": holder, "seq": s.get("seq"), "cycle_id": cycle_id}, log_path)
        rc = run_turn(holder, cycle_id)
        res = _result_since(started, result_path)
        h = (hand or turn.hand_over)(nxt, res.get("summary") or f"{holder} turn ended rc={rc}", cycle_id,
                                     # the turn's own named cause, whatever the witness PROCESS returned:
                                     # hand_over judges the exit code from the witness's exit row
                                     cause=res.get("cause"), path=turn_path, log_path=log_path)
        done.append({"holder": holder, "cycle_id": cycle_id, "rc": rc, "seconds": round(time.time() - t0, 1),
                     "handed": h.get("handed"), "summary": res.get("summary")})
        if not h.get("handed"):
            return {"stuck": h.get("stuck"), "turns": done}
    return {"turns": done}


def main() -> int:
    if "--stop" in sys.argv:
        STOP.parent.mkdir(parents=True, exist_ok=True)
        STOP.write_text(_now(), encoding="utf-8")
        print(f"stop flag written: the loop stops after the current turn ({STOP})")
        return 0
    if PID.exists():
        # psutil, NOT os.kill(pid, 0): on Windows that call terminates the process
        import psutil
        try:
            other = int(PID.read_text().strip())
        except ValueError:
            other = None
        if other and other != os.getpid() and psutil.pid_exists(other):
            print(f"a turns loop is already running (pid {other})")
            return 0
    PID.parent.mkdir(parents=True, exist_ok=True)
    PID.write_text(str(os.getpid()))
    try:
        max_turns = int(sys.argv[sys.argv.index("--turns") + 1]) if "--turns" in sys.argv else None
        r = loop(max_turns=max_turns)
        print(json.dumps(r, indent=1, ensure_ascii=False, default=str))
        return 3 if r.get("stuck") else 0
    finally:
        try:
            if PID.read_text().strip() == str(os.getpid()):
                PID.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
