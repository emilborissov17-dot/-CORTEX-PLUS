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
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SENS_DIR   = REPO / "memory" / "sensorium"
LEAVES     = SENS_DIR / "_merkle_leaves.jsonl"
ROOT_FILE  = SENS_DIR / "_merkle_root.json"
CONSUMED   = SENS_DIR / "_consumed.json"

# ── PENUMBRA (#55): a SECOND, independent Merkle chain — the "Merkle forest".
# Material that is real but not yet trustworthy lives here: committed, tamper-evident,
# and INVISIBLE to every scoring path. There is no soft quarantine and no discount
# factor; a drop is either in the verified chain or it is in the shadow. The only exit
# is promote(), by explicit human action.
PENUMBRA_DIR    = REPO / "memory" / "penumbra"
PENUMBRA_LEAVES = PENUMBRA_DIR / "_penumbra_leaves.jsonl"
PENUMBRA_ROOT   = PENUMBRA_DIR / "_penumbra_root.json"
COLD_DIR        = PENUMBRA_DIR / "cold"        # expired items move here, still committed

# Typed reasons. "uncertain" is deliberately NOT one of them: an untyped doubt is a
# doubt nobody can act on or measure. model_anomaly is the only reason that never
# expires — an open wound in the causal structure does not heal by waiting.
_QUARANTINE_REASONS = ("source_singleton", "temporal_mismatch", "low_confidence",
                       "model_anomaly", "unverified_xref")
_NEVER_EXPIRES = ("model_anomaly",)
_DEFAULT_EXPIRY_DAYS = 90
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


def _read_leaves(path):
    if not Path(path).exists():
        return []
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _recommit(leaves_file, root_file):
    leaves = _read_leaves(leaves_file)
    root = _merkle_root([lf["leaf"] for lf in leaves])
    Path(root_file).parent.mkdir(parents=True, exist_ok=True)
    Path(root_file).write_text(json.dumps({"root": root, "n_leaves": len(leaves), "ts": _now()},
                                          ensure_ascii=False, indent=2), encoding="utf-8")
    return root, len(leaves)


def _recommit_root():
    return _recommit(LEAVES, ROOT_FILE)


def _recommit_penumbra():
    return _recommit(PENUMBRA_LEAVES, PENUMBRA_ROOT)


def _validate_quarantine(q: dict) -> dict:
    """Typed or nothing. A quarantine without a reason the system can name is exactly the
    'uncertain' bucket this design exists to forbid."""
    if not isinstance(q, dict):
        raise ValueError("quarantine must be a dict")
    reason = q.get("reason")
    if reason not in _QUARANTINE_REASONS:
        raise ValueError(f"quarantine reason must be one of {_QUARANTINE_REASONS}, got {reason!r}")
    expires = q.get("expires", "auto")
    if reason in _NEVER_EXPIRES:
        expires = None                      # an open wound does not expire
    else:
        if expires == "auto":
            expires = (datetime.now(timezone.utc)
                       + timedelta(days=_DEFAULT_EXPIRY_DAYS)).date().isoformat()
        if not expires:
            raise ValueError(f"quarantine reason {reason!r} requires an 'expires' date "
                             f"(or \"auto\" for +{_DEFAULT_EXPIRY_DAYS}d)")
        try:
            datetime.fromisoformat(str(expires)[:10])
        except Exception:
            raise ValueError(f"quarantine 'expires' must be an ISO date, got {expires!r}")
    return {"reason": reason, "expires": expires}


