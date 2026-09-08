#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_fork_advances.py — THE FORK MAY ADVANCE; PRODUCTION MAY NOT BE TOUCHED.

EXPERIMENTAL (branch experimental/self-mod). Nothing under test here is wired
into the cycle.

WHAT THIS SUITE IS FOR
-----------------------
Two opposite failures, and a test file that only guarded one of them would be
worse than none:

  1. NOTHING CAN EVER PASS. Before the split, core.earning.verify() answered
     every run with "global_cap is LOCKED" — the right answer to a question
     about production, given to a question about a patch. A gate that returns
     the same verdict to every input is not grading, and a pipeline that can
     never advance can never be shown to work. So this suite pins a DEMONSTRABLE
     PATH TO PASS: a real patch, graded on merits, committed to a real branch.

  2. IT ADVANCES SOMEWHERE IT MUST NOT. So this suite also pins the three
     safety limits, behaviourally and structurally:
        * the pipeline NEVER commits to main or master;
        * it NEVER writes production memory/ or snapshots/;
        * only a HUMAN PR can move a fork commit toward main — there is no push,
          no merge and no rebase anywhere in the advancing code.

Every git test runs in a THROWAWAY repository under tmp_path. A suite that
created branches in the real repo to prove it can create branches would leave
the mess it is testing against.

    venv\\Scripts\\python.exe -m pytest test/test_fork_advances.py -v
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess

import pytest

from core.self_improve import forkadvance as FA
from core.self_improve import merits as M

REPO = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# a throwaway repository, shaped like this one
# ---------------------------------------------------------------------------

def _run(args, cwd):
    p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, f"{args} failed: {p.stderr or p.stdout}"
    return p.stdout


def _sha(ref, cwd):
    return _run(["git", "rev-parse", ref], cwd).strip()


@pytest.fixture()
def tiny(tmp_path):
    """A repo with a master, an experimental/self-mod, a target file, and
    production trees that must not move."""
    root = tmp_path / "repo"
    root.mkdir()
    _run(["git", "init", "-b", "master"], root)
    _run(["git", "config", "user.email", "t@example.invalid"], root)
    _run(["git", "config", "user.name", "test"], root)

    (root / "data_providers").mkdir()
    (root / "data_providers" / "thing_provider.py").write_text(
        "def fetch():\n    return 1\n", encoding="utf-8")
    (root / "memory").mkdir()
    (root / "memory" / "goal_score_history.json").write_text(
        json.dumps([{"a": 1}, {"a": 2}]), encoding="utf-8")
    (root / "snapshots").mkdir()
    (root / "snapshots" / "latest.json").write_text("{}", encoding="utf-8")
    (root / "test").mkdir()
    (root / "test" / "test_thing_provider.py").write_text(
        "def test_it_imports():\n"
        "    import importlib.util, pathlib\n"
        "    p = pathlib.Path('data_providers/thing_provider.py')\n"
        "    assert p.is_file()\n", encoding="utf-8")
    _run(["git", "add", "-A"], root)
    _run(["git", "commit", "-m", "base"], root)
    _run(["git", "branch", "experimental/self-mod"], root)
    return root


def _append_diff(root: pathlib.Path, rel: str, line: str) -> str:
    """A unified diff built from the file's own bytes, so it really applies."""
    src = (root / rel).read_text(encoding="utf-8").splitlines()
    ctx = src[-3:]
    start = len(src) - len(ctx) + 1
    nl = chr(10)
    body = "".join(" " + c + nl for c in ctx)
    return (f"--- a/{rel}{nl}+++ b/{rel}{nl}"
            f"@@ -{start},{len(ctx)} +{start},{len(ctx) + 1} @@{nl}{body}+{line}{nl}")


SPEC = {"problem": "the provider defaults",
        "root_cause": "no entry for the key",
        "desired_change": "the provider resolves the series",
        "success_metric": "the number of rows in memory/goal_score_history.json",
        "domain": "external",
        "categories": ["ECONOMY_WORK_REVIEW"],
        "allowed_paths": ["data_providers/thing_provider.py"]}

