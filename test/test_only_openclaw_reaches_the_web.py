# -*- coding: utf-8 -*-
"""test/test_only_openclaw_reaches_the_web.py — C-FIX-1 Part 4 (2 Oct 2026).

THE RULE (Emil R43, §20): no code may open a network connection except through the
OpenClaw door (core/openclaw_door.py, scripts/openclaw_search.py), a local model, a
cloud model backend, or the two outbound channels (Telegram alarm, GitHub
publication). Every exception is named in config/network_allowlist.json with its
class (M = model, O = outbound, L = local only) and a one-line reason.

A REFUSAL looks like this test failing with the file and the line of the import or
the call. The forbidden fallback is widening the scan's blind spots instead of
moving the code behind the door.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOWLIST = REPO / "config" / "network_allowlist.json"
# core/fetch_standard.py is the door's rulebook: socket only for the address rule's
# getaddrinfo, and its requests path needs a session injected by a caller.
DOOR = {"core/openclaw_door.py", "scripts/openclaw_search.py", "core/fetch_standard.py"}
LOOPBACK = {"localhost", "127.0.0.1"}
HOST = re.compile(r"(?:https?|wss?)://([A-Za-z0-9.\-]+)")
CLASSES = {"M", "O", "L"}

NET_MODULES = {"requests", "urllib.request", "urllib3", "http.client", "httpx", "aiohttp", "socket",
               "ftplib", "smtplib", "telnetlib", "websocket", "websockets", "yt_dlp", "youtube_dl",
               "pycurl", "ddgs", "duckduckgo_search", "feedparser", "pytube", "youtube_transcript_api",
               "selenium", "playwright", "mechanize", "httplib2", "tweepy", "praw", "openai", "anthropic",
               "groq", "google.generativeai"}
NET_TOOLS = ("curl", "wget", "yt-dlp", "youtube-dl", "aria2c")
SHELLS = {"subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call",
          "subprocess.check_output", "os.system", "os.popen", "run", "Popen", "check_output", "call"}


def _root(name: str) -> str:
    for m in NET_MODULES:
        if name == m or name.startswith(m + "."):
            return m
    return ""


def _tool_in(node) -> str:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            first = sub.value.strip().split(" ")[0].split("/")[-1].split("\\")[-1].lower()
            if first.removesuffix(".exe") in NET_TOOLS:
                return first
    return ""


def reaches(source: str) -> list[str]:
    """Every network import and every shell call to a network tool in `source`."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"unparseable: {exc.msg}"]
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [f"{n.lineno}: import {a.name}" for a in n.names if _root(a.name)]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            if _root(n.module):
                out.append(f"{n.lineno}: from {n.module} import ...")
            elif n.module in ("urllib", "http", "google"):
                out += [f"{n.lineno}: from {n.module} import {a.name}" for a in n.names
                        if _root(f"{n.module}.{a.name}")]
        elif isinstance(n, ast.Call) and ast.unparse(n.func) in SHELLS:
            tool = _tool_in(n)
            if tool:
                out.append(f"{n.lineno}: shell call to {tool}")
        elif isinstance(n, ast.Call) and ast.unparse(n.func) in ("__import__", "importlib.import_module"):
            if n.args and isinstance(n.args[0], ast.Constant) and _root(str(n.args[0].value)):
                out.append(f"{n.lineno}: dynamic import {n.args[0].value}")
    return out


def tracked_py() -> list[str]:
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True,
                           check=True).stdout.split()
    return [f for f in files if not f.startswith("test/") and (REPO / f).exists()]


def allowlist() -> dict:
    return json.loads(ALLOWLIST.read_text(encoding="utf-8"))["files"]


def offenders(files, allowed) -> dict:
    bad = {}
    for f in files:
        if f in DOOR or f in allowed:
            continue
        hits = reaches((REPO / f).read_text(encoding="utf-8-sig", errors="replace"))
        if hits:
            bad[f] = hits
    return bad


def test_only_the_door_and_the_named_exceptions_reach_the_web():
    bad = offenders(tracked_py(), allowlist())
    assert not bad, ("code outside the OpenClaw door reaches the network:\n"
                     + "\n".join(f"  {f}: {h}" for f, h in sorted(bad.items())))


def test_every_allowlist_entry_has_a_class_and_a_reason_and_still_reaches_the_web():
    problems = []
    for f, e in allowlist().items():
        if e.get("class") not in CLASSES:
            problems.append(f"{f}: class {e.get('class')!r} is not one of {sorted(CLASSES)}")
        if len(str(e.get("reason", "")).strip()) < 10 or "\n" in str(e.get("reason", "")):
            problems.append(f"{f}: needs a one-line reason")
        if not (REPO / f).exists():
            problems.append(f"{f}: not on disk (stale entry)")
        elif not reaches((REPO / f).read_text(encoding="utf-8-sig", errors="replace")):
            problems.append(f"{f}: reaches nothing (stale entry)")
    assert not problems, "\n".join(problems)


def hosts(source: str) -> set:
    return {h.lower() for h in HOST.findall(source)}


def test_an_allowed_file_names_only_its_declared_hosts_and_loopback_means_loopback():
    problems = []
    for f, e in allowlist().items():
        if not (REPO / f).exists():
            continue
        found = hosts((REPO / f).read_text(encoding="utf-8-sig", errors="replace"))
        new = found - set(e.get("hosts", []))
        if new:
            problems.append(f"{f}: names undeclared host(s) {sorted(new)}")
        if e.get("class") == "L" and set(e.get("hosts", [])) - LOOPBACK:
            problems.append(f"{f}: class L declares a non-loopback host")
    assert not problems, "\n".join(problems)


def test_mutation_a_new_host_in_an_allowed_file_is_seen():
    e = allowlist()["core/brain.py"]
    src = (REPO / "core/brain.py").read_text(encoding="utf-8") + '\nURL = "https://api.worldbank.org/v2"\n'
    assert hosts(src) - set(e["hosts"]) == {"api.worldbank.org"}


def test_the_scan_examines_the_repo():
    files = tracked_py()
    assert len(files) > 200 and "core/fetch_standard.py" in files and "fast_cycle_runner.py" in files


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_import_requests_in_a_core_file_fails_the_scan(tmp_path, monkeypatch):
    f = "core/quote_gate.py"
    assert f not in offenders([f], allowlist())
    (tmp_path / "core").mkdir()
    (tmp_path / f).write_text((REPO / f).read_text(encoding="utf-8") + "\nimport requests\n", encoding="utf-8")
    monkeypatch.setattr(__import__(__name__), "REPO", tmp_path)
    assert f in offenders([f], allowlist())


def test_mutation_each_shape_is_seen():
    assert reaches("import requests")
    assert reaches("import urllib.request as u")
    assert reaches("from urllib import request")
    assert reaches("from http.client import HTTPSConnection")
    assert reaches("import socket\nsocket.create_connection(('8.8.8.8', 53))")
    assert reaches("import subprocess\nsubprocess.run(['curl', '-s', 'https://x'])")
    assert reaches("import os\nos.system('wget https://x')")
    assert reaches("import subprocess\nsubprocess.run(['yt-dlp', 'u'])")
    assert reaches("importlib.import_module('requests')")
    assert not reaches("import json\nimport urllib.parse\nfrom core.openclaw_door import http as requests")
