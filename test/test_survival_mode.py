"""Survival mode: budget exhausted must mean DEGRADE, not STOP.

Every test writes only under tmp_path and injects its own scheduler state,
priority table and notifier. Nothing here reads the live memory/ tree, sends a
Telegram alarm, or starts a cycle.

The notifier is injected rather than imported for a reason this repo already paid
for: on 16 Aug 2026 a test sent a real emergency alarm to the human's phone about
a failure that never happened, and the dedup key then suppressed that day's
genuine alarm. survival_mode.enter() cannot reach Telegram on its own.
"""
import json


from core.survival_mode import (NOTICE_SUBJECT, clear,
                                derived_from_disk, enter, is_critical,
                                load_priorities, p50_ceiling, plan, priority_of,
                                read_state, resolve)
from core.step_budget import CRITICAL, NORMAL

CFG = {"max_restarts_per_day": 2}
TODAY = "2026-08-21"

STEPS = ["boot", "web_intelligence", "scoring_engine", "browser_scout",
         "merklememory_commit", "daily_analysis", "cycle_report"]
TABLE = {s: CRITICAL for s in ("boot", "scoring_engine", "merklememory_commit",
                               "cycle_report")}


def _state(**kw):
    base = {"restarts": {}, "failure": {}}
    base.update(kw)
    return base


# ── the headline ───────────────────────────────────────────────────────────

def test_budget_exhausted_runs_critical_steps_and_skips_normal_ones():
    """The literal ask: force budget-exhausted, assert NORMAL skips, CRITICAL runs."""
    sched = _state(restarts={TODAY: 2})
    active, reason, _ = resolve(TODAY, scheduler_state=sched, cfg=CFG,
                                base=_NOWHERE)

    assert active is True
    assert "restart budget exhausted" in reason

    p = plan(STEPS, active=active, reason=reason, table=TABLE, baseline={},
             ceilings={"_default": 900})

    assert p.run == ["boot", "scoring_engine", "merklememory_commit", "cycle_report"]
    assert p.skip == ["web_intelligence", "browser_scout", "daily_analysis"]
    for step in p.skip:
        assert step not in p.run


def test_a_normal_day_runs_everything():
    sched = _state(restarts={TODAY: 1})
    active, reason, _ = resolve(TODAY, scheduler_state=sched, cfg=CFG, base=_NOWHERE)

    assert active is False
    p = plan(STEPS, active=active, table=TABLE, baseline={},
             ceilings={"_default": 900})
    assert p.run == STEPS
    assert p.skip == []


# ── the bypass this module exists for ──────────────────────────────────────

def test_a_fresh_process_reaches_survival_mode_from_disk_alone(tmp_path):
    """THE finding. The scheduled task starts cycles regardless of the supervisor's
    restart budget: at 16:09 UTC on 21 Aug the supervisor refused to restart, and
    at 17:00 UTC a cycle started anyway with an in-process counter of zero.

    So a brand new process — no shared memory, no counter, nothing inherited —
    must still land in survival mode by reading what the supervisor persisted.
    """
    (tmp_path / "memory").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "memory" / "scheduler_state.json").write_text(
        json.dumps({"restarts": {TODAY: 2}}), encoding="utf-8")
    (tmp_path / "config" / "scheduler.json").write_text(
        json.dumps(CFG), encoding="utf-8")

    # No scheduler_state or cfg passed in: everything comes off disk.
    active, reason, is_new = resolve(TODAY, base=tmp_path)

    assert active is True
    assert is_new is True
    assert "persisted in scheduler_state.json" in reason


def test_the_failure_block_alone_triggers_survival_mode():
    """The supervisor writes `failure` on the tick it gives up. A reader that only
    counted restarts would miss a day lost some other way."""
    sched = _state(restarts={TODAY: 0},
                   failure={"date": TODAY, "wedged_step": "internet_intelligence"})
    should, reason = derived_from_disk(sched, CFG, TODAY)

    assert should is True
    assert "internet_intelligence" in reason


def test_yesterdays_failure_does_not_condemn_today():
    sched = _state(restarts={"2026-08-20": 2},
                   failure={"date": "2026-08-20", "wedged_step": "x"})
    should, _ = derived_from_disk(sched, CFG, TODAY)
    assert should is False