PASSING = {"decision": "PASS", "reason": "all four merits hold",
           "merits": [{"name": "applies", "ok": True, "why": "git applied it"}]}


# ---------------------------------------------------------------------------
# (1) THE PATH TO PASS — the fork really does advance
# ---------------------------------------------------------------------------

def test_a_pass_on_merits_becomes_a_real_commit_on_a_per_run_branch(tiny):
    """THE POINT OF THE WHOLE COMMIT. Not "would have passed" — a commit object
    with a sha, on a branch a human can check out and read."""
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# advanced")
    out = FA.advance(diff, SPEC, "20260908T120000Z-1", PASSING,
                     repo=tiny, changed_files=["data_providers/thing_provider.py"])

    assert out["branch"] == "experimental/self-mod-run-20260908T120000Z-1"
    assert out["base"] == "experimental/self-mod"
    assert out["files"] == ["data_providers/thing_provider.py"]

    # the ref exists, the commit is real, and it is a CHILD of the fork branch
    assert _sha(out["branch"], tiny) == out["commit"]
    assert _sha(out["branch"] + "^", tiny) == _sha("experimental/self-mod", tiny)

    # and the content actually changed on that branch
    shown = _run(["git", "show", f"{out['branch']}:data_providers/thing_provider.py"],
                 tiny)
    assert "# advanced" in shown


def test_only_the_graded_files_are_committed(tiny):
    """`git add -A` would sweep up whatever else the apply left in the worktree,
    and a file nobody verified would ride into the commit under a PASS that was
    not about it. Only the graded paths are staged."""
    nl = chr(10)
    stray = "data_providers/stray.py"
    (tiny / "data_providers" / "stray.py").write_text("x = 1\n", encoding="utf-8")
    _run(["git", "add", "-A"], tiny)
    _run(["git", "commit", "-m", "stray"], tiny)
    _run(["git", "branch", "-f", "experimental/self-mod", "HEAD"], tiny)

    two = (_append_diff(tiny, "data_providers/thing_provider.py", "# graded")
           + f"--- a/{stray}{nl}+++ b/{stray}{nl}"
           + f"@@ -1,1 +1,2 @@{nl} x = 1{nl}+# NOT graded{nl}")

    out = FA.advance(two, SPEC, "subset", PASSING, repo=tiny,
                     changed_files=["data_providers/thing_provider.py"])
    committed = _run(["git", "show", "--name-only", "--format=", out["branch"]],
                     tiny).split()
    assert committed == ["data_providers/thing_provider.py"], committed
    assert "NOT graded" not in _run(["git", "show", f"{out['branch']}:{stray}"], tiny)


def test_the_commit_message_carries_the_spec_and_the_merits(tiny):
    """A commit nobody can trace back to the evidence that justified it is a
    claim, not a record."""
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# traced")
    out = FA.advance(diff, SPEC, "traced", PASSING, repo=tiny,
                     changed_files=["data_providers/thing_provider.py"])
    msg = _run(["git", "log", "-1", "--format=%B", out["branch"]], tiny)

    assert "ECONOMY_WORK_REVIEW" in msg
    assert SPEC["success_metric"] in msg
    assert "applies" in msg and "PASS" in msg
    assert "NOT on main" in msg


# ---------------------------------------------------------------------------
# (2) SAFETY PIN — it never commits to main
# ---------------------------------------------------------------------------

def test_master_does_not_move_when_the_fork_advances(tiny):
    before = _sha("master", tiny)
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# advanced")
    FA.advance(diff, SPEC, "pin", PASSING, repo=tiny,
               changed_files=["data_providers/thing_provider.py"])
    assert _sha("master", tiny) == before, "master moved"
    # and the fork branch itself is untouched: a run that appends to
    # experimental/self-mod directly is a run that cannot be thrown away.
    assert _sha("experimental/self-mod", tiny) == before


def test_branching_off_main_is_refused_by_name(tiny):
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# nope")
    with pytest.raises(FA.AdvanceRefused) as exc:
        FA.advance(diff, SPEC, "x", PASSING, repo=tiny, base="master",
                   changed_files=["data_providers/thing_provider.py"])
    assert FA.CODE_BAD_BASE in str(exc.value)


