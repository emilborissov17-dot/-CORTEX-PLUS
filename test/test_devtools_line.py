# -*- coding: utf-8 -*-
"""test/test_devtools_line.py — the door's direct line (C-DOOR-3 Step 1, Emil R49, 3 Oct 2026).

Measured on 2 Oct (DOOR2, Step 3c): one WebSocket to the DevTools port of the Chrome that
OpenClaw starts for profile `openclaw` fetched a page in 0.13–0.28 s; each `openclaw
browser …` CLI call costs 5–6 s. Emil's "ДА" (R49): one module may open a connection,
to the loopback address only.

THE RULES: scripts/devtools_line.py refuses any host but the loopback address BEFORE a
socket is opened (also a page address the DevTools list names elsewhere); the port comes
from OpenClaw's own `status` (cdpPort), never a constant; start and stop stay with
OpenClaw's CLI; after a start the driver uses the line for navigate / wait / evaluate;
a line that cannot be opened or fails in use is a DEVTOOLS_FALLBACK_CLI row with the
cause, and that call goes through the CLI — never silently. Sockets are injected.
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
from scripts import devtools_line as dl  # noqa: E402
from scripts import openclaw_browser as ob  # noqa: E402

BODY = b'{"ok": 1}'


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    attempts = _live_net.install(monkeypatch)
    from core import turn
    monkeypatch.setattr(turn, "state", lambda path=None: {"holder": "AGENTS"})
    monkeypatch.setattr(door, "_STATE", door._fresh_state())
    yield attempts
    _live_net.check(attempts)


class FakeWS:
    """Chrome's DevTools protocol, scripted: answers by method, a load event after navigate."""

    def __init__(self, value=None, drop_on=None):
        self.sent, self.queue, self.closed = [], [], False
        self.value = value if value is not None else json.dumps(
            {"status": 200, "type": "application/json", "url": "https://d.example/x",
             "b64": base64.b64encode(BODY).decode("ascii")})
        self.drop_on = drop_on

    def send(self, raw):
        m = json.loads(raw)
        self.sent.append(m["method"])
        if self.drop_on == m["method"]:
            raise ConnectionResetError("the remote host closed the connection")
        if m["method"] == "Page.navigate":
            self.queue += [{"id": m["id"], "result": {"frameId": "F"}}, {"method": "Page.loadEventFired"}]
        elif m["method"] == "Runtime.evaluate":
            self.queue.append({"id": m["id"], "result": {"result": {"type": "string", "value": self.value}}})
        else:
            self.queue.append({"id": m["id"], "result": {}})

    def recv(self):
        if not self.queue:
            raise TimeoutError("no message in time")
        return json.dumps(self.queue.pop(0))

    def close(self):
        self.closed = True


def page_list(port, host="127.0.0.1"):
    return [{"type": "page", "webSocketDebuggerUrl": f"ws://{host}:{port}/devtools/page/P1"}]


def line(ws=None, host="127.0.0.1", listing=None, opened=None):
    ws = ws or FakeWS()

    def connect(url, timeout):
        if opened is not None:
            opened.append(url)
        return ws
    return dl.DirectLine(18800, host=host, connect=connect,
                         list_pages=listing or (lambda h, p, t: page_list(p))), ws


# ── the module ──────────────────────────────────────────────────────────────
def test_navigate_and_evaluate_return_the_value():
    ln, ws = line()
    ln.navigate("https://d.example/x")
    ln.wait_load()
    assert json.loads(ln.evaluate("() => 1"))["status"] == 200
    assert ws.sent[:4] == ["Page.enable", "Page.setDownloadBehavior", "Page.navigate", "Runtime.evaluate"]


def test_another_host_is_refused_before_any_socket():
    opened = []
    with pytest.raises(dl.DevToolsHostRefused, match="10.0.0.5"):
        line(host="10.0.0.5", opened=opened, listing=lambda h, p, t: pytest.fail("the list was read"))
    assert opened == []


def test_a_page_address_elsewhere_is_refused_before_the_socket():
    opened = []
    with pytest.raises(dl.DevToolsHostRefused, match="evil.example"):
        line(opened=opened, listing=lambda h, p, t: page_list(p, host="evil.example"))
    assert opened == []


def test_mutation_a_module_that_accepts_another_host_would_open_it(monkeypatch):
    monkeypatch.setattr(dl, "LOOPBACK", ("127.0.0.1", "localhost", "10.0.0.5"))
    opened = []
    line(host="10.0.0.5", opened=opened, listing=lambda h, p, t: page_list(p, host="10.0.0.5"))
    assert opened, "with the host rule widened, the socket opens: the refusal above is the guard"


