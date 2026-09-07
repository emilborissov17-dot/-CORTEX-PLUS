# -*- coding: utf-8 -*-
"""
PRE-FLIGHT C5 — "--dry-run" is a promise that NO MODEL IS TOUCHED.

PREDICTION ONLY (§VI); nothing here trades.

The promise had a hole. The runner read `if "completions" in dry: ... else:
generate_completions(...)`, so a dry-run file that was missing, malformed or CLOBBERED
silently became a live model run. It fired: a fixture named r52_dry.json and its output
named R52_DRY.json are ONE FILE on a case-insensitive filesystem, so the seal overwrote
its own input, and the next "dry" run called qwen2.5:3b for real.

Two guards, one for each half of that chain.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import DryRunUnusable, same_file  # noqa: E402


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(REPO / "tools" / "market_bet.py"), *args],
        capture_output=True, text=True, cwd=str(cwd or REPO),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})


# ── guard 1: a fixture with no completions REFUSES, never generates ─────────
def test_a_dry_run_without_completions_refuses_loudly(tmp_path):
    """THE ONE THAT FIRED. A sealed bet fed back in as a fixture has no 'completions'
    key — and used to be answered by calling the model."""
    bad = tmp_path / "no_completions.json"
    bad.write_text(json.dumps({"snippets": {"SPY": []}, "assets": {}}), encoding="utf-8")
    r = _run(["--grounded", "--dry-run", str(bad), "--out", str(tmp_path / "o.json")])
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "DryRunUnusable" in combined or "no 'completions' key" in combined
    assert not (tmp_path / "o.json").exists(), "it sealed something anyway"


def test_the_refusal_names_what_was_in_the_file_instead():
    """A refusal that does not say what it found makes the next person guess."""
    with pytest.raises(DryRunUnusable, match="completions"):
        raise DryRunUnusable(
            "--dry-run file has no 'completions' key (top-level keys: ['assets'])")


def test_the_fallback_branch_is_gone_from_the_source():
    """Structural, because a comment saying 'no fallback' is not a fallback being
    gone. Inside the grounded runner, `generate_completions` must not be reachable on
    a path where `dry` is not None."""
    import inspect

    import tools.market_bet as mb
    src = inspect.getsource(mb._grounded_run)
    # the guard must come BEFORE the per-asset loop, not inside it: every asset can
    # refuse on evidence first, and the run would then seal an empty bet with exit 0
    # and never reach a per-asset check at all.
    assert "DryRunUnusable" in src
    assert src.index("DryRunUnusable") < src.index("for sym in ASSETS")


# ── guard 2: --dry-run and --out may not be the same file ──────────────────
def test_same_file_sees_a_case_only_difference(tmp_path):
    """The exact collision: r52_dry.json and R52_DRY.json."""
    p = tmp_path / "r52_dry.json"
    p.write_text("{}", encoding="utf-8")
    if os.path.normcase("A") == os.path.normcase("a"):        # case-insensitive FS
        assert same_file(p, tmp_path / "R52_DRY.json") is True
    assert same_file(p, p) is True
    assert same_file(p, tmp_path / "different.json") is False


def test_same_file_handles_a_target_that_does_not_exist_yet():
    """--out normally names a file that is not there yet, and os.path.samefile raises
    on that. The guard has to work anyway or it only fires on the second run."""
    assert same_file("a/b/../b/x.json", "a/b/x.json") is True


def test_a_colliding_out_refuses_before_reading_anything(tmp_path):
    fixture = tmp_path / "dry.json"
    fixture.write_text(json.dumps({"snippets": {}, "completions": {}}), encoding="utf-8")
    before = fixture.read_text(encoding="utf-8")
    r = _run(["--grounded", "--dry-run", str(fixture), "--out", str(fixture)])
    assert r.returncode == 5, r.stdout + r.stderr
    assert "THE SAME FILE" in r.stdout
    assert fixture.read_text(encoding="utf-8") == before, "the fixture was modified"


def test_a_case_only_colliding_out_refuses(tmp_path):
    if os.path.normcase("A") != os.path.normcase("a"):
        pytest.skip("case-sensitive filesystem")
    fixture = tmp_path / "mybet_dry.json"
    fixture.write_text(json.dumps({"snippets": {}, "completions": {}}), encoding="utf-8")
    r = _run(["--grounded", "--dry-run", str(fixture),
              "--out", str(tmp_path / "MYBET_DRY.json")])
    assert r.returncode == 5, r.stdout + r.stderr
    assert "THE SAME FILE" in r.stdout


def test_a_distinct_out_is_allowed(tmp_path):
    """The guard must not block the normal case."""
    fixture = tmp_path / "dry_in.json"
    fixture.write_text(json.dumps({"snippets": {}, "completions": {}}), encoding="utf-8")
    r = _run(["--grounded", "--dry-run", str(fixture),
              "--out", str(tmp_path / "dry_out.json")])
    assert "THE SAME FILE" not in r.stdout
