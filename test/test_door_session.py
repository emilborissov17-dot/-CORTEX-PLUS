# -*- coding: utf-8 -*-
"""test/test_door_session.py — one browser for a whole run (C-DOOR-2 Step 3a, 2 Oct 2026).

Measured live on 2 Oct (DOOR2 report, Step 1b): one door fetch made 13 `openclaw browser`
calls at about 6 s each — status asked 7 times, start twice — and the browser was started
and stopped for every fetch.

THE RULES: inside `core.openclaw_door.session()` the browser is started once and stopped
once, in a `finally`; a fetch after the first makes no status call (navigate, wait,
evaluate); a status that only repeats what the previous call said is not asked again;
an exception inside the session still stops the browser; DoorClosed passes through by
name. The class-N readers use the door's `http` face, which keeps one session for the
whole process and stops it at exit.
The CLI call is injected and counted; nothing here reaches OpenClaw or Chrome.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from core import openclaw_door as door  # noqa: E402
from scripts import openclaw_browser as ob  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    from core import turn
    monkeypatch.setattr(turn, "state", lambda path=None: {"holder": "AGENTS"})
    monkeypatch.setattr(door, "_STATE", door._fresh_state())
    yield attempts
    _live_net.check(attempts)


class Clock:
    def wait(self, host):
        return 0.0


def public(*a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


class World:
    def __init__(self):
        self.calls, self.running, self.procs = [], False, []

    def call(self, *args):
        self.calls.append(args[0])
        if args[0] == "status":
            return {"running": self.running, "cdpPort": 18800}
        if args[0] == "start":
            self.running = True
            return {"ok": True}
        if args[0] == "stop":
            self.running = False
            return {"ok": True}
        if args[0] == "open":
            return {"tabId": "t1"}
        if args[0] == "evaluate":
            return {"result": json.dumps({"status": 200, "type": "application/json", "url": "https://d.example/x",
                                          "b64": base64.b64encode(b'{"ok": 1}').decode("ascii")})}
        return {}


class Gateway:
    def __init__(self, healthy=True):
        self._h, self.restarts = healthy, 0

    def healthy(self):
        return self._h

    def restart(self):
        self.restarts += 1


def browser(w):
    b = ob.OpenClawBrowser("openclaw", procs=lambda: list(w.procs), kill=lambda pid: None, sleep=lambda s: None)
    b._call = w.call
    return b


def fetch(n):
    return door.get_bytes(f"https://d.example/x{n}", resolve=public, clock=Clock())


def test_n_fetches_in_a_session_start_once_and_stop_once():
    w = World()
    with door.session(browser=browser(w), gateway=Gateway()):
        got = [fetch(i)["status"] for i in range(5)]
    assert got == [200] * 5
    assert w.calls.count("start") == 1 and w.calls.count("stop") == 1
    assert w.calls.count("status") <= 2, w.calls


def test_a_fetch_after_the_first_asks_no_status():
    w = World()
    with door.session(browser=browser(w), gateway=Gateway()):
        fetch(0)
        before = len(w.calls)
        fetch(1)
        assert w.calls[before:] == ["navigate", "wait", "evaluate"]


def test_one_fetch_alone_no_longer_starts_twice_or_repeats_status():
    w = World()
    with door.session(browser=browser(w), gateway=Gateway()):
        fetch(0)
    assert w.calls.count("start") == 1
    assert w.calls[:6] == ["status", "start", "open", "wait", "evaluate", "stop"], w.calls


def test_an_exception_inside_the_session_still_stops_the_browser():
    w = World()
    with pytest.raises(RuntimeError, match="reader broke"):
        with door.session(browser=browser(w), gateway=Gateway()):
            fetch(0)
            raise RuntimeError("reader broke")
    assert w.calls.count("stop") == 1


def test_door_closed_passes_through_the_session_by_name():
    w = World()
    with pytest.raises(door.DoorClosed) as e:
        with door.session(browser=browser(w), gateway=Gateway(healthy=False)):
            fetch(0)
    assert e.value.cause.startswith("GATEWAY_DEAD")


def test_the_readers_face_keeps_one_browser_for_the_process(monkeypatch):
    w = World()
    exits = []
    monkeypatch.setattr(door, "_register_exit", lambda fn: exits.append(fn))
    door._STATE.update(browser=browser(w), gateway=Gateway())
    monkeypatch.setattr(door.socket, "getaddrinfo", public)
    monkeypatch.setattr(door, "_default_clock", lambda: Clock())
    for i in range(3):
        assert door.http.get(f"https://d.example/x{i}").status_code == 200
    assert w.calls.count("start") == 1 and w.calls.count("stop") == 0 and len(exits) == 1
    exits[0]()
    assert w.calls.count("stop") == 1


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_without_the_session_every_fetch_starts_and_stops():
    w = World()
    b, gw = browser(w), Gateway()
    for i in range(3):
        with door.session(browser=b, gateway=gw):
            fetch(i)
    assert w.calls.count("start") == 3 and w.calls.count("stop") == 3


def test_mutation_without_the_known_ready_every_fetch_asks_status(monkeypatch):
    monkeypatch.setattr(door, "_known_ready", lambda b: False)
    w = World()
    with door.session(browser=browser(w), gateway=Gateway()):
        for i in range(4):
            fetch(i)
    assert w.calls.count("status") >= 5


def test_mutation_without_the_finally_an_exception_leaves_the_browser(monkeypatch):
    monkeypatch.setattr(door, "close", lambda: None)
    w = World()
    with pytest.raises(RuntimeError):
        with door.session(browser=browser(w), gateway=Gateway()):
            fetch(0)
            raise RuntimeError("reader broke")
    assert w.calls.count("stop") == 0
