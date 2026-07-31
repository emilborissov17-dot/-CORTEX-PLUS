#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_grounding_locate.py — punctuation-tolerant span location + pre-truncation
chrome stripping. Both born from a measured run, 2026-07-31, 12 real-page extractions:

  _located     qwen2.5:7b quoted a REAL sentence and wrapped it in quotation marks. The
               span was 0.981 similar and matched exactly once punctuation was ignored,
               but GUARD 1 compares a 40-char prefix, so one leading '"' shifted every
               character and a true observation was thrown away. 2 of 12.

  _strip_chrome Wikipedia renders "List of ongoing armed conflicts 33 languages" in its
               nav block; qwen2.5:7b reported "33 ongoing armed conflicts" 6 runs out of
               6. The page is 60k chars and the model sees 6500, so the menu was a large
               share of everything it saw.

The invariant both must preserve: loosening WHERE a span is found must never loosen WHAT
it must contain. A fabricated number must still be caught.

  venv\\Scripts\\python.exe test\\test_grounding_locate.py
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "browser_scout"))
import goal_impact as gi

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

PAGE = ("And it is exactly ten years since the United Nations General Assembly met. "
        "This consensus means that national happiness can now become an operational "
        "objective for governments. The number of active armed conflicts rose to 56.")

# ---------- _located: punctuation-tolerant ----------
check("exact span still located", gi._located("national happiness can now become an operational", PAGE))
check("the live case: model added quotation marks",
      gi._located('"This consensus means that national happiness can now become an operational"', PAGE))
check("curly quotes located", gi._located("“This consensus means that national happiness can now”", PAGE))
check("trailing punctuation located", gi._located("national happiness can now become an operational objective!!", PAGE))
check("case and whitespace still tolerated",
      gi._located("  NATIONAL   Happiness  can now become an operational  ", PAGE))
check("genuinely absent span still rejected",
      not gi._located("global happiness rose by forty percent last year in every country", PAGE))
check("empty span rejected (never vacuously true)", not gi._located("", PAGE))
check("punctuation-only span rejected (loose form is empty)", not gi._located('"""---!!!', PAGE))

# ---------- the loosening must not weaken the number checks ----------
def fake(payload):
    import json
    def _f(prompt, num_predict=350, **kw):
        return json.dumps(payload)
    return _f

gi._RELEVANCE_GATE = False
gi._SIGN_GUARD = False
gi._STRUCTURAL = False

GOOD = {"observation": "active armed conflicts rose to 56",
        "evidence": '"The number of active armed conflicts rose to 56."',
        "value": 56, "unit": "conflicts", "sign": "-", "magnitude": 0.7,
        "dimension": "peace", "rationale": "war moves away from the goal",
        "contested": False, "counterview": ""}
gi._local = fake(GOOD)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("quoted evidence now PASSES end to end (the 2-of-12 case)", o is not None and o["value"] == 56)

# the '33' shape: evidence real, observation smuggles a number that is not in it
BAD = dict(GOOD, observation="33 ongoing armed conflicts",
           evidence='"The number of active armed conflicts rose to 56."', value=None)
gi._local = fake(BAD)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("GUARD 1c still catches a smuggled number under loose location",
      o is None and "33" in why)

PHANTOM = dict(GOOD, value=999, evidence='"The number of active armed conflicts rose to 56."')
gi._local = fake(PHANTOM)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("phantom claimed value still rejected", o is None and "number" in why)

UNGROUNDED = dict(GOOD, evidence='"happiness rose by forty percent worldwide"', value=None,
                  observation="happiness rose")
gi._local = fake(UNGROUNDED)
o, why = gi.extract_goal_impact(PAGE, "AX", "need", "http://x")
check("an absent span is still rejected", o is None and "grounded" in why)

# ---------- _strip_chrome ----------
WIKI = ("Toggle the table of contents List of ongoing armed conflicts 33 languages "
        "العربية Create account Log in "
        "The following is a list of ongoing armed conflicts. Deaths reached 56.")
stripped = gi._strip_chrome(WIKI)
check("the '33 languages' trap is removed", "33" not in stripped)
check("nav phrases removed", "toggle the table of contents" not in stripped.lower()
      and "create account" not in stripped.lower())
check("real content survives", "ongoing armed conflicts" in stripped and "56" in stripped)
check("stripping shortens the model's view", len(stripped) < len(WIKI))

COOKIE = ("This website utilizes technologies such as cookies to enable essential site "
          "functionality. Global temperature anomaly reached 1.19 C in 2025.")
cs = gi._strip_chrome(COOKIE)
check("cookie sentence removed, measurement kept", "cookies" not in cs and "1.19" in cs)

check("a clean page is left materially intact",
      gi._strip_chrome("Global temperature anomaly reached 1.19 C in 2025.")
      == "Global temperature anomaly reached 1.19 C in 2025.")
check("stripping never invents digits",
      not any(c.isdigit() for c in gi._strip_chrome("Toggle the table of contents 33 languages")))

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
