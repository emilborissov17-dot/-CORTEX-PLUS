#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_improve/forkadvance.py — A PASS ON MERITS BECOMES A COMMIT IN THE FORK.

THE PRINCIPLE
--------------
No model output passes a stage unverified; the FORK advances by STANDARD,
production is gated by a human PR.

WHAT THIS MODULE IS FOR
------------------------
Until now the pipeline printed a diff and stopped, because the only verdict
available to it was "global_cap is LOCKED" — an answer about production, given
to a question about a patch. So a good patch and a confabulated one ended the
same way: printed, and thrown away. Nothing could ever advance, which means
nothing could ever be shown to work.

The split is: core.self_improve.merits grades the work on evidence, and when it
says PASS, THIS module makes the work real — on a branch of its own, off the
experimental fork, and nowhere near main.

WHERE THE COMMIT GOES, AND WHERE IT CANNOT GO
----------------------------------------------
    experimental/self-mod                  <- the fork this branches OFF
    experimental/self-mod-run-<id>         <- the branch this creates and commits to
    main / master                          <- UNREACHABLE from this file

A human PR is the only thing that can move a fork commit toward main. This
module has no push, no merge, no rebase and no checkout of any branch outside
the run prefix; the tests in test/test_fork_advances.py assert that structurally,
against the parsed code rather than the prose, so the pin survives an edit that
means well.

IT NEVER TOUCHES THE HUMAN'S WORKING TREE
------------------------------------------
The patch is applied inside a throwaway git worktree checked out from the fork
branch. The user's checkout, their current branch and their uncommitted changes
are not read, not stashed and not modified. What persists afterwards is a branch
ref and a commit object — nothing on disk that anyone was using.

FORBIDDEN FALLBACKS, NAMED
---------------------------
  * do NOT commit when the grade is not PASS. "It nearly passed" is not a merit.
  * do NOT commit to the base branch to save creating one — a run that appends to
    experimental/self-mod directly is a run that cannot be thrown away.
  * do NOT `git add -A`. Only the files the patch was graded on are staged; a
    stray file swept up by -A is a change nobody verified.
  * do NOT retry a failed apply here. Applying is not the place to be clever;
    the patch was already proven to apply during grading, so a failure here means
    the tree moved underneath the run and the honest answer is to stop.

    venv\\Scripts\\python.exe core/self_improve/forkadvance.py --selftest
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.self_improve.merits import PINNED, _norm, _under   # noqa: E402

BASE_BRANCH = "experimental/self-mod"
BRANCH_PREFIX = "experimental/self-mod-run-"

# Named so the record says WHY nothing advanced, without parsing prose.
CODE_NOT_PASSED = "REFUSED_ADVANCE_NOT_PASSED"
CODE_BAD_BRANCH = "REFUSED_ADVANCE_BRANCH_NOT_A_RUN_BRANCH"
CODE_BAD_BASE = "REFUSED_ADVANCE_BASE_NOT_EXPERIMENTAL"
CODE_PINNED = "REFUSED_ADVANCE_TOUCHES_PINNED_PATH"
CODE_GIT = "REFUSED_ADVANCE_GIT_SAID_NO"


class AdvanceRefused(Exception):
    """The fork did not advance, and the reason is the result."""


def _git(args, cwd, timeout=180.0, stdin: bytes | None = None):
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          input=stdin, capture_output=True, timeout=timeout)
    dec = lambda b: (b or b"").decode("utf-8", errors="replace")   # noqa: E731
    return proc.returncode, dec(proc.stdout), dec(proc.stderr)


