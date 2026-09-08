#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_refusal_leaves_an_experience.py

THE DEFECT THIS GUARDS
-----------------------
memory/runtime_experiences.json is what the system remembers about itself. Three
modules read it: memory/body_scan.py:162 (counts data["experiences"]),
memory/existence_model.py:72 (reads data["summary"]["error_count"] into
pain_score) and core/phase_evidence.py:470 (counts the same list).

Its only writer was memory/runtime_telemetry.record_experience(), and that
function's only caller sat INSIDE agents/core/self_modifier.run(). The notary has
refused self_modifier 35 times out of 35 since 2026-08-17 — a refusal happens
BEFORE run() — so the writer never fired once. Measured 2026-09-08: the newest
record inside the file is 2026-06-21T13:56:57Z. Seventy-nine days in which the
system was stopped from modifying itself every night and remembered none of it.

The most consequential thing this system does is refuse to change itself. It has
to leave a trace with a CAUSE, written where the decision is made.

THE FORBIDDEN FALLBACK, PINNED
-------------------------------
The cheap way to make this file "fresh" is a placeholder — a synthetic entry, a
heartbeat record, anything with a new mtime. That is forbidden: an mtime is not
a memory. test_the_record_carries_the_real_reason_not_a_canned_one puts a
unique string through the gate and demands it come out the other end verbatim,
so a canned or templated record cannot pass.

    venv\\Scripts\\python.exe -m pytest test/test_refusal_leaves_an_experience.py -v
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT = "memory/runtime_experiences.json"

# The 2026-09-08 refusal, verbatim from memory/night_events.jsonl.
NOTARY_WHY = ("level_1 (минимално) — explicit ceiling for 'self_modifier': this step "
              "is capped at level_1 (минимално) by core/notary.MAX_LEVEL regardless "
              "of its own vector (level_3 (пълно)).")


@pytest.fixture
def gate(tmp_path, monkeypatch):
    """The runner's gate, with every live write redirected into tmp_path.

    NOTHING here may touch the real memory/ tree: a cycle may be running while
    these tests do, and a test that writes into live state is the defect it is
    supposed to be catching, one level up.
    """
    import fast_cycle_runner as runner
    from memory import runtime_telemetry as rt

    tel = tmp_path / "memory" / "runtime_experiences.json"
    tel.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rt, "TEL_PATH", tel)

    events: list = []
    monkeypatch.setattr(runner, "_refusal_event",
                        lambda step, gate, why: events.append((step, gate, why)))

    from core import phase_tracker
    monkeypatch.setattr(phase_tracker, "note_refusal",
                        lambda step, gate, why: None)

    return runner, tel, events


def _records(tel: pathlib.Path) -> list:
    if not tel.exists():
        return []
    return json.loads(tel.read_text(encoding="utf-8"))["experiences"]


# ---------------------------------------------------------------------------
# (a) THE MUTATION TEST — delete the gate-level write and this goes red
# ---------------------------------------------------------------------------

def test_a_notary_refusal_leaves_a_new_experience_with_its_cause(gate):
    """Remove the record_refusal() call from fast_cycle_runner._refused and this
    fails: no new record appears at all.

    It cannot be satisfied by anything self_modifier.run() does, because run()
    is exactly what a refusal prevents.
    """
    runner, tel, _ = gate
    before = len(_records(tel))

    assert runner._refused("self_modifier", "notary", NOTARY_WHY,
                           prev_step="self_observer") is False

    after = _records(tel)
    assert len(after) == before + 1, (
        "\n  A REFUSAL LEFT NO TRACE.\n"
        "  The notary stopped self_modifier and memory/runtime_experiences.json\n"
        "  gained no record. The only writer used to live inside\n"
        "  self_modifier.run(), which a refusal prevents from starting — that is\n"
        "  why the write has to happen AT THE GATE, in\n"
        "  fast_cycle_runner._refused(). 79 days of nightly refusals were lost\n"
        "  to exactly this.\n")

    rec = after[-1]
    assert rec["event_type"] == "REFUSAL"
    assert rec["data"]["step"] == "self_modifier"
    assert rec["data"]["gate"] == "notary"
    assert rec["data"]["reason"] == NOTARY_WHY
    assert rec["data"]["prev_step"] == "self_observer"
    assert rec["data"]["level"] == 1, "the notary's level was not carried"
    assert rec["data"]["level_source"] == "parsed_from_gate_reason"
    assert rec["timestamp"], "a cause with no time is not cause and effect"


def test_the_record_carries_the_real_reason_not_a_canned_one(gate):
    """THE FORBIDDEN FALLBACK. A placeholder or templated entry cannot carry a
    string it has never seen, so a unique reason must survive the round trip."""
    runner, tel, _ = gate
    unique = f"level_2 (намалено) — {uuid.uuid4()}"
    runner._refused("execute_patches", "notary", unique)
    rec = _records(tel)[-1]
    assert rec["data"]["reason"] == unique, (
        "the stored reason is not the reason the gate gave; a synthetic or "
        "templated record cannot stand in for the real refusal")
    assert rec["data"]["level"] == 2


