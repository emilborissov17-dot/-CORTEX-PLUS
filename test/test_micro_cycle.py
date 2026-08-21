"""
The micro-cycle: small, local, and confined to what it said it would touch.

The value of running something 3-4 times a day unattended is entirely in the
confinement. A short loop that writes wherever it likes is a second big cycle
with no supervision, so the declaration is the contract and this file is what
holds it:

  * every step declares its outputs, and the declaration is not empty
  * a file outside the declaration is a VIOLATION, named
  * one step cannot shelter behind another step's declaration
  * the cloud is off by mechanism, through the same gate every other cloud
    decision passes (core.backend_policy), not by hoping no step reaches for it
  * it refuses to run beside the big cycle, and fails CLOSED when it cannot tell
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "micro_cycle", REPO / "scripts" / "micro_cycle.py")
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)

from core import backend_policy  # noqa: E402


# --------------------------------------------------------------------------- #
# (a) the declaration
# --------------------------------------------------------------------------- #

def test_the_six_steps_are_the_six_steps():
    assert [s[0] for s in mc.STEPS] == [
        "body_scan", "axis_feed", "resolve_predictions",
        "observe_experiments", "consolidate", "mirror_row"]


@pytest.mark.parametrize("label", [s[0] for s in mc.STEPS])
def test_every_step_declares_at_least_one_output(label):
    assert mc.declared_for(label), f"{label} declares nothing it may write"


def test_an_undeclared_file_is_a_violation():
    assert mc.violations("mirror_row", ["memory/goal_score_history.json"]) == [
        "memory/goal_score_history.json"]


def test_a_declared_file_is_not_a_violation():
    assert mc.violations("mirror_row", ["memory/self_mirror_log.jsonl"]) == []


def test_a_declared_folder_covers_its_children():
    assert mc.violations(
        "resolve_predictions", ["memory/composer_state/gi_noaa_co2.json"]) == []


def test_one_step_cannot_borrow_another_steps_declaration():
    """NEGATIVE CONTROL. If the check pooled every step's outputs, any step
    could write anything the micro-cycle writes anywhere, and the per-step
    declaration would be decoration."""
    assert mc.violations("mirror_row", ["memory/self_experiments.json"]) == [
        "memory/self_experiments.json"]
    assert mc.violations("axis_feed", ["memory/self_mirror_latest.json"]) == [
        "memory/self_mirror_latest.json"]


def test_the_always_allowed_list_is_small_and_explicit():
    """A blanket exemption is how a confinement stops confining. These four are
    bookkeeping the machinery writes, not the step's own work."""
    assert len(mc.ALWAYS_ALLOWED) <= 6
    assert all(f.startswith("memory/") for f in mc.ALWAYS_ALLOWED)
    # and it must NOT cover the interesting files
    for f in ("memory/goal_score_history.json", "memory/auto_levels.json",
              "config/target_config.json"):
        assert not any(f.startswith(a) for a in mc.ALWAYS_ALLOWED)


# --------------------------------------------------------------------------- #
# (b) the windows
# --------------------------------------------------------------------------- #

def test_three_or_four_runs_a_day():
    assert 3 <= len(mc.WINDOWS_LOCAL_HOUR) <= 4


def test_the_windows_avoid_the_big_cycle():
    """config/scheduler.json starts the daily cycle at 03:00 and it has run for
    up to ~3 h. No micro window may land inside that."""
    sched = json.loads((REPO / "config" / "scheduler.json").read_text(encoding="utf-8"))
    start = int(sched["daily_hour"])
    for h in mc.WINDOWS_LOCAL_HOUR:
        assert not (start <= h <= start + 3), (
            f"micro window {h:02d}:00 lands inside the big cycle's "
            f"{start:02d}:00 + 3h span")


def test_the_windows_do_not_collide_with_the_prophecy_task():
    """CORTEX_Prophecy runs at 12:00 local and writes the same ledger the
    micro-cycle scores."""
    assert 12 not in mc.WINDOWS_LOCAL_HOUR


def test_in_window_is_exact():
    for h in mc.WINDOWS_LOCAL_HOUR:
        assert mc.in_window(h) is True
    for h in (0, 3, 4, 5, 12, 23):
        if h not in mc.WINDOWS_LOCAL_HOUR:
            assert mc.in_window(h) is False


# --------------------------------------------------------------------------- #
# (c) local only, by mechanism
# --------------------------------------------------------------------------- #

def test_block_cloud_shuts_the_same_gate_everything_else_passes_through():
    backend_policy.reset_for_tests()
    try:
        assert backend_policy.cloud_allowed("ordinary_work")[0] is True
        backend_policy.block_cloud("test")
        allowed, why = backend_policy.cloud_allowed("ordinary_work")
        assert allowed is False
        assert "local-only" in why
        # and it outranks everything, including a purpose that would normally pass
        assert backend_policy.cloud_allowed(None)[0] is False
    finally:
        backend_policy.reset_for_tests()


