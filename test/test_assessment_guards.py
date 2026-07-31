#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_assessment_guards.py — the ASSESSMENT-layer guards (Progress #39 + #40), fixtures.
Born from two live failures (30 Jul autonomous run):
  #40: "-0.5" read off a colour-scale's tick labels and reported as today's anomaly —
       verbatim + number-in-span, every factual guard passed. _looks_like_scale is the
       deterministic "measurement, not chart furniture" check.
  #39: "+1.0 for higher 2025 warming" stamped calibrated (2 votes, stably wrong). Vote
       consistency proves STABILITY, not CORRECTNESS. _sign_refuted is a canon-anchored
       skeptic that tries to refute the PROPOSED SIGN (never the fact); a refuted or
       uncheckable sign is NOT asserted (sign->0, fact kept, reason named).
No Ollama, no browser, no network.

  venv\\Scripts\\python.exe test\\test_assessment_guards.py
"""
import json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "browser_scout"))
import goal_impact as gi

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

# ---------- #40: deterministic scale/legend detector (no model) ----------
LEGEND = ("Difference from Normal for average temperatures, Jul 30, 2026 Temperature "
          "anomalies (°C) -14 -10 -6 -3 -1 -0.5 0 0.5 1 3 6 10 14")
check("legend tick (-0.5) detected as scale", gi._looks_like_scale(LEGEND, -0.5))
check("real sentence (56) NOT flagged",
      not gi._looks_like_scale("the number of active armed conflicts rose to 56, the highest since 1946", 56))
check("real measurement (1.19) NOT flagged",
      not gi._looks_like_scale("global mean temperature anomaly reached 1.19 C in 2025", 1.19))
check("few numbers NOT flagged", not gi._looks_like_scale("from 3 to 6 to 9", 6))
check("value absent from run NOT flagged", not gi._looks_like_scale("scale: 1 2 3 4 5 6", 42))

# ---------- #39: canon-anchored sign skeptic (stubbed model) ----------
def local_holds(prompt, num_predict=200, **kw):   return json.dumps({"holds": True,  "why": ""})
def local_refutes(prompt, num_predict=200, **kw): return json.dumps({"holds": False, "why": "more warming moves AWAY from the goal"})
def local_raises(prompt, num_predict=200, **kw):  raise ConnectionError("dead server")

gi._local = local_holds
r, note = gi._sign_refuted("conflicts rose to 56", "rose to 56", "-", "peace")
check("correct sign holds", r is False)

gi._local = local_refutes
r, note = gi._sign_refuted("2025 anomalies expected higher", "expected to be higher", "+", "sustainability")
check("inverted sign refuted (the live +1.0 warming case)", r is True and "AWAY" in note)

gi._local = local_raises
r, note = gi._sign_refuted("x", "y", "+", "peace")
check("transport failure -> sign not asserted, named", r is True and "ConnectionError" in note)

# ---------- integration through extract_goal_impact ----------
PAGE = ("Global report 2025. The number of active armed conflicts rose to 56, the highest "
        "since WWII. Temperature anomalies (C) -14 -10 -6 -3 -1 -0.5 0 0.5 1 3 6 10 14")

def router(impact_json, holds):
    """Fake local model: impact read -> impact_json; sign-skeptic -> holds verdict."""
    def _fake(prompt, num_predict=300, **kw):
        if '"holds"' in prompt:
            return json.dumps({"holds": holds, "why": "" if holds else "direction contradicts the goal"})
        return json.dumps(impact_json)
    return _fake

GOOD = {"observation": "armed conflicts rose to 56",
        "evidence": "the number of active armed conflicts rose to 56",
        "value": 56, "unit": "conflicts", "sign": "-", "magnitude": 0.7,
        "dimension": "peace", "rationale": "war moves away from the goal",
        "contested": False, "counterview": ""}

# 1) good component, sign holds -> unchanged
gi._local = router(GOOD, holds=True)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("integration: good + sign holds -> sign kept", o is not None and o["sign"] == "-"
      and o["signed_scalar"] == -0.7 and not o.get("sign_guard"))

# 2) good fact, WRONG sign -> fact kept, sign NOT asserted
BAD_SIGN = dict(GOOD, sign="+")
gi._local = router(BAD_SIGN, holds=False)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("integration: refuted sign -> kept with sign 0 + named reason",
      o is not None and o["sign"] == "0" and o["signed_scalar"] == 0.0
      and "direction contradicts" in (o.get("sign_guard") or ""))

# 3) legend value -> rejected before any sign logic
LEGEND_READ = {"observation": "temperature anomaly is -0.5",
               "evidence": "Temperature anomalies (C) -14 -10 -6 -3 -1 -0.5 0 0.5 1 3 6 10 14",
               "value": -0.5, "unit": "C", "sign": "-", "magnitude": 0.8,
               "dimension": "sustainability", "rationale": "x",
               "contested": False, "counterview": ""}
gi._local = router(LEGEND_READ, holds=True)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("integration: legend tick rejected as non-measurement",
      o is None and "scale" in why)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
