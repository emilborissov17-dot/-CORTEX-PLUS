#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
experiments/grounding/divergence_ledger.py — E2: where the sources disagree.

A PURE RECORDER. It holds no threshold, raises no alert, and passes no verdict.
It writes down, tamper-evidently, what the anchor said, what the daily proxy said,
how far apart they were, and how that distance compares to this axis's OWN
history. Whether the distance MEANS anything is decided elsewhere:
core/source_trust.py::grounding_verdict types it, core/notary.py weighs it.
One truth, one judge — a second judge is a schism.

PROVENANCE OF THIS VERSION. The requirement is RECOVERED, the implementation is
NEW WORK dated 2026-08-28. A `git reset --hard` over uncommitted work destroyed
the version that carried these fixes; the module docstring survived whole inside
experiments/grounding/__pycache__/divergence_ledger.cpython-314.pyc compiled
2026-08-17 14:16:18, and that docstring is the specification below. No line here
was reassembled from bytecode.

Four defects closed here, each named:

 1. DIVERGENCE_ALERT = 0.5 IS GONE. A hardcoded 0.5 is a verdict smuggled in as a
    constant. It is replaced by `divergence_z`: how far today's divergence sits
    from this axis's own rolling mean, measured in this axis's own sigmas. The
    sigma that turns z into a verdict lives in the HUMAN file
    config/source_trust_rules.json, beside every other tolerance — so no second
    threshold exists anywhere in the system.

 2. THE RECORD NOW CARRIES `def_hash`. Without a fingerprint of the definitions
    that produced a row, the ledger's own history silently stops being comparable
    to itself. Rows are compared only against rows carrying the SAME def_hash.
    The fingerprint is deliberately over-sensitive — even a comment flips it.
    That errs in the safe direction: it may say "not comparable" too often, never
    "comparable" wrongly.

 3. WITH TOO LITTLE HISTORY IT STILL WRITES. Below `grounding_min_history`
    observations the row carries insufficient_history: true and no z — but the
    raw number is kept. Silence would be data loss, and data loss is not caution.

 4. THE TAMPER CHECK NOW CHECKS THE CONTENT. The old one verified only that
    prev_hash pointed at the previous hash. Any record's body could be rewritten,
    its stored hash left untouched, and the chain still reported intact — it
    guarded the ORDER and not the CONTENT. verify() now recomputes sha256(body)
    for every record.

Two further defects, found while reading rather than reported:
  * composers' `daily` is a slot DICT ({id, value, unit, ...}), not a scalar. The
    old ledger stored the whole dict under "daily" and counted "axes with live
    daily" off a dict that is truthy whenever a slot exists at all.
  * "No daily source at all" and "subtraction refused as a category error" both
    recorded divergence=None and were indistinguishable — a blind spot
    masquerading as a missing measurement. Now recorded as `divergence_blocked`.

Safe by construction: reads memory/composed_indicators.json, appends to its own
ledger. It never touches scoring and never quarantines anything.

  python experiments/grounding/divergence_ledger.py --record   # append this cycle
  python experiments/grounding/divergence_ledger.py --report   # recent state + integrity
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

RULES = REPO / "config" / "source_trust_rules.json"

# recorder only: no thresholds, no alerts, no verdicts
# The sigma that turns a z into a verdict lives in config/source_trust_rules.json,
# beside every other tolerance, so no second threshold exists in the system.
MIN_HISTORY_DEFAULT = 5
SCHEMA = "grounding/2"
JUDGED_BY = "core.source_trust.grounding_verdict + core.notary"
DEF_FILES = ("experiments/grounding/divergence_ledger.py",
             "experiments/composers/composer.py")


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


def _rules() -> dict:
    """source_trust's rules are the SINGLE source of tolerances in the system."""
    return _load(RULES, {}) or {}


def _min_history() -> int:
    r = _rules()
    return int(r.get("grounding_min_history", r.get("min_history",
                                                    MIN_HISTORY_DEFAULT)))


