#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_survival_gate.py — THE NIGHT IS NEVER SKIPPED QUIETLY.

The gate has exactly one power — it can stop the cycle — and one obligation
that matters more than the power: when it uses it, tomorrow morning must be
able to tell a refusal apart from a scheduler that never fired.

So the tests are about the noise, not just the decision:
  * a gate-level reading refuses, and the ledger line carries variable, value,
    threshold AND time-to-threshold;
  * the siren fires at ALARM, not as a morning notice;
  * a refusal counts as an END record, so tomorrow does not call it a crash;
  * anything the gate cannot evaluate lets the cycle START.

The real siren and the real ledger are monkeypatched out. No Telegram message
is sent and memory/existence_ledger.jsonl is never appended to by this file.

    venv/Scripts/python.exe -m pytest test/test_survival_gate.py -v
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import survival_gate as sg  # noqa: E402

STARVED_RAM = {"ram_free": lambda: 500.0, "disk_free_pct": lambda: 65.0}
FULL_DISK = {"ram_free": lambda: 4000.0, "disk_free_pct": lambda: 3.0}
HEALTHY = {"ram_free": lambda: 4000.0, "disk_free_pct": lambda: 65.0}


@pytest.fixture
def caught(monkeypatch):
    """Intercept every outward effect: ledger, siren, state file, exit."""
    box = {"ledger": [], "siren": [], "exit": [], "saved": []}

    monkeypatch.setattr(sg, "_to_ledger",
                        lambda cid, d: (box["ledger"].append((cid, d))
                                        or {"seq": 999}))
    monkeypatch.setattr(sg, "_to_siren",
                        lambda cid, d: (box["siren"].append((cid, d)) or True))
    monkeypatch.setattr(sg, "_save_state", lambda d: box["saved"].append(d))
    box["on_refuse"] = lambda code: box["exit"].append(code)
    return box


# ── the decision ────────────────────────────────────────────────────────────

def test_a_healthy_machine_is_allowed():
    d = sg.check(state={}, sensors=HEALTHY)
    assert d["allowed"] is True
    assert d["level"] == "clear"


def test_ram_at_gate_level_refuses():
    d = sg.check(state={}, sensors=STARVED_RAM)
    assert d["allowed"] is False
    assert d["variables"]["ram_free"]["level"] == "gate"
    assert any("ram_free" in r for r in d["reasons"])


def test_disk_at_gate_level_refuses():
    d = sg.check(state={}, sensors=FULL_DISK)
    assert d["allowed"] is False
    assert d["variables"]["disk_free_pct"]["level"] == "gate"


def test_one_variable_at_gate_is_enough():
    """Both must be healthy. Either one alone can stop the night."""
    for sensors in (STARVED_RAM, FULL_DISK):
        assert sg.check(state={}, sensors=sensors)["allowed"] is False


# ── the four facts the ledger line must carry ───────────────────────────────

def test_the_ledger_line_names_variable_value_threshold_and_ttt(caught):
    sg.guard(cycle_id="cycle-test", state={}, sensors=STARVED_RAM,
             on_refuse=caught["on_refuse"])
    assert caught["ledger"], "a refusal wrote nothing to the ledger"
    cid, decision = caught["ledger"][0]
    assert cid == "cycle-test"
    rows = sg._offending(decision["variables"])
    assert len(rows) == 1
    row = rows[0]
    assert row["variable"] == "ram_free"
    assert row["value"] == 500.0
    assert row["threshold"] == 600            # the gate threshold it crossed
    assert "ttt_seconds" in row and "ttt_confidence" in row


def test_the_ledger_line_carries_the_config_hash(caught):
    """Which thresholds were in force is part of the record."""
    sg.guard(cycle_id="c", state={}, sensors=FULL_DISK,
             on_refuse=caught["on_refuse"])
    _, decision = caught["ledger"][0]
    assert decision["config_sha256"], "no record of which thresholds applied"


# ── the noise ───────────────────────────────────────────────────────────────

