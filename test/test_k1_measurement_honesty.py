# -*- coding: utf-8 -*-
"""ITEM 7.1 — K1 must be written every cycle, and it must be able to say why.

Until 28 August 2026 memory/measurement_honesty_latest.json had one writer: a
human typing `python core/measurement_honesty.py`. It last ran on 20 August and
the first of the four needles had produced no number for eight days.

These tests hold the three properties that make the number worth reading:

  1. an axis counts as measured only if it NAMES the external observation it
     resolved from — a score alone is not evidence;
  2. when the provenance cannot be read, K1 is null with a reason, never 0.0 —
     "nobody looked" and "nothing is measured" are different claims;
  3. the numerator is a weight sum, so a metric shared by two axes must count
     both. metric_details is keyed by metric and silently drops one of them;
     axis_observations is keyed by axis and cannot.

Nothing here touches live state; the last test proves it.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.measurement_honesty import (  # noqa: E402
    OUT, assess, read_provenance, run,
)

TARGETS = json.loads((BASE / "config" / "target_config.json").read_text(encoding="utf-8"))


def _config_axes():
    out = {}
    for domain, axes in TARGETS.items():
        if str(domain).startswith("_"):
            continue
        for axis, cfg in axes.items():
            out[axis] = float(cfg.get("weight", 1))
    return out


CONFIG_AXES = _config_axes()
CONFIG_TOTAL = sum(CONFIG_AXES.values())


def _digest(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


# Taken at import, before a single test runs. The last test compares against it.
_LIVE_BEFORE = {p.as_posix(): _digest(p) for p in (
    OUT,
    BASE / "snapshots" / "master" / "goal_score_latest.json",
    BASE / "memory" / "goal_score_history.json",
)}


def _snapshot(axis_observations):
    return {"axis": "GOAL_SCORE", "metric_details": {},
            "axis_observations": axis_observations}


def _write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# ── provenance: the reason travels with the absence ────────────────────────

def test_a_missing_snapshot_yields_a_reason_not_an_empty_shrug(tmp_path):
    prov, note = read_provenance(tmp_path / "nope.json")
    assert prov == {}
    assert "does not exist" in note
    assert "nope.json" in note


def test_a_snapshot_that_names_no_observation_says_it_predates_the_change(tmp_path):
    p = _write(tmp_path, "goal.json",
               {"metric_details": {"co2_ppm_mauna_loa": {"axis": "CLIMATE_GLOBAL_RISK_REVIEW",
                                                         "current": 432.3}}})
    prov, note = read_provenance(p)
    assert prov == {}
    assert "predates" in note


def test_provenance_read_from_the_old_block_carries_a_caveat(tmp_path):
    p = _write(tmp_path, "goal.json",
               {"metric_details": {"co2_ppm_mauna_loa": {
                   "axis": "CLIMATE_GLOBAL_RISK_REVIEW", "current": 432.3,
                   "observation_key": "noaa_co2_ppm", "source_id": "NOAA",
                   "observation_where": "last_observations"}}})
    prov, note = read_provenance(p)
    assert "CLIMATE_GLOBAL_RISK_REVIEW" in prov
    assert note and "metric_details" in note


# ── K1 itself ──────────────────────────────────────────────────────────────

def test_without_provenance_k1_is_null_and_never_zero():
    a = assess({}, {}, TARGETS, provenance=None,
               provenance_why="the scorer has not run here")
    d = a.to_dict()
    assert d["k1"] is None, "0.0 would be a claim; there is no claim to make"
    assert d["measured_weight"] is None
    assert "the scorer has not run here" in d["k1_why"]


def test_an_axis_that_names_no_observation_does_not_count_however_it_scored():
    axis = next(iter(CONFIG_AXES))
    a = assess({axis: 99.0}, {axis: "measured"}, TARGETS, provenance={})
    d = a.to_dict()
    assert d["measured_weight"] == 0.0
    assert d["k1"] == 0.0
    assert d["by_axis"][axis]["counts_toward_k1"] is False
    assert d["by_axis"][axis]["measured_by"] is None


def test_k1_is_the_named_weight_over_the_config_total():
    picked = sorted(CONFIG_AXES)[:3]
    prov = {ax: {"source_id": "NOAA", "observation_key": "noaa_co2_ppm",
                 "observation_where": "last_observations", "observed_value": 432.3,
                 "metric": "co2_ppm_mauna_loa"} for ax in picked}
    d = assess({}, {}, TARGETS, provenance=prov).to_dict()
    expected = sum(CONFIG_AXES[ax] for ax in picked)
    assert d["measured_weight"] == expected
    assert d["honest_composite"]["total_weight"] == CONFIG_TOTAL
    assert d["k1"] == round(expected / CONFIG_TOTAL, 4)


def test_two_axes_sharing_one_metric_both_count():
    """MATERIALS_WASTE_REVIEW and CLIMATE_GLOBAL_RISK_REVIEW both declare
    co2_ppm_mauna_loa. Reading provenance out of the metric-keyed dict loses
    one of them and understates K1 by its whole weight."""
    pair = ["MATERIALS_WASTE_REVIEW", "CLIMATE_GLOBAL_RISK_REVIEW"]
    for ax in pair:
        assert ax in CONFIG_AXES, f"{ax} left config/target_config.json — retire this test"
    obs = {ax: {"metric": "co2_ppm_mauna_loa", "observation_key": "noaa_co2_ppm",
                "observation_where": "last_observations", "source_id": "NOAA",
                "observed_value": 432.3, "weight": CONFIG_AXES[ax], "scored": True}
           for ax in pair}
    prov, note = read_provenance(_write(pathlib.Path(__file__).parent, "_k1_tmp.json",
                                        _snapshot(obs)))
    (pathlib.Path(__file__).parent / "_k1_tmp.json").unlink()
    assert note is None
    assert set(prov) == set(pair)
    d = assess({}, {}, TARGETS, provenance=prov).to_dict()
    assert d["measured_weight"] == CONFIG_AXES[pair[0]] + CONFIG_AXES[pair[1]]


def test_every_axis_that_counts_names_a_source_id_and_a_key():
    prov = {"CLIMATE_GLOBAL_RISK_REVIEW": {
        "source_id": "NOAA", "observation_key": "noaa_co2_ppm",
        "observation_where": "last_observations", "observed_value": 432.3,
        "metric": "co2_ppm_mauna_loa"}}
    d = assess({}, {}, TARGETS, provenance=prov).to_dict()
    counted = [v for v in d["by_axis"].values() if v["counts_toward_k1"]]
    assert counted, "the fixture supplied one; none counted"
    for v in counted:
        assert v["measured_by"]["source_id"]
        assert v["measured_by"]["observation_key"]


def test_carried_weight_is_published_and_is_not_inside_k1():
    axis = next(iter(CONFIG_AXES))
    d = assess({axis: 60.0}, {axis: "carried"}, TARGETS, provenance={}).to_dict()
    assert d["carried_weight"] == CONFIG_AXES[axis]
    assert d["measured_weight"] == 0.0


# ── run(): the file it writes ──────────────────────────────────────────────

def test_run_stamps_the_write_time_and_carries_the_basis_separately(tmp_path):
    hist = _write(tmp_path, "hist.json",
                  [{"timestamp": "2026-06-21T13:57:09.803467+00:00",
                    "scores": {}, "score_sources": {}}])
    snap = _write(tmp_path, "goal.json", _snapshot(
        {"CLIMATE_GLOBAL_RISK_REVIEW": {
            "metric": "co2_ppm_mauna_loa", "observation_key": "noaa_co2_ppm",
            "observation_where": "last_observations", "source_id": "NOAA",
            "observed_value": 432.3, "weight": 10.0, "scored": True}}))
    out = tmp_path / "honesty.json"
    d = run(write=True, out=out, history=hist, goal_snap=snap)

    from datetime import datetime, timezone
    assert d["ts"].startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d")), (
        "ts must be when the file was written, not when the basis record was made")
    assert d["basis_ts"] == "2026-06-21T13:57:09.803467+00:00"
    assert json.loads(out.read_text(encoding="utf-8"))["k1"] == d["k1"]


def test_the_written_file_carries_the_keys_the_item_asked_for(tmp_path):
    hist = _write(tmp_path, "hist.json", [{"timestamp": "2026-08-28T00:00:00+00:00",
                                           "scores": {}, "score_sources": {}}])
    snap = _write(tmp_path, "goal.json", _snapshot({}))
    out = tmp_path / "honesty.json"
    run(write=True, out=out, history=hist, goal_snap=snap)
    d = json.loads(out.read_text(encoding="utf-8"))
    for key in ("ts", "basis_ts", "measured_weight", "k1", "k1_why",
                "carried_weight", "honest_composite", "todays_number",
                "asserted_axes", "absent_axes", "by_branch", "by_axis"):
        assert key in d, f"{key} missing from the produced file"
    assert d["honest_composite"]["total_weight"] == CONFIG_TOTAL


# ── the wiring ─────────────────────────────────────────────────────────────

def test_the_cycle_calls_it_after_the_scorer_and_after_feedback_loop():
    src = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    beats = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "beat" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            idx = None
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                idx = node.args[1].value
            beats.append((node.args[0].value, idx))
    names = {n: i for n, i in beats}
    assert "measurement_honesty" in names, "nothing in the cycle calls it — the ITEM 7.1 defect"
    assert float(names["measurement_honesty"]) > float(names["goal_score_calculator"])
    assert float(names["measurement_honesty"]) > float(names["feedback_loop"])


def test_the_phase_map_declares_the_step_and_the_file_it_produces():
    phases = json.loads((BASE / "config" / "cycle_phases.json").read_text(encoding="utf-8"))["phases"]
    g = phases["G_LEARN"]
    assert any(s["name"] == "measurement_honesty" for s in g["steps"])
    assert "memory/measurement_honesty_latest.json" in g["produces"]


# ── live state ─────────────────────────────────────────────────────────────

def test_the_real_files_are_byte_identical_after_this_module_ran():
    """Every test above wrote to tmp_path. The digests were taken when this
    module was imported, before any of them ran; this compares against them."""
    assert _LIVE_BEFORE, "nothing was watched — the fixture proves nothing"
    for path, before in _LIVE_BEFORE.items():
        after = _digest(pathlib.Path(path))
        assert after == before, f"{path} MOVED during the test run: {before} -> {after}"


def test_the_module_has_exactly_one_write_target():
    src = (BASE / "core" / "measurement_honesty.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    writers = [n for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == "write_text"]
    assert len(writers) == 1, (
        "core/measurement_honesty.py must have exactly one write_text; found "
        f"{len(writers)}")
