#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_improve/merits.py — THE FORK ADVANCES BY STANDARD, NOT BY PERMISSION.

THE PRINCIPLE
--------------
No model output passes a stage unverified; the FORK advances by STANDARD,
production is gated by a human PR.

THE SPLIT THIS MODULE MAKES
----------------------------
Until now one function answered two different questions at once, and the first
answer swallowed the second:

    core.earning.verify()  ->  FAIL, "global_cap is LOCKED"

That is the right answer to "may this be granted capability in production" and
it is a NON-ANSWER to "is this patch any good". Every run ended FAIL for the
same reason, whatever the patch said, so the pipeline could not tell a competent
patch from a confabulated one — the verdict carried no information about the
work. A gate that returns the same answer to every input is not grading.

So the two questions are separated:

    merits.grade()   ->  did the work MEET THE STANDARD?   (evidence only)
    earning.verify() ->  may it enter PRODUCTION?          (ceiling, human PR)

grade() never reads global_cap, never reads earning_classes.json, and cannot be
made to pass or fail by a policy switch. It reads the repository.

THE FOUR MERITS, each mechanical, each traced by name
------------------------------------------------------
  APPLIES     git apply, in a clean sandbox worktree of the fork branch. Not a
              regex opinion about the diff — git's own verdict, from the tool
              that would have to succeed for the patch to exist at all.
  IN SCOPE    every changed path inside the spec's allowed_paths, and none of
              them in the pinned set (the verifier, the policy, the rules of
              passage, the tests that pin them, production memory).
  TESTS PASS  pytest, run INSIDE the sandbox after the patch is applied, so a
              green result describes the patched tree and not this one.
  BEFORE/AFTER the spec's success_metric, recomputed from real files on both
              sides of the patch BY THIS MODULE. The model's own claim about the
              number is never consulted; a number nobody recomputed is the
              FABRICATED verdict execute_patches already refuses.

PASS requires all four. Each merit records the evidence that decided it, so the
record says WHY and not merely WHAT.

FORBIDDEN FALLBACKS, NAMED
---------------------------
  * do NOT return PASS because the sandbox could not be built, the tests could
    not be run, or the metric could not be read. Every one of those is FAIL with
    the reason — "could not check" and "checked and fine" must never collapse.
  * do NOT grade against the dirty working tree. The sandbox is a clean checkout
    of the branch the fork commit would land on; that is the tree the patch has
    to be true about.
  * do NOT let a policy switch decide a merit. If reading global_cap could change
    a grade, the split this module exists to make would be undone.

    venv\\Scripts\\python.exe core/self_improve/merits.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:                # run as a script as well as imported
    sys.path.insert(0, str(REPO))

PASS, FAIL = "PASS", "FAIL"

# The fork branch a run is graded against and would be committed onto.
BASE_BRANCH = "experimental/self-mod"

# Never in scope, whatever a spec says it allows. The first four are the
# verifier, the policy, the rules of passage and the tests that pin them —
# core.earning refuses these too, and both refusals must hold. The rest is
# production state: an experiment that rewrites the memory it is measured
# against is measuring itself.
PINNED = ("core/earning.py", "core/notary.py", "config/earning_classes.json",
          "config/passage_rules.json", "test/", "memory/", "snapshots/",
          "cortex_memory/", "output/")

# Run when no test file names the changed module. Declared here rather than
# discovered, so the record can say exactly which tests a grade stands on.
DEFAULT_SUITE = ("test/test_self_improve_requirer.py",
                 "test/test_self_improve_implementer.py",
                 "test/test_self_improve_pipeline.py",
                 "test/test_patch_must_apply.py")

TEST_TIMEOUT = 900.0


class SandboxUnavailable(Exception):
    """The clean worktree could not be built. FAIL, never PASS."""


def _git(args, cwd, timeout=120.0, stdin: bytes | None = None):
    """(returncode, stdout, stderr) as text. Bytes on stdin, deliberately.

    text=True writes stdin in universal-newline mode, so on Windows every "\\n"
    in a diff becomes "\\r\\n" before git sees it and git then refuses a patch
    that was perfectly correct. That bug cost a full live run once already.
    """
    proc = subprocess.run(["git", *args], cwd=str(cwd),
                          input=stdin, capture_output=True, timeout=timeout)
    dec = lambda b: (b or b"").decode("utf-8", errors="replace")   # noqa: E731
    return proc.returncode, dec(proc.stdout), dec(proc.stderr)


def _norm(p: str) -> str:
    return str(p or "").replace("\\", "/").strip().lstrip("./")


