"""The pulse must not report a dead cycle as alive.

THE BUG (found in the 2026-07-14 review)
----------------------------------------
_sense_cycle() returned running=True whenever memory/heartbeat.json EXISTED. It
computed heartbeat_age_sec and then never looked at it.

A cycle killed hard leaves its heartbeat behind — TerminateProcess runs no
handler, so fast_cycle_runner's _clear_heartbeat() never runs — and the pulse
would have gone on reporting a live cycle, stuck in the same step, forever. The
sensor would be asserting life over a corpse.

That is the exact anomaly a proprioceptive stream exists to notice, so reporting
it as health is the worst available failure for this instrument. It stayed
invisible because every cycle observed so far exited cleanly and cleared its own
heartbeat.

Testing an anomaly detector on a sensor known to be blind to that anomaly would
prove nothing, so this is fixed BEFORE the anomaly test runs.

The heartbeats below are written by memory/heartbeat.py's own beat(), not
hand-rolled dicts: a test that invents its own schema stops testing the contract
the moment the real one drifts.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "pulse"))

import pulse_daemon as pd
from memory import heartbeat as hb


@pytest.fixture
def beating(tmp_path, monkeypatch):
    """A heartbeat file the pulse reads and heartbeat.py writes — never the real one."""
    path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", path)
    monkeypatch.setattr(pd, "HEARTBEAT_FILE", path)
    return path


def _age_the_beat(path: Path, seconds: float) -> None:
    """Backdate the heartbeat on disk, leaving every other field as beat() wrote it."""
    data = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    data["updated_utc"] = old
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# The sensor is not deaf: a live cycle reads as live, with its step
# ---------------------------------------------------------------------------

def test_a_fresh_heartbeat_reads_as_a_running_cycle(beating):
    hb.beat("self_observer", 19)

    cyc = pd._sense_cycle()

    assert cyc["running"] is True
    assert cyc["step"] == "self_observer"
    assert cyc["step_index"] == 19
    assert cyc["heartbeat_age_sec"] < 5
    assert "stale_heartbeat" not in cyc


def test_the_pulse_reads_the_same_file_the_cycle_writes():
    """Path agreement, checked against the real constants — not the fixture. If
    these ever drift apart the pulse goes silently blind to every cycle."""
    import importlib
    fresh_pd = importlib.reload(pd)
    fresh_hb = importlib.reload(hb)
    assert fresh_pd.HEARTBEAT_FILE.resolve() == fresh_hb.HEARTBEAT_PATH.resolve()


# ---------------------------------------------------------------------------
# THE fix: a stale heartbeat is not proof of life
# ---------------------------------------------------------------------------

def test_a_stale_heartbeat_reads_as_NOT_running(beating):
    """The hard-kill case: the cycle is dead, its heartbeat is not."""
    hb.beat("web_intelligence", 12)
    _age_the_beat(beating, 45 * 60)      # killed 45 minutes ago

    cyc = pd._sense_cycle()

    assert cyc["running"] is False, "a corpse was reported as a live cycle"
    assert cyc["stale_heartbeat"] is True
    # The forensics survive: WHERE it died is the whole value of the record.
    assert cyc["step"] == "web_intelligence"
    assert cyc["heartbeat_age_sec"] > 2400


def test_a_long_but_legitimate_step_still_reads_as_running(beating):
    """web_intelligence genuinely runs for the better part of an hour. The
    threshold must not turn a slow step into a phantom death — this daemon only
    senses; the supervisor owns the kill decision and has its own ceilings."""
    hb.beat("web_intelligence", 12)
    _age_the_beat(beating, 20 * 60)      # 20 min into a legitimately slow step

    cyc = pd._sense_cycle()

    assert cyc["running"] is True
    assert cyc["step"] == "web_intelligence"


def test_the_threshold_is_where_we_think_it_is(beating):
    hb.beat("scoring_engine", 20)
    _age_the_beat(beating, pd.STALE_HEARTBEAT_SEC + 30)
    assert pd._sense_cycle()["running"] is False

    hb.beat("scoring_engine", 20)
    _age_the_beat(beating, pd.STALE_HEARTBEAT_SEC - 30)
    assert pd._sense_cycle()["running"] is True


def test_an_undateable_heartbeat_is_not_proof_of_life(beating):
    """No timestamp means we cannot claim the beat is recent. Absence of evidence
    is not evidence of life."""
    beating.write_text(json.dumps({"pid": 1, "step": "self_observer"}), encoding="utf-8")

    cyc = pd._sense_cycle()

    assert cyc["running"] is False
    assert cyc["stale_heartbeat"] is True


# ---------------------------------------------------------------------------
# The pre-existing readings must not regress
# ---------------------------------------------------------------------------

def test_no_heartbeat_at_all_is_a_quiet_idle_system(beating):
    """A cleanly finished cycle clears its heartbeat. That is idle — NOT stale."""
    cyc = pd._sense_cycle()

    assert cyc == {"running": False}
    assert "stale_heartbeat" not in cyc


def test_a_torn_heartbeat_is_unreadable_not_running(beating):
    beating.write_text('{"pid": 1, "step": "self_obs', encoding="utf-8")

    cyc = pd._sense_cycle()

    assert cyc["running"] is False
    assert cyc["heartbeat_unreadable"] is True