def _def_hash(*parts: str) -> str:
    """Fingerprint of the definitions that produced a row.

    OVER-SENSITIVE BY CHOICE — even a comment flips it. A false "not comparable"
    costs one cycle of history; a false "comparable" silently compares numbers
    that mean different things, which is the failure this exists to prevent.
    """
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def _def_files() -> dict:
    """{path: fingerprint} — WHICH definitions the row's def_hash covers.
    A hash nobody can attribute is a number, not evidence."""
    out = {}
    for rel in DEF_FILES:
        try:
            out[rel] = _def_hash((REPO / rel).read_text(encoding="utf-8"))[:12]
        except Exception:
            out[rel] = "<unreadable>"
    return out


def _current_def_hash() -> str:
    """The definitions in force this cycle: this recorder plus the composer that
    produces the numbers it reads."""
    src = []
    for f in (Path(__file__), REPO / "experiments" / "composers" / "composer.py"):
        try:
            src.append(f.read_text(encoding="utf-8"))
        except Exception:
            src.append("<unreadable>")
    return _def_hash(*src)


def _slot_value(slot):
    """composers' `daily` is a slot DICT, not a scalar. A dict is truthy whenever
    a slot EXISTS, so treating it as a value counted slots and called them live
    measurements."""
    if isinstance(slot, dict):
        v = slot.get("value")
        return v if isinstance(v, (int, float)) else None
    return slot if isinstance(slot, (int, float)) else None


def _slot_unit(slot):
    return slot.get("unit") if isinstance(slot, dict) else None


def _past(records, def_hash):
    """{axis: [divergence, ...]} — ONLY from rows produced by the same definitions."""
    out = {}
    for r in records:
        if not isinstance(r, dict) or r.get("def_hash") != def_hash:
            continue
        for axis, row in (r.get("axes") or {}).items():
            d = row.get("divergence") if isinstance(row, dict) else None
            if isinstance(d, (int, float)):
                out.setdefault(axis, []).append(float(d))
    return out


def _z(value, history):
    """How far `value` sits from its own history, in its own sigmas. None when
    the history cannot produce a sigma — a z from zero spread is not a number."""
    if value is None or len(history) < 2:
        return None
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / (len(history) - 1)
    sd = var ** 0.5
    if sd < 1e-12:
        return None
    return round((float(value) - mean) / sd, 4)


def _score(row: dict, history: list, min_history: int) -> dict:
    """The row for this cycle: raw numbers and their own statistics. NO VERDICTS.

    FIELD NAMES ARE NOT A CHOICE HERE. 53 records already on disk use this exact
    shape — divergence_blocked as a SENTENCE (null when nothing blocked),
    n_history, insufficient_history always present as a bool. Inventing a second
    convention in the same file is how a ledger stops being comparable to itself,
    which is the very defect def_hash exists to prevent.
    """
    out = dict(row)
    div = row.get("divergence")
    out["divergence_blocked"] = None
    out["n_history"] = len(history)

    if div is None:
        # A daily VALUE that cannot be subtracted is a blind spot and says so.
        # No daily source at all is already legible from daily_source == None,
        # and the two must not look alike.
        if row.get("daily") is not None:
            a_u = row.get("anchor_unit") or "undeclared"
            d_u = row.get("daily_unit") or "undeclared"
            if a_u != d_u:
                out["divergence_blocked"] = (
                    f"not comparable: anchor unit {a_u} vs daily unit {d_u} — "
                    f"subtraction would be a category error")
        out["divergence_z"] = None
        out["insufficient_history"] = len(history) < min_history
        return out

    if len(history) < min_history:
        # Still written. Silence would be data loss, and data loss is not caution.
        out["insufficient_history"] = True
        out["divergence_z"] = None
        return out

    out["insufficient_history"] = False
    out["divergence_z"] = _z(div, history)
    return out


