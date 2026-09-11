# -*- coding: utf-8 -*-
"""test/test_signed_schedule.py — the human signs the randomisation; the machine keeps no pen (10 Sep 2026)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location("signed_schedule", REPO / "tools" / "signed_schedule.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


def _sched(**over):
    base = {"id": "s-t", "experiment": "exp-001", "knob": "step_ceiling", "step": "daily_analysis",
            "file": "config/scheduler.json", "key": "step_ceilings_sec.daily_analysis",
            "arms": {"a": 900, "b": 1500}, "restore_value": 1500, "seed": 5, "n_per_arm": 2,
            "sequence": ss.draw(5, 2), "signed_by": "Emil Borissov", "signed_on": "2026-09-10"}
    base.update(over)
    return base


def _target(tmp_path):
    p = tmp_path / "scheduler.json"
    p.write_text(json.dumps({"step_ceilings_sec": {"_default": 900, "daily_analysis": 1500}}), encoding="utf-8")
    return p


# ── refusals first ─────────────────────────────────────────────────────────

def test_unsigned_applies_nothing(tmp_path):
    t = _target(tmp_path)
    r = ss.apply(_sched(signed_by=None, signed_on=None), t, log=tmp_path / "log.jsonl")
    assert r["verdict"] == "UNSIGNED" and r["written"] is False
    assert json.loads(t.read_text())["step_ceilings_sec"]["daily_analysis"] == 1500
    assert not (tmp_path / "log.jsonl").exists()


def test_a_sequence_that_is_not_the_seeds_is_tampered_and_refused(tmp_path):
    t = _target(tmp_path)
    forged = ["a", "a", "a", "a"]                     # all the arm someone wanted
    assert forged != ss.draw(5, 2)
    r = ss.apply(_sched(sequence=forged), t, log=tmp_path / "log.jsonl")
    assert r["verdict"] == "TAMPERED" and r["written"] is False


def test_an_arm_outside_the_band_is_refused(tmp_path):
    t = _target(tmp_path)
    r = ss.apply(_sched(arms={"a": 900, "b": 99999}, sequence=ss.draw(99, 2), seed=99), t, log=tmp_path / "log.jsonl")
    # first position of seed 99 may be 'a'; force 'b' to be first by picking a seed whose draw starts with 'b'
    seed = next(s for s in range(1, 200) if ss.draw(s, 2)[0] == "b")
    r = ss.apply(_sched(arms={"a": 900, "b": 99999}, sequence=ss.draw(seed, 2), seed=seed), t, log=tmp_path / "log2.jsonl")
    assert r["verdict"] == "OUT_OF_BAND" and r["written"] is False


# ── the happy path, and that it ends ───────────────────────────────────────

def test_applies_the_seeds_sequence_in_order_then_restores_once(tmp_path):
    t, log = _target(tmp_path), tmp_path / "log.jsonl"
    s = _sched()
    seq = ss.draw(5, 2)
    for i, arm in enumerate(seq):
        r = ss.apply(s, t, log=log, now=f"2026-09-{11 + i:02d}T00:50:00+00:00")
        assert r["verdict"] == "APPLIED" and r["position"] == i and r["arm"] == arm
        assert json.loads(t.read_text())["step_ceilings_sec"]["daily_analysis"] == s["arms"][arm]
    r = ss.apply(s, t, log=log, now="2026-09-20T00:50:00+00:00")
    assert r["verdict"] == "RESTORED" and json.loads(t.read_text())["step_ceilings_sec"]["daily_analysis"] == 1500
    r = ss.apply(s, t, log=log)
    assert r["verdict"] == "DONE" and r["written"] is False
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert [x["arm"] for x in rows[:-1]] == seq and rows[-1]["restored"] is True


def test_draw_is_balanced_and_seed_determined():
    assert sorted(ss.draw(20260910, 6)) == ["a"] * 6 + ["b"] * 6
    assert ss.draw(20260910, 6) == ss.draw(20260910, 6) != ss.draw(20260911, 6)


# ── the log is evidence of the value in force ──────────────────────────────

def test_value_in_force_from_log_reads_the_window_not_the_mtime(tmp_path):
    log = tmp_path / "log.jsonl"
    rows = [{"applied_utc": "2026-09-11T00:50:00+00:00", "step": "daily_analysis", "value": 900, "arm": "a", "position": 0, "signed_by": "E"},
            {"applied_utc": "2026-09-12T00:50:00+00:00", "step": "daily_analysis", "value": 1500, "arm": "b", "position": 1, "signed_by": "E"}]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    v, basis = ss.value_in_force_from_log("daily_analysis", "2026-09-11T01:04:00+00:00", "2026-09-11T03:00:00+00:00", log)
    assert v == 900 and "position 0" in basis
    v, basis = ss.value_in_force_from_log("daily_analysis", "2026-09-12T01:04:00+00:00", "2026-09-12T03:00:00+00:00", log)
    assert v == 1500
    # a change INSIDE the window: nobody knows which value the cycle saw
    v, basis = ss.value_in_force_from_log("daily_analysis", "2026-09-11T23:00:00+00:00", "2026-09-12T02:00:00+00:00", log)
    assert v is None and "inside this cycle" in basis
    # another step's log is not this step's evidence
    assert ss.value_in_force_from_log("other_step", "2026-09-11T01:04:00+00:00", "2026-09-11T03:00:00+00:00", log) == (None, None)


def test_self_experiment_uses_the_log_before_the_mtime(tmp_path, monkeypatch):
    from core import self_experiment as sx
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"applied_utc": "2026-09-11T00:50:00+00:00", "step": "daily_analysis", "value": 900,
                               "arm": "a", "position": 0, "signed_by": "E"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(ss, "LOG", log)
    # the hook loads tools/signed_schedule.py by path; point its LOG at ours through the module it will build
    real_from_spec = importlib.util.module_from_spec

    def patched(spec_):
        m = real_from_spec(spec_)
        if spec_.name == "signed_schedule":
            spec_.loader.exec_module(m)
            m.LOG = log
            spec_.loader.exec_module = lambda mod: None      # keep our LOG
        return m
    monkeypatch.setattr(importlib.util, "module_from_spec", patched)
    v, basis = sx.value_in_force("step_ceiling", step="daily_analysis",
                                 cycle_start="2026-09-11T01:04:00+00:00", cycle_end="2026-09-11T03:00:00+00:00")
    assert v == 900 and "signed schedule" in basis


def test_the_live_schedule_is_consistent_and_unsigned_until_a_human_signs():
    s = ss.load()
    st = ss.status(s)
    assert st["tampered"] is False and st["length"] == 2 * s["n_per_arm"]
    assert s["arms"] == {"a": 900, "b": 1500} and s["key"] == "step_ceilings_sec.daily_analysis"
    # not asserting signed: that is the human's move, and a test must not make it for them


# ── the band is read, not mirrored (11 Sep 2026) ─────────────────────────────

def test_the_band_is_not_a_copy():
    """A MIRRORED CONTRACT IS THE merkle_to_training DEFECT AGAIN.

    This module used to carry `BANDS = {"step_ceiling": (300, 1800)}` with the
    comment "mirrors core/self_experiment.ALLOWED_KNOBS". Two readers of one rule
    drift apart silently — and here the drift points OUTWARD: widen the mirror and
    the signature could write a ceiling outside the band declared in code, so the
    watchdog guard falls without anyone removing it.

    _bands() now reads ALLOWED_KNOBS, which is the authority. The literal survives
    only as a fallback for running this file without the package, and this test
    fails if the fallback ever disagrees with the source."""
    from core.self_experiment import ALLOWED_KNOBS
    live = ss._bands()
    for knob, (lo, hi) in ss._BAND_FALLBACK.items():
        declared = ALLOWED_KNOBS[knob]["band"]
        assert (lo, hi) == tuple(declared), (
            f"the fallback band for {knob} says {(lo, hi)} and the code declares "
            f"{tuple(declared)} — one of them is a lie")
        assert live[knob] == tuple(declared), "_bands() did not read the declaration"


def test_the_signed_file_cannot_widen_its_own_band():
    """THE CONTAINMENT THAT MAKES THE SIGNATURE SAFE. The band lives in code, so a
    signature — even a valid one — can only choose AMONG values a human already
    bounded. An arm outside it is refused with the value named, and nothing is
    written."""
    sched = ss.load()
    lo, hi = ss._bands()[sched["knob"]]
    for v in list(sched["arms"].values()) + [sched["restore_value"]]:
        assert lo <= v <= hi, f"the live signed schedule carries {v}, outside {lo}..{hi}"


def test_the_live_schedule_is_signed_and_untampered():
    """The state the scheduled task depends on. If this fails the 02:50 task is
    writing nothing every night, which is safe but silent."""
    st = ss.status(ss.load())
    assert st["signed"] is True, "the live schedule is unsigned — --apply refuses nightly"
    assert st["tampered"] is False, "the sequence on file is not what the seed derives"
    assert st["length"] == 12 and len(set(st["expected"])) == 2
