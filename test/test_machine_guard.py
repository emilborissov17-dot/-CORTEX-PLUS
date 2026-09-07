# -*- coding: utf-8 -*-
"""
PRE-FLIGHT B3 — refuse to generate while a cycle is running or the GPU is busy.

PREDICTION ONLY (§VI); nothing here trades, and no test here needs a GPU: the probe and
the lock path are injected.

tools/first_bet.py has had this guard since it was written, and its own comment says
why: "this is how A3 died four times on 6 September". THE GUARD WAS NEVER REACHED FROM
market_bet.py, which imports only MODEL_PIN and generate_completions and never calls
first_bet.main(). So the grounded bet — the one that actually gets sealed — could start
eight generations on top of a running cycle. A guard that lives in a sibling script and
not on the path that runs is a guard nobody has.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.market_bet import (CYCLE_LOCK, GPU_BUSY_MIB,  # noqa: E402
                              machine_is_free)


def test_a_present_cycle_lock_refuses(tmp_path):
    lock = tmp_path / "cycle.lock"
    lock.write_text("pid 1234", encoding="utf-8")
    free, note = machine_is_free(lock_path=lock, probe=lambda: 0)
    assert free is False
    assert "cycle is running" in note
    assert "A3 died four times" in note


def test_a_free_machine_is_allowed(tmp_path):
    free, note = machine_is_free(lock_path=tmp_path / "absent.lock", probe=lambda: 12)
    assert free is True
    assert "GPU free" in note


def test_an_unknown_gpu_occupancy_refuses_rather_than_assuming_zero(tmp_path):
    """NONE IS NOT ZERO. Getting this backwards turns a safety check into a rubber
    stamp, which is why the rule is written down in both scripts."""
    free, note = machine_is_free(lock_path=tmp_path / "absent.lock", probe=lambda: None)
    assert free is False
    assert "UNKNOWN" in note
    assert "not a zero" in note


def test_a_busy_gpu_refuses(tmp_path):
    free, note = machine_is_free(lock_path=tmp_path / "absent.lock",
                                 probe=lambda: GPU_BUSY_MIB + 1)
    assert free is False
    assert "already held on the GPU" in note


def test_the_threshold_is_a_named_constant_not_a_magic_number():
    assert isinstance(GPU_BUSY_MIB, int) and GPU_BUSY_MIB > 0
    free, _ = machine_is_free(lock_path=Path("nope.lock"), probe=lambda: GPU_BUSY_MIB)
    assert free is True, "the limit itself must be allowed, not refused"


def test_the_lock_path_points_at_the_real_cycle_lock():
    assert CYCLE_LOCK.name == "cycle.lock"
    assert CYCLE_LOCK.parent.name == "memory"


# ── the guard is actually ON the path that runs ────────────────────────────
def test_the_live_path_refuses_with_a_lock_present_and_generates_nothing(
        tmp_path, monkeypatch, capsys):
    """END TO END through main(), in-process, with the lock redirected into tmp_path.

    NOT a subprocess writing a real memory/cycle.lock: conftest's live-write guard
    refuses that, and it is right to. Leaving a stray lock behind would block the 03:04
    cycle — a worse bug than the one under test — and the guard exists because on
    16 Aug 2026 this class of leak fired a fabricated alarm at the human's phone.
    """
    import tools.market_bet as mb

    lock = tmp_path / "cycle.lock"
    lock.write_text("test lock", encoding="utf-8")
    monkeypatch.setattr(mb, "CYCLE_LOCK", lock)
    monkeypatch.setattr(sys, "argv", ["market_bet.py", "--grounded", "--live",
                                      "--out", str(tmp_path / "never.json")])
    # if the guard fails to stop it, this makes the next step loud instead of slow
    monkeypatch.setattr(mb, "compute_baseline",
                        lambda *a, **k: pytest.fail("prices were fetched anyway"))

    rc = mb.main()
    out = capsys.readouterr().out
    assert rc == 4, out
    assert "cycle is running" in out
    assert not (tmp_path / "never.json").exists()


def test_the_guard_also_stops_a_busy_gpu_on_the_live_path(tmp_path, monkeypatch,
                                                          capsys):
    import tools.market_bet as mb

    monkeypatch.setattr(mb, "CYCLE_LOCK", tmp_path / "absent.lock")
    monkeypatch.setattr(mb, "gpu_used_mib", lambda: None)      # unknown occupancy
    monkeypatch.setattr(sys, "argv", ["market_bet.py", "--grounded", "--live",
                                      "--out", str(tmp_path / "never.json")])
    monkeypatch.setattr(mb, "compute_baseline",
                        lambda *a, **k: pytest.fail("prices were fetched anyway"))

    rc = mb.main()
    out = capsys.readouterr().out
    assert rc == 4, out
    assert "UNKNOWN" in out


def test_the_guard_runs_before_the_baseline_fetch_and_before_generation():
    """Structural: in main(), the machine check must precede both compute_baseline and
    anything that reaches the model."""
    import inspect

    import tools.market_bet as mb
    src = inspect.getsource(mb.main)
    assert "machine_is_free" in src
    assert src.index("machine_is_free") < src.index("compute_baseline")


def test_a_dry_run_is_not_blocked_by_a_busy_machine(tmp_path, monkeypatch, capsys):
    """--dry-run touches no GPU, so the guard must not stand in its way."""
    import json

    import tools.market_bet as mb

    lock = tmp_path / "cycle.lock"
    lock.write_text("test lock", encoding="utf-8")
    monkeypatch.setattr(mb, "CYCLE_LOCK", lock)

    fixture = tmp_path / "in.json"
    from tools.market_bet import ASSETS
    fixture.write_text(json.dumps({
        "snippets": {}, "completions": {},
        "baseline": {"baseline": {s: {"sign": "UP"} for s in ASSETS},
                     "last_close": {s: {"date": "2026-09-04", "adjclose": 1.0}
                                    for s in ASSETS}}}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["market_bet.py", "--grounded",
                                      "--dry-run", str(fixture),
                                      "--out", str(tmp_path / "out.json")])
    mb.main()
    assert "cycle is running" not in capsys.readouterr().out
