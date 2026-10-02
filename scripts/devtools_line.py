# -*- coding: utf-8 -*-
"""scripts/devtools_line.py — the door's direct line to OpenClaw's own Chrome
(C-DOOR-3, 3 Oct 2026; Emil R49: "ДА").

One WebSocket to the DevTools endpoint of the Chrome that OpenClaw starts for a
profile, on the loopback address only. OpenClaw still starts and stops that Chrome
(scripts/openclaw_browser.py); this line only navigates, waits for the load and
evaluates, so a page is opened in a fraction of a second instead of the 5–6 s each
`openclaw browser …` call costs (DOOR2_2026-10-02.md, Steps 1b and 3c).

Decided: a host other than the loopback address is refused by name before any
socket is opened, and so is a page address the DevTools list names elsewhere
(test/test_devtools_line.py holds both).

    venv\\Scripts\\python.exe -m scripts.devtools_line --selftest
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Callable, Optional

LOOPBACK = ("127.0.0.1", "localhost")
CALL_TIMEOUT_S = 30


class DevToolsHostRefused(ValueError):
    """DEVTOOLS_HOST_REFUSED: the direct line goes to the loopback address only."""


class DevToolsConnectionFailed(RuntimeError):
    """DEVTOOLS_CONNECTION_FAILED: the line could not be opened, dropped, or got no answer in time."""


class DevToolsNavigateFailed(RuntimeError):
    """DEVTOOLS_NAVIGATE_FAILED: Chrome answered the navigation with an error (a download, an
    unreachable address); the line itself is fine."""


def _host_of(ws_url: str) -> str:
    rest = ws_url.split("://", 1)[-1]
    return rest.split("/", 1)[0].rsplit(":", 1)[0].strip("[]").lower()


def _refuse_unless_loopback(host: str, what: str) -> None:
    if str(host).lower() not in LOOPBACK:
        raise DevToolsHostRefused(f"DEVTOOLS_HOST_REFUSED: {what} {host!r} is not the loopback address")


def _list_pages(host: str, port: int, timeout: float) -> list:
    with urllib.request.urlopen(f"http://{host}:{int(port)}/json/list", timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _connect(url: str, timeout: float):
    import websocket                            # websocket-client, already in venv
    return websocket.create_connection(url, timeout=timeout, suppress_origin=True)


class DirectLine:
    """navigate(url), wait_load(), evaluate(js) -> value, close(). Every call has a timeout;
    every failure is DevToolsConnectionFailed with the cause."""

    def __init__(self, port: int, host: str = "127.0.0.1", connect: Optional[Callable] = None,
                 list_pages: Optional[Callable] = None, timeout_s: float = CALL_TIMEOUT_S):
        _refuse_unless_loopback(host, "host")
        if not isinstance(port, int) or not 0 < port < 65536:
            raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: no valid port ({port!r})")
        self.host, self.port, self.timeout_s, self._id = host, port, timeout_s, 0
        try:
            pages = (list_pages or _list_pages)(host, port, timeout_s)
            page = next(p for p in pages if p.get("type") == "page" and p.get("webSocketDebuggerUrl"))
        except DevToolsHostRefused:
            raise
        except StopIteration:
            raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: no page target on port {port}") from None
        except Exception as exc:                                     # noqa: BLE001
            raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: the page list on port {port}: "
                                           f"{type(exc).__name__}: {exc}"[:300]) from exc
        url = page["webSocketDebuggerUrl"]
        _refuse_unless_loopback(_host_of(url), "page address")
        try:
            self.ws = (connect or _connect)(url, timeout_s)
        except Exception as exc:                                     # noqa: BLE001
            raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: connect: {type(exc).__name__}: {exc}"[:300]) \
                from exc
        self._call("Page.enable")
        # C-DOOR-3 Step 2b: a navigation that is a download is written to disk by Chrome. Denied.
        self._call("Page.setDownloadBehavior", {"behavior": "deny"})

    def _call(self, method: str, params: Optional[dict] = None, until_event: Optional[str] = None) -> dict:
        self._id += 1
        want, deadline, answer, seen = self._id, time.time() + self.timeout_s, None, until_event is None
        try:
            self.ws.send(json.dumps({"id": want, "method": method, "params": params or {}}))
            while time.time() < deadline:
                m = json.loads(self.ws.recv())
                if m.get("id") == want:
                    if m.get("error"):
                        raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: {method}: {m['error']}"[:300])
                    answer = m.get("result") or {}
                elif until_event and m.get("method") == until_event:
                    seen = True                      # the event may come before or after the answer
                if answer is not None and (seen or answer.get("errorText")):
                    return answer                    # an error answer brings no load event
        except DevToolsConnectionFailed:
            raise
        except Exception as exc:                                     # noqa: BLE001
            raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: {method}: {type(exc).__name__}: {exc}"[:300]) \
                from exc
        raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: {method}: no answer in {self.timeout_s}s")

    def navigate(self, url: str) -> None:
        r = self._call("Page.navigate", {"url": url}, until_event="Page.loadEventFired")
        if r.get("errorText"):
            raise DevToolsNavigateFailed(f"DEVTOOLS_NAVIGATE_FAILED: {url}: {r['errorText']}"
                                         f"{' (isDownload)' if r.get('isDownload') else ''}"[:300])

    def wait_load(self) -> None:
        """navigate() returns after the page's load event; kept as the driver's wait step."""
        return None

    def evaluate(self, js: str):
        r = self._call("Runtime.evaluate", {"expression": f"({js})()", "awaitPromise": True,
                                            "returnByValue": True})
        if r.get("exceptionDetails"):
            raise DevToolsConnectionFailed(f"DEVTOOLS_CONNECTION_FAILED: evaluate: "
                                           f"{r['exceptionDetails'].get('text')}"[:300])
        return (r.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:                                            # noqa: BLE001
            pass


def selftest() -> dict:
    res = {"integrations": {}}
    try:
        import websocket
        res["integrations"]["websocket-client"] = f"LIVE ({websocket.__version__})"
    except ImportError:
        res["integrations"]["websocket-client"] = "INERT (not installed)"
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