def test_reset_clears_the_local_only_flag():
    """NEGATIVE CONTROL for the test harness itself: a flag that survived
    reset_for_tests would silently disable cloud for every later test."""
    backend_policy.block_cloud("test")
    backend_policy.reset_for_tests()
    assert backend_policy.local_only()[0] is False
    assert backend_policy.cloud_allowed("ordinary_work")[0] is True


def test_the_run_blocks_cloud_before_it_does_anything(monkeypatch):
    """The block must happen before the first step, not after — a step that
    already reached the cloud cannot be un-reached."""
    calls = []
    monkeypatch.setattr(backend_policy, "block_cloud",
                        lambda reason: calls.append(reason))
    monkeypatch.setattr(mc, "big_cycle_running",
                        lambda: (True, "pretend the big cycle holds the lock"))
    out = mc.run()
    assert out["ran"] is False              # refused, so no step ran
    assert calls, "block_cloud was not called before the refusal check"


# --------------------------------------------------------------------------- #
# (d) it never runs beside the big cycle
# --------------------------------------------------------------------------- #

def test_it_refuses_while_the_big_cycle_holds_the_lock(monkeypatch, tmp_path):
    lock = tmp_path / "cycle.lock"
    lock.write_text(json.dumps({"pid": 4321, "cycle_id": "x"}), encoding="utf-8")
    monkeypatch.setattr(mc, "LOCK", lock)
    import supervisor
    monkeypatch.setattr(supervisor, "pid_is_our_cycle", lambda pid: True)
    busy, why = mc.big_cycle_running()
    assert busy is True
    assert "4321" in why


def test_a_stale_lock_does_not_block(monkeypatch, tmp_path):
    lock = tmp_path / "cycle.lock"
    lock.write_text(json.dumps({"pid": 4321, "cycle_id": "x"}), encoding="utf-8")
    monkeypatch.setattr(mc, "LOCK", lock)
    import supervisor
    monkeypatch.setattr(supervisor, "pid_is_our_cycle", lambda pid: False)
    busy, why = mc.big_cycle_running()
    assert busy is False
    assert "stale" in why


def test_it_fails_closed_when_liveness_cannot_be_checked(monkeypatch, tmp_path):
    """NEGATIVE CONTROL. 'I could not tell' must mean 'do not run'. The opposite
    default would put two writers on the same files after any import error."""
    lock = tmp_path / "cycle.lock"
    lock.write_text(json.dumps({"pid": 4321}), encoding="utf-8")
    monkeypatch.setattr(mc, "LOCK", lock)
    import supervisor
    def _boom(pid):
        raise RuntimeError("cannot read process table")
    monkeypatch.setattr(supervisor, "pid_is_our_cycle", _boom)
    busy, why = mc.big_cycle_running()
    assert busy is True
    assert "could not be checked" in why


# --------------------------------------------------------------------------- #
# (e) the live artifact — the proof, held
# --------------------------------------------------------------------------- #

def test_the_recorded_micro_run_touched_only_what_it_declared():
    """THE DELIVERABLE. If a micro-cycle has ever run on this machine, its own
    record must show zero undeclared writes. This is the guard that stops the
    small loop from quietly growing a footprint."""
    if not mc.LATEST.exists():
        pytest.skip("no micro-cycle has run on this machine yet")
    rec = json.loads(mc.LATEST.read_text(encoding="utf-8"))
    assert rec["violations"] == [], (
        f"the last micro-cycle wrote outside its declaration: {rec['violations']}")
    # The consolidation folds the steps BEFORE it — it cannot see itself or the
    # mirror row that follows. Writing those in afterwards would be a write
    # outside every step's contract, which is the footprint this loop claims not
    # to have. The other two live in the contract report.
    assert set(rec["steps"]) == {"body_scan", "axis_feed",
                                 "resolve_predictions", "observe_experiments"}
    for label, row in rec["steps"].items():
        assert row["undeclared"] == [], f"{label}: {row['undeclared']}"


def test_all_six_footprints_are_in_the_contract_report():
    """The consolidation folds four; the contract report must carry all six,
    otherwise two steps run each time with nobody measuring them."""
    if not mc.REPORT.exists():
        pytest.skip("no micro-cycle has run on this machine yet")
    blob = json.loads(mc.REPORT.read_text(encoding="utf-8"))
    seen = {s["step"] for s in blob.get("steps", [])}
    expected = {f"micro:{s[0]}" for s in mc.STEPS}
    assert expected <= seen, f"no footprint recorded for {sorted(expected - seen)}"


def test_the_recorded_micro_run_stayed_inside_its_budget():
    if not mc.LATEST.exists():
        pytest.skip("no micro-cycle has run on this machine yet")
    rec = json.loads(mc.LATEST.read_text(encoding="utf-8"))
    assert rec["seconds"] <= mc.SOFT_BUDGET_SEC, (
        f"the micro-cycle took {rec['seconds']}s against a {mc.SOFT_BUDGET_SEC}s "
        "promise — it is not a micro-cycle any more")
