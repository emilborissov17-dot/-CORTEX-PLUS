"""
Pre-registered experiments on SELF — and the four things they refuse.

The framework is only worth having if it says NO. The refusals under test:

  * a knob that is not in ALLOWED_KNOBS         -> Rejected  (canon.py)
  * two arms holding the same value             -> Rejected
  * an arm outside the code-declared band       -> Rejected
  * a metric no machine can resolve             -> Rejected

and the structural guarantee that makes the rest safe: a GUARDED file is never
written. config/scheduler.json holds the watchdog ceilings and is human-only —
an experiment on it may OBSERVE the arm the file already carries and must file a
proposal for the other. A system that can widen its own ceiling has no ceiling.

Nothing here touches the live store: every write goes to tmp_path.
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]

from core import self_experiment as sx  # noqa: E402

# The store of 21 Aug 2026, captured VERBATIM from memory/self_experiments.json
# (producer: core/self_experiment.py) on the day exp-001 was accepted.
STORE_FIXTURE = BASE / "test" / "fixtures" / "self_experiments_2026-08-21.json"


def _spec(**over) -> dict:
    s = copy.deepcopy(sx.FIRST)
    s.update(over)
    return s


# --------------------------------------------------------------------------- #
# (a) the refusals — each one a negative control
# --------------------------------------------------------------------------- #

def test_canon_py_as_a_knob_is_rejected():
    """THE named negative control. core/canon.py holds the goal, the boundary
    hash and the frame injected into every prompt. It is not a knob and no
    experiment may name it."""
    ok, reasons = sx.validate(_spec(
        id="neg-canon",
        knob={"name": "canon", "file": "core/canon.py", "a": "old", "b": "new"}))
    assert ok is False
    assert any("ALLOWED_KNOBS" in r for r in reasons), reasons


def test_canon_py_is_a_protected_path_by_the_same_module_that_guards_patches():
    """The registry must not carry its own second opinion about what is
    protected — it asks safety/protected_paths, the module the patch guardian
    asks."""
    assert sx.is_guarded("core/canon.py") is True
    assert sx.is_guarded("config/scheduler.json") is True
    assert sx.is_guarded("BOUNDARIES.md") is True
    assert sx.is_guarded("memory/self_experiment_overlay.json") is False


def test_equal_arms_are_rejected():
    """An A/B whose A equals its B distinguishes nothing. It would resolve,
    report a tie, and look like evidence."""
    ok, reasons = sx.validate(_spec(
        id="neg-equal", knob={**sx.FIRST["knob"], "a": 900, "b": 900}))
    assert ok is False
    assert any("equal" in r for r in reasons), reasons


@pytest.mark.parametrize("value", [0, 60, 299, 1801, 99999, -900])
def test_an_arm_outside_the_declared_band_is_rejected(value):
    ok, reasons = sx.validate(_spec(
        id="neg-band", knob={**sx.FIRST["knob"], "b": value}))
    assert ok is False
    assert any("band" in r for r in reasons), reasons


@pytest.mark.parametrize("n", [0, 1, 2, 16, 100])
def test_n_per_arm_outside_3_to_15_is_rejected(n):
    ok, _ = sx.validate(_spec(id="neg-n", n_per_arm=n))
    assert ok is False


def test_a_metric_only_a_model_could_resolve_is_rejected():
    ok, reasons = sx.validate(_spec(
        id="neg-metric",
        metric={**sx.FIRST["metric"], "resolver": "ask the debrief model"}))
    assert ok is False
    assert any("machine-resolvable" in r for r in reasons), reasons


def test_a_knob_pointed_at_the_wrong_file_is_rejected():
    """The file is declared in code. A request naming a different one is either
    a mistake or an attempt to redirect the write."""
    ok, reasons = sx.validate(_spec(
        id="neg-file",
        knob={**sx.FIRST["knob"], "file": "memory/somewhere_else.json"}))
    assert ok is False
    assert any("declared on" in r for r in reasons), reasons


# --------------------------------------------------------------------------- #
# (b) the guarded file is never written
# --------------------------------------------------------------------------- #

def test_overlay_set_refuses_a_guarded_knob():
    with pytest.raises(PermissionError):
        sx.overlay_set("step_ceiling", 1500)


def test_scheduler_json_is_untouched_by_registering_the_experiment(tmp_path):
    sched = BASE / "config" / "scheduler.json"
    before = sched.read_bytes()
    sx.register(sx.FIRST, store=tmp_path / "exp.json")
    assert sched.read_bytes() == before, (
        "registering an experiment modified config/scheduler.json — the whole "
        "point is that it cannot")


def test_a_guarded_experiment_registers_but_blocks_the_arm_it_cannot_apply(tmp_path):
    store = tmp_path / "exp.json"
    imp = tmp_path / "improvements.json"
    imp.write_text(json.dumps({"proposals": []}), encoding="utf-8")

    rec = sx.register(sx.FIRST, store=store)
    assert rec["accepted"] is True
    assert rec["knob_is_guarded"] is True
    # Whichever arm the guarded file currently carries is the observable one, and
    # the OTHER becomes a proposal. Registered on 21 Aug the file read 900 (arm a);
    # after Emil approved the ceiling change the same day it reads 1500 (arm b).
    # Pinning either number here would make this test a record of one afternoon.
    live = rec["live_value_at_registration"]
    assert live in (900, 1500)
    observable = "a" if live == 900 else "b"
    assert rec["arms_observable_now"] == [observable]

    sx.propose_human_arm(rec, improvements=imp)
    rows = json.loads(imp.read_text(encoding="utf-8"))["proposals"]
    assert len(rows) == 1
    other = 1500 if live == 900 else 900
    assert str(other) in rows[0]["solution"]
    assert rows[0]["component"] == "config/scheduler.json"


def test_the_human_arm_is_proposed_once_and_never_twice(tmp_path):
    """NEGATIVE CONTROL for nagging. A proposal that reappears every cycle is
    how a person learns to ignore the channel."""
    imp = tmp_path / "improvements.json"
    imp.write_text(json.dumps({"proposals": []}), encoding="utf-8")
    rec = sx.register(sx.FIRST, store=tmp_path / "exp.json")
    assert sx.propose_human_arm(rec, improvements=imp) is True
    assert sx.propose_human_arm(rec, improvements=imp) is False
    assert len(json.loads(imp.read_text(encoding="utf-8"))["proposals"]) == 1


# --------------------------------------------------------------------------- #
# (c) alternation and the arm-in-force check
# --------------------------------------------------------------------------- #

def test_alternation_is_deterministic_by_cycle_ordinal():
    assert [sx.arm_for_cycle(i) for i in range(8)] == list("abababab")


def test_an_observation_whose_arm_was_not_in_force_does_not_count(tmp_path, monkeypatch):
    """The heart of the honesty here: the experiment reads what the file
    ACTUALLY said, and refuses to count a cycle that ran the other setting.

    RETARGETED 10 Sep 2026 (STEP 6a), and the reason matters. This test used to
    make its point on exp-001, a GUARDED knob, by picking the ordinal parity
    whose alternation disagreed with the file. That is no longer a miss but the
    normal case: for a guarded knob the arm is READ from the file, because the
    machine cannot write it and a human decides — the old expectation counted an
    enforced prohibition as a failed write, 14 times in exp-001's 30 nights.

    The property under test is unchanged and still needs a test, so it moves to
    the knob where an unapplied arm is a genuine miss: an UNGUARDED one, which
    the machine does choose and therefore can get wrong. The guarded refusal
    (a file holding neither arm) is pinned in section (g)."""
    store = tmp_path / "exp.json"
    rec = {"id": "exp-u", "accepted": True, "state": sx.REGISTERED,
           "knob": {"name": "debrief_model",
                    "file": "memory/self_experiment_overlay.json",
                    "a": "qwen2.5:3b", "b": "qwen3:8b"},
           "knob_is_guarded": False, "n_per_arm": 4,
           "metric": {"step": "daily_analysis", "direction": sx.LOWER_BETTER,
                      "resolver": "watchdog_kills+step_seconds"},
           "observations": []}
    store.write_text(json.dumps({"experiments": [rec]}), encoding="utf-8")
    live = "qwen3:8b"                          # what the overlay holds = arm b
    monkeypatch.setattr(sx, "live_value", lambda name, step=None: live)
    matching, other = 1, 0                     # ordinal 1 -> b, ordinal 0 -> a
    future = "2099-01-01T00:00:00+00:00"       # nothing edited after this

    row = sx.observe("exp-u", "cyc-1", other,
                     "2026-08-01T00:00:00+00:00", future, store=store)
    assert row["value_in_force"] == live
    assert row["value_expected"] != live
    assert row["counts"] is False
    assert "not applied" in row["why_not"]

    row = sx.observe("exp-u", "cyc-2", matching,
                     "2026-08-01T00:00:00+00:00", future, store=store)
    assert row["counts"] is True
    assert row["metric"]["watchdog_kills"] >= 0


# --------------------------------------------------------------------------- #
# (d) the verdict is arithmetic
# --------------------------------------------------------------------------- #

def _exp(rows, n=2) -> dict:
    return {"id": "t", "n_per_arm": n,
            "knob": {"name": "step_ceiling", "a": 900, "b": 1500},
            "metric": {"step": "s"}, "observations": rows}


def _obs(arm, kills, secs, counts=True, i=0):
    return {"cycle_id": f"{arm}-{i}", "counts": counts, "arm_expected": arm,
            "metric": {"watchdog_kills": kills, "step_seconds": secs}}


def test_fewer_watchdog_kills_wins():
    v = sx.verdict(_exp([_obs("a", 1, 800, i=0), _obs("a", 1, 820, i=1),
                         _obs("b", 0, 900, i=2), _obs("b", 0, 910, i=3)]))
    assert v["decided"] and v["winner"] == "b"
    assert "kills" in v["why"]


def test_seconds_break_a_tie_on_kills():
    v = sx.verdict(_exp([_obs("a", 0, 800, i=0), _obs("a", 0, 800, i=1),
                         _obs("b", 0, 900, i=2), _obs("b", 0, 900, i=3)]))
    assert v["decided"] and v["winner"] == "a"
    assert "seconds" in v["why"]


def test_a_dead_heat_declares_no_winner():
    """NEGATIVE CONTROL. A tie must not resolve in favour of the status quo —
    it must say the knob did not matter."""
    v = sx.verdict(_exp([_obs("a", 0, 800, i=0), _obs("a", 0, 800, i=1),
                         _obs("b", 0, 800, i=2), _obs("b", 0, 800, i=3)]))
    assert v["decided"] is True
    assert v["winner"] is None


def test_too_few_counted_observations_decides_nothing():
    v = sx.verdict(_exp([_obs("a", 0, 800, i=0), _obs("b", 0, 900, i=1)], n=4))
    assert v["decided"] is False
    assert "not enough" in v["why"]


def test_adoption_is_a_proposal_not_an_action(tmp_path):
    """A winner never writes itself in. It joins the same queue, with the same
    24-hour clock, as every other proposal."""
    imp = tmp_path / "improvements.json"
    imp.write_text(json.dumps({"proposals": []}), encoding="utf-8")
    exp = _exp([_obs("a", 1, 800, i=0), _obs("a", 1, 820, i=1),
                _obs("b", 0, 900, i=2), _obs("b", 0, 910, i=3)])
    exp["verdict"] = sx.verdict(exp)
    exp["knob_file"] = "config/scheduler.json"

    sched_before = (BASE / "config" / "scheduler.json").read_bytes()
    res = sx.adopt(exp, improvements=imp)
    assert res["proposed"] is True
    assert (BASE / "config" / "scheduler.json").read_bytes() == sched_before
    rows = json.loads(imp.read_text(encoding="utf-8"))["proposals"]
    assert len(rows) == 1 and "1500" in rows[0]["solution"]
    # and never twice
    assert sx.adopt(exp, improvements=imp)["proposed"] is False


# --------------------------------------------------------------------------- #
# (e) the knob reader clamps in code, not in the file
# --------------------------------------------------------------------------- #

def test_the_reader_clamps_a_tampered_overlay(tmp_path, monkeypatch):
    """The band lives in code. Even if something rewrote the overlay in memory/,
    a read cannot return a value outside the declared choices."""
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"debrief_model": "gpt-4-turbo"}),
                       encoding="utf-8")
    monkeypatch.setattr(sx, "OVERLAY", overlay)
    assert sx.knob("debrief_model", default="qwen3:8b") == "qwen3:8b"

    overlay.write_text(json.dumps({"debrief_model": "qwen2.5:7b"}), encoding="utf-8")
    assert sx.knob("debrief_model", default="qwen3:8b") == "qwen2.5:7b"


def test_a_guarded_knob_is_never_served_from_the_overlay(tmp_path, monkeypatch):
    """NEGATIVE CONTROL. Writing 'step_ceiling' into the overlay by hand must
    not change what the live code reads — the guarded knob has no overlay lane
    at all."""
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"step_ceilings_sec.<step>": 3600}),
                       encoding="utf-8")
    monkeypatch.setattr(sx, "OVERLAY", overlay)
    assert sx.knob("step_ceiling", default=900) == 900


def test_the_first_experiment_is_registered_in_the_captured_store(monkeypatch):
    """The deliverable: exp-001 was registered, accepted, with arm a observable.

    Read from the capture of 21 Aug 2026 (test/fixtures/self_experiments_2026-08-21.json,
    VERBATIM from memory/self_experiments.json). The live store is regenerable runtime
    state and is no longer tracked; what is guarded is the registration of exp-001 as
    it was accepted, which is a fact about that day and does not move.
    """
    monkeypatch.setattr(sx, "STORE", STORE_FIXTURE)
    blob = sx.load()
    exp = next((e for e in blob.get("experiments", [])
                if e["id"] == "exp-001-daily-analysis-ceiling"), None)
    assert exp is not None, "the first experiment was never registered"
    assert exp["accepted"] is True
    assert exp["knob"]["a"] == 900 and exp["knob"]["b"] == 1500
    assert exp["n_per_arm"] == 4


# --------------------------------------------------------------------------- #
# (f) the ordinal counts cycles, not supervisor announcements
# --------------------------------------------------------------------------- #

def _ledger(tmp_path, rows) -> pathlib.Path:
    p = tmp_path / "existence_ledger.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def test_the_ordinal_counts_distinct_cycles(tmp_path):
    led = _ledger(tmp_path, [
        {"event": "CYCLE_STARTED", "cycle_id": "c1"},
        {"event": "CYCLE_FINISHED", "cycle_id": "c1"},
        {"event": "CYCLE_STARTED", "cycle_id": "c2"},
        {"event": "CYCLE_KILLED", "cycle_id": "c2"},
        {"event": "CYCLE_FAILED_BUDGET_EXHAUSTED", "cycle_id": "c2"},
        {"event": "MISSED_RUN_CATCHUP"},
    ])
    assert sx.cycle_ordinal(ledger=led, current=None) == 2


def test_a_manual_run_still_advances_the_ordinal(tmp_path):
    """CYCLE_STARTED is written by supervisor.py, not by the runner. Counting it
    meant two manual runs in a row drew the SAME arm and the alternation — the
    entire reason the choice is deterministic — silently stopped."""
    rows = [{"event": "CYCLE_STARTED", "cycle_id": "c1"},
            {"event": "CYCLE_FINISHED", "cycle_id": "c1"}]
    led = _ledger(tmp_path, rows)
    first = sx.cycle_ordinal(ledger=led, current="manual-1")
    rows += [{"event": "CYCLE_FINISHED", "cycle_id": "manual-1"}]
    led = _ledger(tmp_path, rows)
    second = sx.cycle_ordinal(ledger=led, current="manual-2")
    assert first == 1 and second == 2
    assert sx.arm_for_cycle(first) != sx.arm_for_cycle(second), (
        "two consecutive manual runs drew the same arm")


def test_the_current_cycle_never_counts_itself(tmp_path):
    """A supervisor run's own CYCLE_STARTED is already in the ledger while it
    runs; a manual run's is not. Without excluding the current id the two kinds
    of run would count themselves differently and draw different arms for the
    same position in the sequence."""
    rows = [{"event": "CYCLE_STARTED", "cycle_id": "c1"},
            {"event": "CYCLE_FINISHED", "cycle_id": "c1"}]
    manual = _ledger(tmp_path, rows)
    supervised = _ledger(tmp_path, rows + [{"event": "CYCLE_STARTED",
                                            "cycle_id": "c2"}])
    assert (sx.cycle_ordinal(ledger=manual, current="c2")
            == sx.cycle_ordinal(ledger=supervised, current="c2") == 1)


def test_the_window_is_never_the_running_cycles(monkeypatch, tmp_path):
    """Superseded on 21 Aug: an earlier version of this preferred the RUNNING
    cycle, and that is precisely what made a killed cycle unobservable. The
    window must belong to a cycle that has ENDED, even while another one runs.
    """
    led = _ledger(tmp_path, [
        {"event": "CYCLE_STARTED", "cycle_id": "closed-one",
         "ts": "2026-08-21T09:00:00+00:00"},
        {"event": "CYCLE_FINISHED", "cycle_id": "closed-one",
         "ts": "2026-08-21T11:00:00+00:00"},
        {"event": "CYCLE_STARTED", "cycle_id": "running-now",
         "ts": "2026-08-21T12:00:00+00:00"},
    ])
    cid, since, until = sx.last_cycle_window(ledger=led)
    assert cid == "closed-one"
    assert since == "2026-08-21T09:00:00+00:00"
    assert until == "2026-08-21T11:00:00+00:00"


# --------------------------------------------------------------------------- #
# (g) a cycle is scored AFTER it ends — learned from a live kill
# --------------------------------------------------------------------------- #

def test_a_killed_cycle_is_still_observed(tmp_path):
    """THE lesson of 21 Aug. The first cycle with the observer live was killed by
    the watchdog at daily_analysis — the exact failure exp-001 was registered to
    study — and the observation did not happen, because the observer sits at step
    25.44 and the cycle died at step 22.

    An experiment about a step that brings the cycle down can never be seen by an
    observer running at the end of that same cycle. The blindness is worst
    exactly where the hypothesis is most right. So the cycle is judged from the
    ledger AFTER it closes, and a kill is a perfectly observable ending."""
    led = _ledger(tmp_path, [
        {"event": "CYCLE_STARTED", "cycle_id": "c1", "ts": "2026-08-20T00:00:00+00:00"},
        {"event": "CYCLE_FINISHED", "cycle_id": "c1", "ts": "2026-08-20T02:00:00+00:00"},
        {"event": "CYCLE_STARTED", "cycle_id": "c2", "ts": "2026-08-21T00:00:00+00:00"},
        {"event": "CYCLE_KILLED", "cycle_id": "c2", "ts": "2026-08-21T02:00:00+00:00",
         "reason": {"wedged_step": "daily_analysis", "ceiling_sec": 900}},
    ])
    cid, since, until, ordinal = sx.last_closed_cycle(ledger=led)
    assert cid == "c2"
    assert since == "2026-08-21T00:00:00+00:00"
    assert until == "2026-08-21T02:00:00+00:00"
    assert ordinal == 1, "the ordinal must be the OBSERVED cycle's, not today's"


def test_the_window_covers_the_whole_cycle_not_just_its_death(tmp_path):
    """NEGATIVE CONTROL. A manually launched cycle has no CYCLE_STARTED —
    supervisor.py writes that, the runner does not — so the only event carrying
    its id can be its own kill, and the window would collapse to one instant.
    The cycle_id IS the start time; it is used as the floor."""
    led = _ledger(tmp_path, [
        {"event": "CYCLE_FINISHED", "cycle_id": "old", "ts": "2026-08-20T02:00:00+00:00"},
        {"event": "CYCLE_KILLED", "cycle_id": "2026-08-21T11:57:28+00:00",
         "ts": "2026-08-21T14:24:02+00:00"},
    ])
    cid, since, until, _ = sx.last_closed_cycle(ledger=led)
    assert since.startswith("2026-08-21T11:57:28")
    assert until.startswith("2026-08-21T14:24:02")
    assert since < until, "the window collapsed onto the moment of death"


def test_a_watchdog_kill_on_the_measured_step_is_counted(tmp_path):
    led = _ledger(tmp_path, [
        {"event": "CYCLE_KILLED", "cycle_id": "c", "ts": "2026-08-21T14:00:00+00:00",
         "reason": {"wedged_step": "daily_analysis"}},
        {"event": "CYCLE_KILLED", "cycle_id": "d", "ts": "2026-08-21T15:00:00+00:00",
         "reason": {"wedged_step": "web_intelligence"}},
    ])
    m = sx.resolve_watchdog_and_seconds(
        {"metric": {"step": "daily_analysis"}},
        "2026-08-21T00:00:00+00:00", "2026-08-21T23:00:00+00:00", ledger=led)
    assert m["watchdog_kills"] == 1, "a kill on another step must not count here"


def test_an_unfinished_step_reports_no_seconds_rather_than_a_number(tmp_path):
    """A step the watchdog killed has no duration in the contract, and inventing
    one — the ceiling, say — would be a fabricated measurement in a training-
    grade record."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"daily_analysis": {"runs": []}}), encoding="utf-8")
    m = sx.resolve_watchdog_and_seconds(
        {"metric": {"step": "daily_analysis"}},
        "2026-08-21T00:00:00+00:00", "2026-08-21T23:00:00+00:00",
        ledger=tmp_path / "none.jsonl", baseline=baseline)
    assert m["step_seconds"] is None


