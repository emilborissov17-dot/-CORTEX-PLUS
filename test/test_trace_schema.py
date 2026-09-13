#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_trace_schema.py — the flight recorder, checked where it can lie.

A recorder is trusted more than the thing it records, so the ways it can be
quietly wrong all matter more than usual:

  * a half-written line makes the whole file unreadable;
  * a span with no open, or a duplicate span id, makes the tree wrong in a way
    that still renders;
  * arithmetic that does not close, reported as if it did;
  * an audit hook that raises — which does not break the recorder, it breaks the
    OPERATION that triggered it, anywhere in the process;
  * attribution that guesses. The 32 steps outside _run() are the reason this
    exists, and a plausible label invented for them would delete the question;
  * a kill leaving nothing behind, which is the case the whole synchronous-write
    design is for.

Every test drives the real module. Nothing writes to the live memory/cycle_trace.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import flight_recorder as fr          # noqa: E402


@pytest.fixture
def rec(tmp_path, monkeypatch):
    """The recorder, writing into tmp_path, stopped however the test ends."""
    monkeypatch.setattr(fr, "TRACE_DIR", str(tmp_path))
    yield fr
    if fr.is_on():
        fr.stop()


def _rows(path) -> list:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


# ── 1. every line is JSON ────────────────────────────────────────────────────

def test_every_line_is_valid_json(rec):
    p = rec.start("t-json")
    with rec.span("cycle"):
        with rec.span("step:a", {"step": "a"}):
            rec.event("touch", {"ev": "open-w", "path": "memory/x.json"})
    rec.stop()
    text = Path(p).read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except Exception as e:
            pytest.fail(f"line {i} is not JSON: {e}: {line[:120]!r}")
    assert text.endswith("\n"), "the file must not end mid-line"


# ── 2. the tree is well formed ───────────────────────────────────────────────

def test_every_span_has_an_earlier_open_and_ids_are_unique(rec):
    p = rec.start("t-tree")
    with rec.span("cycle"):
        for name in ("step:a", "step:b", "step:c"):
            with rec.span(name, {"step": name[5:]}):
                pass
    rec.stop()
    rows = _rows(p)
    seen_open = {}
    span_ids = []
    for i, r in enumerate(rows):
        if r["k"] == "open":
            assert r["sp"] not in seen_open, f"duplicate open id {r['sp']}"
            seen_open[r["sp"]] = i
        elif r["k"] == "span":
            assert r["sp"] in seen_open, f"span {r['sp']} has no open before it"
            assert seen_open[r["sp"]] < i, "the open must come first in the file"
            span_ids.append(r["sp"])
            assert r["t_end"] >= r["t"]
    assert len(span_ids) == len(set(span_ids)), "duplicate span ids"


def test_a_raising_step_is_recorded_as_error_and_the_exception_still_travels(rec):
    p = rec.start("t-err")
    with pytest.raises(ValueError):
        with rec.span("step:boom", {"step": "boom"}):
            raise ValueError("deliberate")
    rec.stop()
    span = next(r for r in _rows(p) if r["k"] == "span")
    assert span["st"] == "ERROR"
    assert span["attr"]["error_type"] == "ValueError"
    assert len(span["attr"]["error"]) <= fr.ERR_CHARS


# ── 3. the arithmetic, on numbers chosen so the answer is known ──────────────

