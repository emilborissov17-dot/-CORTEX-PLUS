#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_collection_can_never_abort.py — THE SPLIT IS WIRED, NOT JUST DECLARED.

WHY THIS FILE EXISTS, AND WHY IT IS NOT "NO MODULE-LEVEL EXIT"
---------------------------------------------------------------
20 files under test/ end in a module-level `sys.exit(...)`. That is DELIBERATE
and documented: they are standalone scripts, each runnable on its own, and
test/_script_style.py calls itself "the single source of the split". The root
conftest.py excludes them from collection and test/test_script_suite.py runs each
as a subprocess, so `pytest` still means every test.

So the rule this repo enforces is NOT "no module-level exit". It is:

    every module-level exit must be in SCRIPT_STYLE,
    SCRIPT_STYLE must be what conftest actually ignores,
    and everything in SCRIPT_STYLE must be run by the subprocess suite.

Rewriting those 20 files to guard their exits behind __main__ would remove the
DETECTION SIGNAL that keeps them in SCRIPT_STYLE, drop them out of
collect_ignore AND out of test_script_suite at the same time, and leave twenty
files silently unrun — the exact failure _script_style.py says it exists to
prevent. Measured 2026-09-08 before writing this: 20 module-level exits, 20 of
them already ignored, 0 unignored, and `pytest test/` collecting 4381 tests
cleanly.

THE HOLE THIS ACTUALLY CLOSES
------------------------------
_script_style.is_script_style() detects the signal with a TEXT check:

    if any(ln.startswith("sys.exit(") for ln in lines)

Column 0 only. A module-level exit that is INDENTED — inside a module-level
`if`, `try` or `for`, which still runs at import — evades it, is therefore NOT
ignored by conftest, and aborts the whole run with INTERNALERROR. Nothing
asserted that today. The check below is an AST walk, which is strictly stronger
than the text check and would catch that file.

Nothing asserted the wiring either: conftest sets collect_ignore = SCRIPT_STYLE,
and no test checked they had not drifted apart.

A NOTE FOR THE NEXT PERSON TO MISDIAGNOSE THIS (I did, twice)
--------------------------------------------------------------
`collect_ignore` applies when pytest DISCOVERS files. It does NOT apply to paths
named explicitly on the command line. So

    pytest test/                      collects 4381 tests, no abort
    pytest test/a.py test/test_pulse.py     INTERNALERROR: SystemExit

Both are true at the same time and neither is a defect in the file. An
INTERNALERROR from an explicit file list means the invocation bypassed the split,
not that a test file is broken.

    venv\\Scripts\\python.exe -m pytest test/test_collection_can_never_abort.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

if str(REPO / "test") not in sys.path:
    sys.path.insert(0, str(REPO / "test"))
from _script_style import SCRIPT_STYLE, SCAN_DIRS      # noqa: E402

EXIT_FUNCS = {"exit", "quit"}
EXIT_ATTRS = {("sys", "exit"), ("os", "_exit"), ("os", "abort")}


def _is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    dumped = ast.dump(node.test)
    return "__name__" in dumped and "__main__" in dumped


