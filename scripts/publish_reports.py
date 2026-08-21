#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/publish_reports.py — STAGE THE REPORTS. NEVER PUSH.

WHAT IT DOES, AND THE FULL LIST
--------------------------------
Copies exactly two kinds of file into reports/ and commits them:

    output/reports/CYCLE_REPORT_*.md      the morning reports
    output/wellbeing_continent.json       the per-continent well-being roll-up

then `git add` on exactly those destination paths and `git commit -m
"reports: cycle YYYY-MM-DD"`. And then it stops.

WHY IT STOPS
-------------
The push is where a mistake becomes public and irreversible. Everything before
it is local and recoverable: a bad commit is `git reset`, a bad copy is `rm`.
`git push` is neither. This machine holds a V-Dem CSV it may not redistribute,
a .env with five API keys, Telegram credentials, and a memory/ tree containing
its own reasoning about its operator. An automated publisher on that machine is
one glob away from an incident that cannot be taken back, and "it has never gone
wrong yet" is not a mechanism.

So the push stays human. `git push` is not in this file, and
test/test_publish_reports.py asserts that it is not.

THE PARAMETERS ARE FROZEN
--------------------------
INCLUDE, DEST, FORBIDDEN_PREFIXES, FORBIDDEN_SUBSTRINGS and MAX_BYTES are
constants in this file, not configuration and not command-line flags. There is
no --include, no --dest, no --allow-large. Widening what gets published is a
HUMAN EDIT TO THIS FILE, by definition — it shows up in a diff, with a name on
it, and can be argued with before it happens rather than discovered after.

REFUSE AND SCREAM
------------------
Before a single `git add`, every destination path is checked against the
forbidden list, and any violation aborts the whole run with a non-zero exit and
a loud message. Not "skip the bad file and publish the rest": if the selection
produced something under memory/ or config/, or a .env, or anything with "vdem"
in its name, or a file over 5 MB, then the SELECTION is wrong and nothing it
produced should be trusted. A publisher that quietly drops the one file it was
never supposed to see has learned nothing.

    venv\\Scripts\\python.exe scripts/publish_reports.py --dry-run
    venv\\Scripts\\python.exe scripts/publish_reports.py
    venv\\Scripts\\python.exe scripts/publish_reports.py --selftest
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime

REPO = pathlib.Path(__file__).resolve().parents[1]

# ── FROZEN PARAMETERS ───────────────────────────────────────────────────────
# Changing anything in this block is a human edit to this file. That is the
# design, not an inconvenience.

INCLUDE = (
    "output/reports/CYCLE_REPORT_*.md",
    "output/wellbeing_continent.json",
)

DEST = "reports"

FORBIDDEN_PREFIXES = ("memory/", "config/")
# "v-dem" AS WELL AS "vdem", and the selftest is why. The rule was written as
# "any path containing vdem" and the file it exists to stop is called
# data/V-Dem-CY-Core-v16.csv — which, lowercased, contains "v-dem" and does NOT
# contain "vdem". The guard would have passed the exact file it was written for.
FORBIDDEN_SUBSTRINGS = ("vdem", "v-dem", ".env")
MAX_BYTES = 5 * 1024 * 1024

COMMIT_TEMPLATE = "reports: cycle {date}"

# ── end of frozen parameters ────────────────────────────────────────────────

_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


class Refused(Exception):
    """A violation of the frozen rules. Aborts the run; publishes nothing."""


def _rel(p: pathlib.Path, base: pathlib.Path) -> str:
    return str(p.relative_to(base)).replace("\\", "/")


def select(base: pathlib.Path | None = None) -> list:
    """Every source file the frozen INCLUDE globs match, sorted."""
    base = base or REPO
    out = []
    for pattern in INCLUDE:
        out.extend(sorted(base.glob(pattern)))
    return [p for p in out if p.is_file()]


