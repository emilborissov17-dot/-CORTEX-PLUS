#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_extraordinary_cycle.py — the alarm clock is HUMAN-OWNED.

External review named the failure precisely: an endogenous trigger that is auto-honoured
is not a horizontal capability, it is vertical creep in a horizontal costume. A system
that can set its own alarm and then answer it has quietly taken the clock.

So the chain is: pulse PROPOSES -> needs report surfaces "OK <id>" -> Emil replies ->
approve_reader (the ONLY authorised writer) writes the supervisor's request -> supervisor
still applies every existing check. Four fences are tested here:

  authorship   the supervisor honours only a file authored by approve_reader AND carrying
               a human approver. A file the system wrote for itself is refused however
               fresh and well-reasoned it is.
  origin       a model_anomaly born from the system's own IDEATION never even qualifies to
               propose. Otherwise the loop closes: ideate -> anomaly -> necessity -> cycle
               -> more ideation. Auto-stimulation, dressed as need.
  rate         4h minimum between extraordinary starts, plus lock and restart budget.
  inflation    >3 requests in 7 days is itself a symptom, surfaced to the human.

  venv\\Scripts\\python.exe test\\test_extraordinary_cycle.py
"""
import json, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "pulse"))
sys.path.insert(0, str(REPO / "experiments" / "needs"))
import supervisor as SV
import pulse_continuum as P
import needs_report as N
import approve_reader as A

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

TMP = Path(tempfile.mkdtemp())
SV.EXTRAORDINARY_PATH = TMP / "extraordinary_request.json"
A.EXTRAORDINARY = SV.EXTRAORDINARY_PATH
P.CYCLE_PROPOSALS = TMP / "proposals.json"
A.CYCLE_PROPOSALS = P.CYCLE_PROPOSALS
N.CYCLE_PROPOSALS = P.CYCLE_PROPOSALS
N.PULSE_STREAM = TMP / "pulse_stream.jsonl"

NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()
CFG = {"daily_hour": 3, "catchup_grace_hours": 20}
STATE_RAN = {"last_run_date": TODAY, "restarts": {}, "failure": None}


def human_req(ts=None, reason="composite_moved: 0.5 -> 0.6", author="approve_reader",
              approver="12345"):
    SV.EXTRAORDINARY_PATH.write_text(json.dumps(
        {"ts": ts or NOW.isoformat(), "reason": reason,
         "authored_by": author, "approved_by": approver}), encoding="utf-8")


# ---------- 1. AUTHORSHIP: only a human-approved file is honoured ----------
human_req()
check("an approve_reader file with a human approver is honoured",
      SV.read_extraordinary(NOW) is not None)

human_req(author="pulse_continuum")
check("a file the PULSE authored is REFUSED (the core fence)",
      SV.read_extraordinary(NOW) is None)

human_req(approver="")
check("approve_reader file with no human approver is refused",
      SV.read_extraordinary(NOW) is None)

SV.EXTRAORDINARY_PATH.write_text(json.dumps({"ts": NOW.isoformat(), "reason": "x"}),
                                 encoding="utf-8")
check("a file with no authorship at all is refused", SV.read_extraordinary(NOW) is None)

# ---------- freshness / consumption ----------
human_req(ts=(NOW - timedelta(minutes=30)).isoformat())
check("a 30-min-old request is litter, not a request", SV.read_extraordinary(NOW) is None)
human_req(ts=(NOW + timedelta(hours=2)).isoformat())
check("a future-dated request is refused", SV.read_extraordinary(NOW) is None)
human_req(reason="   ")
check("a request with no named reason is refused", SV.read_extraordinary(NOW) is None)
SV.EXTRAORDINARY_PATH.write_text("{not json", encoding="utf-8")
check("malformed request is refused, not raised", SV.read_extraordinary(NOW) is None)

human_req()
check("consume deletes the file",
      SV.consume_extraordinary() and not SV.EXTRAORDINARY_PATH.exists())
human_req(author="pulse_continuum")
SV.read_extraordinary(NOW)
check("even a REFUSED file is consumed (it cannot retry tomorrow)",
      SV.consume_extraordinary() and not SV.EXTRAORDINARY_PATH.exists())

# ---------- decide(): honoured request, still fenced ----------
req = {"ts": NOW.isoformat(), "reason": "composite_moved: 0.5 -> 0.6",
       "authored_by": "approve_reader", "approved_by": "12345"}
a = SV.decide(NOW, dict(STATE_RAN), None, None, CFG, extraordinary=req)
check("an approved request starts a cycle even though today's already ran",
      a.kind == SV.START and a.reason.startswith("extraordinary: "))

lock = {"pid": 1234, "cycle_id": "c1", "started_utc": NOW.isoformat()}
a = SV.decide(NOW, dict(STATE_RAN), {"step": "x", "updated_utc": NOW.isoformat()}, lock,
              CFG, lock_pid_alive=True, extraordinary=req)
check("a running cycle still vetoes it", a.kind == SV.NOTHING)

spent = dict(STATE_RAN, failure={"date": TODAY, "reason": "budget"})
check("a spent restart budget still vetoes it",
      SV.decide(NOW, spent, None, None, CFG, extraordinary=req).kind == SV.NOTHING)

recent = dict(STATE_RAN, last_extraordinary_utc=(NOW - timedelta(hours=1)).isoformat())
a = SV.decide(NOW, recent, None, None, CFG, extraordinary=req)
check("rate limit refuses a second start within 4h",
      a.kind == SV.NOTHING and "rate limit" in a.reason)
old = dict(STATE_RAN, last_extraordinary_utc=(NOW - timedelta(hours=5)).isoformat())
check("5h later it is allowed", SV.decide(NOW, old, None, None, CFG,
                                          extraordinary=req).kind == SV.START)

# ---------- 2. PULSE PROPOSES, never writes the supervisor's file ----------
def reasons(*keys):
    return [{"key": k, "points": 1, "why": f"{k} happened"} for k in keys]

SV.EXTRAORDINARY_PATH.unlink(missing_ok=True)
P.CYCLE_PROPOSALS.unlink(missing_ok=True)
r = P.propose_extraordinary_cycle(reasons("unconsumed_drops", "approvals_pending"))
check("routine reasons never propose", r.startswith("not_proposed")
      and not P.CYCLE_PROPOSALS.exists())

r = P.propose_extraordinary_cycle(reasons("composite_moved"))
check("composite_moved proposes", r == "proposed:composite_moved")
check("...and the pulse did NOT write the supervisor's file",
      not SV.EXTRAORDINARY_PATH.exists())
check("...it wrote only a proposal", json.loads(
    P.CYCLE_PROPOSALS.read_text(encoding="utf-8"))["pending"]["reason"].startswith(
        "composite_moved"))

# ---------- 3. ORIGIN RESTRICTION ----------
pen_self = {"by_reason": {"model_anomaly": 3},
            "anomalies_by_origin": {"pulse_ideation": 3}}
pen_ext = {"by_reason": {"model_anomaly": 1},
           "anomalies_by_origin": {"goal_impact_collector": 1}}
pen_mix = {"by_reason": {"model_anomaly": 4},
           "anomalies_by_origin": {"pulse_ideation": 3, "goal_impact_collector": 1}}
check("ideation-born anomalies count as ZERO external", P.external_anomalies(pen_self) == 0)
check("collector-born anomalies count", P.external_anomalies(pen_ext) == 1)
check("a mix counts only the external ones", P.external_anomalies(pen_mix) == 1)

C = {"threshold": 4, "weights": {"penumbra_model_anomaly_new": 3}}
def ctx(pen):
    return {"prev": [], "body": {"disk_gb": 500, "ollama_alive": True}, "new_drops": 0,
            "penumbra": pen, "needs_total": 0, "stalled": [], "composite": 0.5,
            "worst_gap_axis": "AX", "approvals": 0, "ideas_pending": 0}

n_self = P.necessity(ctx(pen_self), C)
check("an IDEATION-born anomaly does not raise necessity at all", n_self["score"] == 0)
n_ext = P.necessity(ctx(pen_ext), C)
check("an externally-sourced anomaly does", n_ext["score"] == 3)

# and end-to-end: a self-born anomaly creates no proposal
P.CYCLE_PROPOSALS.unlink(missing_ok=True)
P.wake(n_self, ctx(pen_self), dry=False)
check("ideation-born anomaly creates NO cycle proposal (loop broken at the root)",
      not P.CYCLE_PROPOSALS.exists())

# ---------- the approval path is the only writer ----------
P.propose_extraordinary_cycle(reasons("composite_moved"))
items = [i for i in N._cycle_request_items() if i.get("approve_id")]
check("the proposal surfaces as an approval item", len(items) == 1)
check("...phrased as a request the human owns",
      items[0]["need"].startswith("PULSE requests extraordinary cycle"))
spec = items[0]["approve"]
check("...of type request_cycle", spec["type"] == "request_cycle")

res = A._apply_cycle_request(spec, "12345")
check("Emil's OK writes the supervisor file", res["ok"] and SV.EXTRAORDINARY_PATH.exists())
body = json.loads(SV.EXTRAORDINARY_PATH.read_text(encoding="utf-8"))
check("...authored by approve_reader with the approver recorded",
      body["authored_by"] == "approve_reader" and body["approved_by"] == "12345")
check("...and the supervisor now honours it", SV.read_extraordinary(NOW) is not None)
check("...and the spent proposal no longer surfaces",
      not [i for i in N._cycle_request_items() if i.get("approve_id")])
check("a cycle request with no reason is refused by the writer too",
      A._apply_cycle_request({"reason": ""}, "12345")["ok"] is False)

# ---------- 4. ANOMALY-INFLATION MONITOR ----------
P.CYCLE_PROPOSALS.write_text(json.dumps({"history": [
    {"ts": (NOW - timedelta(days=d)).isoformat(), "keys": ["composite_moved"]}
    for d in (1, 2, 3)]}), encoding="utf-8")
check("3 requests in a week is not yet flagged",
      not [i for i in N._cycle_request_items() if "auto-stimulation" in i["need"]])

P.CYCLE_PROPOSALS.write_text(json.dumps({"history": [
    {"ts": (NOW - timedelta(days=d)).isoformat(), "keys": ["composite_moved"]}
    for d in (1, 2, 3, 4, 5)]}), encoding="utf-8")
flag = [i for i in N._cycle_request_items() if "auto-stimulation" in i["need"]]
check("5 requests in a week FLAGS possible auto-stimulation", len(flag) == 1)
check("...at high severity, to a human", flag[0]["severity"] == "high"
      and flag[0]["actor"] == "human")
check("...and says not to answer it with more cycles",
      "not more cycles" in flag[0]["proposed_action"])

P.CYCLE_PROPOSALS.write_text(json.dumps({"history": [
    {"ts": (NOW - timedelta(days=d)).isoformat(), "keys": ["composite_moved"]}
    for d in (10, 20, 30, 40, 50)]}), encoding="utf-8")
check("old requests age out of the 7-day window",
      not [i for i in N._cycle_request_items() if "auto-stimulation" in i["need"]])

import shutil
shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
