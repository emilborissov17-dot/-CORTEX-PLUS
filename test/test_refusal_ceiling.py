"""Three refusals a night, cleaning before each, and then sleep.

Emil, 27 Aug 2026, verbatim: "одобрявам таван 3 с чистене преди отказ."

Three separate things had to be true and only one of them was:

  the ceiling is 3        max_refusal_retries_per_day was ABSENT from
                          config/scheduler.json, so the code fell back to
                          max_restarts_per_day and the real ceiling was 2 while
                          every comment described a budget of its own.

  the night is a night    the pool was keyed by the calendar date. With
                          catchup_grace_hours at 20, a catch-up at 01:00 belongs
                          to the night that started at 03:00 yesterday — but
                          midnight rolled the key and handed a still-refusing
                          night a second full allowance.

  cleaning comes first    nothing ever tried to make the crossed threshold
                          false. This is the part that was simply missing.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import supervisor as sup   # noqa: E402

LIVE_CFG = json.loads((REPO / "config" / "scheduler.json").read_text(encoding="utf-8"))


def at(hour, day=13, minute=0):
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


def lock(pid=4321):
    return {"pid": pid, "cycle_id": "c1"}


def state(**kw):
    st = {"last_run_date": None, "last_run_utc": None, "restarts": {},
          "refusals": {}, "failure": None}
    st.update(kw)
    return st


def refused(now, st, cfg=None):
    return sup.decide(now, st, None, lock(), cfg or LIVE_CFG,
                      lock_pid_alive=False, lock_cycle_finished=False,
                      lock_cycle_refused=True)


# -- the ceiling is 3, and it is in the file --------------------------------

def test_the_live_config_carries_the_approved_ceiling():
    assert LIVE_CFG["max_refusal_retries_per_day"] == 3, (
        "the ceiling Emil approved is not in config/scheduler.json, so the "
        "code silently falls back to max_restarts_per_day")
    assert sup.refusal_budget(LIVE_CFG) == 3


def test_the_ceiling_is_not_the_restart_budget():
    assert LIVE_CFG["max_restarts_per_day"] == 2
    assert sup.refusal_budget(LIVE_CFG) != LIVE_CFG["max_restarts_per_day"], (
        "a refused night would spend the budget that recovers a real death")


def test_the_fallback_is_what_was_actually_in_force_before():
    """Documented, not guessed: with the key absent the ceiling really was 2."""
    assert sup.refusal_budget({"max_restarts_per_day": 2}) == 2


def test_the_config_still_parses_and_kept_every_ceiling():
    """A scheduler.json that does not parse reverts every step ceiling to the
    defaults, silently, inside load_config."""
    assert len(LIVE_CFG["step_ceilings_sec"]) == 17
    assert LIVE_CFG["daily_hour"] == 3 and LIVE_CFG["catchup_grace_hours"] == 20


def test_emils_sentence_is_in_the_file_that_carries_the_number():
    raw = (REPO / "config" / "scheduler.json").read_text(encoding="utf-8")
    assert "одобрявам таван 3 с чистене преди отказ" in raw, (
        "the number is in the config without the sentence that authorised it")


# -- three, then sleep ------------------------------------------------------

def test_the_first_three_refusals_still_owe_the_night():
    for used in (0, 1, 2):
        a = refused(at(9), state(refusals={"2026-07-13": used}))
        assert a.kind == sup.CLEAR_REFUSED_LOCK, (
            "refusal %d of 3 already stopped trying" % (used + 1))
        assert "still owed" in a.reason
        assert "%d/3" % (used + 1) in a.reason


def test_the_third_counted_refusal_ends_in_survival_sleep():
    a = refused(at(9), state(refusals={"2026-07-13": 3}))
    assert a.kind == sup.SURVIVAL_SLEEP
    assert "3/3" in a.reason
    assert "next 03:00" in a.reason, (
        "the sleep does not say when it ends: %s" % a.reason)


def test_sleep_does_not_re_owe_the_night():
    a = refused(at(9), state(refusals={"2026-07-13": 3}))
    assert "still owed" not in a.reason, (
        "the day would be un-satisfied and the next tick would spawn again, "
        "which is the spawn loop the ceiling exists to stop")


def test_the_action_carries_the_numbers_not_just_a_verdict():
    a = refused(at(9), state(refusals={"2026-07-13": 1}))
    assert a.details["refusals_used"] == 1
    assert a.details["refusal_budget"] == 3
    assert a.details["night"] == "2026-07-13"


# -- the night runs 03:00 to 03:00 -----------------------------------------

def test_a_moment_before_three_belongs_to_the_night_before():
    assert sup.cycle_day(at(2, day=14, minute=59), LIVE_CFG) == "2026-07-13"


def test_three_oclock_starts_the_new_night():
    assert sup.cycle_day(at(3, day=14), LIVE_CFG) == "2026-07-14"
    assert sup.cycle_day(at(23, day=14), LIVE_CFG) == "2026-07-14"


def test_midnight_does_not_hand_a_refusing_night_a_fresh_allowance():
    """The defect this replaces, stated as the behaviour that must not return.

    Three refusals at 22:00; a catch-up attempt at 01:00 is still inside the
    same night (catchup_grace_hours is 20) and must still be asleep.
    """
    st = state(refusals={"2026-07-13": 3})
    assert refused(at(22, day=13), st).kind == sup.SURVIVAL_SLEEP
    assert refused(at(1, day=14), st).kind == sup.SURVIVAL_SLEEP, (
        "the pool reset at midnight and the night got three more attempts")


def test_the_next_night_really_does_start_fresh():
    st = state(refusals={"2026-07-13": 3})
    assert refused(at(3, day=14), st).kind == sup.CLEAR_REFUSED_LOCK, (
        "the ceiling never lifts, so one bad night disables the system")


def test_the_boundary_follows_daily_hour_rather_than_being_hardcoded():
    assert sup.cycle_day(at(4, day=14), {"daily_hour": 5}) == "2026-07-13"
    assert sup.cycle_day(at(5, day=14), {"daily_hour": 5}) == "2026-07-14"


# -- cleaning comes before the count ---------------------------------------

def _refusal_branch():
    """The supervisor's HANDLER for a refused cycle, as AST.

    Selected by its two-kind test. Matching on CLEAR_REFUSED_LOCK alone finds
    the decision function first — it has the same test and none of the acting.
    """
    tree = ast.parse((REPO / "supervisor.py").read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if not isinstance(n, ast.If):
            continue
        src = ast.dump(n.test)
        if "CLEAR_REFUSED_LOCK" in src and "REFUSED_BUDGET_DONE" in src:
            return n
    raise AssertionError("the refusal handler is gone from supervisor.py")


def test_the_handler_cleans_before_it_counts():
    """Order is the whole mechanism. Counting first would charge the pool for a
    night that then ran perfectly well."""
    branch = _refusal_branch()
    lines = []
    for n in ast.walk(branch):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if name in ("cure_refusal", "refusals_today"):
                lines.append((n.lineno, name))
    lines.sort()
    names = [n for _, n in lines]
    assert "cure_refusal" in names, (
        "nothing is cleaned before the refusal is counted")
    assert names.index("cure_refusal") < names.index("refusals_today"), (
        "the refusal is counted before anything tries to cure it")


def test_a_cured_refusal_is_not_counted():
    """The increment sits behind the cure's own verdict, not beside it."""
    branch = _refusal_branch()
    guards = [ast.dump(n.test) for n in ast.walk(branch) if isinstance(n, ast.If)]
    assert any("counted" in g and "cured" in g for g in guards), (
        "the refusal count is not guarded by whether cleaning cured it")


