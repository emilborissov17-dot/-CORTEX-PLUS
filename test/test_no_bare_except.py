#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_no_bare_except.py — NOTHING IN THIS REPO MAY REFUSE TO BE STOPPED.

WHY A BARE except: IS A SAFETY DEFECT HERE AND NOT A STYLE COMPLAINT
---------------------------------------------------------------------
`except:` catches BaseException, which includes SystemExit and KeyboardInterrupt.
Everything this system's safety story rests on is the ability to stop a cycle:

  - the watchdog kills a step whose heartbeat has gone stale past its ceiling
    (supervisor.py, ceiling_for / _kill_or_fail)
  - the human interrupts a run at the terminal
  - a module calls sys.exit() to refuse to proceed

A bare `except:` inside a step swallows all three. The step logs nothing, returns
as if it had merely failed a fetch, and the cycle carries on. The kill signal is
not delayed — it is discarded.

Measured 17 Aug 2026, before the fix: 68 bare handlers across 25 tracked files,
45 of them on the live nightly cycle path (statically reachable from
fast_cycle_runner.py), including memory/body_scan.py, memory/existence_model.py
and eleven data_providers modules that run every night.

WHAT THIS TEST DOES NOT COVER
------------------------------
`except BaseException:` is the same defect spelled differently, and three of those
remain in the repo ON PURPOSE — see test_baseexception_sites_are_the_documented_ones
below, which pins the exact set so a fourth cannot appear unnoticed.

This is a source-structure test: it parses, it does not execute. It proves no bare
handler exists; it cannot prove that the narrowed handlers catch the right things.

    venv\\Scripts\\python.exe -m pytest test/test_no_bare_except.py -v
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# The three deliberate `except BaseException:` sites, with the reason each exists.
# Pinned as data so that adding a fourth fails this file rather than passing quietly.
ALLOWED_BASE_EXCEPTION = {
    ("fast_cycle_runner.py", "importing web_intelligence_agent, which may sys.exit() "
                             "at import time; the runner must survive that"),
    ("supervisor.py",        "metta_selfcheck must never throw — it records the "
                             "verdict and returns, including when the bridge exits"),
}


def _tracked_python_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=str(REPO),
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        pytest.skip(f"git ls-files unavailable: {out.stderr.strip()[:200]}")
    files = [REPO / p for p in out.stdout.splitlines() if p.strip()]
    assert files, "git ls-files returned no .py files — the scan would pass on nothing"
    return files


def _read(p: Path) -> str:
    """utf-8-sig, not utf-8.

    agents/internet/internet_agent.py carries a UTF-8 BOM. Read as plain utf-8 it
    raises SyntaxError at line 1 on the BOM character, and a scanner that treats a
    parse failure as 'nothing to see' would skip the file silently. That happened
    during this work: the first scan reported the file as broken and excluded it.
    Python itself handles the BOM, so the file is fine — the reader was wrong.
    """
    return p.read_text(encoding="utf-8-sig", errors="replace")


def _bare_except_sites(src: str, label: str = "<memory>") -> list[str]:
    """`file:line` for every bare `except:` — via AST, so comments and strings cannot
    produce a hit and cannot hide one either."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [f"{label}:{e.lineno}: UNPARSEABLE ({e.msg}) — cannot be scanned"]
    return [f"{label}:{n.lineno}"
            for n in ast.walk(tree)
            if isinstance(n, ast.ExceptHandler) and n.type is None]


def _base_exception_sites(src: str, label: str = "<memory>") -> list[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return [f"{label}:{n.lineno}"
            for n in ast.walk(tree)
            if isinstance(n, ast.ExceptHandler)
            and isinstance(n.type, ast.Name) and n.type.id == "BaseException"]


# ---------------------------------------------------------------------------
# Positive controls
# ---------------------------------------------------------------------------

def test_the_detector_actually_detects():
    """POSITIVE CONTROL. A scan that finds nothing proves nothing until the scanner
    is shown catching what it is for — and shown NOT firing on the near-misses that
    a grep-based version of this test would trip over."""
    assert _bare_except_sites("try:\n    x()\nexcept:\n    pass\n"), \
        "detector missed a bare except:"
    assert _bare_except_sites("try:\n    x()\nexcept:  # noqa\n    pass\n"), \
        "detector missed a bare except: with a trailing comment"

    # The near-misses. A regex for 'except:' would fail every one of these.
    for benign, why in (
        ("try:\n    x()\nexcept Exception:\n    pass\n", "the narrowed form"),
        ("try:\n    x()\nexcept (ValueError, KeyError):\n    pass\n", "a tuple"),
        ("try:\n    x()\nexcept Exception as e:\n    pass\n", "bound to a name"),
        ("# a bare except: in a comment\nx = 1\n", "inside a comment"),
        ('MSG = "do not write except: here"\n', "inside a string literal"),
        ('"""docstring mentioning except: in prose"""\nx = 1\n', "inside a docstring"),
        ("try:\n    x()\nexcept BaseException:\n    pass\n", "BaseException — a different test's job"),
    ):
        assert not _bare_except_sites(benign), f"detector FALSE-POSITIVED on {why}"


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_no_tracked_python_file_contains_a_bare_except():
    """No tracked .py may swallow SystemExit and KeyboardInterrupt.

    THE STAKE: the watchdog stops a wedged cycle by killing it, and the human stops
    one with Ctrl-C. A bare handler anywhere on the cycle path turns either signal
    into a shrug — the step continues, and the mechanism the last two days of work
    repaired is defeated one level below it.

    Use `except Exception:`. If a block genuinely must run during interpreter
    shutdown — a lock release, a final flush — that is what `finally:` is for, and it
    is worth a comment saying so. At the time of writing, no site in this repo needed
    one: all 68 were fetch fallbacks, JSON reads and scans.
    """
    offenders = []
    for f in _tracked_python_files():
        offenders += _bare_except_sites(_read(f), f.relative_to(REPO).as_posix())

    assert not offenders, (
        f"{len(offenders)} bare `except:` handler(s):\n  " + "\n  ".join(offenders) +
        "\n\nA bare except catches SystemExit and KeyboardInterrupt, so this code can "
        "refuse to be stopped by the watchdog or by the human. Use `except Exception:`. "
        "If the block must also run on interpreter shutdown, use `finally:` and say why.")


def test_baseexception_sites_are_the_documented_ones():
    """`except BaseException:` is the same defect spelled out, so the set is pinned.

    Three sites are deliberate — a module that may sys.exit() at import time, and a
    selfcheck contracted never to throw. They are legitimate and they are also exactly
    the shape that would let a new one hide. Pinning the FILES (not the line numbers,
    which move on every edit) means a fourth file acquiring one fails this test, while
    ordinary edits to the existing two do not.
    """
    allowed_files = {f for f, _why in ALLOWED_BASE_EXCEPTION}
    unexpected = []
    for f in _tracked_python_files():
        rel = f.relative_to(REPO).as_posix()
        if rel in allowed_files:
            continue
        unexpected += _base_exception_sites(_read(f), rel)

    assert not unexpected, (
        "`except BaseException:` in a file not on the documented list:\n  "
        + "\n  ".join(unexpected)
        + "\n\nThis catches SystemExit and KeyboardInterrupt exactly as a bare except "
          "does. If it is deliberate, add the file to ALLOWED_BASE_EXCEPTION in this "
          "test WITH the reason. If it is not, use `except Exception:`.")
