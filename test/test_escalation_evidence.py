#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_escalation_evidence.py — FRAMING CONTROL: the human sees the raw payload, and
the raw payload is what the signature covers.

The gap this closes: the approval item used to carry a sentence the pulse composed
("composite_moved: composite 0.5 -> 0.6"). Whoever writes the sentence chooses the
framing, and framing is most of persuasion. Raw fields do not bend — pre_composite,
post_composite, delta, and for an anomaly the penumbra leaf hash, the source URL and the
violated rule.

The equality between displayed and signed is a PRODUCTION GUARD, not an assertion that
only exists here: supervisor.read_extraordinary() recomputes the digest from the raw
evidence, requires it to equal the signed digest, and only then verifies the signature.
Editing a number breaks step one; editing the digest to match breaks step two.

  venv\\Scripts\\python.exe test\\test_escalation_evidence.py
"""
import json, shutil, sys, tempfile
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
import core.request_signing as RS

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

TMP = Path(tempfile.mkdtemp())
RS.KEY_PATH = TMP / "signing.key"
RS.ensure_key()
SV.EXTRAORDINARY_PATH = TMP / "req.json"
A.EXTRAORDINARY = SV.EXTRAORDINARY_PATH
P.CYCLE_PROPOSALS = TMP / "proposals.json"
A.CYCLE_PROPOSALS = P.CYCLE_PROPOSALS
N.CYCLE_PROPOSALS = P.CYCLE_PROPOSALS
N.PULSE_STREAM = TMP / "stream.jsonl"
N.RATE_BASELINE = TMP / "baseline.json"

NOW = datetime.now(timezone.utc)
FULL_EV = {"pre_composite": 0.50, "post_composite": 0.62, "delta": 0.12,
           "anomaly_leaf_hash": None, "source_url": None, "rule_violated": None}
ANOM_EV = {"pre_composite": 0.50, "post_composite": 0.62, "delta": 0.12,
           "anomaly_leaf_hash": "abc123", "source_url": "https://example.org/x",
           "rule_violated": "(fired R5 from WATER_REVIEW floor 2)"}


# ---------- evidence completeness ----------
ok, missing = RS.evidence_complete(FULL_EV, ["composite_moved"])
check("composite escalation needs pre/post/delta only", ok and not missing)

for f in ("pre_composite", "post_composite", "delta"):
    partial = dict(FULL_EV); partial[f] = None
    ok, missing = RS.evidence_complete(partial, ["composite_moved"])
    check(f"missing {f} makes the evidence incomplete", not ok and f in missing)

ok, missing = RS.evidence_complete(FULL_EV, ["penumbra_model_anomaly_new"])
check("an ANOMALY escalation additionally needs hash+source+rule",
      not ok and set(missing) == {"anomaly_leaf_hash", "source_url", "rule_violated"})
ok, _ = RS.evidence_complete(ANOM_EV, ["penumbra_model_anomaly_new"])
check("...and passes when all three are present", ok)


# ---------- the raw signal carries the numbers; nothing can propose without them ----------
# (since the split, the pulse only EMITS — the watchdog proposes. See
# test_trigger_watchdog.py for the split itself.)
sys.path.insert(0, str(REPO / "experiments" / "watchdog"))
import trigger_watchdog as W
W.PROPOSALS = P.CYCLE_PROPOSALS

def ctx(prev_comp=0.50, comp=0.62):
    return {"prev": [{"spirit": {"composite": prev_comp}}], "composite": comp}

sig = P.build_signal(ctx())
check("the pulse's signal carries the RAW numbers, not a sentence",
      sig["pre_composite"] == 0.50 and sig["post_composite"] == 0.62 and sig["delta"] == 0.12)

ev, missing = W.evidence_from(sig, ["composite_moved"])
check("...and they become complete evidence for a proposal", not missing)

blank = P.build_signal({"prev": [], "composite": None})
_, missing = W.evidence_from(blank, ["composite_moved"])
check("no composites -> the evidence is incomplete", set(missing) >= {"pre_composite", "delta"})
W.PROPOSALS.unlink(missing_ok=True)
r = W.propose(blank, {"keys": ["composite_moved"], "reason": "x"})
check("...so NOTHING can propose on it",
      r.startswith("not_proposed:incomplete_evidence") and not W.PROPOSALS.exists())


# ---------- the item never surfaces without raw fields ----------
def put_pending(evidence, keys=("composite_moved",)):
    P.CYCLE_PROPOSALS.write_text(json.dumps({"pending": {
        "ts": NOW.isoformat(), "proposed_by": "pulse_continuum",
        "reason": "composite_moved: composite 0.5 -> 0.62",
        "keys": list(keys), "evidence": evidence}}), encoding="utf-8")

put_pending(FULL_EV)
items = [i for i in N._cycle_request_items() if i.get("approve_id")]
check("a complete proposal surfaces as an approval item", len(items) == 1)
shown = items[0]["why"]
check("the raw numbers are INLINE in what Emil reads",
      "pre_composite=0.5" in shown and "post_composite=0.62" in shown and "delta=0.12" in shown)
check("displayed evidence == the evidence that will be signed",
      items[0]["evidence"] == items[0]["approve"]["evidence"] == FULL_EV)

put_pending(dict(FULL_EV, delta=None))
items = [i for i in N._cycle_request_items() if i.get("approve_id")]
check("an item missing a raw field NEVER surfaces as approvable", not items)
refusal = [i for i in N._cycle_request_items() if "REFUSED before it could be shown" in i["need"]]
check("...and the refusal is NAMED, with the missing field", refusal
      and "delta" in refusal[0]["need"])

put_pending(FULL_EV, keys=("penumbra_model_anomaly_new",))
check("an anomaly escalation without hash/source/rule cannot surface",
      not [i for i in N._cycle_request_items() if i.get("approve_id")])
put_pending(ANOM_EV, keys=("penumbra_model_anomaly_new",))
items = [i for i in N._cycle_request_items() if i.get("approve_id")]
check("...and surfaces once they are present", len(items) == 1)
check("the leaf hash, source and rule are shown to the human",
      "abc123" in items[0]["why"] and "example.org" in items[0]["why"]
      and "R5" in items[0]["why"])


# ---------- approve_reader refuses to sign incomplete evidence ----------
res = A._apply_cycle_request({"reason": "r", "keys": ["composite_moved"],
                              "evidence": dict(FULL_EV, pre_composite=None)}, "12345")
check("approve_reader refuses to sign incomplete evidence",
      res["ok"] is False and "incomplete evidence" in res["error"])

res = A._apply_cycle_request({"reason": "r", "keys": ["composite_moved"],
                              "evidence": FULL_EV}, "12345")
check("a complete request is signed and written", res["ok"])
body = json.loads(SV.EXTRAORDINARY_PATH.read_text(encoding="utf-8"))
check("the written request carries the raw evidence", body["evidence"] == FULL_EV)
check("...and a digest over it", body["evidence_sha256"] == RS.evidence_digest(FULL_EV))


# ---------- THE PRODUCTION GUARD in read_extraordinary ----------
check("a well-formed signed request is honoured", SV.read_extraordinary(NOW) is not None)

t = json.loads(SV.EXTRAORDINARY_PATH.read_text(encoding="utf-8"))
t["evidence"] = dict(FULL_EV, post_composite=0.99)      # change what was displayed
SV.EXTRAORDINARY_PATH.write_text(json.dumps(t), encoding="utf-8")
check("editing a displayed number after approval is REFUSED in production",
      SV.read_extraordinary(NOW) is None)

t["evidence_sha256"] = RS.evidence_digest(t["evidence"])  # also fix the digest
SV.EXTRAORDINARY_PATH.write_text(json.dumps(t), encoding="utf-8")
check("...and fixing the digest to match still fails the signature",
      SV.read_extraordinary(NOW) is None)

t = json.loads(json.dumps(body)); t.pop("evidence", None)
SV.EXTRAORDINARY_PATH.write_text(json.dumps(t), encoding="utf-8")
check("a request with NO evidence block is refused", SV.read_extraordinary(NOW) is None)

t = json.loads(json.dumps(body)); t["evidence_sha256"] = "0" * 64
SV.EXTRAORDINARY_PATH.write_text(json.dumps(t), encoding="utf-8")
check("a wrong digest is refused even with intact raw fields",
      SV.read_extraordinary(NOW) is None)

SV.EXTRAORDINARY_PATH.write_text(json.dumps(body), encoding="utf-8")
check("the untouched original still verifies (the guard is not just refusing everything)",
      SV.read_extraordinary(NOW) is not None)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
