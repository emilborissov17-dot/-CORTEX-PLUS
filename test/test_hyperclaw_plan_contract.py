"""The HyperClaw plan contract (Kimi Round 31, step 2, 5 Sep 2026).

The generator is told (a) what CORTEX++ can and cannot do, (b) which indicators are
gradeable tonight, with their numbers, and (c) that every step carries
INDICATOR / EXPECTED_DELTA / DEADLINE or is refused at intake. The parser reads those
three lines and nothing else fills them in. Each test names what breaks without it.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from agents.hyperclaw import hyperclaw_orchestrator as hc
from core import proposal_intake as pi


# A permissive cadence check for the tests that use SYNTHETIC axes.
# Added 6 Sep 2026 with the cadence gate. These tests exercise FIELD VALIDATION
# on made-up indicators; they make no claim about when the World Bank publishes,
# so they inject a cadence check exactly as they already inject a resolver. The
# cadence gate itself is tested against the real declaration in
# test/test_cadence_gate.py.
def _any_cadence(indicator, deadline):
    return None



REPO = Path(__file__).resolve().parents[1]
TS = "2026-09-05T20:00:00+00:00"

PLAN = """# HYPERCLAW MULTI-AXIS PLAN - 2026-09-06

HUMAN_AXIS_FOCUS:
  SELECTED_SUBAXES: [HEALTH]
  OBJECTIVE: Register a prediction on infant mortality for the ten worst countries
  PLAN_STEPS:
    - STEP 1: Register a 90-day prediction on HUMAN_HEALTH for the ten lowest countries
      INDICATOR: HUMAN_HEALTH
      EXPECTED_DELTA: -0.4
      DEADLINE: 2026-12-05
    - STEP 2: Publish a report on the refugee axis to GitHub
      **INDICATOR**: HUMAN_REFUGEES__unhcr_total
      EXPECTED_DELTA: +1,5
      DEADLINE: 2026-11-01T00:00:00Z
  CROSS_AXIS_EFFECTS: none

PLANET_AXIS_FOCUS:
  SELECTED_SUBAXES: [CLIMATE]
  OBJECTIVE: Build membrane filters for microplastics in three rivers
  PLAN_STEPS:
    - STEP 1: Deploy filters in the Danube
    - STEP 2: Read NOAA CO2 nightly and register a prediction
      INDICATOR: CLIMATE_GLOBAL_RISK_REVIEW
      EXPECTED_DELTA: zero
      DEADLINE: 2026-10-01
"""


def _resolves(axis, metric):
    table = {("HUMAN_HEALTH", None): 0.5, ("HUMAN_REFUGEES", "unhcr_total"): 1.2e8,
             ("CLIMATE_GLOBAL_RISK_REVIEW", None): 0.3}
    v = table.get((axis, metric))
    return (v, None) if v is not None else (None, f"no reading for {axis}/{metric}")


def test_prompt_states_capabilities_indicators_and_the_three_keys():
    prompt = hc._build_prompt("ctx", "spec", "2026-09-06", "", {"HUMAN_HEALTH": 0.5, "PLANET": 0.61})
    assert "CORTEX++ CAN:" in prompt and "CORTEX++ CANNOT:" in prompt
    assert "GRADEABLE INDICATORS" in prompt
    assert "HUMAN_HEALTH: 0.5" in prompt and "PLANET: 0.61" in prompt
    for key in hc.PROPOSAL_KEYS:
        assert prompt.count(key) >= 8, f"{key} must appear under every STEP of every axis"
    assert "ОТКАЗВА при приемане" in prompt  # the rule is stated to the generator, not only enforced


def test_prompt_without_indicators_says_so_instead_of_inventing_some():
    prompt = hc._build_prompt("ctx", "spec", "2026-09-06", "", {})
    assert "none resolved this cycle" in prompt
    assert re.search(r"^\s+[A-Z_]+: [0-9.]+$", prompt, re.M) is None


def test_parse_plan_reads_the_three_lines_and_nothing_else():
    props = hc.parse_plan(PLAN, "plan-2026-09-06.md", TS)
    by_solution = {p["solution"]: p for p in props}
    assert len(props) == 6  # 2 objectives + 4 steps
    s1 = by_solution["Register a 90-day prediction on HUMAN_HEALTH for the ten lowest countries"]
    assert s1["indicator"] == "HUMAN_HEALTH" and s1["expected_delta"] == -0.4 and s1["deadline"] == "2026-12-05"
    s2 = by_solution["Publish a report on the refugee axis to GitHub"]
    assert s2["indicator"] == "HUMAN_REFUGEES__unhcr_total"      # bold markers stripped
    assert s2["expected_delta"] == 1.5                             # decimal comma accepted
    assert s2["deadline"] == "2026-11-01"                          # time part dropped
    danube = by_solution["Deploy filters in the Danube"]
    assert not any(k in danube for k in ("indicator", "expected_delta", "deadline"))
    co2 = by_solution["Read NOAA CO2 nightly and register a prediction"]
    assert co2["expected_delta"] == "zero"                         # kept verbatim, intake names it
    obj = by_solution["Build membrane filters for microplastics in three rivers"]
    assert "indicator" not in obj and obj["problem"] == "PLANET axis needs progress"
    assert all("measurable_goal" not in p for p in props)          # the fake field is gone


def test_key_lines_never_attach_to_the_wrong_step():
    text = ("HUMAN_AXIS_FOCUS:\n  PLAN_STEPS:\n    - STEP 1: First action of sufficient length\n"
            "PLANET_AXIS_FOCUS:\n      INDICATOR: PLANET\n      EXPECTED_DELTA: 1\n      DEADLINE: 2026-12-01\n")
    props = hc.parse_plan(text, "p.md", TS)
    assert len(props) == 1 and "indicator" not in props[0]  # axis change resets the target


def test_end_to_end_only_complete_steps_pass_the_door(tmp_path):
    props = hc.parse_plan(PLAN, "plan-2026-09-06.md", TS)
    adm, ref = pi.admit(props, "hyperclaw_to_proposals", today=date(2026, 9, 5),
                        resolver=_resolves, cadence_check=_any_cadence, refusals_path=tmp_path / "r.jsonl")
    assert [p["solution"][:20] for p in adm] == ["Register a 90-day pr", "Publish a report on "]
    assert len(ref) == 4
    missing = {r["solution"][:20]: r["missing"] for r in ref}
    assert missing["Deploy filters in th"] == ["indicator", "expected_delta", "deadline"]
    assert missing["Read NOAA CO2 nightl"] == ["expected_delta"]


def test_runner_uses_parse_plan_and_keeps_no_private_parser():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8", errors="ignore")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    body = code[code.find("def _hyperclaw_to_proposals("):code.find("\ndef ", code.find("def _hyperclaw_to_proposals(") + 1)]
    assert "parse_plan(" in body
    assert "_step_dash_re" not in body and "OBJECTIVE" not in body, "the private regex parser came back"
    assert '_inject_proposals(new_proposals, "HYPERCLAW"' in body