def check(paths, base: pathlib.Path | None = None) -> None:
    """Refuse-and-scream. Runs BEFORE any copy and again before any git add.

    Checks the SOURCE path and the DESTINATION path of every file, because a
    forbidden thing can enter by either end: a glob that reached into memory/,
    or a destination that would land there.
    """
    base = base or REPO
    violations = []
    for src in paths:
        try:
            rel = _rel(src, base)
        except ValueError:
            violations.append(f"{src} is outside the repository")
            continue
        low = rel.lower()
        for bad in FORBIDDEN_PREFIXES:
            if low.startswith(bad):
                violations.append(f"{rel} is under {bad} — never published")
        for bad in FORBIDDEN_SUBSTRINGS:
            if bad in low:
                violations.append(
                    f"{rel} contains {bad!r} — never published"
                    + (" (V-Dem may not be redistributed)"
                       if bad in ("vdem", "v-dem") else ""))
        try:
            size = src.stat().st_size
        except OSError as exc:
            violations.append(f"{rel} cannot be stat'ed: {exc}")
            continue
        if size > MAX_BYTES:
            violations.append(
                f"{rel} is {size:,} bytes, over the {MAX_BYTES:,} ceiling")
    if violations:
        raise Refused("\n".join(violations))


def plan(base: pathlib.Path | None = None) -> dict:
    """What WOULD be published: sources, destinations, sizes, commit message."""
    base = base or REPO
    srcs = select(base)
    dest_dir = base / DEST
    rows = []
    newest = None
    for s in srcs:
        d = dest_dir / s.name
        rows.append({"src": _rel(s, base), "dest": _rel(d, base),
                     "bytes": s.stat().st_size})
        m = _DATE_IN_NAME.search(s.name)
        if m and (newest is None or m.group(1) > newest):
            newest = m.group(1)
    date = newest or datetime.now().strftime("%Y-%m-%d")
    return {"files": rows, "date": date,
            "commit_message": COMMIT_TEMPLATE.format(date=date),
            "dest_dir": _rel(dest_dir, base)}