def test_a_gate_that_reports_no_level_says_so_instead_of_guessing_zero(gate):
    """level_0 means "unknown provenance" to the notary and is a real reading.
    A gate that never reports a level must not be recorded as if it had."""
    runner, tel, _ = gate
    runner._refused("github_publish", "human_channel", "the channel is dead")
    rec = _records(tel)[-1]
    assert rec["data"]["level"] is None
    assert rec["data"]["level_source"] == "not_reported_by_this_gate"


def test_the_gate_still_refuses_when_the_recorder_breaks(gate, monkeypatch, capsys):
    """FAIL-OPEN, AND LOUD. The record must never be able to turn a refusal into
    a crash — but losing it must be visible, not swallowed."""
    runner, tel, _ = gate
    from memory import runtime_telemetry as rt

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(rt, "record_refusal", _boom)
    assert runner._refused("self_modifier", "notary", NOTARY_WHY) is False
    out = capsys.readouterr().out
    assert "runtime_experiences.json" in out and "OSError" in out, (
        "the recorder failed silently: " + out)


# ---------------------------------------------------------------------------
# (b) the grading, end to end
# ---------------------------------------------------------------------------

def test_f_self_grades_runtime_experiences_WRITTEN_under_a_refusal(gate, tmp_path):
    """The point of shipping the move and the write together.

    self_modifier is refused, so memory/improvement_proposals.json is REFUSED and
    exempt (commit 0ae4bb4) — but runtime_experiences.json is WRITTEN, because
    the gate itself produced it. If the write were absent, this artifact would be
    exempted too and the 79-day silence would be graded DONE forever.
    """
    from core.phase_report import PhaseReport, REFUSED

    runner, tel, _ = gate
    cfg = json.loads((REPO / "config" / "cycle_phases.json").read_text(encoding="utf-8"))
    promised = cfg["phases"]["F_SELF"]["produces"]
    assert ARTIFACT in promised, "F_SELF must promise it after the attribution move"

    pf = tmp_path / "phases.json"
    pf.write_text(json.dumps({"phases": {"F_SELF": {
        "purpose": "t", "index_range": ["18", "19"], "steps": [], "requires": [],
        "produces": promised}}}), encoding="utf-8")

    # every other promised artifact present but old, as on a real refused night
    old = (datetime.now(timezone.utc) - timedelta(hours=11)).timestamp()
    for rel in promised:
        if rel == ARTIFACT:
            continue
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (old, old))

    with PhaseReport("F_SELF", "cid", base_dir=tmp_path, phases_file=pf) as rep:
        rep.step_refused("self_modifier", "notary", NOTARY_WHY)
        runner._refused("self_modifier", "notary", NOTARY_WHY)

    report = json.loads((tmp_path / "memory" / "phase_reports" / "cid" /
                         "F_SELF.json").read_text(encoding="utf-8"))
    rows = {r["path"]: r for r in report["produces_check"]}

    assert rows[ARTIFACT]["state"] == "WRITTEN", (
        "the gate's refusal record did not land inside the phase window; "
        "F_SELF would report DONE while remembering nothing: " + str(rows[ARTIFACT]))
    assert rows[ARTIFACT]["refused_by_gate"] is None
    assert rows["memory/improvement_proposals.json"]["state"] == REFUSED


def test_e_propose_no_longer_promises_what_it_never_wrote():
    """No step of E_PROPOSE has ever written this file. Verified in the code:
    agents/core/self_observer.py writes development_journal.json and
    improvement_proposals.json, and nothing else."""
    cfg = json.loads((REPO / "config" / "cycle_phases.json").read_text(encoding="utf-8"))
    assert ARTIFACT not in cfg["phases"]["E_PROPOSE"]["produces"]
    assert ARTIFACT in cfg["phases"]["F_SELF"]["produces"]

    src = (REPO / "agents" / "core" / "self_observer.py").read_text(encoding="utf-8")
    assert "runtime_experiences" not in src, (
        "self_observer now mentions the artifact; re-check the attribution")


# ---------------------------------------------------------------------------
# (c) structural: all three cards agree, read from the code
# ---------------------------------------------------------------------------

