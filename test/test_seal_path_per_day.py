# -*- coding: utf-8 -*-
"""
PRE-FLIGHT D1 — one sealed file per day, derived from the date, never hardcoded.

PREDICTION ONLY (§VI); nothing here trades.

The old target was the literal string "BET_2026-09-07_markets_grounded.json", and that
file has existed since 3e60956. From 8 September onward a bare --live would either die
on FileExistsError or, with --allow-overwrite, DESTROY THE SEALED R48 BET — the only
live grounded bet on record, and the file tomorrow's grading reads.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import LEDGER, seal_path  # noqa: E402


def test_the_target_carries_todays_date():
    p = seal_path()
    assert date.today().isoformat() in p.name
    assert p.name.startswith("BET_") and p.name.endswith("_markets_grounded.json")


def test_no_hardcoded_september_seventh_remains_in_the_seal_path():
    """The literal that caused the blocker, gone from the CODE that builds the path.

    CODE, NOT PROSE. Both docstrings quote the old filename while explaining why it was
    a blocker, and a text grep fails on the explanation — the fourth time this repo has
    had a test bent by its own comments. String constants are blanked and the AST is
    checked, except for the f-string that actually builds the name.
    """
    import ast
    import inspect

    import tools.market_bet as mb

    class _Blank(ast.NodeTransformer):
        def visit_Expr(self, node):        # drop docstrings entirely
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return None
            return node

    for fn in (mb.seal_path, mb._grounded_run):
        tree = _Blank().visit(ast.parse(inspect.getsource(fn).lstrip()))
        assert "2026-09-07" not in ast.unparse(tree), fn.__name__


def test_each_day_gets_its_own_file():
    a = seal_path(date(2026, 9, 7))
    b = seal_path(date(2026, 9, 8))
    assert a != b
    assert "2026-09-07" in a.name and "2026-09-08" in b.name


def test_it_can_no_longer_reach_yesterdays_sealed_bet():
    """THE REAL DANGER. --allow-overwrite is scoped to today by construction: a run on
    the 8th cannot name the 7th's file at all."""
    today = seal_path(date(2026, 9, 8))
    r48 = LEDGER / "BET_2026-09-07_markets_grounded.json"
    assert today != r48
    assert today.name != r48.name


def test_the_r48_bet_is_still_on_disk_and_untouched():
    """The file this fix exists to protect."""
    r48 = LEDGER / "BET_2026-09-07_markets_grounded.json"
    assert r48.exists(), "the sealed R48 bet is missing"
    assert r48.stat().st_size > 10_000


def test_a_second_same_day_run_without_allow_overwrite_refuses(tmp_path):
    """One file per day is only a guarantee if the second run of that day refuses."""
    import json
    import os
    import subprocess

    fixture = tmp_path / "in.json"
    fixture.write_text(json.dumps({"snippets": {}, "completions": {}}), encoding="utf-8")
    out = tmp_path / seal_path().name

    def run(*extra):
        return subprocess.run(
            [sys.executable, str(REPO / "tools" / "market_bet.py"), "--grounded",
             "--dry-run", str(fixture), "--out", str(out), *extra],
            capture_output=True, text=True, cwd=str(REPO),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"})

    first = run()
    assert out.exists(), first.stdout + first.stderr
    sealed = out.read_text(encoding="utf-8")

    second = run()
    assert second.returncode != 0
    assert "already holds a sealed bet" in second.stdout + second.stderr
    assert out.read_text(encoding="utf-8") == sealed, "the sealed bet was modified"

    third = run("--allow-overwrite")
    assert third.returncode == 0, third.stdout + third.stderr


def test_the_default_lives_under_the_ledger_directory():
    assert seal_path().parent == LEDGER


def test_an_explicit_out_still_wins():
    """--out is how the dry run writes somewhere harmless; the date default must not
    override it."""
    import inspect

    import tools.market_bet as mb
    src = inspect.getsource(mb._grounded_run)
    assert "a.out or seal_path()" in src