def test_the_arithmetic_closes_on_a_file_with_known_numbers(tmp_path):
    """40s of steps + 10s unattributed against a 50s wall clock."""
    from tools import trace_report as tr
    rows = [
        {"k": "head", "trace_id": "a" * 32, "cycle_id": "known", "t0": "2026-09-13T00:00:00Z",
         "pid": 1, "py": "3.14.5", "channels": ["pulse", "audit"]},
        {"k": "open", "sp": "s1", "pa": None, "name": "step:one", "t": 0.0, "attr": {}},
        {"k": "span", "sp": "s1", "pa": None, "name": "step:one", "t": 0.0,
         "t_end": 25.0, "ms": 25000, "st": "OK", "attr": {}},
        {"k": "open", "sp": "s2", "pa": None, "name": "step:two", "t": 30.0, "attr": {}},
        # a nested call: span, which must NOT be added to the step total
        {"k": "open", "sp": "s3", "pa": "s2", "name": "call:core.x.f", "t": 31.0, "attr": {}},
        {"k": "span", "sp": "s3", "pa": "s2", "name": "call:core.x.f", "t": 31.0,
         "t_end": 40.0, "ms": 9000, "st": "OK", "attr": {}},
        {"k": "span", "sp": "s2", "pa": None, "name": "step:two", "t": 30.0,
         "t_end": 45.0, "ms": 15000, "st": "OK", "attr": {}},
        # ten unattributed seconds, as one coalesced pulse
        {"k": "ev", "sp": None, "name": "pulse", "t": 45.0,
         "attr": {"where": "fast_cycle_runner.py:1:main", "n": 10, "t_end": 55.0}},
    ]
    p = tmp_path / "known.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    f = tr.fold(tr.load(p))
    assert f["step_ms_total"] == 40000, "nested call: spans were counted twice"
    assert f["unattributed_sec"] == pytest.approx(10.0)
    assert f["last_t"] == pytest.approx(55.0)
    assert f["accounted"] == pytest.approx(50.0)
    assert f["gap"] == pytest.approx(5.0), "the 5s before the first step must show"
    text = tr.md(f, p)
    assert "does not close" in text and "5s" in text


def test_the_report_gives_every_step_a_row_even_when_it_never_ran(tmp_path):
    from tools import trace_report as tr
    from core.cycle_map import STEPS
    rows = [{"k": "head", "cycle_id": "empty", "t0": "2026-09-13T00:00:00Z",
             "trace_id": "b" * 32, "pid": 1, "py": "3", "channels": []}]
    p = tmp_path / "empty.jsonl"
    p.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    text = tr.md(tr.fold(tr.load(p)), p)
    missing = [s[0] for s in STEPS if f"| {s[0]} |" not in text]
    assert not missing, f"steps with no row at all: {missing[:5]}"
    assert "(unattributed)" in text


# ── 4. the audit hook may never raise ────────────────────────────────────────

def test_the_audit_hook_swallows_its_own_errors(rec, tmp_path, monkeypatch):
    """An exception in an audit hook fails the OPERATION, not the hook — any
    open(), anywhere in the process, including the supervisor's own writes."""
    p = rec.start("t-hook")

    def _explode(*a, **k):
        raise RuntimeError("deliberate failure inside the hook")

    monkeypatch.setattr(fr, "_rel_if_ours", _explode)
    target = tmp_path / "written_while_the_hook_is_broken.txt"
    target.write_text("this write must succeed", encoding="utf-8")   # triggers the hook
    assert target.read_text(encoding="utf-8") == "this write must succeed"
    rec.stop()
    assert Path(p).is_file()
    assert not fr.THREAD_ERRORS, fr.THREAD_ERRORS


def test_the_hook_ignores_reads_and_records_a_write(rec, monkeypatch, tmp_path):
    """fr.REPO is pointed at tmp_path so the hook counts tmp_path as ours.

    The first version of this test wrote to memory/_trace_probe.tmp to be inside
    the real repo, and conftest's live-state guard failed it — correctly. A test
    for a recorder is not allowed to be the thing that writes to live state.
    """
    monkeypatch.setattr(fr, "REPO", str(tmp_path))
    p = rec.start("t-touch")
    inside = tmp_path / "probe.tmp"
    with rec.span("step:probe", {"step": "probe"}):
        inside.write_text("x", encoding="utf-8")
        inside.read_text(encoding="utf-8")              # a read must NOT be recorded
    time.sleep(fr.FLUSH_SEC + 1.5)
    rec.stop()
    touches = [r for r in _rows(p) if r.get("name") == "touch"]
    paths = {t["attr"]["path"] for t in touches}
    assert "probe.tmp" in paths, f"the write was not seen: {paths}"
    kinds = {t["attr"]["ev"] for t in touches if t["attr"]["path"] == "probe.tmp"}
    assert kinds and all(k.startswith(("open-w", "open-a", "open-x")) for k in kinds), kinds
    assert not any(k.startswith("open-r") for k in kinds), "a read was recorded as a write"


