#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_relevance_gate.py — the RELEVANCE gate, fixtures.

Born from the first real sensorium drop (31 Jul 2026, leaf 51acdab9): 3 of 4 pages were
correctly rejected by the anti-fabrication guards, and the ONE surviving component was a
cookie-consent banner — verbatim, number-free, uncontested, so grounding, number-in-span,
legend-tick and sign guards all passed it. Every guard in the stack asks whether a claim is
GROUNDED; none asked whether it is ABOUT the axis. Result: n=1, overall 0.0 — a
zero-information commit that looked like a successful sensing event.

Two layers, mirroring #40/#39:
  _is_boilerplate      deterministic, free — the page describing itself, not the world.
  _relevance_refuted   axis-anchored skeptic — FAIL-CLOSED (uncheckable -> rejected),
                       because an unverifiable relevance claim is the very thing this
                       gate exists to keep out of the Merkle chain.
Rejection happens inside extract_goal_impact, so no component ever forms and the
collector's existing n=0 path skips the drop ("empty is empty").
No Ollama, no browser, no network.

  venv\\Scripts\\python.exe test\\test_relevance_gate.py
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

# The exact text that survived the first real drop.
COOKIE = ("This website utilizes technologies such as cookies to enable essential site "
          "functionality, as well as for analytics, personalization, and targeted advertising.")

# ---------- deterministic layer (no model) ----------
check("live cookie banner detected as boilerplate", gi._is_boilerplate(COOKIE, COOKIE))
check("consent bar detected", gi._is_boilerplate("Accept all cookies", "Accept all cookies to continue"))
check("real measurement NOT flagged",
      not gi._is_boilerplate("global mean temperature anomaly reached 1.19 C in 2025",
                             "temperature anomaly reached 1.19 C"))
check("real sentence NOT flagged",
      not gi._is_boilerplate("active armed conflicts rose to 56",
                             "the number of active armed conflicts rose to 56"))
check("single incidental keyword NOT flagged (>=2 required)",
      not gi._is_boilerplate("the paper criticises targeted advertising in climate reporting",
                             "criticises targeted advertising"))

# ---------- axis-anchored skeptic (stubbed model) ----------
def local_relevant(prompt, num_predict=200, **kw):   return json.dumps({"relevant": True,  "why": ""})
def local_irrelevant(prompt, num_predict=200, **kw): return json.dumps({"relevant": False, "why": "a cookie notice says nothing about climate risk"})
def local_raises(prompt, num_predict=200, **kw):     raise ConnectionError("dead server")

gi._local = local_relevant
r, why = gi._relevance_refuted("conflicts rose to 56", "rose to 56", "SOCIAL_RELATIONS_REVIEW", "cohesion")
check("on-topic observation not refuted", r is False)

gi._local = local_irrelevant
r, why = gi._relevance_refuted(COOKIE, COOKIE, "CLIMATE_GLOBAL_RISK_REVIEW", "event_daily source")
check("off-topic observation refuted, reason named", r is True and "cookie notice" in why)

gi._local = local_raises
r, why = gi._relevance_refuted("x", "y", "AX", "need")
check("transport failure -> FAIL-CLOSED, named", r is True and "ConnectionError" in why)

# ---------- integration through extract_goal_impact ----------
PAGE = ("Global report 2025. The number of active armed conflicts rose to 56, the highest "
        "since WWII. " + COOKIE)

def router(impact_json, relevant=True, holds=True):
    def _fake(prompt, num_predict=300, **kw):
        if '"relevant"' in prompt:
            return json.dumps({"relevant": relevant,
                               "why": "" if relevant else "not about the axis at all"})
        if '"holds"' in prompt:
            return json.dumps({"holds": holds, "why": ""})
        return json.dumps(impact_json)
    return _fake

GOOD = {"observation": "armed conflicts rose to 56",
        "evidence": "the number of active armed conflicts rose to 56",
        "value": 56, "unit": "conflicts", "sign": "-", "magnitude": 0.7,
        "dimension": "peace", "rationale": "war moves away from the goal",
        "contested": False, "counterview": ""}

# THE REGRESSION: the first real drop's component, replayed end to end.
BANNER_READ = dict(GOOD, observation=COOKIE, evidence=COOKIE, value=None, unit="",
                   sign="0", magnitude=0.1, dimension="sustainability",
                   rationale="unrelated to the goal")
gi._local = router(BANNER_READ, relevant=True)   # even if the skeptic says yes, det. layer kills it
o, why = gi.extract_goal_impact(PAGE, "CLIMATE_GLOBAL_RISK_REVIEW", "event_daily", "http://x")
check("integration: live cookie-banner component rejected (leaf 51acdab9 regression)",
      o is None and "boilerplate" in why)

# on-topic read still passes the whole stack untouched
gi._local = router(GOOD, relevant=True, holds=True)
o, why = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", "cohesion", "http://x")
check("integration: relevant observation still passes", o is not None and o["sign"] == "-"
      and o["signed_scalar"] == -0.7)

# off-topic but not boilerplate -> caught by the skeptic, reason named
gi._local = router(GOOD, relevant=False)
o, why = gi.extract_goal_impact(PAGE, "CLIMATE_GLOBAL_RISK_REVIEW", "event_daily", "http://x")
check("integration: off-topic rejected by the skeptic, reason named",
      o is None and "relevance" in why and "not about the axis" in why)

# the gate is the ONLY thing standing between the banner and the chain — prove it
gi._RELEVANCE_GATE = False
gi._local = router(BANNER_READ, holds=True)
o, why = gi.extract_goal_impact(PAGE, "CLIMATE_GLOBAL_RISK_REVIEW", "event_daily", "http://x")
check("gate off -> the banner passes again (proves the gate is what stops it)", o is not None)
gi._RELEVANCE_GATE = True

# and with the gate on, nothing groundable -> the collector commits nothing
gi._local = router(BANNER_READ, holds=True)
o, why = gi.extract_calibrated(PAGE, "CLIMATE_GLOBAL_RISK_REVIEW", "event_daily", "http://x", votes=2)
check("calibrated: banner yields no component at all", o is None and "nothing groundable" in why)

vec = gi.compose_vector([])
check("empty vector -> n=0 (collector skips the drop)", vec["n"] == 0)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
