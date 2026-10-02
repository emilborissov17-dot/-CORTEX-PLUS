# -*- coding: utf-8 -*-
"""test/test_browser_start_stop.py — C-DOOR-1 Step 2 (2 Oct 2026).

A browser start survives a leftover Chrome and a false "exited before adoption";
a stop that leaves Chrome running ends it. Seen live on 2 Oct (FIX 4B-a, CHECK
Part B): a five-hour-old Chrome of profile `openclaw` blocked the connection while
the gateway said ready; a start reported "exited before adoption" although a
working Chrome was left; `stop` answered and Chrome kept running.

THE RULES:
  start(): status says not running -> every Chrome with this profile's debugging
  port is ended by exact PID first (LEFTOVER_CHROME_ENDED); start; "exited before
  adoption" -> wait, ask status ONCE: running -> go on (START_ADOPTED_LATE); not
  running -> end leftovers, start once more; a second failure raises
  ProfileStartFailed (PROFILE_START_FAILED) with both error texts. No third attempt.
  stop(): stop, then status and the process list; Chrome still alive -> ended by
  exact PID (PROFILE_CHROME_ENDED); it cannot be ended -> ProfileStopFailed.
  Emil's own Chrome (no OpenClaw debugging port) is never touched.
The CLI call and the process list are injected; nothing here reaches OpenClaw or Chrome.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "test"))
import _live_net  # noqa: E402
from scripts import openclaw_browser as ob  # noqa: E402

ADOPT = 'openclaw browser start failed: {\'type\': \'cli_error\', \'message\': \'Managed Chrome for profile "openclaw" exited before adoption.\'}'


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    yield attempts
    _live_net.check(attempts)


class Proc:
    def __init__(self, pid, cmdline, name="chrome.exe", age_s=18000):
        self.info = {"pid": pid, "name": name, "cmdline": cmdline, "create_time": time.time() - age_s}


def chrome(pid, port=18800):
    return Proc(pid, ["chrome.exe", f"--remote-debugging-port={port}", "--user-data-dir=x"])


EMILS = Proc(7, ["chrome.exe", "--profile-directory=Default"])          # Emil's own Chrome: no debugging port


class World:
    """The gateway's answers and the process table, scripted."""

    def __init__(self, procs, running=False, start=(), stop_leaves_running=False):
        self.procs, self.running, self.start = list(procs), running, list(start)
        self.stop_leaves_running, self.calls, self.killed = stop_leaves_running, [], []

    def call(self, *args):
        self.calls.append(args[0])
        if args[0] == "status":
            return {"running": self.running, "cdpPort": 18800}
        if args[0] == "start":
            outcome = self.start.pop(0) if self.start else "ok"
            if outcome == "ok":
                self.running = True
                self.procs.append(chrome(500 + len(self.calls), 18800))
                return {"ok": True}
            if outcome == "adopted-late":
                self.running = True
                self.procs.append(chrome(600 + len(self.calls), 18800))
            raise ob.OpenClawFailed(ADOPT)
        if args[0] == "stop":
            if not self.stop_leaves_running:
                self.running = False
                self.procs = [p for p in self.procs if not ob.chrome_pids_for_port(18800, [p])]
            return {"ok": True, "running": self.running}
        return {}

    def kill(self, pid):
        self.killed.append(pid)
        self.procs = [p for p in self.procs if p.info["pid"] != pid]
        if not ob.chrome_pids_for_port(18800, self.procs):
            self.running = False


def browser(w):
    b = ob.OpenClawBrowser("openclaw", procs=lambda: list(w.procs), kill=w.kill, sleep=lambda s: None)
    b._call = w.call
    return b


def events(b):
    return [e["event"] for e in b.events]


# ── 2a: start ───────────────────────────────────────────────────────────────
def test_a_leftover_chrome_is_ended_before_start():
    w = World([chrome(208204), EMILS])
    b = browser(w)
    b.start()
    assert w.killed == [208204] and "LEFTOVER_CHROME_ENDED" in events(b)
    row = [e for e in b.events if e["event"] == "LEFTOVER_CHROME_ENDED"][0]
    assert row["pid"] == 208204 and row["port"] == 18800 and row["age_min"] >= 299
    assert w.calls.index("start") > w.calls.index("status")


def test_mutation_without_the_leftover_end_the_old_chrome_stays(monkeypatch):
    monkeypatch.setattr(ob.OpenClawBrowser, "_end_chromes", lambda self, event: [])
    w = World([chrome(208204)])
    browser(w).start()
    assert 208204 in [p.info["pid"] for p in w.procs]


def test_a_false_exited_before_adoption_with_status_running_goes_on():
    w = World([], start=["adopted-late"])
    b = browser(w)
    b.start()
    assert "START_ADOPTED_LATE" in events(b) and w.calls.count("start") == 1 and w.killed == []