def test_the_count_is_keyed_by_the_night_not_the_calendar_day():
    branch = _refusal_branch()
    subs = [n for n in ast.walk(branch) if isinstance(n, ast.Subscript)]
    keys = {getattr(s.slice, "id", None) for s in subs}
    assert "night" in keys, (
        "the refusal pool is still keyed by the calendar day: %s" % keys)
    assert "today" not in keys


def test_cleanup_failing_counts_the_refusal_rather_than_swallowing_it():
    """The safe direction. A cleanup that cannot run must not look like a cure."""
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    i = src.index("refusal cleanup unavailable")
    assert "the safe direction" in src[i:i + 400]
    branch = _refusal_branch()
    for n in ast.walk(branch):
        if isinstance(n, ast.If) and "counted" in ast.dump(n.test):
            assert "cured is None" in ast.unparse(n.test), (
                "an unavailable cleanup does not fall through to counting")
            return
    raise AssertionError("no guard found")


# -- sleep says so out loud ------------------------------------------------

def test_survival_sleep_writes_itself_into_the_state():
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    i = src.index('state["survival_sleep"]')
    block = src[i:i + 500]
    for field in ("night", "refusals", "budget", "until", "reason"):
        assert '"%s"' % field in block, (
            "survival sleep does not record %r, so the silence has to be "
            "guessed at" % field)


def test_survival_sleep_rings_the_bell():
    """A lost night is news. Silence reads as health."""
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    assert '_ring_death_bell("SURVIVAL_SLEEP"' in src


def test_the_old_name_and_the_new_one_are_the_same_kind():
    assert sup.REFUSED_BUDGET_DONE == sup.SURVIVAL_SLEEP
