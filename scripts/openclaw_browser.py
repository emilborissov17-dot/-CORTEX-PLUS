# -*- coding: utf-8 -*-
"""scripts/openclaw_browser.py — OpenClaw's browser and gateway, driven through the
`openclaw` CLI (moved out of scripts/openclaw_search.py, C-FIX-1, 2 Oct 2026).

core/openclaw_door.py needs only these; scripts/openclaw_search.py also stores and
ingests pages (core.knowledge), which the door must not import (test/test_llm_text.py:
no consumer reaches the model door past llm_parse). openclaw_search re-exports every
name here.

    venv\Scripts\python.exe -m scripts.openclaw_browser --selftest
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SEARCH_URL = "https://html.duckduckgo.com/html/?q={q}"
_LINKS_JS = ("() => JSON.stringify(Array.from(document.querySelectorAll('a.result__a'))"
             ".map(a => ({url: a.href, title: a.innerText})))")
_PDF_JS = ("async () => { const r = await fetch(location.href); const b = new Uint8Array(await r.arrayBuffer()); "
           "let s = ''; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode.apply(null, b.subarray(i, i + 32768)); "
           "return JSON.stringify({status: r.status, type: r.headers.get('content-type'), b64: btoa(s)}); }")
_TEXT_JS = ("() => JSON.stringify({title: document.title, url: location.href, "
            "text: document.body ? document.body.innerText : '', "
            "html: document.documentElement ? document.documentElement.outerHTML : ''})")


class OpenClawFailed(RuntimeError):
    pass


class ProfileTimeout(OpenClawFailed):
    """A call for one browser profile got no answer in time (C-FIX-1 4B-a: a profile
    can stop answering inside the gateway while the gateway's own health answers)."""


def openclaw_cmd() -> list:
    """`node <npm root>/openclaw/openclaw.mjs` — called directly, NOT through the
    openclaw.cmd shim: cmd.exe would read the `>` of a JS arrow function as a
    redirect."""
    import shutil
    shim = shutil.which("openclaw")
    if shim:
        mjs = Path(shim).resolve().parent / "node_modules" / "openclaw" / "openclaw.mjs"
        node = shutil.which("node")
        if mjs.exists() and node:
            return [node, str(mjs)]
    raise OpenClawFailed("the openclaw CLI (node + openclaw.mjs) was not found")


class OpenClawBrowser:
    """The live driver: `openclaw browser <cmd> --json` through the gateway."""

    def __init__(self, profile: str = "openclaw", timeout_s: int = 60):
        self.profile, self.timeout_s, self.tab = profile, timeout_s, None
        self.timed_out, self.cdp_port = False, None

    def _call(self, *args) -> dict:
        if any(a is None for a in args):
            # 1 Oct 2026 20:20: a tab id of None reached subprocess and the agents turn died
            # with a TypeError (TURN_STUCK). A missing argument is a failed call, by name.
            raise OpenClawFailed(f"openclaw browser {args[0] if args else '?'}: a None argument {list(args)!r}")
        cmd = [*openclaw_cmd(), "browser", "--browser-profile", self.profile, "--json", *args]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=self.timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise ProfileTimeout(f"openclaw browser {args[0]} timed out after {self.timeout_s}s "
                                 f"(profile {self.profile})") from exc
        out = p.stdout.strip()
        i = out.find("{")
        try:
            d = json.loads(out[i:]) if i >= 0 else {}
        except ValueError:
            d = {}
        if p.returncode != 0 or not d.get("ok", True):
            raise OpenClawFailed(f"openclaw browser {args[0]} failed: {(d.get('error') or p.stderr or out)!s:.300}")
        return d

    def _goto(self, url: str) -> None:
        """Open `url` in this driver's tab. If OpenClaw's browser has gone away
        (first real agents turn, 1 Oct 2026: "Browser profile ... is not running",
        and every later call failed on the dead tab) it is started again ONCE and a
        new tab opened; a second failure is raised."""
        if self.tab is not None:
            try:
                self._call("navigate", url, "--target-id", self.tab)
            except OpenClawFailed:
                self.tab = None                         # the browser or the tab is gone: start again below
        if self.tab is None:
            self._call("start")
            self.tab = self._call("open", url).get("tabId")
            if not self.tab:
                raise OpenClawFailed(f"openclaw browser open {url}: no tab id came back")
        try:
            self._call("wait", "--load", "domcontentloaded", "--target-id", self.tab)
        except OpenClawFailed:
            time.sleep(2.5)

    def alive(self) -> bool:
        """OpenClaw's own status for this profile: running or not. A failed status call is
        not alive; one that timed out sets `timed_out` (C-FIX-1 4B-b iii)."""
        self.timed_out = False
        try:
            d = self._call("status")
        except ProfileTimeout:
            self.timed_out = True
            return False
        except OpenClawFailed:
            return False
        self.cdp_port = d.get("cdpPort") or self.cdp_port
        return bool(d.get("running"))

    def start(self) -> None:
        self.tab = None
        self._call("start")

    def stop(self) -> None:
        self.tab = None
        self._call("stop")

    def _eval(self, js: str) -> dict:
        d = self._call("evaluate", "--target-id", self.tab, "--fn", js)
        return {"raw": d, "value": json.loads(d.get("result") or "null")}

    def search(self, query: str) -> dict:
        self._goto(SEARCH_URL.format(q=urllib.parse.quote_plus(query)))
        page = self._eval(_TEXT_JS)
        links = self._eval(_LINKS_JS)
        return {"page": page["value"] or {}, "links": links["value"] or [], "raw": links["raw"]}

    def read_pdf(self, url: str) -> dict:
        """The PDF's bytes, fetched by OpenClaw's browser inside the PDF's own page."""
        self._goto(url)
        d = self._call("evaluate", "--target-id", self.tab, "--fn", _PDF_JS, "--timeout-ms", "60000")
        v = json.loads(d.get("result") or "null") or {}
        import base64
        return {"bytes": base64.b64decode(v.get("b64") or ""), "status": v.get("status"), "type": v.get("type"),
                "raw": {"ok": d.get("ok", True), "status": v.get("status"), "type": v.get("type")}}

    def read(self, url: str) -> dict:
        self._goto(url)
        r = self._eval(_TEXT_JS)
        return {"page": r["value"] or {}, "raw": r["raw"]}


GATEWAY_PORT = 18789


class Gateway:
    """OpenClaw's gateway, the one thing every browser call goes through (C-GW-1).

    healthy(): `openclaw gateway health --json` answers {"ok": true}.
    restart(): what worked on 2 Oct 2026 (C-GW-1 0b) — `openclaw gateway stop --force`
    failed ("port 18789 is still busy after stop"), so the process listening on the
    port is ended (only if its command line is an openclaw gateway), then the service
    is started with `openclaw gateway start` (the scheduled task "OpenClaw Gateway"),
    and health is polled for up to `wait_s`."""

    def __init__(self, timeout_s: int = 60, wait_s: int = 90):
        self.timeout_s, self.wait_s = timeout_s, wait_s

    @staticmethod
    def parse_health(out: str) -> bool:
        i = (out or "").find("{")
        try:
            return bool(json.loads(out[i:]).get("ok") is True) if i >= 0 else False
        except ValueError:
            return False

    def _cli(self, *args, timeout=None) -> subprocess.CompletedProcess:
        return subprocess.run([*openclaw_cmd(), "gateway", *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout or self.timeout_s)

    def healthy(self) -> bool:
        try:
            p = self._cli("health", "--json")
        except subprocess.TimeoutExpired:
            return False
        return p.returncode == 0 and self.parse_health(p.stdout)

    def restart(self) -> None:
        import psutil
        for c in psutil.net_connections("tcp"):
            if c.laddr and c.laddr.port == GATEWAY_PORT and c.status == "LISTEN" and c.pid:
                try:
                    proc = psutil.Process(c.pid)
                    if "openclaw" in " ".join(proc.cmdline()) and "gateway" in " ".join(proc.cmdline()):
                        proc.terminate()
                        psutil.wait_procs([proc], timeout=15)
                except psutil.Error:
                    pass
        try:
            self._cli("start", timeout=180)
        except subprocess.TimeoutExpired:
            pass
        t0 = time.time()
        while time.time() - t0 < self.wait_s and not self.healthy():
            time.sleep(5)


def selftest() -> dict:
    try:
        ok = Gateway().healthy()
        return {"integrations": {"openclaw gateway": "LIVE" if ok else "INERT (does not answer)"}, "ok": True}
    except Exception as exc:                                         # noqa: BLE001
        return {"integrations": {"openclaw gateway": f"INERT ({type(exc).__name__})"}, "ok": True}


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), indent=2))
