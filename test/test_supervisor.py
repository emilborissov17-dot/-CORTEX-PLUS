"""Permanent test suite for supervisor.decide() — the whole scheduling policy.

decide() is a PURE function of (now, state, heartbeat, lock, config), so the
entire policy is testable with no clock, no processes and no OS. That is the
point: it lets us assert the thing that actually matters, which is not "does it
kill hung cycles" but **"does it leave healthy ones alone"**.

THE FALSE-KILL REGRESSION
-------------------------
A single global 15-minute ceiling would murder healthy cycles: web_intelligence
legitimately runs for the better part of an hour and global_indicators hits 20
live HTTP APIs. A watchdog that kills those is worse than no watchdog at all —
it would guarantee the system never completes a cycle. Several tests below exist
solely to pin that down.
"""
from datetime import datetime, timedelta, timezone

import pytest

import supervisor as sup


CFG = {
    "daily_hour": 3,
    "catchup_grace_hours": 20,
    "max_restarts_per_day": 2,
    "step_ceilings_sec": {
        "_default": 900,
        "web_intelligence": 3600,
        "internet_intelligence": 2700,
    },
}


def at(h, m=0, day=13):
    return datetime(2026, 7, day, h, m, tzinfo=timezone.utc)


def beat(step, updated, pid=999, cycle_id="c1", index="1"):
    return {"pid": pid, "cycle_id": cycle_id, "step": step,
            "step_index": index, "updated_utc": updated.isoformat()}


def lock(pid=999, started=None, cycle_id="c1"):
    return {"pid": pid, "cycle_id": cycle_id,
            "started_utc": (started or at(3)).isoformat()}


def _silence_heartbeat(minutes: int = 20) -> None:
    """Backdate the heartbeat on disk so the cycle reads as SILENT.

    Why this exists (16 Aug 2026). The end-to-end death tests used to call
    hb.beat(...) and then assert the cycle was dead — a heartbeat written this
    instant, next to a claim that nothing is running. No machine can be in that
    state, and the impossibility was load-bearing: it let the supervisor's
    "dead pid -> dead cycle" rule pass its tests for a month while, on the real
    laptop, that rule buried 21 live cycles at exactly the 300-second mark.

    Death is now judged by SILENCE, so a test that wants a death must produce
    silence. Twenty minutes is comfortably past HEARTBEAT_ALIVE_CEILING (600s).
    """
    import json as _json
    from memory import heartbeat as _hb
    d = _hb.read() or {}
    d["updated_utc"] = (datetime.now(timezone.utc)
                        - timedelta(minutes=minutes)).isoformat()
    _hb.HEARTBEAT_PATH.write_text(_json.dumps(d, ensure_ascii=False, indent=2),
                                  encoding="utf-8")


def state(last_run_date=None, restarts=None, failure=None):
    return {"last_run_date": last_run_date, "last_run_utc": None,
            "restarts": restarts or {}, "failure": failure}


# ---------------------------------------------------------------------------
# Healthy cycles must be LEFT ALONE  (the false-kill regression)
# ---------------------------------------------------------------------------

def test_healthy_cycle_is_not_killed():
    now = at(3, 20)
    hb = beat("trend_tracker", now - timedelta(seconds=60))
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)
    assert a.kind == sup.NOTHING


def test_a_forty_minute_web_intelligence_step_is_not_killed():
    """THE regression. Its ceiling is 60 min; a global 15-min ceiling would have
    killed this healthy cycle."""
    now = at(3, 45)
    hb = beat("web_intelligence", now - timedelta(minutes=40))
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)
    assert a.kind == sup.NOTHING, "a healthy long-running step was killed"


def test_a_step_just_under_its_ceiling_is_not_killed():
    now = at(4)
    hb = beat("internet_intelligence", now - timedelta(seconds=2699))  # ceiling 2700
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)
    assert a.kind == sup.NOTHING


def test_an_unnamed_step_uses_the_default_ceiling():
    now = at(4)
    hb = beat("some_new_step", now - timedelta(seconds=899))   # default 900
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)
    assert a.kind == sup.NOTHING


def test_cycle_that_just_started_without_a_heartbeat_is_not_killed():
    now = at(3, 1)
    a = sup.decide(now, state("2026-07-13"), None, lock(started=at(3)), CFG,
                   lock_pid_alive=True)
    assert a.kind == sup.NOTHING


# ---------------------------------------------------------------------------
# Wedged cycles must be killed — with a REASON
# ---------------------------------------------------------------------------

@pytest.fixture
def livelocked(monkeypatch):
    """Make the kill policy see a process that is burning CPU with no I/O.

    Added 22 Aug 2026, when the watchdog stopped killing for slowness alone
    (core/kill_policy.py). A stale heartbeat past a ceiling no longer reaches
    the kill path by itself, so the tests below — which are about the RESTART
    BUDGET, not about why a kill happened — have to supply a cause that is still
    killable, or they would be silently testing nothing.
    """
    import core.kill_policy as kp

    def _livelocked(pid, step, priority=kp.NORMAL, degraded=False,
                    heartbeat_age_sec=0.0, ceiling_sec=900.0, **kw):
        return kp.Observation(step=step or "unknown", priority=priority,
                              degraded=degraded,
                              heartbeat_age_sec=heartbeat_age_sec,
                              ceiling_sec=ceiling_sec,
                              cpu_percent=99.0, io_idle_sec=120.0,
                              cuda_state="OK")

    monkeypatch.setattr(kp, "observe", _livelocked)


