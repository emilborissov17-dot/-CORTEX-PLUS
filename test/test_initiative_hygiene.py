# -*- coding: utf-8 -*-
"""test/test_initiative_hygiene.py — A-3: initiatives stop being a graveyard (11 Sep 2026).

Measured 7–11 Sep: 117 -> 133 PROPOSED, 0 IN_PROGRESS, twenty for one indicator,
three Groq calls a night for plans nobody could advance. Pinned here:
  (a) one active initiative per (indicator, direction); a second is refused
  (b) a cap on active initiatives
  (c) no action_plan at creation; one is generated when a human moves it to IN_PROGRESS
  (d) awaiting_decision() names what waits for the human
No LLM: _generate_action_plan is monkeypatched and counted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import initiative_tracker as IT  # noqa: E402


def _env(tmp_path, monkeypatch, proposals):
    d = tmp_path / "initiatives"; d.mkdir()
    p = tmp_path / "improvement_proposals.json"
    p.write_text(json.dumps({"proposals": proposals}), encoding="utf-8")
    monkeypatch.setattr(IT, "INITIATIVES_DIR", d)
    monkeypatch.setattr(IT, "PROPOSALS_PATH", p)
    monkeypatch.setattr(IT, "_INDICATORS_PATH", tmp_path / "no_indicators.json")
    calls = []
    monkeypatch.setattr(IT, "_generate_action_plan", lambda **kw: (calls.append(kw) or [{"step": "s1"}]))
    monkeypatch.setattr(IT, "_apply_overdue_transitions", lambda: 0)
    return d, calls


def _prop(i, goal, solution="do the thing", priority="MEDIUM"):
    return {"measurable_goal": goal, "solution": f"{solution} #{i}", "problem": "p",
            "timestamp": f"2026-09-{(i % 28) + 1:02d}T00:00:00", "priority": priority, "component": "x"}


def _active(d):
    return [json.loads(f.read_text(encoding="utf-8")) for f in d.glob("*.json")
            if json.loads(f.read_text(encoding="utf-8")).get("status") in ("PROPOSED", "IN_PROGRESS", "OVERDUE")]


# (a) ─────────────────────────────────────────────────────────────────────────

def test_twenty_proposals_for_one_indicator_become_one_initiative(tmp_path, monkeypatch):
    d, calls = _env(tmp_path, monkeypatch, [_prop(i, "Safe water access (%) to 80%") for i in range(20)])
    IT.run()
    act = _active(d)
    assert len(act) == 1
    assert calls == []                                   # (c): no plan generated at creation


def test_different_indicators_are_different_initiatives(tmp_path, monkeypatch):
    d, _ = _env(tmp_path, monkeypatch, [_prop(1, "Safe water access (%) up"), _prop(2, "Electricity access (%) up"),
                                        _prop(3, "Forest area (%) up")])
    IT.run()
    assert len(_active(d)) == 3


def test_a_duplicate_is_refused_on_the_next_night_too(tmp_path, monkeypatch):
    d, _ = _env(tmp_path, monkeypatch, [_prop(1, "Safe water access (%) up")])
    IT.run()
    IT.PROPOSALS_PATH.write_text(json.dumps({"proposals": [_prop(1, "Safe water access (%) up"),
                                                            _prop(9, "Safe water access (%) up")]}), encoding="utf-8")
    IT.run()
    assert len(_active(d)) == 1


# (b) ─────────────────────────────────────────────────────────────────────────

def test_the_cap_holds(tmp_path, monkeypatch):
    monkeypatch.setattr(IT, "MAX_ACTIVE", 5)
    d, _ = _env(tmp_path, monkeypatch, [_prop(i, f"unique goal number {i} about topic {i}") for i in range(12)])
    IT.run()
    assert len(_active(d)) == 5


# the sweep on an existing graveyard ─────────────────────────────────────────

def test_the_sweep_cancels_existing_duplicates_and_names_the_survivor(tmp_path, monkeypatch):
    d, _ = _env(tmp_path, monkeypatch, [])
    for i in range(4):
        rec = {"id": f"init_{i}", "status": "PROPOSED", "priority": "MEDIUM", "milestone": "Safe water access (%) up",
               "problem": "", "solution": "", "created_at": f"2026-08-0{i + 1}T00:00:00+00:00", "target_date": "2027-01-01"}
        (d / f"init_{i}.json").write_text(json.dumps(rec), encoding="utf-8")
    c = IT.dedupe_active()
    assert c["duplicates_cancelled"] == 3 and c["active"] == 1
    kept = json.loads((d / "init_0.json").read_text(encoding="utf-8"))
    assert kept["status"] == "PROPOSED"                  # the oldest survives
    gone = json.loads((d / "init_3.json").read_text(encoding="utf-8"))
    assert gone["status"] == "CANCELLED" and gone["cancel_reason"] == "duplicate of init_0"
    assert IT.dedupe_active()["duplicates_cancelled"] == 0   # idempotent


def test_an_in_progress_initiative_is_never_cancelled_by_the_sweep(tmp_path, monkeypatch):
    d, _ = _env(tmp_path, monkeypatch, [])
    for i, st in enumerate(["PROPOSED", "IN_PROGRESS"]):
        rec = {"id": f"init_{i}", "status": st, "priority": "LOW", "milestone": "Forest area (%) up",
               "problem": "", "solution": "", "created_at": f"2026-08-0{i + 1}T00:00:00+00:00", "target_date": "2027-01-01"}
        (d / f"init_{i}.json").write_text(json.dumps(rec), encoding="utf-8")
    IT.dedupe_active()
    assert json.loads((d / "init_1.json").read_text(encoding="utf-8"))["status"] == "IN_PROGRESS"


# (c) ─────────────────────────────────────────────────────────────────────────

def test_the_plan_is_generated_once_when_a_human_accepts(tmp_path, monkeypatch):
    d, calls = _env(tmp_path, monkeypatch, [_prop(1, "Forest area (%) up")])
    IT.run()
    rid = _active(d)[0]["id"]
    assert calls == []
    assert IT.advance_status(rid, "IN_PROGRESS") is True
    assert len(calls) == 1
    rec = json.loads((d / f"{rid}.json").read_text(encoding="utf-8"))
    assert rec["status"] == "IN_PROGRESS" and rec["action_plan"] == [{"step": "s1"}]
    IT.advance_status(rid, "PROPOSED"); IT.advance_status(rid, "IN_PROGRESS")
    assert len(calls) == 1                               # once


# (d) ─────────────────────────────────────────────────────────────────────────

def test_awaiting_decision_names_ids_and_leaves_in_progress_out(tmp_path, monkeypatch):
    d, _ = _env(tmp_path, monkeypatch, [_prop(1, "Forest area (%) up", priority="HIGH"), _prop(2, "Electricity access (%) up")])
    IT.run()
    w = IT.awaiting_decision()
    assert len(w) == 2 and w[0]["priority"] == "HIGH" and all("id" in x for x in w)
    IT.advance_status(w[0]["id"], "IN_PROGRESS")
    assert len(IT.awaiting_decision()) == 1