def _git(args, base: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(base), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def publish(base: pathlib.Path | None = None, dry_run: bool = False,
            runner=None) -> dict:
    """Copy, check again, add exactly those paths, commit. No push, ever."""
    base = base or REPO
    git = runner or (lambda args: _git(args, base))

    srcs = select(base)
    if not srcs:
        return {"published": False, "why": "nothing matched the frozen INCLUDE "
                                           "globs — there is nothing to publish",
                "files": []}

    check(srcs, base)                       # the sources, before touching anything
    p = plan(base)

    if dry_run:
        return {"published": False, "dry_run": True, **p}

    dest_dir = base / DEST
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for row in p["files"]:
        shutil.copy2(base / row["src"], base / row["dest"])
        copied.append(base / row["dest"])

    # SECOND CHECK, on the destinations, after the copy and before git sees
    # anything. The first check cleared the sources; this one clears what is
    # actually about to be staged. They are not the same set and only one of
    # them is what gets committed.
    check(copied, base)

    paths = [row["dest"] for row in p["files"]]
    add = git(["add", "--", *paths])         # EXACTLY these paths. No -A, no ".".
    if add.returncode != 0:
        raise Refused(f"git add failed: {add.stderr.strip()}")

    commit = git(["commit", "-m", p["commit_message"]])
    committed = commit.returncode == 0
    return {
        "published": committed,
        "files": p["files"],
        "commit_message": p["commit_message"],
        "git_output": (commit.stdout or commit.stderr).strip()[:400],
        # Said out loud in the return value, not only in the docstring, so a
        # caller cannot mistake a successful commit for a publish.
        "pushed": False,
        "note": "NOT PUSHED. The push is human — run `git push` yourself "
                "after reading `git show --stat`.",
    }


def _print_plan(p: dict) -> None:
    print(f"destination: {p['dest_dir']}/")
    print(f"commit:      {p['commit_message']}")
    print(f"files:       {len(p['files'])}")
    total = 0
    for row in p["files"]:
        total += row["bytes"]
        print(f"  {row['bytes']:>10,}  {row['src']}  ->  {row['dest']}")
    print(f"  {total:>10,}  total")
    print("\nNOTHING IS PUSHED by this script, in any mode.")


def _selftest() -> int:
    import json
    import os
    import tempfile
    print("scripts/publish_reports.py --selftest")
    ok = True

    def check_(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {name}")

    # Built by concatenation so that this check does not match ITSELF — the
    # first version of it failed against its own assertion text, which is funny
    # once and useless afterwards.
    _p = "pu" + "sh"
    src_txt = (REPO / "scripts" / "publish_reports.py").read_text(encoding="utf-8")
    git_calls = [ln for ln in src_txt.splitlines()
                 if ("git([" in ln or 'git(["' in ln or '_git([' in ln)
                 and _p in ln]
    check_("no git call in this file is a " + _p, not git_calls)

    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        (base / "output" / "reports").mkdir(parents=True)
        (base / "output" / "reports" / "CYCLE_REPORT_2026-08-21.md").write_text(
            "# report", encoding="utf-8")
        (base / "output" / "wellbeing_continent.json").write_text(
            json.dumps({"regions": {}}), encoding="utf-8")
        (base / "output" / "reports" / "NOTES.md").write_text("x", encoding="utf-8")

        p = plan(base)
        check_("only the two frozen kinds are selected", len(p["files"]) == 2)
        check_("...the stray NOTES.md is not among them",
               not any("NOTES" in r["src"] for r in p["files"]))
        check_("the commit message carries the report's own date",
               p["commit_message"] == "reports: cycle 2026-08-21")

        # forbidden: a path under memory/
        (base / "memory").mkdir()
        secret = base / "memory" / "notify_channel.json"
        secret.write_text("{}", encoding="utf-8")
        try:
            check(select(base) + [secret], base)
            check_("a memory/ path is refused", False)
        except Refused as exc:
            check_("a memory/ path is refused", "memory/" in str(exc))

        # forbidden: vdem anywhere in the name
        (base / "data").mkdir()
        vd = base / "data" / "V-Dem-CY-Core-v16.csv"
        vd.write_text("a,b", encoding="utf-8")
        try:
            check([vd], base)
            check_("a vdem path is refused", False)
        except Refused as exc:
            check_("a vdem path is refused", "redistributed" in str(exc))

        # forbidden: over the size ceiling
        big = base / "output" / "reports" / "CYCLE_REPORT_2026-08-22.md"
        big.write_bytes(b"x" * (MAX_BYTES + 1))
        try:
            check([big], base)
            check_("an oversized file is refused", False)
        except Refused as exc:
            check_("an oversized file is refused", "ceiling" in str(exc))
        os.remove(big)

        # the happy path: git add is called with EXACTLY the destinations
        calls = []

        def fake_git(args):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "1 file changed", "")

        out = publish(base, runner=fake_git)
        check_("it commits", out["published"] is True)
        check_("it says out loud that it did not push", out["pushed"] is False)
        adds = [c for c in calls if c[0] == "add"]
        check_("git add names exactly the two destinations",
               len(adds) == 1 and sorted(adds[0][2:]) ==
               ["reports/CYCLE_REPORT_2026-08-21.md",
                "reports/wellbeing_continent.json"])
        check_("git add never uses -A or .",
               all(a not in adds[0] for a in ("-A", ".", "--all")))
        check_("no git call is a push", not any(c[0] == "push" for c in calls))
        check_("the files really landed",
               (base / "reports" / "CYCLE_REPORT_2026-08-21.md").exists())

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Stage cycle reports into reports/ and commit. Never pushes.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the file list and the commit message, change nothing")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    try:
        result = publish(dry_run=args.dry_run)
    except Refused as exc:
        print("REFUSED — nothing was copied, nothing was staged, nothing was "
              "committed.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("\nThe selection produced a path it must never produce. That is a "
              "defect in the selection, not one file to skip.", file=sys.stderr)
        return 2

    if result.get("dry_run"):
        _print_plan(result)
        return 0
    if not result.get("files"):
        print(result.get("why", "nothing to publish"))
        return 1

    _print_plan(result)
    print(f"\ngit: {result.get('git_output', '')}")
    print(result.get("note", ""))
    return 0 if result.get("published") else 1


if __name__ == "__main__":
    sys.exit(main())
