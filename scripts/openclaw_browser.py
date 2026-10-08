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
from typing import Optional

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


class GatewayTimeout(OpenClawFailed):
    """The CLI answered "gateway timeout": the gateway's socket did not answer the browser
    call in time, while `gateway health` may still say ok (C-GW-2, 8 Oct 2026: turns 93-97
    of 5 Oct and 103-107 of 7 Oct ended SEARCHER_DEAD on exactly this, with no restart)."""


# The CLI's own words for a browser call the gateway did not answer (C-GW-2).
GATEWAY_TIMEOUT = "gateway timeout"


class ProfileStartFailed(OpenClawFailed):
    """PROFILE_START_FAILED: the profile did not start after the one retry (C-DOOR-1)."""


class ProfileStopFailed(OpenClawFailed):
    """PROFILE_STOP_FAILED: the profile's Chrome is still alive after stop and its end (C-DOOR-1)."""


# The CLI's own words for a start whose Chrome may in fact be running (FIX 4B-a, CHECK Part B).
ADOPTION = "exited before adoption"
ADOPT_WAIT_S = 5


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

    def __init__(self, profile: str = "openclaw", timeout_s: int = 60, procs=None, kill=None, sleep=time.sleep,
                 ledger=None, devtools=None):
        self.profile, self.timeout_s, self.tab = profile, timeout_s, None
        self.timed_out, self.gateway_timed_out, self.cdp_port = False, False, None
        self.procs, self.kill, self.sleep, self.ledger = procs, kill, sleep, ledger
        self.events: list = []
        # C-DOOR-2 3a: what the last call already said, so it is not asked again
        self.last_status: Optional[dict] = None
        self.running_known = False
        # C-DOOR-3 (Emil R49): the direct line to this profile's Chrome, opened after a start
        self.devtools, self.direct, self._direct_tried, self._last_url = devtools, None, False, None

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
            msg = f"openclaw browser {args[0]} failed: {(d.get('error') or p.stderr or out)!s:.300}"
            if GATEWAY_TIMEOUT in msg.lower():
                raise GatewayTimeout(msg)
            raise OpenClawFailed(msg)
        return d

    def _open_direct(self) -> None:
        """C-DOOR-3: after a start, one direct line to this profile's Chrome. The port is
        OpenClaw's own `status` cdpPort, never a constant. A line that cannot be opened is a
        DEVTOOLS_FALLBACK_CLI row and the CLI is used."""
        self._direct_tried = True
        port = (self.last_status or {}).get("cdpPort") or self._status().get("cdpPort")
        if not port:
            self._fallback("no cdpPort in OpenClaw's status")
            return
        try:
            if self.devtools is not None:
                self.direct = self.devtools(int(port))
            else:
                from scripts import devtools_line
                self.direct = devtools_line.DirectLine(int(port))
        except Exception as exc:                                     # noqa: BLE001
            self._fallback(f"{type(exc).__name__}: {exc}")

    def _fallback(self, cause: str) -> None:
        """The direct line is not used from here on: said by a row, never silently."""
        self._event({"event": "DEVTOOLS_FALLBACK_CLI", "cause": str(cause)[:300]})
        if self.direct is not None:
            self.direct.close()
        self.direct = None
        self.tab = None

    def _goto(self, url: str) -> None:
        """Open `url` in this driver's tab. If OpenClaw's browser has gone away
        (first real agents turn, 1 Oct 2026: "Browser profile ... is not running",
        and every later call failed on the dead tab) it is started again ONCE and a
        new tab opened; a second failure is raised."""
        self._last_url = url
        if self.tab is None and self.direct is None and not self.running_known:
            # started HERE, before the path is chosen: a start opens the direct line, and the
            # page must be opened where it will be read (C-DOOR-3 Step 2d)
            self.start()
        if self.direct is None and self.running_known and not self._direct_tried:
            self._open_direct()
        if self.direct is not None:
            from scripts import devtools_line
            try:
                self.direct.navigate(url)
                self.direct.wait_load()
                return
            except devtools_line.DevToolsNavigateFailed as exc:
                raise OpenClawFailed(str(exc)) from exc   # the page, not the line: the line stays
            except Exception as exc:                                 # noqa: BLE001
                self._fallback(f"navigate: {type(exc).__name__}: {exc}")
        if self.tab is not None:
            try:
                self._call("navigate", url, "--target-id", self.tab)
            except OpenClawFailed:
                self.tab = None                         # the browser or the tab is gone: start again below
                self.running_known = False
        if self.tab is None:
            if not self.running_known:
                self.start()
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
        self.timed_out = self.gateway_timed_out = False
        try:
            d = self._call("status")
        except ProfileTimeout:
            self.timed_out = True
            self.last_status = {}
            return False
        except GatewayTimeout:
            self.gateway_timed_out = True
            self.last_status = {}
            return False
        except OpenClawFailed:
            self.last_status = {}
            return False
        self.cdp_port = d.get("cdpPort") or self.cdp_port
        self.last_status = d
        self.running_known = bool(d.get("running"))
        return self.running_known

    def _event(self, row: dict) -> None:
        row = {"profile": self.profile, **row}
        self.events.append(row)
        if self.ledger is not None:
            self.ledger(row)

    def _status(self) -> dict:
        """The profile's status, or {} when the call fails (unknown is not "not running")."""
        try:
            d = self._call("status")
        except OpenClawFailed:
            self.last_status = {}
            return {}
        self.cdp_port = d.get("cdpPort") or self.cdp_port
        self.last_status = d
        return d

    def _chromes(self) -> list:
        return chrome_pids_for_port(cdp_port(self.profile, self), self.procs() if self.procs else None)

    def _end_chromes(self, event: str) -> list:
        """End every Chrome carrying this profile's debugging port, by exact PID, each
        logged (pid, port, age, command line) before the kill. Never another Chrome."""
        port = cdp_port(self.profile, self)
        if not port:
            return []
        procs = list(self.procs()) if self.procs else _process_list()
        by_pid = {p.info["pid"]: p.info for p in procs}
        pids = chrome_pids_for_port(port, procs)
        for pid in pids:
            info = by_pid.get(pid) or {}
            age = (time.time() - info["create_time"]) / 60 if info.get("create_time") else None
            self._event({"event": event, "pid": pid, "port": port,
                         "age_min": round(age, 1) if age is not None else None,
                         "cmdline": " ".join(map(str, info.get("cmdline") or []))[:300]})
            (self.kill or _kill)(pid)
        return pids

    def start(self, status: Optional[dict] = None) -> None:
        """C-DOOR-1 2a: leftovers ended first; a false "exited before adoption" survived;
        one retry; a second failure is PROFILE_START_FAILED. No third attempt.
        `status`: the status the caller has just read (C-DOOR-2 3a: not asked again)."""
        self.tab = None
        st = status if status is not None else self._status()
        if st.get("running") is False:
            self._end_chromes("LEFTOVER_CHROME_ENDED")
        try:
            self._call("start")
            self.running_known = True
            self._open_direct()
            return
        except OpenClawFailed as exc:
            if ADOPTION not in str(exc):
                raise
            first = exc
        self.sleep(ADOPT_WAIT_S)
        if self._status().get("running"):
            self._event({"event": "START_ADOPTED_LATE", "error": str(first)[:300]})
            self.running_known = True
            self._open_direct()
            return
        self._end_chromes("LEFTOVER_CHROME_ENDED")
        try:
            self._call("start")
            self.running_known = True
        except OpenClawFailed as second:
            raise ProfileStartFailed(f"PROFILE_START_FAILED: profile {self.profile}: first: {first}; "
                                     f"second: {second}"[:900]) from second
        self._open_direct()

    def stop(self) -> None:
        """C-DOOR-1 2b: stop, then status and the process list; a Chrome still alive is
        ended by exact PID; one that cannot be ended raises PROFILE_STOP_FAILED. A stop
        never returns while that Chrome is alive."""
        self.tab = None
        self.running_known = False
        if self.direct is not None:
            self.direct.close()
        self.direct, self._direct_tried = None, False
        try:
            self._call("stop")
        except OpenClawFailed as exc:
            self._event({"event": "STOP_FAILED", "error": str(exc)[:300]})
        if self._status().get("running") or self._chromes():
            self._end_chromes("PROFILE_CHROME_ENDED")
            left = self._chromes()
            if left:
                raise ProfileStopFailed(f"PROFILE_STOP_FAILED: profile {self.profile}: Chrome {left} still alive "
                                        f"on port {cdp_port(self.profile, self)} after stop and end")

    def evaluate_fn(self, js: str, timeout_ms: Optional[int] = None) -> dict:
        """The page's `js` (a function) -> {"result": <its JSON string>}, through the direct
        line when it is open; a failure there falls back to the CLI with a row."""
        if self.direct is not None:
            try:
                v = self.direct.evaluate(js)
                return {"ok": True, "result": v if isinstance(v, str) else json.dumps(v)}
            except Exception as exc:                                 # noqa: BLE001
                self._fallback(f"evaluate: {type(exc).__name__}: {exc}")
                self._goto(self._last_url)
        args = ["evaluate", "--target-id", self.tab, "--fn", js]
        if timeout_ms:
            args += ["--timeout-ms", str(int(timeout_ms))]
        return self._call(*args)

    def _eval(self, js: str) -> dict:
        d = self.evaluate_fn(js)
        return {"raw": d, "value": json.loads(d.get("result") or "null")}

    def search(self, query: str) -> dict:
        self._goto(SEARCH_URL.format(q=urllib.parse.quote_plus(query)))
        page = self._eval(_TEXT_JS)
        links = self._eval(_LINKS_JS)
        return {"page": page["value"] or {}, "links": links["value"] or [], "raw": links["raw"]}

    def read_pdf(self, url: str) -> dict:
        """The PDF's bytes, fetched by OpenClaw's browser inside the PDF's own page."""
        self._goto(url)
        d = self.evaluate_fn(_PDF_JS, 60000)
        v = json.loads(d.get("result") or "null") or {}
        import base64
        return {"bytes": base64.b64decode(v.get("b64") or ""), "status": v.get("status"), "type": v.get("type"),
                "raw": {"ok": d.get("ok", True), "status": v.get("status"), "type": v.get("type")}}

    def read(self, url: str) -> dict:
        self._goto(url)
        r = self._eval(_TEXT_JS)
        return {"page": r["value"] or {}, "raw": r["raw"]}


