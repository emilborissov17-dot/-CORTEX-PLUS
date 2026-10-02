# -*- coding: utf-8 -*-
"""core/openclaw_door.py — the one door to the world (C-FIX-1 Part 3, 2 Oct 2026).

Emil, R43: "News, data, information, podcasts, YouTube, radio — only through
OpenClaw." Numbers from machine interfaces (World Bank, USGS, UCDP, market
prices) come through here too (§20, decided by Emil with the cost named: when the
gateway is down nothing new arrives — and that is LOUD, never silent).

get_bytes(url) / get_text(url): the page is opened in OpenClaw's own browser
(the gateway's direct tool calls, scripts/openclaw_browser.py) and its
bytes are fetched INSIDE that page — the PDF path of C-TURN-1 — so every byte this
repository receives from the network arrives through OpenClaw's browser.
Under core.fetch_standard's rules: GET only, no credentials, no private
addresses, 5 MB, 30 s, one request per host per 2 s, no fetch in the brain's turn.

A CLOSED DOOR IS LOUD. Gateway down, or browser dead after the one gateway
restart of fd0a4b7 → DoorClosed with the cause. There is NO fallback to requests
or urllib: a reader that catches its usual network errors does not catch
DoorClosed (it is not a requests exception), so it cannot quietly fill in a value.

`http` below is a requests-shaped face of this door for the class-N readers:
`from core.openclaw_door import http as requests` changes WHERE the bytes come
from and nothing about how a reader parses them.

    venv\\Scripts\\python.exe -m core.openclaw_door --selftest
"""
from __future__ import annotations

import base64
import json
import socket
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
MAX_GATEWAY_RESTARTS = 1
PROFILE = "openclaw"
# core.fetch_standard forbids credentials. Beyond its three header names, a header whose
# name says it carries a key or a token is a credential too (UCDP: x-ucdp-access-token).
# Refused by name - never sent, never silently dropped (C-FIX-1 Part 3).
CREDENTIAL_HINTS = ("token", "api-key", "apikey", "x-api", "secret", "password")


def _credential_header(name: str) -> bool:
    from core import fetch_standard as fs
    n = str(name).lower()
    return n in fs.FORBIDDEN_HEADERS or any(h in n for h in CREDENTIAL_HINTS)


class DoorClosed(BaseException):
    """Nothing can come in: the gateway or its browser is not there. Not a network
    error of the page — the door itself. A BaseException ON PURPOSE: a reader's
    `except Exception` (there are many) cannot catch it and fill in a default; it is
    caught only by name, where the caller writes nothing and says why."""

    def __init__(self, cause: str):
        super().__init__(cause)
        self.cause = cause


class DoorFetchFailed(IOError):
    """The door is open and this one fetch failed (status, CORS, size, timeout)."""


_STATE = {"browser": None, "gateway": None, "gateway_restarts": 0}


def _fetch_js(url: str) -> str:
    u = json.dumps(url)
    return ("async () => { try { const r = await fetch(" + u + ", {credentials: 'omit', redirect: 'follow'}); "
            "const b = new Uint8Array(await r.arrayBuffer()); let s = ''; "
            "for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768)); "
            "return JSON.stringify({status: r.status, type: r.headers.get('content-type') || '', url: r.url, "
            "b64: btoa(s)}); } catch (e) { return JSON.stringify({error: String(e)}); } }")


