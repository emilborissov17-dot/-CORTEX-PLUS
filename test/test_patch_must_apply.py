#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_patch_must_apply.py — GIT DECIDES WHETHER THE PATCH DESCRIBES REALITY.

THE PRINCIPLE
--------------
No model output reaches the next stage unverified. Every field the model emits
has a mechanical net behind it, and this is the net for the diff BODY — the only
one that can catch confabulated CONTENT rather than a confabulated path.

THE DEFECT IT CLOSES, MEASURED
-------------------------------
On 2026-09-08, after the path grounding landed, a live run produced a diff that
passed every earlier check: real path, inside the allowlist, ranged hunk header.
It proposed removing

    def self_observe(prompt):        <- not in agents/core/self_observer.py
    class SelfObserver:              <- not in it either
    llm_call(...)                    <- nor this

Real file, invented contents. `git apply --check` refuses it in one call, and
git is the same tool that would have to succeed before the patch could ever be
applied — so passing it is necessary, not merely encouraging.

Every test here builds its own throwaway git repo in tmp_path. Nothing runs
against this repository's working tree except the two that deliberately assert
--check leaves it untouched.

    venv\\Scripts\\python.exe -m pytest test/test_patch_must_apply.py -v
"""
from __future__ import annotations

import subprocess
import pathlib

import pytest

from core.self_improve import applies as A

REPO = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def sandbox(tmp_path):
    """A real git repo with one known file, so a diff can be judged for real."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    f = tmp_path / "thing.py"
    f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    return tmp_path


APPLIES = ("--- a/thing.py\n"
           "+++ b/thing.py\n"
           "@@ -1,3 +1,4 @@\n alpha\n beta\n+delta\n gamma\n")

CONFABULATED = ("--- a/thing.py\n"
                "+++ b/thing.py\n"
                "@@ -1,3 +1,3 @@\n"
                "-def self_observe(prompt):\n"
                "-    return llm_call(prompt)\n"
                "-class SelfObserver:\n"
                "+def self_observe(p):\n"
                "+    return llm_call(p)\n"
                "+class SelfObserver:\n")


# ---------------------------------------------------------------------------
# (a) THE TWO CASES THE BRIEF ASKS FOR
# ---------------------------------------------------------------------------

def test_a_diff_that_really_applies_passes(sandbox):
    """THE POSITIVE CONTROL. Without it a net that refuses everything would look
    like a working net, and the pipeline would be a wall."""
    ok, err = A.check_applies(APPLIES, repo=sandbox)
    assert ok, f"a valid diff was refused: {err}"
    assert err == ""


def test_a_confabulated_diff_is_refused(sandbox):
    """Real path, invented contents — the exact 2026-09-08 shape."""
    ok, err = A.check_applies(CONFABULATED, repo=sandbox)
    assert not ok, "a patch describing lines that are not in the file was accepted"
    assert "does not apply" in err or "error" in err.lower(), err


def test_the_refusal_is_named_and_carries_gits_own_words(sandbox):
    _, err = A.check_applies(CONFABULATED, repo=sandbox)
    text = A.refusal(err)
    assert A.CODE == "REFUSED_PATCH_DOES_NOT_APPLY"
    assert text.startswith(A.CODE)
    assert err.splitlines()[0] in text, (
        "git's own error was summarised away; the retry loop feeds this text "
        "back to the model, and 'patch does not apply' teaches it nothing")
    assert "CONTENT failure" in text


# ---------------------------------------------------------------------------
# (b) IT NEVER WRITES, AND IT NEVER LIES ABOUT NOT RUNNING
# ---------------------------------------------------------------------------

def test_check_writes_nothing_to_the_tree_it_checks(sandbox):
    def status():
        return subprocess.run(["git", "status", "--porcelain"], cwd=sandbox,
                              capture_output=True, text=True).stdout

    before = status()
    A.check_applies(APPLIES, repo=sandbox)
    A.check_applies(CONFABULATED, repo=sandbox)
    assert status() == before, "--check modified the tree"
    assert (sandbox / "thing.py").read_text(encoding="utf-8") == "alpha\nbeta\ngamma\n"


def test_check_writes_nothing_to_the_real_repo():
    """The retry loop runs this against the live tree up to four times per patch."""
    def status():
        return subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                              capture_output=True, text=True).stdout

    before = status()
    A.check_applies(CONFABULATED)
    assert status() == before, "--check modified the live working tree"


def test_git_being_unavailable_is_not_reported_as_a_pass(monkeypatch, sandbox):
    """SILENCE IS NOT SUCCESS. 'git was unavailable' and 'the patch is good'
    must never collapse into the same answer — that is the failure this module
    exists to stop, one level up."""
    def _boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", _boom)
    ok, err = A.check_applies(APPLIES, repo=sandbox)
    assert not ok
    assert "not on PATH" in err


def test_a_timeout_is_not_a_pass(monkeypatch, sandbox):
    def _slow(*a, **k):
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(subprocess, "run", _slow)
    ok, err = A.check_applies(APPLIES, repo=sandbox)
    assert not ok and "timed out" in err


@pytest.mark.parametrize("junk", ["", "   ", "not a diff at all"])
def test_junk_is_refused(junk, sandbox):
    ok, _ = A.check_applies(junk, repo=sandbox)
    assert not ok


# ---------------------------------------------------------------------------
# (c) IT RUNS BEFORE THE JUDGE
# ---------------------------------------------------------------------------

def test_the_pipeline_checks_the_patch_before_it_reaches_earning():
    """STRUCTURAL. A judge handed an inapplicable patch would grade a fiction."""
    import ast

    tree = ast.parse((REPO / "tools" / "self_improve_pipeline.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_once")

    check_line = verify_line = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "check_applies":
                check_line = node.lineno
            elif node.func.attr == "verify":
                verify_line = node.lineno

    assert check_line, "run_once never calls check_applies"
    assert verify_line, "run_once never calls earning.verify"
    assert check_line < verify_line, (
        "the patch reaches the judge before git has said whether it applies")


def test_the_pipeline_refuses_with_the_named_code(monkeypatch, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sip_probe", REPO / "tools" / "self_improve_pipeline.py")
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)
    P.OUT_DIR = tmp_path / "runs"

    brain, coder = P._fixture_models()
    monkeypatch.setattr(A, "check_applies", lambda d, **k: (False, "patch does not apply"))

    with pytest.raises(P.PipelineRefused) as exc:
        P.run_once({"problem": "p"}, brain=brain, coder=coder)
    assert A.CODE in str(exc.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
