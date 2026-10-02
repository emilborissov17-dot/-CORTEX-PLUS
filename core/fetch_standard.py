# -*- coding: utf-8 -*-
"""core/fetch_standard.py — the ONE way an open source is fetched (C-OC-3 Part 2).

Sources are open now (Emil R27): the seed list is where the search starts, not a
fence. What replaces the fence is a fetch standard, and every rule in it is a
mechanical refusal with a mutation test (test/test_fetch_standard.py):

  GET only · no credentials, cookies, auth headers or form posts · no private,
  loopback, link-local or LAN address (checked on the literal AND on every
  address the name resolves to, and again on every redirect hop) · body at most
  5 MB · timeout 30 s · one request per host per 2 s.

A source is PARKED only after 3 CONSECUTIVE fetch failures, and is retried as
soon as a need names it (unpark). One success resets the streak.

core/axon_agents._refuse_url was read first (2026-10-01): it is literal-only and
bound to a per-role allowlist, which is the fence this command removes; it stays
as it is for its own callers.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
PARKING = REPO / "memory" / "fetch_parking.json"

MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 30
HOST_INTERVAL_S = 2.0
PARK_AFTER = 3
MAX_REDIRECTS = 5
USER_AGENT = "CORTEX-open-fetch/1.0"
FORBIDDEN_HEADERS = ("authorization", "cookie", "proxy-authorization")


class FetchRefused(Exception):
    """The fetch standard forbids this request. Raised, never returned."""


# ── the address rule ────────────────────────────────────────────────────────
def _bad_ip(ip: str) -> Optional[str]:
    a = ipaddress.ip_address(ip.split("%")[0])
    if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
        return f"non-public address {a}"
    return None


def url_problem(url: str, resolve: Callable = socket.getaddrinfo) -> Optional[str]:
    """None if `url` may be fetched, else why not."""
    p = urllib.parse.urlparse(str(url))
    if p.scheme not in ("http", "https"):
        return f"scheme {p.scheme!r} is not http/https"
    if p.username or p.password or "@" in (p.netloc or ""):
        return "credentials in the url"
    host = (p.hostname or "").lower()
    if not host:
        return "no host"
    if host in ("localhost", "localhost.localdomain", "ip6-localhost") or host.endswith(".local"):
        return f"loopback or LAN name {host}"
    try:
        return _bad_ip(host)
    except ValueError:
        pass
    try:
        infos = resolve(host, None)
    except OSError as exc:
        return f"does not resolve: {exc}"
    for info in infos:
        why = _bad_ip(info[4][0])
        if why:
            return f"{host} resolves to a {why}"
    return None


# ── one request per host per 2 s ────────────────────────────────────────────
class HostClock:
    def __init__(self, interval: float = HOST_INTERVAL_S, now: Callable = time.monotonic,
                 sleep: Callable = time.sleep):
        self.interval, self.now, self.sleep, self.last = interval, now, sleep, {}

    def wait(self, host: str) -> float:
        waited = 0.0
        prev = self.last.get(host)
        if prev is not None:
            waited = self.interval - (self.now() - prev)
            if waited > 0:
                self.sleep(waited)
            else:
                waited = 0.0
        self.last[host] = self.now()
        return waited


_CLOCK = HostClock()


# ── the GET ─────────────────────────────────────────────────────────────────
def get(url: str, timeout: float = TIMEOUT_S, headers: Optional[dict] = None, *, method: str = "GET",
        session=None, resolve: Callable = socket.getaddrinfo, clock: Optional[HostClock] = None,
        max_bytes: int = MAX_BYTES) -> dict:
    """-> {status, raw, content_type, final_url, bytes}. Raises FetchRefused for
    anything the standard forbids; network errors propagate as they are."""
    if method != "GET":
        raise FetchRefused(f"method {method} is not GET")
    from core import turn as _turn
    if _turn.state().get("holder") == _turn.BRAIN:
        # C-TURN-1 Part 3a: the brain's turn has no network (Emil R31: it works only
        # with collected, prepared and approved information)
        raise FetchRefused("the baton is BRAIN: no fetch in the brain's turn")
    hdrs = {"User-Agent": USER_AGENT}
    for k, v in (headers or {}).items():
        if k.lower() in FORBIDDEN_HEADERS:
            raise FetchRefused(f"header {k} carries credentials or cookies")
        hdrs[k] = v
    if timeout > TIMEOUT_S:
        raise FetchRefused(f"timeout {timeout}s exceeds {TIMEOUT_S}s")
    clock = clock or _CLOCK
    if session is None:
        # C-FIX-1 Part 3 (2 Oct 2026, Emil R43): the bytes come through OpenClaw's
        # browser (core/openclaw_door.py), never from requests. The door applies this
        # module's address rule, host clock and size limit itself; DoorClosed is not
        # caught here.
        from core import openclaw_door as _door
        got = _door.get_bytes(url, resolve=resolve, clock=clock, max_bytes=max_bytes)
        return {"status": got["status"],
                "raw": got["bytes"].decode(_door._charset(got["content_type"]), errors="replace"),
                "content_type": got["content_type"], "final_url": got["final_url"], "bytes": len(got["bytes"])}
    session.cookies.clear()
    session.trust_env = False                      # no proxy auth, no .netrc credentials
    for _hop in range(MAX_REDIRECTS + 1):
        why = url_problem(url, resolve)
        if why:
            raise FetchRefused(why)
        clock.wait((urllib.parse.urlparse(url).hostname or "").lower())
        r = session.request("GET", url, headers=hdrs, timeout=timeout, stream=True,
                            allow_redirects=False)
        session.cookies.clear()                    # a Set-Cookie is never sent back
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urllib.parse.urljoin(url, r.headers["location"])
            r.close()
            continue
        declared = r.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            r.close()
            raise FetchRefused(f"body {declared} bytes exceeds {max_bytes}")
        buf = bytearray()
        for chunk in r.iter_content(65536):
            buf += chunk
            if len(buf) > max_bytes:
                r.close()
                raise FetchRefused(f"body exceeds {max_bytes} bytes")
        enc = r.encoding or "utf-8"
        return {"status": r.status_code, "raw": bytes(buf).decode(enc, errors="replace"),
                "content_type": r.headers.get("content-type", ""), "final_url": url, "bytes": len(buf)}
    raise FetchRefused(f"more than {MAX_REDIRECTS} redirects")


# ── parking ─────────────────────────────────────────────────────────────────
def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def record(source_id: str, ok: bool, err: str = "", path: Optional[Path] = None) -> dict:
    """One fetch outcome. 3 consecutive failures park the source; one success resets."""
    path = Path(path or PARKING)
    state = _load(path)
    s = state.get(source_id, {"consecutive_failures": 0, "parked": False})
    if ok:
        s = {"consecutive_failures": 0, "parked": False}
    else:
        s["consecutive_failures"] = s.get("consecutive_failures", 0) + 1
        s["last_err"] = err[:300]
        if s["consecutive_failures"] >= PARK_AFTER:
            s["parked"] = True
    s["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state[source_id] = s
    _save(state, path)
    return s


def is_parked(source_id: str, path: Optional[Path] = None) -> bool:
    return bool(_load(Path(path or PARKING)).get(source_id, {}).get("parked"))


def unpark(source_id: str, reason: str, path: Optional[Path] = None) -> None:
    """A need named this source: it is tried again (its streak is kept)."""
    path = Path(path or PARKING)
    state = _load(path)
    if source_id in state:
        state[source_id]["parked"] = False
        state[source_id]["unparked_by"] = reason[:200]
        _save(state, path)


# ── selftest ────────────────────────────────────────────────────────────────
def selftest() -> dict:
    import inspect
    res = {"integrations": {}}
    worker = REPO / "scripts" / "data_feed_reader.py"
    src = worker.read_text(encoding="utf-8") if worker.exists() else ""
    res["integrations"]["worker fetches through fetch_standard.get"] = (
        "LIVE" if "fetch_standard" in src and "_fs.get(" in src else "INERT")
    res["integrations"]["worker parks after 3 failures"] = "LIVE" if "_fs.record(" in src else "INERT"
    res["integrations"]["memory/fetch_parking.json"] = (
        f"LIVE ({len(_load(PARKING))} sources)" if PARKING.exists() else "INERT (no failure recorded yet)")
    res["checks"] = {
        "loopback refused": url_problem("http://127.0.0.1/") is not None,
        "LAN refused": url_problem("http://192.168.1.1/") is not None,
        "credentials refused": url_problem("https://u:p@example.org/") is not None,
        "get signature has no body/data/auth": not {"data", "json", "auth", "cookies"} & set(
            inspect.signature(get).parameters),
    }
    res["ok"] = all(res["checks"].values())
    return res


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        r = selftest()
        print(json.dumps(r, indent=2))
        sys.exit(0 if r["ok"] else 1)
    print(__doc__)
