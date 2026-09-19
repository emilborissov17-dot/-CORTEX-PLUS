# -*- coding: utf-8 -*-
"""test/test_suite_gate_baseline.py — the baseline is a committed file, not the last run.

THE DEFECT, measured 19 September 2026 from memory/suite_runs.jsonl.

tools/suite_gate.py had no baseline file. It compared each run's failed set to the
PREVIOUS record in that ledger, so THE BASELINE WAS WRITTEN BY THE RUN IT JUDGED.
A failure was "new" exactly once; from the next run on it was known, forever, and
no human was ever asked.

Of the 58 recorded runs, 57 are VALID and one is COLLECTION_FAILED. TWENTY of the
VALID runs admitted node ids the previous run did not:

    +19 on 2026-09-03      +23 on 2026-09-06      +30 on 2026-09-08
    +18 on 2026-09-14      +5  on 2026-09-18

That is a ratchet, not a baseline. And the verdict name helped it along: VALID
meant only "the suite executed and no cycle touched the window", yet it was read
every day as "safe to push" — so a run with thirty new failures came back VALID.

WHAT THESE TESTS PIN:
  * a failure absent from test/known_failures.txt makes the run NOT clean, and
    the id is named in the result;
  * a failed set matching the file exactly is clean;
  * a listed test that PASSES is reported, so the debt gets removed rather than
    silently kept;
  * an id in the file that no longer exists is reported, because a line
    protecting nothing is how a real failure hides;
  * a run NEVER writes the baseline — byte-identical before and after.

None of these runs the real suite.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
import suite_gate as sg   # noqa: E402


def _fake_pytest(tmp_path, failed=(), passed=()):
    """A stand-in that prints pytest's -rA short summary and a summary line.

    The file is NAMED fake_pytest.py on purpose: run() decides whether the
    "did it finish" inference applies by looking for "pytest" in the command,
    and a shim that is not recognisable as pytest would skip the very logic
    under test.
    """
    lines = []
    for n in passed:
        lines.append("PASSED %s" % n)
    for n in failed:
        lines.append("FAILED %s" % n)
    lines.append("%d failed, %d passed in 1.23s" % (len(failed), len(passed)))
    script = tmp_path / "fake_pytest.py"
    body = ["import sys"]
    for l in lines:
        body.append("print(%r)" % l)
    body.append("sys.exit(%d)" % (1 if failed else 0))
    script.write_text("\n".join(body) + "\n", encoding="utf-8")
    return [sys.executable, str(script)]


def _baseline(tmp_path, entries):
    p = tmp_path / "known_failures.txt"
    out = ["# seeded by a test", ""]
    for node, why in entries:
        out.append("%s  # %s" % (node, why))
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return p


def _isolated(tmp_path):
    return {"lock": tmp_path / "cycle.lock",
            "heartbeat": tmp_path / "heartbeat.json",
            "last_sealed": tmp_path / "last_sealed.json",
            "runs_path": tmp_path / "suite_runs.jsonl"}


A = "test/test_a.py::test_one"
B = "test/test_b.py::test_two"
C = "test/test_c.py::test_three"


# ── 1. a failure not in the file is not clean, and is named ─────────────────

def test_a_failure_absent_from_the_file_is_not_clean_and_is_named(tmp_path):
    kf = _baseline(tmp_path, [(A, "REAL_DEFECT: known")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A, B]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["outcome"] == sg.RAN_WITH_NEW_FAILURES, entry["outcome"]
    assert entry["new_failures"] == [B]
    assert any(B in r for r in entry["reasons"]), (
        "the new failure was not named in the reasons: %r" % entry["reasons"])
    assert B in sg.format_verdict(entry)


def test_the_old_behaviour_is_gone_a_new_failure_is_never_VALID(tmp_path):
    """THE ONE THAT MATTERS. Before today this exact shape returned VALID and
    read as 'safe to push'."""
    kf = _baseline(tmp_path, [(A, "REAL_DEFECT: known")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A, B, C]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["outcome"] != sg.VALID
    assert sorted(entry["new_failures"]) == sorted([B, C])
    assert "DO NOT push" in sg.format_verdict(entry)


# ── 2. an exact match is clean ──────────────────────────────────────────────

def test_a_failed_set_matching_the_file_exactly_is_clean(tmp_path):
    kf = _baseline(tmp_path, [(A, "LIVE_STATE: moves with the world"),
                              (B, "OBSOLETE: behaviour removed on purpose")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A, B]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["outcome"] == sg.RAN_CLEAN
    assert entry["new_failures"] == []
    assert entry["baseline_size"] == 2


def test_fewer_failures_than_the_file_is_still_clean_but_reported(tmp_path):
    """Green is never a failure, but it is never silent either."""
    kf = _baseline(tmp_path, [(A, "REAL_DEFECT: x"), (B, "REAL_DEFECT: y")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A], passed=[B]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["outcome"] == sg.RAN_CLEAN
    assert entry["baseline_now_green"] == [B]


# ── 3. a listed test that passes is reported ────────────────────────────────

def test_a_baseline_entry_that_passes_is_reported_not_swallowed(tmp_path):
    kf = _baseline(tmp_path, [(A, "REAL_DEFECT: x"), (B, "FLAKY: y")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A], passed=[B]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["baseline_now_green"] == [B]
    assert any("GREEN" in r and B in r for r in entry["reasons"]), entry["reasons"]
    out = sg.format_verdict(entry)
    assert "remove this line from the baseline" in out


# ── 4. an id in the file that no longer exists is reported ──────────────────

def test_an_id_in_the_file_that_no_longer_exists_is_reported(tmp_path):
    """A renamed or deleted test leaves a line that protects nothing, and a line
    protecting nothing is where the next real failure hides."""
    kf = _baseline(tmp_path, [(A, "REAL_DEFECT: x"),
                              ("test/test_gone.py::test_vanished", "OBSOLETE: z")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["baseline_vanished"] == ["test/test_gone.py::test_vanished"]
    assert any("no longer exist" in r for r in entry["reasons"]), entry["reasons"]
    assert "protects nothing" in sg.format_verdict(entry)


def test_a_vanished_id_is_not_confused_with_one_that_simply_passed(tmp_path):
    """Both are 'not in failed'. Collapsing them would report a deleted test as
    a fixed one and quietly drop the line."""
    kf = _baseline(tmp_path, [(A, "x"), (B, "y"), ("test/test_gone.py::t", "z")])
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A], passed=[B]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["baseline_now_green"] == [B]
    assert entry["baseline_vanished"] == ["test/test_gone.py::t"]


# ── 5. a run never writes the baseline ──────────────────────────────────────

def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_a_run_never_writes_the_baseline_file(tmp_path):
    """MECHANICAL, not a promise. The whole defect was a baseline that wrote
    itself, so the file is hashed before and after."""
    kf = _baseline(tmp_path, [(A, "REAL_DEFECT: x")])
    before = _sha(kf)
    sg.run(command=_fake_pytest(tmp_path, failed=[A, B, C], passed=[]),
           write_record=False, known_path=kf, **_isolated(tmp_path))
    assert _sha(kf) == before, "the run modified the baseline file"


def test_not_even_a_clean_run_touches_the_baseline(tmp_path):
    kf = _baseline(tmp_path, [(A, "x"), (B, "y")])
    before = _sha(kf)
    entry = sg.run(command=_fake_pytest(tmp_path, failed=[A, B]),
                   write_record=False, known_path=kf, **_isolated(tmp_path))
    assert entry["outcome"] == sg.RAN_CLEAN
    assert _sha(kf) == before


def test_no_writer_of_the_baseline_exists_in_the_module():
    """Mutation guard: if anything ever opens the baseline for writing, this
    goes red before the behaviour tests can be fooled by a no-op run."""
    src = (REPO / "tools" / "suite_gate.py").read_text(encoding="utf-8")
    for bad in ("KNOWN_FAILURES.write_text", "KNOWN_FAILURES.open(\"w",
                "open(KNOWN_FAILURES", "known_path.write_text"):
        assert bad not in src, "suite_gate writes the baseline: %r" % bad


# ── the seeded file itself ──────────────────────────────────────────────────

def test_the_committed_baseline_parses_and_every_line_carries_a_reason():
    known = sg.load_known_failures()
    assert known, "test/known_failures.txt is empty or missing"
    # THE COUNT IS A TRIPWIRE, not bookkeeping. It moves only in a commit that
    # says why, which is the whole difference between this file and the ledger
    # it replaced: 42 at seeding on 19 Sep, 41 once
    # test_heartbeat_coverage::test_each_beat_reports_the_step_it_is_actually_in
    # went green the same day and its line was removed in the same commit.
    # 42 at seeding on 19 Sep; 41 when test_heartbeat_coverage went green; 39
    # when the two test_consult_free_only entries did, same day, same rule --
    # the line goes in the commit that makes it pass.
    # 42 at seeding; 41 when test_heartbeat_coverage went green; 39 when the two
    # test_consult_free_only entries did; 13 when Half A of the sweep settled the
    # 26 that were never code defects — 15 marked live_state, 2 ENVIRONMENT (one
    # skipped by name, one green after ), 3 OBSOLETE, 4
    # BROKEN_TEST fixed, 2 FLAKY de-coupled from suite residue.
    # 42 at seeding; 41, 39, then 13 when Half A settled the 26 that were never
    # code defects; 6 after Half B verified the thirteen REAL_DEFECT claims one
    # at a time. Seven left the list - three cadence, the quarantine scanner, the
    # blind-producer ratchet, the composite package, the CI network flag. Four
    # CLAIMS TURNED OUT FALSE and were deliberately NOT fixed; two hold but need
    # a decision that is not this sweep's to make.
    assert len(known) == 6, "the baseline changed size, got %d" % len(known)
    missing = sorted(n for n, why in known.items() if not why)
    assert not missing, (
        "these baseline entries carry no reason, which makes them a "
        "dispensation rather than a debt:\n  " + "\n  ".join(missing))


def test_every_committed_baseline_entry_names_a_triage_bucket():
    # CLAIM_FALSE added 19 Sep 2026 by Half B of the sweep: an entry whose
    # triage claim was checked against the code and did not hold. It stays in the
    # baseline because the test is still red, but the line records that the
    # DIAGNOSIS was wrong rather than carrying an unexamined bucket.
    buckets = {"REAL_DEFECT", "OBSOLETE", "LIVE_STATE", "CLAIM_FALSE",
               "BROKEN_TEST", "ENVIRONMENT", "FLAKY", "UNKNOWN"}
    bad = [n for n, why in sg.load_known_failures().items()
           if why.split(":")[0].strip() not in buckets]
    assert not bad, "entries with no recognised bucket: %r" % bad[:5]


def test_a_comment_only_file_yields_no_entries(tmp_path):
    p = tmp_path / "kf.txt"
    p.write_text("# nothing here\n\n   \n# still nothing\n", encoding="utf-8")
    assert sg.load_known_failures(p) == {}


def test_a_missing_baseline_file_is_empty_not_an_error(tmp_path):
    """An absent file must mean 'nothing is accepted', so every failure is new —
    never 'everything is accepted'."""
    assert sg.load_known_failures(tmp_path / "does_not_exist.txt") == {}
