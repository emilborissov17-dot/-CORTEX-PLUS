#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/grounding/divergence_ledger.py — E2: where the sources disagree.

Grounding means the system can be RIGHT or WRONG about the world, and knows which.
Each cycle the composers produce, per axis: an anchor (slow authoritative value), a
daily proxy, their divergence, and whether independent proxies confirm or contradict
the anchor's direction. This ledger records that, tamper-evidently (hash chain), and
raises a GROUNDING ALERT when the daily proxy materially contradicts the anchor, or
when proxies disagree with the anchor's direction. That alert is the concrete
"the data is telling us something the headline number isn't" signal — the seed of
E2 (learn per-axis how much to trust each source).

Safe by construction: it only READS composed_indicators.json and APPENDS to its own
ledger. It never touches scoring. Until a live daily source is promoted, divergence
is None and the ledger simply records the baseline (no alerts) — it activates itself
the moment daily data starts flowing.

PRE-DECLARED: this is a recorder, not a claim. Its value is realised when daily
sources exist and it surfaces real contradictions for the human. Now it establishes
the tamper-evident baseline.

  python experiments/grounding/divergence_ledger.py --record   # append this cycle
  python experiments/grounding/divergence_ledger.py --report   # recent state + alerts
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMPOSED = REPO / "memory" / "composed_indicators.json"
LEDGER   = REPO / "memory" / "grounding_ledger.jsonl"

DIVERGENCE_ALERT = 0.5   # provisional; recalibrated once real daily values exist


def _load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _last_hash():
    if not LEDGER.exists():
        return "0" * 64
    last = None
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    if not last:
        return "0" * 64
    try:
        return json.loads(last).get("hash", "0" * 64)
    except Exception:
        return "0" * 64


def _snapshot():
    """Build this cycle's per-axis grounding row + alerts from composed_indicators."""
    comp = _load(COMPOSED, {})
    axes, alerts = {}, []
    for axis, r in comp.items():
        if not isinstance(r, dict):
            continue
        c = r.get("composed", {}) or {}
        anchor = (c.get("anchor") or {}).get("value")
        daily = c.get("daily")
        div = c.get("divergence")
        agree = r.get("agreement", {}) or {}
        # proxies that contradict the anchor's direction
        contra = [pid for pid, pv in (agree.get("proxies") or {}).items()
                  if isinstance(pv, dict) and pv.get("direction") == "contradict"]
        axes[axis] = {"anchor": anchor, "daily": daily, "divergence": div,
                      "confidence": r.get("confidence"),
                      "anchor_direction": agree.get("anchor_direction"),
                      "contradicting_proxies": contra}
        if isinstance(div, (int, float)) and abs(div) >= DIVERGENCE_ALERT:
            alerts.append({"axis": axis, "kind": "anchor_vs_daily",
                           "divergence": div, "anchor": anchor, "daily": daily})
        if contra:
            alerts.append({"axis": axis, "kind": "proxy_contradiction",
                           "proxies": contra})
    return axes, alerts


def record():
    axes, alerts = _snapshot()
    prev = _last_hash()
    body = {"ts": _now(), "axes": axes, "alerts": alerts, "prev_hash": prev}
    h = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                       .encode("utf-8")).hexdigest()
    rec = {**body, "hash": h}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    live = sum(1 for a in axes.values() if a["daily"] is not None)
    print(f"[grounding] recorded {len(axes)} axes ({live} with live daily), "
          f"{len(alerts)} alert(s) -> memory/grounding_ledger.jsonl")
    for al in alerts:
        print(f"  ALERT {al['axis']}: {al['kind']} {al.get('divergence', al.get('proxies'))}")
    return rec


def report():
    if not LEDGER.exists():
        print("no grounding ledger yet — run --record (from a cycle)")
        return
    lines = [l for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"grounding ledger: {len(lines)} records")
    for line in lines[-3:]:
        r = json.loads(line)
        live = sum(1 for a in r["axes"].values() if a.get("daily") is not None)
        print(f"  {r['ts'][:19]}Z  axes={len(r['axes'])} live_daily={live} "
              f"alerts={len(r['alerts'])}")
        for al in r["alerts"]:
            print(f"     ! {al['axis']}: {al['kind']}")
    # tamper check
    ok, prev = True, "0" * 64
    for line in lines:
        r = json.loads(line)
        if r.get("prev_hash") != prev:
            ok = False
            break
        prev = r.get("hash")
    print(f"hash chain intact: {ok}")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        record()
