#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_trigger_watchdog.py — THE SPLIT: the process that computes the escalation is no
longer the process that benefits from it.

Before: pulse_continuum measured the composite move, judged it cycle-worthy, and wrote its
own proposal. Its necessity score rose when it escalated, and it decided whether to
escalate. That is the shape to remove, whatever the intentions of the code inside it.

After: the pulse emits raw numbers and stops. trigger_watchdog reads them, applies
thresholds it never computes, RE-DERIVES any cited penumbra leaf hash from the chain, and
can only ever write a proposal — the cry. Emil's OK is still what creates authority.

Honest about what this is: defense-in-depth with a known co-residence vulnerability (same
user, same filesystem, same kernel, editable code), not a capability boundary. The walls
below are named speed bumps. BACKLOG #58 is the real boundary.

  venv\\Scripts\\python.exe test\\test_trigger_watchdog.py
"""
import ast, json, re, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


def code_of(path):
    """Source with docstrings and comments REMOVED.

    A capability wall must be asserted against what the module DOES, not against what it
    says. Scanning raw text makes an honest docstring ('never imports core.request_signing')
    indistinguishable from the import it disclaims — the first version of this file failed
    exactly that way."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def prose_of(path):
    """The human-readable text, whitespace-collapsed so a wrapped sentence still matches."""
    return re.sub(r"\s+", " ", Path(path).read_text(encoding="utf-8"))


def call_names(fn_node):
    out = set()
    for n in ast.walk(fn_node):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(getattr(f, "id", None) or getattr(f, "attr", None))
    return {x for x in out if x}

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "experiments" / "pulse"))
sys.path.insert(0, str(REPO / "experiments" / "watchdog"))
sys.path.insert(0, str(REPO / "experiments" / "needs"))
sys.path.insert(0, str(REPO / "experiments" / "sensorium"))
import pulse_continuum as P
import trigger_watchdog as W
import needs_report as N
import approve_reader as A
import supervisor as SV
import core.request_signing as RS
import sensorium as S

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

TMP = Path(tempfile.mkdtemp())
NOW = datetime.now(timezone.utc)

W.CONFIG = TMP / "watchdog.json"
W.SIGNAL = TMP / "pulse_signal.json"
W.PROPOSALS = TMP / "proposals.json"
W.FORBIDDEN_OUTPUT = TMP / "extraordinary_request.json"
P.PULSE_SIGNAL = W.SIGNAL
N.CYCLE_PROPOSALS = W.PROPOSALS
A.CYCLE_PROPOSALS = W.PROPOSALS
A.EXTRAORDINARY = W.FORBIDDEN_OUTPUT
SV.EXTRAORDINARY_PATH = W.FORBIDDEN_OUTPUT
RS.KEY_PATH = TMP / "signing.key"
RS.ensure_key()

W.CONFIG.write_text(json.dumps({"composite_move_min": 0.02,
                                "propose_on_verified_anomaly": True,
                                "min_gap_minutes": 60,
                                "signal_max_age_minutes": 30}), encoding="utf-8")


def write_signal(delta=0.12, pre=0.50, post=0.62, ts=None, **extra):
    sig = {"ts": ts or NOW.isoformat(), "pre_composite": pre, "post_composite": post,
           "delta": delta, "anomaly_leaf_hash": None, "source_url": None,
           "rule_violated": None}
    sig.update(extra)
    W.SIGNAL.write_text(json.dumps(sig), encoding="utf-8")
    return sig


# ---------- 1. the pulse emits a SIGNAL, never a qualification ----------
PULSE_PY = REPO / "experiments" / "pulse" / "pulse_continuum.py"
psrc = code_of(PULSE_PY)
check("pulse no longer has propose_extraordinary_cycle",
      "def propose_extraordinary_cycle" not in psrc)
check("pulse no longer has a _CYCLE_WORTHY gate", "_CYCLE_WORTHY" not in psrc)
check("pulse no longer READS a composite threshold",
      "composite_move" not in psrc and "'composite_moved'" not in psrc
      and '"composite_moved"' not in psrc)
