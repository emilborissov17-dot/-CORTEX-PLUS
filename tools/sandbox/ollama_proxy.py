#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/sandbox/ollama_proxy.py — THE ONE HOLE THE FENCE COULD NOT CLOSE.

THE DEFECT THIS EXISTS FOR
--------------------------
The sandbox built on 18 Sep 2026 gave the omega user exactly one reachable
destination: 127.0.0.1:11434, the in-distro Ollama. That destination is a FULL
Ollama API. `/api/pull` fetches a model from the public registry; `/api/create`,
`/api/copy`, `/api/delete` and `/api/push` change or send the model store.

The fence is an iptables OUTPUT rule keyed on `--uid-owner 1001`. Ollama runs as
uid 999. So a prompt that persuaded the agent to POST /api/pull would reach the
internet THROUGH OLLAMA, whose traffic the fence never sees. The fence stops
omega from opening a socket; it does not stop omega from asking something else to
open one, and that was written into the report's "does NOT protect against" as
item 1 rather than left to be discovered.

WHAT THIS DOES
--------------
Listens on 127.0.0.1:11435, forwards a fixed allowlist to 127.0.0.1:11434, and
answers everything else 403. The fence then allows omega 11435 and rejects 11434
with everything else, so the agent cannot reach the real API at all — only the
six endpoints below.

ALLOWLIST BY (METHOD, EXACT PATH). Not a prefix, not a regex:

    POST /v1/chat/completions      the OpenAI-compatible endpoint Omega uses
    POST /api/chat                 Ollama native chat
    POST /api/generate             Ollama native completion
    GET  /api/tags                 which models exist
    GET  /api/version              which Ollama
    GET  /                         the "Ollama is running" liveness string

A PREFIX MATCH WOULD BE A HOLE, which is why the path is normalised before it is
compared. `/api/generate/../pull` is `/api/pull` after normalisation, and
`//api//generate` is `/api/generate`; matching the raw string would let the first
through under a prefix rule and refuse the second under an exact one. The query
string is stripped before matching and forwarded unchanged.

THE DEFAULT IS REFUSE. A new Ollama endpoint that appears in a future version is
refused by this proxy on the day it ships, without anyone editing this file. That
is the direction an allowlist must fail in, and it is the whole reason this is an
allowlist rather than a list of blocked paths.

EVERY REQUEST IS RECORDED, allowed or refused, one JSON line to
/var/log/omega-proxy.jsonl: ts, method, path, status, ms. A refusal that is not
recorded is a refusal nobody can count later.

STREAMING IS PASSED THROUGH UNCHANGED. Ollama streams NDJSON by default and the
OpenAI-compatible endpoint streams SSE; both are copied chunk by chunk and
flushed, so a token appears at the client when Ollama emits it rather than when
the response ends. Hop-by-hop headers are dropped; when upstream declares no
Content-Length the connection is closed to delimit the body, because urllib has
already de-chunked anything that arrived chunked and forwarding the original
Transfer-Encoding would describe a body that is no longer there.

WHAT THIS IS NOT. It does not read prompts, does not judge content, and does not
rate-limit. It decides which door is open, and nothing about what goes through it.

