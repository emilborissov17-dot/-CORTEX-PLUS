#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/disk_actuator.py â€” THE ONLY THING HERE THAT DELETES, AND IT ALMOST NEVER DOES.

THE WARNING THIS IS BUILT AGAINST
-----------------------------------
From the adversarial review, quoted because it is the whole specification:

    "if the deletion is not bounded by an allowlist, the system can delete
     existence_ledger.jsonl. Then homeostasis becomes suicide."

That has to be impossible BY CONSTRUCTION, not by care. So:

  POSITIVE ALLOWLIST   the only things that may ever be removed
  NEGATIVE ALLOWLIST   checked before EVERY deletion, and it WINS

The negative list is checked last and independently, on the resolved absolute
path of each candidate, after the positive list has already said yes. A file
that matches both is kept. There is no ordering, no priority number and no flag
that can reverse that â€” the keep branch returns before the delete branch is
reachable.

BOTH LISTS ARE HASHED. manifest_sha256() covers the two lists and the age
threshold together; the caller checks it against MANIFEST_SHA256 before acting.
The system cannot extend either list without the hash changing, and a changed
hash refuses the sweep.

WHAT "TRACKED BY GIT" MEANS HERE
----------------------------------
`git ls-files` is consulted once per sweep and cached. Anything git knows about
is protected, full stop â€” that covers every source file, every config, every
document, without needing to enumerate them. If git cannot be reached the sweep
REFUSES rather than proceeding without that protection: losing a cleanup is a
missed opportunity, losing a tracked file is data loss.

DRY RUN IS THE DEFAULT
------------------------
sweep() does nothing unless it is passed apply=True. Every call is logged with
what, why, how many bytes, and which level fired.

    venv/Scripts/python.exe core/disk_actuator.py            # dry run, deletes nothing
    venv/Scripts/python.exe core/disk_actuator.py --manifest # print the hashed manifest
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

SWEEP_LOG = BASE / "memory" / "disk_actuator_log.jsonl"

# â”€â”€ POSITIVE ALLOWLIST â€” the ONLY things that may be removed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Emil approved this exact manifest in writing. Nothing is added to it by the
# system, ever, under any pressure.
POSITIVE_GLOBS = (
    "*.tmp",
)

POSITIVE_DIRS = (
    "tmp",
    "temp",
    ".cache",
    "cache",
    "__pycache__",
)

# *.log older than this. A log being written right now is not rubbish.
LOG_MAX_AGE_DAYS = 7
LOG_GLOB = "*.log"

# â”€â”€ NEGATIVE ALLOWLIST â€” never touched, checked before EVERY deletion â”€â”€â”€â”€â”€â”€â”€
# Repo-relative paths, matched case-insensitively because Windows filesystems
# are, and a check that missed that would be trivially bypassable.
#
# THE BASENAME IS PROTECTED TOO, WHEREVER IT SITS. `memory/` is not on the
# positive list, so a stray `tmp/heartbeat.json` cannot arise from the current
# lists â€” but the rule this module exists to enforce is that the negative
# allowlist wins BY CONSTRUCTION, not by luck of the directory layout. The test
# that put every one of these names inside `tmp/` deleted three of them:
# BOUNDARIES.md, LAW_OF_THE_BRAIN.md and heartbeat.json. Path-only matching was
# the reason. The rule is carried in the hashed manifest below, so switching it
# off again breaks the hash and refuses the sweep.
NEGATIVE_MATCH_BASENAME = True

NEGATIVE_FILES = (
    "memory/existence_ledger.jsonl",
    "memory/brain_journal.jsonl",
    "memory/heartbeat.json",
    "memory/cycle.lock",
    "memory/scheduler_state.json",
    "memory/commitments.db",
    "commitments.db",
    "boundaries.md",
    "law_of_the_brain.md",
)