# The profile `openclaw` is not in ~/.openclaw/openclaw.json; its CDP port was read from
# `openclaw browser status` on 2 Oct 2026 (C-FIX-1 4B-a). A status that answers overrides it.
DEFAULT_CDP_PORTS = {"openclaw": 18800}


def cdp_port(profile: str, browser=None) -> Optional[int]:
    """The profile's Chrome debugging port: from its last status, its config, or the default."""
    if browser is not None and getattr(browser, "cdp_port", None):
        return int(browser.cdp_port)
    try:
        cfg = json.loads((Path.home() / ".openclaw" / "openclaw.json").read_text(encoding="utf-8"))
        port = (((cfg.get("browser") or {}).get("profiles") or {}).get(profile) or {}).get("cdpPort")
        if port:
            return int(port)
    except (OSError, ValueError):
        pass
    return DEFAULT_CDP_PORTS.get(profile)


def chrome_pids_for_port(port: int, procs=None) -> list:
    """Chrome's browser process (not a renderer or helper: no --type=) whose
    --remote-debugging-port is exactly `port`."""
    if procs is None:
        procs = _process_list()
    flag = f"--remote-debugging-port={port}"
    out = []
    for p in procs:
        info = p.info
        args = info.get("cmdline") or []
        if "chrome" in str(info.get("name") or "").lower() and flag in args \
                and not any(str(a).startswith("--type=") for a in args):
            out.append(info["pid"])
    return out


