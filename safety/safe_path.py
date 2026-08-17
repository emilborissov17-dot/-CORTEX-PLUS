#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
safety/safe_path.py — ONE containment check for paths built from untrusted fragments.

WHAT THIS IS FOR
----------------
A path fragment that came from a model, a JSON file the cycle wrote, or anything
else the system produced about itself, must not be able to name a file outside the
tree it is allowed to touch. This module is the single place that decides that.

WHY IT LIVES IN safety/ AND NOT core/
--------------------------------------
It was written as core/safe_path.py and moved. The reason is measurable, not stylistic:
agents/core/self_modifier._write_python carries its own allowlist of directories the
system may write generated Python into, and that list is

    ["memory/", "agents/core/", "data_providers/", "alignment/", "core/"]

`core/` is on it. `safety/` is not — safety/ is in protected_paths.PROTECTED_DIRS, so
no generated patch may target it, at any depth. Verified against this repo:

    safety/safe_path.py         passes self_modifier's allowlist = False
    core/safe_path.py           passes self_modifier's allowlist = True
    core/notary.py              passes self_modifier's allowlist = True

A guard that the constrained thing can rewrite is not a guard. Left in core/, this
module would have been a lock whose key sits in the room it locks: the self-modifier
could have proposed a patch to core/safe_path.py that widens what safe_path() accepts,
and the patch would have been written by the very machinery this file exists to bound.

test_the_guard_is_not_writable_by_the_thing_it_constrains pins that, by importing the
real allowlist rather than restating it. It fails if the file moves back to core/, and
it fails if someone adds "safety/" to the allowlist.

WHY IT EXISTS WHEN safety/protected_paths.normalise() ALREADY EXISTS
---------------------------------------------------------------------
They answer different questions and neither replaces the other:

    protected_paths.normalise()  — "is this path SHAPED like an escape?"
                                   Pure string logic. Never touches the disk.
    safe_path()                  — "does this path RESOLVE inside the root?"
                                   Calls realpath. Follows symlinks.

normalise() already refuses absolute paths, drive letters, UNC and '..' that climbs
out of the repo — verified, not assumed. What it cannot see is a symlink, because it
never stats anything. Measured 17 Aug 2026 against the live guardian:

    agents/core/evil_patch.py  ->  normalise()        accepted
                                   _is_dynamic_patch  True
                                   _is_patchable      True

If that name is a symlink pointing at C:/Windows/system.ini, every string-level check
passes and write_text() follows the link out of the repo. Closing that needs the
filesystem, which is what this module adds. It is a SECOND layer, deliberately — the
repo already runs protected_paths and ast_gate as independent gates, and the rule
there is that a bypass of one must not be a bypass of the system.

FAIL CLOSED, ALWAYS
-------------------
Every refusal raises UnsafePath. Nothing here returns a "cleaned" path: silently
normalising an attacker-supplied fragment into something writable is how a guard
becomes a laundering step. If a caller cannot handle the exception, the caller is
wrong — not this function.

'..' IS REFUSED OUTRIGHT, even where it would resolve back inside the root.
'a/../b' is harmless and still rejected, because "harmless traversal" and "traversal"
differ only by arithmetic a reviewer has to redo every time they read the line. No
legitimate caller in this repo needs it.

    venv\\Scripts\\python.exe -m safety.safe_path --selftest
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Union

REPO_ROOT = Path(__file__).resolve().parents[1]
MEMORY_ROOT = REPO_ROOT / "memory"


class UnsafePath(ValueError):
    """A path fragment that cannot be proven to stay inside its allowed root.

    ValueError subclass on purpose: existing `except Exception` handlers keep
    working, but a caller that wants to report the refusal precisely can.
    """


def _refuse(fragment: object, why: str) -> "UnsafePath":
    return UnsafePath(f"refused path fragment {fragment!r}: {why}")


