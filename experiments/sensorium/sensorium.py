#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/sensorium/sensorium.py — the decoupled, Merkle-committed sensory backbone.

Separates SENSING from THINKING (Emil, 30 Jul 2026). Independent per-axis collectors
(the Playwright browser agents, built on top of this) gather calmly and call drop();
the fast_cycle only calls ingest() — light, no browser, no search. Every drop is an
IMMUTABLE leaf in a tamper-evident sensory Merkle tree, so the brain can trust and
audit its own senses: you can't fake what you sensed. (See
claude/SENSORY_COLLECTORS_ARCHITECTURE_30JUL.md.)

  drop(axis, kind, payload, collector)  # a collector deposits verified numeric/semantic JSON
  ingest()                              # the cycle consumes ready drops -> composer / brain
  verify()                              # recompute the Merkle root from the drop files

  python experiments/sensorium/sensorium.py --verify
  python experiments/sensorium/sensorium.py --ingest
  python experiments/sensorium/sensorium.py --demo   # deposit two drops (labelled demo)
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SENS_DIR   = REPO / "memory" / "sensorium"
LEAVES     = SENS_DIR / "_merkle_leaves.jsonl"
ROOT_FILE  = SENS_DIR / "_merkle_root.json"
CONSUMED   = SENS_DIR / "_consumed.json"
COMPOSER_IN = REPO / "memory" / "browse_sources"       # numeric -> composer "file" kind
SEMANTIC_IN = REPO / "memory" / "semantic_inbox"        # semantic -> the brain layer
GOALIMP_IN  = REPO / "memory" / "goal_impact_inbox"     # goal_impact -> brain (full vector)

