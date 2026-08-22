#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/terminal.py — A REAL TERMINAL, AND AN HONEST DESCRIPTION OF WHAT IT IS.

WHAT THIS IS
-------------
A WebSocket bridge over pywinpty (pinned 3.0.5), driving xterm.js in the page.
Three tabs: PowerShell, WSL Ubuntu, and the Claude Code CLI.

THE SECURITY POSTURE, STATED PLAINLY
--------------------------------------
    This terminal has exactly the user's own rights, the same as opening
    PowerShell directly.

That sentence is printed in the panel footer, not buried here. It is the whole
posture. What follows are the things that ARE controls, and they are about
reachability, not about capability:

  * bound to 127.0.0.1 only, never 0.0.0.0
  * a random 32-byte token generated at launch, required on the WS handshake,
    printed ONLY to the launch console — never served by an endpoint, never
    written to the log
  * every byte in and out appended to memory/cockpit_terminal.log

WHAT IS DELIBERATELY ABSENT
-----------------------------
No command parsing. No allowlist. No "dangerous command" detector.

A shell allowlist is security theatre: the process already has the user's rights,
so anything the allowlist blocks can be reached by a shell one character
different — a base64 pipe, a renamed binary, a script file. What such a filter
actually produces is a FALSE SENSE that the terminal is sandboxed, which is more
dangerous than the terminal, because it invites someone to expose the port on the
belief that it is contained. The honest control is the token and the loopback
bind; the honest description is the sentence above.

THE LOG IS EVIDENCE, NOT A CONTROL
------------------------------------
memory/cockpit_terminal.log records what happened. It does not prevent anything
and is not offered as prevention.

    venv/Scripts/python.exe -m cockpit.terminal --selftest
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import secrets
import sys
import threading
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]

HOST = "127.0.0.1"          # never 0.0.0.0. A test asserts it.
DEFAULT_WS_PORT = 5056

FOOTER_NOTICE = ("This terminal has exactly the user's own rights, the same as "
                 "opening PowerShell directly.")

# The three tabs. A tab is a command, not a capability level — see the docstring.
TABS = {
    "powershell": ["powershell.exe", "-NoLogo"],
    "wsl": ["wsl.exe"],
    "claude": ["claude"],
}

_TOKEN: Optional[str] = None
_THREAD: Optional[threading.Thread] = None
_HTTP_PORT: int = 5055          # the page's own port; set by start_bridge()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_token() -> str:
    """32 bytes from secrets. Printed to the console once and nowhere else."""
    return secrets.token_hex(32)


def current_token() -> Optional[str]:
    return _TOKEN


def append_log(direction: str, tab: str, data: str, log_path: pathlib.Path) -> None:
    """Append terminal I/O. `log_path` is REQUIRED — no default.

    The token is never written here: it is the credential, and a credential in a
    log is a credential on disk for as long as the log lives.
    """
    p = pathlib.Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", errors="replace") as fh:
        fh.write(json.dumps({"ts": _now(), "dir": direction, "tab": tab,
                             "data": data}, ensure_ascii=False) + "\n")


def allowed_origins(port: int) -> set:
    """The Origin values the browser may send. Loopback only, both spellings."""
    return {"http://127.0.0.1:{}".format(port), "http://localhost:{}".format(port)}


def origin_ok(origin: Optional[str], port: int) -> bool:
    """A SECOND lock, not the only one.

    The token is what authenticates; this stops a page on some other origin from
    opening a socket to 127.0.0.1:5056 in a browser that already has the token in
    memory. A MISSING Origin is refused too: browsers always send one on a
    WebSocket handshake, so its absence means the caller is not a browser tab and
    has no business here.
    """
    return bool(origin) and origin in allowed_origins(port)


def spawn(tab: str, cols: int = 120, rows: int = 30,
          cwd: Optional[pathlib.Path] = None):
    """Start a PTY for one tab, IN THE REPO ROOT. Raises if pywinpty is absent.

    cwd defaults to the repo rather than to wherever the server happened to be
    launched from: every command a human types here is about this repository, and
    a terminal that opens somewhere else makes the first thing they type a `cd`.
    """
    if tab not in TABS:
        raise ValueError("unknown tab {!r}; the three are {}".format(
            tab, ", ".join(TABS)))
    from winpty import PtyProcess          # noqa: PLC0415
    return PtyProcess.spawn(TABS[tab], cwd=str(cwd or BASE),
                            dimensions=(rows, cols))


