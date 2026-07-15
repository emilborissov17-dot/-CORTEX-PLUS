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

def test_stale_heartbeat_past_ceiling_is_killed():
    now = at(4)
    hb = beat("trend_tracker", now - timedelta(seconds=1000))   # default ceiling 900
    a = sup.decide(now, state("2026-07-13"), hb, lock(), CFG, lock_pid_alive=True)

    assert a.kind == sup.KILL_RESTART
    assert a.wedged_step == "trend_tracker"
    assert a.ceiling_sec == 900
    assert a.heartbeat_age_sec == pytest.approx(1000, abs=2)


def test_kill_records_which_step_and_by_how_much():
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

def test_second_restart_is_allowed():
    now = at(4)
    hb = beat("x", now - timedelta(seconds=1000))
    a = sup.decide(now, state("2026-07-13", restarts={"2026-07-13": 1}), hb, lock(),
                   CFG, lock_pid_alive=True)
    assert a.kind == sup.KILL_RESTART


def test_third_restart_fails_loudly_instead_of_restarting():
    now = at(4)
    hb = beat("x", now - timedelta(seconds=1000))
    a = sup.decide(now, state("2026-07-13", restarts={"2026-07-13": 2}), hb, lock(),
                   CFG, lock_pid_alive=True)

    assert a.kind == sup.KILL_BUDGET_DONE
    assert "budget" in a.reason.lower()


def test_yesterdays_restarts_do_not_count_against_today():
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
    """A death should still answer 'which step killed me?' — from the last beat."""
    now = at(9)
    hb = beat("web_intelligence", now - timedelta(minutes=5))  # its own heartbeat
    a = sup.decide(now, state(last_run_date="2026-07-13"), hb, lock(pid=4321),
                   CFG, lock_pid_alive=False, lock_cycle_finished=False)
    assert a.kind == sup.DEAD_LOCK_RETRY
    assert a.wedged_step == "web_intelligence"


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


def test_supervisor_never_writes_outside_its_permitted_surface():
    """Enumerated in the design: heartbeat/lock/ledger/state/log. Nothing else."""
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

    allowed = {"LOCK_PATH", "STATE_PATH", "LOG_PATH", "CONFIG_PATH"}
    assert written <= allowed, f"supervisor writes to unexpected targets: {written - allowed}"


# ---------------------------------------------------------------------------
# Fix 2 — a cycle that DIED must be recorded and retried, end to end
# ---------------------------------------------------------------------------

@pytest.fixture
def tick_sandbox(tmp_path, monkeypatch):
    """Point every surface tick() touches at a throwaway dir: state, lock, log,
    cycle logs, the existence ledger, and the heartbeat. The real ones are
    protected constitutional state — a test must never write to them."""
    from memory import existence_ledger as el
    from memory import heartbeat as hb

    monkeypatch.setattr(sup, "STATE_PATH", tmp_path / "scheduler_state.json")
    monkeypatch.setattr(sup, "LOCK_PATH", tmp_path / "cycle.lock")
    monkeypatch.setattr(sup, "LOG_PATH", tmp_path / "supervisor.log")
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(el, "LEDGER_PATH", tmp_path / "existence_ledger.jsonl")
    monkeypatch.setattr(hb, "HEARTBEAT_PATH", tmp_path / "heartbeat.json")
    return tmp_path


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

    # The lock and heartbeat are gone, the chain is intact...
    assert not sup.LOCK_PATH.exists()
    assert hb.read() is None
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


def test_tick_stops_after_repeated_deaths_exhaust_the_budget(tick_sandbox, monkeypatch):
    """A cycle that dies on every attempt must become a VISIBLE failure, not an
    invisible restart loop. Once the budget is spent the death is still recorded,
    but the system stays down and waits for a human."""
    from memory import existence_ledger as el
    from memory import heartbeat as hb

    today = _today()
    el.append(el.CYCLE_STARTED, cycle_id="dead-3", pid=4321)
    hb.beat("scoring_engine", 15, cycle_id="dead-3")
    sup.write_lock(pid=4321, cycle_id="dead-3")
    st = sup.load_state()
    st["last_run_date"] = today
    st["restarts"] = {today: 2}            # budget already spent
    sup.save_state(st)

    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: False)

    action = sup.tick()
    assert action.kind == sup.DEAD_LOCK_BUDGET_DONE

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