def test_exited_before_adoption_and_not_running_retries_once_then_raises():
    w = World([], start=["fail", "fail"])
    b = browser(w)
    with pytest.raises(ob.ProfileStartFailed) as e:
        b.start()
    assert w.calls.count("start") == 2
    assert "PROFILE_START_FAILED" in str(e.value) and "openclaw" in str(e.value)
    assert str(e.value).count("exited before adoption") == 2


def test_exited_before_adoption_then_a_good_second_start_goes_on():
    w = World([], start=["fail", "ok"])
    b = browser(w)
    b.start()
    assert w.calls.count("start") == 2 and w.running


def test_mutation_without_the_late_adoption_check_a_working_start_is_called_failed(monkeypatch):
    monkeypatch.setattr(ob, "ADOPTION", "a message that never matches")
    w = World([], start=["adopted-late"])
    with pytest.raises(ob.OpenClawFailed):
        browser(w).start()


def test_goto_starts_through_start():
    w = World([chrome(208204)])
    b = browser(w)
    w.call = (lambda orig: (lambda *a: {"tabId": "t1"} if a[0] == "open" else orig(*a)))(w.call)
    b._call = w.call
    b._goto("https://x.example/")
    assert w.killed == [208204] and b.tab == "t1"


# ── 2b: stop ────────────────────────────────────────────────────────────────
def test_a_stop_that_answers_running_ends_the_chrome():
    w = World([chrome(221472), EMILS], running=True, stop_leaves_running=True)
    b = browser(w)
    b.stop()
    assert w.killed == [221472] and "PROFILE_CHROME_ENDED" in events(b)
    assert ob.chrome_pids_for_port(18800, w.procs) == []


def test_mutation_without_the_check_after_stop_chrome_stays(monkeypatch):
    monkeypatch.setattr(ob.OpenClawBrowser, "_end_chromes", lambda self, event: [])
    w = World([chrome(221472)], running=True, stop_leaves_running=True)
    with pytest.raises(ob.ProfileStopFailed):
        browser(w).stop()
    assert 221472 in [p.info["pid"] for p in w.procs]


def test_a_chrome_that_cannot_be_ended_raises_by_name():
    w = World([chrome(221472)], running=True, stop_leaves_running=True)
    b = browser(w)
    b.kill = lambda pid: None                       # the kill does not take
    with pytest.raises(ob.ProfileStopFailed, match="PROFILE_STOP_FAILED"):
        b.stop()


def test_a_clean_stop_kills_nothing():
    w = World([chrome(221472), EMILS], running=True)
    b = browser(w)
    b.stop()
    assert w.killed == [] and "PROFILE_CHROME_ENDED" not in events(b)


def test_a_stop_that_times_out_still_ends_the_chrome():
    w = World([chrome(221472)], running=True, stop_leaves_running=True)
    b = browser(w)
    real = w.call

    def call(*a):
        if a[0] == "stop":
            raise ob.ProfileTimeout("openclaw browser stop timed out after 60s (profile openclaw)")
        return real(*a)
    b._call = call
    b.stop()
    assert w.killed == [221472]


# ── Emil's own Chrome ───────────────────────────────────────────────────────
def test_emils_own_chrome_is_never_touched():
    w = World([EMILS, chrome(208204)], stop_leaves_running=True)
    b = browser(w)
    b.start()
    b.stop()
    assert 7 not in w.killed and 7 in [p.info["pid"] for p in w.procs]


def test_mutation_a_match_on_the_name_alone_would_take_emils_chrome():
    loose = [p.info["pid"] for p in [EMILS, chrome(208204)] if "chrome" in p.info["name"]]
    assert 7 in loose and 7 not in ob.chrome_pids_for_port(18800, [EMILS, chrome(208204)])


# ── 2c: the door's one-shot command stops what it started ───────────────────
def test_the_door_command_stops_its_browser_even_when_the_fetch_fails(monkeypatch):
    from core import openclaw_door as door
    log = []

    class B:
        def stop(self):
            log.append("stop")

    def boom(url, **k):
        door._STATE["browser"] = B()
        raise door.DoorFetchFailed("x")
    monkeypatch.setattr(door, "_STATE", {"browser": None, "gateway": None, "gateway_restarts": 0})
    monkeypatch.setattr(door, "get_bytes", boom)
    with pytest.raises(door.DoorFetchFailed):
        door.one_shot("https://x.example/")
    assert log == ["stop"]


def test_the_door_command_starts_nothing_to_stop_when_it_never_reached_a_browser(monkeypatch):
    from core import openclaw_door as door
    from core import fetch_standard as fs
    monkeypatch.setattr(door, "_STATE", {"browser": None, "gateway": None, "gateway_restarts": 0})
    monkeypatch.setattr(door, "get_bytes", lambda url, **k: (_ for _ in ()).throw(fs.FetchRefused("BRAIN")))
    with pytest.raises(fs.FetchRefused):
        door.one_shot("https://x.example/")
