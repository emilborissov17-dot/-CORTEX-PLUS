# -*- coding: utf-8 -*-
"""ITEM 29 — the history is annotated, not rewritten.

ITEM 21 fixed the mechanism. It could not fix the 133 reports already on disk,
every one of which says steps_failed: [] because its writer had no way to say
anything else. A reader who does not know that will read "no failed steps" as a
fact about the cycle rather than a fact about the recorder.

The rule this file enforces is the one that matters: EDITING THOSE 133 RECORDS
IS FORBIDDEN. Rewriting them to state something their writer never knew would be
inventing evidence while cleaning up after a defect about invented evidence. One
annotation is appended beside them and carries the warning.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tools import annotate_phase_reports as ann  # noqa: E402


def _digests(d: pathlib.Path) -> dict:
    return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.glob("*/*.json"))}


_LIVE_BEFORE = _digests(ann.REPORTS_DIR)


def _fixture(tmp_path):
    rd = tmp_path / "phase_reports"
    (rd / "cycleA").mkdir(parents=True)
    (rd / "cycleA" / "G_LEARN.json").write_text(json.dumps(
        {"phase": "G_LEARN", "verdict": "PARTIAL", "steps_failed": [],
         "steps_run": ["feedback_loop"]}), encoding="utf-8")
    (rd / "cycleA" / "D_SCORE.json").write_text(json.dumps(
        {"phase": "D_SCORE", "verdict": "DONE", "steps_failed": []}),
        encoding="utf-8")
    ld = tmp_path / "cycle_logs"
    ld.mkdir()
    (ld / "c.log").write_text(
        "[FAST_CYCLE] feedback_loop -> FAILED: TypeError: boom\n", encoding="utf-8")
    return rd, ld


# ── the rule ───────────────────────────────────────────────────────────────

def test_writing_the_annotation_does_not_touch_one_report(tmp_path):
    rd, ld = _fixture(tmp_path)
    before = _digests(rd)
    ann.append(ann.build(rd, ld), write=True, out=tmp_path / "_A.jsonl")
    assert _digests(rd) == before, "a report was modified — the one forbidden act"


def test_it_appends_exactly_one_record_and_never_a_second(tmp_path):
    rd, ld = _fixture(tmp_path)
    out = tmp_path / "_A.jsonl"
    assert ann.append(ann.build(rd, ld), write=True, out=out)["appended"] is True
    assert ann.append(ann.build(rd, ld), write=True, out=out)["appended"] is False
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_a_dry_run_creates_nothing(tmp_path):
    rd, ld = _fixture(tmp_path)
    out = tmp_path / "_A.jsonl"
    ann.append(ann.build(rd, ld), write=False, out=out)
    assert not out.exists()


# ── what the record has to say ─────────────────────────────────────────────

def test_the_record_distinguishes_could_not_say_from_nothing_failed(tmp_path):
    rd, ld = _fixture(tmp_path)
    rec = ann.build(rd, ld)
    txt = rec["what_steps_failed_means_in_those_reports"]
    assert "could not say otherwise" in txt
    assert "does NOT mean" in txt or "not the same" in txt.lower()


def test_the_record_names_the_mechanism_not_just_the_symptom(tmp_path):
    rd, ld = _fixture(tmp_path)
    d = ann.build(rd, ld)["the_defect"]
    assert "beat() time" in d, "the cause is WHEN step_ok is called"
    assert "step_failed" in d, "and that step_failed had no live caller"


def test_the_record_voids_past_analysis_and_says_where_to_re_derive(tmp_path):
    rd, ld = _fixture(tmp_path)
    ins = ann.build(rd, ld)["instruction"]
    assert "VOID" in ins
    assert "cycle_logs" in ins, "a void instruction with no alternative is a dead end"


def test_the_record_carries_the_gap_between_logs_and_reports(tmp_path):
    """The number that makes it actionable: the logs kept what the reports lost."""
    rd, ld = _fixture(tmp_path)
    rec = ann.build(rd, ld)
    assert rec["evidence_that_survives"]["step_failures_found"] == 1
    assert rec["reports_at_time_of_annotation"]["naming_any_failed_step"] == 0
    assert "1 step failure" in rec["the_gap"]


def test_the_record_flags_the_done_verdicts_as_unverifiable(tmp_path):
    rd, ld = _fixture(tmp_path)
    v = ann.build(rd, ld)["verdicts_now_unverifiable"]
    assert "DONE" in v and "not evidence" in v


# ── the live annotation ────────────────────────────────────────────────────

def test_the_real_annotation_is_on_file_exactly_once():
    assert ann.already_annotated(), (
        "ITEM 29's annotation has not been written to "
        f"{ann.OUT} — the 133 reports carry no warning")
    lines = [l for l in ann.OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [json.loads(l).get("annotation_id") for l in lines]
    assert ids.count(ann.ANNOTATION_ID) == 1


def test_the_real_reports_are_byte_identical_after_this_module_ran():
    after = _digests(ann.REPORTS_DIR)
    assert after == _LIVE_BEFORE, "a live phase report moved during the test run"
    assert len(after) >= 133, f"expected at least 133 reports, found {len(after)}"
