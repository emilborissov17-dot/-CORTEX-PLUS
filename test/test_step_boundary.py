#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_step_boundary.py — B4 STEP 1: the 31 steps that never call _run().

44 of the 75 steps in the map have a measured contract. The other 31 have none,
and not through neglect: they are inline blocks in fast_cycle_runner, so _run()
never wraps them and StepContract is never opened. Nobody writes a row, so no
duration exists, so the ceiling that applies to them is the default one — which
is how constancy_and_constellation was killed on 13 Sep 2026 for exceeding 900 s
it had never once been measured against.

beat() is the one call all 75 make. The boundary is taken from there.

WHAT A FAILURE LOOKS LIKE, said plainly so it cannot be quietly satisfied:
  * an inline step with no span at all — the boundary did not fire;
  * a span left open at the end — an open with no span is reserved for "the
    process died here", and a boundary that leaks one destroys that meaning;
  * a beat span counted in the step:* arithmetic — beat runs BEFORE _run, so it
    wraps it, and those seconds would be counted twice;
  * reads recorded on an ordinary night — the channel is for instrumented runs,
    and a night opens tens of thousands of files.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import flight_recorder as fr        # noqa: E402


def _rows(p):
    return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _trace(tmp_path, monkeypatch, body):
    monkeypatch.setattr(fr, "TRACE_DIR", str(tmp_path))
    p = fr.start("boundary-test")
    try:
        body()
    finally:
        fr.stop("OK")
    return _rows(p)


# ── the boundary exists, and it closes ───────────────────────────────────────

def test_an_inline_step_gets_a_span_and_a_duration(tmp_path, monkeypatch):
    import time

    def body():
        fr.mark_step("canon_load", "0.05")
        time.sleep(0.05)
        fr.mark_step("trend_tracker", "3")
        time.sleep(0.05)

    rows = _trace(tmp_path, monkeypatch, body)
    spans = {r["name"]: r for r in rows if r["k"] == "span"}
    assert "stepb:canon_load" in spans, "the first inline step left no span"
    assert "stepb:trend_tracker" in spans, "the second inline step left no span"
    assert spans["stepb:canon_load"]["ms"] > 0, "a step with no duration is not measured"
    assert spans["stepb:canon_load"]["attr"]["index"] == "0.05"


def test_the_last_inline_step_is_closed_and_not_left_hanging(tmp_path, monkeypatch):
    """An open with no span means the process died there. A boundary that leaks
    one destroys the only signal the trace has for a death."""
    rows = _trace(tmp_path, monkeypatch, lambda: fr.mark_step("cycle_report", "25.6"))
    opens = {r["sp"] for r in rows if r["k"] == "open"}
    spans = {r["sp"] for r in rows if r["k"] == "span"}
    assert opens and opens == spans, f"left open: {sorted(opens - spans)}"


def test_repeated_beats_inside_one_step_do_not_chop_it_up(tmp_path, monkeypatch):
    """A long step beats several times. Each beat must not start a new span, or
    a 40-minute step is recorded as forty one-minute ones."""
    def body():
        for _ in range(5):
            fr.mark_step("web_intelligence", "1")

    rows = _trace(tmp_path, monkeypatch, body)
    got = [r for r in rows if r["k"] == "span" and r["name"] == "stepb:web_intelligence"]
    assert len(got) == 1, f"five beats produced {len(got)} spans"


def test_the_boundary_never_raises_even_when_the_recorder_is_broken(monkeypatch):
    """An observer may not cost a step. This is the whole reason it is wrapped."""
    def _boom(*a, **k):
        raise RuntimeError("the recorder is broken")
    monkeypatch.setattr(fr, "span", _boom)
    monkeypatch.setitem(fr._state, "on", True)
    assert fr.mark_step("anything", "1") is None


# ── the arithmetic must not count the same seconds twice ─────────────────────

