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
SAME_CAUSE_TURNS = 3          # C-GW-1 1b: three agents' turns, same cause, nothing served -> stop


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
    # CORTEX_TURN_ID: the narrator (core/narration.py, R60) names the turn's file by the witness's cycle id
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "CORTEX_TURN_ID": cycle_id}
    return subprocess.run(argv, cwd=str(REPO), env=env, stdin=subprocess.DEVNULL).returncode


def _result_since(started: str, path=None) -> dict:
    try:
        r = json.loads(Path(path or RESULT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return r if str(r.get("utc") or "") >= started else {}


def health_for(cause: str, oc=None, log: Optional[Callable] = None) -> Optional[bool]:
    """The health check of a named cause, or None when the cause has none (then the
    loop stays stopped until it is started by hand).

    C-GW-2 (8 Oct 2026): for GATEWAY_DEAD and SEARCHER_DEAD alike the check is a REAL
    browser start, never `gateway health` alone (health said ok for 36 h on 5-7 Oct and
    for 21 h on 7-8 Oct while every start timed out). A start that the CLI answers with
    "gateway timeout" gets ONE gateway restart in this check and one more start; each is a
    row in the turns log. Still failing -> False, and the next check (WAIT_S later) may
    restart once again: the gateway is to run always and its fall is to be loud (Emil R66,
    R43), so the loop keeps trying and keeps saying so."""
    if oc is None:
        from scripts import openclaw_search as oc
    if log is None:
        from core import turn
        log = turn.log
    if not (cause.startswith("GATEWAY_DEAD") or cause.startswith("SEARCHER_DEAD")):
        return None
    gw = oc.Gateway()
    if not gw.healthy():
        return False

    def start() -> bool:
        b = oc.OpenClawBrowser()
        try:
            b.start()
            return bool(b.alive())
        finally:
            try:
                b.stop()
            except oc.OpenClawFailed:
                pass

    try:
        return start()
    except oc.GatewayTimeout as exc:
        log({"event": "GATEWAY_TIMEOUT", "where": "health check", "cause": cause[:60], "error": str(exc)[:300]})
    except oc.OpenClawFailed:
        return False
    t1 = time.time()
    gw.restart()
    log({"event": "GATEWAY_RESTARTED", "by": "health check", "seconds": round(time.time() - t1, 1),
         "healthy_after": gw.healthy()})
    try:
        return start()
    except oc.OpenClawFailed as exc:
        log({"event": "BROWSER_START_FAILED", "where": "health check after the gateway restart",
             "error": f"{type(exc).__name__}: {exc}"[:300]})
        return False


def _live_alarm(cause: str, seq=None) -> str:
    """C-GW-2 (8 Oct 2026): the stop reaches the phone. Until now it went with
    cls="TURN_STUCK", which supervisor.telegram_refusal keeps files-only, so the stops of
    5 Oct 18:27 UTC and 7 Oct 08:06 UTC were "refused" and nobody was told (R43, R66: the
    gateway's fall is to be loud). The dedup key carries the baton's seq, so a second stop
    with the same cause is not swallowed as a repeat of the first."""
    import supervisor
    if seq is None:
        from core import turn
        seq = turn.state().get("seq")
    return supervisor.alarm_human(
        "LOOP_STOPPED_SAME_CAUSE",
        f"{SAME_CAUSE_TURNS} agents' turns in a row ended with '{cause}' and served nothing. The turns loop "
        f"has stopped at seq {seq}; it resumes when the health check of that cause passes, or by hand "
        f"(tools\turns.bat).",
        dedup_key=f"LOOP_STOPPED_SAME_CAUSE:{seq}:{cause[:60]}", cls="alarm", level=supervisor.ALARM)


def same_cause(agents: list) -> Optional[str]:
    """The cause when the last SAME_CAUSE_TURNS agents' turns ended with the same named
    cause and served nothing, else None."""
    last = agents[-SAME_CAUSE_TURNS:]
    if len(last) < SAME_CAUSE_TURNS:
        return None
    causes = {a.get("cause") for a in last}
    if len(causes) != 1 or not next(iter(causes)) or any(a.get("served") for a in last):
        return None
    return next(iter(causes))


def loop(max_turns: Optional[int] = None, run_turn: Optional[Callable] = None, blocked: Optional[Callable] = None,
         sleep: Callable = time.sleep, turn_path=None, result_path=None, stop_path=None, hand=None,
         log_path=None, health: Optional[Callable] = None, alarm: Optional[Callable] = None) -> dict:
    from core import turn
    from core import turn_live
    run_turn = run_turn or witnessed
    health = health or health_for
    stop = Path(stop_path or STOP)
    done, agents = [], []
    while max_turns is None or len(done) < max_turns:
        if stop.exists():
            stop.unlink()
            turn.log({"event": "LOOP_STOPPED", "why": "stop flag"}, log_path)
            return {"stopped": "stop flag", "turns": done}
        cause = same_cause(agents)
        if cause:
            # C-GW-1 1b (Emil, 24 Sep: knowledge, not budget): a loop that learns nothing stops
            turn.log({"event": "LOOP_STOPPED_SAME_CAUSE", "cause": cause, "turns": SAME_CAUSE_TURNS}, log_path)
            (alarm or _live_alarm)(cause)
            while True:
                if stop.exists():
                    stop.unlink()
                    turn.log({"event": "LOOP_STOPPED", "why": "stop flag"}, log_path)
                    return {"stopped": "stop flag", "turns": done}
                ok = health(cause)
                if ok is None:
                    return {"stopped": "same cause", "cause": cause, "turns": done}
                if ok:
                    turn.log({"event": "LOOP_RESUMED", "cause": cause, "why": "its health check passed"}, log_path)
                    agents = []
                    break
                sleep(WAIT_S)
            continue
        why = blocked() if blocked else turn.blocked(cycle=turn_live.cycle, body=turn_live.body,
                                                     log_path=log_path)
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
        wired = {} if hand else {"witness": turn_live.witness, "alarm": turn_live.alarm}
        h = (hand or turn.hand_over)(nxt, res.get("summary") or f"{holder} turn ended rc={rc}", cycle_id,
                                     # the turn's own named cause, whatever the witness PROCESS returned:
                                     # hand_over judges the exit code from the witness's exit row
                                     cause=res.get("cause"), path=turn_path, log_path=log_path, **wired)
        done.append({"holder": holder, "cycle_id": cycle_id, "rc": rc, "seconds": round(time.time() - t0, 1),
                     "handed": h.get("handed"), "summary": res.get("summary")})
        if holder == turn.AGENTS:
            agents.append({"cause": res.get("cause"), "served": len(res.get("per_need") or [])})
        if not h.get("handed"):
            return {"stuck": h.get("stuck"), "turns": done}
    return {"turns": done}


TEST_SWITCHES = ("CORTEX_NO_REAL_MODEL", "CONTROL_NO_TELEGRAM")


def live_switches(env=None) -> list:
    """The test switches set in `env` (default: this process), as NAME=value. A live loop
    refuses to start while any is set, whatever its value."""
    env = os.environ if env is None else env
    return [f"{k}={env[k]}" for k in TEST_SWITCHES if k in env]


def main() -> int:
    if "--stop" in sys.argv:
        STOP.parent.mkdir(parents=True, exist_ok=True)
        STOP.write_text(_now(), encoding="utf-8")
        print(f"stop flag written: the loop stops after the current turn ({STOP})")
        return 0
    bad = live_switches()
    if bad:
        print(f"REFUSED: {', '.join(bad)} is set in this environment. Every turn of a loop started here "
              f"inherits it (5 Oct 2026: CORTEX_NO_REAL_MODEL=1 from a test window reached two brain turns "
              f"and no request reached the local model). Start the loop from a window where it is not set.")
        return 4
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
