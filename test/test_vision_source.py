# -*- coding: utf-8 -*-
"""test/test_vision_source.py — ONE canonical path for the vision text, fail loud (C-VISION-4, Emil 4 Oct: "път").

Decided: core/civilization_vision.txt is read only through core.vision_source.load_vision(); a missing,
undecodable or empty file raises VisionMissing — no default text stands in for the vision.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import vision_source as VS  # noqa: E402

LITERAL = "civilization_vision.txt"
ALLOWED = {"core/vision_source.py"}
# KNOWN EXCEPTIONS, documented (C-VISION-4 Step 1):
KNOWN = {
    "merkle_memory.py",           # VISION_FILE = Path("civilization_vision.txt") is defined and never used; left untouched by order
    "safety/protected_paths.py",  # the write-protection entry, a name in a set, not a read
    "cortex_scan.py",             # names data/civilization_vision.json, a different file; does not match the literal
}
SKIP_DIRS = {"memory", "snapshots", "test", ".git", "__pycache__", "node_modules"}


def _head():
    return VS.VISION_PATH.read_text(encoding="utf-8").strip()[:40]


# (1)
def test_the_canonical_file_exists_and_is_read():
    assert VS.VISION_PATH == REPO / "core" / LITERAL and VS.VISION_PATH.exists()
    assert VS.load_vision().startswith(_head())


# (2)
def test_a_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(VS, "VISION_PATH", tmp_path / "absent.txt")
    with pytest.raises(VS.VisionMissing, match="absent.txt"):
        VS.load_vision()


def test_an_empty_file_raises(monkeypatch, tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("  \n", encoding="utf-8")
    monkeypatch.setattr(VS, "VISION_PATH", f)
    with pytest.raises(VS.VisionMissing, match="empty"):
        VS.load_vision()


def test_an_undecodable_file_raises(monkeypatch, tmp_path):
    f = tmp_path / "bad.txt"
    f.write_bytes(b"\xff\xfe\xfa not utf-8")
    monkeypatch.setattr(VS, "VISION_PATH", f)
    with pytest.raises(VS.VisionMissing, match="bad.txt"):
        VS.load_vision()


# (3)
def _builds_path_from_literal(tree) -> bool:
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            if any(isinstance(x, ast.Constant) and x.value == LITERAL for x in (n.left, n.right)):
                return True
        if isinstance(n, ast.Call) and any(isinstance(a, ast.Constant) and a.value == LITERAL for a in n.args):
            return True
    return False


def _repo_py_files():
    for root, dirs, files in os.walk(REPO):
        rel_root = Path(root).relative_to(REPO)
        dirs[:] = [d for d in dirs
                   if not d.startswith("venv") and d not in SKIP_DIRS
                   and (rel_root / d).as_posix() != "core/history"]
        for name in files:
            if name.endswith(".py"):
                yield (Path(root) / name).relative_to(REPO).as_posix()


def test_no_other_module_builds_a_path_to_the_vision():
    bad, examined = [], 0
    for f in _repo_py_files():
        examined += 1
        if f in ALLOWED | KNOWN:
            continue
        src = (REPO / f).read_text(encoding="utf-8", errors="replace")
        if LITERAL in src:
            try:
                if _builds_path_from_literal(ast.parse(src)):
                    bad.append(f)
            except SyntaxError:
                pass
    assert examined > 100, f"the scan examined only {examined} files — it could not have found anything"
    assert bad == [], f"a path to {LITERAL} built outside core/vision_source.py: {bad}"


def test_the_known_exceptions_are_still_there():
    """If a KNOWN exception disappears, the list must shrink with it."""
    for f in KNOWN:
        assert (REPO / f).exists(), f"{f} is listed as a known exception but no longer exists"


# (4)
def test_canon_goals_orchestrator_and_prophecy_read_the_file():
    from core import canon, goals, cortex_orchestrator
    sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
    import goal_prophecy
    assert _head() in canon.load_canon()["vision"]
    assert _head() in goals.load_civilization_vision()
    assert _head() in cortex_orchestrator.VISION
    assert _head() in goal_prophecy._moral_core()


def test_the_readers_raise_instead_of_a_stand_in(monkeypatch, tmp_path):
    from core import canon, goals
    sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
    import goal_prophecy
    monkeypatch.setattr(VS, "VISION_PATH", tmp_path / "absent.txt")
    for reader in (lambda: canon.load_canon(), goals.load_civilization_vision, goal_prophecy._moral_core):
        with pytest.raises(VS.VisionMissing):
            reader()


# (5)
def test_the_readme_carries_the_vision_and_a_missing_vision_publishes_nothing(monkeypatch, tmp_path):
    import github_publisher as gp
    pushed = []
    monkeypatch.setattr(gp, "_push_file", lambda path, content, msg: pushed.append((path, content)))
    gp.publish_vision()
    (path, readme), = pushed
    assert path == "README.md"
    assert readme.split("## Vision\n\n", 1)[1].split("\n\n## Global Goal", 1)[0] == VS.load_vision()
    pushed.clear()
    monkeypatch.setattr(VS, "VISION_PATH", tmp_path / "absent.txt")
    gp.publish_vision()
    assert pushed == [], "a missing vision must abort the README, not publish an empty Vision section"


# (6) write protection is on the real file (Emil "ДА" 4 Oct)
def test_the_canonical_vision_file_is_write_protected():
    from safety.protected_paths import is_protected
    assert is_protected("core/civilization_vision.txt")
    assert is_protected(VS.VISION_PATH.relative_to(REPO).as_posix())
    assert is_protected(str(VS.VISION_PATH.relative_to(REPO)))


# ── mutation of the static check itself ─────────────────────────────────────
def test_mutation_the_static_check_sees_a_path_built_from_the_literal():
    assert _builds_path_from_literal(ast.parse('VISION = BASE / "civilization_vision.txt"\n'))
    assert _builds_path_from_literal(ast.parse('VISION = Path("civilization_vision.txt")\n'))
    assert not _builds_path_from_literal(ast.parse('NAMES = ["civilization_vision.txt"]\n'))
