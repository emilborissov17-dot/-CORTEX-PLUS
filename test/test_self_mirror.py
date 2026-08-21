"""
The mirror: self-observation is a SENSE, not an axis of the goal.

Two things are guarded here, and they are different in kind.

1. THE CALIBRATION IS CORRECT ON REAL, CAPTURED EVIDENCE.
   test/fixtures/mirror_cycle_2026-08-21/ holds the VERBATIM slice of
   memory/brain_step_log.jsonl and memory/step_contract_latest.json produced by
   the cycle of 21 August 2026 (started 2026-08-20T21:33Z, sealed
   2026-08-21T00:31Z). Nothing in it is reconstructed. On that evidence the
   local 3B judge declared "the previous step failed" seven times on 21 August
   UTC — self_observer, feedback_loop, session_update, daily_analysis,
   data_scout, metta_column and brain_relay — while the step contract recorded
   that each of those steps touched between 2 and 9 files and raised nothing.
   Those seven MUST land in the false-alarm count. If a refactor ever silently
   stops counting them, this fails.

2. NOTHING FROM THE MIRROR REACHES THE COMPOSITE.
   That is the whole reason GENERAL_SELF_REVIEW left the goal tree. A mirror
   that feeds the score it is meant to describe re-creates the defect one layer
   down, so the guarantee is asserted mechanically against the files that
   actually compute the composite.
"""
from __future__ import annotations

import json
import pathlib

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = BASE / "test" / "fixtures" / "mirror_cycle_2026-08-21"
STEP_LOG = FIXTURE / "brain_step_log.jsonl"
CONTRACT = FIXTURE / "step_contract_latest.json"

from core import self_mirror as sm  # noqa: E402

# The seven, named. They are the deliverable of this test, not an incidental count.
THE_SEVEN = {
    "self_observer", "feedback_loop", "session_update", "daily_analysis",
    "data_scout", "metta_column", "brain_relay",
}


def _cal() -> dict:
    assert FIXTURE.is_dir(), (
        f"missing {FIXTURE.relative_to(BASE)} — this guard cannot run without the "
        "captured evidence it was written against."
    )
    return sm.calibration(step_log_path=STEP_LOG, contract_path=CONTRACT)


# --------------------------------------------------------------------------- #
# (a) the classifier — every cell of the table, plus its refusals
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("said,evidence,expected", [
    (False, sm.WORKED, sm.FALSE_ALARM),
    (False, sm.FAILED, sm.JUSTIFIED_DOUBT),
    (True, sm.FAILED, sm.MISSED_FAILURE),
    (True, sm.WORKED, sm.CONFIRMED),
    (False, sm.UNDECIDABLE, sm.UNDECIDABLE),
    (True, sm.UNDECIDABLE, sm.UNDECIDABLE),
    (None, sm.WORKED, sm.UNDECIDABLE),
    (None, sm.FAILED, sm.UNDECIDABLE),
])
def test_every_cell_of_the_calibration_table(said, evidence, expected):
    assert sm.classify(said, evidence) == expected


@pytest.mark.parametrize("record,expected", [
    ({"verdict": "OK", "touched_count": 3}, sm.WORKED),
    ({"verdict": "NO_EFFECT", "touched_count": 0}, sm.FAILED),
    ({"verdict": "MISSING", "touched_count": 0}, sm.FAILED),
    ({"verdict": "RAISED", "touched_count": 0}, sm.FAILED),
    ({"verdict": "OK", "touched_count": 3, "error": "boom"}, sm.FAILED),
    ({"verdict": "UNKNOWN", "touched_count": 5}, sm.WORKED),
    ({"verdict": "UNKNOWN", "touched_count": 0}, sm.UNDECIDABLE),
    ({}, sm.UNDECIDABLE),
])
def test_the_footprint_is_read_conservatively(record, expected):
    assert sm.footprint_verdict(record) == expected


def test_a_warming_up_step_with_no_footprint_is_never_called_a_failure():
    """NEGATIVE CONTROL. During warm-up the contract has no baseline. Turning
    'I cannot tell' into 'it failed' would manufacture justified doubts out of
    nothing and make the judge look better than it is."""
    assert sm.footprint_verdict({"verdict": "UNKNOWN", "touched_count": 0}) != sm.FAILED
    assert sm.classify(False, sm.UNDECIDABLE) != sm.JUSTIFIED_DOUBT


# --------------------------------------------------------------------------- #
# (b) label resolution — the beat name and the contract label do not always match
# --------------------------------------------------------------------------- #

def test_the_beat_name_resolves_to_the_contract_label():
    """fast_cycle_runner beats `session_update` and wraps the same step as
    `session_updater`. Without this, one real judgement per cycle is lost."""
    labels = {"session_updater", "daily_analysis", "data_scout"}
    assert sm.resolve_label("session_update", labels) == "session_updater"
    assert sm.resolve_label("daily_analysis", labels) == "daily_analysis"
    assert sm.resolve_label("no_such_step", labels) is None


