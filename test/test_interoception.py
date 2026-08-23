# -*- coding: utf-8 -*-
"""
test/test_interoception.py — THE BRAIN MUST KNOW HOW IT HAS BEEN DOING.

core/brain.py gave every call a ТЯЛО line (what the machine is) and a ДУХ block
(what the mission is). Neither said how the system has been PERFORMING. A brain
asked "should I flag this as a risk?" answers differently at a false-alarm rate
of 1.0 than at 0.05, and could not know which it was.

Measured on this machine while writing this, which is why the number matters:

    FALSE_ALARMS: 1.0 (16 of 16 paired)
    OPEN_PROPOSALS: 72 (39 overdue), oldest 27.4 days
    LAST_CYCLE: DIED at step body_scan
    FREE_MEMORY: RAM 149.4 MB (98.9% used), VRAM 518 MB of 4096
    RESTARTS_TODAY: 2/2, 0 left

Every doubt the system raised in the window came out false, and it did not know.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import interoception as io   # noqa: E402

# The mirror of 21 Aug 2026, captured VERBATIM from memory/self_mirror_latest.json
# (producer: core/self_mirror.py). Laid out as <base>/memory/... because that is
# exactly what interoception.must_cite(base=...) resolves.
MIRROR_BASE = REPO / "test" / "fixtures" / "interoception_2026-08-21"
MIRROR_FIXTURE = MIRROR_BASE / "memory" / "self_mirror_latest.json"


# --------------------------------------------------------------------------- #
# Five rows, fixed positions, no pictures of numbers
# --------------------------------------------------------------------------- #

def test_the_block_is_five_rows_in_a_fixed_order():
    lines = io.block().splitlines()
    assert len(lines) == 5
    assert [ln.split(":")[0] for ln in lines] == list(io.ROWS)


def test_a_row_whose_source_is_missing_is_still_a_row():
    """Fixed positions only mean anything if the positions are always filled. A
    line that quietly is not there turns row 4 into row 3."""
    s = io.self_state(mirror=None, body_row=None)
    assert len(s) == 5
    assert set(s) == set(io.ROWS)
    for label, value in s.items():
        assert value.strip(), label


def test_an_unknown_value_carries_its_reason():
    s = io.self_state(mirror=None, body_row=None)
    for label, value in s.items():
        if io.UNKNOWN in value:
            assert "(" in value, f"{label} says unknown without saying why"


def test_no_sparklines_no_bars_no_emoji():
    """A model reads "0.62" and a bar of eight blocks differently, and only one
    of them is the number."""
    text = io.block()
    for glyph in "▁▂▃▄▅▆▇█░▒▓●○◆■□▲▼★☆":
        assert glyph not in text
    assert all(ord(c) < 0x1F000 for c in text), "an emoji reached the prompt"


def test_a_row_that_raises_still_produces_a_row(monkeypatch):
    monkeypatch.setattr(io, "_restart_budget",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s = io.self_state()
    assert len(s) == 5
    assert "RuntimeError" in s["RESTARTS_TODAY"]


# --------------------------------------------------------------------------- #
# The five readings say the right thing
# --------------------------------------------------------------------------- #

def test_the_last_cycle_row_names_the_step_it_died_on(tmp_path):
    """"KILLED" is an event; "KILLED on daily_analysis" is evidence a brain can
    weigh when it is asked to plan more daily_analysis."""
    led = tmp_path / "ledger.jsonl"
    led.write_text("\n".join(json.dumps(e) for e in [
        {"event": "CYCLE_STARTED", "cycle_id": "c1"},
        {"event": "CYCLE_KILLED", "cycle_id": "c1",
         "reason": {"wedged_step": "daily_analysis"}},
    ]) + "\n", encoding="utf-8")
    assert io._last_cycle(led) == "KILLED at step daily_analysis"


def test_a_finished_cycle_says_finished(tmp_path):
    led = tmp_path / "ledger.jsonl"
    led.write_text(json.dumps({"event": "CYCLE_FINISHED", "cycle_id": "c1"}) + "\n",
                   encoding="utf-8")
    assert io._last_cycle(led) == "FINISHED"


def test_the_false_alarm_row_is_a_rate_with_its_denominator():
    """A rate with no n behind it invites the wrong conclusion. 1.0 out of 2 and
    1.0 out of 200 are different facts."""
    row = io._false_alarms({"calibration": {"false_alarms": 16,
                                            "justified_doubts": 0,
                                            "missed_failures": 0}})
    assert "1.0" in row and "16" in row


def test_zero_paired_judgements_is_not_a_rate_of_zero():
    row = io._false_alarms({"calibration": {"false_alarms": 0,
                                            "justified_doubts": 0,
                                            "missed_failures": 0}})
    assert io.UNKNOWN in row
    assert "0 paired" in row


def test_the_restart_row_survives_an_unreadable_state_file():
    row = io._restart_budget(state=None, cfg={"max_restarts_per_day": 2})
    assert "0/2" in row


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #

def test_the_block_is_built_inside_the_budget():
    """Measured, not assumed. If it ever goes over, this goes red rather than
    the cycle quietly getting slower."""
    _text, secs = io.timed_block()
    assert secs <= io.LATENCY_BUDGET_SEC, (
        f"the self-state block cost {secs:.2f}s per brain call, over the "
        f"{io.LATENCY_BUDGET_SEC}s budget")


def test_it_is_built_per_call_not_cached():
    """A cached self-state is the weekly report again. The whole point is that
    it is fresh at the moment of the thought."""
    src = (REPO / "core" / "interoception.py").read_text(encoding="utf-8")
    assert "lru_cache" not in src
    assert "_CACHE" not in src


# --------------------------------------------------------------------------- #
# It reaches the prompt
# --------------------------------------------------------------------------- #

def test_every_brain_call_carries_the_block():
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    assert "_self_state()" in src
    assert "HOW YOU ARE DOING" in src
    prompt = src.split("prompt = (", 1)[1][:900]
    assert "_self_state()" in prompt, (
        "the block is defined but does not reach the prompt string")


def test_the_brain_thinks_on_without_it(monkeypatch):
    """A thought must not die of self-observation."""
    from core import brain
    monkeypatch.setattr(io, "block",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = brain._self_state()
    assert "не се чете" in out or "RuntimeError" in out


# --------------------------------------------------------------------------- #
# The deliberate daily read
# --------------------------------------------------------------------------- #

def test_the_read_verifies_the_numbers_against_the_mirror(tmp_path):
    """The model is asked which numbers it cited. What counts is which of them
    are in the mirror AND in the sentence — a number that is in neither is an
    invention, and 'numbers' with no prose behind them is not a reading."""
    mirror = {"calibration": {"false_alarms": 16, "justified_doubts": 3}}
    rec = io.read_the_mirror(
        thinker=lambda **kw: {"saw": "16 фалшиви тревоги срещу 3 основателни",
                              "worries": "none", "numbers": "16,3,999999"},
        mirror=mirror, out_path=tmp_path / "read.json")
    assert rec["cited"] == ["16", "3"]
    assert "999999" not in rec["cited"], "an invented number was accepted"
    assert rec["met_quota"] is True


def test_a_reading_with_no_real_numbers_fails_the_quota(tmp_path):
    rec = io.read_the_mirror(
        thinker=lambda **kw: {"saw": "всичко изглежда наред", "worries": "-",
                              "numbers": ""},
        mirror={"calibration": {"false_alarms": 16}},
        out_path=tmp_path / "read.json")
    assert rec["cited_count"] == 0
    assert rec["met_quota"] is False


def test_the_read_never_raises_when_the_brain_is_down(tmp_path):
    rec = io.read_the_mirror(
        thinker=lambda **kw: (_ for _ in ()).throw(RuntimeError("ollama is dead")),
        mirror={"calibration": {"false_alarms": 16}},
        out_path=tmp_path / "read.json")
    assert "RuntimeError" in rec["error"]
    assert rec["cited"] == []
    assert (tmp_path / "read.json").exists(), "the failure was not recorded"


def test_the_runner_calls_it_inside_g_learn():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert 'beat("read_the_mirror", "25.46")' in src
    assert "read_the_mirror as _rtm" in src
    # After self_mirror, because it reads what self_mirror just wrote.
    assert src.index('_run("self_mirror"') < src.index('beat("read_the_mirror"')
    assert src.index('beat("read_the_mirror"') < src.index('beat("brain_debrief"')


def test_the_phase_spec_places_it_in_g_learn():
    spec = json.loads((REPO / "config" / "cycle_phases.json")
                      .read_text(encoding="utf-8"))["phases"]
    names = [s["name"] for s in spec["G_LEARN"]["steps"]]
    assert "read_the_mirror" in names
    for phase, body in spec.items():
        if phase == "G_LEARN":
            continue
        assert "read_the_mirror" not in [s["name"] for s in body["steps"]]


# --------------------------------------------------------------------------- #
# The quota on the G_LEARN debrief
# --------------------------------------------------------------------------- #

GOOD = {"verdict": "OK", "risk": "none", "do": "nothing"}


def test_a_g_learn_debrief_that_ignores_the_mirror_is_rejected():
    from core import phase_debrief as pd
    ev = {"phase": "G_LEARN", "experiments_total": 30}
    accepted, reasons = pd.validate({**GOOD, "what": "G_LEARN ran 30 experiments."},
                                    ev, {"30"}, must_cite={"16", "72"})
    assert not accepted
    assert any(pd.MIRROR_QUOTA_UNMET in r for r in reasons)


def test_two_mirror_numbers_satisfy_it():
    from core import phase_debrief as pd
    ev = {"phase": "G_LEARN", "experiments_total": 30}
    accepted, reasons = pd.validate(
        {**GOOD, "what": "30 experiments; огледалото: 16 фалшиви от 72 отворени."},
        ev, {"30"}, must_cite={"16", "72"})
    assert accepted, reasons


def test_one_mirror_number_is_not_two():
    from core import phase_debrief as pd
    accepted, reasons = pd.validate(
        {**GOOD, "what": "30 experiments; огледалото: 16 фалшиви."},
        {"phase": "G_LEARN", "experiments_total": 30}, {"30"},
        must_cite={"16", "72"})
    assert not accepted
    assert any("owes 2" in r for r in reasons)


def test_the_quota_applies_to_g_learn_and_to_nothing_else(monkeypatch):
    """The routing, end-to-end, on a captured mirror.

    G_LEARN's quota is drawn from memory/self_mirror_latest.json, which is
    regenerable runtime state and is no longer tracked. The mirror of 21 Aug 2026
    is captured VERBATIM under test/fixtures/interoception_2026-08-21/, so this
    still exercises the real path phase_tracker -> interoception.must_cite ->
    mirror_numbers rather than asserting against whatever ran here last night.
    """
    from core import phase_tracker as pt
    monkeypatch.setattr(io, "MIRROR", MIRROR_FIXTURE)
    assert pt._must_cite("G_LEARN"), (
        "G_LEARN draws no numbers from the captured mirror")
    for phase in ("A_ORIENT", "B_SENSE", "C_SNAPSHOT", "D_SCORE",
                  "E_PROPOSE", "F_SELF"):
        assert pt._must_cite(phase) == set(), phase


def test_the_quota_reads_the_mirror_through_the_documented_base():
    """must_cite(base=...) resolves <base>/memory/self_mirror_latest.json."""
    assert io.must_cite(base=MIRROR_BASE) == io.must_cite(base=MIRROR_BASE)
    assert io.must_cite(base=MIRROR_BASE), "the captured mirror yields no numbers"


def test_the_mirrors_own_numbers_stay_f_selfs_own():
    """G_LEARN's MENU carries facts about the READ (how many were cited, out of
    how many, in how long) and not the mirror's values — otherwise F_SELF's
    numbers would appear in two menus and stop being anyone's own, which would
    blunt the swap test for both phases."""
    from core import phase_evidence as pe
    menus = pe.all_menus()
    assert len(pe.own_numbers("F_SELF", menus)) >= pe.MIN_OWN_NUMBERS
    assert len(pe.own_numbers("G_LEARN", menus)) >= pe.MIN_OWN_NUMBERS
    g = menus["G_LEARN"]
    assert not any(k.startswith("mirror_false_alarms") for k in g)
