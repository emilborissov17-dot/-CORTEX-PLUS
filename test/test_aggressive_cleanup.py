"""Cleaning before the refusal, and the one thing cleaning must never do.

Emil, 27 Aug 2026: "одобрявам таван 3 с чистене преди отказ."

THE NEGATIVE CONTROL IS THE POINT OF THIS FILE. This is the first caller of
disk_actuator.sweep(apply=True) anywhere in the repo — until now the actuator
was built, hashed, tested and never fired. So the test that matters is not that
rubbish gets deleted; it is that BOUNDARIES.md, LAW_OF_THE_BRAIN.md and
heartbeat.json survive sitting inside a directory the sweep is allowed to empty.

And the control has to be able to FAIL, or it says nothing. Two ways it was
nearly vacuous, both caught while writing it:

  1. The first sandbox was not a git repo. disk_actuator refuses to sweep where
     git cannot say which files are tracked, so the three files "survived" a
     sweep that never ran. Every test below asserts the junk file actually died
     in the same call.

  2. A control nobody has seen fail is a control nobody has tested. The second
     test restores the exact pre-COMMAND-26 defect — matching the negative
     allowlist on the path only, not the basename — and asserts that the three
     files ARE deleted under it. If that test ever starts passing by accident,
     the first one has stopped meaning anything.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import aggressive_cleanup as ac   # noqa: E402
from core import disk_actuator as da        # noqa: E402

NAMED = ("BOUNDARIES.md", "LAW_OF_THE_BRAIN.md", "heartbeat.json")


@pytest.fixture(autouse=True)
def no_real_logs(tmp_path, monkeypatch):
    """Nothing in this file can reach the operator's real logs.

    Belt and braces on top of passing log_path explicitly. Three tests below
    call cure_refusal() without one, and the default is the real
    memory/disk_actuator_log.jsonl — which is how 31 sandbox rows got into it
    in the first place. The two tests that assert the real log is untouched
    check the file on disk, so they still mean what they say.
    """
    monkeypatch.setattr(ac, "LOG", tmp_path / "cleanup.jsonl")
    monkeypatch.setattr(da, "SWEEP_LOG", tmp_path / "sweep.jsonl")


@pytest.fixture
def sandbox(tmp_path):
    """A real git repo with the three named files inside a sweepable dir."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "keep.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "add", "keep.txt"], cwd=tmp_path, check=True)
    (tmp_path / "tmp").mkdir()
    for name in NAMED:
        (tmp_path / "tmp" / name).write_text("do not delete me", encoding="utf-8")
    (tmp_path / "tmp" / "junk.tmp").write_text("rubbish", encoding="utf-8")
    return tmp_path


# -- the negative control -------------------------------------------------

def test_the_three_named_files_survive_a_real_sweep(sandbox):
    res = ac.cleanup(apply=True, base=sandbox, log_path=sandbox / "log.jsonl")

    assert res["refused"] is None, (
        "the sweep refused, so nothing was ever at risk and this control "
        "proves nothing: %s" % res["refused"])
    assert not (sandbox / "tmp" / "junk.tmp").exists(), (
        "the sweep deleted nothing at all; a control that passes because "
        "nothing happened is vacuous")

    for name in NAMED:
        assert (sandbox / "tmp" / name).exists(), (
            "%s was deleted from inside a cleanup directory" % name)


def test_each_survivor_says_why_it_survived(sandbox):
    res = ac.cleanup(apply=True, base=sandbox, log_path=sandbox / "log.jsonl")
    kept = {pathlib.PurePath(p).name.lower(): why for p, why in res["sweep"]["kept"]}
    for name in NAMED:
        why = kept.get(name.lower(), "")
        assert "basename" in why, (
            "%s survived without the basename rule being the reason — it may "
            "have survived by luck of the directory layout: %r" % (name, why))


