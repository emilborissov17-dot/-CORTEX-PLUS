"""
The debrief that can pass — without the gate getting any softer.

On 21 Aug 2026 the cycle closed six phases and rejected six debriefs, all six
for the same reason ("'what' cites no number at all"), all six from a 3B model
that brain.think(fast=True) had selected simply for being the smallest
installed. A gate that refuses everything trains the operator to stop reading
it. Three things changed, and this file holds all three plus the guarantee that
none of them weakened the gate:

  * the model is qwen3:8b, chosen through the experiment registry so it is a
    KNOB rather than a constant somebody has to remember
  * exactly ONE retry, with a prompt that quotes the rejection reason back and
    lists the numbers that would be accepted
  * the last phase (G_LEARN) closes at the END OF THE CYCLE, because there is no
    next phase to close it — close_last() existed since 20 Aug with zero callers

The rejection path must still fire. Every negative control below feeds a
numberless, CJK, or malformed answer and demands a refusal.
"""
from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

from core import phase_debrief as pd  # noqa: E402

GOOD = {"what": "Scored 25 axes, 0 of 173 weight measured.",
        "verdict": "DEGRADED", "risk": "the composite is assertion",
        "do": "wire a real metric"}
EVIDENCE = {"axes_scored": 25, "measured_weight": 0, "total_weight": 173}


# --------------------------------------------------------------------------- #
# (a) the gate is unchanged
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("payload,ok", [
    (GOOD, True),
    ({**GOOD, "what": "The phase completed successfully."}, False),
    ({**GOOD, "what": "Scored 999 axes."}, False),
    ({**GOOD, "verdict": "FINE"}, False),
    ({**GOOD, "what": "已评分25个轴。"}, False),
    ({**GOOD, "risk": ""}, False),
    ("not an object", False),
])
def test_the_gate_still_judges_the_same_way(payload, ok):
    accepted, _ = pd.validate(payload, EVIDENCE)
    assert accepted is ok


# --------------------------------------------------------------------------- #
# (b) the retry
# --------------------------------------------------------------------------- #

def _asker(*answers):
    """An asker that returns the given answers in order and records the `why`
    it was handed on each call."""
    state = {"calls": [], "i": 0}

    def ask(phase, evidence, why=None):
        state["calls"].append(why)
        i = min(state["i"], len(answers) - 1)
        state["i"] += 1
        return answers[i]

    ask.state = state
    return ask


def test_a_bad_first_answer_gets_exactly_one_sharpened_retry(tmp_path):
    bad = {**GOOD, "what": "The phase completed successfully."}
    ask = _asker(bad, GOOD)
    rec = pd.debrief_phase("D_SCORE", "t", EVIDENCE, base=tmp_path, asker=ask)
    assert rec["accepted"] is True
    assert rec["attempts"] == 2
    assert len(ask.state["calls"]) == 2
    assert ask.state["calls"][0] is None
    assert "cites no number" in ask.state["calls"][1], (
        "the retry was not told WHY the first attempt failed")
    assert rec["attempt_log"][0]["prompt"] == pd.BASE_PROMPT
    assert rec["attempt_log"][1]["prompt"] == pd.SHARP_PROMPT
    assert str(rec["written_to"]).endswith("D_SCORE.json")


def test_a_good_first_answer_is_not_retried(tmp_path):
    ask = _asker(GOOD)
    rec = pd.debrief_phase("D_SCORE", "t", EVIDENCE, base=tmp_path, asker=ask)
    assert rec["accepted"] is True
    assert rec["attempts"] == 1
    assert len(ask.state["calls"]) == 1


def test_two_bad_answers_are_still_rejected_and_both_are_kept(tmp_path):
    """NEGATIVE CONTROL — the whole point. A retry must not become a way to
    eventually accept anything."""
    bad1 = {**GOOD, "what": "The phase completed successfully."}
    bad2 = {**GOOD, "what": "Everything is fine."}
    ask = _asker(bad1, bad2)
    rec = pd.debrief_phase("G_LEARN", "t", EVIDENCE, base=tmp_path, asker=ask)
    assert rec["accepted"] is False
    assert rec["attempts"] == 2
    assert str(rec["written_to"]).endswith("G_LEARN.rejected.json")
    on_disk = json.loads(pathlib.Path(rec["written_to"]).read_text(encoding="utf-8"))
    assert [a["prompt"] for a in on_disk["attempt_log"]] == [pd.BASE_PROMPT,
                                                            pd.SHARP_PROMPT]
    assert on_disk["accepted"] is False


def test_a_numberless_fixture_is_rejected_end_to_end(tmp_path):
    """The named proof: the rejection path still fires."""
    numberless = {"what": "The phase completed successfully.", "verdict": "OK",
                  "risk": "none", "do": "nothing"}
    rec = pd.debrief_phase("B_SENSE", "t", EVIDENCE, base=tmp_path,
                           asker=_asker(numberless))
    assert rec["accepted"] is False
    assert any("cites no number" in r for r in rec["rejected_because"])
    assert pathlib.Path(rec["written_to"]).exists()


def test_a_silent_brain_is_a_rejection_not_a_crash(tmp_path):
    rec = pd.debrief_phase("A_ORIENT", "t", EVIDENCE, base=tmp_path,
                           asker=lambda p, e, why=None: None)
    assert rec["accepted"] is False
    assert rec["rejected_because"]