def test_the_latched_flag_survives_a_process_death(tmp_path):
    """Latched by one process, seen by the next, with no shared state."""
    (tmp_path / "memory").mkdir()
    enter(TODAY, "budget spent", base=tmp_path)

    # A later process: the supervisor state is now CLEAN, but the latch holds.
    active, reason, is_new = resolve(TODAY, base=tmp_path,
                                     scheduler_state=_state(), cfg=CFG)
    assert active is True
    assert is_new is False, "a latched mode must not re-announce itself"
    assert reason == "budget spent"


def test_a_latch_from_yesterday_DOES_carry_over(tmp_path):
    """REVERSED 22 Aug 2026. This test used to assert the opposite, and the
    behaviour it pinned made the flag unreachable.

    Walk the old rule through the only sequence that can produce a latch:
      budget exhausted on day D -> latch written for D
      no further restart on D — that is what "exhausted" means
      03:00 on D+1: the scheduled task starts a cycle regardless of the
      supervisor's budget. Day-scoped resolve() discards the latch for D,
      re-derives from scheduler_state for D+1 (zero restarts, no failure) and
      answers NOT ACTIVE.

    So the reduced profile applied only to restarts inside the same day, and by
    construction there were none left. The flag would have been written,
    notified about, and never once read as True.

    What clears it is evidence, not the clock: a cycle that finishes.
    """
    (tmp_path / "memory").mkdir()
    enter("2026-08-20", "yesterday's collapse", base=tmp_path)

    active, reason, is_new = resolve(TODAY, base=tmp_path,
                                     scheduler_state=_state(), cfg=CFG)
    assert active is True, (
        "the latch was dropped at midnight, so the 03:00 cycle — the one the "
        "flag exists for — would run at full fat into the wall that set it")
    assert is_new is False, "a carried-over latch must not re-announce itself"
    assert "2026-08-20" in reason, (
        "the reason must say WHEN it was latched; a stale flag with no date is "
        "indistinguishable from a fresh one")


def test_a_finished_cycle_is_what_lifts_the_latch(tmp_path):
    (tmp_path / "memory").mkdir()
    enter("2026-08-20", "yesterday's collapse", base=tmp_path)
    clear(base=tmp_path)

    active, _, _ = resolve(TODAY, base=tmp_path, scheduler_state=_state(), cfg=CFG)
    assert active is False, (
        "clear() is what a finished cycle calls; after it the next cycle runs "
        "in full")


# ── exactly one notice ─────────────────────────────────────────────────────

def test_entering_sends_exactly_one_notice(tmp_path):
    (tmp_path / "memory").mkdir()
    sent = []

    enter(TODAY, "budget spent", base=tmp_path,
          notifier=lambda subject, body: sent.append((subject, body)))
    assert sent == [(NOTICE_SUBJECT, "budget spent")]

    # A second process, same day, same condition.
    enter(TODAY, "budget spent", base=tmp_path,
          notifier=lambda subject, body: sent.append((subject, body)))
    assert len(sent) == 1, "survival mode announced itself twice in one day"

    assert read_state(tmp_path)["entries"] == 1


def test_a_failing_notifier_does_not_fail_survival_mode(tmp_path):
    """A dead phone must not stop the system from surviving."""
    (tmp_path / "memory").mkdir()

    def broken(subject, body):
        raise RuntimeError("telegram unreachable")

    state = enter(TODAY, "budget spent", base=tmp_path, notifier=broken)

    assert state["active"] is True
    assert state["notified"] is False, "an un-sent notice must stay un-sent"
    assert "telegram unreachable" in state["notify_error"]


def test_a_failed_notice_is_retried_by_the_next_entry(tmp_path):
    (tmp_path / "memory").mkdir()
    sent = []

    enter(TODAY, "r", base=tmp_path,
          notifier=lambda s, b: (_ for _ in ()).throw(RuntimeError("down")))
    enter(TODAY, "r", base=tmp_path, notifier=lambda s, b: sent.append(s))

    assert sent == [NOTICE_SUBJECT]


def test_enter_never_reaches_telegram_on_its_own(tmp_path):
    """No notifier, no send — and no crash."""
    (tmp_path / "memory").mkdir()
    state = enter(TODAY, "budget spent", base=tmp_path)
    assert state["active"] is True
    assert state["notified"] is False