def _live(browser=None, gateway=None):
    """The browser, alive; or DoorClosed with the cause. One gateway restart per process."""
    from scripts import openclaw_browser as oc
    b = browser or _STATE["browser"] or oc.OpenClawBrowser(PROFILE)
    gw = gateway or _STATE["gateway"] or oc.Gateway()
    if browser is None:
        _STATE["browser"] = b
    if gateway is None:
        _STATE["gateway"] = gw
    if b.alive():
        return b
    if not gw.healthy():
        if _STATE["gateway_restarts"] >= MAX_GATEWAY_RESTARTS:
            raise DoorClosed("GATEWAY_DEAD: the OpenClaw gateway does not answer and was already restarted once")
        _STATE["gateway_restarts"] += 1
        gw.restart()
        if not gw.healthy():
            raise DoorClosed("GATEWAY_DEAD: the OpenClaw gateway does not answer after one restart")
    if b.alive():
        return b
    try:
        b.start()
    except Exception as exc:                                         # noqa: BLE001
        raise DoorClosed(f"SEARCHER_DEAD: OpenClaw's browser did not start ({type(exc).__name__}: {exc})"[:400])
    if not b.alive():
        raise DoorClosed("SEARCHER_DEAD: OpenClaw's browser is not running after one start")
    return b


def get_bytes(url: str, *, browser=None, gateway=None, resolve: Callable = socket.getaddrinfo, clock=None,
              max_bytes: Optional[int] = None) -> dict:
    """-> {status, bytes, content_type, final_url}. FetchRefused (core.fetch_standard)
    for what the standard forbids, DoorClosed for a closed door, DoorFetchFailed for
    one failed fetch through an open door."""
    from core import fetch_standard as fs
    from core import turn as _turn
    from scripts import openclaw_browser as oc
    max_bytes = max_bytes or fs.MAX_BYTES
    if _turn.state().get("holder") == _turn.BRAIN:
        raise fs.FetchRefused("the baton is BRAIN: no fetch in the brain's turn")
    why = fs.url_problem(url, resolve)
    if why:
        raise fs.FetchRefused(why)
    (clock or fs._CLOCK).wait((urllib.parse.urlparse(url).hostname or "").lower())
    b = _live(browser, gateway)
    try:
        b._goto(url)
        d = b._call("evaluate", "--target-id", b.tab, "--fn", _fetch_js(url),
                    "--timeout-ms", str(int(fs.TIMEOUT_S * 1000)))
    except oc.OpenClawFailed as exc:
        try:
            _live(browser, gateway)
        except DoorClosed:
            raise
        raise DoorFetchFailed(f"{url}: {exc}"[:400]) from exc
    v = json.loads(d.get("result") or "null") or {}
    if v.get("error"):
        raise DoorFetchFailed(f"{url}: in-page fetch failed: {v['error']}"[:400])
    data = base64.b64decode(v.get("b64") or "")
    if len(data) > max_bytes:
        raise fs.FetchRefused(f"body {len(data)} bytes exceeds {max_bytes}")
    final = v.get("url") or url
    why = fs.url_problem(final, resolve)
    if why:
        raise fs.FetchRefused(f"redirected to a forbidden address: {why}")
    return {"status": int(v.get("status") or 0), "bytes": data, "content_type": v.get("type") or "",
            "final_url": final}


def _charset(content_type: str) -> str:
    for part in (content_type or "").split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip().strip('"') or "utf-8"
    return "utf-8"


def get_text(url: str, **kw) -> dict:
    """-> {status, text, content_type, final_url}."""
    r = get_bytes(url, **kw)
    return {"status": r["status"], "text": r["bytes"].decode(_charset(r["content_type"]), errors="replace"),
            "content_type": r["content_type"], "final_url": r["final_url"]}


# ── a requests-shaped face of the door, for the class-N readers ──────────────
class _HTTPError(IOError):
    pass


class Response:
    def __init__(self, url: str, got: dict):
        self.url = got.get("final_url") or url
        self.status_code = got["status"]
        self.content = got["bytes"]
        self.headers = {"content-type": got.get("content_type", "")}
        self.encoding = _charset(got.get("content_type", ""))

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if not self.ok:
            e = _HTTPError(f"HTTP {self.status_code} for {self.url}")
            e.response = self                        # as requests' HTTPError carries it
            raise e

    def iter_content(self, chunk_size: int = 65536):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:                     # urllib-style
        return self.content

    @property
    def status(self) -> int:                     # urllib-style
        return self.status_code

    def getcode(self) -> int:
        return self.status_code