def test_observing_the_same_cycle_twice_leaves_one_row(tmp_path):
    store = tmp_path / "exp.json"
    sx.register(sx.FIRST, store=store)
    for _ in range(3):
        sx.observe(sx.FIRST["id"], "same-cycle", 0, "2026-08-01T00:00:00+00:00",
                   "2026-09-01T00:00:00+00:00", store=store)
    exp = json.loads(store.read_text(encoding="utf-8"))["experiments"][0]
    assert len(exp["observations"]) == 1


def test_the_first_arm_a_observation_is_in_the_capture(monkeypatch):
    """THE DELIVERABLE. One counted arm-A observation, and it is a watchdog kill
    on daily_analysis — the hypothesis reproducing itself. Read from the capture
    of 21 Aug 2026; see the note on the registration test above."""
    monkeypatch.setattr(sx, "STORE", STORE_FIXTURE)
    exp = next(e for e in sx.load()["experiments"]
               if e["id"] == "exp-001-daily-analysis-ceiling")
    counted = [o for o in exp["observations"]
               if o["counts"] and o["arm_expected"] == "a"]
    assert counted, "no counted arm-A observation was ever recorded"
    first = counted[0]
    assert first["value_in_force"] == 900 == first["value_expected"]
    assert first["metric"]["watchdog_kills"] >= 1
    assert first["window"][0] < first["window"][1]


