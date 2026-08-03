"""Permanent test suite for the cycle heartbeat.

THE FAILURE THIS PREVENTS
-------------------------
The watchdog kills a cycle whose heartbeat is stale past a per-step ceiling. If
a step does not beat, the cycle looks FROZEN for that step's entire duration —
and the steps most likely to be missed are the slow ones (global_indicators hits
20 live HTTP APIs; web_intelligence_agent can run the better part of an hour).
An uninstrumented step therefore does not merely lose telemetry: it causes the
watchdog to kill a perfectly healthy cycle.

Roughly a dozen steps in fast_cycle_runner bypass _run() and use inline
try/except, so instrumenting _run() alone would NOT have been enough. That is
why coverage is asserted structurally, against the source, rather than hoped for.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from memory import heartbeat as hb

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "fast_cycle_runner.py"

STEP_COMMENT_RE = re.compile(r'^    # ── ([\d.]+)\.\s*(.+?)\s*─*\s*$')
BEAT_RE = re.compile(r'^\s*beat\(')


@pytest.fixture(autouse=True)
def isolated_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    yield


# ---------------------------------------------------------------------------
# Coverage — every step boundary must beat
# ---------------------------------------------------------------------------

def _steps_and_beats():
    """(step_id, description, beats, beat_id) for every step boundary.

    The beat must be the first EXECUTABLE line of the step. It used to be looked for in
    a fixed 3-line window, which quietly meant "within 3 physical lines" rather than
    "before any work" — so four correctly instrumented steps (2.54, 2.55, 2.6, 2.7)
    failed this suite purely because their boundary comment runs to several lines. The
    test was wrong, not the runner. Skipping the continuation comment first measures what
    the docstring above actually claims, and costs nothing.
    """
    lines = RUNNER.read_text(encoding="utf-8").splitlines()
    found = []
    for i, line in enumerate(lines):
        m = STEP_COMMENT_RE.match(line)
        if not m:
            continue
        j = i + 1
        # a step boundary may carry a multi-line comment; the beat must come before code
        while j < len(lines) and (not lines[j].strip()
                                  or lines[j].lstrip().startswith("#")):
            j += 1
        window = lines[j: j + 3]
        beat_line = next((w for w in window if BEAT_RE.match(w)), None)
        beat_id = None
        if beat_line:
            bm = re.search(r'beat\(\s*"[^"]*"\s*,\s*"([\d.]+)"', beat_line)
            beat_id = bm.group(1) if bm else None
        found.append((m.group(1), m.group(2), beat_line is not None, beat_id))
    return found


def test_every_step_boundary_beats():
    steps = _steps_and_beats()
    assert steps, "no step boundaries found — did the comment format change?"

    missing = [f"step {num}: {desc}" for num, desc, beats, _bid in steps if not beats]

    assert not missing, (
        "These cycle steps do not call beat() — the watchdog will see the cycle "
        "as frozen for their whole duration and kill a healthy run:\n  "
        + "\n  ".join(missing)
    )


def test_each_beat_reports_the_step_it_is_actually_in():
    """A beat carrying the wrong step id is worse than a missing one: the watchdog's
    per-step ceiling is keyed on that id, so a slow step reporting a fast step's number
    gets killed early, and the log points the reader at the wrong place."""
    wrong = [f"step {num} ({desc}) beats as {bid!r}"
             for num, desc, beats, bid in _steps_and_beats()
             if beats and bid and bid != num]
    assert not wrong, ("These beats report a different step id than their boundary:\n  "
                       + "\n  ".join(wrong))


def test_there_are_a_plausible_number_of_steps():
    """Guards the regex itself: if the comment format changes, the coverage test
    above would silently pass on zero steps."""
    assert len(_steps_and_beats()) >= 30


def test_runner_clears_heartbeat_on_clean_finish():
    src = RUNNER.read_text(encoding="utf-8")
    assert "_clear_heartbeat()" in src, \
        "a completed cycle must drop its heartbeat, or it looks hung to the supervisor"


# ---------------------------------------------------------------------------
# The heartbeat module itself
# ---------------------------------------------------------------------------

def test_beat_writes_step_and_pid():
    hb.beat("global_indicators", "2.5")
    got = hb.read()

    assert got["step"] == "global_indicators"
    assert got["step_index"] == "2.5"
    assert isinstance(got["pid"], int)
    assert got["updated_utc"]


def test_cycle_id_is_stable_across_beats():
    """The supervisor uses cycle_id to tie a kill back to a specific run."""
    hb.beat("step_one", "1")
    first = hb.read()["cycle_id"]

    hb.beat("step_two", "2")
    second = hb.read()["cycle_id"]

    assert first == second, "cycle_id must not change mid-cycle"


def test_read_returns_none_when_absent():
    assert hb.read() is None


def test_read_returns_none_on_corrupt_file():
    """A torn write must read as 'no proof of life', not crash the supervisor."""
    hb.HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    hb.HEARTBEAT_PATH.write_text("{not json", encoding="utf-8")
    assert hb.read() is None


def test_age_seconds_is_small_right_after_a_beat():
    hb.beat("x", "1")
    age = hb.age_seconds()
    assert age is not None and age < 5


def test_age_seconds_detects_a_stale_heartbeat():
    hb.beat("wedged_step", "11")
    future = datetime.now(timezone.utc) + timedelta(minutes=42)

    age = hb.age_seconds(now=future)

    assert age > 40 * 60, "a wedged cycle must show its true age"


def test_age_seconds_none_when_no_heartbeat():
    assert hb.age_seconds() is None


def test_clear_removes_the_heartbeat():
    hb.beat("x", "1")
    assert hb.read() is not None
    hb.clear()
    assert hb.read() is None


def test_clear_is_safe_when_already_absent():
    hb.clear()
    hb.clear()   # must not raise


def test_beat_never_raises_even_if_the_path_is_unwritable(monkeypatch):
    """A failed heartbeat write must never kill the cycle. Worst case the
    supervisor sees a stale beat and restarts us — which is correct and
    conservative. Crashing a healthy cycle over a transient file lock is not."""
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", Path("Z:/nonexistent/dir/hb.json"))
    hb.beat("x", "1")   # must not raise


def test_write_is_atomic_no_temp_files_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    for i in range(5):
        hb.beat(f"step_{i}", str(i))

    leftovers = list(tmp_path.glob("*.tmp"))
    assert not leftovers, f"atomic write leaked temp files: {leftovers}"
    assert json.loads((tmp_path / "heartbeat.json").read_text(encoding="utf-8"))
