#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_voluntary_halt.py — the third state, and it must not become a death.

Until 13 Sep 2026 a cycle either finished or was killed. One bad minute at step 48
threw away two hours and left a record saying "died", the supervisor charged a
restart from a budget of two, and the replacement walked into the same wall. Three
times that day.

A halt is the missing ending: stop, say where and why, keep everything already
written, exit with a code that is not a crash.

Each test below fails if the thing it names is removed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import halt as H                       # noqa: E402

# conftest's autouse _no_live_side_effects replaces core.halt.check with a no-op
# for EVERY test in the repo, and rightly: a unit test of beat() must not end
# because the machine it runs on happens to be starved. It also means that this
# file, which exists to test that very function, would have quietly tested a stub
# — two of these tests passed against the no-op before this fixture existed and
# proved nothing. So: capture the real one at import, put it back per test, and
# assert below that the swap actually happened.
_REAL_CHECK = H.check


@pytest.fixture(autouse=True)
def _the_real_check(monkeypatch):
    monkeypatch.setattr(H, "check", _REAL_CHECK)


def test_this_file_exercises_the_real_check_and_not_the_stub():
    """Mutation net for the fixture above. Delete it and this fails, instead of
    ten green tests that touched nothing."""
    assert H.check is _REAL_CHECK
    assert getattr(H.check, "__module__", None) == "core.halt"


# ── the halt cannot be swallowed ─────────────────────────────────────────────

def test_a_halt_is_not_an_Exception_and_run_cannot_eat_it():
    """_run catches Exception so one broken step cannot cost the night — and that
    is exactly what would swallow the decision to stop."""
    assert issubclass(H.VoluntaryHalt, BaseException)
    assert not issubclass(H.VoluntaryHalt, Exception)
    swallowed = False
    try:
        try:
            raise H.VoluntaryHalt("s", "1", "why", 10.0, 99.0)
        except Exception:                       # noqa: BLE001 — the shape _run uses
            swallowed = True
    except H.VoluntaryHalt:
        pass
    assert not swallowed, "a step's except Exception ate the halt"


def test_the_exit_code_is_not_a_crash_and_not_a_success():
    assert H.HALT_EXIT_CODE == 7
    assert H.HALT_EXIT_CODE not in (0, 1, 2, 3, 130)


def test_the_ledger_event_is_its_own_and_not_a_death():
    """A death charges a restart and triggers an immediate replacement. If a halt
    were written as CYCLE_DIED the whole feature would be undone by its record."""
    assert H.LEDGER_EVENT == "CYCLE_HALTED_SELF"
    assert "DIED" not in H.LEDGER_EVENT


# ── the trigger reads the gate, and nothing else ─────────────────────────────

def test_a_refusing_gate_raises_with_the_numbers_attached(monkeypatch):
    monkeypatch.setattr(H, "_LAST_ASK", 0.0, raising=False)
    monkeypatch.setattr("core.survival_gate.check",
                        lambda *a, **k: {"allowed": False,
                                         "reasons": ["ram_free=88MB at gate level 600"]})
    with pytest.raises(H.VoluntaryHalt) as e:
        H.check("daily_analysis", "22")
    assert e.value.step == "daily_analysis" and e.value.index == "22"
    assert "ram_free" in e.value.reason
    assert e.value.free_mb is None or e.value.free_mb >= 0


def test_an_allowing_gate_lets_the_cycle_walk_on(monkeypatch):
    monkeypatch.setattr(H, "_LAST_ASK", 0.0, raising=False)
    monkeypatch.setattr("core.survival_gate.check", lambda *a, **k: {"allowed": True})
    assert H.check("x", "1") is None


def test_an_unreadable_gate_does_not_stop_a_healthy_cycle(monkeypatch):
    """FAIL-OPEN. A sensor that cannot be read must not be able to end the night;
    that failure would be silent and would arrive every single time."""
    monkeypatch.setattr(H, "_LAST_ASK", 0.0, raising=False)
    def _boom(*a, **k):
        raise RuntimeError("gate is broken")
    monkeypatch.setattr("core.survival_gate.check", _boom)
    assert H.check("x", "1") is None


def test_the_ask_is_throttled(monkeypatch):
    asks = []
    monkeypatch.setattr(H, "_LAST_ASK", 0.0, raising=False)
    monkeypatch.setattr("core.survival_gate.check",
                        lambda *a, **k: asks.append(1) or {"allowed": True})
    H.gate_refuses(min_gap_sec=300)
    H.gate_refuses(min_gap_sec=300)
    assert len(asks) == 1, "beat() runs 75 times a night; one answer per step is waste"


