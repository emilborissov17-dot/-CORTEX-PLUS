# -*- coding: utf-8 -*-
"""test/_live_net.py — the mechanical net behind "tests never read live data"
(C-OC-3 Part 5). install() makes any read under memory/, snapshots/ or
cortex_memory/ — read OR write — RAISE, and records the attempt, so a module that swallows the
raise in its own try/except still fails the test at teardown (check()).
"""
from __future__ import annotations

import builtins
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_DIRS = ("memory", "snapshots", "cortex_memory")
_READS = ("read_text", "read_bytes", "iterdir", "glob", "rglob", "exists", "is_dir", "is_file", "stat",
          "open", "write_text", "write_bytes", "mkdir", "touch", "unlink")


def is_live(path) -> bool:
    try:
        rel = Path(path).resolve().relative_to(REPO).parts
    except (ValueError, TypeError, OSError):
        return False
    return bool(rel) and rel[0] in LIVE_DIRS


def install(monkeypatch) -> list:
    attempts: list = []

    def guard(fn):
        def wrapped(self, *a, **k):
            if is_live(self):
                attempts.append(str(self))
                raise AssertionError(f"a test read live data: {self}")
            return fn(self, *a, **k)
        return wrapped
    for name in _READS:
        monkeypatch.setattr(Path, name, guard(getattr(Path, name)))
    real_open = builtins.open

    def guarded_open(file, *a, **k):
        if isinstance(file, (str, os.PathLike)) and is_live(file):
            attempts.append(str(file))
            raise AssertionError(f"a test read live data: {file}")
        return real_open(file, *a, **k)
    monkeypatch.setattr(builtins, "open", guarded_open)
    # C-GW-1 (2 Oct 2026): a test without an injected gateway called the REAL
    # `openclaw gateway health`; with a dead answer it would have restarted the live
    # gateway. Every OpenClaw CLI call goes through openclaw_cmd(): a test reaching it fails.
    # C-FIX-1 (2 Oct 2026): decided - both the driver module and the searcher are netted.
    try:
        from scripts import openclaw_browser as _ob
        from scripts import openclaw_search as _oc

        def no_cli():
            attempts.append("openclaw CLI")
            raise AssertionError("a test reached the live OpenClaw CLI")
        monkeypatch.setattr(_ob, "openclaw_cmd", no_cli)
        monkeypatch.setattr(_oc, "openclaw_cmd", no_cli)
    except ImportError:
        pass
    return attempts


def check(attempts: list) -> None:
    assert not attempts, f"a test reached live data (the module swallowed the error): {attempts}"