def _under(path: str, prefix: str) -> bool:
    p, q = _norm(path), _norm(prefix)
    return p == q or p.startswith(q if q.endswith("/") else q + "/")


# ---------------------------------------------------------------------------
# the sandbox
# ---------------------------------------------------------------------------

class Sandbox:
    """A clean git worktree of the fork branch, thrown away afterwards.

    THE PATCH IS GRADED SOMEWHERE THAT IS NOT THIS WORKING TREE. Applying a
    model's diff to the tree the human is working in is the one thing an
    experimental pipeline must never do, and a grade taken from a dirty tree
    describes a state that will never exist again anyway.
    """

    def __init__(self, base: str = BASE_BRANCH, repo: Path | None = None):
        self.repo = Path(repo or REPO)
        self.base = base
        self.path: Path | None = None

    def __enter__(self) -> "Sandbox":
        tmp = Path(tempfile.mkdtemp(prefix="selfmod_sandbox_"))
        self.path = tmp / "tree"
        rc, _out, err = _git(["worktree", "add", "--detach",
                              str(self.path), self.base], cwd=self.repo)
        if rc != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            self.path = None
            raise SandboxUnavailable(
                f"could not create a clean worktree of {self.base!r}: {err.strip()}")
        self._tmp = tmp
        return self

    def __exit__(self, *exc) -> bool:
        if self.path is not None:
            _git(["worktree", "remove", "--force", str(self.path)], cwd=self.repo)
            shutil.rmtree(getattr(self, "_tmp", self.path.parent), ignore_errors=True)
        return False


# ---------------------------------------------------------------------------
# the four merits
# ---------------------------------------------------------------------------

def merit_in_scope(changed_files, spec: dict) -> dict:
    """Every changed path inside the allowlist, none of them pinned."""
    allowed = [_norm(a) for a in (spec.get("allowed_paths") or [])]
    changed = [_norm(f) for f in (changed_files or [])]
    ev = {"name": "in_scope", "changed": changed, "allowed": allowed}

    if not changed:
        return {**ev, "ok": False, "why": "the patch changes no file"}
    for f in changed:
        for pin in PINNED:
            if _under(f, pin):
                return {**ev, "ok": False,
                        "why": f"{f} is PINNED ({pin}) — the verifier, the policy, "
                               f"the rules of passage, the tests that pin them and "
                               f"production state are out of reach of every patch, "
                               f"whatever a spec allows"}
    if not allowed:
        return {**ev, "ok": False, "why": "the spec allows no path at all"}
    for f in changed:
        if not any(_under(f, a) for a in allowed):
            return {**ev, "ok": False,
                    "why": f"{f} is outside the spec's allowed_paths {allowed}"}
    return {**ev, "ok": True, "why": f"{len(changed)} file(s) inside {allowed}"}


def merit_applies(diff: str, tree: Path) -> dict:
    """git applies the patch to the clean tree, for real, and says so."""
    ev = {"name": "applies", "tree": str(tree)}
    if not (diff or "").strip():
        return {**ev, "ok": False, "why": "empty diff"}
    rc, _out, err = _git(["apply", "--verbose", "-"], cwd=tree,
                         stdin=diff.encode("utf-8"))
    if rc != 0:
        return {**ev, "ok": False,
                "why": f"git refused the patch on a clean checkout: {err.strip()[:600]}"}
    rc2, out2, _e = _git(["status", "--porcelain"], cwd=tree)
    touched = [ln[3:].strip() for ln in out2.splitlines() if ln.strip()]
    return {**ev, "ok": True, "why": "git applied it", "touched": touched}


def select_tests(changed_files, tree: Path) -> tuple:
    """(paths, why). Tests that NAME a changed module, else the declared suite.

    The choice is recorded rather than hidden, because "the tests passed" means
    nothing until the record says which tests they were.
    """
    stems = {Path(_norm(f)).stem for f in (changed_files or []) if f}
    stems.discard("")
    hits = []
    tdir = tree / "test"
    if tdir.is_dir() and stems:
        for tf in sorted(tdir.glob("test_*.py")):
            try:
                body = tf.read_text(encoding="utf-8", errors="replace")
            except Exception:                                    # noqa: BLE001
                continue
            if any(re.search(r"\b" + re.escape(s) + r"\b", body) for s in stems):
                hits.append(f"test/{tf.name}")
    if hits:
        return hits, f"targeted: {len(hits)} test file(s) name {sorted(stems)}"
    return list(DEFAULT_SUITE), (f"no test file names {sorted(stems)}; ran the "
                                 f"declared default suite instead")