def test_an_ambiguous_prefix_refuses_rather_than_guesses():
    """NEGATIVE CONTROL. Two candidates must yield no pairing: calibrating a
    judgement against the WRONG step is worse than not calibrating it."""
    assert sm.resolve_label("data", {"data_scout", "data_load"}) is None


# --------------------------------------------------------------------------- #
# (c) the captured cycle — the seven false alarms
# --------------------------------------------------------------------------- #

def test_the_seven_false_alarms_of_21_august_are_counted():
    cal = _cal()
    on_21 = {r["about_step"] for r in cal["rows"]
             if r["ts"].startswith("2026-08-21") and r["verdict"] == sm.FALSE_ALARM}
    assert THE_SEVEN <= on_21, (
        "the seven steps the judge wrongly declared failed on 21 Aug are no longer "
        f"all counted as false alarms. missing: {sorted(THE_SEVEN - on_21)}"
    )
    assert cal["false_alarms"] >= len(THE_SEVEN)


def test_each_of_the_seven_has_a_footprint_that_contradicts_the_judge():
    """The claim is not 'the judge was wrong'; it is 'the disk says otherwise'.
    Every one of the seven must carry the evidence that overrules it."""
    rows = {r["about_step"]: r for r in _cal()["rows"]
            if r["ts"].startswith("2026-08-21")}
    for step in sorted(THE_SEVEN):
        r = rows[step]
        assert r["brain_said_ok"] is False
        assert r["footprint"] == sm.WORKED
        assert (r["touched_count"] or 0) > 0, (
            f"{step} was called a false alarm without a footprint to prove it")
        assert r["contract_verdict"] is not None


def test_the_judge_is_not_uniformly_overruled():
    """NEGATIVE CONTROL for the calibration itself. If every pairing came back
    FALSE_ALARM the classifier would be a constant, not a measurement. The
    captured cycle contains at least one CONFIRMED judgement (`deduction` on
    `goal_score_calculator`), and it must survive."""
    cal = _cal()
    assert cal["confirmed"] >= 1, (
        "not one judgement was confirmed — the classifier has degenerated into "
        "a constant")
    verdicts = {r["verdict"] for r in cal["rows"]}
    assert len(verdicts) > 1


def test_unpaired_judgements_are_reported_not_dropped():
    """A judgement the contract cannot speak to is UNDECIDABLE and visible.
    Silently dropping it would flatter the false-alarm rate."""
    cal = _cal()
    assert cal["undecidable"] > 0
    assert cal["judgements_paired"] + cal["undecidable"] == len(cal["rows"])


def test_the_rate_is_computed_over_paired_judgements_only():
    cal = _cal()
    expected = round(cal["false_alarms"] / cal["judgements_paired"], 3)
    assert cal["false_alarm_rate"] == expected


# --------------------------------------------------------------------------- #
# (d) the wall: nothing from the mirror reaches the composite
# --------------------------------------------------------------------------- #

COMPOSITE_SOURCES = (
    "goal_score_calculator.py",
    "cortex_scoring_engine.py",
    "core/measurement_honesty.py",
)

MIRROR_TOKENS = ("self_mirror", "self_mirror_latest", "self_mirror_log")


@pytest.mark.parametrize("rel", COMPOSITE_SOURCES)
def test_no_composite_source_reads_the_mirror(rel):
    p = BASE / rel
    if not p.exists():
        pytest.skip(f"{rel} not present in this checkout")
    text = p.read_text(encoding="utf-8")
    hits = [t for t in MIRROR_TOKENS if t in text]
    assert not hits, (
        f"{rel} references {hits} — self-observation must never enter the number "
        "it is supposed to describe. That is why GENERAL_SELF_REVIEW was retired.")


def test_general_self_review_is_out_of_the_goal_tree():
    cfg = json.loads((BASE / "config" / "target_config.json").read_text(encoding="utf-8"))
    axes = {a for branch, body in cfg.items() if not branch.startswith("_")
            for a in body}
    assert "GENERAL_SELF_REVIEW" not in axes, (
        "the axis is back in the goal tree — the mirror and the axis cannot both exist")


def test_the_mirror_writes_only_its_own_files(tmp_path):
    """The mirror is a describer. Its write() touches exactly two paths."""
    latest = tmp_path / "self_mirror_latest.json"
    log = tmp_path / "self_mirror_log.jsonl"
    mirror = {"ts": "2026-08-21T00:00:00+00:00",
              "calibration": _cal(), "debriefs": {"accepted": [], "rejected": []}}
    sm.write(mirror, latest=latest, log=log)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "self_mirror_latest.json", "self_mirror_log.jsonl"]
    row = json.loads(log.read_text(encoding="utf-8").strip())
    assert row["false_alarms"] == mirror["calibration"]["false_alarms"]


def test_build_does_not_write():
    """NEGATIVE CONTROL. build() must be pure — the micro-cycle calls it to
    LOOK, and a look that mutates state cannot be used to observe an experiment."""
    before = sm.LATEST.stat().st_mtime if sm.LATEST.exists() else None
    sm.build()
    after = sm.LATEST.stat().st_mtime if sm.LATEST.exists() else None
    assert before == after