def run_branch(run_id: str) -> str:
    """experimental/self-mod-run-<id>, with the id made safe for a ref name.

    A branch name built from unchecked model-adjacent text is a shell-shaped
    hole; git would refuse most of it, but "would refuse" is not a guarantee.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(run_id or "")).strip("-.") or "unnamed"
    return BRANCH_PREFIX + safe[:60]


def _assert_safe(branch: str, base: str, changed) -> None:
    """The three pins, before git is asked to do anything at all."""
    if not branch.startswith(BRANCH_PREFIX):
        raise AdvanceRefused(
            f"{CODE_BAD_BRANCH}: {branch!r} is not a per-run branch. This module "
            f"commits only to {BRANCH_PREFIX}<id>; main, master and the fork "
            f"branch itself are unreachable from here by construction.")
    if not base.startswith("experimental/"):
        raise AdvanceRefused(
            f"{CODE_BAD_BASE}: {base!r} is not an experimental branch. A run "
            f"branches off the fork; branching off main would put an unreviewed "
            f"commit one merge away from production.")
    for f in (changed or []):
        for pin in PINNED:
            if _under(_norm(f), pin):
                raise AdvanceRefused(
                    f"{CODE_PINNED}: {f} is PINNED ({pin}). The verifier, the "
                    f"policy, the rules of passage, the tests that pin them and "
                    f"production state are out of reach of every patch — the "
                    f"grader refuses them and so does the committer, because one "
                    f"net is a single point of failure.")


def advance(diff: str, spec: dict, run_id: str, grade: dict,
            base: str = BASE_BRANCH, repo: Path | None = None,
            changed_files=None) -> dict:
    """Commit a PASSING patch to its own branch off the fork. Raises otherwise.

    Returns {branch, commit, base_commit, files} — the branch name is the point:
    a human can read the diff, run the tests, and open the PR that is the ONLY
    path to main.
    """
    root = Path(repo or REPO)
    changed = [_norm(f) for f in (changed_files or [])]

    if (grade or {}).get("decision") != "PASS":
        raise AdvanceRefused(
            f"{CODE_NOT_PASSED}: the grade is {(grade or {}).get('decision')!r}, "
            f"so nothing advances. {(grade or {}).get('reason', '')[:400]}")

    branch = run_branch(run_id)
    _assert_safe(branch, base, changed)

    rc, base_sha, err = _git(["rev-parse", "--verify", base], cwd=root)
    if rc != 0:
        raise AdvanceRefused(f"{CODE_GIT}: base branch {base!r} does not exist: "
                             f"{err.strip()}")
    base_sha = base_sha.strip()

    tmp = Path(tempfile.mkdtemp(prefix="selfmod_advance_"))
    tree = tmp / "tree"
    try:
        rc, _o, err = _git(["worktree", "add", "-b", branch, str(tree), base],
                           cwd=root)
        if rc != 0:
            raise AdvanceRefused(
                f"{CODE_GIT}: could not create the run branch {branch!r}: "
                f"{err.strip()}")

        rc, _o, err = _git(["apply", "--verbose", "-"], cwd=tree,
                           stdin=(diff or "").encode("utf-8"))
        if rc != 0:
            raise AdvanceRefused(
                f"{CODE_GIT}: the patch graded PASS but will not apply to a fresh "
                f"checkout of {base!r}: {err.strip()[:400]}. The tree moved under "
                f"the run; stopping rather than re-deriving a patch nobody graded.")

        # ONLY the graded files. `git add -A` would sweep up anything the apply
        # happened to leave behind, and a file nobody verified would ride into
        # the commit under a PASS that was not about it.
        rc, _o, err = _git(["add", "--", *changed], cwd=tree)
        if rc != 0:
            raise AdvanceRefused(f"{CODE_GIT}: could not stage {changed}: {err.strip()}")

        rc, staged, _e = _git(["diff", "--cached", "--name-only"], cwd=tree)
        staged_files = [s.strip() for s in staged.splitlines() if s.strip()]
        if not staged_files:
            raise AdvanceRefused(
                f"{CODE_GIT}: the patch applied but staged nothing — there is no "
                f"change to commit, and an empty commit is a claim without work.")

        msg = _message(spec, grade, run_id, staged_files)
        rc, _o, err = _git(["commit", "--no-verify", "-m", msg], cwd=tree)
        if rc != 0:
            raise AdvanceRefused(f"{CODE_GIT}: the commit failed: {err.strip()}")

        rc, sha, _e = _git(["rev-parse", "HEAD"], cwd=tree)
        return {"branch": branch, "commit": sha.strip(), "base": base,
                "base_commit": base_sha, "files": staged_files,
                "path_to_main": "a human PR, and nothing else"}
    finally:
        # The worktree is temporary; the BRANCH is what persists. Removing the
        # worktree does not remove the ref, which is the whole point.
        _git(["worktree", "remove", "--force", str(tree)], cwd=root)
        shutil.rmtree(tmp, ignore_errors=True)


def _message(spec: dict, grade: dict, run_id: str, files) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merits = "\n".join(f"  {m.get('name'):<13} {'PASS' if m.get('ok') else 'FAIL'}  "
                       f"{str(m.get('why'))[:160]}"
                       for m in (grade or {}).get("merits") or [])
    return (
        f"self-improve run {run_id}: {str(spec.get('desired_change', ''))[:60]}\n"
        f"\n"
        f"WRITTEN BY THE PIPELINE, GRADED ON MERITS, COMMITTED TO THE FORK.\n"
        f"This commit is on a per-run branch off {BASE_BRANCH}. It is NOT on main\n"
        f"and cannot reach main except through a human pull request.\n"
        f"\n"
        f"  problem        {str(spec.get('problem', ''))[:120]}\n"
        f"  root cause     {str(spec.get('root_cause', ''))[:120]}\n"
        f"  change         {str(spec.get('desired_change', ''))[:120]}\n"
        f"  metric         {str(spec.get('success_metric', ''))[:120]}\n"
        f"  goal axis      {spec.get('goal_axis')}\n"
        f"  files          {', '.join(files)}\n"
        f"\n"
        f"MERITS (evidence only — no production ceiling was consulted):\n"
        f"{merits}\n"
        f"\n"
        f"Graded {stamp} by core/self_improve/merits.py.\n")


def _selftest() -> int:
    print("core/self_improve/forkadvance.py --selftest")
    ok = True

    rc, _o, _e = _git(["rev-parse", "--verify", BASE_BRANCH], cwd=REPO)
    print(f"  fork branch {BASE_BRANCH:<22}: {'LIVE' if rc == 0 else 'MISSING'}")
    ok &= rc == 0

    print(f"  a run branch is named       : {run_branch('20260908T101500Z')}")

    for label, kw in (
            ("a FAIL never advances", dict(grade={"decision": "FAIL", "reason": "x"})),
            ("main is unreachable", dict(grade={"decision": "PASS"}, base="main")),
            ("a pinned path is refused",
             dict(grade={"decision": "PASS"}, changed_files=["core/earning.py"]))):
        try:
            advance("", {}, "selftest", **{**{"base": BASE_BRANCH}, **kw})
            print(f"  {label:<27} : NOT REFUSED — the pin is open")
            ok = False
        except AdvanceRefused as exc:
            print(f"  {label:<27} : refused ({str(exc).split(':')[0]})")

    rc, out, _e = _git(["branch", "--list", BRANCH_PREFIX + "*"], cwd=REPO)
    n = len([l for l in out.splitlines() if l.strip()])
    print(f"  existing run branches       : {n}")

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