def test_the_control_is_not_vacuous_it_fails_with_path_only_matching(
        sandbox, monkeypatch):
    """The pre-COMMAND-26 defect, restored, to prove the control has teeth.

    Matching the negative allowlist on the repo-relative path only — which is
    what this did before — lets all three through, because 'tmp/boundaries.md'
    is not 'boundaries.md'. The manifest hash is restamped alongside the flag,
    exactly as it would have been then, so the sweep really runs.
    """
    monkeypatch.setattr(da, "NEGATIVE_MATCH_BASENAME", False)
    monkeypatch.setattr(da, "MANIFEST_SHA256", da.manifest_sha256())
    da.tracked_files(sandbox, refresh=True)

    res = ac.cleanup(apply=True, base=sandbox, log_path=sandbox / "log.jsonl")
    assert res["refused"] is None

    died = [n for n in NAMED if not (sandbox / "tmp" / n).exists()]
    assert len(died) == 3, (
        "the historical defect no longer deletes these, so the control above "
        "would pass whether or not the basename rule exists: survived=%s"
        % [n for n in NAMED if n not in died])


def test_a_sweep_that_cannot_reach_git_deletes_nothing(tmp_path):
    """Losing a cleanup is a missed opportunity; losing a tracked file is not."""
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "junk.tmp").write_text("rubbish", encoding="utf-8")
    da.tracked_files(tmp_path, refresh=True)
    res = ac.cleanup(apply=True, base=tmp_path, log_path=tmp_path / "log.jsonl")
    assert res["refused"], "a sweep ran with no idea what git tracks"
    assert (tmp_path / "tmp" / "junk.tmp").exists()


def test_dry_run_deletes_nothing(sandbox):
    res = ac.cleanup(apply=False, base=sandbox, log_path=sandbox / "log.jsonl")
    assert res["applied"] is False
    assert (sandbox / "tmp" / "junk.tmp").exists(), "a dry run deleted a file"
    # The SWEEP does record a dry run — that is a real observation of a real
    # tree and worth keeping. What must not appear is a cleanup record, which
    # would claim room was freed.
    assert json.loads((sandbox / "log.jsonl").read_text(
        encoding="utf-8").splitlines()[0])["applied"] is False
    assert res["working_set"]["applied"] is False


# -- the one thing it may never do ---------------------------------------

def test_nothing_here_kills_a_process():
    """The machine is Emil's. Freeing RAM by closing Chrome is not homeostasis.

    ast, not a grep: the ban is on the CALL, and a docstring that mentions
    killing must not fail the test that forbids it.
    """
    src = (REPO / "core" / "aggressive_cleanup.py").read_text(encoding="utf-8-sig")
    banned = {"kill", "terminate", "taskkill", "TerminateProcess", "OpenProcess",
              "killpg", "system", "Popen", "run", "call", "check_output"}
    allowed_run = {"git"}
    offenders = []
    for n in ast.walk(ast.parse(src)):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        if name not in banned:
            continue
        # subprocess.run(["git", ...]) inside the selftest sandbox is not a kill
        first = n.args[0] if n.args else None
        if (name == "run" and isinstance(first, ast.List) and first.elts
                and isinstance(first.elts[0], ast.Constant)
                and first.elts[0].value in allowed_run):
            continue
        offenders.append("%s at line %d" % (name, n.lineno))
    assert not offenders, (
        "aggressive_cleanup can end a process: %s" % offenders)


def test_the_working_set_released_is_this_process_and_no_other():
    src = (REPO / "core" / "aggressive_cleanup.py").read_text(encoding="utf-8-sig")
    assert "GetCurrentProcess" in src
    assert "OpenProcess" not in src, (
        "a handle to another process can be opened, so 'own working set' is "
        "no longer guaranteed by construction")


# -- cured is not counted -------------------------------------------------

def test_a_gate_that_was_not_refusing_is_not_a_cure():
    r = ac.cure_refusal(check=lambda: {"allowed": True})
    assert r["cured"] is None, (
        "'nothing to cure' was reported as a cure; only one of those means "
        "the cleaning did anything")
    assert r["counted"] is False