def test_a_stale_heartbeat_past_its_ceiling_is_NOT_killed():
    """REVERSED 22 Aug 2026. This asserted KILL_RESTART, which was the rule that
    produced 11 kills — internet_intelligence 6, daily_analysis 5 — every one a
    NORMAL step waiting on a model, each destroying the steps that followed.

    Slowness now has a better answer than death: core/step_budget marks the step
    DEGRADED and the cycle walks on. See core/kill_policy.py for the three causes
    that may still carry a kill.
    """
    now = at(4)
    hb = beat("trend_tracker", now - timedelta(seconds=1000))   # default ceiling 900
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)

    assert a.kind == sup.NOTHING, (
        f"a slow NORMAL step was still killed ({a.kind}): {a.reason}")
    assert "not killable" in a.reason


def test_a_livelocked_cycle_is_still_killed(livelocked):
    """The kill did not disappear — it acquired a reason."""
    now = at(4)
    hb = beat("trend_tracker", now - timedelta(seconds=1000))
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)

    assert a.kind == sup.KILL_RESTART
    assert a.wedged_step == "trend_tracker"
    assert a.ceiling_sec == 900
    assert a.heartbeat_age_sec == pytest.approx(1000, abs=2)


def test_kill_records_which_step_and_by_how_much(livelocked):
    """A future agent needs to know WHY it was restarted, not just that it was."""
    now = at(5)
    hb = beat("web_intelligence", now - timedelta(seconds=3700))  # ceiling 3600
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)

    assert a.kind == sup.KILL_RESTART
    assert a.wedged_step == "web_intelligence"
    assert a.ceiling_sec == 3600
    assert "web_intelligence" in a.reason and "3600" in a.reason


def test_alive_cycle_that_never_beats_is_eventually_killed():
    """A process that started and then wedged before its first beat must not be
    immortal just because it never produced a heartbeat to go stale."""
    now = at(4)
    a = sup.decide(now, state("2026-07-13"), None, lock(started=at(3)), CFG,
                   lock_pid_alive=True)
    assert a.kind == sup.KILL_RESTART
    assert "never written a heartbeat" in a.reason


# ---------------------------------------------------------------------------
# Restart budget
# ---------------------------------------------------------------------------

def test_second_restart_is_allowed(livelocked):
    now = at(4)
    hb = beat("x", now - timedelta(seconds=1000))
    a = sup.decide(now, state("2026-07-13", restarts={"2026-07-13": 1}), hb, lock(),
                   CFG, lock_pid_alive=True)
    assert a.kind == sup.KILL_RESTART


def test_third_restart_fails_loudly_instead_of_restarting(livelocked):
    now = at(4)
    hb = beat("x", now - timedelta(seconds=1000))
    a = sup.decide(now, state("2026-07-13", restarts={"2026-07-13": 2}), hb, lock(),
                   CFG, lock_pid_alive=True)

    assert a.kind == sup.KILL_BUDGET_DONE
    assert "budget" in a.reason.lower()


def test_yesterdays_restarts_do_not_count_against_today(livelocked):
    now = at(4)
    hb = beat("x", now - timedelta(seconds=1000))
    a = sup.decide(now, state("2026-07-13", restarts={"2026-07-12": 2}), hb, lock(),
                   CFG, lock_pid_alive=True)
    assert a.kind == sup.KILL_RESTART


def test_after_budget_exhaustion_no_new_cycle_is_started():
    """The system must stay down and visible, not silently limp on."""
    now = at(10)
    st = state(last_run_date=None, failure={"date": "2026-07-13", "reason": "wedged"})
    a = sup.decide(now, st, None, None, CFG)
    assert a.kind == sup.NOTHING
    assert "human" in a.reason.lower()


# ---------------------------------------------------------------------------
# Daily schedule + catch-up
# ---------------------------------------------------------------------------

def test_before_the_scheduled_hour_nothing_happens():
    a = sup.decide(at(2, 30), state(), None, None, CFG)
    assert a.kind == sup.NOTHING


def test_at_the_scheduled_hour_the_cycle_starts():
    a = sup.decide(at(3, 2), state(), None, None, CFG)
    assert a.kind == sup.START


def test_already_ran_today_does_nothing():
    a = sup.decide(at(14), state(last_run_date="2026-07-13"), None, None, CFG)
    assert a.kind == sup.NOTHING


def test_machine_booted_late_triggers_catchup():
    """THE catch-up case: the laptop was off at 03:00 and boots at 09:40."""
    a = sup.decide(at(9, 40), state(last_run_date="2026-07-12"), None, None, CFG)

    assert a.kind == sup.CATCHUP
    assert a.details["late_by_hours"] == pytest.approx(6.67, abs=0.05)
    assert a.scheduled_for.startswith("2026-07-13T03:00")


def test_catchup_at_the_edge_of_the_grace_window():
    a = sup.decide(at(22, 59), state(last_run_date="2026-07-12"), None, None, CFG)
    assert a.kind == sup.CATCHUP   # 19.98h late, grace is 20h


def test_past_the_grace_window_the_day_is_skipped_not_run():
    """Starting a multi-hour cycle at 23:55 would collide with tomorrow's."""
    a = sup.decide(at(23, 55), state(last_run_date="2026-07-12"), None, None, CFG)

    assert a.kind == sup.SKIP_MISSED
    assert "grace" in a.reason


def test_a_skipped_day_is_still_an_event():
    """A day with no cycle is a fact about the system's existence and must be
    recorded, not silently dropped."""
    a = sup.decide(at(23, 55), state(last_run_date="2026-07-12"), None, None, CFG)
    assert a.kind == sup.SKIP_MISSED
    assert a.scheduled_for is not None


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------

def test_live_lock_prevents_a_second_cycle():
    """req 5: a new cycle must never start while one is running."""
    now = at(9)
    hb = beat("internet_intelligence", now - timedelta(seconds=30))
    a = sup.decide(now, state(last_run_date=None), hb, lock(), CFG, lock_pid_alive=True)
    assert a.kind == sup.NOTHING, "started a second cycle on top of a running one"


