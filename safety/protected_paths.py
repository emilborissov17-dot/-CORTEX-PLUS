#!/usr/bin/env python3
"""
safety/protected_paths.py — the constitution of the bubble.

THE PRINCIPLE
-------------
The machinery that GRANTS autonomy must not be reachable by the autonomy it
grants. A system that can rewrite its own guardian has no guardian; a system
that can rewrite its own audit log has no audit log. These files are therefore
human-only: no self-generated patch may write to them, ever, for any reason.

This is a TARGET check, and it is deliberately separate from safety/ast_gate.py,
which is a SHAPE check. The AST gate asks "is this code dangerous?"; this asks
"is this file allowed to be touched at all?" They are different guarantees and
neither implies the other — a perfectly innocent-looking patch that happens to
rewrite patch_guardian.py is catastrophic precisely because its shape is fine.

DEFENCE IN DEPTH
----------------
Enforced at BOTH layers, independently:
  1. safety/ast_gate.check_code()   — refuses generated code whose literal
     write target is protected (catches e.g. a patch that writes to
     memory/existence_ledger.jsonl, which ALLOWED_DIR_PREFIXES would otherwise
     permit because it lives under memory/).
  2. patch_guardian.PatchGuardian.apply_patch() — refuses to apply a patch whose
     TARGET FILE is protected, regardless of what the AST gate concluded.

Either layer alone would be a single point of failure. A bypass of one must not
be a bypass of the system.

WHY THIS FILE IS CODE, NOT CONFIG
---------------------------------
It protects itself. A JSON denylist is data, and data is exactly what a patch
can most easily rewrite; making the denylist a config file would mean the
denylist is only as strong as the rule protecting the denylist. As code inside
safety/ — which is itself protected, as a directory — it is covered by its own
rule with no bootstrap gap.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# The protected set
# ---------------------------------------------------------------------------

# Entire directories — everything beneath them, at any depth.
PROTECTED_DIRS = (
    "safety",        # the AST gate, the quarantine, and this file
    "config",        # the action policy, the scheduler config, the source registry
)

# Individual files.
PROTECTED_FILES = frozenset({
    # ── The gates and the guardian ───────────────────────────────────────────
    "patch_guardian.py",
    "execute_patches.py",        # the gate must not be able to rewrite the gate
    "scripts/review_quarantine.py",   # the human's window into what was rejected

    # ── The scheduler / supervisor (autonomy rung 1) ─────────────────────────
    # The thing that decides WHETHER the system runs must not be writable by
    # the system it runs.
    "supervisor.py",

    # ── The registry logic behind config/dead_sources.json ───────────────────
    "core/source_status.py",

    # ── The audit trail ──────────────────────────────────────────────────────
    # These live under memory/, which ast_gate's ALLOWED_DIR_PREFIXES otherwise
    # permits generated code to write to. Without an explicit rule, a patch
    # could forge its own existence history, or fake a heartbeat and thereby
    # defeat the watchdog that is supposed to notice it hanging.
    "memory/existence_ledger.jsonl",
    "memory/heartbeat.json",
    "memory/cycle.lock",
    "memory/scheduler_state.json",
})


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalise(path: str) -> Optional[str]:
    """Repo-relative, forward-slashed, lower-cased path — or None if the path
    cannot be safely reasoned about.

    Returns None (which callers MUST treat as protected — fail closed) for:
      - absolute paths (POSIX '/x' or Windows 'C:\\x')
      - any path that escapes the repo via '..'

    Lower-cased because Windows filesystems are case-insensitive:
    'Patch_Guardian.py' and 'patch_guardian.py' are the same file, and a check
    that missed that would be trivially bypassable.
    """
    if not path or not str(path).strip():
        return None

    norm = str(path).replace("\\", "/").strip()

    # Absolute paths: we cannot know whether they land inside the repo.
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return None

    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if not parts:
        return None

    # Resolve '..' — and refuse anything that climbs out of the repo root.
    resolved: list[str] = []
    for part in parts:
        if part == "..":
            if not resolved:
                return None      # escapes the repo
            resolved.pop()
        else:
            resolved.append(part)

    if not resolved:
        return None

    return "/".join(resolved).lower()


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def protection_reason(path: str) -> Optional[str]:
    """Why `path` may not be written by generated code — or None if it may.

    FAIL CLOSED: a path that cannot be normalised (absolute, or traversing out
    of the repo) is treated as protected. We would rather refuse a legitimate
    patch than permit one we cannot reason about.
    """
    norm = normalise(path)
    if norm is None:
        return f"unresolvable or out-of-repo path: {path!r} (fail-closed)"

    for d in PROTECTED_DIRS:
        if norm == d.lower() or norm.startswith(d.lower() + "/"):
            return f"{path} is inside protected directory {d}/ — human-only"

    if norm in {f.lower() for f in PROTECTED_FILES}:
        return f"{path} is a protected file — human-only"

    return None


def is_protected(path: str) -> bool:
    """True if generated code / patches must never write to `path`."""
    return protection_reason(path) is not None


# ---------------------------------------------------------------------------
# Introspection (for tests, review tooling, and the daily report)
# ---------------------------------------------------------------------------

def all_protected() -> dict:
    return {
        "protected_dirs":  list(PROTECTED_DIRS),
        "protected_files": sorted(PROTECTED_FILES),
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        for target in sys.argv[1:]:
            reason = protection_reason(target)
            verdict = f"DENIED  — {reason}" if reason else "allowed"
            print(f"{target:45} {verdict}")
    else:
        print(json.dumps(all_protected(), indent=2))