async def _serve(websocket, log_path: pathlib.Path):
    """One websocket, one PTY. Token checked BEFORE anything is spawned."""
    import websockets

    try:
        hello_raw = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        hello = json.loads(hello_raw)
    except Exception:
        await websocket.close(code=1008, reason="handshake required")
        return

    # ORIGIN FIRST, then the token. Both must hold.
    origin = None
    try:
        origin = websocket.request.headers.get("Origin")
    except Exception:
        try:
            origin = websocket.request_headers.get("Origin")
        except Exception:
            origin = None
    if not origin_ok(origin, _HTTP_PORT):
        await websocket.close(code=1008, reason="bad origin")
        return

    if not _TOKEN or not secrets.compare_digest(str(hello.get("token") or ""), _TOKEN):
        # No PTY is spawned on a bad token. The refusal happens before any
        # process exists, so a wrong token costs nothing but a closed socket.
        await websocket.close(code=1008, reason="bad token")
        return

    tab = str(hello.get("tab") or "powershell")
    if tab not in TABS:
        await websocket.close(code=1008, reason="unknown tab")
        return

    try:
        pty = spawn(tab, int(hello.get("cols") or 120), int(hello.get("rows") or 30),
                    cwd=BASE)
    except Exception as e:
        await websocket.send(json.dumps(
            {"type": "error", "error": "{}: {}".format(type(e).__name__, e)}))
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    stop = threading.Event()

    def pump():
        while not stop.is_set() and pty.isalive():
            try:
                data = pty.read(4096)
            except Exception:
                break
            if not data:
                continue
            append_log("out", tab, data, log_path)
            asyncio.run_coroutine_threadsafe(
                websocket.send(json.dumps({"type": "out", "data": data})), loop)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("type") == "in":
                data = str(msg.get("data") or "")
                append_log("in", tab, data, log_path)
                pty.write(data)
            elif msg.get("type") == "resize":
                try:
                    pty.setwinsize(int(msg.get("rows") or 30),
                                   int(msg.get("cols") or 120))
                except Exception:
                    pass
    except Exception:
        pass
    finally:
        stop.set()
        try:
            pty.terminate(force=True)
        except Exception:
            pass


def start_bridge(log_path: pathlib.Path, port: int = DEFAULT_WS_PORT,
                 http_port: int = 5055) -> str:
    """Start the WS bridge in a daemon thread. Returns the token.

    `log_path` is REQUIRED — no default.
    """
    global _TOKEN, _THREAD, _HTTP_PORT
    import websockets                       # noqa: PLC0415

    _HTTP_PORT = int(http_port)
    _TOKEN = new_token()

    async def runner():
        async with websockets.serve(
                lambda ws: _serve(ws, log_path), HOST, port,
                max_size=2 ** 20):
            await asyncio.Future()

    def thread_main():
        try:
            asyncio.run(runner())
        except Exception as e:               # noqa: BLE001
            print("[TERMINAL] bridge stopped: {}: {}".format(type(e).__name__, e))

    _THREAD = threading.Thread(target=thread_main, daemon=True)
    _THREAD.start()
    return _TOKEN


def posture() -> dict:
    """What the panel footer shows. One sentence, no hedging."""
    return {
        "notice": FOOTER_NOTICE,
        "bind": HOST,
        "token_required": True,
        "token_printed_to": "the launch console only",
        "log": "memory/cockpit_terminal.log (append-only; the token is never logged)",
        "command_parsing": "none",
        "allowlist": ("none, deliberately — a shell allowlist is theatre when the "
                      "process already has the user's rights, and it invites "
                      "someone to expose the port believing it is contained"),
        "tabs": sorted(TABS),
        "cwd": str(BASE),
        "origin_check": "loopback only, and a missing Origin is refused",
    }


def _selftest() -> int:
    print("cockpit/terminal.py --selftest")
    ok = True
    try:
        import winpty
        import importlib.metadata as md
        print("  pywinpty             LIVE ({})".format(md.version("pywinpty")))
    except Exception as e:
        print("  pywinpty             INERT ({})".format(type(e).__name__))
        ok = False
    try:
        import websockets
        print("  websockets           LIVE ({})".format(websockets.__version__))
    except Exception:
        print("  websockets           INERT")
        ok = False

    import shutil
    for tab, cmd in sorted(TABS.items()):
        where = shutil.which(cmd[0])
        print("  tab {:<12} {}".format(tab, where or "NOT FOUND on PATH"))

    t1, t2 = new_token(), new_token()
    print("  token                {} hex chars, distinct across calls: {}".format(
        len(t1), t1 != t2))
    print("  bind                 {} (never 0.0.0.0)".format(HOST))
    print("  posture              {}".format(FOOTER_NOTICE))
    print("\n  NOT RUN HERE: spawning a real PTY. A cycle is live, and the PTY "
          "test is deferred until CYCLE_FINISHED.")
    print("  RESULT: {}".format("OK" if ok else "BROKEN"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