# The kinds a collector may deposit. "goal_impact" is Emil's unified measure (30 Jul 2026):
# ONE signed, weighted composite relative to the goal/vision that carries BOTH the moving
# scalar (for statistics/scoring) AND the rationale/dimensions/counterviews (for the brain).
_KINDS = ("numeric", "semantic", "goal_impact")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _merkle_root(hashes: list) -> str:
    """Standard binary Merkle root over leaf hashes (duplicate-last for odd counts)."""
    if not hashes:
        return "0" * 64
    layer = list(hashes)
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [_sha(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0]


def _load(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _recommit_root():
    leaves = [json.loads(l) for l in LEAVES.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if LEAVES.exists() else []
    root = _merkle_root([lf["leaf"] for lf in leaves])
    ROOT_FILE.write_text(json.dumps({"root": root, "n_leaves": len(leaves), "ts": _now()},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return root, len(leaves)


def drop(axis: str, kind: str, payload: dict, collector: str = "collector") -> str:
    """A collector deposits a verified sensory record. Immutable; becomes a Merkle leaf."""
    assert kind in _KINDS, f"kind must be one of {_KINDS}"
    ts = _now()
    rec = {"axis": axis, "kind": kind, "ts": ts, "collector": collector, "payload": payload}
    canon = _canon(rec)
    leaf = _sha(canon)
    drop_id = f"{axis}/{ts.replace(':', '').replace('.', '')}_{leaf[:8]}"
    path = SENS_DIR / axis / f"{ts.replace(':', '').replace('.', '')}_{leaf[:8]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canon, encoding="utf-8")   # store the EXACT canonical bytes we hashed
    SENS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEAVES, "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": drop_id, "leaf": leaf, "path": str(path.relative_to(REPO)),
                            "axis": axis, "kind": kind, "ts": ts}, ensure_ascii=False) + "\n")
    _recommit_root()
    return drop_id


def verify() -> dict:
    """Recompute each leaf from its drop file and the root from the leaves — detects any
    tampering of a drop or the leaf list."""
    if not LEAVES.exists():
        return {"ok": True, "n": 0, "root": "0" * 64, "mismatches": []}
    leaves = [json.loads(l) for l in LEAVES.read_text(encoding="utf-8").splitlines() if l.strip()]
    mism = []
    for lf in leaves:
        p = REPO / lf["path"]
        recomputed = _sha(p.read_text(encoding="utf-8")) if p.exists() else "MISSING"
        if recomputed != lf["leaf"]:
            mism.append({"id": lf["id"], "reason": "missing" if recomputed == "MISSING" else "content changed"})
    root = _merkle_root([lf["leaf"] for lf in leaves])
    committed = _load(ROOT_FILE, {}).get("root")
    ok = (not mism) and (root == committed)
    return {"ok": ok, "n": len(leaves), "root": root, "committed_root": committed,
            "mismatches": mism}


def ingest() -> dict:
    """The cycle's light step: route each axis's newest unconsumed drop to where it's used —
    numeric -> composer (browse_sources/<axis>.json), semantic -> semantic_inbox. Mark
    consumed WITHOUT touching the immutable drop (consumption is tracked separately, so the
    Merkle stays intact)."""
    if not LEAVES.exists():
        return {"ingested": 0, "axes": {}}
    leaves = [json.loads(l) for l in LEAVES.read_text(encoding="utf-8").splitlines() if l.strip()]
    consumed = set(_load(CONSUMED, {"ids": []}).get("ids", []))
    fresh = [lf for lf in leaves if lf["id"] not in consumed]
    # newest drop per (axis, kind)
    latest = {}
    for lf in fresh:
        latest[(lf["axis"], lf["kind"])] = lf  # leaves are append-order = chronological
    out = {"ingested": 0, "axes": {}}
    for (axis, kind), lf in latest.items():
        rec = _load(REPO / lf["path"], {})
        payload = rec.get("payload", {})
        if kind == "goal_impact":
            # Emil's unified measure reaches BOTH consumers from one committed drop:
            #  (a) full vector -> goal_impact_inbox/<axis>.json  (the brain reads dimensions,
            #      disagreements, rationale, counterviews — the meaning),
            #  (b) the moving scalar -> browse_sources/<axis>.json shaped so the composer's
            #      existing "file" kind reads overall_signed_weighted (the number for scoring).
            GOALIMP_IN.mkdir(parents=True, exist_ok=True)
            (GOALIMP_IN / f"{axis}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            COMPOSER_IN.mkdir(parents=True, exist_ok=True)
            scalar = {
                "metric": "goal_impact_signed_weighted",
                "value": payload.get("overall_signed_weighted", 0.0),
                "orientation": "higher = better",   # positive = toward the goal, by design
                "data_date": payload.get("data_date", rec.get("ts", "")[:10]),
                "n_components": payload.get("n", 0),
                "source": "sensorium goal_impact drop",
                "axis": axis,
            }
            (COMPOSER_IN / f"{axis}.json").write_text(
                json.dumps(scalar, ensure_ascii=False, indent=2), encoding="utf-8")
            a = out["axes"].setdefault(axis, {})
            a["goal_impact"] = str((GOALIMP_IN / f"{axis}.json").relative_to(REPO))
            a["numeric"] = str((COMPOSER_IN / f"{axis}.json").relative_to(REPO))
            out["ingested"] += 1
            continue
        dest_dir = COMPOSER_IN if kind == "numeric" else SEMANTIC_IN
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{axis}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        out["axes"].setdefault(axis, {})[kind] = str((dest_dir / f"{axis}.json").relative_to(REPO))
        out["ingested"] += 1
    # mark ALL fresh drops consumed (we routed the newest; older ones are superseded)
    consumed |= {lf["id"] for lf in fresh}
    CONSUMED.write_text(json.dumps({"ids": sorted(consumed), "ts": _now()}, ensure_ascii=False),
                        encoding="utf-8")
    return out


if __name__ == "__main__":
    if "--verify" in sys.argv:
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
    elif "--ingest" in sys.argv:
        print(json.dumps(ingest(), ensure_ascii=False, indent=2))
    elif "--demo" in sys.argv:
        a = drop("SOCIAL_RELATIONS_REVIEW", "numeric",
                 {"metric": "ongoing_armed_conflicts", "value": 48, "data_date": _now()[:10],
                  "note": "DEMO drop"}, collector="demo")
        b = drop("GOVERNANCE_INSTITUTIONS_REVIEW", "semantic",
                 {"concept": "authoritarian drift", "direction": "deteriorating",
                  "strongest_counterview": "courts still function; normal politics",
                  "note": "DEMO drop"}, collector="demo")
        print(f"dropped: {a}\ndropped: {b}")
        print(json.dumps(verify(), ensure_ascii=False, indent=2))
    else:
        print(__doc__)