def drop(axis: str, kind: str, payload: dict, collector: str = "collector",
         quarantine: dict = None) -> str:
    """A collector deposits a verified sensory record. Immutable; becomes a Merkle leaf.

    quarantine={"reason": <typed>, "expires": ISO|"auto"|None} routes the drop to the
    PENUMBRA chain instead. A quarantined drop NEVER touches the main leaves or root:
    the two chains are separate trees, so tampering in each screams separately, and
    nothing downstream can accidentally read shadow material as verified sense."""
    assert kind in _KINDS, f"kind must be one of {_KINDS}"
    q = _validate_quarantine(quarantine) if quarantine is not None else None
    ts = _now()
    rec = {"axis": axis, "kind": kind, "ts": ts, "collector": collector, "payload": payload}
    if q:
        rec["quarantine"] = q
    canon = _canon(rec)
    leaf = _sha(canon)
    stem = f"{ts.replace(':', '').replace('.', '')}_{leaf[:8]}"
    drop_id = f"{axis}/{stem}"
    base = PENUMBRA_DIR if q else SENS_DIR
    path = base / axis / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canon, encoding="utf-8")   # store the EXACT canonical bytes we hashed
    # collector is carried on the LEAF ENTRY (not just inside the hashed record) so
    # provenance is readable without opening every drop file. It is not part of the
    # leaf hash, so this changes no existing commitment.
    entry = {"id": drop_id, "leaf": leaf, "path": str(path.relative_to(REPO)),
             "axis": axis, "kind": kind, "ts": ts, "collector": collector}
    if q:
        entry["quarantine"] = q
        PENUMBRA_DIR.mkdir(parents=True, exist_ok=True)
        with open(PENUMBRA_LEAVES, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _recommit_penumbra()
    else:
        SENS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LEAVES, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _recommit_root()
    return drop_id


def _verify_chain(leaves_file, root_file, cold_map=None) -> dict:
    """Recompute each leaf from its drop file and the root from the leaves — detects any
    tampering of a drop or the leaf list. cold_map lets an EXPIRED penumbra item verify
    from its cold location, so archiving never looks like tampering."""
    leaves = _read_leaves(leaves_file)
    if not leaves:
        return {"ok": True, "n": 0, "root": "0" * 64,
                "committed_root": _load(root_file, {}).get("root"), "mismatches": []}
    mism = []
    for lf in leaves:
        p = REPO / lf["path"]
        if not p.exists() and cold_map and lf["id"] in cold_map:
            p = REPO / cold_map[lf["id"]]      # moved to cold, not lost
        recomputed = _sha(p.read_text(encoding="utf-8")) if p.exists() else "MISSING"
        if recomputed != lf["leaf"]:
            mism.append({"id": lf["id"],
                         "reason": "missing" if recomputed == "MISSING" else "content changed"})
    root = _merkle_root([lf["leaf"] for lf in leaves])
    committed = _load(root_file, {}).get("root")
    ok = (not mism) and (root == committed)
    return {"ok": ok, "n": len(leaves), "root": root, "committed_root": committed,
            "mismatches": mism}


def _cold_map() -> dict:
    """id -> WHERE THE DROP MOVED TO. Note this is cold_to, not the marker leaf's own
    path: the marker is itself a leaf with its own file, and confusing the two makes an
    archived item verify against the wrong bytes and look like tampering."""
    return {lf["cold_of"]: lf["cold_to"] for lf in _read_leaves(PENUMBRA_LEAVES)
            if lf.get("kind") == "cold_marker" and lf.get("cold_of") and lf.get("cold_to")}


def verify() -> dict:
    """Both chains, verified INDEPENDENTLY. Tampering in each screams separately: a
    corrupted shadow must never cast doubt on verified sense, and a corrupted verified
    chain must never hide behind a healthy shadow."""
    return {"verified": _verify_chain(LEAVES, ROOT_FILE),
            "penumbra": _verify_chain(PENUMBRA_LEAVES, PENUMBRA_ROOT, _cold_map())}


def _penumbra_active() -> list:
    """Quarantined leaves that are still in the shadow: not cold markers, not yet moved."""
    cold = set(_cold_map())
    return [lf for lf in _read_leaves(PENUMBRA_LEAVES)
            if lf.get("kind") != "cold_marker" and lf["id"] not in cold]


def penumbra_report() -> dict:
    """What is accumulating in the shadow, and WHERE.

    growth is the metric that matters: an axis piling up unverifiable material is telling
    you its model or its coverage is weak there. That is hunger, and it belongs in the
    needs report — not a number to be averaged into a score."""
    active = _penumbra_active()
    by_reason, by_axis = {}, {}
    for lf in active:
        r = (lf.get("quarantine") or {}).get("reason", "?")
        by_reason[r] = by_reason.get(r, 0) + 1
        by_axis[lf["axis"]] = by_axis.get(lf["axis"], 0) + 1
    growth = sorted(({"axis": a, "n_active": n} for a, n in by_axis.items()),
                    key=lambda x: -x["n_active"])
    # WHERE an anomaly came from decides what it is allowed to cause. An anomaly the
    # system generated from its own ideas is a thought about itself; one that came from
    # a collector reading the world is evidence. Only the second may ever move anything.
    origins = {}
    for lf in active:
        if (lf.get("quarantine") or {}).get("reason") == "model_anomaly":
            o = lf.get("collector") or "unknown"
            origins[o] = origins.get(o, 0) + 1
    return {"n_active": len(active), "by_reason": by_reason, "growth": growth,
            "anomalies_by_origin": origins}


def anomaly_arrivals(since_iso: str = None, until_iso: str = None,
                     exclude_origins=()) -> int:
    """How many model_anomaly items ARRIVED in a window. A rate, not a stock: the stock
    only grows, so it can never show whether the system started generating anomalies
    faster after some change was made to it."""
    n = 0
    for lf in _read_leaves(PENUMBRA_LEAVES):
        if lf.get("kind") == "cold_marker":
            continue
        if (lf.get("quarantine") or {}).get("reason") != "model_anomaly":
            continue
        if (lf.get("collector") or "unknown") in exclude_origins:
            continue
        ts = str(lf.get("ts", ""))
        if since_iso and ts < since_iso:
            continue
        if until_iso and ts >= until_iso:
            continue
        n += 1
    return n


def newest_anomaly(exclude_origins=()) -> dict:
    """The most recent model_anomaly leaf, with its LEAF HASH and file path, so a caller
    can cite it and a verifier can recompute it from the chain instead of trusting the
    citation. Returns {} when there is none."""
    best = {}
    for lf in _read_leaves(PENUMBRA_LEAVES):
        if lf.get("kind") == "cold_marker":
            continue
        if (lf.get("quarantine") or {}).get("reason") != "model_anomaly":
            continue
        if (lf.get("collector") or "unknown") in exclude_origins:
            continue
        if not best or str(lf.get("ts", "")) > str(best.get("ts", "")):
            best = lf
    return best


def leaf_hash_matches(leaf_hash: str, drop_id: str = None) -> bool:
    """Recompute a penumbra leaf's hash FROM THE CHAIN and its file. The point is that a
    hash arriving from another process is a claim; this turns it back into evidence."""
    if not leaf_hash:
        return False
    for lf in _read_leaves(PENUMBRA_LEAVES):
        if lf.get("leaf") != leaf_hash:
            continue
        if drop_id and lf.get("id") != drop_id:
            continue
        p = REPO / lf["path"]
        if not p.exists():
            p = REPO / _cold_map().get(lf["id"], lf["path"])
        if not p.exists():
            return False
        return _sha(p.read_text(encoding="utf-8")) == leaf_hash
    return False


def promote(drop_id: str, by: str = "emil") -> str:
    """Move a penumbra item into verified sense — the ONLY exit from the shadow, and only
    by explicit human action. The penumbra leaf REMAINS: the history of having doubted it
    is itself a record, and an append-only chain cannot un-say something."""
    lf = next((x for x in _read_leaves(PENUMBRA_LEAVES)
               if x["id"] == drop_id and x.get("kind") != "cold_marker"), None)
    if lf is None:
        raise ValueError(f"no penumbra item with id {drop_id!r}")
    src = REPO / lf["path"]
    if not src.exists():
        src = REPO / _cold_map().get(drop_id, lf["path"])
    rec = _load(src, {})
    payload = dict(rec.get("payload") or {})
    payload.update({"promoted_from": drop_id, "promoted_by": by, "promoted_at": _now(),
                    "quarantine_was": rec.get("quarantine")})
    return drop(lf["axis"], lf["kind"], payload,
                collector=rec.get("collector", "promoted"))


def expire(today: str = None) -> dict:
    """Move items past their expiry to cold storage. Never deletes: a cold marker leaf is
    appended to the penumbra chain recording the new path, so the chain still verifies.
    model_anomaly is never touched — it has no expiry by design."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    moved = []
    for lf in _penumbra_active():
        q = lf.get("quarantine") or {}
        exp = q.get("expires")
        if q.get("reason") in _NEVER_EXPIRES or not exp or str(exp)[:10] > today:
            continue
        src = REPO / lf["path"]
        dest = COLD_DIR / lf["axis"] / Path(lf["path"]).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            src.replace(dest)
        marker = {"cold_of": lf["id"], "moved_at": _now(), "expired_on": exp,
                  "from": lf["path"], "to": str(dest.relative_to(REPO))}
        canon = _canon(marker)
        mleaf = _sha(canon)
        mpath = COLD_DIR / lf["axis"] / f"{Path(lf['path']).stem}_coldmarker.json"
        mpath.write_text(canon, encoding="utf-8")
        with open(PENUMBRA_LEAVES, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": f"{lf['id']}#cold", "leaf": mleaf,
                                "path": str(mpath.relative_to(REPO)), "axis": lf["axis"],
                                "kind": "cold_marker", "ts": _now(),
                                "cold_of": lf["id"],
                                "cold_to": str(dest.relative_to(REPO))},
                               ensure_ascii=False) + "\n")
        moved.append(lf["id"])
    if moved:
        _recommit_penumbra()
    return {"moved": moved, "n_moved": len(moved), "cold_dir": str(COLD_DIR.relative_to(REPO))}


def ingest() -> dict:
    """The cycle's light step: route each axis's newest unconsumed drop to where it's used —

    numeric -> composer (browse_sources/<axis>.json), semantic -> semantic_inbox. Mark
    consumed WITHOUT touching the immutable drop (consumption is tracked separately, so the
    Merkle stays intact).

    THE WALL: this reads ONLY the main chain. Penumbra is invisible to all
    scoring/hypothesis/alerting paths — no discount factors, no soft quarantine, no
    "weighted-down" shadow data leaking into a score. The exit from the penumbra is
    promote(), by explicit human action, and nothing else."""
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
    elif "--penumbra" in sys.argv:
        print(json.dumps(penumbra_report(), ensure_ascii=False, indent=2))
    elif "--promote" in sys.argv:
        i = sys.argv.index("--promote")
        if i + 1 >= len(sys.argv):
            print("usage: --promote <drop_id> [--by <name>]"); sys.exit(2)
        who = sys.argv[sys.argv.index("--by") + 1] if "--by" in sys.argv else "emil"
        print(json.dumps({"promoted_to": promote(sys.argv[i + 1], by=who)},
                         ensure_ascii=False, indent=2))
    elif "--expire" in sys.argv:
        print(json.dumps(expire(), ensure_ascii=False, indent=2))
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
