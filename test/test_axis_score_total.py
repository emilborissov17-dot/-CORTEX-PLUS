# -*- coding: utf-8 -*-
"""ITEM 21 — one malformed field must not kill a whole cycle step.

THE CRASH. On 2026-08-29 the nightly cycle logged

    [FAST_CYCLE] feedback_loop -> FAILED: TypeError: cannot use 'dict' as a
    dict key (unhashable type: 'dict')

agents/core/feedback_loop.py:47 does `if val in level_map`, and
DEEP_TIME_RISKS_REVIEW.current_level is a DICT — {"asteroid": "HIGH",
"supervolcano": "UNKNOWN", "astrophysical": "MEDIUM"}, a per-hazard breakdown
where every other axis carries a single word. `in` against a dict key raises,
and the whole step dies with it.

WHAT THAT COSTS. feedback_loop is the only writer of
memory/goal_score_history.json and memory/feedback_log.json. When it dies no
history record is appended, so measurement_honesty's basis_ts stops advancing —
it read 2026-08-21 on 2026-08-29, eight days stale, and honest_composite was
computed from that. Intermittent, 3 of the last 15 cycles, which is why it
survived: the axis agent emits a dict on some runs and a word on others.

THE DISCIPLINE THIS APPLIES. _measured_axis_scores in the same file learned this
lesson on 20 Aug, when one None killed all measurement and the fix was to fail
PER AXIS and name the offender. This is that lesson applied to the other loop in
the same file.

WHAT IS DELIBERATELY NOT DECIDED HERE: what DEEP_TIME_RISKS_REVIEW's level IS.
Reducing a per-hazard breakdown to one word is a scoring decision — worst?
weighted? — and inventing one silently is the defect, not the fix. The axis
yields no level, is named on stdout, and waits for a human.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from agents.core import feedback_loop as fl  # noqa: E402

HISTORY = BASE / "memory" / "goal_score_history.json"
FEEDBACK = BASE / "memory" / "feedback_log.json"


def _digest(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


_LIVE_BEFORE = {p.as_posix(): _digest(p) for p in (HISTORY, FEEDBACK)}

THE_REAL_SHAPE = {"asteroid": "HIGH", "supervolcano": "UNKNOWN",
                  "astrophysical": "MEDIUM"}


# ── the crash itself ───────────────────────────────────────────────────────

def test_a_dict_where_a_level_word_belongs_does_not_raise():
    """The exact payload from the 2026-08-29 cycle."""
    assert fl._axis_score({"current_level": THE_REAL_SHAPE},
                          "DEEP_TIME_RISKS_REVIEW") is None


def test_a_list_where_a_level_word_belongs_does_not_raise():
    """Unhashable is the class of defect, not dict specifically."""
    assert fl._axis_score({"current_level": ["HIGH", "LOW"]}, "AX") is None


def test_a_level_that_is_not_a_string_is_not_a_level():
    for bad in (3, 3.5, True, None, {"a": 1}, ["a"], set()):
        assert fl._axis_score({"current_level": bad}, "AX") is None, bad


def test_a_real_level_word_still_scores():
    """The negative control: the fix must not stop the thing working."""
    assert fl._axis_score({"current_level": "HIGH"}, "AX") == 85.0
    assert fl._axis_score({"current_level": "LOW"}, "AX") == 30.0


def test_a_risk_axis_still_inverts():
    """RISK axes read HIGH as bad; that mapping must survive the fix."""
    assert fl._axis_score({"current_level": "HIGH"}, "CLIMATE_RISK_REVIEW") == 20.0
    assert fl._axis_score({"current_level": "LOW"}, "CLIMATE_RISK_REVIEW") == 85.0


def test_a_malformed_level_does_not_block_the_other_scoring_paths():
    """A bad current_level must not stop a snapshot that also carries a score."""
    snap = {"current_level": THE_REAL_SHAPE, "score": 42.0}
    assert fl._axis_score(snap, "DEEP_TIME_RISKS_REVIEW") == 42.0


def test_a_malformed_level_still_lets_urgency_through():
    snap = {"current_level": THE_REAL_SHAPE, "urgency": "HIGH"}
    assert fl._axis_score(snap, "AX") == 20.0


# ── the acceptance, as the item words it ───────────────────────────────────

def test_read_current_scores_survives_and_names_the_offender(monkeypatch, capsys):
    """Feed a master snapshot whose current_level is a dict: the OTHER axes
    still score, the offender is named, and nothing raises."""
    master = {"snapshots": {
        "GOOD_ONE": {"current_level": "HIGH"},
        "DEEP_TIME_RISKS_REVIEW": {"current_level": THE_REAL_SHAPE},
        "GOOD_TWO": {"score": 55.0},
    }}
    monkeypatch.setattr(fl, "_load_json", lambda p, d: master if "master" in str(p) else d)
    monkeypatch.setattr(fl, "_measured_axis_scores", lambda: {})

    scores = fl.read_current_scores()

    assert scores["GOOD_ONE"] == 85.0
    assert scores["GOOD_TWO"] == 55.0
    assert "DEEP_TIME_RISKS_REVIEW" not in scores, (
        "an axis with no single level must not be given one")

    out = capsys.readouterr().out
    assert "DEEP_TIME_RISKS_REVIEW" in out, "the offender must be named on stdout"
    assert "dict" in out, "the SHAPE must be named, not just the axis"


def test_the_live_ledgers_are_byte_identical_after():
    for path, before in _LIVE_BEFORE.items():
        after = _digest(pathlib.Path(path))
        assert after == before, f"{path} moved during the test run"