# --------------------------------------------------------------------------- #
# (h) what was in force THEN, not what the file says now
# --------------------------------------------------------------------------- #

def test_a_knob_edited_after_the_cycle_ended_cannot_be_attributed_to_it():
    """A defect this session's own fix created, caught the same hour. Once a
    cycle is judged AFTER it closes, "what the file says now" stops being "what
    the file said then". Live: a cycle died at 14:39:02 and the ceiling was
    raised to 1500 at 14:40:11 — 69 seconds later. Reading the file would have
    recorded that cycle as an arm-B observation of a setting it never saw."""
    value, basis = sx.value_in_force(
        "step_ceiling", step="daily_analysis",
        cycle_end="2000-01-01T00:00:00+00:00")
    assert value is None
    assert "cannot be established" in basis


def test_an_untouched_knob_is_read_from_the_file():
    value, basis = sx.value_in_force(
        "step_ceiling", step="daily_analysis",
        cycle_end="2099-01-01T00:00:00+00:00")
    assert value == sx.live_value("step_ceiling", step="daily_analysis")
    assert "unchanged since" in basis


def test_a_kill_record_is_testimony_from_the_moment():
    """CYCLE_KILLED carries the ceiling the watchdog actually measured against.
    That outranks the file, and survives any later edit."""
    killed = {"event": "CYCLE_KILLED",
              "reason": {"wedged_step": "daily_analysis", "ceiling_sec": 900}}
    value, basis = sx.value_in_force(
        "step_ceiling", step="daily_analysis",
        cycle_end="2000-01-01T00:00:00+00:00", evidence=killed)
    assert value == 900
    assert "CYCLE_KILLED" in basis


