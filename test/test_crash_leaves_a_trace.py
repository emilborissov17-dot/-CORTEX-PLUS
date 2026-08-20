#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_crash_leaves_a_trace.py — A DEATH MUST LEAVE LAST WORDS.

WHAT WENT WRONG (measured 20 August 2026)
------------------------------------------
Four cycles have died leaving a log that stops mid-step with nothing after it:

    [STEP] llm_self_review_axes        <- last line of an 813-line file

No error, no traceback, no partial line. A Python exception would have printed.
A fault BELOW Python — SIGSEGV or SIGABRT inside a C extension, and this process
loads several (requests/OpenSSL, chromadb/sqlite, ollama clients) — prints
nothing whatsoever: the interpreter dies before it can say why.

WHAT WAS RULED OUT FIRST
-------------------------
The obvious suspect was buffering: stdout redirected to a file is block-buffered,
so a dying process could lose the tail of its own log. That was MEASURED rather
than assumed, and it is not what happened:

    PYTHONUNBUFFERED=1, no reconfigure   -> write_through=True, line survived os._exit
    PYTHONUNBUFFERED=1, with reconfigure -> write_through=True, line survived os._exit

sys.stdout.reconfigure(encoding=...) does NOT reset write_through, and the
supervisor has set PYTHONUNBUFFERED=1 since the 2026-07-15 empty-log incident.
So the missing line was not swallowed by a buffer — it never executed. That is
evidence about WHERE the process stopped, and it only holds because the log is
genuinely unbuffered, which test_the_log_survives_an_abrupt_death pins.

    venv\\Scripts\\python.exe -m pytest test/test_crash_leaves_a_trace.py -v
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNNER = REPO / "fast_cycle_runner.py"
SUPERVISOR = REPO / "supervisor.py"

# os.abort() raises a genuine SIGABRT: the process dies below Python, exactly
# like a fault inside a C extension. It is NOT a Python exception, which is the
# whole point — a catchable error would prove nothing about faults below Python.
#
# The first attempt used ctypes.string_at(0) and was wrong: on Windows, CPython
# converts the access violation into a catchable OSError, so the "crash" printed
# a normal traceback with faulthandler disabled and the negative control failed.
# Measured, then replaced.
CRASH = "import os; os.abort()"

CYCLE_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}


def _run_to_log(source: str, log: pathlib.Path, unbuffered: bool = True) -> int:
    """Run `source` exactly the way supervisor.spawn_cycle runs the cycle:
    stdout to a file, stderr folded into it, unbuffered."""
    script = log.with_suffix(".py")
    script.write_text(source, encoding="utf-8")
    argv = [sys.executable] + (["-u"] if unbuffered else []) + [str(script)]
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(argv, stdout=fh, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, cwd=str(REPO),
                              env=CYCLE_ENV, timeout=120)
    return proc.returncode


# ---------------------------------------------------------------------------
# (a) faulthandler — and the negative control
# ---------------------------------------------------------------------------

def test_a_fatal_crash_with_faulthandler_lands_a_traceback_in_the_log(tmp_path):
    log = tmp_path / "with_faulthandler.log"
    rc = _run_to_log(
        "import faulthandler; faulthandler.enable(all_threads=True)\n"
        "print('[STEP] the_step_that_dies', flush=True)\n"
        f"{CRASH}\n",
        log,
    )
    text = log.read_text(encoding="utf-8", errors="replace")

    assert rc != 0, "the victim did not actually crash; the test proves nothing"
    assert "[STEP] the_step_that_dies" in text
    assert "Fatal Python error" in text, (
        f"\n  A FATAL CRASH LEFT NO TRACEBACK.\n"
        f"  faulthandler was enabled and the process still died silently, so a\n"
        f"  crash below Python remains as unreadable as the four cycles that\n"
        f"  ended mid-step with no last words.\n"
        f"  Log said:\n{text}\n"
    )
    assert "Current thread" in text, (
        "the dump names no frame, so it cannot say WHERE the crash was"
    )