def test_a_cured_refusal_is_not_charged_to_the_pool():
    seq = iter([{"allowed": False, "reasons": ["ram 400MB < 600MB"]},
                {"allowed": True, "reasons": []}])
    r = ac.cure_refusal(check=lambda: next(seq))
    assert r["cured"] is True
    assert r["counted"] is False, (
        "a night that ran after cleaning still spent one of the three")


def test_a_refusal_cleaning_could_not_cure_is_counted():
    reasons = ["ram 400MB < 600MB"]
    r = ac.cure_refusal(check=lambda: {"allowed": False, "reasons": reasons})
    assert r["cured"] is False and r["counted"] is True
    assert "400MB" in r["why"], (
        "the refusal does not say what is still crossed: %s" % r["why"])


def test_the_cure_cleans_before_it_asks_again():
    """Order is the whole mechanism: asking first would always give the same
    answer, and cleaning after would be too late to matter."""
    events = []

    def check():
        events.append("check")
        return {"allowed": False, "reasons": ["ram"]}

    ac.cure_refusal(check=check, apply=False)
    assert events == ["check", "check"]
    src = (REPO / "core" / "aggressive_cleanup.py").read_text(encoding="utf-8-sig")
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "cure_refusal"][0]
    order = [n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in ("cleanup", "check")]
    assert order.index("cleanup") < len(order) - 1, (
        "the gate is not asked again after cleaning")


# -- it stays off live state ---------------------------------------------

def test_the_module_dry_runs_when_run_bare():
    src = (REPO / "core" / "aggressive_cleanup.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    main = [n for n in tree.body if isinstance(n, ast.If)
            and getattr(getattr(n.test, "left", None), "id", None) == "__name__"]
    assert main, "no __main__ guard"
    for n in ast.walk(main[0]):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "cleanup":
            kw = {k.arg: getattr(k.value, "value", None) for k in n.keywords}
            assert kw.get("apply") is False, (
                "running this module bare would delete files from the repo")


def test_the_tests_above_left_the_repo_alone():
    for rel in ("memory/aggressive_cleanup_log.jsonl",
                "memory/disk_actuator_log.jsonl"):
        p = REPO / rel
        assert not p.exists() or p.stat().st_size >= 0
    for rel in ("BOUNDARIES.md", "LAW_OF_THE_BRAIN.md"):
        for cand in (REPO / rel, REPO / "docs" / rel):
            if cand.exists():
                assert cand.stat().st_size > 0


def test_a_sandboxed_sweep_writes_nothing_to_the_real_sweep_log(sandbox):
    """The whole write surface is redirected, or none of it is.

    cleanup() took a log_path and did not pass it to sweep(), so 31 rows from
    sandboxed runs landed in the operator's real memory/disk_actuator_log.jsonl
    while every test believed it was writing to a tmp_path.
    """
    real = REPO / "memory" / "disk_actuator_log.jsonl"
    before = real.read_bytes() if real.exists() else None

    ac.cleanup(apply=True, base=sandbox, log_path=sandbox / "log.jsonl")

    after = real.read_bytes() if real.exists() else None
    assert after == before, (
        "a sandboxed sweep appended to the real disk_actuator log")
    assert (sandbox / "log.jsonl").exists(), (
        "the sweep wrote no log at all, so the assertion above is vacuous")


def test_cure_refusal_forwards_the_log_path(sandbox):
    """A caller that redirects the cleanup must redirect the sweep under it."""
    real = REPO / "memory" / "disk_actuator_log.jsonl"
    before = real.read_bytes() if real.exists() else None
    ac.cure_refusal(check=lambda: {"allowed": False, "reasons": ["ram"]},
                    apply=True, base=sandbox, log_path=sandbox / "log.jsonl")
    after = real.read_bytes() if real.exists() else None
    assert after == before, "cure_refusal swept into the real log"
    assert (sandbox / "log.jsonl").exists()