def merit_tests(changed_files, tree: Path, timeout: float = TEST_TIMEOUT) -> dict:
    """pytest INSIDE the sandbox, after the patch is applied."""
    paths, why = select_tests(changed_files, tree)
    ev = {"name": "tests_pass", "tests": paths, "selection": why}
    present = [p for p in paths if (tree / p).exists()]
    if not present:
        return {**ev, "ok": False,
                "why": f"none of the selected tests exist in the sandbox: {paths}"}
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *present, "-q", "-p", "no:randomly"],
            cwd=str(tree), capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {**ev, "ok": False, "timed_out": True,
                "why": f"the tests timed out after {timeout}s — a timeout is not a pass"}
    except Exception as exc:                                     # noqa: BLE001
        return {**ev, "ok": False,
                "why": f"the tests could not be run: {type(exc).__name__}: {exc}"}
    tail = [l for l in (proc.stdout or "").splitlines() if l.strip()]
    summary = tail[-1][:300] if tail else ""
    return {**ev, "ok": proc.returncode == 0, "exit_code": proc.returncode,
            "summary": summary,
            "why": (f"pytest exited {proc.returncode} on {present}: {summary}")}


# The metric's path shapes are defined once, by the requirer that enforces them
# at spec time. Re-declaring them here is how the two halves of one rule drift
# apart until a metric passes one and fails the other.
from core.self_improve.requirer import _METRIC_PATH          # noqa: E402


def measure(metric: str, tree: Path) -> dict:
    """Every real file the metric names, measured mechanically. No model.

    rows is the honest number for the shapes this repo stores: a JSON list's
    length, a JSON object's key count, a JSONL/CSV/text file's line count.
    """
    out = {}
    for cand in _METRIC_PATH.findall(str(metric or "")):
        rel = _norm(cand).strip("'\"` ")
        p = tree / rel
        if not p.is_file():
            continue
        info = {"bytes": p.stat().st_size}
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:                                 # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}"
            out[rel] = info
            continue
        info["lines"] = len(text.splitlines())
        if rel.endswith(".json"):
            try:
                doc = json.loads(text)
                info["rows"] = len(doc) if isinstance(doc, (list, dict)) else 1
            except Exception:                                    # noqa: BLE001
                info["rows"] = None
        else:
            info["rows"] = info["lines"]
        out[rel] = info
    return out


def merit_before_after(spec: dict, before: dict, after: dict) -> dict:
    """The metric, recomputed on BOTH sides by this module.

    The model's own claim about the number is never consulted. A metric that
    names no readable file cannot be recomputed, and something nobody can
    recompute cannot be evidence — that is FAIL, not a warning.
    """
    metric = str(spec.get("success_metric", ""))
    ev = {"name": "before_after", "metric": metric,
          "before": before, "after": after}
    if not before:
        return {**ev, "ok": False,
                "why": f"success_metric {metric!r} named no readable file in the "
                       f"sandbox, so there is no before to compare against"}
    missing = [k for k in before if k not in after]
    if missing:
        return {**ev, "ok": False,
                "why": f"the patch removed the file(s) the metric is read from: {missing}"}
    delta = {k: {"rows": (after[k].get("rows"), before[k].get("rows")),
                 "bytes": after[k].get("bytes", 0) - before[k].get("bytes", 0)}
             for k in before}
    moved = [k for k in before
             if after[k].get("rows") != before[k].get("rows")
             or after[k].get("bytes") != before[k].get("bytes")]
    return {**ev, "ok": True, "delta": delta, "moved": moved,
            "why": (f"recomputed on both sides of the patch from {sorted(before)}; "
                    f"{'changed: ' + str(moved) if moved else 'unchanged'}")}


# ---------------------------------------------------------------------------
# the grade
# ---------------------------------------------------------------------------