check("pulse still emits the signal every tick", "emit_signal" in psrc)

sig = P.build_signal({"prev": [{"spirit": {"composite": 0.50}}], "composite": 0.62})
check("the signal carries only raw fields, no verdict",
      set(sig) >= {"pre_composite", "post_composite", "delta"}
      and not any(k in sig for k in ("propose", "qualified", "keys", "cycle_worthy")))
check("delta is stated, not judged", sig["delta"] == 0.12)


# ---------- 2. thresholds are READ, never computed ----------
WD_PY = REPO / "experiments" / "watchdog" / "trigger_watchdog.py"
wsrc = code_of(WD_PY)
wprose = prose_of(WD_PY)
wtree = ast.parse(WD_PY.read_text(encoding="utf-8"))

# STRUCTURAL, not textual: thresholds() may only read the file and coerce types. If it
# could call anything that looks at data, the split would be cosmetic — the process that
# computes the escalation would be tuning its own trigger point.
th_fn = next(n for n in wtree.body
             if isinstance(n, ast.FunctionDef) and n.name == "thresholds")
check("thresholds() calls nothing but the file read and type coercion",
      call_names(th_fn) <= {"_load", "float", "bool", "get"})
check("thresholds() touches no history/baseline",
      not {"history", "baseline"} & set(ast.unparse(th_fn).lower().split()))
for mod in ("statistics", "numpy", "pandas"):
    check(f"watchdog imports no analysis library ({mod})",
          not any(isinstance(n, (ast.Import, ast.ImportFrom))
                  and mod in ast.unparse(n) for n in ast.walk(wtree)))
W.CONFIG.write_text(json.dumps({"composite_move_min": 0.5,
                                "propose_on_verified_anomaly": True,
                                "min_gap_minutes": 60,
                                "signal_max_age_minutes": 30}), encoding="utf-8")
check("thresholds come from the file verbatim",
      W.thresholds()["composite_move_min"] == 0.5)
W.CONFIG.write_text(json.dumps({"composite_move_min": 0.02,
                                "propose_on_verified_anomaly": True,
                                "min_gap_minutes": 60,
                                "signal_max_age_minutes": 30}), encoding="utf-8")
check("...and change only when the file changes",
      W.thresholds()["composite_move_min"] == 0.02)


# ---------- 3. over / under threshold ----------
W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.12)
r = W.run()
check("over threshold -> exactly one proposal", r["result"].startswith("proposed:"))
doc = json.loads(W.PROPOSALS.read_text(encoding="utf-8"))
check("...written by the WATCHDOG, not the pulse",
      doc["pending"]["proposed_by"] == "trigger_watchdog")
check("...carrying the raw fields",
      doc["pending"]["evidence"]["pre_composite"] == 0.50
      and doc["pending"]["evidence"]["delta"] == 0.12)
check("...and exactly one pending entry", len(doc.get("history", [])) == 1)

W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.001)
r = W.run()
check("under threshold -> silence", r["result"] == "silent"
      and not W.PROPOSALS.exists())

W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.12, ts=(NOW - timedelta(hours=3)).isoformat())
check("a stale signal proposes nothing", W.run()["result"] == "silent")

W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.12)
W.run()
r2 = W.run()
check("a pending proposal is not duplicated within the gap",
      r2["result"] == "silent" and "already pending" in r2["verdict"]["why"])


# ---------- 4. the leaf hash is VERIFIED, not trusted ----------
S.REPO = TMP
S.PENUMBRA_DIR = TMP / "penumbra"
S.PENUMBRA_LEAVES = S.PENUMBRA_DIR / "_penumbra_leaves.jsonl"
S.PENUMBRA_ROOT = S.PENUMBRA_DIR / "_penumbra_root.json"
S.COLD_DIR = S.PENUMBRA_DIR / "cold"
S.SENS_DIR = TMP / "sensorium"
S.LEAVES = S.SENS_DIR / "_merkle_leaves.jsonl"
S.ROOT_FILE = S.SENS_DIR / "_merkle_root.json"
S.SENS_DIR.mkdir(parents=True, exist_ok=True)
drop_id = S.drop("AX", "semantic", {"url": "https://example.org/a", "note": "real"},
                 collector="goal_impact_collector",
                 quarantine={"reason": "model_anomaly"})