def test_a_dropped_connection_is_devtools_connection_failed_with_the_cause():
    ln, ws = line(FakeWS(drop_on="Runtime.evaluate"))
    with pytest.raises(dl.DevToolsConnectionFailed, match="DEVTOOLS_CONNECTION_FAILED.*closed the connection"):
        ln.evaluate("() => 1")


def test_a_call_that_gets_no_answer_times_out_by_name():
    ws = FakeWS()
    ws.send = lambda raw: ws.sent.append(json.loads(raw)["method"])        # nothing ever answers
    with pytest.raises(dl.DevToolsConnectionFailed, match="DEVTOOLS_CONNECTION_FAILED"):
        line(ws)                                      # Page.enable, the first call, gets no answer


def test_the_load_event_may_come_before_the_answer():
    ws = FakeWS()
    real = ws.send

    def send(raw):
        real(raw)
        if json.loads(raw)["method"] == "Page.navigate":
            ws.queue.reverse()                        # the event first, then the answer
    ws.send = send
    ln, _ = line(ws)
    ln.navigate("https://d.example/x")


# ── the driver ──────────────────────────────────────────────────────────────
class World:
    def __init__(self, cdp_port=18800):
        self.calls, self.running, self.cdp_port = [], False, cdp_port

    def call(self, *args):
        self.calls.append(args[0])
        if args[0] == "status":
            d = {"running": self.running}
            if self.cdp_port:
                d["cdpPort"] = self.cdp_port
            return d
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
                                          "b64": base64.b64encode(BODY).decode("ascii")})}
        return {}


def driver(w, ws=None, lines=None):
    ws = ws or FakeWS()
    lines = [] if lines is None else lines

    def factory(port):
        lines.append(port)
        return dl.DirectLine(port, connect=lambda url, timeout: ws, list_pages=lambda h, p, t: page_list(p))
    b = ob.OpenClawBrowser("openclaw", procs=lambda: [], kill=lambda pid: None, sleep=lambda s: None,
                           devtools=factory)
    b._call = w.call
    return b, ws, lines


class Gateway:
    def __init__(self, healthy=True):
        self._h = healthy

    def healthy(self):
        return self._h

    def restart(self):
        pass


def public(*a, **k):
    return [(2, 1, 6, "", ("93.184.216.34", 0))]


class Clock:
    def wait(self, host):
        return 0.0


def fetch(n):
    return door.get_bytes(f"https://d.example/x{n}", resolve=public, clock=Clock())


def test_the_port_comes_from_openclaws_status():
    w = World(cdp_port=19999)
    b, ws, lines = driver(w)
    b.start()
    assert lines == [19999]


def test_mutation_without_a_cdpport_in_status_no_constant_is_used():
    w = World(cdp_port=None)
    b, ws, lines = driver(w)
    b.start()
    assert lines == [] and [e for e in b.events if e["event"] == "DEVTOOLS_FALLBACK_CLI"]


def test_n_fetches_in_a_session_one_start_one_line_one_stop_no_cli_page_calls():
    w = World()
    b, ws, lines = driver(w)
    with door.session(browser=b, gateway=Gateway()):
        got = [fetch(i)["bytes"] for i in range(5)]
    assert got == [BODY] * 5
    assert w.calls.count("start") == 1 and w.calls.count("stop") == 1 and lines == [18800]
    assert not {"open", "navigate", "wait", "evaluate"} & set(w.calls), w.calls
    assert ws.closed


def test_a_dropped_line_falls_back_to_the_cli_with_a_row():
    w = World()
    b, ws, lines = driver(w, FakeWS(drop_on="Runtime.evaluate"))
    with door.session(browser=b, gateway=Gateway()):
        r = fetch(0)
    assert r["bytes"] == BODY and "evaluate" in w.calls
    rows = [e for e in b.events if e["event"] == "DEVTOOLS_FALLBACK_CLI"]
    assert len(rows) == 1 and "closed the connection" in rows[0]["cause"]


def test_mutation_without_the_fallback_the_dropped_line_fails_the_fetch(monkeypatch):
    def no_fallback(self, cause):
        raise dl.DevToolsConnectionFailed(cause)
    monkeypatch.setattr(ob.OpenClawBrowser, "_fallback", no_fallback)
    w = World()
    b, ws, lines = driver(w, FakeWS(drop_on="Runtime.evaluate"))
    with pytest.raises(BaseException):
        with door.session(browser=b, gateway=Gateway()):
            fetch(0)


