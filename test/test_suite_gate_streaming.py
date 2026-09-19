# -*- coding: utf-8 -*-
"""test/test_suite_gate_streaming.py — a 37-minute run that shows nothing until it ends.

THE DEFECT, 19 September 2026. tools/suite_gate.py ran the suite through
subprocess.run(..., capture_output=True). That buffers the child's entire output
in a pipe and hands it over only at exit, so claude/reports/SUITE_GATE_*.out.log
sat at 0 bytes for thirty-seven minutes, and a run killed mid-flight — by the
harness, by the low-memory reaper, by a reboot — lost EVERY line it had produced.
Two gate runs were killed on 19 September and neither could say which test it was
on, because the answer had never left the pipe.

WHAT THESE TESTS PIN, in order of what actually matters:

  1. Lines arrive WHILE the child runs, not at its exit. Asserted against the
     clock, because "the text is all there afterwards" is equally true of the
     buffered version this replaces and would pass against the bug.
  2. The collected text is exactly what was streamed — the log the human watches
     and the text the parser judges cannot be two different things.
  3. run()'s parsed result is UNCHANGED for the same text. The whole change was
     meant to move where the text comes from and nothing else.
  4. stderr does NOT reach the parser. This is why the streams stayed separate
     rather than being merged with stderr=STDOUT, and it is a measurement:
     merging silently flips verdicts.

None of these runs the real suite.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

sys.path.insert(0, str(REPO / "tools"))
import suite_gate as sg   # noqa: E402


def _child(script: str) -> list:
    return [sys.executable, "-c", script]


# ── 1. It streams. Measured against the clock. ───────────────────────────────

def test_lines_arrive_while_the_child_is_still_running(monkeypatch):
    """THE ONE THAT WOULD HAVE CAUGHT IT.

    The child prints a line, sleeps, then prints another and exits. If output is
    streamed, the first line reaches us roughly a second before the call returns.
    If it is buffered — the old behaviour — both appear only at exit, and the gap
    collapses to ~0.
    """
    seen = []

    class _Recorder:
        def write(self, s):
            if s.strip():
                seen.append((s.rstrip("\n"), time.monotonic()))
            return len(s)

        def flush(self):
            pass

    monkeypatch.setattr(sys, "stdout", _Recorder())
    script = ("import sys,time\n"
              "print('first'); sys.stdout.flush()\n"
              "time.sleep(1.2)\n"
              "print('second'); sys.stdout.flush()\n"
              "sys.exit(3)\n")
    t0 = time.monotonic()
    proc = sg._stream_command(_child(script), str(REPO))
    t_return = time.monotonic()

    monkeypatch.undo()

    assert [s for s, _ in seen] == ["first", "second"], seen
    first_at = seen[0][1]
    assert t_return - first_at > 0.8, (
        "the first line appeared only %.2fs before the call returned — output is "
        "being buffered to the end, not streamed" % (t_return - first_at))
    assert first_at - t0 < 0.8, "the first line took too long to appear"
    assert proc.returncode == 3


def test_every_line_of_a_failing_command_reaches_stdout(monkeypatch, capsys):
    """N lines in, N lines out, and a non-zero exit does not lose any of them."""
    n = 40
    script = ("import sys\n"
              "for i in range(%d): print('line %%d' %% i)\n"
              "sys.exit(7)\n" % n)
    proc = sg._stream_command(_child(script), str(REPO))
    printed = capsys.readouterr().out.splitlines()
    assert printed == ["line %d" % i for i in range(n)], (
        "streamed %d lines, expected %d" % (len(printed), n))
    assert proc.returncode == 7


# ── 2. What was streamed is what was collected ───────────────────────────────

def test_the_collected_text_equals_what_was_streamed(capsys):
    script = ("import sys\n"
              "for i in range(25): print('row %d' % i)\n"
              "sys.exit(0)\n")
    proc = sg._stream_command(_child(script), str(REPO))
    streamed = capsys.readouterr().out
    assert proc.stdout == streamed.rstrip("\n"), (
        "the text handed to the parser is not the text the human watched")
    assert proc.stdout.splitlines() == ["row %d" % i for i in range(25)]


def test_a_trailing_newline_does_not_create_a_phantom_empty_line():
    """An off-by-one here would add an empty last line to every run, which the
    reverse summary scan would then walk past forever."""
    proc = sg._stream_command(_child("print('only')"), str(REPO))
    assert proc.stdout == "only"
    assert proc.stdout.splitlines() == ["only"]


# ── 3. run() parses the same as before ───────────────────────────────────────

def _reference_parse(text: str) -> dict:
    """The parsing as it stood BEFORE this change, reproduced verbatim."""
    summary = ""
    for line in reversed((text or "").splitlines()):
        if " passed" in line or " failed" in line:
            summary = line.strip()
            break
    failed = sorted(l.split(" ")[1] for l in (text or "").splitlines()
                    if l.startswith("FAILED ") and len(l.split(" ")) > 1)
    collect = sorted(l.split(" ")[1] for l in (text or "").splitlines()
                     if l.startswith("ERROR ") and len(l.split(" ")) > 1)
    return {"summary": summary, "failed": failed, "collection_errors": collect}


def _isolated(tmp_path):
    """Paths that exist nowhere near live state."""
    return {"lock": tmp_path / "cycle.lock",
            "heartbeat": tmp_path / "heartbeat.json",
            "last_sealed": tmp_path / "last_sealed.json",
            "runs_path": tmp_path / "suite_runs.jsonl"}


def test_run_parses_a_streamed_suite_exactly_as_the_old_code_did(tmp_path):
    lines = [
        "test session starts",
        "FAILED test/test_b.py::test_two",
        "FAILED test/test_a.py::test_one",
        "2 failed, 118 passed in 3.21s",
    ]
    script = ("import sys\n"
              "for l in %r: print(l)\n"
              "sys.exit(1)\n" % lines)
    entry = sg.run(command=_child(script), write_record=False, **_isolated(tmp_path))
    ref = _reference_parse("\n".join(lines))
    assert entry["summary"] == ref["summary"] == "2 failed, 118 passed in 3.21s"
    assert entry["failed"] == ref["failed"] == [
        "test/test_a.py::test_one", "test/test_b.py::test_two"]
    assert entry["collection_errors"] == ref["collection_errors"] == []
    assert entry["returncode"] == 1


def test_a_collection_error_is_still_recognised(tmp_path):
    """The outcome that must never be mistaken for a clean suite."""
    lines = ["ERROR Broker-bot/test_x.py", "!!! Interrupted: 1 error during collection !!!"]
    script = ("import sys\n"
              "for l in %r: print(l)\n"
              "sys.exit(2)\n" % lines)
    entry = sg.run(command=_child(script), write_record=False, **_isolated(tmp_path))
    assert entry["collection_errors"] == ["Broker-bot/test_x.py"]
    assert entry["outcome"] == "COLLECTION_FAILED"


def test_a_killed_pytest_is_still_incomplete_not_clean(tmp_path):
    """A run with no summary line must not read as zero failures."""
    script = ("import sys\n"
              "print('test session starts')\n"
              "print('pytest was here')\n"
              "sys.exit(1)\n")
    entry = sg.run(command=[sys.executable, "-c", "import sys\n"
                            "print('running pytest shim')\nsys.exit(1)\n"],
                   write_record=False, **_isolated(tmp_path))
    assert entry["summary"] == ""
    assert entry["failed"] == []
    assert entry["outcome"] == "INCOMPLETE", (
        "a run that printed no summary was recorded as %r" % entry["outcome"])


# ── 4. stderr stays out of the parser ────────────────────────────────────────

def test_stderr_is_captured_but_never_reaches_the_parsed_text():
    """WHY THE STREAMS ARE SEPARATE.

    With stderr=STDOUT these two lines would make the run a COLLECTION_FAILED
    with a hijacked summary. Merging is the obvious simplification and it
    silently changes verdicts, so it is pinned out here.
    """
    script = ("import sys\n"
              "print('1 failed, 2 passed in 0.10s')\n"
              "print('ERROR conftest could not load', file=sys.stderr)\n"
              "print('warning: 0 failed to initialise', file=sys.stderr)\n"
              "sys.exit(1)\n")
    proc = sg._stream_command(_child(script), str(REPO))
    assert "ERROR conftest" not in proc.stdout, (
        "stderr leaked into the text the parser judges")
    ref = _reference_parse(proc.stdout)
    assert ref["collection_errors"] == [], (
        "a stderr line became a collection error: %r" % ref["collection_errors"])
    assert ref["summary"] == "1 failed, 2 passed in 0.10s"
    assert "ERROR conftest" in proc.stderr, (
        "stderr was dropped entirely — it must be drained, or a full pipe "
        "deadlocks the child")


def test_a_large_stderr_does_not_deadlock_the_child():
    """The reason stderr is drained on a thread rather than left unread: a full
    pipe blocks the writer forever and the gate hangs with no output at all."""
    script = ("import sys\n"
              "sys.stderr.write('x' * 300000)\n"
              "print('done')\n"
              "sys.exit(0)\n")
    proc = sg._stream_command(_child(script), str(REPO))
    assert proc.stdout == "done"
    assert len(proc.stderr) >= 300000


# ── 5. The durations flag is actually asked for ──────────────────────────────

def test_the_real_command_asks_pytest_where_the_time_went():
    """--durations=25, so a 37-minute run says which tests spent it.

    Checked by CONSTRUCTING the command run() builds, not by reading the source
    and not by running the suite.
    """
    import tempfile
    import types
    from pathlib import Path as _P

    captured = {}

    def _fake_stream(cmd, cwd):
        captured["cmd"] = list(cmd)
        return types.SimpleNamespace(stdout="0 passed in 0.01s", stderr="",
                                     returncode=0)

    real = sg._stream_command
    sg._stream_command = _fake_stream
    try:
        with tempfile.TemporaryDirectory() as td:
            sg.run(write_record=False,
                   lock=_P(td) / "l", heartbeat=_P(td) / "h",
                   last_sealed=_P(td) / "s", runs_path=_P(td) / "r.jsonl")
    finally:
        sg._stream_command = real

    cmd = captured["cmd"]
    assert "--durations=25" in cmd, (
        "the gate no longer asks pytest for its slowest tests: %r" % cmd)
    # and the flags that decide WHAT runs are untouched
    assert "-q" in cmd and "-rf" in cmd
    # NOT cmd.index("-m"): the first -m is `python -m pytest`. The marker
    # selector is the LAST one, and conflating them is how this assertion
    # first read "pytest" and went red.
    assert cmd[len(cmd) - 1 - cmd[::-1].index("-m") + 1] == "not live_state"