def test_a_beat_span_is_not_counted_against_the_wall_clock(tmp_path, monkeypatch):
    """beat() runs BEFORE _run(), so the beat span WRAPS the _run span. If both
    were named step:* the report would sum the same seconds twice and announce
    that the night took longer than it did."""
    import time

    def body():
        fr.mark_step("daily_tier", "2.52")
        with fr.span("step:daily_tier", {"step": "daily_tier", "source": "_run"}):
            time.sleep(0.05)

    rows = _trace(tmp_path, monkeypatch, body)
    counted = [r for r in rows if r["k"] == "span" and r["name"].startswith("step:")]
    assert len(counted) == 1, (
        f"the wall-clock sum sees {[r['name'] for r in counted]} — the same "
        f"seconds twice")
    assert counted[0]["attr"]["source"] == "_run"


def test_events_land_on_the_inline_step_when_there_is_no_run_span(tmp_path, monkeypatch):
    """Attribution is the point. A read recorded against sp=null tells nobody
    which step consumes that file.

    FROM ANOTHER THREAD, deliberately. In the calling thread the ContextVar
    carries the span and this would pass no matter what — the first version of
    this test did, and the mutation that breaks cross-thread attribution went
    through it green. The cases that matter are all off-thread: the pulse
    sampler, the audit hook firing inside a worker, a ThreadPoolExecutor
    fetching axes. Those reach the step only through the process-wide
    _CURRENT_STEP, which is set for a span only if it counts as a step.
    """
    import threading

    def body():
        fr.mark_step("scoring_engine", "12.4")
        th = threading.Thread(
            target=lambda: fr.event("read", {"path": "config/scheduler.json"}))
        th.start()
        th.join()

    rows = _trace(tmp_path, monkeypatch, body)
    ev = next(r for r in rows if r["k"] == "ev" and r["name"] == "read")
    span = next(r for r in rows if r["k"] == "span" and r["name"] == "stepb:scoring_engine")
    assert ev["sp"] == span["sp"], (
        f"a worker thread's read was attributed to {ev['sp']!r}, not to the step "
        f"that was open — an honest null would be better than a wrong span, but "
        f"the step was known and could have been named")


# ── reads: a real input channel, and OFF unless asked ────────────────────────

def _in_subprocess(body: str, env_extra=None):
    script = textwrap.dedent(f"""
        import json, os, sys, tempfile
        {"os.environ['CORTEX_TRACE_READS'] = '1'" if env_extra else ""}
        sys.path.insert(0, r"{REPO}")
        from core import flight_recorder as fr
        fr.TRACE_DIR = tempfile.mkdtemp()
        p = fr.start("read-channel")
        fr.mark_step("canon_load", "0.05")
        open(os.path.join(r"{REPO}", "config", "scheduler.json"), encoding="utf-8").read()
        fr.stop("OK")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        {body}
    """)
    env = dict(os.environ)
    env.pop("CORTEX_TRACE_READS", None)
    if env_extra:
        env.update(env_extra)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         env=env, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    return out.stdout.strip().splitlines()[-1]


def test_reads_are_silent_unless_the_channel_is_asked_for():
    """A night opens tens of thousands of files for reading. Recording them all
    by default would drown the trace a human is supposed to read."""
    n = _in_subprocess('print(sum(1 for r in rows if r.get("name") == "read"))')
    assert n == "0", f"reads were recorded without CORTEX_TRACE_READS: {n}"


def test_with_the_channel_on_a_read_is_recorded_and_named():
    line = _in_subprocess(
        'print(json.dumps(sorted({r["attr"]["path"] for r in rows '
        'if r.get("name") == "read"})))',
        env_extra={"CORTEX_TRACE_READS": "1"})
    paths = json.loads(line)
    assert "config/scheduler.json" in paths, (
        f"the read channel is on and the file it read is not in the trace: {paths}")


# ── structural: the boundary hangs off beat(), and nowhere else ──────────────

def test_beat_is_what_marks_the_boundary():
    """If it moves, the steps that do not beat stop being measured — and those
    are exactly the 31 this was built for."""
    import ast
    src = (REPO / "memory" / "heartbeat.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "beat")
    names = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "mark_step" in names, "beat() no longer marks the step boundary"