real_leaf = [lf for lf in S._read_leaves(S.PENUMBRA_LEAVES) if lf["id"] == drop_id][0]["leaf"]

check("a real leaf hash verifies against the chain", S.leaf_hash_matches(real_leaf, drop_id))
check("a valid-LOOKING but wrong hash does not", not S.leaf_hash_matches("a" * 64, drop_id))

W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.001, anomaly_leaf_hash=real_leaf, anomaly_drop_id=drop_id,
             source_url="https://example.org/a", rule_violated="(fired R5)")
r = W.run()
check("a VERIFIED anomaly proposes even with a tiny composite move",
      r["result"].startswith("proposed:"))
check("...and names the verification in the reason",
      "verified against the penumbra chain" in
      json.loads(W.PROPOSALS.read_text(encoding="utf-8"))["pending"]["reason"])

W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.001, anomaly_leaf_hash="b" * 64, anomaly_drop_id=drop_id,
             source_url="https://example.org/a", rule_violated="(fired R5)")
r = W.run()
check("a WRONG leaf hash is refused, not forwarded",
      r["result"] == "silent" and not W.PROPOSALS.exists())
check("...with the reason named", "does NOT match the penumbra chain" in r["verdict"]["why"])


# ---------- 5. the three capability walls ----------
imports = {ast.unparse(n) for n in ast.walk(wtree)
           if isinstance(n, (ast.Import, ast.ImportFrom))}
check("WALL (a): watchdog imports no cycle executor",
      not any(("fast_cycle_runner" in i or "supervisor" in i) for i in imports)
      and "spawn_cycle" not in wsrc)
check("WALL (b): watchdog never imports the signer, never reads the key",
      not any("request_signing" in i for i in imports)
      and "KEY_PATH" not in wsrc and "signing.key" not in wsrc)
check("WALL (c): watchdog never writes the consumable request",
      not re.search(r"FORBIDDEN_OUTPUT\s*\.\s*(write|open|touch|unlink)", wsrc)
      and "EXTRAORDINARY_PATH" not in wsrc)
check("the walls are LABELLED as speed bumps, not boundaries",
      "not a capability boundary" in wprose.lower())
check("...and the co-residence vulnerability is named", "co-residence" in wprose.lower())
check("and the real boundary is named as a backlog item", "BACKLOG #58" in wprose)

W.FORBIDDEN_OUTPUT.unlink(missing_ok=True)
W.PROPOSALS.unlink(missing_ok=True)
write_signal(delta=0.12)
W.run()
check("a full watchdog pass never creates the supervisor's file",
      not W.FORBIDDEN_OUTPUT.exists())


# ---------- 6. the whole chain, end to end ----------
W.PROPOSALS.unlink(missing_ok=True)
W.FORBIDDEN_OUTPUT.unlink(missing_ok=True)
write_signal(delta=0.12)
check("chain 1/5 — watchdog proposes", W.run()["result"].startswith("proposed:"))
items = [i for i in N._cycle_request_items() if i.get("approve_id")]
check("chain 2/5 — it surfaces to the human with raw fields",
      len(items) == 1 and "pre_composite=0.5" in items[0]["why"])
res = A._apply_cycle_request(items[0]["approve"], "12345")
check("chain 3/5 — Emil's OK signs it", res["ok"] and W.FORBIDDEN_OUTPUT.exists())
body = json.loads(W.FORBIDDEN_OUTPUT.read_text(encoding="utf-8"))
check("chain 4/5 — the signed payload carries the same raw evidence",
      body["evidence"]["delta"] == 0.12
      and body["evidence_sha256"] == RS.evidence_digest(body["evidence"]))
check("chain 5/5 — the supervisor verifies and honours it",
      SV.read_extraordinary(NOW) is not None)
check("...and consuming it leaves nothing behind",
      SV.consume_extraordinary() and not W.FORBIDDEN_OUTPUT.exists())

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
