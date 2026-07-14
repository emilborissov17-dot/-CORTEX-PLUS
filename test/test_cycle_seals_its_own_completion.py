"""A cycle that finished must say so, and let go of its lock.

THE BUG (2026-07-14)
--------------------
Nothing ever wrote CYCLE_FINISHED. The constant existed in existence_ledger.py
and summary() counted it, but no producer did — so total_cycles_finished was
permanently 0. And because the runner never cleared its own lock, every CLEAN
finish left a lock held by a dead pid, which the next supervisor tick cleared as
stale and logged as "machine likely lost power mid-cycle".

The result: in the system's own permanent record, a successful cycle was
indistinguishable from a crashed one. The 2026-07-14 catch-up ran all 25 steps,
committed its Merkle root, and its record says it never finished and probably
lost power.

WHY THE RUNNER AND NOT THE SUPERVISOR
-------------------------------------
From outside, "exited cleanly" and "died quietly" look the same: both leave a
dead pid. Only the cycle itself knows it reached the end. So the witness must
speak — the runner appends CYCLE_FINISHED, and nothing else, to the ledger.

NOT BACKFILLED, deliberately: today's cycle has no CYCLE_FINISHED event and never
will. The ledger stays honest about its own history, including the era of this
bug. See test_no_backfill_of_history.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import fast_cycle_runner as fcr
from memory import existence_ledger as el
from memory import heartbeat as hb


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the ledger, lock and heartbeat at a tmp dir. The real ones are
    protected constitutional state — a test must never write to them."""
    monkeypatch.setattr(el, "LEDGER_PATH", tmp_path / "existence_ledger.jsonl")
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    monkeypatch.setattr(fcr, "LOCK_PATH", tmp_path / "cycle.lock")
    return tmp_path


def _write_lock(sandbox, pid, cycle_id="2026-07-14T08:14:02+03:00",
                started="2026-07-14T05:14:02+00:00"):
    (sandbox / "cycle.lock").write_text(json.dumps({
        "pid": pid, "cycle_id": cycle_id, "started_utc": started,
    }), encoding="utf-8")


# ---------------------------------------------------------------------------
# The two properties
# ---------------------------------------------------------------------------

def test_clean_finish_writes_cycle_finished_to_the_ledger(sandbox):
    _write_lock(sandbox, os.getpid())

    fcr._seal_cycle_record()

    events = el.read_all()
    assert [e["event"] for e in events] == [el.CYCLE_FINISHED]

    ev = events[0]
    assert ev["cycle_id"] == "2026-07-14T08:14:02+03:00"
    assert ev["pid"] == os.getpid()
    assert ev["duration_sec"] is not None and ev["duration_sec"] > 0


def test_clean_finish_releases_its_own_lock(sandbox):
    _write_lock(sandbox, os.getpid())

    fcr._seal_cycle_record()

    assert not (sandbox / "cycle.lock").exists(), (
        "a finished cycle that keeps its lock is read as a crash by the next tick"
    )


def test_summary_finally_counts_a_finished_cycle(sandbox):
    """The whole point: total_cycles_finished stops being permanently 0."""
    el.append(el.CYCLE_STARTED, cycle_id="c1", pid=os.getpid(), trigger="CATCHUP")
    _write_lock(sandbox, os.getpid(), cycle_id="c1")

    fcr._seal_cycle_record()

    s = el.summary()
    assert s["total_cycles_started"] == 1
    assert s["total_cycles_finished"] == 1
    assert s["chain_valid"] is True


# ---------------------------------------------------------------------------
# The dangerous edge: do not release a lock that is not ours
# ---------------------------------------------------------------------------

def test_does_not_release_a_lock_belonging_to_another_cycle(sandbox):
    """If the supervisor judged us hung, killed us, and started a replacement, the
    lock on disk belongs to the NEW cycle. A dying straggler deleting it would
    leave the live cycle unlocked and invite a second one."""
    _write_lock(sandbox, os.getpid() + 1)      # somebody else's lock

    fcr._seal_cycle_record()

    assert (sandbox / "cycle.lock").exists(), "released a lock we did not hold"
    lock = json.loads((sandbox / "cycle.lock").read_text(encoding="utf-8"))
    assert lock["pid"] == os.getpid() + 1


def test_still_seals_when_run_by_hand_with_no_lock(sandbox):
    """A manual `python fast_cycle_runner.py` has no supervisor and no lock. It is
    still a cycle, and it still finished — falling back to the heartbeat's
    cycle_id."""
    hb.beat("training_data_accumulation", 25, cycle_id="manual-run-1")

    fcr._seal_cycle_record()

    events = el.read_all()
    assert [e["event"] for e in events] == [el.CYCLE_FINISHED]
    assert events[0]["cycle_id"] == "manual-run-1"


def test_seal_never_raises_even_if_the_ledger_is_unwritable(sandbox, monkeypatch):
    """Sealing the record must not fail a cycle that already did all its work.
    The worst case of a failed seal is the OLD behaviour, which is survivable."""
    def _boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(el, "append", _boom)
    _write_lock(sandbox, os.getpid())

    fcr._seal_cycle_record()      # must not raise

    # And the lock is still released — the two failures are independent.
    assert not (sandbox / "cycle.lock").exists()


# ---------------------------------------------------------------------------
# Honesty about history
# ---------------------------------------------------------------------------

def test_no_backfill_of_history():
    """The 2026-07-14 catch-up finished, but has no CYCLE_FINISHED event, and must
    never acquire one. Backfilling would be the system editing its own past to
    look better — precisely the lie the hash chain exists to prevent. A ledger
    that is honest about the era of a bug is worth more than a tidy one.

    Reads the REAL ledger, read-only.
    """
    events = el.read_all()
    on_the_14th = [e for e in events
                   if e["event"] == el.CYCLE_FINISHED and e["ts"].startswith("2026-07-14")]
    assert on_the_14th == [], (
        "someone backfilled a CYCLE_FINISHED for the cycle that ran during the bug"
    )
