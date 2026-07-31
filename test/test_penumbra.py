#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_penumbra.py — the penumbra: typed quarantine as a SEPARATE Merkle chain (#55).

The shape being defended: material that is real but not yet trustworthy is committed and
tamper-evident, and is INVISIBLE to every scoring path. No discount factors, no soft
quarantine, no weighted-down shadow data leaking into a number. A drop is either verified
sense or it is shadow, and the only exit is promote(), by explicit human action.

Reasons are TYPED on purpose — "uncertain" is not a reason, because an untyped doubt is
one nobody can act on or measure. model_anomaly alone never expires: an open wound in the
causal structure does not heal by waiting.

Everything runs in a temp sandbox; the real memory/sensorium and memory/penumbra are
never touched.

  venv\\Scripts\\python.exe test\\test_penumbra.py
"""
import json, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "experiments" / "sensorium"))
import sensorium as S

FAILS = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: FAILS.append(name)

TMP = Path(tempfile.mkdtemp()) / "repo"
(TMP / "memory").mkdir(parents=True)
S.REPO            = TMP
S.SENS_DIR        = TMP / "memory" / "sensorium"
S.LEAVES          = S.SENS_DIR / "_merkle_leaves.jsonl"
S.ROOT_FILE       = S.SENS_DIR / "_merkle_root.json"
S.CONSUMED        = S.SENS_DIR / "_consumed.json"
S.COMPOSER_IN     = TMP / "memory" / "browse_sources"
S.SEMANTIC_IN     = TMP / "memory" / "semantic_inbox"
S.GOALIMP_IN      = TMP / "memory" / "goal_impact_inbox"
S.PENUMBRA_DIR    = TMP / "memory" / "penumbra"
S.PENUMBRA_LEAVES = S.PENUMBRA_DIR / "_penumbra_leaves.jsonl"
S.PENUMBRA_ROOT   = S.PENUMBRA_DIR / "_penumbra_root.json"
S.COLD_DIR        = S.PENUMBRA_DIR / "cold"
S.SENS_DIR.mkdir(parents=True, exist_ok=True)

PAY = {"metric": "x", "value": 1}
TOMORROW = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

# ---------- typed reason validation ----------
def raises(fn):
    try:
        fn(); return False
    except ValueError:
        return True
    except Exception:
        return False

check("unknown reason rejected",
      raises(lambda: S.drop("AX", "numeric", PAY, quarantine={"reason": "uncertain"})))
check("missing reason rejected",
      raises(lambda: S.drop("AX", "numeric", PAY, quarantine={"expires": TOMORROW})))
check("non-dict quarantine rejected",
      raises(lambda: S.drop("AX", "numeric", PAY, quarantine="low_confidence")))
check("expires required for a non-anomaly reason",
      raises(lambda: S.drop("AX", "numeric", PAY,
                            quarantine={"reason": "low_confidence", "expires": None})))
check("malformed expires rejected",
      raises(lambda: S.drop("AX", "numeric", PAY,
                            quarantine={"reason": "low_confidence", "expires": "soonish"})))
for r in S._QUARANTINE_REASONS:
    q = {"reason": r} if r == "model_anomaly" else {"reason": r, "expires": "auto"}
    ok = True
    try:
        S.drop("AX_TYPES", "numeric", PAY, quarantine=q)
    except Exception:
        ok = False
    check(f"typed reason accepted: {r}", ok)

auto = [lf for lf in S._read_leaves(S.PENUMBRA_LEAVES)
        if (lf.get("quarantine") or {}).get("reason") == "low_confidence"][-1]
check("'auto' expiry resolves to ~+90 days",
      auto["quarantine"]["expires"] > (datetime.now(timezone.utc)
                                       + timedelta(days=85)).date().isoformat())
anom = [lf for lf in S._read_leaves(S.PENUMBRA_LEAVES)
        if (lf.get("quarantine") or {}).get("reason") == "model_anomaly"][-1]
check("model_anomaly never expires", anom["quarantine"]["expires"] is None)

# ---------- the two chains are separate ----------
main_before = len(S._read_leaves(S.LEAVES))
pen_before = len(S._read_leaves(S.PENUMBRA_LEAVES))
good_id = S.drop("AX", "numeric", PAY, collector="c")
q_id = S.drop("AX", "numeric", {"metric": "shadow", "value": 9}, collector="c",
              quarantine={"reason": "source_singleton", "expires": TOMORROW})
check("verified drop went to the MAIN chain only",
      len(S._read_leaves(S.LEAVES)) == main_before + 1)
check("quarantined drop did NOT touch the main chain",
      len(S._read_leaves(S.LEAVES)) == main_before + 1)
check("quarantined drop landed in the PENUMBRA chain",
      len(S._read_leaves(S.PENUMBRA_LEAVES)) == pen_before + 1)
check("penumbra drop file lives under the penumbra dir",
      (TMP / [lf for lf in S._read_leaves(S.PENUMBRA_LEAVES) if lf["id"] == q_id][0]["path"])
      .is_relative_to(S.PENUMBRA_DIR))
check("the two roots differ (separate trees)",
      S._load(S.ROOT_FILE, {}).get("root") != S._load(S.PENUMBRA_ROOT, {}).get("root"))

# ---------- the wall: ingest ignores penumbra ----------
ing = S.ingest()
routed = json.dumps(ing)
check("ingest routed the verified drop", ing["ingested"] >= 1)
check("ingest never mentions the quarantined drop", q_id not in routed)
check("no shadow payload reached the composer inbox",
      "shadow" not in (S.COMPOSER_IN / "AX.json").read_text(encoding="utf-8"))

# ---------- verify() reports both, independently ----------
v = S.verify()
check("verify() reports both chains", set(v) == {"verified", "penumbra"})
check("both chains healthy", v["verified"]["ok"] and v["penumbra"]["ok"])

pen_leaf = [lf for lf in S._read_leaves(S.PENUMBRA_LEAVES) if lf["id"] == q_id][0]
(TMP / pen_leaf["path"]).write_text('{"tampered":true}', encoding="utf-8")
v = S.verify()
check("tampering the SHADOW screams on the penumbra chain only",
      v["penumbra"]["ok"] is False and v["verified"]["ok"] is True)
check("...and names the item", any(m["id"] == q_id for m in v["penumbra"]["mismatches"]))

main_leaf = [lf for lf in S._read_leaves(S.LEAVES) if lf["id"] == good_id][0]
orig = (TMP / main_leaf["path"]).read_text(encoding="utf-8")
(TMP / main_leaf["path"]).write_text('{"tampered":true}', encoding="utf-8")
check("tampering the VERIFIED chain screams there too", S.verify()["verified"]["ok"] is False)
(TMP / main_leaf["path"]).write_text(orig, encoding="utf-8")
(TMP / pen_leaf["path"]).write_text(
    S._canon({"axis": "AX", "collector": "c", "kind": "numeric",
              "payload": {"metric": "shadow", "value": 9},
              "quarantine": pen_leaf["quarantine"], "ts": pen_leaf["ts"]}), encoding="utf-8")
check("both healthy again after restore", S.verify()["verified"]["ok"] and S.verify()["penumbra"]["ok"])

# ---------- promote ----------
main_n = len(S._read_leaves(S.LEAVES))
pen_n = len(S._read_leaves(S.PENUMBRA_LEAVES))
new_id = S.promote(q_id, by="emil")
check("promote created a NEW main leaf", len(S._read_leaves(S.LEAVES)) == main_n + 1)
check("promote LEFT the penumbra leaf in place (append-only history)",
      len(S._read_leaves(S.PENUMBRA_LEAVES)) == pen_n)
promoted = json.loads((TMP / [lf for lf in S._read_leaves(S.LEAVES)
                              if lf["id"] == new_id][0]["path"]).read_text(encoding="utf-8"))
check("promoted payload records provenance",
      promoted["payload"]["promoted_from"] == q_id
      and promoted["payload"]["promoted_by"] == "emil"
      and promoted["payload"].get("promoted_at"))
check("promoting an unknown id raises", raises(lambda: S.promote("NOPE/xxx")))
check("chains still verify after promote",
      S.verify()["verified"]["ok"] and S.verify()["penumbra"]["ok"])

# ---------- expire ----------
old_id = S.drop("AX_EXP", "numeric", {"m": "old"}, quarantine={"reason": "temporal_mismatch",
                                                              "expires": YESTERDAY})
anom_id = S.drop("AX_EXP", "numeric", {"m": "anomaly"}, quarantine={"reason": "model_anomaly"})
fresh_id = S.drop("AX_EXP", "numeric", {"m": "fresh"}, quarantine={"reason": "low_confidence",
                                                                  "expires": TOMORROW})
res = S.expire()
check("expired item moved to cold", old_id in res["moved"])
check("model_anomaly never moved", anom_id not in res["moved"])
check("unexpired item untouched", fresh_id not in res["moved"])
check("cold file exists", any(S.COLD_DIR.rglob("*.json")))
check("nothing deleted — the original leaf is still in the chain",
      any(lf["id"] == old_id for lf in S._read_leaves(S.PENUMBRA_LEAVES)))
check("penumbra STILL verifies after the move (cold marker keeps it whole)",
      S.verify()["penumbra"]["ok"] is True)

# ---------- report ----------
rep = S.penumbra_report()
check("report counts only ACTIVE items (cold excluded)",
      rep["n_active"] == len(S._penumbra_active()) and old_id not in
      [lf["id"] for lf in S._penumbra_active()])
check("report types the reasons", "model_anomaly" in rep["by_reason"])
check("report exposes per-axis growth",
      isinstance(rep["growth"], list) and all("axis" in g and "n_active" in g
                                              for g in rep["growth"]))

shutil.rmtree(TMP.parent, ignore_errors=True)
print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
