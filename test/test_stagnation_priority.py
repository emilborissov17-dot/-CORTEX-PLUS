# -*- coding: utf-8 -*-
"""test/test_stagnation_priority.py — #59 part 2 (Emil, 11 Sep 2026): a negative constant
is non-progress and must trigger a SEARCH for a solution. Pinned:
  * stagnant_axes() reads the last constancy sweep; absent file -> []
  * proposals about a stagnant axis go first and become HIGH, with stagnation_axis set
  * under the cap, the stagnant-axis proposal is the one admitted
  * the brain's briefing state names the stagnant axes before the state files
  * for_cycle_report carries the count and the names
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import alarm_bands as ab  # noqa: E402
import initiative_tracker as IT  # noqa: E402

ROW = {"axis": "WATER_REVIEW", "class": "NEGATIVE_CONSTANT", "score": 0.3,
       "why": "NON-PROGRESS: unchanged 410 days at score 0.3 (target 100.0)"}


def _constancy(tmp_path, monkeypatch, rows):
    p = tmp_path / "constancy_bands_latest.json"
    p.write_text(json.dumps({"stagnation": rows, "rows": rows}), encoding="utf-8")
    monkeypatch.setattr(ab, "CONSTANCY_LOG", p)
    return p


def test_stagnant_axes_reads_the_sweep_and_survives_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "CONSTANCY_LOG", tmp_path / "absent.json")
    assert ab.stagnant_axes() == []
    _constancy(tmp_path, monkeypatch, [ROW, {"no_axis": 1}])
    assert [r["axis"] for r in ab.stagnant_axes()] == ["WATER_REVIEW"]


def test_proposals_about_a_stagnant_axis_go_first_and_high():
    stag = {"WATER_REVIEW": dict(ROW, metric="safe_water_access_pct")}
    props = [{"measurable_goal": "Forest area up", "priority": "MEDIUM"},
             {"measurable_goal": "raise safe_water_access_pct to 80", "priority": "LOW"},
             {"problem": "water review stalls", "solution": "x", "priority": "MEDIUM"}]
    out, raised = IT.prioritise_for_stagnation(props, stag)
    assert raised == 2
    assert out[0]["stagnation_axis"] == "WATER_REVIEW" and out[0]["priority"] == "HIGH"
    assert out[1]["stagnation_axis"] == "WATER_REVIEW"
    assert out[2]["measurable_goal"] == "Forest area up" and "stagnation_axis" not in out[2]
    assert IT.prioritise_for_stagnation(props, {}) == (props, 0)


def test_under_the_cap_the_stagnant_axis_is_admitted(tmp_path, monkeypatch):
    _constancy(tmp_path, monkeypatch, [ROW])
    d = tmp_path / "initiatives"; d.mkdir()
    p = tmp_path / "improvement_proposals.json"
    props = [{"measurable_goal": f"unique goal {i} about topic {i}", "solution": f"s{i}", "problem": "p",
              "timestamp": f"2026-09-{i + 1:02d}T00:00:00", "priority": "MEDIUM", "component": "x"} for i in range(6)]
    props.append({"measurable_goal": "Safe water access (%) to 80", "solution": "wells", "problem": "p",
                  "timestamp": "2026-09-20T00:00:00", "priority": "LOW", "component": "WATER_REVIEW"})
    p.write_text(json.dumps({"proposals": props}), encoding="utf-8")
    monkeypatch.setattr(IT, "INITIATIVES_DIR", d)
    monkeypatch.setattr(IT, "PROPOSALS_PATH", p)
    monkeypatch.setattr(IT, "_INDICATORS_PATH", tmp_path / "none.json")
    monkeypatch.setattr(IT, "MAX_ACTIVE", 3)
    monkeypatch.setattr(IT, "_apply_overdue_transitions", lambda: 0)
    monkeypatch.setattr(IT, "_generate_action_plan", lambda **kw: [])
    IT.run()
    recs = [json.loads(f.read_text(encoding="utf-8")) for f in d.glob("*.json")]
    active = [r for r in recs if r["status"] == "PROPOSED"]
    assert len(active) == 3
    water = [r for r in active if r.get("stagnation_axis") == "WATER_REVIEW"]
    assert len(water) == 1 and water[0]["priority"] == "HIGH"


def test_the_brain_briefing_names_stagnation_first(tmp_path, monkeypatch):
    _constancy(tmp_path, monkeypatch, [ROW])
    from core import brain
    monkeypatch.setattr(brain, "recent_reviews", lambda n=3: [])
    state = brain._state_for_briefing()
    assert state.startswith("--- STAGNATION") and "WATER_REVIEW" in state.splitlines()[1]


def test_for_cycle_report_carries_stagnation(tmp_path, monkeypatch):
    _constancy(tmp_path, monkeypatch, [ROW])
    monkeypatch.setattr(ab, "sweep", lambda: {"AWAITING_HUMAN_VALUES": 0, "axes": 0, "alarms": [], "config_errors": []})
    monkeypatch.setattr(ab, "sweep_indicators", lambda: {"bands": 0, "counts": {}, "alarms": []})
    r = ab.for_cycle_report()
    assert r["stagnation"] == 1 and r["stagnant_axes"] == ["WATER_REVIEW"]


def test_the_brain_briefing_carries_base_and_trend(tmp_path, monkeypatch):
    row = dict(ROW, trend={"years": 25, "first": [2000, 30.0], "last": [2024, 30.2], "verdict": "FLAT",
                           "slope_per_year": 0.01, "fit_years": 10})
    p = tmp_path / "constancy_bands_latest.json"
    p.write_text(json.dumps({"stagnation": [row], "rows": [row]}), encoding="utf-8")
    monkeypatch.setattr(ab, "CONSTANCY_LOG", p)
    from core import brain
    monkeypatch.setattr(brain, "recent_reviews", lambda n=3: [])
    state = brain._state_for_briefing()
    assert "--- AXIS BASE AND TREND" in state and "2000 30 -> 2024 30.2, FLAT" in state