def test_an_asker_without_a_why_parameter_is_not_retried(tmp_path):
    """Inspected, not caught. Deciding this by swallowing TypeError would hide a
    real TypeError raised inside a working asker."""
    calls = []

    def two_arg(phase, evidence):
        calls.append(phase)
        return {**GOOD, "what": "no numbers here"}

    rec = pd.debrief_phase("F_SELF", "t", EVIDENCE, base=tmp_path, asker=two_arg)
    assert rec["accepted"] is False
    assert rec["attempts"] == 1
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# (c) the sharpened prompt says something the first one did not
# --------------------------------------------------------------------------- #

def test_the_sharpened_prompt_lists_the_acceptable_numbers():
    menu = pd._numbers_menu(EVIDENCE)
    for n in ("25", "0", "173"):
        assert n in menu
    text = pd.PROMPT_SHARP.format(phase="D_SCORE", evidence="{}",
                                  why="'what' cites no number at all",
                                  numbers=menu)
    assert "173" in text
    assert "cites no number" in text
    assert text != pd.PROMPT_BG.format(phase="D_SCORE", evidence="{}")


def test_the_numbers_menu_is_honest_when_there_are_none():
    assert "няма" in pd._numbers_menu({"note": "no numbers at all"})


# --------------------------------------------------------------------------- #
# (d) the model
# --------------------------------------------------------------------------- #

def test_the_debrief_model_is_the_8b_not_the_smallest_installed():
    assert pd.DEBRIEF_MODEL == "qwen3:8b"
    assert pd.debrief_model() == "qwen3:8b"


def test_the_model_is_a_declared_knob():
    """It must be varyable by an experiment, not a constant to remember."""
    from core.self_experiment import ALLOWED_KNOBS
    assert "debrief_model" in ALLOWED_KNOBS
    assert pd.DEBRIEF_MODEL in ALLOWED_KNOBS["debrief_model"]["choices"]
    assert "debrief_prompt" in ALLOWED_KNOBS


def test_the_debrief_never_asks_the_cloud():
    """A self-directed call. It has to work precisely when the cloud is gone."""
    from core import backend_policy
    assert pd.PURPOSE in backend_policy.SELF_DIRECTED
    allowed, why = backend_policy.cloud_allowed(pd.PURPOSE)
    assert allowed is False


# --------------------------------------------------------------------------- #
# (e) the last phase closes
# --------------------------------------------------------------------------- #

def test_close_last_is_actually_called_by_the_runner():
    """close_last() existed from 20 Aug with ZERO callers, which is why G_LEARN
    never got a debrief — not even a rejected one."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "close_last" in src, (
        "nothing calls phase_tracker.close_last(); the last phase of the cycle "
        "will never close and G_LEARN will have no debrief, again")


def test_close_last_runs_before_the_cycle_is_sealed():
    """The debrief must land INSIDE the cycle it describes."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert src.index("close_last") < src.index("_seal_cycle_record()\n    try:")


def test_g_learn_is_the_last_phase_and_therefore_needs_close_last():
    phases = json.loads((REPO / "config" / "cycle_phases.json")
                        .read_text(encoding="utf-8"))["phases"]
    assert list(phases)[-1] == "G_LEARN"


def test_close_last_closes_an_open_phase(monkeypatch):
    from core import phase_tracker as pt
    closed = []
    pt._reset_for_tests()

    class _Report:
        def finish(self):
            return {"verdict": "OK", "reason": "test"}

    monkeypatch.setattr(pt, "_open_phase", "G_LEARN", raising=False)
    monkeypatch.setattr(pt, "_open_report", _Report(), raising=False)
    monkeypatch.setattr(pt, "_close", lambda phase, report: closed.append(phase))
    pt.close_last()
    assert closed == ["G_LEARN"]
    assert pt._open_phase is None


def test_close_last_on_nothing_open_is_a_no_op(monkeypatch):
    from core import phase_tracker as pt
    pt._reset_for_tests()
    called = []
    monkeypatch.setattr(pt, "_close", lambda phase, report: called.append(phase))
    pt.close_last()
    assert called == []


# --------------------------------------------------------------------------- #
# (f) the test suite must not write live debriefs
# --------------------------------------------------------------------------- #

def test_the_phase_tracker_is_neutralised_for_the_suite():
    """Found 21 Aug: hb.beat() in test_supervisor.py opened and closed real
    phases against LIVE memory, writing model-produced debriefs into
    memory/phase_debriefs/dead-1/ and burning nine minutes of the suite."""
    conf = (REPO / "test" / "conftest.py").read_text(encoding="utf-8")
    assert '"core.phase_tracker", "on_beat"' in conf, (
        "core.phase_tracker.on_beat is not in _NEUTRALISED — a test that beats "
        "the heartbeat will call a language model and write into live memory")


def test_no_fabricated_cycle_ids_are_left_in_live_debriefs():
    """The garbage those leaks left behind must be gone and stay gone."""
    root = REPO / "memory" / "phase_debriefs"
    if not root.exists():
        pytest.skip("no debriefs on this machine")
    fabricated = [d.name for d in root.iterdir()
                  if d.is_dir() and (d.name.startswith("dead-")
                                     or d.name.startswith("manual-run-")
                                     or d.name in ("selftest", "unknown-cycle"))]
    assert not fabricated, (
        f"test-fabricated debrief directories in live memory: {fabricated}")
