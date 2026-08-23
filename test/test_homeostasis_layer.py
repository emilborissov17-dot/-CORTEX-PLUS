#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_homeostasis_layer.py — HYSTERESIS, INSUFFICIENT, AND TTT.

Three properties the review named, each with a failure mode that is invisible
without a test:

  hysteresis   a value sitting on a threshold must not chatter. For the disk
               actuator every chatter is a real deletion sweep.
  INSUFFICIENT an action that fired and did not move the value must not be
               repeated, and the next arrival must escalate to the human.
  TTT          80% growing at 0.01%/hour and 80% growing at 5%/minute are the
               same distance and opposite situations.

No sensor is read. Every value is synthetic and every path is tmp_path.

    venv/Scripts/python.exe -m pytest test/test_homeostasis_layer.py -v
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import homeostasis as h  # noqa: E402

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)

DISK = {"unit": "%", "levels": {"notice": 28, "action": 15, "gate": 5},
        "hysteresis": 5}
RAM = {"unit": "MB", "levels": {"notice": 1200, "action": 900, "gate": 600},
       "hysteresis": 300}


# ── the signed config ───────────────────────────────────────────────────────

def test_the_live_config_verifies():
    cfg = h.load_config()
    assert set(cfg["variables"]) == {"ram_free", "disk_free_pct"}, (
        "two variables only — see the autoimmune-disorder warning")
    assert cfg["variables"]["disk_free_pct"]["levels"] == \
        {"notice": 28, "action": 15, "gate": 5}
    assert cfg["variables"]["ram_free"]["levels"] == \
        {"notice": 1200, "action": 900, "gate": 600}


def test_an_edited_threshold_is_a_hard_refusal(tmp_path):
    """Not a fallback. Silent defaults would mean the thresholds deciding
    whether a cycle may start are editable by anything that can write a file."""
    cfg = json.loads((REPO / "config" / "homeostasis.json").read_text(
        encoding="utf-8"))
    cfg["variables"]["disk_free_pct"]["levels"]["gate"] = 1     # widened
    p = tmp_path / "homeostasis.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    with pytest.raises(h.ConfigRefused) as e:
        h.load_config(p)
    assert "sha256 mismatch" in str(e.value)


def test_a_config_with_no_stamp_is_refused(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"variables": {}}), encoding="utf-8")
    with pytest.raises(h.ConfigRefused):
        h.load_config(p)


def test_a_missing_config_is_refused_not_defaulted(tmp_path):
    with pytest.raises(h.ConfigRefused):
        h.load_config(tmp_path / "absent.json")


# ── hysteresis ──────────────────────────────────────────────────────────────

def test_disk_engages_at_85_used_and_releases_at_80_used():
    """The brief's own example: engages at 15% free, releases at 20% free."""
    armed = h.level_for(15.0, DISK, h.CLEAR)
    assert armed == "action"
    assert h.level_for(17.0, DISK, armed) == "action", "released too early"
    assert h.level_for(19.9, DISK, armed) == "action", "released too early"
    assert h.level_for(20.0, DISK, armed) == "notice", "did not release at 20"


def test_it_does_not_chatter_over_100_samples_oscillating_on_the_line():
    """Each flip would be a real deletion sweep."""
    armed = h.CLEAR
    flips = 0
    prev = armed
    for i in range(100):
        # oscillate tightly around the action threshold of 15
        value = 15.0 + (1.5 if i % 2 else -1.5)
        armed = h.level_for(value, DISK, armed)
        if armed != prev:
            flips += 1
            prev = armed
    assert flips <= 1, (
        "the level changed {} times across 100 samples on the line".format(flips))


def test_ram_does_not_chatter_either():
    armed = h.CLEAR
    flips, prev = 0, armed
    for i in range(100):
        value = 900.0 + (100.0 if i % 2 else -100.0)
        armed = h.level_for(value, RAM, armed)
        if armed != prev:
            flips += 1
            prev = armed
    assert flips <= 1, flips


def test_escalation_upward_is_immediate_not_hysteretic():
    """Getting worse must never be damped. The dead band protects the release,
    not the arming."""
    armed = h.level_for(15.0, DISK, h.CLEAR)
    assert armed == "action"
    assert h.level_for(4.0, DISK, armed) == "gate", "escalation was damped"


def test_a_value_far_above_everything_is_clear():
    assert h.level_for(65.0, DISK, h.CLEAR) == h.CLEAR
    assert h.level_for(4000.0, RAM, h.CLEAR) == h.CLEAR


def test_release_falls_back_to_the_milder_level_not_to_clear():
    armed = h.level_for(4.0, DISK, h.CLEAR)          # gate
    assert armed == "gate"
    got = h.level_for(12.0, DISK, armed)             # past 5+5, still under 15
    assert got == "action", got


# ── INSUFFICIENT ────────────────────────────────────────────────────────────

def test_the_second_arrival_at_action_escalates_to_gate():
    cfg = h.load_config()
    state = {}
    lvl, why = h.effective_level("disk_free_pct", "action", state, cfg, NOW)
    assert lvl == "action" and not why

    h.mark_insufficient("disk_free_pct", state,
                        "freed 0 bytes; free% did not reach the release point",
                        NOW)
    lvl, why = h.effective_level("disk_free_pct", "action", state, cfg, NOW)
    assert lvl == "gate", "an action known not to work did not escalate"
    assert "INSUFFICIENT" in why


