#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_structural_faithfulness.py — v0 of the DNA-vs-DNA guard (Progress #34), fixtures only.
Proves goal_impact.structural_faithful() decomposes an observation into atomic claims and
requires EACH to survive (1) per-claim verbatim+number grounding and (2) adversarial entailment
(a strict skeptic seeing ONLY the claim's evidence_span). Catches numeric AND non-numeric
fabrication — the gap the single digit guard could not. No Ollama, no browser, no network.

  venv\\Scripts\\python.exe test\\test_structural_faithfulness.py
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

PAGE = ("Global report 2025. The number of active armed conflicts rose to 56, the highest "
        "since WWII. In some regions tensions eased somewhat this year. "
        "The following is a list of ongoing armed conflicts around the world.")

def make_local(claims, refute_map):
    """Fake local model: routes on the prompt. Decompose -> the claims list; skeptic -> the
    per-claim supported verdict (missing => supported True)."""
    def _fake(prompt, num_predict=300, **kw):
        if "Decompose" in prompt:
            return json.dumps({"claims": claims})
        if "skeptic" in prompt:
            for ctext, sup in refute_map.items():
                if ctext[:25] in prompt:
                    return json.dumps({"supported": sup, "why": "x"})
            return json.dumps({"supported": True, "why": "x"})
        return "{}"
    return _fake

# 1) FAITHFUL — one grounded, supported claim
gi._local = make_local(
    [{"text": "active armed conflicts rose to 56", "entity": "armed conflicts",
      "predicate": "rose", "quantity": {"value": 56, "unit": "conflicts"}, "polarity": "-",
      "evidence_span": "the number of active armed conflicts rose to 56"}],
    {"active armed conflicts rose to 56": True})
p, sv, br = gi.structural_faithful("armed conflicts rose to 56", "", PAGE)
check("faithful component passes (1 survivor, 0 broken)", p and len(sv) == 1 and not br)

# 2) FABRICATED NUMBER — "33" quoting a numberless span
gi._local = make_local(
    [{"text": "33 ongoing armed conflicts", "quantity": {"value": 33, "unit": ""},
      "polarity": "-", "evidence_span": "The following is a list of ongoing armed conflicts"}],
    {"33 ongoing armed conflicts": True})
p, sv, br = gi.structural_faithful("33 ongoing armed conflicts", "", PAGE)
check("fabricated number rejected (grounding), names the claim",
      not p and br and br[0]["stage"] == "grounding" and "33" in (br[0]["claim"] or ""))

# 3) FABRICATED POLARITY — grounded number, wrong direction; skeptic refutes
gi._local = make_local(
    [{"text": "armed conflicts fell to 56", "quantity": {"value": 56, "unit": ""},
      "polarity": "+", "evidence_span": "the number of active armed conflicts rose to 56"}],
    {"armed conflicts fell to 56": False})
p, sv, br = gi.structural_faithful("armed conflicts fell to 56", "", PAGE)
check("fabricated polarity rejected (entailment)", not p and br and br[0]["stage"] == "entailment")

# 4) PARAPHRASE — evidence_span not verbatim in the page
gi._local = make_local(
    [{"text": "conflicts increased sharply", "quantity": {"value": None, "unit": ""},
      "polarity": "-", "evidence_span": "conflicts have increased dramatically across the globe"}],
    {"conflicts increased sharply": True})
p, sv, br = gi.structural_faithful("conflicts increased sharply", "", PAGE)
check("paraphrased evidence rejected (grounding, not verbatim)",
      not p and br and br[0]["stage"] == "grounding")

# 5) NON-NUMERIC FABRICATION — verbatim span, no number, but claim contradicts it
gi._local = make_local(
    [{"text": "the situation is catastrophic", "quantity": {"value": None, "unit": ""},
      "polarity": "-", "evidence_span": "tensions eased somewhat this year"}],
    {"the situation is catastrophic": False})
p, sv, br = gi.structural_faithful("the situation is catastrophic", "", PAGE)
check("NON-numeric fabrication rejected (entailment) — the key gap",
      not p and br and br[0]["stage"] == "entailment")

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