def test_an_unestablished_value_never_counts(tmp_path):
    """NEGATIVE CONTROL. 'I cannot tell what was in force' must not resolve to
    'it matched' — that is how a fabricated data point enters an experiment."""
    store = tmp_path / "exp.json"
    sx.register(sx.FIRST, store=store)
    row = sx.observe(sx.FIRST["id"], "c", 0, "2026-08-01T00:00:00+00:00",
                     "2000-01-01T00:00:00+00:00", store=store)
    assert row["value_in_force"] is None
    assert row["counts"] is False
    assert "cannot be established" in row["why_not"]


# --------------------------------------------------------------------------- #
# (g) STEP 6a — a GUARDED arm is read from the file, never alternated for
# --------------------------------------------------------------------------- #

def _guarded_store(tmp_path, ceiling: int):
    """A registered exp-001 plus a scheduler.json reading `ceiling`."""
    store = tmp_path / "exp.json"
    sched = tmp_path / "scheduler.json"
    sched.write_text(json.dumps({"step_ceilings_sec": {"daily_analysis": ceiling}}),
                     encoding="utf-8")
    rec = {"id": "exp-001", "accepted": True, "state": sx.REGISTERED,
           "knob": {"name": "step_ceiling", "file": "config/scheduler.json",
                    "step": "daily_analysis", "a": 900, "b": 1500},
           "knob_is_guarded": True, "n_per_arm": 4,
           "metric": {"step": "daily_analysis", "direction": sx.LOWER_BETTER,
                      "resolver": "watchdog_kills+step_seconds"},
           "observations": []}
    store.write_text(json.dumps({"experiments": [rec]}), encoding="utf-8")
    return store, sched


