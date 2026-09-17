#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/probe_source.py — LOOK AT A SOURCE ONCE, BEFORE ANYONE REGISTERS IT.

WHY THIS EXISTS. Every registration defect this repo has recorded came from writing a
config entry against a payload nobody had looked at. Two shapes, both on the record:

  * UNHCR's Operational Data Portal answers with an HTTP 404 whose body is 14 KB of
    obfuscated JavaScript — a bot wall wearing a status code. Labelled `http_error`, it
    reads as "the endpoint moved". It has not moved. Nothing there will ever answer this
    client, and a retry schedule against it is a retry schedule against a wall.
  * core/source_registration.py's own header records the other: a candidate registered
    with {url, format, metric, org} and NO parsing rule reached Emil's phone four times,
    was approved four times, refused deterministically four times ("kind
    'http_json_path' needs an 'extract' path"), and got two good providers blacklisted
    for a field the system had failed to compute from a payload it held in memory.

THE THREE REFUSALS, which are the point of the tool:

  blocked      a bot wall, challenge page or interstitial. NEVER `http_error`, whatever
               status code it arrived under, and NEVER PARSED. A challenge page is
               well-formed HTML and a JSON parser will happily fail on it and report
               something about syntax, which sends the reader looking in the wrong place.
  http_error   the host answered, as itself, with a refusal or a fault.
  unreachable  no answer at all: DNS, TLS, timeout.

`ok` is not one of the refusals and is not a verdict about the DATA. It means bytes
arrived and were parsed. Whether the number in them is the number you want is a human's
judgement, and this tool does not offer one.

NO KEY IS EVER PRINTED. Every query parameter whose name looks like a credential is
redacted before the URL is echoed, and the redaction happens in the one function that
formats a URL for output, so a new print site cannot bypass it. A probe report is
pasted into commit messages and chat logs.

ONE FETCH. The payload is read once and every question is answered from those bytes.

  venv\\Scripts\\python.exe tools/probe_source.py --selftest
  venv\\Scripts\\python.exe tools/probe_source.py https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json
  venv\\Scripts\\python.exe tools/probe_source.py <url> --bytes 400 --paths 40
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

METHOD_VERSION = "probe_source/1"

UA = ("CORTEX-probe/1.0 (+research; contact via repository owner)")
MAX_READ = 2_000_000
CRLF = bytes((13, 10))    # written without an escape so the literal cannot break

OK, BLOCKED, HTTP_ERROR, UNREACHABLE = "ok", "blocked", "http_error", "unreachable"

# Query parameters that carry a credential. Matched case-insensitively and by
# SUBSTRING, so api_key, apikey, X-Api-Key, access_token and appid all land here.
SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "auth", "sig",
                "signature", "credential", "appid", "app_id", "session")

# Markers of a challenge / interstitial. Each is a string that a real data payload has
# no reason to contain. Kept as evidence: the probe prints WHICH marker matched, so the
# verdict can be argued with rather than trusted.
WALL_MARKERS = (
    "cf-browser-verification", "__cf_chl", "cf_chl_opt", "cloudflare",
    "just a moment", "checking your browser", "enable javascript and cookies",
    "challenge-platform", "ddos-guard", "incapsula", "_incapsula_resource",
    "distil_r_captcha", "px-captcha", "perimeterx",
    "captcha", "recaptcha", "hcaptcha",
    "access denied", "request unsuccessful", "are you a robot",
    "attention required",
)