def test_a_branch_outside_the_run_prefix_cannot_be_committed_to():
    """run_branch() is the only namer, and _assert_safe re-checks its output —
    two guards for one rule, because the namer is the kind of function someone
    later "simplifies"."""
    assert FA.run_branch("abc").startswith(FA.BRANCH_PREFIX)
    with pytest.raises(FA.AdvanceRefused) as exc:
        FA._assert_safe("master", "experimental/self-mod", [])
    assert FA.CODE_BAD_BRANCH in str(exc.value)
    for hostile in ("../../main", "main", "", "  "):
        assert FA.run_branch(hostile).startswith(FA.BRANCH_PREFIX)


def test_nothing_advances_without_a_pass(tiny):
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# no")
    for grade in ({"decision": "FAIL", "reason": "tests failed"},
                  {"decision": None}, {}, None):
        with pytest.raises(FA.AdvanceRefused) as exc:
            FA.advance(diff, SPEC, "x", grade, repo=tiny,
                       changed_files=["data_providers/thing_provider.py"])
        assert FA.CODE_NOT_PASSED in str(exc.value)
    assert not [b for b in _run(["git", "branch"], tiny).splitlines()
                if FA.BRANCH_PREFIX in b], "a branch was created for a FAIL"


# ---------------------------------------------------------------------------
# (3) SAFETY PIN — production memory/ and snapshots/ are never written
# ---------------------------------------------------------------------------

def test_production_trees_are_out_of_reach_of_both_guards(tiny):
    """The grader refuses them and so does the committer. One net is a single
    point of failure; the whole design of this pipeline is two."""
    for rel in ("memory/goal_score_history.json", "snapshots/latest.json",
                "cortex_memory/state.json", "core/earning.py",
                "config/passage_rules.json", "test/test_thing_provider.py"):
        scope = M.merit_in_scope([rel], {"allowed_paths": [rel]})
        assert not scope["ok"], f"the grader allowed {rel}"
        assert "PINNED" in scope["why"]

        with pytest.raises(FA.AdvanceRefused) as exc:
            FA.advance("x", SPEC, "x", PASSING, repo=tiny, changed_files=[rel])
        assert FA.CODE_PINNED in str(exc.value), rel


def test_an_advance_leaves_production_files_byte_identical(tiny):
    before = {p: (tiny / p).read_bytes()
              for p in ("memory/goal_score_history.json", "snapshots/latest.json")}
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# advanced")
    FA.advance(diff, SPEC, "x", PASSING, repo=tiny,
               changed_files=["data_providers/thing_provider.py"])
    for p, blob in before.items():
        assert (tiny / p).read_bytes() == blob, f"{p} was written"


def test_the_working_tree_is_not_touched_by_an_advance(tiny):
    """The patch is applied inside a throwaway worktree. The human's checkout,
    their branch and their uncommitted changes are not read and not modified."""
    # Built against the COMMITTED file, then the tree is dirtied — the order
    # matters, and the reverse order is a real refusal rather than a bug: a
    # patch written against a dirty tree does not describe the branch it would
    # land on, and REFUSED_TARGET_DIRTY in the pipeline stops that earlier.
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# advanced")
    (tiny / "data_providers" / "thing_provider.py").write_text(
        "def fetch():\n    return 1\n# a human's uncommitted edit\n", encoding="utf-8")
    dirty_before = _run(["git", "status", "--porcelain"], tiny)
    head_before = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], tiny).strip()

    FA.advance(diff, SPEC, "x", PASSING, repo=tiny,
               changed_files=["data_providers/thing_provider.py"])

    assert _run(["git", "status", "--porcelain"], tiny) == dirty_before
    assert _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], tiny).strip() == head_before
    assert "a human's uncommitted edit" in (
        tiny / "data_providers" / "thing_provider.py").read_text(encoding="utf-8")


def test_no_worktree_is_left_behind(tiny):
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# advanced")
    FA.advance(diff, SPEC, "x", PASSING, repo=tiny,
               changed_files=["data_providers/thing_provider.py"])
    listed = _run(["git", "worktree", "list"], tiny).splitlines()
    assert len(listed) == 1, f"a sandbox worktree survived: {listed}"