Run:      /usr/local/sbin/omega-ollama-proxy.py
Unit:     tools/sandbox/omega-proxy.service -> /etc/systemd/system/
Selftest: python3 ollama_proxy.py --selftest
"""
from __future__ import annotations

import json
import os
import posixpath
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_HOST = os.environ.get("OMEGA_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("OMEGA_PROXY_PORT", "11435"))
UPSTREAM = os.environ.get("OMEGA_PROXY_UPSTREAM", "http://127.0.0.1:11434")
LOG_PATH = os.environ.get("OMEGA_PROXY_LOG", "/var/log/omega-proxy.jsonl")

# Generation on a 3B model on this box takes ~10 s and can take much longer with
# a long context. A short timeout here would look to the agent exactly like a
# refusal, which is the one thing this proxy must never be confused with.
UPSTREAM_TIMEOUT = float(os.environ.get("OMEGA_PROXY_TIMEOUT", "600"))

ALLOWED = frozenset({
    ("POST", "/v1/chat/completions"),
    ("POST", "/api/chat"),
    ("POST", "/api/generate"),
    ("GET", "/api/tags"),
    ("GET", "/api/version"),
    ("GET", "/"),
})

# Headers that describe THIS connection and must not be copied to the next one.
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
})

REFUSED_PREFIX = "SANDBOX-PROXY-REFUSED"
MAX_BODY = int(os.environ.get("OMEGA_PROXY_MAX_BODY", str(32 * 1024 * 1024)))

_log_lock = threading.Lock()


def normalise(raw_path: str) -> tuple[str, str]:
    """(path for matching, query for forwarding).

    posixpath.normpath collapses `//`, `.` and `..`, so `/api/generate/../pull`
    becomes `/api/pull` BEFORE it meets the allowlist. Without this the allowlist
    is a string comparison against something the server will later interpret
    differently, which is the classic way an allowlist is walked past.

    TWO THINGS HERE ARE NOT THE OBVIOUS CODE, and the selftest found both:

    1. The query is split off with partition('?'), NOT with urlsplit. urlsplit
       reads a leading `//` as an AUTHORITY — `urlsplit('//api//generate')` gives
       netloc 'api' and path '//generate' — so a request line starting with two
       slashes was being parsed as a protocol-relative URL and the path this
       function returned was not the path the client asked for.
    2. Leading slashes are collapsed BEFORE normpath, because POSIX reserves a
       path beginning with exactly two slashes and normpath preserves it:
       normpath('//api//generate') is '//api/generate', not '/api/generate'.

    Both failed closed rather than open — a mangled path misses the allowlist and
    is refused — but a guard that is right for the wrong reason is one edit away
    from being wrong for the wrong reason.
    """
    raw, _sep, query = raw_path.partition("?")
    path = urllib.parse.unquote(raw)
    if not path.startswith("/"):
        path = "/" + path
    while path.startswith("//"):
        path = path[1:]
    path = posixpath.normpath(path)
    # normpath keeps "/" as "/" and strips the trailing slash from "/api/tags/";
    # it returns "." for an empty path.
    if path == ".":
        path = "/"
    return path, query


def record(method: str, path: str, status: int, ms: float) -> None:
    """One line per request, allowed or refused. Never raises into the handler."""
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "method": method,
        "path": path,
        "status": status,
        "ms": round(ms, 1),
    }
    try:
        with _log_lock:
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as e:
        # The log failing must not take the proxy down, but it must be visible:
        # a proxy that silently stops recording is a proxy whose refusals cannot
        # be counted, and the count is half of what this file is for.
        print(f"omega-proxy: LOG WRITE FAILED {LOG_PATH}: {e}", file=sys.stderr, flush=True)


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "omega-proxy/1"
    sys_version = ""

    def log_message(self, fmt, *args):            # noqa: A003
        """Silence BaseHTTPRequestHandler's stderr line; record() is the record."""

    # every method the stdlib dispatches, funnelled into one decision
    def do_GET(self):     self._handle("GET")     # noqa: E704,N802
    def do_POST(self):    self._handle("POST")    # noqa: E704,N802
    def do_PUT(self):     self._handle("PUT")     # noqa: E704,N802
    def do_DELETE(self):  self._handle("DELETE")  # noqa: E704,N802
    def do_PATCH(self):   self._handle("PATCH")   # noqa: E704,N802
    def do_HEAD(self):    self._handle("HEAD")    # noqa: E704,N802
    def do_OPTIONS(self): self._handle("OPTIONS")  # noqa: E704,N802

    def _refuse(self, method: str, path: str, t0: float) -> None:
        body = f"{REFUSED_PREFIX} {method} {path}\n".encode("utf-8")
        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        record(method, path, 403, (time.time() - t0) * 1000)

    def _handle(self, method: str) -> None:
        t0 = time.time()
        path, query = normalise(self.path)

        if (method, path) not in ALLOWED:
            self._refuse(method, path, t0)
            return

        # Read the body before anything else: an unread body wedges keep-alive.
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._refuse(method, path, t0)
            return
        body = self.rfile.read(length) if length else None

        target = UPSTREAM + path + (("?" + query) if query else "")
        req = urllib.request.Request(target, data=body, method=method)
        for key, value in self.headers.items():
            if key.lower() in HOP_BY_HOP or key.lower() == "host":
                continue
            req.add_header(key, value)

        try:
            upstream = urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT)
        except urllib.error.HTTPError as e:
            # Upstream said no for its own reasons. Pass its answer through as
            # itself: turning a 404 from Ollama into a 403 from here would make
            # a missing model look like a refused endpoint.
            upstream = e
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            msg = f"omega-proxy: upstream {UPSTREAM} unreachable: {e}\n".encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            record(method, path, 502, (time.time() - t0) * 1000)
            return

        status = upstream.status
        out = [(k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP]
        has_length = any(k.lower() == "content-length" for k, _ in out)

        self.send_response(status)
        for key, value in out:
            self.send_header(key, value)
        if not has_length:
            # urllib has already de-chunked anything chunked, so the original
            # framing is gone. Close-delimited is the honest way to say "the body
            # ends when the connection does", and it is what lets a stream flow.
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()

        if method != "HEAD":
            try:
                while True:
                    chunk = upstream.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()          # per chunk: this is the streaming
            except (BrokenPipeError, ConnectionResetError):
                pass                            # client hung up mid-stream
            finally:
                upstream.close()
        record(method, path, status, (time.time() - t0) * 1000)


def selftest() -> int:
    """What is LIVE and what is INERT in the box this file finds itself in."""
    out = {"listen": f"{LISTEN_HOST}:{LISTEN_PORT}", "upstream": UPSTREAM,
           "log": LOG_PATH, "allowed": sorted("%s %s" % p for p in ALLOWED)}

    # normalise() is the guard the allowlist rests on, so it is exercised rather
    # than described. Each of these is a real shape of the same attack.
    cases = [
        ("/api/generate/../pull", "/api/pull"),
        ("//api//generate", "/api/generate"),
        ("///api/pull", "/api/pull"),
        ("/api/./tags", "/api/tags"),
        ("/api/tags/", "/api/tags"),
        ("/%2e%2e/api/pull", "/api/pull"),
        ("/api/chat/../../api/pull", "/api/pull"),
        ("/api/tags?x=1", "/api/tags"),
        ("", "/"),
    ]
    out["normalise"] = {}
    ok = True
    for raw, want in cases:
        got, _q = normalise(raw)
        out["normalise"][raw or "(empty)"] = got
        if got != want:
            out["normalise"][raw or "(empty)"] = f"{got}  EXPECTED {want}"
            ok = False
    out["normalise_ok"] = ok
    # and the point of it: the traversal does not land in the allowlist
    out["traversal_refused"] = ("POST", normalise("/api/generate/../pull")[0]) not in ALLOWED

    try:
        with urllib.request.urlopen(UPSTREAM + "/api/version", timeout=5) as r:
            out["upstream_reachable"] = f"LIVE ({r.status})"
    except Exception as e:                                       # noqa: BLE001
        out["upstream_reachable"] = f"INERT ({type(e).__name__})"
    try:
        with open(LOG_PATH, "a", encoding="utf-8"):
            pass
        out["log_writable"] = "LIVE"
    except OSError as e:
        out["log_writable"] = f"INERT ({e.__class__.__name__})"

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if (ok and out["traversal_refused"]) else 1


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Proxy)
    server.daemon_threads = True
    print(f"omega-proxy: {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM}; "
          f"{len(ALLOWED)} endpoints allowed, everything else 403; log {LOG_PATH}",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
