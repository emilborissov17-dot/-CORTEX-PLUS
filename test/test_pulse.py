#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_pulse.py — the PULSE continuum (#50). Everything external is stubbed.

What is being defended:
  necessity is ARITHMETIC over named thresholds, and every contribution is NAMED, so a
  wake is explainable and a silence is auditable;
  under threshold the tick takes NO actions — silence is the normal state;
  a missing canon degrades, it does not crash — there is no tick without a goal frame,
  but there is a tick with the fallback one;
  ideation refuses ungrounded refs and tests without a horizon;
  a mentor contradiction is KEPT as training material and NOT surfaced;
  a contradiction that stands on sourced observation goes to the PENUMBRA as
  model_anomaly — the novelty door, not the bin;
  the reflection is skipped silently when the model is dead.

  venv\\Scripts\\python.exe test\\test_pulse.py
"""
import json, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "pulse"))
import pulse_continuum as P

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

TMP = Path(tempfile.mkdtemp())
P.STREAM = TMP / "pulse_stream.jsonl"
P.IDEAS = TMP / "idea_stream.jsonl"

C = {"threshold": 4, "context_lines": 24, "series_stall_hours": 26, "composite_move": 0.02,
     "disk_free_gb_min": 10, "quiet_hour": 21, "no_fire_hours_for_creative": 6,
     "reflection_every_n_ticks": 12,
     "weights": {"unconsumed_drops": 2, "needs_increased": 1, "series_stalled": 2,
                 "composite_moved": 3, "disk_low": 3, "ollama_dead": 2,
                 "approvals_pending": 1, "penumbra_model_anomaly_new": 3}}

def ctx(**over):
    base = {"prev": [], "body": {"disk_gb": 500, "ram_pct": 40, "ollama_alive": True},
            "leaf_n": 1, "new_drops": 0, "penumbra": {"n_active": 0, "by_reason": {}},
            "needs_total": 10, "stalled": [], "composite": 0.5,
            "worst_gap_axis": "AX", "approvals": 0, "ideas_pending": 0}
    base.update(over)
    return base

def keys_of(n):
    return {r["key"] for r in n["reasons"]}

# ---------- necessity: each trigger fires with its named reason ----------
n = P.necessity(ctx(), C)
check("quiet context scores 0 with no reasons", n["score"] == 0 and n["reasons"] == [])

n = P.necessity(ctx(new_drops=3), C)
check("unconsumed drops fires (+2), named", n["score"] == 2 and "unconsumed_drops" in keys_of(n))
check("...and the reason states the count", "3 unconsumed" in n["reasons"][0]["why"])

prev = [{"mind": {"needs_total": 5, "penumbra_anomalies": 0}, "spirit": {"composite": 0.5}}]
n = P.necessity(ctx(prev=prev, needs_total=9), C)
check("needs increase fires (+1)", n["score"] == 1 and "needs_increased" in keys_of(n))
n = P.necessity(ctx(prev=prev, needs_total=3), C)
check("needs DECREASE does not fire", n["score"] == 0)

n = P.necessity(ctx(stalled=["A", "B"]), C)
check("stalled series fires (+2), names the axes",
      n["score"] == 2 and "A" in n["reasons"][0]["why"])

# THE SPLIT: composite movement no longer contributes to necessity at all. That
# comparison existed to justify an escalation, so it moved to the watchdog — the pulse
# reports the composite and forms no opinion about whether the move is big enough.
n = P.necessity(ctx(prev=prev, needs_total=5, composite=0.60), C)
check("a LARGE composite move no longer raises the pulse's own necessity",
      n["score"] == 0 and "composite_moved" not in keys_of(n))
n = P.necessity(ctx(prev=prev, needs_total=5, composite=0.505), C)
check("...and neither does a small one", n["score"] == 0)

n = P.necessity(ctx(body={"disk_gb": 4, "ram_pct": 20, "ollama_alive": True}), C)
check("low disk fires (+3)", n["score"] == 3 and "disk_low" in keys_of(n))
n = P.necessity(ctx(body={"disk_gb": 500, "ram_pct": 20, "ollama_alive": False}), C)
check("dead ollama fires (+2)", n["score"] == 2 and "ollama_dead" in keys_of(n))
n = P.necessity(ctx(approvals=2), C)
check("pending approvals fire (+1)", n["score"] == 1)

EXT_ANOM = {"n_active": 1, "by_reason": {"model_anomaly": 1},
            "anomalies_by_origin": {"goal_impact_collector": 1}}
n = P.necessity(ctx(penumbra=EXT_ANOM), C)
check("a NEW externally-sourced model_anomaly fires (+3)", n["score"] == 3
      and "penumbra_model_anomaly_new" in keys_of(n))
prev_a = [{"mind": {"needs_total": 10, "penumbra_anomalies_external": 1},
           "spirit": {"composite": 0.5}}]
n = P.necessity(ctx(prev=prev_a, penumbra=EXT_ANOM), C)
check("the SAME anomaly does not re-fire every tick", n["score"] == 0)
n = P.necessity(ctx(penumbra={"n_active": 1, "by_reason": {"model_anomaly": 1},
                              "anomalies_by_origin": {"pulse_ideation": 1}}), C)
check("an anomaly the system IDEATED never fires", n["score"] == 0)
n = P.necessity(ctx(penumbra={"n_active": 1, "by_reason": {"model_anomaly": 1}}), C)
check("an anomaly with UNKNOWN provenance never fires (fail-closed)", n["score"] == 0)

n = P.necessity(ctx(new_drops=1, stalled=["A"]), C)
check("contributions add up and each is named separately",
      n["score"] == 4 and len(n["reasons"]) == 2)

# ---------- threshold behaviour ----------
check("below threshold -> no waking actions", P.wake(P.necessity(ctx(approvals=1), C),
                                                     ctx(approvals=1), dry=True) == ["dry:approvals_pending"])
called = {"ingest": 0}
class FakeSens:
    LEAVES = CONSUMED = None
    @staticmethod
    def ingest():
        called["ingest"] += 1
        return {"ingested": 2}
sys.modules["sensorium"] = FakeSens
acted = P.wake({"reasons": [{"key": "unconsumed_drops"}]}, ctx(), dry=False)
check("over threshold WAKES sensorium ingest", called["ingest"] == 1 and "ingest=2" in acted[0])
acted = P.wake({"reasons": [{"key": "unconsumed_drops"}]}, ctx(), dry=True)
check("dry run takes no real action", called["ingest"] == 1 and acted == ["dry:unconsumed_drops"])

# the pulse may ASK for a cycle, never start one — and only for cycle-worthy reasons.
# (Freshness, consumption and the 4h rate limit are the supervisor's side and live in
# test_extraordinary_cycle.py.)
# THE SPLIT: the pulse cannot propose a cycle at all any more. It emits the raw signal
# and a separate process decides. (test_trigger_watchdog.py owns that contract.)
P.CYCLE_PROPOSALS = TMP / "proposals.json"
P.PULSE_SIGNAL = TMP / "pulse_signal.json"
PCTX = ctx(prev=[{"spirit": {"composite": 0.50}}], composite=0.62)
check("the pulse has no proposal function", not hasattr(P, "propose_extraordinary_cycle"))
acted = P.wake({"reasons": [{"key": "composite_moved", "why": "0.5 -> 0.6"}]},
               PCTX, dry=False)
check("wake() no longer emits any cycle proposal",
      not any("cycle_proposal" in a or "cycle_request" in a for a in acted))
check("...and writes no proposal file", not P.CYCLE_PROPOSALS.exists())
check("the pulse emits the raw signal instead", P.emit_signal(PCTX) == "signal_written"
      and json.loads(P.PULSE_SIGNAL.read_text(encoding="utf-8"))["delta"] == 0.12)
P.PULSE_SIGNAL.unlink(missing_ok=True)

# ---------- degraded core ----------
import builtins
real_import = builtins.__import__
def no_canon(name, *a, **k):
    if name == "core.canon" or name.endswith("canon"):
        raise ImportError("no canon")
    return real_import(name, *a, **k)
builtins.__import__ = no_canon
frame, degraded = P.moral_core()
builtins.__import__ = real_import
check("canon failure degrades, does not crash", degraded is True and len(frame) > 20)
line = P.state_line(ctx(), {"score": 0, "reasons": []}, True)
check("the degraded line still has the full schema",
      set(line) >= {"ts", "body", "mind", "spirit", "necessity", "degraded_core"}
      and line["degraded_core"] is True)

# ---------- stream line schema ----------
line = P.state_line(ctx(new_drops=2, stalled=["A"]), {"score": 4, "reasons": []}, False)
check("body block stable", set(line["body"]) == {"disk_gb", "ram_pct", "ollama_alive"})
check("mind block stable", {"needs_total", "new_drops", "penumbra_active",
                            "series_stalled_axes"} <= set(line["mind"]))
check("spirit block stable", set(line["spirit"]) == {"composite", "worst_gap_axis",
                                                     "ideas_pending"})
check("necessity carries score and reasons", set(line["necessity"]) == {"score", "reasons"})

# ---------- reflection ----------
check("reflection skipped silently when ollama is dead",
      P.reflection(ctx(body={"disk_gb": 1, "ram_pct": 1, "ollama_alive": False}), "f") == {})

# ---------- ideation guards ----------
P.seeds_rule_violation = lambda: [{"kind": "hypothesis", "seed": "rule_violation",
                                   "axis": "AX", "detail": "d", "proof": ["(fired R5)"]}]
P.seeds_trend = lambda min_points=5: []

def art(payload):
    return lambda seed, frame: payload

P.mentor = lambda rec, seed: {"checked": True, "contradicts": False}
P.articulate = art({"idea": "a real idea", "grounded_on": ["config/pulse.json"],
                    "dimension": "truth", "falsifiable_test": "check X",
                    "horizon": "2026-09-01"})
r = P.ideate("frame", dry=True)
check("a grounded, falsifiable idea is kept", len(r["kept"]) == 1)

P.articulate = art({"idea": "x", "grounded_on": ["memory/does_not_exist_zzz.json"],
                    "dimension": "d", "falsifiable_test": "t", "horizon": "2026-09-01"})
r = P.ideate("frame", dry=True)
check("ungrounded ref rejected", not r["kept"] and "ungrounded" in r["rejected"][0]["why"])

P.articulate = art({"idea": "x", "grounded_on": ["config/pulse.json"],
                    "dimension": "d", "falsifiable_test": "", "horizon": "2026-09-01"})
r = P.ideate("frame", dry=True)
check("missing falsifiable_test rejected", not r["kept"] and "falsifiable" in r["rejected"][0]["why"])

P.articulate = art({"idea": "x", "grounded_on": ["config/pulse.json"],
                    "dimension": "d", "falsifiable_test": "t", "horizon": ""})
r = P.ideate("frame", dry=True)
check("missing horizon rejected", not r["kept"])

# mentor contradiction, NOT well-sourced -> kept as training material, not surfaced
P.articulate = art({"idea": "contradicting idea", "grounded_on": ["config/pulse.json"],
                    "dimension": "d", "falsifiable_test": "t", "horizon": "2026-09-01"})
P.mentor = lambda rec, seed: {"checked": True, "contradicts": True, "proof": ["(fired R5)"],
                              "well_sourced": False}
r = P.ideate("frame", dry=True)
check("mentor contradiction is NOT surfaced", not r["kept"])
check("...but is kept with its proof (training material)",
      r["rejected"] and r["rejected"][0].get("proof") == ["(fired R5)"])

# contradiction + well-sourced -> penumbra model_anomaly (the novelty door)
dropped = {}
class FakeSens2:
    @staticmethod
    def drop(axis, kind, payload, collector=None, quarantine=None):
        dropped.update({"axis": axis, "kind": kind, "quarantine": quarantine})
        return "PEN/1"
sys.modules["sensorium"] = FakeSens2
P.mentor = lambda rec, seed: {"checked": True, "contradicts": True, "proof": ["(fired R5)"],
                              "well_sourced": True}
r = P.ideate("frame", dry=False)
check("rule-contradicting + well-sourced routes to the PENUMBRA", len(r["penumbra"]) == 1)
check("...as model_anomaly, the reason that never expires",
      dropped.get("quarantine") == {"reason": "model_anomaly"})
check("...and is not surfaced as a kept idea", not r["kept"])
check("every idea carries the outcome metric fields",
      r["penumbra"][0]["outcome"] is None and r["penumbra"][0]["test_horizon"])

# ── the grounding guard, which was open ──────────────────────────────────────
#
# _refs_exist did `split("#", 1)[0]` to drop a fragment from "docs/FILE.md#section".
# Given "#GLOBAL-TARGET.md" that returns the EMPTY STRING, and REPO / "" is the repo
# root, which exists — so the check passed. The one idea the creative phase had produced
# by 2026-08-03 cited "#GLOBAL-TARGET.md" and "#PODCELLS.md", neither a file in this
# repo, and was kept and surfaced with well_sourced=true. A guard that accepts an
# invented citation is worse than no guard: it puts a stamp on the hallucination.

check("a ref that is nothing but an anchor is NOT grounding — the live bug",
      P._refs_exist(["#GLOBAL-TARGET.md"]) is False)
check("...nor two of them", P._refs_exist(["#GLOBAL-TARGET.md", "#PODCELLS.md"]) is False)
check("an empty ref list is not grounding", P._refs_exist([]) is False)
check("a file that does not exist is not grounding",
      P._refs_exist(["docs/NOT_A_REAL_FILE_xyz.md"]) is False)
check("a DIRECTORY is not a citation — it always exists and grounds nothing",
      P._refs_exist(["docs"]) is False and P._refs_exist(["."]) is False)
check("a path escaping the repo is refused", P._refs_exist(["../../etc/passwd"]) is False)
check("a real file IS grounding", P._refs_exist(["CLAUDE.md"]) is True)
check("...and a real file with an anchor fragment still is",
      P._refs_exist(["CLAUDE.md#python-interpreter"]) is True)
check("one bad ref among good ones fails the whole set",
      P._refs_exist(["CLAUDE.md", "#INVENTED.md"]) is False)

import shutil as _sh
_sh.rmtree(TMP, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