def test_insufficient_expires_after_the_cooldown():
    cfg = h.load_config()
    state = {}
    h.mark_insufficient("disk_free_pct", state, "no effect", NOW)
    assert h.is_insufficient("disk_free_pct", state, cfg,
                             NOW + timedelta(hours=23)) is True
    assert h.is_insufficient("disk_free_pct", state, cfg,
                             NOW + timedelta(hours=25)) is False


def test_insufficient_on_one_variable_does_not_escalate_the_other():
    cfg = h.load_config()
    state = {}
    h.mark_insufficient("disk_free_pct", state, "no effect", NOW)
    lvl, _ = h.effective_level("ram_free", "action", state, cfg, NOW)
    assert lvl == "action"


def test_a_notice_level_is_never_escalated_by_insufficiency():
    """notice is record-only. There is no action to have failed."""
    cfg = h.load_config()
    state = {}
    h.mark_insufficient("disk_free_pct", state, "no effect", NOW)
    lvl, _ = h.effective_level("disk_free_pct", "notice", state, cfg, NOW)
    assert lvl == "notice"


# ── TTT ─────────────────────────────────────────────────────────────────────

def _series(start_value, per_sample_delta, n, t0=0.0, dt=60.0):
    return [[t0 + i * dt, start_value + i * per_sample_delta] for i in range(n)]


def test_ttt_is_infinite_when_the_rate_points_away():
    """A variable moving to safety has no time-to-threshold. Reporting a large
    finite number there would invite comparison with a real one."""
    info = h.interoception("disk_free_pct", 40.0, DISK,
                           _series(30.0, +1.0, 10))
    assert info["direction"] == "rising"
    assert info["ttt_seconds"] == "inf"


def test_ttt_is_infinite_when_flat():
    info = h.interoception("disk_free_pct", 40.0, DISK, _series(40.0, 0.0, 10))
    assert info["direction"] == "flat"
    assert info["ttt_seconds"] == "inf"


def test_the_same_distance_at_two_rates_gives_two_different_ttts():
    """The brief's whole argument for TTT existing."""
    slow = h.interoception("disk_free_pct", 30.0, DISK,
                           _series(30.05, -0.005, 10))
    fast = h.interoception("disk_free_pct", 30.0, DISK,
                           _series(35.0, -0.5, 10))
    assert slow["distance"] == fast["distance"]
    assert slow["direction"] == fast["direction"] == "falling"
    assert slow["ttt_seconds"] > fast["ttt_seconds"] * 10, (
        slow["ttt_seconds"], fast["ttt_seconds"])


def test_ttt_confidence_reflects_the_sample_not_the_future():
    thin = h.interoception("disk_free_pct", 30.0, DISK, _series(31.0, -0.2, 3))
    thick = h.interoception("disk_free_pct", 30.0, DISK, _series(31.0, -0.2, 10))
    assert thin["ttt_confidence"] == "low"
    assert thick["ttt_confidence"] == "high"


def test_too_few_samples_gives_no_rate_at_all():
    info = h.interoception("disk_free_pct", 30.0, DISK, _series(31.0, -0.2, 2))
    assert info["rate_per_second"] is None
    assert info["ttt_confidence"] == "none"
    assert info["direction"] == "unknown"


def test_there_is_no_affect_vocabulary_anywhere_in_the_output():
    """'urgent' and 'hungry' are not measurements."""
    banned = ("urgent", "hungry", "panic", "afraid", "scared", "worried",
              "critical", "desperate", "starving", "suffering", "distress")
    info = h.interoception("disk_free_pct", 6.0, DISK, _series(30.0, -2.0, 10))
    blob = json.dumps(info, ensure_ascii=False).lower()
    hits = [w for w in banned if w in blob]
    assert not hits, hits
    assert "ttt_seconds" in info and "ttt_confidence" in info


def test_the_module_source_carries_no_affect_vocabulary_in_its_outputs():
    src = (REPO / "core" / "homeostasis.py").read_text(encoding="utf-8")
    layer = src.split("THE DEFENDED VARIABLES", 1)[-1]
    code = "\n".join(l for l in layer.splitlines()
                     if not l.lstrip().startswith("#"))
    for word in ("urgent", "hungry", "panic", "starving"):
        assert word not in code.lower(), word


# ── the whole assembly ──────────────────────────────────────────────────────

def test_evaluate_reads_both_variables_and_gates_on_neither_today():
    r = h.evaluate(state={})
    assert set(r["variables"]) == {"ram_free", "disk_free_pct"}
    assert r["config_sha256"]
    for v in r["variables"].values():
        assert v["value"] is not None
        assert "ttt_seconds" in v and "distance" in v and "direction" in v


def test_evaluate_gates_when_a_variable_is_at_gate_level():
    fake = {"ram_free": lambda: 500.0, "disk_free_pct": lambda: 65.0}
    r = h.evaluate(state={}, sensors=fake)
    assert r["gate"] is True
    assert any("ram_free" in s for s in r["gate_reasons"])
    assert r["variables"]["ram_free"]["level"] == "gate"
    assert r["variables"]["disk_free_pct"]["level"] == h.CLEAR


def test_an_unreadable_sensor_is_reported_not_guessed():
    def _boom():
        raise OSError("no sensor")
    r = h.evaluate(state={}, sensors={"ram_free": _boom,
                                      "disk_free_pct": lambda: 65.0})
    assert r["variables"]["ram_free"]["level"] == "unknown"
    assert r["gate"] is False


def test_the_config_is_in_the_protected_paths_denylist():
    from safety.protected_paths import is_protected
    assert is_protected("config/homeostasis.json") is True