def _observe_with_file(tmp_path, ceiling, ordinal, monkeypatch):
    store, sched = _guarded_store(tmp_path, ceiling)
    monkeypatch.setattr(sx, "live_value",
                        lambda name, step=None: ceiling if name == "step_ceiling" else None)
    return sx.observe("exp-001", f"cyc-{ordinal}", ordinal,
                      "2026-09-01T00:00:00+00:00", "2026-09-02T00:00:00+00:00",
                      store=store), sched


def test_a_guarded_arm_counts_from_the_file_even_when_the_ordinal_disagrees(tmp_path, monkeypatch):
    """THE STEP 6a DEFECT. The file reads 1500 (arm b). Ordinal 0 alternates to
    arm a. Before the fix that row was recorded 'NOT counted: arm not applied' —
    14 of exp-001's 30 nights burned that way, describing an ENFORCED
    PROHIBITION as a failed write. The arm must be read from the file."""
    row, _ = _observe_with_file(tmp_path, 1500, 0, monkeypatch)
    assert sx.arm_for_cycle(0) == "a", "ordinal 0 does alternate to a"
    assert row["arm_expected"] == "b", "but the guarded arm is whatever the file holds"
    assert row["counts"] is True, "a readable guarded file is an observation, not a miss"
    assert row["why_not"] is None
    assert "human" in row["arm_source"]


