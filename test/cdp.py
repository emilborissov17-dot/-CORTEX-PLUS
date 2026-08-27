"""A small Chrome DevTools Protocol client — the only judge that sees pixels.

WHY THIS EXISTS. test/cockpit_dom_harness.js runs the cockpit's JavaScript
against a strict stub and proves the code RUNS. It cannot prove anything is
VISIBLE, because it has no CSS engine — which is how the dead CLOSE button
shipped behind a test asserting `wrap.hidden === true`. The property was true.
The renderer painted the panel 742 pixels wide anyway.

So: no in-memory property is evidence here. A control worked if the RENDERER
reports that something changed — computed style, a bounding box, an element
count, the text on screen, or a request that actually left the page.

Free and already installed: the Chrome on this machine, headless, with its own
throwaway --user-data-dir. It never touches the operator's profile.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


def find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if c and pathlib.Path(c).exists():
            return c
    return shutil.which("google-chrome") or shutil.which("chromium")


def why_unavailable() -> str | None:
    """None when a sweep can run; otherwise the NAMED reason it cannot.

    A sweep that passes for lack of a browser is worse than no sweep, so this
    string is what the skip message says.
    """
    if find_chrome() is None:
        return ("no Chrome or Chromium found — looked in: "
                + ", ".join(c for c in CHROME_CANDIDATES if c))
    try:
        import websocket  # noqa: F401
    except ImportError:
        return "the websocket-client package is not installed in this venv"
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Browser:
    """One headless Chrome, one tab, its own profile. Context-managed."""

    def __init__(self, headless: bool = True):
        self.exe = find_chrome()
        self.port = free_port()
        self.profile = pathlib.Path(tempfile.mkdtemp(prefix="cockpit_sweep_"))
        self.proc = None
        self.ws = None
        self._id = 0
        self._headless = headless
        self.events: list = []

    # ── lifecycle ──────────────────────────────────────────────────────────
    def __enter__(self):
        argv = [self.exe,
                "--headless=new" if self._headless else "",
                "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking",
                "--window-size=1600,1000",
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile}",
                "about:blank"]
        self.proc = subprocess.Popen([a for a in argv if a],
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self._connect()
        return self

    def __exit__(self, *exc):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        try:
            if self.proc:
                self.proc.terminate()
                self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)

    def _connect(self, timeout: float = 25.0) -> None:
        import websocket
        deadline = time.time() + timeout
        target = None
        while time.time() < deadline:
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/json/new?about:blank",
                    method="PUT")           # Chrome >= 111 requires PUT here
                target = json.load(urllib.request.urlopen(req, timeout=5))
                break
            except Exception:
                time.sleep(0.3)
        if target is None:
            raise RuntimeError("Chrome never opened its debugging port")
        self.target_id = target["id"]
        # suppress_origin: Chrome refuses a WS handshake carrying an Origin
        # unless --remote-allow-origins is passed. Not sending one is simpler
        # and does not widen what the browser accepts.
        self.ws = websocket.create_connection(target["webSocketDebuggerUrl"],
                                              timeout=30, suppress_origin=True)
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        self.cmd("Network.enable")

    # ── protocol ───────────────────────────────────────────────────────────
    def cmd(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if "id" not in msg:
                self.events.append(msg)
                continue
            if msg["id"] != mid:
                continue
            if "error" in msg:
                raise RuntimeError(f"{method}: {msg['error']}")
            return msg.get("result", {})

    def drain(self) -> list:
        """Events that arrived while we were not looking. Never blocks."""
        import websocket
        self.ws.settimeout(0.05)
        try:
            while True:
                try:
                    msg = json.loads(self.ws.recv())
                except (websocket.WebSocketTimeoutException, OSError):
                    break
                if "id" not in msg:
                    self.events.append(msg)
        finally:
            self.ws.settimeout(30)
        return self.events

    # ── page ───────────────────────────────────────────────────────────────
    def goto(self, url: str, settle: float = 1.5) -> None:
        self.cmd("Page.navigate", url=url)
        time.sleep(settle)

    def js(self, expression: str, settle: float = 0.0):
        """Evaluate in the page and return the value. Raises page exceptions."""
        r = self.cmd("Runtime.evaluate",
                     expression=f"(() => {{ {expression} }})()",
                     returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            desc = (d.get("exception", {}).get("description")
                    or d.get("text") or str(d))
            raise RuntimeError("page threw: " + desc.split("\n")[0])
        if settle:
            time.sleep(settle)
        return r.get("result", {}).get("value")

    # ── the vocabulary the sweep is allowed to use ─────────────────────────
    VISIBLE_JS = """
      const vis = (el) => {
        if (!el) return {found:false};
        const cs = getComputedStyle(el);
        const r  = el.getBoundingClientRect();
        return {found:true,
                display: cs.display, visibility: cs.visibility,
                opacity: parseFloat(cs.opacity),
                w: Math.round(r.width), h: Math.round(r.height),
                visible: cs.display !== 'none' && cs.visibility !== 'hidden'
                         && parseFloat(cs.opacity) > 0.01
                         && r.width > 0 && r.height > 0};
      };
    """

    def visible(self, selector: str) -> dict:
        """What the RENDERER says about this element. Never reads .hidden."""
        return self.js(self.VISIBLE_JS +
                       f"return vis(document.querySelector({selector!r}));")

    def click(self, selector: str, settle: float = 0.6):
        """A real click, dispatched at the element's own centre.

        Not el.onclick() — that would prove the handler runs, which is the thing
        the DOM harness already proves and which was true while CLOSE was dead.
        """
        ok = self.js(f"""
          const el = document.querySelector({selector!r});
          if (!el) return false;
          el.scrollIntoView({{block:'center'}});
          const r = el.getBoundingClientRect();
          el.dispatchEvent(new MouseEvent('mousedown', {{bubbles:true}}));
          el.dispatchEvent(new MouseEvent('mouseup', {{bubbles:true}}));
          el.dispatchEvent(new MouseEvent('click', {{bubbles:true, cancelable:true}}));
          return true;
        """)
        time.sleep(settle)
        return ok

    def key(self, key: str, settle: float = 0.4):
        self.js(f"""
          document.dispatchEvent(new KeyboardEvent('keydown',
            {{key:{key!r}, bubbles:true}}));
          return true;
        """)
        time.sleep(settle)

    def count(self, selector: str) -> int:
        return self.js(f"return document.querySelectorAll({selector!r}).length;")

    def text(self, selector: str = "#view") -> str:
        return self.js(f"""
          const el = document.querySelector({selector!r});
          return el ? (el.innerText || el.textContent || '') : '';
        """) or ""

    # ── breaking a route on purpose (2.5) ──────────────────────────────────
    def fail_route(self, url_substring: str, status: int = 500) -> None:
        """Make one endpoint fail, at the network layer, for real.

        Not a stubbed fetch() inside the page: the point is to see what the PAGE
        does when a request it made genuinely comes back 500, including whatever
        its own error handling paints. Intercepted with the Fetch domain so the
        server is left alone.
        """
        self._failing = getattr(self, "_failing", {})
        self._failing[url_substring] = status
        self.cmd("Fetch.enable", patterns=[{"urlPattern": "*"}])

    def pump_intercepts(self, seconds: float = 2.0) -> int:
        """Answer paused requests: fail the marked ones, continue the rest."""
        import websocket
        failing = getattr(self, "_failing", {})
        failed = 0
        deadline = time.time() + seconds
        self.ws.settimeout(0.25)
        try:
            while time.time() < deadline:
                try:
                    msg = json.loads(self.ws.recv())
                except (websocket.WebSocketTimeoutException, OSError):
                    continue
                if msg.get("method") != "Fetch.requestPaused":
                    if "id" not in msg:
                        self.events.append(msg)
                    continue
                p = msg["params"]
                rid, url = p["requestId"], p["request"]["url"]
                hit = next((s for k, s in failing.items() if k in url), None)
                self.ws.settimeout(30)
                if hit:
                    self.cmd("Fetch.fulfillRequest", requestId=rid,
                             responseCode=hit,
                             responseHeaders=[{"name": "Content-Type",
                                               "value": "text/plain"}],
                             body="")
                    failed += 1
                else:
                    self.cmd("Fetch.continueRequest", requestId=rid)
                self.ws.settimeout(0.25)
        finally:
            self.ws.settimeout(30)
        return failed

    def stop_failing(self) -> None:
        self._failing = {}
        try:
            self.cmd("Fetch.disable")
        except Exception:
            pass

    def requests_since(self, mark: int) -> list:
        """URLs the PAGE actually asked for, from the Network domain."""
        self.drain()
        urls = [e["params"]["request"]["url"]
                for e in self.events
                if e.get("method") == "Network.requestWillBeSent"]
        return urls[mark:]

    def request_mark(self) -> int:
        self.drain()
        return len([e for e in self.events
                    if e.get("method") == "Network.requestWillBeSent"])