def test_the_searcher_reads_through_the_line_too():
    w = World()
    page = json.dumps({"title": "t", "url": "https://d.example/a", "text": "A page.", "html": "<p>A page.</p>"})
    b, ws, lines = driver(w, FakeWS(value=page))
    b.start()
    r = b.read("https://d.example/a")
    assert r["page"]["text"] == "A page." and not {"open", "navigate", "evaluate"} & set(w.calls)


def test_an_exception_inside_the_session_still_stops_and_closes_the_line():
    w = World()
    b, ws, lines = driver(w)
    with pytest.raises(RuntimeError):
        with door.session(browser=b, gateway=Gateway()):
            fetch(0)
            raise RuntimeError("reader broke")
    assert w.calls.count("stop") == 1 and ws.closed


def test_door_closed_still_passes_by_name():
    w = World()
    b, ws, lines = driver(w)
    with pytest.raises(door.DoorClosed):
        with door.session(browser=b, gateway=Gateway(healthy=False)):
            fetch(0)


# ── the exception list ──────────────────────────────────────────────────────
def test_the_allowlist_carries_exactly_this_one_entry_with_the_ruling():
    files = json.loads((REPO / "config" / "network_allowlist.json").read_text(encoding="utf-8"))["files"]
    e = files["scripts/devtools_line.py"]
    assert e["class"] == "L" and e["hosts"] == ["127.0.0.1"] and e["ruling"] == "R49" and e["quote"] == "ДА"
    assert len(files) == 45


# ── a navigation that is a download (C-DOOR-3 Step 2b, live: FRED csv, ECB csvdata) ──
class DownloadWS(FakeWS):
    """Chrome's answer to a download, as read live on 3 Oct 2026: errorText net::ERR_ABORTED,
    isDownload true, and no load event ever."""

    def __init__(self, download_urls, **k):
        super().__init__(**k)
        self.download_urls, self.navigated, self.params = set(download_urls), [], []

    def send(self, raw):
        m = json.loads(raw)
        self.params.append((m["method"], m.get("params") or {}))
        if m["method"] == "Page.navigate" and m["params"]["url"] in self.download_urls:
            self.sent.append(m["method"])
            self.navigated.append(m["params"]["url"])
            self.queue.append({"id": m["id"], "result": {"frameId": "F", "errorText": "net::ERR_ABORTED",
                                                         "isDownload": True}})
            return
        if m["method"] == "Page.navigate":
            self.navigated.append(m["params"]["url"])
        super().send(raw)


CSV = "https://d.example/graph/data.csv?id=X"


def test_downloads_are_denied_on_the_line():
    ln, ws = line(DownloadWS([]))
    assert ("Page.setDownloadBehavior", {"behavior": "deny"}) in ws.params


def test_a_download_navigation_fails_at_once_by_name_not_as_a_dropped_line():
    ln, ws = line(DownloadWS([CSV]))
    with pytest.raises(dl.DevToolsNavigateFailed, match="isDownload"):
        ln.navigate(CSV)


def test_the_driver_keeps_the_line_after_a_download_navigation():
    w = World()
    b, ws, lines = driver(w, DownloadWS([CSV]))
    b.start()
    with pytest.raises(ob.OpenClawFailed):
        b._goto(CSV)
    assert b.direct is not None and not [e for e in b.events if e["event"] == "DEVTOOLS_FALLBACK_CLI"]


def test_the_door_fetches_a_download_from_its_own_origin():
    w = World()
    b, ws, lines = driver(w, DownloadWS([CSV]))
    with door.session(browser=b, gateway=Gateway()):
        r = door.get_bytes(CSV, resolve=public, clock=Clock())
    assert r["bytes"] == BODY and ws.navigated == [CSV, "https://d.example/"]
    assert not {"open", "navigate", "evaluate"} & set(w.calls)


def test_mutation_without_the_origin_step_a_download_is_a_failed_fetch(monkeypatch):
    monkeypatch.setattr(door, "_origin_of", lambda url: url)
    w = World()
    b, ws, lines = driver(w, DownloadWS([CSV]))
    with pytest.raises(door.DoorFetchFailed):
        with door.session(browser=b, gateway=Gateway()):
            door.get_bytes(CSV, resolve=public, clock=Clock())