def test_no_threshold_number_is_written_in_this_module():
    """The line lives in homeostasis. A copy here would one day disagree with it,
    and the disagreement would be found on a bad night."""
    src = (REPO / "core" / "halt.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    body = [n for n in tree.body if not isinstance(n, ast.Expr)]
    nums = [n.value for n in ast.walk(ast.Module(body=body, type_ignores=[]))
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool)]
    assert 92 not in nums and 600 not in nums, (
        f"a threshold was copied into core/halt.py: {sorted(set(nums))}")


# ── the record: ledger row, closed span, and a live cycle stopping itself ────

def test_the_record_writes_a_ledger_row_and_closes_the_trace(tmp_path, monkeypatch):
    from core import flight_recorder as fr
    rows = []
    monkeypatch.setattr("memory.existence_ledger.append",
                        lambda ev, **f: rows.append((ev, f)) or {})
    monkeypatch.setattr(fr, "TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(H, "_LAST_ASK", 0.0, raising=False)
    monkeypatch.setattr("core.survival_gate.check",
                        lambda *a, **k: {"allowed": False, "reasons": ["ram_free=88MB"]})
    p = fr.start("halting-cycle")
    exc = None
    try:
        # The real shape: the halt is raised INSIDE the open step and travels out
        # through the recorder's context manager. That is the moment a kill leaves
        # an "open" with no "span" behind it, so it is the moment worth testing.
        with fr.span("step:deduction", {"step": "deduction"}):
            H.check("deduction", "12.65")
    except H.VoluntaryHalt as e:
        exc = e
    assert exc is not None, "the gate refused and nothing was raised"
    rec = H.record(exc, cycle_id="c1", steps_done=47)

    assert rec["ledger"] is True and rows, "nothing reached the ledger"
    ev, fields = rows[0]
    assert ev == "CYCLE_HALTED_SELF"
    assert fields["step"] == "deduction" and fields["steps_completed"] == 47
    assert fields["reason"]

    lines = [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()
             if l.strip()]
    opens = {r["sp"] for r in lines if r["k"] == "open"}
    spans = {r["sp"] for r in lines if r["k"] == "span"}
    assert opens and opens == spans, (
        f"the trace has an open with no span: {sorted(opens - spans)} — a halt must "
        f"not look like a kill")
    assert any(r.get("name") == "halt" for r in lines), "the halt itself is not in the trace"
    step = next(r for r in lines if r["k"] == "span" and r["name"] == "step:deduction")
    assert step["st"] == "HALTED", (
        f'the step closed as {step["st"]!r}; a night that stopped on purpose must '
        f"not be coloured as a failed step in the morning report")
    assert step["ms"] >= 0 and step.get("t_end") is not None


def test_a_starved_cycle_stops_itself_and_exits_seven(tmp_path):
    """End to end, in a real process: the gate refuses at the third beat, the
    program stops itself, and the exit code says so."""
    script = tmp_path / "victim.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, r"{REPO}")
        import core.survival_gate as sg
        from core import halt as H

        beats = {{"n": 0}}
        def _check(*a, **k):
            beats["n"] += 1
            return {{"allowed": beats["n"] < 3,
                    "reasons": ["ram_free=88MB at gate level 600"]}}
        sg.check = _check
        H.ASK_GAP_SEC = 0.0

        done = 0
        try:
            for i in range(10):
                H.check(f"step{{i}}", str(i))
                done += 1
                print("did", i, flush=True)
        except H.VoluntaryHalt as e:
            print("HALTED", e.step, "after", done, flush=True)
            raise SystemExit(H.HALT_EXIT_CODE)
        raise SystemExit(0)
    """), encoding="utf-8")

    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       timeout=120)
    assert p.returncode == H.HALT_EXIT_CODE, (
        f"exit {p.returncode}, stdout={p.stdout[-300:]} stderr={p.stderr[-300:]}")
    assert "HALTED step2 after 2" in p.stdout, p.stdout
    assert "did 1" in p.stdout, "it stopped before doing any work at all"


def test_the_heartbeat_is_where_the_gate_is_asked():
    """Structural, and the reason the halt can exist at all: beat() is the one
    gate all 75 steps pass. Ask anywhere else and the steps that do not call it
    walk on into memory that is not there."""
    import ast
    src = (REPO / "memory" / "heartbeat.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "beat")
    names = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_halt_check" in names or "check" in names, (
        "beat() no longer asks the gate; the cycle can only be killed again")


def test_the_runner_catches_it_rather_than_letting_it_look_like_a_crash():
    """Structural: fast_cycle_runner must handle VoluntaryHalt around main(). If
    that clause goes, a halt becomes an unhandled BaseException and the supervisor
    reads a corpse."""
    import ast
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            for sub in ast.walk(node.type):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    assert "_VoluntaryHalt" in names, "the runner no longer catches a voluntary halt"