def safe_path(fragment: Union[str, os.PathLike],
              root: Union[str, os.PathLike, None] = None) -> Path:
    """Resolve `fragment` under `root`, or raise UnsafePath.

    Returns an ABSOLUTE, symlink-resolved path that is provably inside `root`.
    `root` defaults to the repository root.

    Refuses, in order:
      empty / whitespace-only / non-string-able  — nothing to reason about
      NUL byte                                   — truncation attacks on the C layer
      UNC path        (//server/share, \\\\srv)   — a different machine entirely
      POSIX absolute  (/etc/passwd)
      drive-absolute  (C:/Windows) and
      drive-relative  (C:evil — resolves against the CWD of that drive)
      any '..' component
      anything whose realpath lands outside `root`  — this is the symlink case
    """
    if fragment is None:
        raise _refuse(fragment, "is None")
    try:
        raw = os.fspath(fragment) if isinstance(fragment, os.PathLike) else str(fragment)
    except Exception as e:                       # noqa: BLE001 — any failure is a refusal
        raise _refuse(fragment, f"is not path-like ({type(e).__name__})") from e

    if not raw.strip():
        raise _refuse(fragment, "is empty or whitespace only")
    if "\x00" in raw:
        raise _refuse(fragment, "contains a NUL byte")

    probe = raw.replace("\\", "/").strip()

    if probe.startswith("//"):
        raise _refuse(fragment, "is a UNC path (names another host)")
    if probe.startswith("/"):
        raise _refuse(fragment, "is an absolute POSIX path")
    # 'C:/x' (drive-absolute) and 'C:x' (drive-RELATIVE, resolves against that
    # drive's own current directory — absolute in effect, and easy to miss).
    if len(probe) >= 2 and probe[1] == ":":
        raise _refuse(fragment, "names a drive letter")
    # Belt and braces for shapes the string checks above do not model.
    if PureWindowsPath(raw).is_absolute() or PureWindowsPath(raw).drive:
        raise _refuse(fragment, "is absolute")
    if ".." in probe.split("/"):
        raise _refuse(fragment, "contains a '..' component (refused even if it would "
                                "resolve back inside the root)")

    root_real = Path(os.path.realpath(str(root) if root is not None else REPO_ROOT))
    # realpath, not resolve(strict=True): the target usually does NOT exist yet — we
    # are about to create it — but every symlink on the way there must still be
    # followed before containment is judged.
    candidate = Path(os.path.realpath(str(root_real / probe)))

    try:
        candidate.relative_to(root_real)
    except ValueError:
        raise _refuse(fragment, f"resolves to {str(candidate)!r}, which is outside "
                                f"{str(root_real)!r} (symlink or traversal)") from None

    if candidate == root_real:
        raise _refuse(fragment, "resolves to the root itself, not a path within it")

    return candidate


def safe_repo_path(fragment: Union[str, os.PathLike]) -> Path:
    """Resolve `fragment` inside the repository root, or raise UnsafePath."""
    return safe_path(fragment, REPO_ROOT)


def safe_memory_path(fragment: Union[str, os.PathLike]) -> Path:
    """Resolve `fragment` inside memory/, or raise UnsafePath."""
    return safe_path(fragment, MEMORY_ROOT)


def is_safe(fragment: Union[str, os.PathLike],
            root: Union[str, os.PathLike, None] = None) -> bool:
    """Boolean form, for call sites that branch rather than propagate.

    Prefer safe_path(): the exception carries WHY, and a bare False at a refusal
    site tends to get logged as 'skipped' rather than 'refused'.
    """
    try:
        safe_path(fragment, root)
        return True
    except UnsafePath:
        return False


# ---------------------------------------------------------------------------
# --selftest: which integrations are LIVE in the repo this module finds itself in
# ---------------------------------------------------------------------------

def _selftest() -> int:
    print(f"safety/safe_path.py selftest")
    print(f"  REPO_ROOT   : {REPO_ROOT}   exists={REPO_ROOT.is_dir()}")
    print(f"  MEMORY_ROOT : {MEMORY_ROOT} exists={MEMORY_ROOT.is_dir()}")

    print("\n  integrations:")
    for label, mod, attr in (("safety.protected_paths.normalise (layer 1, string)",
                              "safety.protected_paths", "normalise"),
                             ("safety.ast_gate.check_code (layer 2, shape)",
                              "safety.ast_gate", "check_code"),
                             ("patch_guardian (the one tainted write site)",
                              "patch_guardian", "PatchGuardian")):
        try:
            m = __import__(mod, fromlist=[attr])
            state = "LIVE" if hasattr(m, attr) else "INERT (attr missing)"
        except Exception as e:                    # noqa: BLE001
            state = f"INERT ({type(e).__name__})"
        print(f"    {state:24} {label}")

    print("\n  refusals:")
    bad = 0
    for frag in ("/etc/passwd", "C:/Windows/system.ini", "C:evil.py",
                 "//server/share/x", "..", "../../evil.py",
                 "agents/core/../../evil.py", "", "   ", "\x00x"):
        try:
            safe_path(frag)
            print(f"    !! ACCEPTED {frag!r} — THIS IS A HOLE")
            bad += 1
        except UnsafePath as e:
            print(f"    refused  {frag!r:32} {str(e).split(': ', 1)[-1]}")

    print("\n  accepts (legitimate):")
    for frag in ("memory/heartbeat.json", "agents/core/x_patch.py"):
        try:
            print(f"    ok       {frag!r:32} -> {safe_path(frag).relative_to(REPO_ROOT)}")
        except UnsafePath as e:
            print(f"    !! REFUSED a legitimate path {frag!r}: {e}")
            bad += 1

    print(f"\n  {'OK' if not bad else f'{bad} PROBLEM(S)'}")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_selftest() if "--selftest" in sys.argv else _selftest())
