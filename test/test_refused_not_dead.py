"""A cycle a gate refused to start is not a cycle that died.

24 Aug 2026, 03:04+03:00. The homeostatic gate read RAM at 93% — 1.0GB free,
against a stated need of 2+ GB — and returned. The log ends cleanly after 19
lines; body_scan had completed and nothing crashed. But the refusal wrote NO end
record, so fifteen minutes later the stale-lock reaper found the lock, asked
existence_ledger.has_finished() (which only ever matched CYCLE_FINISHED), got
False, and wrote:

    CYCLE_DIED ... last step 'body_scan'

A deliberate safety abort entered the permanent history as a death, the morning
autopsy blamed a crash that never happened, and it spent a restart from the day's
budget.

The event name was not even new: core/survival_gate.py defined it, and
core/unclean_stop.py already listed it as terminal. Nothing on the homeostasis
path produced it. A constant with no producer is not wiring — the same shape of
bug as CYCLE_FINISHED before 2026-07-14.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import supervisor as sup                            # noqa: E402
from memory import existence_ledger as led          # noqa: E402

CFG = {"daily_hour": 3, "catchup_grace_hours": 20, "max_restarts_per_day": 2}
THE_NIGHT = "2026-08-24T03:04:02.258265+03:00"


def at(h, m=0, day=13):
    return datetime(2026, 7, day, h, m, tzinfo=timezone.utc)


def lock(pid=999, cycle_id="c1"):
    return {"pid": pid, "cycle_id": cycle_id, "started_utc": at(3).isoformat()}


def state(**kw):
    st = {"last_run_date": "2026-07-13", "restarts": {}, "refusals": {}}
    st.update(kw)
    return st


# ── the decision ────────────────────────────────────────────────────────────

def test_a_refused_cycle_is_cleared_without_a_death_record():
    """The headline: refusal on record -> clear the lock, write no death."""
    a = sup.decide(at(9), state(), None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False,
                   lock_cycle_refused=True)
    assert a.kind == sup.CLEAR_REFUSED_LOCK
    assert a.kind not in (sup.DEAD_LOCK_RETRY, sup.DEAD_LOCK_BUDGET_DONE)
    assert "REFUSED" in a.reason
    assert "not a death" in a.reason


def test_without_the_refusal_on_record_it_is_still_a_death():
    """The guard against over-correcting: a real death must stay a death."""
    a = sup.decide(at(9), state(), None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False,
                   lock_cycle_refused=False)
    assert a.kind == sup.DEAD_LOCK_RETRY
    assert "DIED" in a.reason


def test_a_refusal_does_not_satisfy_the_day():
    """Unlike a clean finish: no work was done, so the night is still owed."""
    a = sup.decide(at(9), state(), None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False,
                   lock_cycle_refused=True)
    assert "still owed" in a.reason
    # and it is NOT the benign-race path, which means the opposite about the day
    assert a.kind != sup.CLEAR_STALE_LOCK


def test_refusal_retries_are_bounded_so_a_full_disk_cannot_spawn_forever():
    """Un-satisfying the day makes the next tick spawn. That needs a ceiling."""
    spent = state(refusals={"2026-07-13": 2})
    a = sup.decide(at(9), spent, None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False,
                   lock_cycle_refused=True)
    assert a.kind == sup.REFUSED_BUDGET_DONE
    assert a.kind == sup.SURVIVAL_SLEEP, (
        "the old name and the new one must be the same kind, or a caller that "
        "imports one will silently stop matching the other")
    assert "SURVIVAL SLEEP" in a.reason
    assert "2/2" in a.reason, "the reason does not say how many were spent"


def test_refusals_are_counted_separately_from_restarts():
    """A refused night must not spend the budget that recovers a real death."""
    used_restarts = state(restarts={"2026-07-13": 2})
    a = sup.decide(at(9), used_restarts, None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False,
                   lock_cycle_refused=True)
    assert a.kind == sup.CLEAR_REFUSED_LOCK, (
        "a spent RESTART budget must not bound REFUSAL retries — they are "
        "different failures with different remedies")


# ── the producer ────────────────────────────────────────────────────────────

def test_the_runner_has_a_producer_for_the_refusal_record():
    """The 2026-07-14 lesson: a constant nothing writes is not wiring."""
    import fast_cycle_runner as fcr
    assert hasattr(fcr, "_seal_refusal_record")
    from core import survival_gate as sg
    assert hasattr(sg, "record_refusal")
    assert sg.EVENT == led.CYCLE_REFUSED == "CYCLE_REFUSED_SURVIVAL_GATE"


def test_the_homeostasis_refusal_calls_the_producer_before_returning():
    """ast, not a substring scan: the call must be on the refusing branch."""
    import ast
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if "can_start" not in ast.unparse(node.test):
            continue
        calls = [n for n in ast.walk(node)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "_seal_refusal_record"]
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        if calls and returns:
            found = True
    assert found, ("the homeostasis refusal branch must seal a refusal record "
                   "before it returns — a bare return is the bug this test "
                   "exists for")


def test_a_refusal_written_to_a_scratch_ledger_is_an_end_record(tmp_path,
                                                                monkeypatch):
    """End-to-end on the real writer, against a throwaway chain."""
    from core import survival_gate as sg
    monkeypatch.setattr(led, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    rec = sg.record_refusal(cycle_id="c-refused", gate="homeostasis",
                            reasons=["RAM 93% (1.0GB free)"])
    assert rec and rec["event"] == "CYCLE_REFUSED_SURVIVAL_GATE"
    assert rec["gate"] == "homeostasis"
    assert led.was_refused("c-refused") is True
    assert led.has_finished("c-refused") is False, (
        "a refusal must not read as a completed run")
    assert led.verify()["valid"] is True

    from core import unclean_stop as us
    assert "CYCLE_REFUSED_SURVIVAL_GATE" in us.END_EVENTS


def test_was_refused_does_not_claim_anything_about_a_nameless_cycle():
    assert led.was_refused(None) is False
    assert led.was_refused("") is False


# ── the correction to the real 24 Aug line ──────────────────────────────────

def test_the_24_aug_misclassification_is_corrected_by_appending_not_editing():
    """History stays. Exactly one correction, and seq 278 is untouched."""
    rows = led.read_all()
    by_seq = {e.get("seq"): e for e in rows}

    original = by_seq.get(278)
    assert original is not None
    assert original["event"] == "CYCLE_DIED", (
        "seq 278 must stand exactly as it was written — the ledger is corrected "
        "by appending, never by editing")
    assert original["cycle_id"] == THE_NIGHT

    corrections = [e for e in rows
                   if e.get("event") == led.CORRECTION
                   and e.get("corrects_seq") == 278]
    assert len(corrections) == 1, f"expected exactly one, got {len(corrections)}"
    c = corrections[0]
    assert c["should_have_been"] == "CYCLE_REFUSED_SURVIVAL_GATE"
    assert c["corrects_event"] == "CYCLE_DIED"
    assert c["corrects_hash"] == original["hash"], (
        "the correction must pin the exact line it corrects by hash")
    assert c["seq"] > 278
    assert led.verify()["valid"] is True


def test_a_correction_cannot_point_at_a_line_that_is_not_there(tmp_path,
                                                               monkeypatch):
    """A correction pointing at nothing looks like a reconciled record."""
    monkeypatch.setattr(led, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    led.append(led.CYCLE_STARTED, cycle_id="c1", pid=1, trigger="START")
    with pytest.raises(ValueError):
        led.record_correction(corrects_seq=999, should_have_been="WHATEVER",
                              detail="d", recorded_by="test")
