"""One cycle, one window. The past goes to disk, not into the needle.

_append_report() never reset. It dropped the previous entry for a label and kept
the last 200, so memory/step_contract_latest.json was "the latest run of each
step label, WHENEVER it happened" — not a cycle. A step that stopped running
three nights ago still sat in the window, still counted toward the flow score,
and nothing said so. Every consumer calling it "this cycle" was wrong, the
OVERVIEW needle included.

The history is not destroyed to make the window honest. It is FILED, under the
id of the cycle it came from, before the new cycle's first step.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import step_contract as sc  # noqa: E402


def _window(path, cycle_id, steps):
    path.write_text(json.dumps({"cycle_id": cycle_id, "ts": "2026-08-27T00:00:00+00:00",
                                "steps": steps}, ensure_ascii=False),
                    encoding="utf-8")


def _rows(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_the_second_cycle_window_holds_only_the_second_cycle(tmp_path):
    """THE HEADLINE, with two synthetic cycles."""
    report = tmp_path / "step_contract_latest.json"
    archive = tmp_path / "steps"

    first = [{"step": "alpha", "seconds": 10.0, "verdict": "OK"},
             {"step": "beta", "seconds": 20.0, "verdict": "DEGRADED"}]
    _window(report, "CYCLE-1", first)

    out = sc.open_cycle("CYCLE-2", report_path=report, archive_dir=archive)

    assert out["archived"] == 2
    assert out["previous_cycle_id"] == "CYCLE-1"

    blob = json.loads(report.read_text(encoding="utf-8"))
    assert blob["cycle_id"] == "CYCLE-2"
    assert blob["steps"] == [], (
        "the new cycle's window still carries the previous cycle's steps — this "
        "is the defect: the window was never a cycle")

    filed = archive / "CYCLE-1_steps.jsonl"
    assert filed.exists(), "the first cycle's rows were destroyed, not filed"
    assert [r["step"] for r in _rows(filed)] == ["alpha", "beta"]


def test_the_first_cycles_rows_are_on_disk_under_its_own_id(tmp_path):
    """Filed under the cycle they CAME FROM, never the one now starting."""
    report = tmp_path / "r.json"
    archive = tmp_path / "steps"
    _window(report, "CYCLE-A", [{"step": "one", "seconds": 1.0, "verdict": "OK"}])
    sc.open_cycle("CYCLE-B", report_path=report, archive_dir=archive)

    assert (archive / "CYCLE-A_steps.jsonl").exists()
    assert not (archive / "CYCLE-B_steps.jsonl").exists(), (
        "the previous cycle's rows were filed under the NEW cycle's id, which "
        "is worse than not filing them: it is a false attribution")


def test_steps_appended_after_opening_belong_to_the_new_cycle(tmp_path):
    """The window keeps its id across appends, so it can say whose it is."""
    report = tmp_path / "r.json"
    archive = tmp_path / "steps"
    _window(report, "OLD", [{"step": "gone", "seconds": 1.0, "verdict": "OK"}])
    sc.open_cycle("NEW", report_path=report, archive_dir=archive)

    with sc.StepContract("fresh", report_path=report,
                         baseline_path=tmp_path / "baseline.json") as c:
        pass

    blob = json.loads(report.read_text(encoding="utf-8"))
    assert blob["cycle_id"] == "NEW", (
        "the window lost its cycle id on the first append, so nothing can say "
        "which cycle it describes")
    assert [s["step"] for s in blob["steps"]] == ["fresh"]
    assert "gone" not in json.dumps(blob)


def test_a_window_with_no_cycle_id_is_filed_as_such_not_misattributed(tmp_path):
    """Every window written before this change carries no id.

    Filing those under the NEW cycle would invent a fact. They are filed under a
    name that says plainly they predate the change.
    """
    report = tmp_path / "r.json"
    archive = tmp_path / "steps"
    report.write_text(json.dumps({"ts": "2026-08-27T01:02:03+00:00",
                                  "steps": [{"step": "legacy", "seconds": 5.0,
                                             "verdict": "OK"}]}),
                      encoding="utf-8")
    out = sc.open_cycle("CYCLE-NEW", report_path=report, archive_dir=archive)

    assert out["previous_cycle_id"] is None
    filed = list(archive.glob("*.jsonl"))
    assert len(filed) == 1
    assert "pre-cycle-id" in filed[0].name, (
        f"a window with no id was filed as {filed[0].name} — it must not be "
        f"attributed to a cycle it did not come from")


def test_an_empty_window_archives_nothing_and_says_so(tmp_path):
    report = tmp_path / "r.json"
    archive = tmp_path / "steps"
    _window(report, "C", [])
    out = sc.open_cycle("D", report_path=report, archive_dir=archive)
    assert out["archived"] == 0
    assert "already empty" in out["why"]
    assert not archive.exists() or not list(archive.glob("*.jsonl"))


def test_opening_never_raises_even_on_an_unreadable_window(tmp_path):
    """A cycle must not die because it could not archive."""
    report = tmp_path / "r.json"
    report.write_text("{ this is not json", encoding="utf-8")
    out = sc.open_cycle("C", report_path=report, archive_dir=tmp_path / "steps")
    assert out["cycle_id"] == "C"
    blob = json.loads(report.read_text(encoding="utf-8"))
    assert blob["steps"] == []


def test_archiving_is_append_only_across_repeated_opens(tmp_path):
    """Two windows from the same cycle land in one file, not one overwriting."""
    report = tmp_path / "r.json"
    archive = tmp_path / "steps"
    _window(report, "SAME", [{"step": "a", "seconds": 1.0, "verdict": "OK"}])
    sc.open_cycle("NEXT", report_path=report, archive_dir=archive)
    _window(report, "SAME", [{"step": "b", "seconds": 1.0, "verdict": "OK"}])
    sc.open_cycle("NEXT2", report_path=report, archive_dir=archive)

    rows = _rows(archive / "SAME_steps.jsonl")
    assert [r["step"] for r in rows] == ["a", "b"]


def test_the_runner_opens_the_window_at_boot():
    """ast: the reset has to be CALLED, not merely available.

    The 2026-07-14 lesson in this repo: a constant nothing produces is not
    wiring. The same applies to a function nothing calls.
    """
    import ast
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8-sig"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id in ("_open_window", "open_cycle")]
    assert calls, (
        "fast_cycle_runner never opens the step window, so it still accumulates "
        "across nights and the needle still measures the wrong thing")