def _cycle_map_produces() -> dict:
    """{step: [paths]} parsed out of core/cycle_map.STEPS as an AST literal.

    Reads the code, never prose and never the imported module: a test that
    imports the table cannot notice the table being replaced by something that
    computes the same answer at runtime.
    """
    tree = ast.parse((REPO / "core" / "cycle_map.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "STEPS"):
            out = {}
            for elt in node.value.elts:
                name = elt.elts[0].value
                out.setdefault(name, []).extend(
                    c.value for c in elt.elts[3].elts)
            return out
    raise AssertionError("STEPS not found in core/cycle_map.py")


def test_all_three_cards_attribute_the_artifact_to_self_modifier():
    """cycle_map, cycle_phases and the note must agree, or the next reader has
    to work out which one is real."""
    produces = _cycle_map_produces()

    assert ARTIFACT in produces["self_modifier"], (
        "core/cycle_map.py still does not credit self_modifier — the only step "
        "whose code path reaches the writer")
    assert ARTIFACT not in produces.get("self_observer", []), (
        "core/cycle_map.py still promises it from self_observer, which has never "
        "written it")

    cfg = json.loads((REPO / "config" / "cycle_phases.json").read_text(encoding="utf-8"))
    assert ARTIFACT in cfg["phases"]["F_SELF"]["produces"]
    assert ARTIFACT not in cfg["phases"]["E_PROPOSE"]["produces"]

    note = cfg.get("_g_learn_attribution_note", "")
    assert "runtime_experiences.json <- self_modifier" in note, (
        "the 2026-08-28 note still names self_observer as the writer")
    assert "_runtime_experiences_attribution_note" in cfg, (
        "the correction was made silently; the note that explains it is gone")


def test_the_writer_the_cards_now_name_is_the_writer_the_code_has():
    """The claim under test is 'self_modifier can reach the writer'. Assert it
    against the import graph, not against a comment."""
    src = (REPO / "agents" / "core" / "self_modifier.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imports_writer = any(
        isinstance(n, ast.ImportFrom) and n.module == "memory.runtime_telemetry"
        for n in ast.walk(tree))
    assert imports_writer, (
        "self_modifier no longer imports memory.runtime_telemetry; the "
        "attribution in all three cards is now false again")

    tel = ast.parse((REPO / "memory" / "runtime_telemetry.py").read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tel) if isinstance(n, ast.FunctionDef)}
    assert {"record_experience", "record_refusal"} <= names


def test_the_gate_write_is_wired_and_not_merely_available():
    """AST, not grep-for-a-word: fast_cycle_runner._refused must actually call
    record_refusal. Deleting the call is the mutation test (a) catches; this
    catches it being moved somewhere that never runs."""
    tree = ast.parse((REPO / "fast_cycle_runner.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_refused")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "record_refusal" in called, (
        "_refused no longer writes the experience; a refusal will again leave "
        "no memory")
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), (
        "_refused is not fail-open around the recorder")


# ---------------------------------------------------------------------------
# (d) the readers keep working, and a refusal is not an injury
# ---------------------------------------------------------------------------

def test_the_three_readers_still_find_the_shape_they_expect(gate):
    """body_scan reads data["experiences"] (a list); existence_model reads
    data["summary"]["error_count"]; phase_evidence counts the same list."""
    runner, tel, _ = gate
    runner._refused("self_modifier", "notary", NOTARY_WHY)
    data = json.loads(tel.read_text(encoding="utf-8"))
    assert isinstance(data["experiences"], list) and data["experiences"]
    assert isinstance(data["summary"]["error_count"], int)
    assert isinstance(data["summary"]["total_experiences"], int)


def test_a_refusal_does_not_score_as_pain_or_drag_the_success_rate_down(gate):
    """THE FAILURE PATH, ASKED FOR FIRST. memory/existence_model.py adds
    summary.error_count straight into pain_score and get_self_feeling() reads
    success_rate_pct. Count a refusal as an ERROR and containment working reads
    as the system breaking — one point of pain per night for doing the right
    thing, and a success rate walking to 0%."""
    runner, tel, _ = gate
    from memory.runtime_telemetry import record_experience

    record_experience("SUCCESS", {"message": "a real success"})
    for _ in range(20):
        runner._refused("self_modifier", "notary", NOTARY_WHY)

    summary = json.loads(tel.read_text(encoding="utf-8"))["summary"]
    assert summary["error_count"] == 0, (
        "refusals are being counted as errors; existence_model.pain_score will "
        "rise by one every night the gate does its job")
    assert summary["refusal_count"] == 20
    assert summary["success_rate_pct"] == 100.0, (
        "refusals are in the success-rate denominator; a perfectly contained "
        "system reports as a failing one")
    assert summary["last_refusal"]["step"] == "self_modifier"
    assert summary["last_refusal"]["gate"] == "notary"


def test_the_record_survives_a_body_that_cannot_be_read(gate, monkeypatch):
    """psutil.open_files() raises PermissionError routinely on Windows. When the
    only evidence of a refusal is this record, a missing vital sign must cost a
    null, never the memory."""
    runner, tel, _ = gate
    from memory import runtime_telemetry as rt

    class _Boom:
        def __init__(self, *a, **k):
            raise OSError("access denied")

    monkeypatch.setattr(rt, "psutil", type("P", (), {"Process": _Boom}))
    runner._refused("self_modifier", "notary", NOTARY_WHY)
    rec = _records(tel)[-1]
    assert rec["event_type"] == "REFUSAL"
    assert rec["body_state"]["ram_mb"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