def test_the_same_crash_without_faulthandler_says_nothing(tmp_path):
    """THE NEGATIVE CONTROL. Without faulthandler the log stops mid-step exactly
    as the four dead cycles did — which is what makes the test above meaningful
    rather than a tautology."""
    log = tmp_path / "no_faulthandler.log"
    rc = _run_to_log(
        "print('[STEP] the_step_that_dies', flush=True)\n"
        f"{CRASH}\n",
        log,
    )
    text = log.read_text(encoding="utf-8", errors="replace")

    assert rc != 0
    assert "[STEP] the_step_that_dies" in text, "the step line should still be there"
    assert "Fatal Python error" not in text, (
        "a traceback appeared without faulthandler — then the test above is not "
        "measuring faulthandler and the negative control is broken"
    )
    assert text.strip().endswith("the_step_that_dies"), (
        f"expected the log to end mid-step with nothing after it, got:\n{text}"
    )


def test_the_runner_enables_faulthandler_before_it_does_anything(tmp_path):
    """It must be armed at import, not somewhere down in main(): a crash while
    importing chromadb or ollama is exactly the case with no traceback today."""
    src = RUNNER.read_text(encoding="utf-8")
    assert "faulthandler.enable(" in src, "fast_cycle_runner.py does not arm faulthandler"

    before_main = src.split("def main(")[0]
    assert "faulthandler.enable(" in before_main, (
        "faulthandler is armed inside or after main() — too late for a crash "
        "during the import of a C extension"
    )


# ---------------------------------------------------------------------------
# (b) The log must survive an abrupt death — the premise the diagnosis rests on
# ---------------------------------------------------------------------------

def test_the_log_survives_an_abrupt_death(tmp_path):
    """os._exit skips flushing, atexit and finally — the closest thing to an OOM
    kill that can be produced deliberately.

    If this ever fails, then a missing line in a cycle log stops being evidence
    that the code did not reach it, and every autopsy built on that reasoning
    has to be redone.
    """
    log = tmp_path / "abrupt.log"
    _run_to_log(
        "import sys, os\n"
        "if hasattr(sys.stdout, 'reconfigure'):\n"
        "    sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "print('LINE_BEFORE_DEATH')\n"
        "os._exit(1)\n",
        log,
    )
    text = log.read_text(encoding="utf-8", errors="replace")

    assert "LINE_BEFORE_DEATH" in text, (
        "a line printed immediately before an abrupt exit did NOT reach disk. "
        "The cycle log is buffered after all, and an absent line no longer "
        "proves the code never ran."
    )


def test_reconfigure_does_not_undo_write_through(tmp_path):
    """The runner calls sys.stdout.reconfigure(encoding=...) at line 11. Pinned
    because if a future edit adds line_buffering=False or write_through=False
    there, the cycle log silently goes back to losing its tail."""
    log = tmp_path / "wt.log"
    _run_to_log(
        "import sys\n"
        "sys.stdout.reconfigure(encoding='utf-8', errors='replace')\n"
        "print('write_through:', sys.stdout.write_through)\n",
        log,
    )
    assert "write_through: True" in log.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (c) The supervisor spawns the cycle so that all of the above holds
# ---------------------------------------------------------------------------

def test_the_supervisor_spawns_the_cycle_unbuffered():
    src = SUPERVISOR.read_text(encoding="utf-8")
    assert '"PYTHONUNBUFFERED": "1"' in src, (
        "the cycle is spawned without PYTHONUNBUFFERED — its log will lose the "
        "tail on the one run that needed explaining"
    )
    assert '[python, "-u", str(RUNNER)]' in src, (
        "the cycle is spawned without -u. The env var alone can be dropped by a "
        "wrapper or a future edit to the env dict; the flag cannot."
    )
