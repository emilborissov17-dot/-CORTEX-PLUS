#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/provenance_pairs.py — the same quantity, from two different provenances, recorded
side by side. NOTHING IS COMPUTED.

WHY THIS EXISTS, AND WHY IT COMPUTES NOTHING
--------------------------------------------
Stage 3 is divergence detection: noticing when a reported number and an independently
measured one disagree. Kimi gated it on having "at least 3 axes with paired series of
different provenance" first, and the reasoning is worth restating because it is the whole
point of this module: a divergence layer built before the taxonomy exists is a lie
detector that only ever listens to the accused. If every series in a pair comes from the
same aggregator of the same national reporting, disagreement between them measures
rounding, not truth.

So this records pairs and observes both sides. It computes no difference, no ratio, no
agreement score and no flag, and there is a fixture asserting that no observation record
contains one. The temptation to add "just a delta, it's free" is exactly the thing to
resist: a delta published before anyone has established that the two series measure the
same quantity for the same entity is a number that will be read as evidence and is not.

WHAT MAKES A PAIR A PAIR — three conditions, all enforced:
  SAME QUANTITY     asserted by a HUMAN, with a stated reason. Whether two series measure
                    the same thing is layer 4, the one nothing in this system can answer.
                    The system may propose a pair; `proposed` is never counted.
  SAME ENTITY       a Eurostat EU27 unemployment rate and a World Bank world rate are two
                    facts about two different populations. Pairing them would manufacture
                    a divergence out of geography.
  DIFFERENT ORIGIN  two sources resolving to one origin are not two provenances — that is
                    the same lesson as origin concentration, and a pair that fails it
                    would be the fake-diversity bug wearing a new hat.

  venv\\Scripts\\python.exe -m core.provenance_pairs --list
  venv\\Scripts\\python.exe -m core.provenance_pairs --observe
  venv\\Scripts\\python.exe -m core.provenance_pairs --readiness
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "experiments" / "composers"))

PAIRS_FILE = BASE / "memory" / "provenance_pairs.json"

# Kimi's gate on Stage 3. Not a threshold this module enforces on anything — it enforces
# nothing — but the number a human is measuring readiness against.
STAGE3_AXES_REQUIRED = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    try:
        return json.loads(PAIRS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"pairs": {}, "proposed": {}}


def _save(doc: dict) -> None:
    PAIRS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAIRS_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


class NotAPair(ValueError):
    """The two sides do not satisfy what a pair means."""


def _prov():
    import provenance as P
    return P


def check_pair(primary: dict, aggregate: dict, entity: str) -> None:
    """The three conditions. Raises NotAPair with the reason, never a silent False."""
    P = _prov()
    for side, name in ((primary, "primary"), (aggregate, "aggregate")):
        if not side.get("source"):
            raise NotAPair(f"{name} side carries no source record")
        if str(side.get("entity") or "") != str(entity):
            raise NotAPair(
                f"{name} side is about {side.get('entity')!r}, the pair is about "
                f"{entity!r}. Two facts about two different populations are not a pair, "
                f"and pairing them would manufacture a divergence out of geography")
    o1, o2 = P.origin(primary["source"]), P.origin(aggregate["source"])
    if o1 == o2:
        raise NotAPair(
            f"both sides resolve to the same origin ({o1}). That is one provenance wearing "
            f"two labels — the same fake diversity the origin work exists to expose")


def propose(pair_id: str, axis: str, indicator: str, entity: str,
            primary: dict, aggregate: dict, why: str = "") -> dict:
    """The system's guess that two series measure the same quantity. INADMISSIBLE until a
    human confirms it: readiness() and list_pairs() never read this object."""
    doc = _load()
    doc.setdefault("proposed", {})[pair_id] = {
        "axis": axis, "indicator": indicator, "entity": entity,
        "primary": primary, "aggregate": aggregate, "why_same_quantity": why,
        "proposed_at": _now(),
        "status": "PROPOSED — not counted anywhere until a human confirms that these two "
                  "series measure the same quantity. That judgement is layer 4 and the "
                  "system cannot make it.",
    }
    _save(doc)
    return doc["proposed"][pair_id]