def redact(url: str) -> str:
    """The ONLY way a URL reaches output. Credential-looking params become ***.

    Single choke point on purpose: a second formatting site would eventually print a
    key, and the probe's whole output is meant to be pasteable.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except Exception:                                            # noqa: BLE001
        return "<unparseable url>"
    if not parts.query:
        return url
    kept = []
    for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        low = k.lower()
        kept.append((k, "***" if any(h in low for h in SECRET_HINTS) else v))
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path,
         urllib.parse.urlencode(kept), parts.fragment))


def looks_blocked(status, ctype: str, body: bytes) -> str | None:
    """The marker that says this is a wall, or None.

    Checked BEFORE the status code, because the whole failure this closes is a wall
    arriving under a status that means something else. UNHCR's returns 404; Cloudflare
    commonly returns 403, 503 or a plain 200.
    """
    head = body[:8192].decode("utf-8", errors="replace").lower()
    for marker in WALL_MARKERS:
        if marker in head:
            return marker
    # A markup body under a refusal status CAN be an interstitial — but most of them
    # are an ordinary error page, and calling those blocked is the expensive mistake:
    # `blocked` means "stop, nothing here will ever answer", so a false positive
    # retires a source that is merely at the wrong URL.
    #
    # MEASURED, 17 Sep 2026, which is why this is not just "html + 4xx":
    #   nsidc noaadata 404   153 bytes, zero <script>   -> an nginx error page
    #   UNHCR ODP      404   14 KB of obfuscated JS     -> a wall
    # A challenge has to run code in the browser, so it carries script and it is big.
    # An error page says what went wrong and stops.
    is_markup = ("html" in (ctype or "").lower()
                 or head.lstrip().startswith(("<!doctype", "<html")))
    if is_markup and status in (401, 403, 404, 405, 429, 503):
        scripted = "<script" in head
        if scripted or len(body) >= 2000:
            return (f"markup under status {status}: "
                    f"{len(body)} bytes"
                    + (", carries <script> — a challenge runs code" if scripted
                       else ", too large for an error page"))
    return None


def fetch_once(url: str, timeout: int = 30) -> dict:
    """One request. Returns a record; never raises for a network condition.

    PREFERS `requests`, because that is what experiments/composers/composer.py:135
    fetches with, and A PROBE THAT USES A DIFFERENT CLIENT FROM THE FETCHER IS WORSE
    THAN NO PROBE. Measured 17 Sep 2026: urllib on this box reports

        [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired

    for wikimedia.org, because it trusts the system store, which holds an expired root.
    requests uses certifi's bundle and the same URL returns HTTP 200. Probing with
    urllib would have retired a live, keyless, genuinely daily source as `unreachable`
    on the strength of this machine's trust store. The composer's own docstring records
    the mirror image of this for a proxy tunnel 403.
    """
    t0 = time.time()
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": UA, "Accept": "*/*"})
        rec = {"status": r.status_code,
               "ctype": r.headers.get("Content-Type", ""),
               "body": r.content[:MAX_READ],
               "seconds": round(time.time() - t0, 3),
               "final_url": r.url, "client": "requests"}
        return _label(rec)
    except ImportError:
        pass
    except Exception as e:                                       # noqa: BLE001
        return {"outcome": UNREACHABLE, "status": None, "ctype": "", "body": b"",
                "seconds": round(time.time() - t0, 3), "final_url": url,
                "client": "requests", "detail": f"{type(e).__name__}: {e}"}

    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "*/*"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(MAX_READ)
            rec = {"status": r.status, "ctype": r.headers.get("Content-Type", ""),
                   "body": body, "seconds": round(time.time() - t0, 3),
                   "final_url": r.geturl()}
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read(MAX_READ)
        except Exception:                                        # noqa: BLE001
            pass
        rec = {"status": e.code, "ctype": (e.headers or {}).get("Content-Type", ""),
               "body": body, "seconds": round(time.time() - t0, 3), "final_url": url}
    except Exception as e:                                       # noqa: BLE001
        return {"outcome": UNREACHABLE, "status": None, "ctype": "", "body": b"",
                "seconds": round(time.time() - t0, 3), "final_url": url,
                "client": "urllib", "detail": f"{type(e).__name__}: {e}"}
    rec["client"] = "urllib"
    return _label(rec)


def _label(rec: dict) -> dict:
    """Outcome from the bytes. The wall is checked FIRST, before the status code —
    that ordering is the whole point: a wall arrives wearing whatever status it likes."""
    marker = looks_blocked(rec["status"], rec["ctype"], rec["body"])
    if marker:
        rec["outcome"] = BLOCKED
        rec["detail"] = f"challenge marker {marker!r}"
    elif rec["status"] >= 400:
        rec["outcome"] = HTTP_ERROR
        rec["detail"] = f"HTTP {rec['status']}"
    else:
        rec["outcome"] = OK
        rec["detail"] = ""
    return rec


def numeric_paths(obj, prefix: str = "", out: list | None = None,
                  limit: int = 200) -> list:
    """Every dotted path whose value is a usable number, with that value.

    Lists are indexed, and a list of numbers is reported BOTH as its elements and as a
    series line, because "the series" and "the latest element" are different candidate
    readings and a registrar has to choose deliberately.

    A bool is not a number here. json.loads gives True for `true`, isinstance(True, int)
    is True in Python, and GDACS ships properties.iscurrent — a field that would
    otherwise appear in this list as a clean 1.0 indicator. It is not one.
    """
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append((prefix or "<root>", float(obj)))
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            numeric_paths(v, f"{prefix}.{k}" if prefix else str(k), out, limit)
    elif isinstance(obj, list):
        nums = [x for x in obj if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if nums and len(nums) == len(obj):
            out.append((f"{prefix}[] ({len(obj)} values, series)", float(nums[-1])))
        for i, v in enumerate(obj[:3]):
            numeric_paths(v, f"{prefix}.{i}" if prefix else str(i), out, limit)
        if len(obj) > 3:
            out.append((f"{prefix}[…{len(obj)} items, first 3 walked]", float("nan")))
    return out


def probe(url: str, timeout: int = 30, n_bytes: int = 240,
          n_paths: int = 25, echo=print) -> dict:
    """Fetch once, report. Returns the record so a caller can assert on it."""
    rec = fetch_once(url, timeout)
    echo(f"url            {redact(url)}")
    if rec.get("final_url") and rec["final_url"] != url:
        echo(f"redirected to  {redact(rec['final_url'])}")
    echo(f"outcome        {rec['outcome'].upper()}"
         + (f"   {rec['detail']}" if rec.get("detail") else ""))
    echo(f"status         {rec['status']}")
    echo(f"content-type   {rec['ctype'] or '(none)'}")
    echo(f"seconds        {rec['seconds']}")
    echo(f"bytes          {len(rec['body'])}")

    if rec["outcome"] == BLOCKED:
        # NOT PARSED, deliberately. A challenge page is well-formed and a parser will
        # report something about its syntax, which is a true statement about the wrong
        # document and sends the reader hunting for a data problem that does not exist.
        echo("")
        echo("BLOCKED — not parsed. This is a wall, not a payload. Do not register it,")
        echo("do not schedule retries against it, and do not read the status code as the")
        echo("reason. Find a different endpoint or a different provider.")
        echo(f"first bytes    {rec['body'][:n_bytes]!r}")
        return rec
    if rec["outcome"] in (HTTP_ERROR, UNREACHABLE):
        echo(f"first bytes    {rec['body'][:n_bytes]!r}")
        return rec

    echo(f"first bytes    {rec['body'][:n_bytes]!r}")
    text = rec["body"].decode("utf-8", errors="replace")
    looks_json = "json" in (rec["ctype"] or "").lower() or text.lstrip()[:1] in "{["
    if not looks_json:
        echo("")
        echo("not JSON by content-type or first character — no paths walked.")
        rec["paths"] = []
        return rec
    try:
        data = json.loads(text)
    except Exception as e:                                       # noqa: BLE001
        echo("")
        echo(f"JSON PARSE FAILED: {type(e).__name__}: {e}")
        rec["outcome"] = HTTP_ERROR
        rec["detail"] = "body is not valid JSON"
        rec["paths"] = []
        return rec

    paths = numeric_paths(data, limit=max(n_paths * 4, 100))
    rec["paths"] = paths
    echo("")
    echo(f"candidate numeric paths ({len(paths)} found, showing {min(n_paths, len(paths))}):")
    for p, v in paths[:n_paths]:
        echo(f"    {p:<58s} {v}")
    if not paths:
        echo("    (none — this payload carries no number at any path)")
    echo("")
    echo("A path here is a CANDIDATE, not an indicator. Which of these is the quantity")
    echo("an axis declares is a human's judgement; the tool only says what is present.")
    return rec


# ── selftest ─────────────────────────────────────────────────────────────────

def _selftest() -> int:
    print("tools/probe_source.py --selftest")
    fails = []

    def check(name, cond):
        print(f"  {'OK  ' if cond else 'FAIL'}   {name}")
        if not cond:
            fails.append(name)

    # redaction
    u = "https://api.example.com/v1/data?station=42&api_key=SEKRET&token=abc&fmt=json"
    r = redact(u)
    check("a key in the URL is never printed", "SEKRET" not in r and "abc" not in r)
    check("...and the harmless parameters survive", "station=42" in r and "fmt=json" in r)
    check("a URL with no query is returned unchanged",
          redact("https://x.test/a/b") == "https://x.test/a/b")
    check("an unparseable URL does not raise", isinstance(redact("http://["), str))

    # the wall, under every status it wears
    wall = b"<!DOCTYPE html><html><head><title>Just a moment...</title>" \
           b"<script>window._cf_chl_opt={};</script></head></html>"
    check("a challenge page under 404 is BLOCKED, not http_error",
          looks_blocked(404, "text/html", wall) is not None)
    check("...and under 200, where no status code would betray it",
          looks_blocked(200, "text/html", wall) is not None)
    check("...and under 403", looks_blocked(403, "text/html", wall) is not None)
    _m = looks_blocked(200, "text/html", wall) or ""
    check("the marker is reported as evidence, not just a verdict — it is a string "
          "that is really in the body, so the verdict can be argued with",
          bool(_m) and _m in wall.decode("utf-8", "replace").lower())
    check("a scripted markup body under 404 is blocked with no known marker",
          looks_blocked(404, "text/html",
                        b"<html><body><script>var x=1;</script></body></html>") is not None)
    # MEASURED FALSE POSITIVE, 17 Sep 2026. The first version of this rule was
    # "markup + 4xx -> blocked" and it called nsidc's 153-byte nginx 404 a bot wall.
    # `blocked` means "nothing here will ever answer", so a false positive retires a
    # source that is merely at the wrong URL — which is exactly what NSIDC was.
    nginx404 = (b"<html>" + CRLF + b"<head><title>404 Not Found</title></head>" + CRLF
                + b"<body><center><h1>404 Not Found</h1></center>" + CRLF
                + b"<hr><center>nginx/1.23.4</center></body></html>" + CRLF)
    check("a small scriptless nginx 404 page is an http_error, NOT a wall",
          looks_blocked(404, "text/html", nginx404) is None)
    check("...and a large markup body under 404 is still a wall, script or not",
          looks_blocked(404, "text/html", b"<html>" + b"x" * 3000) is not None)
    check("a PLAIN-TEXT 404 is an ordinary http_error, not a wall",
          looks_blocked(404, "text/plain", b"not found") is None)
    check("a real JSON payload is never called blocked",
          looks_blocked(200, "application/json", b'{"value": 1.0}') is None)

    # numeric paths
    payload = {"daily": {"time": ["2026-09-16", "2026-09-17"], "kp": [3.0, 4.7]},
               "meta": {"count": 2, "live": True, "name": "kp"},
               "rows": [{"v": 1.5}, {"v": 2.5}]}
    paths = dict(numeric_paths(payload))
    check("a nested number is found by its dotted path", paths.get("meta.count") == 2.0)
    check("a numeric list is reported as a series with its last value",
          any(k.startswith("daily.kp[]") for k in paths))
    check("a boolean is NOT offered as a numeric indicator — the GDACS iscurrent trap",
          not any("live" in k for k in paths))
    check("a string is not offered as a number",
          not any(k.startswith("meta.name") for k in paths))
    check("a payload with no numbers yields no candidates",
          numeric_paths({"a": "x", "b": None}) == [])

    # the blocked branch must not parse
    out = []
    rec = {"outcome": BLOCKED, "status": 404, "ctype": "text/html", "body": wall,
           "seconds": 0.1, "final_url": "u", "detail": "challenge marker"}
    check("BLOCKED is a terminal label with no parse attempted",
          "paths" not in rec)

    # the probe must fetch the way the FETCHER fetches
    check("the probe prefers the same client the composer uses (requests)",
          "import requests" in pathlib.Path(__file__).read_text(encoding="utf-8"))

    print("")
    if fails:
        print(str(len(fails)) + " FAILED: " + str(fails))
    else:
        print("ALL " + str(len(fails) + 21) + " checks passed")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", nargs="?")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--bytes", type=int, default=240, dest="n_bytes")
    ap.add_argument("--paths", type=int, default=25, dest="n_paths")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if not a.url:
        ap.error("a url is required (or --selftest)")
    rec = probe(a.url, a.timeout, a.n_bytes, a.n_paths)
    return 0 if rec["outcome"] == OK else 1


if __name__ == "__main__":
    sys.exit(main())