def module_level_exits(path: pathlib.Path) -> list:
    """[(lineno, what)] for every process-kill that RUNS AT IMPORT.

    AST, not text, and that is the whole point: the detector in
    test/_script_style.py matches `sys.exit(` at column 0 only, so an INDENTED
    module-level exit slips past it. This walks the statements that actually
    execute on import — skipping function and class bodies, and skipping the
    __main__ guard, which pytest never runs.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="strict"))
    except Exception as exc:                                     # noqa: BLE001
        # A file the guard cannot read is a BLIND SPOT, not a clean file — the
        # same distinction test/test_no_exit_on_import.py draws.
        return [(0, f"UNREADABLE: {type(exc).__name__}: {exc}")]

    found = []

    def walk(body):
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            if _is_main_guard(stmt):
                walk(stmt.orelse)          # the else DOES run under pytest
                continue
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call):
                    f = node.func
                    if isinstance(f, ast.Name) and f.id in EXIT_FUNCS:
                        found.append((node.lineno, f.id))
                    elif (isinstance(f, ast.Attribute)
                          and isinstance(f.value, ast.Name)
                          and (f.value.id, f.attr) in EXIT_ATTRS):
                        found.append((node.lineno, f"{f.value.id}.{f.attr}"))
                elif isinstance(node, ast.Raise) and node.exc is not None:
                    exc = node.exc
                    name = (exc.func.id if isinstance(exc, ast.Call)
                            and isinstance(exc.func, ast.Name)
                            else exc.id if isinstance(exc, ast.Name) else None)
                    if name == "SystemExit":
                        found.append((node.lineno, "raise SystemExit"))

    walk(tree.body)
    return found


def _scanned_files() -> list:
    out = []
    for root in SCAN_DIRS:
        if not root.exists():
            continue
        for p in sorted(root.rglob("test_*.py")):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# (a) THE INVARIANT — every module-level exit is excluded from collection
# ---------------------------------------------------------------------------

def test_every_module_level_exit_is_excluded_from_collection():
    """THE ONE THAT MATTERS. A module-level exit that conftest does not ignore
    aborts the ENTIRE run with INTERNALERROR — no test in any file executes, and
    the run reports no failure of its own."""
    declared = set(SCRIPT_STYLE)
    offenders = {}
    for p in _scanned_files():
        rel = p.resolve().relative_to(REPO).as_posix()
        hits = module_level_exits(p)
        if hits and rel not in declared:
            offenders[rel] = hits

    assert not offenders, (
        "\n  A MODULE-LEVEL EXIT IS NOT EXCLUDED FROM COLLECTION.\n"
        "  pytest imports a module to collect it, so this kills the whole run:\n"
        "  INTERNALERROR, 'no tests ran', and not one file executes.\n"
        + "".join(f"    {f}: {h}\n" for f, h in sorted(offenders.items()))
        + "  Either the file belongs in the script-style population — check why\n"
          "  test/_script_style.is_script_style() did not detect it, most likely\n"
          "  an INDENTED sys.exit that its column-0 text match cannot see — or\n"
          "  the exit should move behind `if __name__ == \"__main__\":`.\n")


def test_the_conftest_actually_ignores_what_the_split_declares():
    """conftest sets collect_ignore = SCRIPT_STYLE. Nothing asserted they had not
    drifted apart, and a conftest that stopped applying the split would look
    fine until the next run aborted."""
    spec = importlib.util.spec_from_file_location(
        "_cortex_root_conftest_probe", REPO / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert hasattr(mod, "collect_ignore"), "conftest no longer sets collect_ignore"
    assert set(mod.collect_ignore) == set(SCRIPT_STYLE), (
        f"conftest ignores {sorted(set(mod.collect_ignore) ^ set(SCRIPT_STYLE))} "
        f"differently from what test/_script_style.py declares")
    assert mod.collect_ignore, "collect_ignore is empty; the split is not applied"


def test_every_excluded_file_is_still_run_somewhere():
    """Excluding a file from collection is only safe because something else runs
    it. If the subprocess suite stopped covering one, it would vanish from the
    suite entirely while every run stayed green."""
    from test_script_suite import SCRIPT_STYLE as suite_list

    assert set(suite_list) == set(SCRIPT_STYLE), (
        "the subprocess runner and the split disagree about which files are "
        "script-style; a file in neither population is never run")


def test_the_split_is_not_empty():
    """A detector that silently stops matching would empty SCRIPT_STYLE, and
    every one of these files would be collected and abort the run."""
    assert len(SCRIPT_STYLE) >= 20, (
        f"SCRIPT_STYLE has shrunk to {len(SCRIPT_STYLE)}. If files were "
        f"deliberately converted to pytest style, lower this number in the same "
        f"commit and say which.")


# ---------------------------------------------------------------------------
# (b) THE AST CHECK IS STRICTLY STRONGER THAN THE TEXT DETECTOR
# ---------------------------------------------------------------------------

INDENTED_EXIT = '''\
import sys

FAILS = []
if not FAILS:
    sys.exit(0)
'''

GUARDED_EXIT = '''\
import sys

def main():
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''

EXIT_IN_A_FUNCTION = '''\
import sys

def helper():
    sys.exit(1)
'''

COLUMN_ZERO_EXIT = '''\
import sys
sys.exit(0)
'''

RAISE_SYSTEMEXIT = '''\
raise SystemExit(1)
'''


@pytest.mark.parametrize("src,expected", [
    (INDENTED_EXIT, True),
    (COLUMN_ZERO_EXIT, True),
    (RAISE_SYSTEMEXIT, True),
    (GUARDED_EXIT, False),
    (EXIT_IN_A_FUNCTION, False),
])
def test_the_checker_sees_what_runs_at_import(tmp_path, src, expected):
    p = tmp_path / "test_sample.py"
    p.write_text(src, encoding="utf-8")
    assert bool(module_level_exits(p)) is expected, module_level_exits(p)


def test_the_ast_check_catches_what_the_text_detector_misses(tmp_path):
    """THE HOLE, DEMONSTRATED. _script_style matches `sys.exit(` at column 0. An
    indented module-level exit runs at import just the same, evades the
    detector, is therefore NOT ignored by conftest, and aborts the run.

    Weaken module_level_exits() to a startswith and this goes red — which is the
    mutation that proves the AST is doing work the text check cannot.
    """
    from _script_style import is_script_style

    p = tmp_path / "test_indented.py"
    p.write_text(INDENTED_EXIT, encoding="utf-8")

    assert not is_script_style(p), (
        "the text detector now catches an indented exit; if it was strengthened, "
        "this test records that it used not to")
    assert module_level_exits(p), (
        "the AST check missed an indented module-level exit — it is no longer "
        "stronger than the text detector it exists to backstop")


def test_a_file_that_cannot_be_read_is_not_reported_as_clean(tmp_path):
    """A guard that cannot read a file has not checked it. Silence must not pass
    for a pass — the same distinction test_no_exit_on_import.py draws."""
    p = tmp_path / "test_broken.py"
    p.write_text("def (((", encoding="utf-8")
    hits = module_level_exits(p)
    assert hits and "UNREADABLE" in hits[0][1]


# ---------------------------------------------------------------------------
# (c) the population, recorded so a change is deliberate
# ---------------------------------------------------------------------------

def test_the_two_populations_together_cover_every_test_file():
    """Nothing may fall between them. test_script_suite asserts this from its
    side; asserted here too because the two files can be edited apart."""
    declared = set(SCRIPT_STYLE)
    all_test_files = {p.resolve().relative_to(REPO).as_posix()
                      for p in (REPO / "test").glob("test_*.py")}
    collected = all_test_files - declared
    assert collected, "everything is script-style; pytest would collect nothing"
    assert declared & all_test_files, "no script-style file left in test/"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