def record_pair(pair_id: str, axis: str, indicator: str, entity: str,
                primary: dict, aggregate: dict, confirmed_by: str,
                why: str = "") -> dict:
    """A human asserts these two series measure the same quantity for the same entity."""
    if not confirmed_by:
        raise NotAPair("a pair needs a human confirming that the two series measure the "
                       "same quantity — the system's own opinion is not evidence")
    check_pair(primary, aggregate, entity)
    P = _prov()
    doc = _load()
    for side in (primary, aggregate):
        side["origin"] = P.origin(side["source"])
        side["reporter_class"] = P.reporter_class(side["source"])[0]
    existing = (doc.get("pairs") or {}).get(pair_id) or {}
    doc.setdefault("pairs", {})[pair_id] = {
        "axis": axis, "indicator": indicator, "entity": entity,
        "primary": primary, "aggregate": aggregate,
        "why_same_quantity": why,
        "confirmed_by": confirmed_by, "confirmed_at": existing.get("confirmed_at") or _now(),
        "observations": existing.get("observations") or [],
        "computes_nothing": "both sides are recorded as read. No difference, ratio, "
                            "agreement score or flag is derived here, by design.",
    }
    doc.get("proposed", {}).pop(pair_id, None)
    _save(doc)
    return doc["pairs"][pair_id]


def _read(side: dict) -> dict:
    """One side, as read. An error is recorded as an error — a side that will not yield is
    a fact about the pair and must not be smoothed into a gap."""
    import composer as C
    try:
        v, dd = C.fetch(side["source"])
        return {"value": v, "data_date": dd}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def observe(pair_id: str = None) -> list:
    """Read both sides of every confirmed pair and append what each said. That is all.

    Deliberately no comparison: see the module docstring. What is stored is two readings
    and their dates, so that when Stage 3 is built it has a history to work on instead of
    starting cold — and so that whoever builds it can see for themselves whether the two
    sides were ever comparable."""
    doc = _load()
    out = []
    for pid, p in (doc.get("pairs") or {}).items():
        if pair_id and pid != pair_id:
            continue
        rec = {"ts": _now(), "primary": _read(p["primary"]),
               "aggregate": _read(p["aggregate"])}
        p.setdefault("observations", []).append(rec)
        p["observations"] = p["observations"][-60:]
        out.append({"pair": pid, **rec})
    _save(doc)
    return out


def list_pairs() -> dict:
    return _load().get("pairs", {})


def readiness() -> dict:
    """How close Stage 3 is to having something to work on. A report, not a gate."""
    pairs = list_pairs()
    axes_confirmed, axes_observed = set(), set()
    both_sides = {}
    for pid, p in pairs.items():
        axes_confirmed.add(p["axis"])
        ok = [o for o in (p.get("observations") or [])
              if "value" in o.get("primary", {}) and "value" in o.get("aggregate", {})]
        both_sides[pid] = len(ok)
        if ok:
            axes_observed.add(p["axis"])
    return {
        "ts": _now(),
        "pairs_confirmed": len(pairs),
        "axes_with_a_confirmed_pair": sorted(axes_confirmed),
        "axes_with_BOTH_sides_yielding": sorted(axes_observed),
        "observations_with_both_sides": both_sides,
        "stage3_axes_required": STAGE3_AXES_REQUIRED,
        "stage3_ready": len(axes_observed) >= STAGE3_AXES_REQUIRED,
        "note": "a confirmed pair whose aggregate side never yields is not paired data. "
                "Both counts are published because only the second one means Stage 3 has "
                "anything to look at.",
        "proposed_not_counted": len(_load().get("proposed") or {}),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(prog="provenance_pairs")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--observe", action="store_true")
    ap.add_argument("--readiness", action="store_true")
    a = ap.parse_args()

    if a.observe:
        print(json.dumps(observe(), ensure_ascii=False, indent=2))
    elif a.readiness:
        print(json.dumps(readiness(), ensure_ascii=False, indent=2))
    elif a.list:
        for pid, p in list_pairs().items():
            print(f"{pid}   [{p['axis']}]  {p['indicator']}  ({p['entity']})")
            for side in ("primary", "aggregate"):
                s = p[side]
                print(f"    {side:<10} {s.get('label')}")
                print(f"               origin={s.get('origin')}  "
                      f"class={s.get('reporter_class')}")
            last = (p.get("observations") or [{}])[-1]
            if last:
                print(f"    last read  primary={last.get('primary')}")
                print(f"               aggregate={last.get('aggregate')}")
        print(f"\n{len(list_pairs())} confirmed pair(s); nothing is computed from them.")
    else:
        ap.print_help()
