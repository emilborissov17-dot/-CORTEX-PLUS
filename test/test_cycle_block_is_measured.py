"""The vector says what the CYCLE did, not only what the machine felt.

All 7 rows in memory/state_vectors.jsonl carried the same empty block on
27 Aug 2026:

    "cycle": {"flow_score": null, "degraded_steps": null,
              "steps_completed": null, "duration_sec": null}

The 25 sensor dimensions were fine. A lexicon fitted on these points could
describe the laptop's body — temperature, RAM, disk, network — and nothing at
all about the work the night did.

Two causes, neither of which announced itself:

  * fast_cycle_runner calls write() with a cycle_id and a store path. Every
    metric defaulted to None and nothing filled them.
  * the one fallback that existed probed `core.flow_score.latest()`, WHICH DOES
    NOT EXIST. hasattr() returned False, the branch was skipped silently, and a
    missing function looked exactly like a missing measurement. The module has
    compute() and history(); nothing in the repo calls either, and
    memory/flow_score.jsonl has never been written, so history() was empty too.
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import cycle_vector as cv             # noqa: E402
from core import flow_score as fs               # noqa: E402

CONTRACT = {"steps": [
    {"step": "a", "seconds": 10.0, "verdict": "OK"},
    {"step": "b", "seconds": 20.0, "verdict": "OK"},
    {"step": "c", "seconds": 30.0, "verdict": "DEGRADED"},
    {"step": "d", "seconds": 40.0, "verdict": "OK"},
]}


def _contract(tmp_path):
    p = tmp_path / "step_contract_latest.json"
    p.write_text(json.dumps(CONTRACT), encoding="utf-8")
    return p


def _lock(tmp_path, age_sec=6543.2):
    p = tmp_path / "cycle.lock"
    started = (datetime.now(timezone.utc) - timedelta(seconds=age_sec)).isoformat()
    p.write_text(json.dumps({"pid": 1, "cycle_id": "c-probe",
                             "started_utc": started}), encoding="utf-8")
    return p


def test_the_four_fields_are_measured_not_none(tmp_path):
    """THE HEADLINE. Every row on disk had all four as null."""
    m = cv.cycle_metrics(cycle_id="c-probe", lock_path=_lock(tmp_path),
                         contract=_contract(tmp_path))
    assert [k for k, v in m.items() if v is None] == [], m
    assert m["steps_completed"] == 3      # 4 steps, one DEGRADED
    assert m["degraded_steps"] == 1
    assert m["flow_score"] > 0
    assert 6543.0 < m["duration_sec"] < 6600.0


def test_steps_completed_counts_what_landed_not_what_ran(tmp_path):
    """A DEGRADED step ran. It did not complete anything worth having."""
    m = cv.cycle_metrics(cycle_id="c", lock_path=_lock(tmp_path),
                         contract=_contract(tmp_path))
    assert m["steps_completed"] == 3
    assert m["steps_completed"] != len(CONTRACT["steps"]), (
        "steps_completed must not be steps_total — the lexicon would read a "
        "degraded night as a complete one")


def test_duration_comes_from_the_lock_because_the_ledger_does_not_know_yet(tmp_path):
    """The vector is assembled BEFORE _seal_cycle_record() writes the seal, so
    the ledger has no duration for this cycle at this moment. The lock does."""
    m = cv.cycle_metrics(cycle_id="c", lock_path=_lock(tmp_path, age_sec=120.0),
                         contract=_contract(tmp_path))
    assert 119.0 < m["duration_sec"] < 180.0


def test_an_explicit_value_still_wins(tmp_path):
    """Filling gaps must never overwrite what the caller measured."""
    m = cv.cycle_metrics(cycle_id="c", duration_sec=42.0, steps_completed=7,
                         degraded_steps=0, flow_score=9.9,
                         lock_path=_lock(tmp_path), contract=_contract(tmp_path))
    assert (m["duration_sec"], m["steps_completed"],
            m["degraded_steps"], m["flow_score"]) == (42.0, 7, 0, 9.9)


def test_a_missing_lock_leaves_duration_none_rather_than_zero(tmp_path):
    """None is 'not measured'. A 0.0 in this file is permanent and the lexicon
    cannot tell it from a real reading — the store's whole rule."""
    m = cv.cycle_metrics(cycle_id="c", lock_path=tmp_path / "nope.lock",
                         contract=_contract(tmp_path))
    assert m["duration_sec"] is None


def test_the_probe_for_a_function_that_does_not_exist_is_gone():
    """core.flow_score has never had latest(). The old fallback asked for it,
    hasattr said False, and the failure was invisible."""
    assert not hasattr(fs, "latest"), (
        "flow_score.latest() now exists — revisit cycle_metrics, which was "
        "written knowing it did not")
    src = (REPO / "core" / "cycle_vector.py").read_text(encoding="utf-8-sig")
    assert "fs.latest" not in src and 'hasattr(fs, "latest")' not in src


def test_a_written_vector_carries_the_block(tmp_path):
    """End to end, through write(), on the real assemble path."""
    store = tmp_path / "state_vectors.jsonl"
    m = cv.cycle_metrics(cycle_id="c-probe", lock_path=_lock(tmp_path),
                         contract=_contract(tmp_path))
    rec = cv.write(cycle_id="c-probe", store_path=store, metrics=m,
                   ledger_rows=[])
    assert rec["written"] is True, rec["why"]
    row = json.loads(store.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row["cycle"]) == {"flow_score", "degraded_steps",
                                 "steps_completed", "duration_sec"}
    assert [k for k, v in row["cycle"].items() if v is None] == []


def test_the_seal_records_how_much_of_the_night_landed():
    """The COMMAND 28 gap: CYCLE_FINISHED carried a duration and no step count,
    so a cycle that completed 4 of 31 steps sealed identically to one that
    completed all 31. ast, because this is a claim about a CALL's arguments."""
    import ast
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8-sig"))
    seal = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_seal_cycle_record")
    calls = [n for n in ast.walk(seal)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_el_append"]
    assert calls, "_seal_cycle_record no longer appends to the ledger"
    kwargs = {k.arg for c in calls for k in c.keywords}
    for field in ("duration_sec", "steps_completed", "degraded_steps"):
        assert field in kwargs, f"CYCLE_FINISHED is sealed without {field}"