def test_the_other_ordinal_reads_the_same_guarded_arm(tmp_path, monkeypatch):
    """Negative control on the alternation: the ordinal must not matter at all
    for a guarded knob. Ordinal 1 alternates to b and would have 'counted' by
    accident — the point is that the SOURCE changed, not that b got lucky."""
    row, _ = _observe_with_file(tmp_path, 1500, 1, monkeypatch)
    assert row["arm_expected"] == "b" and row["counts"] is True
    row900, _ = _observe_with_file(tmp_path, 900, 1, monkeypatch)
    assert sx.arm_for_cycle(1) == "b"
    assert row900["arm_expected"] == "a", "the file said 900; that is arm a whatever the ordinal says"
    assert row900["counts"] is True


def test_a_guarded_file_holding_neither_arm_still_refuses(tmp_path, monkeypatch):
    """The fix must not turn into 'everything counts'. A ceiling that is neither
    900 nor 1500 belongs to no arm and must NOT be counted."""
    row, _ = _observe_with_file(tmp_path, 1200, 0, monkeypatch)
    assert row["arm_expected"] is None
    assert row["counts"] is False
    assert "neither arm" in row["why_not"]


def test_observing_a_guarded_knob_never_writes_the_guarded_file(tmp_path, monkeypatch):
    """MECHANICAL NET. The forbidden fix for STEP 6a was to make the arm land by
    WRITING config/scheduler.json — that is the ceiling the watchdog kills by,
    and a system that sets its own ceiling has none. Observing must leave the
    file byte-identical, and overlay_set must still refuse it outright."""
    store, sched = _guarded_store(tmp_path, 1500)
    before = sched.read_bytes()
    monkeypatch.setattr(sx, "live_value", lambda name, step=None: 1500)
    sx.observe("exp-001", "cyc-0", 0, "2026-09-01T00:00:00+00:00",
               "2026-09-02T00:00:00+00:00", store=store)
    assert sched.read_bytes() == before, "observing wrote the guarded ceiling"
    with pytest.raises(PermissionError):
        sx.overlay_set("step_ceiling", 900)
    assert sx.knob("step_ceiling", default=777) == 777, "guarded knob has no overlay lane"