# ---------------------------------------------------------------------------
# (4) SAFETY PIN — only a human PR can move a fork commit to main
# ---------------------------------------------------------------------------

def _git_subcommands(path: pathlib.Path) -> set:
    """Every git subcommand this module can run, read off the AST.

    Structural, not textual: the calls are _git([...]) and advance() builds no
    argv any other way, so the first element of each list literal IS the
    subcommand. A grep for "push" would also fire on the word in a comment,
    which is how a structural test quietly becomes a spell-checker.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # The pin is about the ADVANCING path. _selftest runs `git branch --list` to
    # report how many run branches exist, which is a read and not a way to move
    # a commit; leaving it in would make the check fire on the wrong thing.
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.FunctionDef) and n.name == "_selftest")]
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in ("_git", "run", "check_call", "check_output"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.List) and arg.elts:
                first = arg.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value if first.value != "git"
                              else (arg.elts[1].value
                                    if len(arg.elts) > 1
                                    and isinstance(arg.elts[1], ast.Constant)
                                    else "?"))
                for el in arg.elts[1:]:
                    if isinstance(el, ast.Starred):
                        found.add("*")
    return found


def test_the_advancing_code_cannot_push_merge_or_rebase():
    """THE PATH TO MAIN IS A HUMAN PR, and this is what makes that true rather
    than merely stated: the module contains no git subcommand that could move a
    commit anywhere else."""
    subs = _git_subcommands(REPO / "core" / "self_improve" / "forkadvance.py")
    assert subs, "the AST walk found no git calls at all — the check is inert"
    for forbidden in ("push", "merge", "rebase", "cherry-pick", "reset",
                      "checkout", "switch", "branch", "tag", "remote"):
        assert forbidden not in subs, (
            f"forkadvance.py runs `git {forbidden}` — the only path from a fork "
            f"commit to main must be a human pull request")
    assert "worktree" in subs and "commit" in subs, subs


def test_no_module_in_the_pipeline_pushes_anything():
    """Same pin, across every module the pipeline runs. A push added to the
    grader would be just as fatal as one added to the committer."""
    for rel in ("core/self_improve/forkadvance.py", "core/self_improve/merits.py",
                "core/self_improve/applies.py", "core/self_improve/requirer.py",
                "core/self_improve/implementer.py", "tools/self_improve_pipeline.py"):
        subs = _git_subcommands(REPO / rel)
        assert "push" not in subs, f"{rel} can run `git push`"
        assert "merge" not in subs, f"{rel} can run `git merge`"


# ---------------------------------------------------------------------------
# (5) THE SPLIT — the ceiling cannot decide a merit
# ---------------------------------------------------------------------------

def test_the_grader_consults_no_production_ceiling():
    """Checked on the CODE with docstrings and the selftest stripped, by the
    same function the module's own selftest uses — one rule, one implementation,
    so the two cannot drift apart."""
    code = M._code_only(REPO / "core" / "self_improve" / "merits.py")
    for token in ("global_cap", "load_classes", "max_cap_ceiling", "core.earning"):
        assert token not in code, f"merits.py consults {token}"


def test_a_locked_policy_cannot_change_a_grade(monkeypatch, tiny):
    """Behavioural, not textual: if core.earning were consulted at all, this
    would explode instead of grading."""
    import core.earning as E

    def _boom(*a, **k):
        raise AssertionError("merits.grade() read the production policy")

    monkeypatch.setattr(E, "load_classes", _boom)
    monkeypatch.setattr(E, "verify", _boom)

    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# graded")
    g = M.grade(SPEC, diff, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=False)
    assert g["decision"] in ("PASS", "FAIL")
    applies = [m for m in g["merits"] if m["name"] == "applies"][0]
    assert applies["ok"], applies["why"]


# ---------------------------------------------------------------------------
# (6) THE MERITS THEMSELVES — each one can fail, and says so by name
# ---------------------------------------------------------------------------

def test_a_patch_that_does_not_apply_fails_and_marks_the_rest_unreached(tiny):
    """A blocked run must not read like a partially good one."""
    ghost = ("--- a/data_providers/thing_provider.py\n"
             "+++ b/data_providers/thing_provider.py\n"
             "@@ -1,1 +1,1 @@\n-def nothing_like_this():\n+def x():\n")
    g = M.grade(SPEC, ghost, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=False)
    assert g["decision"] == M.FAIL
    by = {m["name"]: m for m in g["merits"]}
    assert not by["applies"]["ok"]
    # UNREACHED IS NOT PASSED. Marking them ok would make a blocked run read as
    # three-quarters good, and the word "unreached" in the text would still be
    # there to make it look honest.
    assert not by["tests_pass"]["ok"], by["tests_pass"]
    assert not by["before_after"]["ok"], by["before_after"]
    assert "unreached" in by["tests_pass"]["why"]
    assert "unreached" in by["before_after"]["why"]


def test_tests_that_were_not_run_cannot_count_as_passed(tiny):
    """run_tests=False exists for the cheap structural checks, and it must cost
    the grade. "We did not look" and "we looked and it was fine" are the same
    collapse this pipeline exists to stop, one merit down."""
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# unrun")
    g = M.grade(SPEC, diff, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=False)
    tp = [m for m in g["merits"] if m["name"] == "tests_pass"][0]
    assert not tp["ok"], tp
    assert "not run" in tp["why"]
    assert g["decision"] == M.FAIL, "a grade passed without its tests being run"


def test_failing_tests_fail_the_grade_inside_the_sandbox(tiny):
    """The tests are run on the PATCHED tree, so a patch that breaks them is
    caught even though the tests pass right here."""
    diff = _append_diff(tiny, "test/test_thing_provider.py", "assert False, 'broken'")
    spec = dict(SPEC, allowed_paths=["test/"])
    g = M.grade(spec, diff, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=True)
    by = {m["name"]: m for m in g["merits"]}
    assert by["applies"]["ok"], by["applies"]["why"]
    assert not by["tests_pass"]["ok"], by["tests_pass"]["why"]
    assert g["decision"] == M.FAIL


def test_the_metric_is_recomputed_on_both_sides_by_the_grader(tiny):
    """The model's own claim about the number is never consulted — nothing in
    the record comes from the spec except which file to read."""
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# measured")
    g = M.grade(SPEC, diff, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=False)
    ba = [m for m in g["merits"] if m["name"] == "before_after"][0]
    assert ba["ok"], ba["why"]
    assert ba["before"]["memory/goal_score_history.json"]["rows"] == 2
    assert ba["after"]["memory/goal_score_history.json"]["rows"] == 2


def test_a_metric_naming_no_readable_file_fails_before_after(tiny):
    """"Could not check" and "checked and fine" must never collapse into one
    answer — that collapse is the failure this whole pipeline exists to stop."""
    spec = dict(SPEC, success_metric="a number that goes up")
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# ungrounded")
    g = M.grade(spec, diff, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=False)
    ba = [m for m in g["merits"] if m["name"] == "before_after"][0]
    assert not ba["ok"]
    assert "no before" in ba["why"]
    assert g["decision"] == M.FAIL


def test_the_selected_tests_are_named_in_the_record(tiny):
    """"The tests passed" means nothing until the record says which tests."""
    diff = _append_diff(tiny, "data_providers/thing_provider.py", "# named")
    g = M.grade(SPEC, diff, ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tiny, run_tests=True)
    tp = [m for m in g["merits"] if m["name"] == "tests_pass"][0]
    assert tp["tests"] == ["test/test_thing_provider.py"], tp
    assert "targeted" in tp["selection"]


def test_a_sandbox_that_cannot_be_built_is_a_FAIL_not_a_PASS(tmp_path):
    g = M.grade(SPEC, "x", ["data_providers/thing_provider.py"],
                base="experimental/self-mod", repo=tmp_path, run_tests=False)
    assert g["decision"] == M.FAIL
    assert any("worktree" in m["why"] for m in g["merits"] if not m["ok"])
