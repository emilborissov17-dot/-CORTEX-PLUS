# -*- coding: utf-8 -*-
"""
test/test_body_sensorium.py — STAGE 0 IS A BOUNDARY, AND BOUNDARIES GET TESTS.

The interesting properties of core/body_sensorium.py are all negative — things
it must not do — and a thing not done leaves no trace in any artifact. So:

  * NUMBERS ONLY. No audio, no image, no capture, no microphone, no camera.
    Not "not yet"; absent, and asserted absent, until the physical-switch design
    is agreed. A sensor that can be turned on by editing a config can be turned
    on by a patch.
  * A reading that cannot be taken is NAMED, never zeroed. "no per-core
    temperature" and "per-core temperature is 0 C" are opposite claims.
  * It never raises. It rides the supervisor's tick, and a sense that can kill
    the body it reports on is worse than no sense.
  * It does not live in memory/sensorium/ — that belongs to a different sense
    with a Merkle chain in it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import body_sensorium as bs   # noqa: E402

SRC = (REPO / "core" / "body_sensorium.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The boundary
# --------------------------------------------------------------------------- #

FORBIDDEN_IN_STAGE_0 = (
    "sounddevice", "pyaudio", "wave", "cv2", "PIL", "mss", "pyautogui",
    "ImageGrab", "screenshot", "VideoCapture", "microphone", "webcam",
)


def test_stage_0_imports_no_capture_library():
    """The list is by import name on purpose: a capture that arrives as a
    dependency arrives whether or not anyone wrote 'camera' in a comment."""
    offenders = [name for name in FORBIDDEN_IN_STAGE_0
                 if f"import {name}" in SRC or f"from {name}" in SRC]
    assert not offenders, (
        f"stage 0 is numbers only; these are capture libraries: {offenders}")


def test_a_row_contains_only_numbers_and_named_absences(tmp_path):
    row = bs.tick(base=tmp_path)
    for key, value in row.items():
        if key in ("ts", "unavailable", "core_temps_c"):
            continue
        assert isinstance(value, (int, float)) and not isinstance(value, bool), (
            f"{key} is {type(value).__name__}, not a number: {value!r}")


def test_no_capture_word_appears_in_a_real_row(tmp_path):
    blob = json.dumps(bs.tick(base=tmp_path)).lower()
    for word in ("audio", "image", "screenshot", "camera", "microphone",
                 "frame", "capture", "pixel"):
        assert word not in blob, f"{word!r} appeared in a stage-0 row"


# --------------------------------------------------------------------------- #
# Absence is named, not zeroed
# --------------------------------------------------------------------------- #

def test_an_unreadable_sensor_is_named_with_its_reason(tmp_path):
    row = bs.tick(base=tmp_path)
    missing = row.get("unavailable") or {}
    for key, why in missing.items():
        assert isinstance(why, str) and len(why) > 5, (
            f"{key} is unavailable but the reason is {why!r}")
        assert why not in ("0", "", "None")


def test_per_core_temperature_absence_says_why(monkeypatch):
    """psutil.sensors_temperatures() is Linux-only. On Windows the honest answer
    is 'this platform does not expose it', not a missing key."""
    import psutil
    monkeypatch.delattr(psutil, "sensors_temperatures", raising=False)
    temps, why = bs._temps()
    assert temps is None
    assert "Linux-only" in why or "does not exist" in why


def test_the_battery_sentinel_is_not_written_as_a_measurement(monkeypatch,
                                                              tmp_path):
    """psutil reports 'unlimited'/'unknown' as negative secsleft sentinels
    (POWER_TIME_UNLIMITED == -2). Writing -2 into a seconds field would read as
    a measurement of minus two seconds."""
    import psutil

    class FakeBattery:
        percent = 97.0
        power_plugged = True
        secsleft = -2

    monkeypatch.setattr(psutil, "sensors_battery", lambda: FakeBattery())
    row = bs.sample(tmp_path / "_last.json")
    assert row["battery_pct"] == 97.0
    assert row["on_ac"] == 1
    assert "battery_secs_left" not in row


def test_a_missing_battery_is_a_fact_about_the_machine(monkeypatch, tmp_path):
    import psutil
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    row = bs.sample(tmp_path / "_last.json")
    assert "battery_pct" not in row
    assert "battery" in (row.get("unavailable") or {})


# --------------------------------------------------------------------------- #
# The rate, across process boundaries
# --------------------------------------------------------------------------- #

def test_the_first_tick_reports_no_rate_rather_than_a_wrong_one(tmp_path):
    row = bs.tick(base=tmp_path)
    assert "net_sent_bps" not in row
    assert "first tick" in (row.get("unavailable") or {}).get("net_rate", "")


def test_a_reset_counter_yields_no_rate_not_a_negative_one(tmp_path, monkeypatch):
    """A counter that went DOWN means the interface reset or the machine
    rebooted. A negative throughput is not a slow network."""
    state = tmp_path / "_last.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({
        "ts_epoch": datetime.now(timezone.utc).timestamp() - 600,
        "net_sent_total": 10**15, "net_recv_total": 10**15}), encoding="utf-8")
    row = bs.sample(state)
    assert "net_sent_bps" not in row
    assert "reset" in (row.get("unavailable") or {}).get("net_rate", "")


def test_the_rate_is_computed_from_the_state_file_not_from_memory(tmp_path):
    """The supervisor tick is a short-lived process: there IS no second sample
    in memory. Two independent sample() calls sharing only a file must produce
    a rate."""
    state = tmp_path / "_last.json"
    bs.sample(state)
    import time
    time.sleep(0.6)
    row = bs.sample(state)
    assert isinstance(row.get("net_recv_bps"), (int, float))
    assert row["net_interval_sec"] >= 0.5


# --------------------------------------------------------------------------- #
# It never raises
# --------------------------------------------------------------------------- #

def test_tick_survives_a_sampler_that_explodes(monkeypatch, tmp_path):
    monkeypatch.setattr(bs, "sample",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    row = bs.tick(base=tmp_path)
    assert "sample" in (row.get("unavailable") or {})


def test_tick_survives_an_unwritable_directory(tmp_path):
    wall = tmp_path / "wall"
    wall.write_text("I am a file", encoding="utf-8")
    row = bs.tick(base=wall / "nested")
    assert isinstance(row, dict)
    assert row.get("unavailable")


def test_the_supervisor_calls_it_and_fails_open():
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    assert "BODY_SENSE_DIR = BASE" in src, (
        "the sensorium path is not a module constant, so no fixture can "
        "redirect it — see the NOTIFY_CHANNEL scar in supervisor.py")
    assert "from core import body_sensorium" in src
    assert "body_sensorium.tick(base=BODY_SENSE_DIR)" in src, (
        "the tick calls the sense with its own default path instead of the "
        "supervisor's redirectable constant — a path a fixture cannot redirect "
        "is a path a test writes to for real")
    block = src.split("body_sensorium.tick(base=BODY_SENSE_DIR)")[1][:400]
    assert "except Exception" in block, (
        "the sense is not fail-open in the tick — it could kill the supervisor")


def test_a_dry_run_writes_nothing():
    """A dry run that leaves a row behind is not a dry run."""
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    head = src.split("body_sensorium.tick(base=BODY_SENSE_DIR)")[0]
    assert "if not dry_run:" in head[-800:], (
        "the sensorium tick is not guarded by `if not dry_run`")


# --------------------------------------------------------------------------- #
# Retention and the trend
# --------------------------------------------------------------------------- #

def test_retention_is_fourteen_days(tmp_path):
    assert bs.RETENTION_DAYS == 14
    tmp_path.mkdir(exist_ok=True)
    old = tmp_path / f"{(datetime.now(timezone.utc) - timedelta(days=20)):%Y-%m-%d}.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    keep = tmp_path / f"{(datetime.now(timezone.utc) - timedelta(days=3)):%Y-%m-%d}.jsonl"
    keep.write_text("{}\n", encoding="utf-8")
    gone = bs.prune(base=tmp_path)
    assert old.name in gone
    assert keep.exists(), "a file inside the window was deleted"


def test_prune_leaves_files_that_are_not_daily_rows_alone(tmp_path):
    state = tmp_path / "_last.json"
    state.write_text("{}", encoding="utf-8")
    bs.prune(base=tmp_path)
    assert state.exists()


def test_the_trend_reports_n_alongside_the_mean(tmp_path):
    bs.tick(base=tmp_path)
    bs.tick(base=tmp_path)
    t = bs.trend(1.0, tmp_path)
    assert t["samples"] == 2
    assert "cpu_pct_mean" in t
    assert "cpu_pct_min" in t and "cpu_pct_max" in t


def test_an_empty_window_says_why_rather_than_returning_zeros(tmp_path):
    t = bs.trend(1.0, tmp_path)
    assert t["samples"] == 0
    assert "why" in t
    assert not any(k.endswith("_mean") for k in t)


# --------------------------------------------------------------------------- #
# It is wired as a sense, in both places
# --------------------------------------------------------------------------- #

def test_it_does_not_squat_on_the_other_sensoriums_directory():
    """memory/sensorium/ holds experiments/sensorium/sensorium.py's
    Merkle-committed drop chain (_merkle_leaves.jsonl, _merkle_root.json).
    Daily telemetry files in there would confuse that audit."""
    assert bs.SENSE_DIR.name == "body_sensorium"
    assert "memory/sensorium" not in str(bs.SENSE_DIR).replace("\\", "/")


def test_body_scan_reads_the_sense(tmp_path):
    src = (REPO / "agents" / "body" / "body_scanner.py").read_text(encoding="utf-8")
    assert "from core import body_sensorium" in src
    assert "body_sensorium.latest()" in src
    assert "body_sensorium.trend(1.0)" in src, (
        "the scan takes the level but not the duration — which is the whole "
        "reason a continuous feed exists")


def test_the_a_orient_menu_carries_the_body(tmp_path):
    from core import phase_evidence as pe
    menu = pe.menu("A_ORIENT")
    body_keys = [k for k in menu if k.startswith("body_")]
    assert body_keys, "A_ORIENT's evidence does not include the body's own state"
    assert any(k.startswith("body_1h_") for k in body_keys), (
        "the menu carries level but not the 1-hour trend")


def test_only_a_orient_carries_the_body():
    """body_scan is A_ORIENT's step 0, so this is A_ORIENT's own data. Giving it
    to every phase would recreate the generic-evidence defect that
    core/phase_evidence.py exists to fix."""
    from core import phase_evidence as pe
    menus = pe.all_menus()
    holders = [p for p in pe.PHASES
               if any(k.startswith("body_") for k in menus[p])]
    assert holders == ["A_ORIENT"], holders


def test_requires_and_produces_are_declared():
    assert isinstance(bs.REQUIRES, dict) and bs.REQUIRES
    assert "psutil" in bs.REQUIRES
    assert isinstance(bs.PRODUCES, tuple) and bs.PRODUCES
    assert all("body_sensorium" in p for p in bs.PRODUCES)


def test_config_step_inputs_was_not_touched():
    """That file is in safety/protected_paths.py: it is the one place a step can
    be handed provenance it did not earn from a scan, so a machine must never
    write it. The REQUIRES declaration lives in the module instead."""
    from safety import protected_paths as pp
    assert "config/step_inputs.json" in pp.PROTECTED_FILES
    body = (REPO / "config" / "step_inputs.json").read_text(encoding="utf-8")
    assert "body_sensorium" not in body