# Whole subtrees that are never entered.
#
# memory/cycle_logs IS THE RULE, NOT AN EXCEPTION (23 Aug 2026). Any path a LIVE
# component writes to is named here, and is not left to be protected by the
# accident of its age or by not happening to match the positive list.
# supervisor.spawn_cycle() opens memory/cycle_logs/cycle_<stamp>.log with mode
# "w" BEFORE it spawns the runner, and core/cycle_log.tee_stdio() writes the
# same path for a cycle started by hand. That directory does not match any
# positive glob today, so this entry is belt and braces â€” which is the point.
# The lesson of the tmp/ defect found in COMMAND 26 is that the negative list
# has to hold by construction and not by the luck of the directory layout.
#
# cycle.log at the repo root is deliberately NOT here. It has no writer anywhere
# in this repository; protecting it would state a live relationship that does
# not exist. It is recorded in docs/ENGINEERING_BACKLOG.md instead.
NEGATIVE_DIRS = (
    ".git",
    "config",
    "safety",
    "venv",
    "venv312_metta",
    "patches",
    "memory/cycle_logs",
)

# Any file whose name matches these, wherever it is.
NEGATIVE_GLOBS = (
    ".env*",
    "*.db",
    "*.ledger",
    "existence_ledger*",
    "brain_journal*",
)


def manifest() -> dict:
    """The two lists and the age threshold, as one object."""
    return {
        "positive_globs": list(POSITIVE_GLOBS),
        "positive_dirs": list(POSITIVE_DIRS),
        "log_glob": LOG_GLOB,
        "log_max_age_days": LOG_MAX_AGE_DAYS,
        "negative_files": list(NEGATIVE_FILES),
        "negative_match_basename": NEGATIVE_MATCH_BASENAME,
        "negative_dirs": list(NEGATIVE_DIRS),
        "negative_globs": list(NEGATIVE_GLOBS),
    }


def manifest_sha256() -> str:
    return hashlib.sha256(json.dumps(manifest(), sort_keys=True,
                                     separators=(",", ":")
                                     ).encode("utf-8")).hexdigest()


# The stamp of the manifest as Emil approved it. sweep() refuses if the computed
# hash differs â€” the system cannot extend either list.
MANIFEST_SHA256 = "8311f104e8b912b28ad5e287182594b75564098b9e41c0afb8e944595f4a6d12"


class ManifestRefused(Exception):
    """The manifest hash does not match. No sweep runs."""


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------

# KEYED BY THE RESOLVED BASE, and cleared when git fails.
#
# This was a single unkeyed global. Two consequences, both found the first time
# anything in this repo actually called sweep(apply=True) (COMMAND 33 part 7):
# a sweep of one base could be answered with another base's file list, and a
# git that stopped answering left the previous answer in place — so the sweep
# proceeded on a stale list instead of refusing, which is the one thing the
# docstring above promises it will never do.
_tracked_cache: dict = {}