def _kill(pid: int) -> None:
    import psutil
    psutil.Process(pid).kill()                   # this PID only, never its tree


def end_profile_chrome(profile: str, port: Optional[int], ledger, procs=None, kill=None) -> list:
    """End this profile's Chrome by exact PID; each command line is logged before the kill."""
    if not port:
        ledger({"event": "PROFILE_CHROME_NOT_FOUND", "profile": profile, "why": "no debugging port known"})
        return []
    procs = list(procs) if procs is not None else None
    pids = chrome_pids_for_port(port, procs)
    if not pids:
        ledger({"event": "PROFILE_CHROME_NOT_FOUND", "profile": profile, "port": port,
                "why": "no Chrome process on that debugging port"})
    by_pid = {p.info["pid"]: p.info for p in procs} if procs is not None else {}
    for pid in pids:
        cmd = " ".join(map(str, (by_pid.get(pid) or {}).get("cmdline") or []))
        if not cmd:
            try:
                import psutil
                cmd = " ".join(psutil.Process(pid).cmdline())
            except Exception:                                        # noqa: BLE001
                cmd = "?"
        ledger({"event": "PROFILE_CHROME_ENDED", "profile": profile, "port": port, "pid": pid,
                "cmdline": cmd[:300]})
        (kill or _kill)(pid)
    return pids


def _process_list() -> list:
    import psutil
    return list(psutil.process_iter(["pid", "name", "cmdline", "create_time"]))


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