def _lines(path=None):
    p = Path(path) if path else LEDGER
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _sha(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def verify(path=None) -> dict:
    """Check the CONTENT and the ORDER. The old code checked only the order.

    A chain that guards order but not content is theatre: any record's body could
    be rewritten, its stored hash left untouched, and the chain still reported
    intact.
    """
    prev, n, bad = "0" * 64, 0, None
    for i, line in enumerate(_lines(path)):
        try:
            r = json.loads(line)
        except Exception:
            return {"intact": False, "records": n,
                    "why": f"unreadable line at record {i}"}
        n += 1
        body = {k: v for k, v in r.items() if k != "hash"}
        if _sha(body) != r.get("hash"):
            return {"intact": False, "records": n,
                    "why": f"CONTENT does not match the recorded hash at record {i}"}
        if r.get("prev_hash") != prev:
            return {"intact": False, "records": n,
                    "why": f"ORDER is broken — prev_hash does not point at the "
                           f"previous record at {i}"}
        prev = r.get("hash")
    return {"intact": True, "records": n, "why": "content AND order verified"}


def _snapshot():
    """This cycle's per-axis grounding row. Raw numbers and their own statistics."""
    comp = _load(COMPOSED, {})
    def_hash = _current_def_hash()
    past = _past([json.loads(l) for l in _lines() if l.strip()], def_hash)
    min_h = _min_history()

    axes = {}
    for axis, r in comp.items():
        if not isinstance(r, dict):
            continue
        c = r.get("composed", {}) or {}
        anchor_slot, daily_slot = c.get("anchor") or {}, c.get("daily")
        agree = r.get("agreement", {}) or {}
        contra = [pid for pid, pv in (agree.get("proxies") or {}).items()
                  if isinstance(pv, dict) and pv.get("direction") == "contradict"]
        row = {
            "anchor": anchor_slot.get("value"),
            "anchor_source": anchor_slot.get("id"),
            "anchor_unit": anchor_slot.get("unit"),
            # the VALUE out of the slot, never the slot itself
            "daily": _slot_value(daily_slot),
            "daily_source": daily_slot.get("id") if isinstance(daily_slot, dict) else None,
            "daily_unit": _slot_unit(daily_slot),
            "divergence": c.get("divergence"),
            "confidence": r.get("confidence"),
            "anchor_direction": agree.get("anchor_direction"),
            "contradicting_proxies": contra,
        }
        axes[axis] = _score(row, past.get(axis, []), min_h)
    return axes, def_hash


def record():
    axes, def_hash = _snapshot()
    prev = _last_hash()
    body = {
        "ts": _now(),
        "schema": SCHEMA,
        "note": "recorder only: no thresholds, no alerts, no verdicts",
        "judged_by": JUDGED_BY,
        "def_hash": def_hash,
        "def_files": _def_files(),
        "min_history": _min_history(),
        "axes": axes,
        "prev_hash": prev,
    }
    rec = {**body, "hash": _sha(body)}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + chr(10))

    live = sum(1 for a in axes.values() if a.get("daily") is not None)
    measurable = sum(1 for a in axes.values() if a.get("divergence") is not None)
    blocked = sum(1 for a in axes.values() if a.get("divergence_blocked"))
    print(f"[grounding] def_hash {def_hash} — rows with another fingerprint are "
          f"not compared against this one")
    print(f"[grounding] recorded {len(axes)} axes | live daily {live} | "
          f"divergence measurable {measurable} | blocked as incomparable {blocked} "
          f"-> memory/grounding_ledger.jsonl")
    for axis, a in sorted(axes.items()):
        z = a.get("divergence_z")
        if z is not None:
            print(f"  {axis}: divergence {a['divergence']} — {z} sigma of its own "
                  f"history (n={a.get('n_history')}) — verdict is source_trust's, "
                  f"not ours")
    return rec


def report():
    lines = _lines()
    if not lines:
        print("no grounding ledger yet — run --record (from a cycle)")
        return
    print(f"grounding ledger: records={len(lines)}")
    for line in lines[-3:]:
        try:
            r = json.loads(line)
        except Exception:
            print("  <unreadable line>")
            continue
        axes = r.get("axes") or {}
        live = sum(1 for a in axes.values() if a.get("daily") is not None)
        blocked = sum(1 for a in axes.values() if a.get("divergence_blocked"))
        print(f"  {str(r.get('ts'))[:19]}Z  def_hash={r.get('def_hash')}  "
              f"{len(axes)} axes | live daily {live} | blocked {blocked}")
    v = verify()
    print(f"chain intact (content AND order): {v['intact']} — {v['why']} "
          f"({v['records']} records)")
    print("verdicts live in core.source_trust.grounding_verdict + core.notary")


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    else:
        record()