def tracked_files(base=None, refresh: bool = False) -> Optional[frozenset]:
    """Every path git knows about, repo-relative and lower-cased.

    None means git could not be reached â€” and the caller must treat that as a
    refusal, not as an empty set. An empty set would say "nothing is tracked",
    which would remove the single broadest protection this module has.
    """
    key = str(pathlib.Path(base or BASE).resolve()).lower()
    if key in _tracked_cache and not refresh:
        return _tracked_cache[key]
    try:
        out = subprocess.run(["git", "ls-files"], cwd=str(base or BASE),
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            _tracked_cache.pop(key, None)
            return None
        files = frozenset(l.strip().lower().replace("\\", "/")
                          for l in out.stdout.splitlines() if l.strip())
        if not files:
            _tracked_cache.pop(key, None)
            return None                     # a repo with zero tracked files is
        _tracked_cache[key] = files          # not a repo we should sweep
        return files
    except Exception:
        # THE ANSWER IS FORGOTTEN, NOT KEPT. Returning None while a previous
        # answer stayed cached meant the next caller got the stale list and
        # swept on it.
        _tracked_cache.pop(key, None)
        return None


# ---------------------------------------------------------------------------
# The two lists
# ---------------------------------------------------------------------------

def _rel(path, base=None) -> Optional[str]:
    try:
        return pathlib.Path(path).resolve().relative_to(
            pathlib.Path(base or BASE).resolve()).as_posix().lower()
    except Exception:
        return None                          # outside the repo -> protected


def is_protected(path, base=None, tracked=None) -> tuple:
    """(bool, reason). THE NEGATIVE LIST. Checked before every deletion.

    Anything this cannot reason about is protected. A path that escapes the
    repo, a path git cannot be asked about, a path that will not resolve â€”
    every one of those returns True, because the cost of a wrong "no" here is
    the ledger and the cost of a wrong "yes" is one file left on disk.
    """
    rel = _rel(path, base)
    if rel is None:
        return True, "path does not resolve inside the repo"

    for d in NEGATIVE_DIRS:
        if rel == d or rel.startswith(d + "/"):
            return True, "inside the protected directory {!r}".format(d)

    if rel in {f.lower() for f in NEGATIVE_FILES}:
        return True, "named in the negative allowlist"

    name = pathlib.Path(rel).name
    if NEGATIVE_MATCH_BASENAME:
        for f in NEGATIVE_FILES:
            if name == pathlib.PurePosixPath(f.lower()).name:
                return True, ("carries the protected name {!r} â€” the negative "
                              "allowlist matches the basename wherever it "
                              "sits".format(pathlib.PurePosixPath(f).name))
    for g in NEGATIVE_GLOBS:
        if fnmatch.fnmatch(name, g):
            return True, "matches the protected pattern {!r}".format(g)

    if tracked is None:
        tracked = tracked_files(base)
    if tracked is None:
        return True, "git could not be asked whether this file is tracked"
    if rel in tracked:
        return True, "tracked by git"

    return False, ""


def matches_positive(path, base=None, now=None) -> tuple:
    """(bool, reason). THE POSITIVE LIST. Necessary, never sufficient."""
    rel = _rel(path, base)
    if rel is None:
        return False, "outside the repo"
    p = pathlib.Path(path)
    name = p.name

    for g in POSITIVE_GLOBS:
        if fnmatch.fnmatch(name, g):
            return True, "matches {!r}".format(g)

    parts = rel.split("/")
    for d in POSITIVE_DIRS:
        if d in parts[:-1]:
            return True, "inside the temp/cache directory {!r}".format(d)

    if fnmatch.fnmatch(name, LOG_GLOB):
        try:
            age_days = ((now or time.time()) - p.stat().st_mtime) / 86400.0
        except OSError:
            return False, "log whose age cannot be read"
        if age_days > LOG_MAX_AGE_DAYS:
            return True, "log {:.1f} days old (> {})".format(
                age_days, LOG_MAX_AGE_DAYS)
        return False, "log only {:.1f} days old".format(age_days)

    return False, "not on the positive allowlist"


def candidates(base=None, now=None) -> list:
    """Every file that BOTH lists have been asked about, with both verdicts.

    Returns the refusals too. A sweep that only reported what it deleted would
    hide the thing worth seeing: that the negative list is doing its job.
    """
    base = pathlib.Path(base or BASE)
    tracked = tracked_files(base)
    out = []
    for p in base.rglob("*"):
        try:
            if not p.is_file():
                continue
        except OSError:
            continue
        ok, why_pos = matches_positive(p, base, now)
        if not ok:
            continue
        blocked, why_neg = is_protected(p, base, tracked)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append({
            "path": _rel(p, base),
            "bytes": size,
            "positive": why_pos,
            "protected": blocked,
            "protected_reason": why_neg,
        })
    return out


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

def sweep(level: str = "action", apply: bool = False, base=None, now=None,
          log_path=None, limit_bytes: Optional[int] = None) -> dict:
    """Dry run by default. Every deletion is logged; every refusal is logged.

    `apply=True` is the ONLY way a byte is removed, and the manifest hash is
    checked before that branch is reachable.
    """
    base = pathlib.Path(base or BASE)
    started = datetime.now(timezone.utc)

    computed = manifest_sha256()
    if computed != MANIFEST_SHA256:
        raise ManifestRefused(
            "manifest sha256 mismatch: stamped {}, computed {} â€” the "
            "allowlists have been edited".format(MANIFEST_SHA256[:16],
                                                 computed[:16]))

    tracked = tracked_files(base)
    if tracked is None:
        return {"ts": started.isoformat(), "level": level, "applied": False,
                "refused": "git could not be asked which files are tracked; "
                           "sweeping without that protection is not allowed",
                "deleted": [], "kept": [], "bytes_freed": 0}

    rows = candidates(base, now)
    deleted, kept, freed = [], [], 0

    for row in rows:
        if row["protected"]:
            kept.append(row)
            continue
        if limit_bytes is not None and freed >= limit_bytes:
            row = dict(row, protected_reason="sweep byte limit reached")
            kept.append(row)
            continue
        if not apply:
            deleted.append(dict(row, would_delete=True))
            freed += row["bytes"]
            continue
        # LAST CHECK, on the resolved path, immediately before unlink. The
        # candidate list could in principle be stale by now.
        target = base / row["path"]
        blocked, why = is_protected(target, base, tracked)
        if blocked:
            kept.append(dict(row, protected=True, protected_reason=why))
            continue
        try:
            target.unlink()
            deleted.append(dict(row, would_delete=False))
            freed += row["bytes"]
        except OSError as exc:
            kept.append(dict(row, protected=False,
                             protected_reason="unlink failed: {}".format(exc)))

    result = {
        "ts": started.isoformat(),
        "level": level,
        "applied": bool(apply),
        "manifest_sha256": computed,
        "deleted": deleted,
        "kept": kept,
        "n_deleted": len(deleted),
        "n_kept": len(kept),
        "bytes_freed": freed,
        "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
    }
    _log(result, log_path)
    return result


def _log(result: dict, log_path=None) -> None:
    """What, why, how many bytes, which level. Durable â€” see core/durable.py."""
    try:
        from core.durable import append_json
        append_json(log_path or SWEEP_LOG, {
            "ts": result["ts"],
            "level": result["level"],
            "applied": result["applied"],
            "n_deleted": result["n_deleted"],
            "n_kept": result["n_kept"],
            "bytes_freed": result["bytes_freed"],
            "manifest_sha256": result.get("manifest_sha256"),
            "deleted": [{"path": d["path"], "bytes": d["bytes"],
                         "why": d["positive"]} for d in result["deleted"][:200]],
            "refused": [{"path": k["path"], "why": k["protected_reason"]}
                        for k in result["kept"] if k.get("protected")][:200],
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------

def _cli(argv) -> int:
    if "--manifest" in argv:
        print(json.dumps(manifest(), ensure_ascii=False, indent=2))
        print("\nsha256 = {}".format(manifest_sha256()))
        print("stamped = {}".format(MANIFEST_SHA256))
        print("match   = {}".format(manifest_sha256() == MANIFEST_SHA256))
        return 0

    print("core/disk_actuator.py â€” DRY RUN. Nothing is deleted.")
    print()
    try:
        res = sweep(level="action", apply=False)
    except ManifestRefused as exc:
        print("  REFUSED: {}".format(exc))
        return 1
    if res.get("refused"):
        print("  REFUSED: {}".format(res["refused"]))
        return 1

    print("  manifest sha256 {}  (verified)".format(res["manifest_sha256"][:16]))
    print()
    print("  WOULD DELETE: {} file(s), {:.1f} MB".format(
        res["n_deleted"], res["bytes_freed"] / 1024 ** 2))
    by_reason = {}
    for d in res["deleted"]:
        by_reason.setdefault(d["positive"].split(" (")[0], [0, 0])
        by_reason[d["positive"].split(" (")[0]][0] += 1
        by_reason[d["positive"].split(" (")[0]][1] += d["bytes"]
    for why, (n, b) in sorted(by_reason.items(), key=lambda kv: -kv[1][1]):
        print("    {:<44} {:>5} files  {:>9.1f} MB".format(why, n, b / 1024 ** 2))
    print()
    for d in sorted(res["deleted"], key=lambda r: -r["bytes"])[:15]:
        print("    {:>9.2f} MB  {}".format(d["bytes"] / 1024 ** 2, d["path"]))
    if res["n_deleted"] > 15:
        print("    ... and {} more".format(res["n_deleted"] - 15))

    blocked = [k for k in res["kept"] if k.get("protected")]
    print()
    print("  REFUSED BY THE NEGATIVE ALLOWLIST: {} file(s)".format(len(blocked)))
    for k in blocked[:15]:
        print("    {:<58} {}".format(k["path"][:58], k["protected_reason"]))
    if len(blocked) > 15:
        print("    ... and {} more".format(len(blocked) - 15))
    print()
    print("  Nothing was deleted. sweep(apply=True) is the only path that "
          "removes a byte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
