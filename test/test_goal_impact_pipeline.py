#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_goal_impact_pipeline.py — the goal_impact collector -> sensorium -> ingest
plumbing, verified with FIXTURES (no browser, no Ollama, no network). Proves:
  - the anti-fabrication guards actually fire (ungrounded evidence, phantom number,
    contested-without-counterview all rejected),
  - a grounded, sign-consistent read composes into a signed/weighted axis vector,
  - the vector drops into the Merkle-committed sensorium and verifies,
  - ingest routes it to BOTH consumers (brain: full vector; composer: moving scalar),
  - an empty read commits nothing (empty is empty — never a fake number).

  venv/Scripts/python.exe test/test_goal_impact_pipeline.py
"""
import json, sys, shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "browser_scout"))
sys.path.insert(0, str(REPO / "experiments" / "sensorium"))

import goal_impact as gi
import sensorium
import goal_impact_collector as col

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILS.append(name)

# Redirect the sensorium under REPO (leaf paths are stored relative to REPO) so the
# real memory/sensorium is never touched.
tmp = REPO / "_ti_test_scratch"
if tmp.exists():
    shutil.rmtree(tmp)
tmp.mkdir(parents=True, exist_ok=True)
sensorium.SENS_DIR    = tmp / "sensorium"
sensorium.LEAVES      = sensorium.SENS_DIR / "_merkle_leaves.jsonl"
sensorium.ROOT_FILE   = sensorium.SENS_DIR / "_merkle_root.json"
sensorium.CONSUMED    = sensorium.SENS_DIR / "_consumed.json"
sensorium.COMPOSER_IN = tmp / "browse_sources"
sensorium.SEMANTIC_IN = tmp / "semantic_inbox"
sensorium.GOALIMP_IN  = tmp / "goal_impact_inbox"
sensorium.SENS_DIR.mkdir(parents=True, exist_ok=True)

PAGE = ("Global Peace Index 2025: the world became less peaceful for the sixth year running. "
        "The number of active armed conflicts rose to 56, the highest since the Second World War. "
        "Analysts note this reflects deteriorating social cohesion across multiple regions.")

GOOD = json.dumps({
    "observation": "active armed conflicts rose to 56, the highest since WWII",
    "evidence": "the number of active armed conflicts rose to 56",
    "value": 56, "unit": "conflicts",
    "sign": "-", "magnitude": 0.7, "dimension": "peace",
    "rationale": "more armed conflict moves away from the goal of peace",
    "contested": False, "counterview": ""})

def fake_good(prompt, num_predict=350, **kw):
    if '"relevant"' in prompt:
        return json.dumps({"relevant": True, "why": ""})
    if '"holds"' in prompt:
        return json.dumps({"holds": True, "why": ""})
    return GOOD
def fake_ungrounded(prompt, num_predict=350, **kw):
    return json.dumps({"observation": "peace improved", "evidence": "peace improved dramatically worldwide",
                       "value": None, "unit": "", "sign": "+", "magnitude": 0.5, "dimension": "peace",
                       "rationale": "x", "contested": False, "counterview": ""})
def fake_badnumber(prompt, num_predict=350, **kw):
    return json.dumps({"observation": "conflicts rose", "evidence": "the world became less peaceful",
                       "value": 999, "unit": "", "sign": "-", "magnitude": 0.5, "dimension": "peace",
                       "rationale": "x", "contested": False, "counterview": ""})
def fake_contested(prompt, num_predict=350, **kw):
    return json.dumps({"observation": "conflicts rose to 56", "evidence": "conflicts rose to 56",
                       "value": 56, "unit": "", "sign": "-", "magnitude": 0.5, "dimension": "peace",
                       "rationale": "x", "contested": True, "counterview": "no"})

gi._local = fake_ungrounded
o, why = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", "cohesion", "http://x")
check("guard: ungrounded evidence rejected", o is None and "grounded" in why)

gi._local = fake_badnumber
o, why = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", "cohesion", "http://x")
check("guard: phantom number rejected", o is None and "number" in why)

gi._local = fake_contested
o, why = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", "cohesion", "http://x")
check("guard: contested without counterview rejected", o is None and "counter" in why)

gi._local = fake_good
o, why = gi.extract_goal_impact(PAGE, "SOCIAL_RELATIONS_REVIEW", "cohesion", "http://x")
check("good component passes guards", o is not None and o["sign"] == "-" and o["signed_scalar"] == -0.7)

o, why = gi.extract_calibrated(PAGE, "SOCIAL_RELATIONS_REVIEW", "cohesion", "http://x", votes=2)
check("consistent votes -> calibrated", o and o.get("impact_confidence") == "calibrated")

pages = [("http://gpi.example/2025", PAGE), ("http://echo.example/cohesion", PAGE)]
trail = col.collect("SOCIAL_RELATIONS_REVIEW", "social cohesion vs the goal", votes=2, pages=pages, drop=True)
vec = trail["vector"]
check("vector has 2 components", vec["n"] == 2)
check("overall signed & weighted computed", "overall_signed_weighted" in vec)
check("dim_weights present (human-owned)", "peace" in vec["dim_weights_used"])
check("dropped into sensorium", trail["dropped"] is not None)

v = sensorium.verify()
check("sensorium Merkle verifies", v["ok"] and v["n"] == 1)

ing = sensorium.ingest()
check("ingest routed the goal_impact drop", ing["ingested"] == 1)
gi_file = sensorium.GOALIMP_IN / "SOCIAL_RELATIONS_REVIEW.json"
comp_file = sensorium.COMPOSER_IN / "SOCIAL_RELATIONS_REVIEW.json"
check("brain inbox got the FULL vector", gi_file.exists() and "components" in json.loads(gi_file.read_text()))
comp = json.loads(comp_file.read_text()) if comp_file.exists() else {}
check("composer got the moving scalar", comp.get("metric") == "goal_impact_signed_weighted"
      and comp.get("value") == vec["overall_signed_weighted"])

full = json.loads(gi_file.read_text())
check("composer extract overall_signed_weighted works", float(full["overall_signed_weighted"]) == vec["overall_signed_weighted"])
check("composer data_date works", full["data_date"] == vec["data_date"])

trail2 = col.collect("SOCIAL_RELATIONS_REVIEW", "x", pages=[], drop=True)
check("empty read commits nothing", trail2["vector"]["n"] == 0 and trail2["dropped"] is None)

shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
