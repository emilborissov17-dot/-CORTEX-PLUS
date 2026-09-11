# -*- coding: utf-8 -*-
"""
test/test_repeated_failure_alert.py — ITEM 70: a step that says FAILED two nights
running must ALERT.

Kimi, 3 Sep: "Трябва да спре моделът 'логнал съм FAILED, значи съм си свършил
работата'." merkle_to_training failed on six consecutive nights and the only record
was a line in a log nobody reads to the end. sensorium_ingest did the same and was
found 17 days late.

TWO BIASES, DOUBLE DEFENSE (claude/NORM_TWO_BIASES_DOUBLE_DEFENSE_7SEP.md):

  BIAS 1, helpfulness: alert on SOMETHING, so the detector looks alive. The
  explicit NO-OUTPUT SUCCESS here: {} / no need is the normal and desirable answer.
  Fewer than two logs, one bad night, two nights with DIFFERENT failing steps — all
  produce nothing, and that is correct. The forbidden fallback is a need raised
  from a single night, which is how a channel gets muted.

  BIAS 2, least resistance: detect it from a status file or from memory instead of
  from the logs. The thing being detected is a subsystem whose own report of itself
  is wrong, so only memory/cycle_logs/ can be the source. A second copy of the
  '-> FAILED' parser would be the same defect in another place, so the parser is
  self_forecast's and there is exactly one.

The happy path is last. Each guard has a mutation test that fails if it is removed.
No test reads or writes the real memory/cycle_logs/ or the real needs files.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROPHECY = REPO / "experiments" / "prophecy"
sys.path.insert(0, str(PROPHECY))
sys.path.insert(0, str(REPO))


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sf = _load(PROPHECY / "self_forecast.py", "self_forecast")
nr = _load(REPO / "experiments" / "needs" / "needs_report.py", "needs_report")


def _log(d: Path, day: int, failures: dict):
    """One cycle log with the real line format the runner prints."""
    body = ["[FAST_CYCLE] cycle start", "[FAST_CYCLE] web_intel -> ok"]
    for step, why in failures.items():
        body.append(f"[FAST_CYCLE] {step} -> FAILED: {why}")
    body.append("[FAST_CYCLE] CYCLE_FINISHED")
    p = d / f"cycle_2026-09-{day:02d}_030402.log"
    p.write_text("\n".join(body) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def logs(tmp_path):
    d = tmp_path / "cycle_logs"
    d.mkdir()
    return d


# ── the cases that must produce NOTHING ──────────────────────────────────────

def test_different_steps_failing_on_the_two_nights_is_not_an_alert(logs):
    """THE NEGATIVE CONTROL the handover asks for by name. Two bad nights, but no
    step failed in BOTH, so there is no pattern and no need."""
    _log(logs, 9, {"merkle_to_training": "boom"})
    _log(logs, 10, {"data_scout": "TruncatedJSONError"})
    assert sf.repeated_step_failures(logs, nights=2) == {}


def test_one_bad_night_is_not_an_alert(logs):
    _log(logs, 9, {})
    _log(logs, 10, {"merkle_to_training": "boom"})
    assert sf.repeated_step_failures(logs, nights=2) == {}


def test_two_clean_nights_are_not_an_alert(logs):
    _log(logs, 9, {})
    _log(logs, 10, {})
    assert sf.repeated_step_failures(logs, nights=2) == {}


def test_fewer_logs_than_nights_asked_for_is_not_an_alert(logs):
    """One log cannot evidence two consecutive nights. Answering from one would be
    the 'produce something' failure."""
    _log(logs, 10, {"merkle_to_training": "boom"})
    assert sf.repeated_step_failures(logs, nights=2) == {}


def test_a_missing_logs_directory_is_not_an_alert(tmp_path):
    assert sf.repeated_step_failures(tmp_path / "nope", nights=2) == {}


def test_only_the_last_two_logs_are_considered(logs):
    """A step that failed twice LONG AGO and has been clean for the last two nights
    must not page anyone. 'Two consecutive' means the two most recent."""
    _log(logs, 1, {"merkle_to_training": "boom"})
    _log(logs, 2, {"merkle_to_training": "boom"})
    _log(logs, 9, {})
    _log(logs, 10, {})
    assert sf.repeated_step_failures(logs, nights=2) == {}


# ── the detection, and what the alert has to carry ───────────────────────────

def test_the_same_step_failing_twice_is_detected_with_its_exception(logs):
    _log(logs, 9, {"merkle_to_training": "cannot unpack non-iterable Mapping object"})
    _log(logs, 10, {"merkle_to_training": "cannot unpack non-iterable Mapping object"})
    got = sf.repeated_step_failures(logs, nights=2)
    assert list(got) == ["merkle_to_training"]
    assert got["merkle_to_training"] == ["cannot unpack non-iterable Mapping object"] * 2, \
        "the exception text is not carried — a human would have to grep the log anyway"


def test_a_step_failing_for_two_DIFFERENT_reasons_is_still_detected(logs):
    """It is the STEP that is broken, not one error. Requiring identical messages
    would let a flapping step hide."""
    _log(logs, 9, {"data_scout": "TruncatedJSONError"})
    _log(logs, 10, {"data_scout": "JSONDecodeError"})
    got = sf.repeated_step_failures(logs, nights=2)
    assert got == {"data_scout": ["TruncatedJSONError", "JSONDecodeError"]}


def test_several_repeated_steps_each_get_their_own_entry(logs):
    _log(logs, 9, {"a_step": "x", "b_step": "y", "c_step": "z"})
    _log(logs, 10, {"a_step": "x", "b_step": "y2"})
    assert sorted(sf.repeated_step_failures(logs, nights=2)) == ["a_step", "b_step"]


def test_the_one_parser_is_shared_not_copied(logs):
    """failed_steps() (used by the prophecy self-forecast) and failed_steps_in_log()
    (used by the alert) must agree on every log, because they are one reader. If a
    second parser is ever introduced this is where the disagreement shows."""
    p = _log(logs, 10, {"merkle_to_training": "boom", "data_scout": "bang"})
    assert set(sf.failed_steps_in_log(p)) == {"merkle_to_training", "data_scout"}
    assert sf.failed_steps("2026-09-10T03:04:02+03:00", logs) == set(sf.failed_steps_in_log(p))


# ── the need that reaches the human ──────────────────────────────────────────

def test_a_repeated_failure_becomes_a_HIGH_need_naming_step_and_exception(monkeypatch):
    monkeypatch.setattr(sf, "repeated_step_failures",
                        lambda nights=2: {"merkle_to_training": ["boom", "boom"]})
    monkeypatch.setitem(sys.modules, "self_forecast", sf)
    items = nr._repeated_failure_items()
    assert len(items) == 1
    it = items[0]
    assert it["severity"] == "high", "a nightly-failing step is not a medium"
    assert it["domain"] in ("BODY", "MIND", "SPIRIT"), \
        "an unknown domain KeyErrors in _brief's label map"
    assert "merkle_to_training" in it["need"]
    assert "boom" in it["why"], "the exception text never reaches the human"


def test_no_repeated_failure_means_no_need(monkeypatch):
    monkeypatch.setattr(sf, "repeated_step_failures", lambda nights=2: {})
    monkeypatch.setitem(sys.modules, "self_forecast", sf)
    assert nr._repeated_failure_items() == []


def test_the_needs_report_stays_up_if_the_detector_raises(monkeypatch):
    """FAIL-OPEN, like every other item builder. A missing alert is visible as an
    absent need; a crashed report silences all three hungers at once."""
    def boom(nights=2):
        raise RuntimeError("logs unreadable")
    monkeypatch.setattr(sf, "repeated_step_failures", boom)
    monkeypatch.setitem(sys.modules, "self_forecast", sf)
    assert nr._repeated_failure_items() == []


def test_mutation_without_the_intersection_a_single_night_would_page(logs):
    """The guard is the INTERSECTION across nights. Replace it with a union and the
    negative control becomes an alert — which is the muted-channel failure."""
    _log(logs, 9, {"merkle_to_training": "boom"})
    _log(logs, 10, {"data_scout": "bang"})
    per_night = [sf.failed_steps_in_log(p) for p in sorted(logs.glob("cycle_*.log"))]
    union = set().union(*[set(d) for d in per_night])
    assert union == {"merkle_to_training", "data_scout"}
    assert sf.repeated_step_failures(logs, nights=2) == {}, \
        "the intersection is gone — two unrelated one-off failures would now page"


# ── the happy path, last ─────────────────────────────────────────────────────

def test_a_step_that_is_fixed_stops_alerting_after_two_clean_nights(logs):
    _log(logs, 8, {"merkle_to_training": "boom"})
    _log(logs, 9, {"merkle_to_training": "boom"})
    assert sf.repeated_step_failures(logs, nights=2)      # still broken -> alert
    _log(logs, 10, {})                                    # the fix lands
    assert sf.repeated_step_failures(logs, nights=2) == {}, \
        "one clean night already breaks the pair, so the alert clears"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
