#!/usr/bin/env python3
"""
core/source_status.py — registry of dead / gated external data sources.

WHY THIS EXISTS
---------------
Several upstream sources have been quietly retired or put behind a token.
Without a registry, each one fails on every single cycle: the fetcher tries a
list of stale URLs, every one 404s, the error is printed, and the cycle moves
on having wasted the requests. The noise also hides real, new breakage — a
source that died yesterday looks exactly like the four that died last year.

So: a source that is known-gone is declared ONCE, in config/dead_sources.json,
with the date and the evidence. It is then skipped cleanly, and the log says
"skipped (NEEDS_AUTH since 2026-07-13)" instead of a stack of 404s.

STATUSES
  DEAD       — gone for good. Never called.
  NEEDS_AUTH — alive but gated. Called normally IF the named env var is
               present; skipped quietly if it is not.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent.parent
DEAD_SOURCES_PATH = BASE / "config" / "dead_sources.json"

# Print each skip only once per process, not once per call site per cycle.
_ANNOUNCED: set = set()


def _load() -> dict:
    if not DEAD_SOURCES_PATH.exists():
        return {}
    try:
        data = json.loads(DEAD_SOURCES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [SRC] dead_sources.json unreadable ({type(e).__name__}: {e}) "
              f"— treating all sources as live")
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def get_status(key: str) -> Optional[dict]:
    """The registry entry for `key`, or None if the source is not registered."""
    return _load().get(key)


def credential_for(key: str) -> Optional[str]:
    """The credential for a NEEDS_AUTH source, from env or .env. None if absent."""
    entry = get_status(key) or {}
    env_key = entry.get("env_key")
    if not env_key:
        return None

    val = os.environ.get(env_key, "")
    if val:
        return val

    env_file = BASE / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith(env_key + "="):
                    return line.split("=", 1)[1].strip() or None
        except Exception:
            pass
    return None


def skip_reason(key: str) -> Optional[str]:
    """Why `key` must not be called right now — or None if it is fine to call.

    NEEDS_AUTH sources with their credential present return None (call away).
    """
    entry = get_status(key)
    if not entry:
        return None

    status = entry.get("status", "DEAD").upper()
    since = entry.get("since", "unknown date")

    if status == "NEEDS_AUTH":
        if credential_for(key):
            return None  # we have the token — it is a live source again
        env_key = entry.get("env_key", "<env var>")
        return f"NEEDS_AUTH since {since} — set {env_key} in .env to re-enable"

    if status == "DEAD":
        return f"DEAD since {since} — {entry.get('reason', 'no reason recorded')[:80]}"

    return None  # unknown status: fail open rather than silently disable a source


def announce_skip(key: str, reason: str) -> None:
    """Log a skip once per process."""
    if key in _ANNOUNCED:
        return
    _ANNOUNCED.add(key)
    print(f"  [SRC] {key}: skipped — {reason}")


def is_skipped(key: str) -> bool:
    """True (and logs once) if `key` should not be called this cycle."""
    reason = skip_reason(key)
    if reason is None:
        return False
    announce_skip(key, reason)
    return True


def reset_announcements() -> None:
    """Test hook: forget which skips have been announced."""
    _ANNOUNCED.clear()