class _Http:
    """`from core.openclaw_door import http as requests`. GET only; credentials refused
    by core.fetch_standard; params are encoded into the URL as requests would."""
    RequestException = DoorFetchFailed
    HTTPError = _HTTPError
    ConnectionError = DoorFetchFailed
    Timeout = DoorFetchFailed

    class exceptions:                            # noqa: N801  (requests.exceptions.X)
        RequestException = DoorFetchFailed
        HTTPError = _HTTPError
        ConnectionError = DoorFetchFailed
        Timeout = DoorFetchFailed
        ReadTimeout = DoorFetchFailed
        ConnectTimeout = DoorFetchFailed

    @staticmethod
    def get(url, params=None, headers=None, timeout=None, **kw) -> Response:
        from core import fetch_standard as fs
        for k in (headers or {}):
            if _credential_header(k):
                raise fs.FetchRefused(f"header {k} carries a credential; the door sends none")
        if params:
            sep = "&" if urllib.parse.urlparse(url).query else "?"
            url = url + sep + urllib.parse.urlencode(params, doseq=True)
        return Response(url, get_bytes(url))

    class Request:
        """urllib.request.Request's shape: a URL and headers; GET only."""

        def __init__(self, url, data=None, headers=None, method=None, **kw):
            self.full_url, self.data, self.headers, self.method = url, data, dict(headers or {}), method

        def add_header(self, k, v):
            self.headers[k] = v

    @staticmethod
    def urlopen(req, timeout=None, **kw) -> Response:
        from core import fetch_standard as fs
        url = getattr(req, "full_url", None) or str(req)
        if getattr(req, "data", None) is not None or str(getattr(req, "method", "GET") or "GET").upper() != "GET":
            raise fs.FetchRefused("method is not GET")
        for k in (getattr(req, "headers", None) or {}):
            if _credential_header(k):
                raise fs.FetchRefused(f"header {k} carries a credential; the door sends none")
        r = Response(url, get_bytes(url))
        if not r.ok:                                 # as urllib does: HTTPError with code and body
            import io
            import urllib.error
            raise urllib.error.HTTPError(url, r.status_code, f"HTTP {r.status_code}", r.headers,
                                         io.BytesIO(r.content))
        return r

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, params=None, headers=None, timeout=None, **kw) -> Response:
            return _Http.get(url, params=params, headers=headers, timeout=timeout)

        def mount(self, *a, **k):
            return None

        def close(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


http = _Http()


def one_shot(url: str) -> dict:
    """A one-shot command (`python -m core.openclaw_door <url>`): the fetch, then the
    browser this process started is stopped in a `finally` (C-DOOR-1 2c)."""
    try:
        return get_bytes(url)
    finally:
        b = _STATE["browser"]
        if b is not None:
            b.stop()


def selftest() -> dict:
    from scripts import openclaw_browser as oc
    res = {"integrations": {}}
    try:
        res["integrations"]["openclaw gateway"] = "LIVE" if oc.Gateway().healthy() else "INERT (does not answer)"
    except Exception as exc:                                         # noqa: BLE001
        res["integrations"]["openclaw gateway"] = f"INERT ({type(exc).__name__})"
    res["ok"] = True
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        t0 = time.time()
        try:
            r = one_shot(sys.argv[1])
        finally:
            b = _STATE["browser"]
            for row in getattr(b, "events", None) or []:
                print(json.dumps(row, ensure_ascii=False))
        print(json.dumps({"status": r["status"], "bytes": len(r["bytes"]), "type": r["content_type"],
                          "final_url": r["final_url"], "seconds": round(time.time() - t0, 1)}))
        print("BODY[:200] " + r["bytes"][:200].decode(_charset(r["content_type"]), errors="replace"))