# ── 5. attribution outside _run() ────────────────────────────────────────────

def test_the_pulse_names_a_step_that_never_calls_run(rec):
    """The 32 steps that open no contract are the reason this module exists.

    A function named after a real step, called with NO span around it, must still
    be attributed — by the pulse walking the stack, not by anyone declaring it.
    """
    from core.cycle_map import STEPS
    step_name = next(s[0] for s in STEPS if s[0].isidentifier())
    src = textwrap.dedent(f"""
        def {step_name}():
            import time
            time.sleep(2.6)
    """)
    ns = {}
    exec(compile(src, "<generated>", "exec"), ns)

    p = rec.start("t-attr")
    ns[step_name]()                       # no span, no _run, nothing declared
    time.sleep(fr.FLUSH_SEC + 1.5)
    rec.stop()
    pulses = [r for r in _rows(p) if r.get("name") == "pulse"]
    named = [r for r in pulses if (r.get("attr") or {}).get("step_from_stack") == step_name]
    assert named, (f"the pulse never attributed {step_name}; "
                   f"saw {[(r.get('attr') or {}).get('step_from_stack') for r in pulses]}")
    assert all(r["sp"] is None for r in named), "no span was open; sp must be null"


def test_an_unattributable_pulse_is_null_and_not_guessed(rec):
    p = rec.start("t-null")
    time.sleep(2.6)                       # nothing on the stack but the test
    rec.stop()
    pulses = [r for r in _rows(p) if r.get("name") == "pulse"]
    assert pulses, "the pulse never fired"
    assert all(r["sp"] is None for r in pulses)


# ── 6. a kill leaves the open behind, and the report finds it ────────────────