def test_an_unguarded_knob_still_alternates_by_ordinal(tmp_path, monkeypatch):
    """NEGATIVE CONTROL. The read-from-the-file rule is for GUARDED knobs only.
    An unguarded knob is the machine's own choice, so it must still alternate —
    otherwise the fix would delete randomisation everywhere."""
    store = tmp_path / "exp.json"
    rec = {"id": "exp-u", "accepted": True, "state": sx.REGISTERED,
           "knob": {"name": "debrief_model", "file": "memory/self_experiment_overlay.json",
                    "a": "qwen2.5:3b", "b": "qwen3:8b"},
           "knob_is_guarded": False, "n_per_arm": 4,
           "metric": {"step": "daily_analysis", "direction": sx.LOWER_BETTER,
                      "resolver": "watchdog_kills+step_seconds"},
           "observations": []}
    store.write_text(json.dumps({"experiments": [rec]}), encoding="utf-8")
    monkeypatch.setattr(sx, "live_value", lambda name, step=None: "qwen3:8b")
    r0 = sx.observe("exp-u", "c0", 0, "2026-09-01T00:00:00+00:00",
                    "2026-09-02T00:00:00+00:00", store=store)
    assert r0["arm_expected"] == "a", "unguarded knobs alternate by ordinal"
    assert r0["counts"] is False, "the overlay held b, the alternation asked a"
    assert "arm not applied" in r0["why_not"]
    assert r0["arm_source"] == "alternation by cycle ordinal"


def test_a_guarded_verdict_is_labelled_observational():
    """A guarded arm is chosen by a human over time, not by a coin. The verdict
    must say so, so it is never quoted as a controlled result."""
    rows = [_obs("a", 1, 800, i=0), _obs("a", 1, 820, i=1),
            _obs("b", 0, 900, i=2), _obs("b", 0, 910, i=3)]
    guarded = _exp(rows)
    guarded["knob_is_guarded"] = True
    v = sx.verdict(guarded)
    assert v["randomised"] is False
    assert v["decided"] and "OBSERVATIONAL" in v["why"]
    free = _exp(rows)
    free["knob_is_guarded"] = False
    v2 = sx.verdict(free)
    assert v2["randomised"] is True and "OBSERVATIONAL" not in v2["why"]