def test_a_refusal_fires_the_siren(caught):
    sg.guard(cycle_id="c", state={}, sensors=STARVED_RAM,
             on_refuse=caught["on_refuse"])
    assert caught["siren"], "the night was skipped without a siren"


def test_a_refusal_exits_non_zero(caught):
    sg.guard(cycle_id="c", state={}, sensors=STARVED_RAM,
             on_refuse=caught["on_refuse"])
    assert caught["exit"] == [3], caught["exit"]


def test_the_siren_goes_at_alarm_level_not_as_a_morning_notice(monkeypatch):
    """A refusal is exactly the category alarm_human's ALARM was carved out
    for. Delivered as a NOTICE it would arrive with 'a proposal is 3 days old'
    and be read at breakfast, the morning after the night that did not run."""
    import supervisor
    sent = {}

    def _fake(subject, detail, dedup_key=None, trigger=None, *, level=None):
        sent.update(subject=subject, detail=detail, level=level,
                    trigger=trigger, dedup_key=dedup_key)

    monkeypatch.setattr(supervisor, "alarm_human", _fake)
    d = sg.check(state={}, sensors=STARVED_RAM)
    assert sg._to_siren("c", d) is True
    assert sent["level"] == supervisor.ALARM
    assert sent["trigger"] == sg.NAME == "survival_gate"
    assert "ram_free" in sent["detail"]
    assert "600" in sent["detail"], "the threshold is not in the message"


def test_a_healthy_boot_is_silent(caught):
    d = sg.guard(cycle_id="c", state={}, sensors=HEALTHY,
                 on_refuse=caught["on_refuse"])
    assert d["allowed"] is True
    assert not caught["ledger"] and not caught["siren"] and not caught["exit"]


# ── tomorrow morning must not call this a crash ─────────────────────────────

def test_a_refusal_counts_as_an_end_record():
    from core import unclean_stop as us
    assert sg.EVENT in us.END_EVENTS, (
        "tomorrow's boot would report tonight's refusal as an unclean stop and "
        "bill it the whole night as lost duration")


def test_the_event_name_is_the_one_unclean_stop_knows():
    assert sg.EVENT == "CYCLE_REFUSED_SURVIVAL_GATE"


# ── fail-open ───────────────────────────────────────────────────────────────

def test_a_broken_config_lets_the_cycle_start(monkeypatch):
    from core import homeostasis as h

    def _boom(*a, **k):
        raise h.ConfigRefused("sha256 mismatch")

    monkeypatch.setattr(h, "evaluate", _boom)
    d = sg.check(state={}, sensors=HEALTHY)
    assert d["allowed"] is True
    assert "FAIL-OPEN" in d["reasons"][0]
    assert d["gate_error"]


def test_an_unreadable_sensor_does_not_stop_the_night():
    def _boom():
        raise OSError("no sensor")
    d = sg.check(state={}, sensors={"ram_free": _boom,
                                    "disk_free_pct": lambda: 65.0})
    assert d["allowed"] is True
    assert d["variables"]["ram_free"]["level"] == "unknown"


def test_guard_does_not_raise_when_everything_underneath_it_fails(monkeypatch):
    monkeypatch.setattr(sg, "check",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        sg.guard(cycle_id="c")          # guard itself is not the fail-open
    # the fail-open lives in fast_cycle_runner, which wraps the call


# ── the wiring is real ──────────────────────────────────────────────────────

def test_the_runner_calls_the_gate_at_boot():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "from core.survival_gate import guard" in src
    boot = src.index('beat("boot", "-1", cycle_id=_cycle_id)')
    call = src.index("_survival_guard(cycle_id=_cycle_id)")
    first_step = src.index('beat("body_scan", "0")')
    assert boot < call < first_step, (
        "the gate must run after the cycle log tee and before the first step")


def test_the_runner_fails_open_around_the_gate():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    block = src.split("from core.survival_gate import guard", 1)[1][:600]
    assert "except SystemExit:" in block and "raise" in block, (
        "the refusal's own exit must not be swallowed by the fail-open")
    assert "fail-open" in block


def test_the_selftest_reports_every_integration_live():
    assert sg._selftest() == 0