def test_clear_turns_it_off(tmp_path):
    (tmp_path / "memory").mkdir()
    enter(TODAY, "budget spent", base=tmp_path)
    clear(base=tmp_path)

    active, _, _ = resolve(TODAY, base=tmp_path, scheduler_state=_state(), cfg=CFG)
    assert active is False


# ── ceilings at p50 ────────────────────────────────────────────────────────

def test_survival_ceilings_are_cut_to_p50():
    baseline = {"scoring_engine": {"runs": [{"seconds": s}
                                            for s in (10, 20, 30, 40, 50)]}}
    p = plan(["scoring_engine"], active=True, table=TABLE, baseline=baseline,
             ceilings={"_default": 900})

    seconds, source = p.ceilings["scoring_engine"]
    assert seconds == 30.0
    assert "p50" in source


def test_a_step_with_no_history_keeps_its_ceiling_rather_than_a_made_up_one():
    p = plan(["scoring_engine"], active=True, table=TABLE, baseline={},
             ceilings={"_default": 900})

    seconds, source = p.ceilings["scoring_engine"]
    assert seconds == 900
    assert "no p50" in source


def test_normal_operation_uses_the_ordinary_ceiling():
    baseline = {"scoring_engine": {"runs": [{"seconds": s} for s in (10, 50)]}}
    p = plan(["scoring_engine"], active=False, table=TABLE, baseline=baseline,
             ceilings={"_default": 900})

    seconds, source = p.ceilings["scoring_engine"]
    assert seconds == 900 and source == "ceiling"


def test_p50_reads_history_filed_under_the_agent_label():
    baseline = {"internet_agent": {"runs": [{"seconds": s} for s in (100, 300)]}}
    seconds, source = p50_ceiling("internet_intelligence", baseline,
                                  {"_default": 900})
    assert seconds == 100.0
    assert "p50" in source


# ── refusing to guess ──────────────────────────────────────────────────────

def test_an_empty_priority_table_warns_instead_of_inventing_a_list():
    p = plan(STEPS, active=True, table={}, baseline={}, ceilings={"_default": 900})

    assert p.run == []
    assert p.skip == STEPS
    assert any("Refusing to guess" in w for w in p.warnings)


def test_normal_is_the_default_for_an_unlisted_step():
    """A step added to the cycle and forgotten here is skipped under stress, never
    silently protected."""
    assert priority_of("a_step_nobody_listed", table=TABLE) == NORMAL
    assert is_critical("a_step_nobody_listed", table=TABLE) is False


# ── the shipped table against the real cycle ───────────────────────────────

def test_the_shipped_table_names_only_steps_that_exist():
    from core.cycle_map import STEPS as MAP_STEPS

    table = load_priorities()
    names = {s for s, *_ in MAP_STEPS}
    unknown = set(table) - names
    assert not unknown, f"config/step_priority.json names non-existent steps: {unknown}"


def test_the_shipped_table_covers_every_backbone_step():
    """cycle_map already curates 'not skippable by opinion'. Survival mode must not
    quietly drop one of them."""
    from core.cycle_map import STEPS as MAP_STEPS

    table = load_priorities()
    backbone = {s for s, _i, _p, _prod, bb in MAP_STEPS if bb}
    missing = backbone - set(table)
    assert not missing, f"backbone steps left NORMAL in survival mode: {missing}"


def test_the_shipped_table_protects_the_four_named_duties():
    table = load_priorities()
    for step in ("scoring_engine", "merklememory_commit", "cycle_report",
                 "civilization_snapshots", "planet_snapshots", "human_snapshots",
                 "cosmos_snapshots"):
        assert table.get(step) == CRITICAL, f"{step} is not CRITICAL"


def test_survival_mode_actually_sheds_most_of_the_cycle():
    """If it skipped almost nothing it would not be survival, only ceremony."""
    from core.cycle_map import STEPS as MAP_STEPS

    names = [s for s, *_ in MAP_STEPS]
    p = plan(names, active=True, baseline={}, ceilings={"_default": 900})

    assert len(p.skip) > len(p.run)
    assert len(p.run) + len(p.skip) == len(names)


# A base that has no memory/ or config/ under it, for the pure-logic tests: it
# forces resolve() to find no latch rather than reading the live repo's.
_NOWHERE = __import__("pathlib").Path(__file__).resolve().parent / "_no_such_base"
