# -*- coding: utf-8 -*-
"""ITEM 34 step 2 — scan() runs from the system, not from a human's hand.

memory/cortex_full_state.json was last written 2026-04-13 and
cortex_dashboard.html has been rendering it ever since. cortex_scanner.scan()
had NO caller outside `if __name__ == "__main__"` and appeared 0 times in
fast_cycle_runner.py, core/cycle_map.py and config/cycle_phases.json.
Emil: "make it run from the system, why should I open it by hand."

THE TEST THAT REPLACES A WAIVED SUITE RUN. Kimi's precondition was "the full
suite green with scan() invoked from the cycle runner", and Kimi waived it on
evidence — then named exactly what the waiver gives up: "If the cycle runner's
invocation context differs from manual execution in a way none of us inspected,
the suite would have caught it and I have now waived that protection."

The difference is concrete. cortex_scanner.py:6 is

    BASE = pathlib.Path(__file__).resolve().parent

and every read plus the single write at :166 hangs off BASE. Manual runs had cwd
at the repo root; the cycle runner's cwd is not guaranteed to be. So
test_base_resolves_to_the_repo_root_from_a_foreign_cwd is the whole of the
waived protection, and it must keep passing.
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import cortex_scanner  # noqa: E402


# ── the waived-suite stand-in ──────────────────────────────────────────────

def test_base_resolves_to_the_repo_root_from_a_foreign_cwd(tmp_path):
    """THE ONE TEST STANDING IN FOR THE WAIVED SUITE RUN.

    Run in a subprocess whose cwd is NOT the repo, because that is the only way
    to prove the property rather than assume it — an in-process check inherits
    this session's cwd and would pass vacuously.
    """
    code = ("import cortex_scanner as cs;"
            "print(cs.BASE.as_posix());print(cs.OUT.as_posix())")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path),
                       env={**__import__("os").environ, "PYTHONPATH": str(BASE)},
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    got_base, got_out = r.stdout.strip().splitlines()[:2]
    assert got_base == BASE.as_posix(), (
        f"BASE resolved to {got_base} from cwd {tmp_path} — the cycle would "
        f"read and write outside the repo")
    assert got_out == (BASE / "memory" / "cortex_full_state.json").as_posix()


def test_the_write_target_hangs_off_base_and_not_off_cwd():
    """By AST: no relative path may reach the writer."""
    src = (BASE / "cortex_scanner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "OUT"):
            assert "BASE" in ast.dump(node.value), (
                "OUT no longer derives from BASE — cwd can move the output")
            return
    raise AssertionError("OUT assignment not found")


# ── the wiring, in all three maps ──────────────────────────────────────────

def _beats():
    tree = ast.parse((BASE / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    out = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "beat" and len(n.args) > 1
                and all(isinstance(a, ast.Constant) for a in n.args[:2])):
            out[n.args[0].value] = n.args[1].value
    return out


def test_the_cycle_calls_the_scanner_at_all():
    assert "cortex_scan" in _beats(), (
        "nothing in the cycle calls scan() — the defect this step exists for")


def test_it_runs_after_everything_it_reads():
    """It aggregates the finished cycle: snapshots, trends_latest, axis_history,
    session_*.json (session_update, 21) and development_journal (19)."""
    b = _beats()
    for earlier in ("trend_tracker", "session_update", "cycle_report"):
        assert float(b["cortex_scan"]) > float(b[earlier]), (
            f"cortex_scan runs before {earlier}, whose output it reads")


def test_all_three_step_maps_know_about_it():
    """ITEM 7.1 declared a step in one map and not the other, and the first
    cycle to run it logged an unmapped checkpoint. Three maps, one step."""
    assert "cortex_scan" in _beats()

    phases = json.loads((BASE / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))["phases"]
    g = phases["G_LEARN"]
    assert any(s["name"] == "cortex_scan" for s in g["steps"])
    assert "memory/cortex_full_state.json" in g["produces"]

    from core import cycle_map
    assert any(s[0] == "cortex_scan" for s in cycle_map.STEPS)
    assert cycle_map.resolve("cortex_scan")[0] == "cortex_scan"


# ── staleness signalling ───────────────────────────────────────────────────

def test_the_dashboard_judges_the_date_and_does_not_merely_print_it():
    """cortex_dashboard.html:79 already rendered d.timestamp. A date printed
    without judgement is what let 13 April read as today for 137 days, so the
    page must compute an AGE and mark it once past a threshold."""
    page = (BASE / "cortex_dashboard.html").read_text(encoding="utf-8")
    assert "STALE_HOURS" in page, "no named staleness threshold in the page"
    assert "ageHours" in page or "ageH" in page, "the page never computes an age"
    assert "STALE" in page, "the page never marks a stale file as stale"


def test_the_threshold_is_named_not_buried_as_a_literal():
    page = (BASE / "cortex_dashboard.html").read_text(encoding="utf-8")
    assert "const STALE_HOURS" in page


# ── it still does its job ──────────────────────────────────────────────────

def test_scan_returns_state_without_inventing_scores(monkeypatch, tmp_path):
    """The 34-A guarantee must survive the wiring."""
    monkeypatch.setattr(cortex_scanner, "OUT", tmp_path / "state.json")
    st = cortex_scanner.scan()
    assert "trends" in st and isinstance(st["trends"].get("scores"), dict)
    for axis, v in st["trends"]["scores"].items():
        assert isinstance(v, float) and 0 <= v <= 100