def test_dead_lock_from_a_cleanly_finished_cycle_is_just_cleared():
    """The benign race: the runner sealed CYCLE_FINISHED and then died before it
    could unlink its own lock. Its work is done — clear the orphan, do NOT retry."""
    a = sup.decide(at(9), state(last_run_date="2026-07-13"), None, lock(pid=4321),
                   CFG, lock_pid_alive=False, lock_cycle_finished=True)
    assert a.kind == sup.CLEAR_STALE_LOCK


def test_dead_lock_from_a_died_cycle_is_recorded_and_retried():
    """No CYCLE_FINISHED on record: the cycle DIED mid-run (OOM, power loss). It
    must not be counted as today's run — it is recorded and retried within budget.

    This is the 2026-07-15 bug: a died cycle used to satisfy the daily gate, so
    nothing retried and no death was ever recorded."""
    a = sup.decide(at(9), state(last_run_date="2026-07-13"), None, lock(pid=4321),
                   CFG, lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind == sup.DEAD_LOCK_RETRY
    assert "DIED" in a.reason


def test_a_died_cycle_records_its_last_step_from_the_heartbeat():
    """A death should still answer 'which step killed me?' — from the last beat.

    SETUP CORRECTED 16 Aug 2026, and the correction is the point of the whole day.
    This test used to beat 5 minutes ago while asserting the cycle was dead. That
    is not a state a real machine can be in: a process that no probe can find, yet
    which wrote a file 300 seconds ago. The impossible setup was not harmless — it
    is what let `not lock_pid_alive -> death` look correct for a month while, on
    the real machine, it buried 21 live cycles at exactly the 300-second mark.
    A test may only assert on a state the world can actually produce.
    So: silent for 20 minutes, which is past HEARTBEAT_ALIVE_CEILING (600s). NOW
    it is dead, and the death is judged on the cycle's own silence rather than on
    a launcher stub's pid.
    """
    now = at(9)
    hb = beat("web_intelligence", now - timedelta(minutes=20))  # its own heartbeat
    a = sup.decide(now, state(last_run_date="2026-07-13"), hb, lock(pid=4321),
                   CFG, lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind == sup.DEAD_LOCK_RETRY
    assert a.wedged_step == "web_intelligence"


def test_a_live_cycle_is_not_buried_when_the_launcher_pid_dies():
    """THE 2026-08-16 bug, stated as the regression it is.

    On this machine venv\\Scripts\\python.exe is a launcher: it spawns the real
    interpreter and exits, so the pid Popen handed the supervisor is dead within
    seconds of a perfectly healthy start. Measured: Popen.pid=85400, child
    os.getpid()=97752. From the ledger: 21 of 33 CYCLE_DIED landed at EXACTLY 300s
    — one tick — and the named ones carried live step names.

    Two independent rescues, and this test demands BOTH, because either alone
    leaves a hole: without the pid check a legitimate one-hour step dies at 600s;
    without the ceiling a cycle that died inside a 3600s step waits 59 minutes to
    be noticed.
    """
    now = at(3, 20)
    # (1) the cycle's own pid answers — no ceiling applies, however long the step
    hb = beat("web_intelligence", now - timedelta(minutes=50))
    a = sup.decide(now, state("2026-07-13"), hb, lock(pid=4321), CFG,
                   lock_pid_alive=False, heartbeat_pid_alive=True)
    assert a.kind == sup.NOTHING, "a live cycle was buried on a dead launcher pid"
    # ...but the compromise must SAY it is one. A live pid over a heart that
    # stopped 50 minutes ago is an anomaly we are choosing not to act on, and an
    # unrecorded choice is indistinguishable from not having noticed.
    assert "process_alive_but_heart_stopped" in a.reason, \
        "the anomaly was swallowed instead of recorded"

    # (2) pid unconfirmed, but it beat inside the global ceiling
    hb = beat("web_intelligence", now - timedelta(seconds=120))
    a = sup.decide(now, state("2026-07-13"), hb, lock(pid=4321), CFG,
                   lock_pid_alive=False, heartbeat_pid_alive=False)
    assert a.kind == sup.NOTHING

    # ...and the mercy is BOUNDED: silence past the global ceiling is still death,
    # even though the step's own ceiling is an hour. Otherwise "rescue from a false
    # death" quietly becomes "acceptance of a real one".
    hb = beat("web_intelligence", now - timedelta(seconds=900))
    a = sup.decide(now, state("2026-07-13"), hb, lock(pid=4321), CFG,
                   lock_pid_alive=False, heartbeat_pid_alive=False)
    assert a.kind == sup.DEAD_LOCK_RETRY


def test_a_retired_heartbeat_does_not_resurrect_its_own_cycle():
    """The heartbeat now SURVIVES the death it documents (it is the autopsy). That
    creates a trap: the record of where a cycle stopped must never be read as proof
    that one is running, or the evidence would resurrect the corpse."""
    now = at(9)
    hb = beat("scoring_engine", now - timedelta(seconds=10))
    hb["retired_utc"] = now.isoformat()
    hb["retired_by"] = "supervisor:dead_lock"
    a = sup.decide(now, state(last_run_date="2026-07-13"), hb, lock(pid=4321), CFG,
                   lock_pid_alive=False, heartbeat_pid_alive=True)
    assert a.kind == sup.DEAD_LOCK_RETRY, "a retired heartbeat vouched for a corpse"


def test_a_stale_heartbeat_from_another_cycle_is_not_attributed_to_the_death():
    """A heartbeat left by an EARLIER cycle must not be recorded as this death's
    last step — better 'unknown' than a plausible-sounding wrong answer."""
    now = at(9)
    hb = beat("trend_tracker", now, cycle_id="an-older-cycle")
    a = sup.decide(now, state(last_run_date="2026-07-13"), hb,
                   lock(pid=4321, cycle_id="the-dead-cycle"),
                   CFG, lock_pid_alive=False, lock_cycle_finished=False)
    assert a.wedged_step == "unknown"


def test_a_died_cycle_is_never_killed_only_recorded_and_retried():
    """The PID may have been RECYCLED onto an unrelated process. The dead-lock path
    must never issue a taskkill — clearing and retrying is safe; killing whatever
    holds a recycled PID would be a serious bug."""
    a = sup.decide(at(9), state(), None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind not in (sup.KILL_RESTART, sup.KILL_BUDGET_DONE)


def test_a_died_cycle_stops_retrying_once_the_budget_is_spent():
    """A cycle that dies on every attempt must become a visible failure, not an
    invisible restart loop. Same budget as kill-restarts, same reason."""
    a = sup.decide(at(9), state(last_run_date="2026-07-13", restarts={"2026-07-13": 2}),
                   None, lock(pid=4321), CFG,
                   lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind == sup.DEAD_LOCK_BUDGET_DONE
    assert "budget" in a.reason.lower()


def test_corrupt_lock_is_retried_since_it_cannot_be_proven_finished():
    """A lock we could not even parse has no CYCLE_FINISHED we can match, so we
    cannot claim it finished. Conservatively: record a death and retry within
    budget, rather than silently counting the day as done."""
    a = sup.decide(at(9), state(), None, {"pid": None, "corrupt": True}, CFG,
                   lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind == sup.DEAD_LOCK_RETRY


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_ceiling_lookup_prefers_the_named_step():
    assert sup.ceiling_for("web_intelligence", CFG) == 3600
    assert sup.ceiling_for("anything_else", CFG) == 900
    assert sup.ceiling_for(None, CFG) == 900


def test_real_config_file_parses_and_covers_the_slow_steps():
    cfg = sup.load_config()
    ceilings = cfg["step_ceilings_sec"]
    assert ceilings["_default"] == 900, "the specified default is 15 minutes"
    # The steps that would otherwise be false-killed.
    for slow in ("web_intelligence", "internet_intelligence", "global_indicators"):
        assert ceilings.get(slow, 0) > 900, f"{slow} needs a raised ceiling or it will be false-killed"


# ---------------------------------------------------------------------------
# --mark-ran-today
# ---------------------------------------------------------------------------

@pytest.fixture
def sandboxed_supervisor(tmp_path, monkeypatch):
    """Point supervisor + ledger state at a throwaway dir."""
    from memory import existence_ledger as el

    monkeypatch.setattr(sup, "STATE_PATH", tmp_path / "scheduler_state.json")
    monkeypatch.setattr(sup, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    monkeypatch.setattr(el, "LEDGER_PATH", tmp_path / "existence_ledger.jsonl")
    # tick() appends one telemetry row per call (core/body_sensorium.py). Into
    # tmp_path, not into the live memory/body_sensorium/ — caught by the
    # write-surface guard the first time this was wired without it.
    monkeypatch.setattr(sup, "BODY_SENSE_DIR", tmp_path / "body_sensorium")
    return tmp_path


def test_mark_ran_today_suppresses_the_catchup(sandboxed_supervisor):
    """The reason it exists: installing at midday must not immediately fire a
    catch-up cycle if the human does not want one."""
    from memory import existence_ledger as el

    # Before: a catch-up would fire.
    now = at(12)
    assert sup.decide(now, sup.load_state(), None, None, CFG).kind == sup.CATCHUP

    sup.cmd_mark_ran_today()

    # After: quiet until tomorrow.
    today = datetime.now().astimezone().date().isoformat()
    st = sup.load_state()
    assert st["last_run_date"] == today

    a = sup.decide(datetime.now().astimezone(), st, None, None, CFG)
    assert a.kind == sup.NOTHING


def test_mark_ran_today_does_not_fabricate_a_completed_cycle(sandboxed_supervisor):
    """THE property. It must not write CYCLE_STARTED/CYCLE_FINISHED — that would
    be the system inventing a cycle it never ran, which is exactly the kind of
    lie the existence ledger exists to make impossible."""
    from memory import existence_ledger as el

    sup.cmd_mark_ran_today()

    events = el.read_all()
    kinds = [e["event"] for e in events]

    assert kinds == [el.CATCHUP_SUPPRESSED]
    assert el.CYCLE_STARTED not in kinds
    assert el.CYCLE_FINISHED not in kinds

    s = el.summary()
    assert s["total_cycles_started"] == 0, "no cycle ran; none may be claimed"
    assert s["total_cycles_finished"] == 0


def test_mark_ran_today_records_that_a_human_decided(sandboxed_supervisor):
    """A future agent must not read a human's choice as its own decision."""
    from memory import existence_ledger as el

    sup.cmd_mark_ran_today()

    ev = el.head()
    assert ev["event"] == el.CATCHUP_SUPPRESSED
    assert "human" in ev["detail"].lower()
    assert ev["date"]


def test_mark_ran_today_leaves_last_run_utc_honest(sandboxed_supervisor):
    """last_run_date is set (that is its job), but last_run_utc must stay None:
    no cycle actually ran at any time."""
    sup.cmd_mark_ran_today()
    assert sup.load_state()["last_run_utc"] is None


def test_mark_ran_today_is_idempotent(sandboxed_supervisor):
    from memory import existence_ledger as el

    sup.cmd_mark_ran_today()
    sup.cmd_mark_ran_today()

    assert len(el.read_all()) == 1, "a second call must not append another event"


def test_mark_ran_today_refuses_while_a_cycle_is_running(sandboxed_supervisor, monkeypatch):
    """Marking today as run mid-cycle would let a SECOND cycle start as soon as
    this one released its lock."""
    sup.write_lock(pid=1234, cycle_id="c1")
    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: True)

    with pytest.raises(SystemExit):
        sup.cmd_mark_ran_today()

    assert sup.load_state().get("last_run_date") is None


def test_mark_ran_today_keeps_the_ledger_chain_valid(sandboxed_supervisor):
    from memory import existence_ledger as el
    sup.cmd_mark_ran_today()
    assert el.verify()["valid"] is True


# ---------------------------------------------------------------------------
# The autonomy boundary (req 6)
# ---------------------------------------------------------------------------

def test_supervisor_is_in_the_protected_denylist():
    """The thing that decides WHETHER the system runs must not be writable by
    the system it runs."""
    from safety.protected_paths import is_protected
    assert is_protected("supervisor.py")
    assert is_protected("config/scheduler.json")


def test_supervisor_makes_no_llm_call():
    """It cannot form an intention; it can only observe a clock and a file."""
    src = open(sup.__file__, encoding="utf-8").read()
    for forbidden in ("call_groq", "groq_backend", "openai", "llm", "MerkleMemory"):
        assert forbidden not in src.replace("# ", ""), \
            f"supervisor must not reference {forbidden}"


def test_a_test_can_never_fire_a_real_alarm(tick_sandbox, monkeypatch):
    """THE 16 AUGUST 2026 ACCIDENT, pinned so it cannot happen twice.

    That day a test reached the branch that wakes the human, and every safety
    assumption held except the ones that mattered:
      * it read the REAL memory/notify_channel.json, token and chat id included;
      * it POSTed to api.telegram.org and the message ARRIVED on the phone —
        confirmed by the human, not inferred — describing a failure with a
        fabricated pid that had never occurred;
      * it then stamped the real dedup file, which SUPPRESSED the day's genuine
        alarm on a day the supervisor was already at an exhausted restart budget.

    So the test disarmed the alarm. That is the failure mode worth a permanent
    test: not "did we send the wrong message" but "can a test silence the thing
    that wakes a human when the system dies".

    This forces the dangerous path deliberately — quiet hours off, an already
    populated stamp file — and asserts nothing leaves the sandbox.
    """
    import sys
    import types

    monkeypatch.setattr(sup, "_quiet_now", lambda: False)   # force the SENDING path

    # A requests module that refuses to be used. If alarm_human ever finds
    # credentials in a test again, this fails loudly instead of dialling out.
    # NOTE, and this detail is the whole lesson of the day in miniature: a
    # poisoned requests.post that merely RAISES proves nothing here, because
    # alarm_human's body is wrapped in `except Exception: pass`. The raise would be
    # swallowed, no stamp would be written, and the test would go green — for the
    # wrong reason, having actually reached the network. So the attempt is RECORDED
    # in a list that no exception handler can reach, and the list is what is
    # asserted on. Verified by reverting the fix and watching this go red.
    attempts = []
    poisoned = types.ModuleType("requests")

    def _record_then_refuse(*a, **k):
        attempts.append(a[0] if a else "?")
        raise AssertionError("network call from a test")

    poisoned.post = _record_then_refuse
    monkeypatch.setitem(sys.modules, "requests", poisoned)

    sup.alarm_human("СИСТЕМАТА НЕ РАБОТИ — рестартите за деня свършиха",
                    "fabricated detail from a test")

    assert not attempts, (
        "a test reached the network through alarm_human — this is exactly the "
        "16 Aug 2026 accident, which put a fabricated failure on the human's phone "
        f"and suppressed that day's real alarm. Called: {attempts}")
    assert not sup.ALARM_STAMP.exists(), \
        "a test stamped the alarm dedup file; the next REAL alarm would be swallowed"
    assert sup.NIGHT_LOG.exists(), "the night event should still be recorded — in the sandbox"
    assert str(tick_sandbox) in str(sup.NIGHT_LOG), "the night event escaped the sandbox"


def test_supervisor_never_writes_outside_its_permitted_surface():
    """Enumerated in the design: heartbeat/lock/ledger/state/log. Nothing else.

    WIDENED 16 Aug 2026, because it was narrower than it read. It scanned only
    `X.write_text(...)` / `X.write_bytes(...)`. But night_events.jsonl is written
    like this:

        with open(NIGHT_LOG, "a", encoding="utf-8") as fh:

    — an append through open(), completely invisible to the old scan. So the test
    that exists to enumerate the whole write surface did not see appends at all,
    and NIGHT_LOG sat outside the enumeration while the test shone green. On the
    same day a test wrote a fabricated failure into that very file.

    A guard that inspects one of the two ways to write a file is not a guard; it is
    a decoration. Both are checked now.
    """
    import ast
    src = open(sup.__file__, encoding="utf-8").read()
    tree = ast.parse(src)

    written = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("write_text", "write_bytes"):
                tgt = node.func.value
                if isinstance(tgt, ast.Name):
                    written.add(tgt.id)
            # Path.open("w"/"a") — the same hole in its method form
            if node.func.attr == "open" and isinstance(node.func.value, ast.Name):
                mode = node.args[0] if node.args else None
                if isinstance(mode, ast.Constant) and any(
                        c in str(mode.value) for c in ("w", "a", "x", "+")):
                    written.add(node.func.value.id)
        # os.replace(tmp, NAME) / os.rename / shutil.move — the DESTINATION is a
        # write, and it is how every atomic write in this codebase is performed
        # (memory/heartbeat.py writes its file exactly this way: tempfile, then
        # os.replace). Kimi flagged it as the one omission worth closing: without
        # it the most important files in the system are invisible to this guard.
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("replace", "rename", "move", "copy",
                                       "copyfile", "copy2") \
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Name):
            written.add(node.args[1].id)
        # builtin open(NAME, "a") — how night_events.jsonl is written
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "open" and node.args:
            mode = node.args[1] if len(node.args) > 1 else None
            for kw in node.keywords:
                if kw.arg == "mode":
                    mode = kw.value
            is_write = isinstance(mode, ast.Constant) and any(
                c in str(mode.value) for c in ("w", "a", "x", "+"))
            if is_write and isinstance(node.args[0], ast.Name):
                written.add(node.args[0].id)

    allowed = {
        "LOCK_PATH", "STATE_PATH", "LOG_PATH", "CONFIG_PATH",
        # Added 16 Aug 2026 — NOT to make the test pass, but because this test had
        # been RED on the machine for weeks and nobody was running it, which makes
        # an enumerated surface worth exactly nothing. Each new name is admitted
        # deliberately, with what it is and why it is harmless:
        "METTA_CHECK_FILE",   # memory/metta_bridge_check.json — the result of the
                              # 6-hourly MeTTa bridge probe. Written by the
                              # supervisor because it is the only process that runs
                              # on this machine every 5 minutes. Read by humans and
                              # by the report; nothing in the cycle branches on it.
        "ALARM_STAMP",        # memory/alarm_sent.json — the "I already woke the
                              # human about this" marker that stops one failure
                              # from sending the same alarm every five minutes.
                              # Was an inline `stamp = BASE / ...` until 16 Aug, so
                              # it appeared here under a local variable's name — a
                              # constant with an alias is a constant in disguise.
        # Found by the widened scan on 16 Aug 2026 — both were being written all
        # along through open(), where the old check could not see them:
        "NIGHT_LOG",          # memory/night_events.jsonl — appended by
                              # note_night_event(); the record of what happened
                              # while the human slept, read back by cycle_report.
                              # This is the file a test poisoned on 16 Aug.
        "log_file",           # memory/cycle_logs/cycle_<stamp>.log — opened for the
                              # spawned cycle's stdout. The supervisor opens the
                              # handle; everything inside is written by the cycle.
    }
    assert written <= allowed, (
        f"supervisor writes to unexpected targets: {written - allowed}. "
        f"If the write is legitimate, ADD IT HERE WITH A REASON — do not widen "
        f"the set silently. The point of this test is that the surface stays "
        f"enumerated by a human, not discovered after the fact.")


# ---------------------------------------------------------------------------
# Fix 2 — a cycle that DIED must be recorded and retried, end to end
# ---------------------------------------------------------------------------

@pytest.fixture
def tick_sandbox(tmp_path, monkeypatch):
    """Point every surface tick() touches at a throwaway dir.

    WHAT THIS FIXTURE COST BEFORE IT WAS FIXED (16 August 2026)
    -----------------------------------------------------------
    It used to redirect six paths and it looked complete. Then the suite was run on
    the real machine for the first time in weeks, and the one test that reaches the
    budget-exhausted branch did all of this to LIVE state:

      * wrote a fabricated system-failure event (pid=4321, step 'scoring_engine' —
        the fixture's invented values) into the real memory/night_events.jsonl,
        which core/cycle_report.py reads for the "what happened overnight" section;
      * called the real local model for an autopsy, taking 5m53s of the 5m56s run;
      * sent a REAL Telegram alarm to the human's phone about a failure that had
        not happened;
      * and stamped the real memory/alarm_sent.json — whose dedup key is
        `date:subject[:40]` — thereby SUPPRESSING the day's genuine alarm on a day
        the supervisor was already sitting at an exhausted restart budget.

    The last one is the worst: a test quietly disarmed the alarm that exists to wake
    a human when the system dies.

    None of it was caught by review, and none of it could be caught by running the
    suite in a cloud container, where `core` is absent, no local model answers and
    api.telegram.org is unreachable — there every one of these calls fails silently
    into an `except Exception: pass`. Green there, live rounds here.

    THE FIX IS NOT "ADD THE TWO MISSING PATHS"
    ------------------------------------------
    That is what produced the hole: a hand-kept list that looked exhaustive. Two
    things changed instead:

      1. `alarm_human()` no longer builds its paths inline. NOTIFY_CHANNEL and
         ALARM_STAMP are module constants, so this fixture can redirect them — and
         once NOTIFY_CHANNEL points at an empty temp dir there is no token to find,
         so the function returns BEFORE the network call. The capability is removed
         rather than the call stubbed.
      2. test_the_sandbox_covers_every_writable_path_in_the_supervisor below reads
         the module's own constants and fails if any of them still points at the
         real repo while this fixture is active. The next path someone adds is
         covered automatically, or the suite goes red. No more hand-kept list.
    """
    from memory import existence_ledger as el
    from memory import heartbeat as hb

    monkeypatch.setattr(sup, "STATE_PATH", tmp_path / "scheduler_state.json")
    monkeypatch.setattr(sup, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    monkeypatch.setattr(sup, "NOTIFY_CHANNEL", tmp_path / "notify_channel.json")
    monkeypatch.setattr(sup, "ALARM_STAMP", tmp_path / "alarm_sent.json")
    monkeypatch.setattr(sup, "EXTRAORDINARY_PATH", tmp_path / "extraordinary_request.json")
    monkeypatch.setattr(sup, "METTA_CHECK_FILE", tmp_path / "metta_bridge_check.json")
    monkeypatch.setattr(sup, "CYCLE_EXIT_PATH", tmp_path / "cycle_exit.json")
    monkeypatch.setattr(sup, "OUTBOX", tmp_path / "outbox")
    # 21 Aug 2026: tick() now appends a telemetry row per call
    # (core/body_sensorium.py). It was wired calling tick() with no argument, so
    # it used the module default and four tests here wrote into the LIVE
    # memory/body_sensorium/. The write-surface guard named the file within
    # minutes, and the meta-test below went red because the constant still
    # pointed at the repo — which is precisely what item 2 of this docstring
    # promises. The mechanism was not bypassed; it was used.
    monkeypatch.setattr(sup, "BODY_SENSE_DIR", tmp_path / "body_sensorium")
    monkeypatch.setattr(sup, "OUTBOX_SENT", tmp_path / "outbox" / "sent")
    monkeypatch.setattr(el, "LEDGER_PATH", tmp_path / "existence_ledger.jsonl")
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")

    # The autopsy calls a local model over HTTP. Left live it took 5m53s of a 5m56s
    # run — and a suite that takes six minutes is a suite nobody runs, which is how
    # every defect in this file survived a month.
    #
    #   Kimi, 16 Aug 2026: „Мокнете, не заглушавайте. Вместо да премахвате _autopsy
    #   от пътя, заменете я в тестовата среда."
    #
    # So it is RECORDED, not deleted: the branch still calls it, the call lands in
    # _AUTOPSY_CALLS, and the integration test asserts it happened. The difference
    # matters — a stub that returns a string proves the code did not crash; a mock
    # that records proves the code still asks. Only the six minutes are removed.
    #
    # HONEST SCOPE: this mocks sup._autopsy, not core.self_diagnosis.diagnose one
    # layer deeper. What the diagnosis DOES with evidence is core's subject and
    # belongs in core's own test, with the model mocked there.
    _AUTOPSY_CALLS.clear()

    def _recording_autopsy(action):
        _AUTOPSY_CALLS.append(action)
        return "(autopsy mocked in tests — the real one calls a local model over HTTP)"

    monkeypatch.setattr(sup, "_autopsy", _recording_autopsy)
    return tmp_path


# Filled by tick_sandbox's mock, asserted by the integration test below.
_AUTOPSY_CALLS = []


# The module-level paths the supervisor may write to. Anything under memory/ or
# logs/ must be redirected by tick_sandbox; anything else must be justified here.
_NOT_WRITTEN_BY_SUPERVISOR = {
    "CONFIG_PATH",   # config/scheduler.json — human-owned, read-only to the machine
    "RUNNER",        # fast_cycle_runner.py — spawned, never written
    "PYTHON",        # venv interpreter — spawned, never written
    # BASE is the repo root. It is never written to AS A PATH — but read the
    # warning, because it is how the 16 August accident became possible: every
    # inline `BASE / "memory" / "something.json"` built inside a function body is a
    # write surface that no fixture can redirect and no scan of these constants can
    # see. If you are about to write `BASE / ...` inside a function, stop and make
    # it a module constant instead. That single rule is what closed this hole.
    "BASE",
}


def test_the_sandbox_covers_every_writable_path_in_the_supervisor(tick_sandbox):
    """The fixture must be exhaustive BY CHECK, not by good intentions.

    On 16 Aug 2026 the hand-kept list in tick_sandbox missed NIGHT_LOG and the
    alarm stamp, and a test wrote to real memory and fired a real alarm. Counting
    on the next person to remember is what failed. This walks the supervisor's own
    module constants and fails if any writable one still points at the live repo.
    """
    from pathlib import Path

    tmp = Path(tick_sandbox).resolve()
    escaped = []
    for name in dir(sup):
        if not name.isupper():
            continue
        val = getattr(sup, name)
        if not isinstance(val, Path):
            continue
        if name in _NOT_WRITTEN_BY_SUPERVISOR:
            continue
        try:
            val.resolve().relative_to(tmp)
        except ValueError:
            escaped.append(f"{name} -> {val}")

    assert not escaped, (
        "these supervisor paths are NOT redirected by tick_sandbox, so a test can "
        "write to the live system through them:\n  " + "\n  ".join(escaped) +
        "\n\nAdd a monkeypatch.setattr line to tick_sandbox, or — if the path is "
        "genuinely never written by the supervisor — name it in "
        "_NOT_WRITTEN_BY_SUPERVISOR with the reason. Do not delete this test.")


def _today():
    return datetime.now().astimezone().date().isoformat()


def test_tick_records_a_death_and_retries_the_day(tick_sandbox, monkeypatch):
    """THE 2026-07-15 bug, end to end. A cycle started today, wrote a heartbeat,
    then died (OOM at 99% RAM): a stale lock with no CYCLE_FINISHED. It used to
    still satisfy the daily gate — no death recorded, no retry. Now:
      * CYCLE_DIED lands in the ledger, naming the step it died in, and
      * the day is un-satisfied so the ordinary daily logic retries within budget.
    """
    from memory import existence_ledger as el
    from memory import heartbeat as hb

    today = _today()
    el.append(el.CYCLE_STARTED, cycle_id="dead-1", pid=4321, trigger="CATCHUP")
    hb.beat("web_intelligence", 12, cycle_id="dead-1")
    _silence_heartbeat(minutes=20)      # see the helper: a corpse does not beat
    sup.write_lock(pid=4321, cycle_id="dead-1")
    st = sup.load_state(); st["last_run_date"] = today; sup.save_state(st)

    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: False)

    action = sup.tick()
    assert action.kind == sup.DEAD_LOCK_RETRY

    events = el.read_all()
    died = [e for e in events if e["event"] == el.CYCLE_DIED]
    assert len(died) == 1, "the death was not recorded"
    assert died[0]["cycle_id"] == "dead-1"
    assert died[0]["last_step"] == "web_intelligence"

    st = sup.load_state()
    assert st["last_run_date"] is None, "a death must not count as today's run"
    assert st["restarts"][today] == 1, "the retry must spend one unit of budget"

    # The lock is gone and the chain is intact — but the HEARTBEAT SURVIVES.
    # Changed 16 Aug 2026 (Kimi): „Heartbeat се чисти само при KeyboardInterrupt и
    # при CYCLE_FINISHED." Deleting it here used to erase the only record of where
    # the cycle was, which is exactly why nine of twelve deaths in the live ledger
    # read last_step=unknown: the previous tick had already thrown the evidence
    # away. It is now RETIRED — kept, and stamped with who ended it.
    assert not sup.LOCK_PATH.exists()
    _hb = hb.read()
    assert _hb is not None, "the autopsy evidence was destroyed"
    assert _hb.get("retired_utc"), "the heartbeat was left looking alive"
    assert _hb.get("step") == "web_intelligence", "the death lost its location"
    assert el.verify()["valid"] is True

    # ...and the very next decision, given the un-satisfied day, retries.
    retry = sup.decide(at(9), sup.load_state(), None, None, CFG)
    assert retry.kind in (sup.START, sup.CATCHUP)


def test_tick_does_not_retry_a_cleanly_finished_cycle(tick_sandbox, monkeypatch):
    """The benign race: a cycle sealed CYCLE_FINISHED and then died before it could
    unlink its lock. Its work is DONE. No CYCLE_DIED, no retry — the day stays
    satisfied. A clean finish must stay exactly as it was."""
    from memory import existence_ledger as el

    today = _today()
    el.append(el.CYCLE_STARTED, cycle_id="clean-1", pid=4321, trigger="CATCHUP")
    el.append(el.CYCLE_FINISHED, cycle_id="clean-1", pid=4321, duration_sec=1234.0)
    sup.write_lock(pid=4321, cycle_id="clean-1")
    st = sup.load_state(); st["last_run_date"] = today; sup.save_state(st)

    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: False)

    action = sup.tick()
    assert action.kind == sup.CLEAR_STALE_LOCK

    kinds = [e["event"] for e in el.read_all()]
    assert el.CYCLE_DIED not in kinds, "a cleanly-finished cycle was recorded as a death"

    st = sup.load_state()
    assert st["last_run_date"] == today, "a finished cycle's day must stay satisfied"
    assert st.get("restarts", {}).get(today, 0) == 0, "a finished cycle must not be retried"
    assert not sup.LOCK_PATH.exists()
    assert el.verify()["valid"] is True


def test_budget_exhaustion_is_decided_without_touching_anything():
    """THE UNIT HALF (split out 16 Aug 2026, on Kimi's instruction).

    The old single test bundled two questions: "is the decision right?" and "does
    the system then do the right things?" The first needs no files, no model and no
    network; the second needs all three mocked. Bundled, the fast half was hostage
    to the slow half — and the slow half is why the suite took 5m53s and therefore
    went unrun for a month, which is how every defect in this file survived.

    This half is pure: decide() sees a dead cycle with the day's budget spent and
    must refuse to retry.
    """
    now = at(9)
    hb = beat("scoring_engine", now - timedelta(minutes=20))
    a = sup.decide(now, state("2026-07-13", restarts={"2026-07-13": 2}), hb,
                   lock(pid=4321), CFG, lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind == sup.DEAD_LOCK_BUDGET_DONE
    assert "budget" in a.reason.lower()


def test_tick_stops_after_repeated_deaths_exhaust_the_budget(tick_sandbox, monkeypatch):
    """THE INTEGRATION HALF. A cycle that dies on every attempt must become a
    VISIBLE failure, not an invisible restart loop. Once the budget is spent the
    death is still recorded, but the system stays down and waits for a human.

    This is the only test that reaches the branch which wakes a human, so it is the
    one that has to prove the waking machinery is exercised AND contained. The
    autopsy is MOCKED, not removed (Kimi: „Мокнете, не заглушавайте") — the branch
    still calls it, and the call is asserted below. What is removed is only its
    ability to spend six minutes talking to a local model.
    """
    from memory import existence_ledger as el
    from memory import heartbeat as hb

    today = _today()
    el.append(el.CYCLE_STARTED, cycle_id="dead-3", pid=4321)
    hb.beat("scoring_engine", 15, cycle_id="dead-3")
    _silence_heartbeat(minutes=20)      # a corpse does not beat; see the helper
    sup.write_lock(pid=4321, cycle_id="dead-3")
    st = sup.load_state()
    st["last_run_date"] = today
    st["restarts"] = {today: 2}            # budget already spent
    sup.save_state(st)

    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: False)

    action = sup.tick()
    assert action.kind == sup.DEAD_LOCK_BUDGET_DONE

    # The waking machinery RAN — mocked, but ran. A test that merely deleted the
    # autopsy from the path would leave nobody checking that this branch still
    # tries to explain itself to the human before going quiet.
    assert len(_AUTOPSY_CALLS) == 1, \
        "the budget-exhausted branch no longer asks for an autopsy before it gives up"
    assert _AUTOPSY_CALLS[0].kind == sup.DEAD_LOCK_BUDGET_DONE

    kinds = [e["event"] for e in el.read_all()]
    assert el.CYCLE_DIED in kinds, "the death must be recorded even when the budget is spent"
    assert el.BUDGET_EXHAUSTED in kinds

    st = sup.load_state()
    assert st["failure"]["date"] == today

    # The daily logic now holds and waits for a human, on the SAME day.
    now9 = datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)
    hold = sup.decide(now9, st, None, None, CFG)
    assert hold.kind == sup.NOTHING
    assert "human" in hold.reason.lower()


def test_death_and_retry_keeps_the_ledger_chain_valid(tick_sandbox, monkeypatch):
    """The death record is hash-chained like every other event: recording it must
    not break the very tamper-evidence that makes it worth trusting."""
    from memory import existence_ledger as el
    from memory import heartbeat as hb

    el.append(el.CYCLE_STARTED, cycle_id="dead-x", pid=4321)
    hb.beat("global_indicators", 7, cycle_id="dead-x")
    sup.write_lock(pid=4321, cycle_id="dead-x")
    st = sup.load_state(); st["last_run_date"] = _today(); sup.save_state(st)

    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: False)

    sup.tick()
    assert el.verify()["valid"] is True