def grade(spec: dict, diff: str, changed_files=None, base: str = BASE_BRANCH,
          repo: Path | None = None, run_tests: bool = True) -> dict:
    """(the whole record). decision is PASS only if all four merits hold.

    NEVER reads global_cap, earning_classes.json or any ceiling. A patch is
    graded on what it does to the repository, and nothing else.
    """
    changed = list(changed_files or [])
    merits, decision = [], FAIL

    scope = merit_in_scope(changed, spec)
    merits.append(scope)

    try:
        with Sandbox(base=base, repo=repo) as sb:
            tree = sb.path
            before = measure(spec.get("success_metric", ""), tree)
            ap = merit_applies(diff, tree)
            merits.append(ap)
            if ap["ok"]:
                merits.append(merit_tests(changed, tree) if run_tests else
                              {"name": "tests_pass", "ok": False,
                               "why": "tests were not run, so they cannot have passed"})
                after = measure(spec.get("success_metric", ""), tree)
                merits.append(merit_before_after(spec, before, after))
            else:
                # The later merits are UNREACHED, not passed. Saying so keeps a
                # blocked run from reading like a partially good one.
                merits.append({"name": "tests_pass", "ok": False,
                               "why": "unreached: the patch does not apply"})
                merits.append({"name": "before_after", "ok": False,
                               "why": "unreached: the patch does not apply"})
    except SandboxUnavailable as exc:
        merits.append({"name": "applies", "ok": False, "why": str(exc)})
        merits.append({"name": "tests_pass", "ok": False,
                       "why": "unreached: no sandbox"})
        merits.append({"name": "before_after", "ok": False,
                       "why": "unreached: no sandbox"})

    failed = [m["name"] for m in merits if not m.get("ok")]
    decision = PASS if not failed else FAIL
    reason = ("all four merits hold: " +
              "; ".join(f"{m['name']} ({m['why']})" for m in merits)
              if decision == PASS else
              "failed on " + ", ".join(failed) + ": " +
              "; ".join(f"{m['name']}: {m['why']}" for m in merits
                        if not m.get("ok")))
    return {"decision": decision, "reason": reason, "merits": merits,
            "base": base, "graded_on": "evidence, not the production ceiling"}


def _code_only(path: Path, drop=("_selftest", "_code_only")) -> str:
    """The module's executable code, without docstrings or the selftest.

    Exported so the test suite pins the same rule the selftest checks, from the
    same function, rather than two grep patterns that drift apart.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body
                 if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and n.name in drop)]
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def _selftest() -> int:
    print("core/self_improve/merits.py --selftest")

    ok = True
    rc, out, _e = _git(["rev-parse", "--verify", BASE_BRANCH], cwd=REPO)
    print(f"  base branch {BASE_BRANCH:<22}: "
          f"{'LIVE (' + out.strip()[:8] + ')' if rc == 0 else 'MISSING'}")
    if rc != 0:
        return 1

    try:
        with Sandbox() as sb:
            print(f"  clean sandbox worktree      : LIVE ({sb.path.name})")
            n = len(list(sb.path.glob("*")))
            print(f"  it is a real checkout       : {n} top-level entries")
    except SandboxUnavailable as exc:
        print(f"  clean sandbox worktree      : INERT ({exc})")
        return 1

    # A patch that cannot apply must FAIL, and must not report the later merits
    # as passed.
    ghost = ("--- a/agents/core/self_observer.py\n"
             "+++ b/agents/core/self_observer.py\n"
             "@@ -1,1 +1,1 @@\n-def self_observe(prompt):\n+def self_observe(p):\n")
    g = grade({"allowed_paths": ["agents/core/self_observer.py"],
               "success_metric": "the number of rows in memory/goal_score_history.json"},
              ghost, ["agents/core/self_observer.py"], run_tests=False)
    print(f"  a confabulated patch        : {g['decision']} "
          f"({'correct' if g['decision'] == FAIL else 'WRONG — the net is open'})")
    ok &= g["decision"] == FAIL

    pinned = grade({"allowed_paths": ["core/earning.py"], "success_metric": "x"},
                   "", ["core/earning.py"], run_tests=False)
    scope = [m for m in pinned["merits"] if m["name"] == "in_scope"][0]
    print(f"  a patch to the verifier     : "
          f"{'refused as PINNED' if not scope['ok'] else 'ALLOWED — wrong'}")
    ok &= not scope["ok"]

    # The split itself: no ceiling is consulted anywhere in this module. Checked
    # on the CODE, with the docstrings and this selftest stripped out — grepping
    # the file would fire on the prose that explains the rule, which is how a
    # structural check quietly becomes a spell-checker.
    code = _code_only(Path(__file__))
    leaks = [t for t in ("global_cap", "load_classes", "max_cap_ceiling",
                         "core.earning", "from core import earning")
             if t in code]
    # config/earning_classes.json appears in PINNED — as a file no patch may
    # TOUCH, which is the opposite of consulting it — so it is not a leak.
    print(f"  reads no production ceiling : "
          f"{'clean' if not leaks else 'LEAKS ' + str(leaks)}")
    ok &= not leaks

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