def test_a_killed_process_leaves_an_open_without_a_span(tmp_path):
    """The whole reason 'open' is written synchronously and flushed at once."""
    from tools import trace_report as tr
    script = tmp_path / "victim.py"
    script.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, r"{REPO}")
        from core import flight_recorder as fr
        fr.TRACE_DIR = r"{tmp_path}"
        fr.start("killed-cycle")
        sp = fr.open_span("step:the_one_it_died_in", {{"step": "the_one_it_died_in"}})
        print("OPENED", flush=True)
        time.sleep(120)
    """), encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(script)],
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "OPENED"
        time.sleep(0.5)
    finally:
        proc.kill()
        proc.wait(timeout=15)

    trace = tmp_path / "killed-cycle.jsonl"
    assert trace.is_file(), "the kill left no trace file at all"
    f = tr.fold(tr.load(trace))
    names = [o["name"] for o in f["unclosed"]]
    assert "step:the_one_it_died_in" in names, f"unclosed spans found: {names}"
    text = tr.md(f, trace)
    assert "Died inside" in text and "the_one_it_died_in" in text

    doc_path = tmp_path / "out.json"
    from tools import trace_to_otlp as otlp
    rc = otlp.main(["--trace", str(trace), "--out", str(doc_path)])
    assert rc == 0
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    spans = doc["resourceSpans"][0]["scopeSpans"][0]["spans"]
    dead = [s for s in spans if s["name"] == "step:the_one_it_died_in"]
    assert dead and dead[0]["status"]["code"] == 2
    assert any(kv["key"] == "unclosed" for kv in dead[0]["attributes"])


# ── 7. attribution across threads: the defect that made measurement useless ──

def test_an_event_from_a_worker_thread_is_attributed_to_the_step(rec):
    """THE DEFECT: a ContextVar is per-context, so a worker thread reads the
    default. Measured on the cycle of 13 Sep — 0 of 119 pulses carried a span id
    while step:internet_agent was open for 1691s, and only 2 of 154 spawns were
    attributable, because internet_agent fetches in threads. 'Between 2 and 154'
    is not a measurement."""
    import threading as _th
    p = rec.start("t-threads")
    seen = {}
    with rec.span("step:fetcher", {"step": "fetcher"}) as sp:
        def _worker():
            rec.event("spawn", {"argv": ["yt-dlp"], "pid": 1})
            seen["sp"] = sp.sp
        th = _th.Thread(target=_worker)
        th.start()
        th.join()
    rec.stop()
    spawns = [r for r in _rows(p) if r.get("name") == "spawn"]
    assert spawns, "the worker thread's event never reached the trace"
    assert spawns[0]["sp"] == seen["sp"], (
        f"the event was filed under {spawns[0]['sp']!r} instead of the open step "
        f"{seen['sp']!r} — worker threads are unattributed again")


def test_the_step_is_released_when_it_closes(rec):
    """The process-wide step must not outlive its span, or the next unattributed
    event would be filed under a step that has already finished."""
    p = rec.start("t-release")
    with rec.span("step:one", {"step": "one"}):
        pass
    rec.event("touch", {"ev": "open-w", "path": "after.json"})
    rec.stop()
    after = [r for r in _rows(p) if (r.get("attr") or {}).get("path") == "after.json"]
    assert after and after[0]["sp"] is None, (
        "an event after the step closed was still attributed to it")


def test_a_nested_step_restores_its_parent(rec):
    p = rec.start("t-nested")
    with rec.span("step:outer", {"step": "outer"}) as outer:
        with rec.span("step:inner", {"step": "inner"}):
            pass
        rec.event("touch", {"ev": "open-w", "path": "back_in_outer.json"})
    rec.stop()
    row = next(r for r in _rows(p)
               if (r.get("attr") or {}).get("path") == "back_in_outer.json")
    assert row["sp"] == outer.sp, "the inner step did not give the parent back"


# ── 8. a stalled step must not go silent ─────────────────────────────────────

def test_the_coalescing_ceiling_is_pinned_and_below_a_minute():
    """Watched live on 13 Sep: the trace went quiet for three minutes while the
    cycle was alive, because a coalesced key is only emitted once it stops being
    hit. Silence meaning 'busy' is indistinguishable from silence meaning 'dead'."""
    assert fr.COALESCE_MAX_SEC == 30.0
    assert fr.COALESCE_MAX_SEC > fr.FLUSH_SEC


def test_a_repeating_event_is_still_written_while_it_repeats(rec, monkeypatch):
    """Same key hit continuously; with the ceiling lowered for the test, a row
    must appear WITHOUT the key ever going idle."""
    monkeypatch.setattr(fr, "COALESCE_MAX_SEC", 1.0)
    p = rec.start("t-stall")
    stop = time.time() + 4.0
    while time.time() < stop:
        rec.event("pulse", {"where": "stuck.py:1:f", "t_end": fr._now()})
        time.sleep(0.15)
    rec.stop()
    pulses = [r for r in _rows(p) if r.get("name") == "pulse"]
    assert len(pulses) >= 2, (
        f"only {len(pulses)} row(s) written while the same place was hit for four "
        f"seconds — a stalled step would leave no trace at all")


# ── 9. the report resolves _run labels to step names ─────────────────────────

def test_the_report_matches_run_labels_to_their_step_names(tmp_path):
    """The trace writes step:internet_agent; cycle_map knows internet_intelligence.
    Matching by string made the report say '1 of 75' on a cycle where two steps
    had left spans."""
    from tools import trace_report as tr
    assert tr._canonical("internet_agent") == "internet_intelligence"
    assert tr._canonical("body_scanner") == "body_scan"
    assert tr._canonical("daily_tier") == "daily_tier"

    rows = [{"k": "head", "cycle_id": "x", "t0": "2026-09-13T00:00:00Z",
             "trace_id": "c" * 32, "pid": 1, "py": "3", "channels": []},
            {"k": "open", "sp": "s1", "pa": None, "name": "step:internet_agent",
             "t": 0.0, "attr": {}},
            {"k": "span", "sp": "s1", "pa": None, "name": "step:internet_agent",
             "t": 0.0, "t_end": 100.0, "ms": 100000, "st": "OK", "attr": {}}]
    p = tmp_path / "aliased.jsonl"
    p.write_text(chr(10).join(json.dumps(r) for r in rows) + chr(10), encoding="utf-8")
    f = tr.fold(tr.load(p))
    assert f["ms_by_step"].get("internet_intelligence") == 100000, (
        f"the label was not resolved: {dict(f['ms_by_step'])}")
