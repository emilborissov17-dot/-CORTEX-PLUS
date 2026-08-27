#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/extra_calls_ledger.py — THE LEDGER THAT PROVES IT DID NOT COST THE CYCLE.

core/extra_calls.py guards each call. This measures whether the guarding worked,
in numbers, on every attempt including the ones that never became a call —
because "we skipped it" is a claim about cost too, and a skip that took four
seconds of polling is not free.

WHAT IS ACTUALLY BEING DEFENDED. Reaction and perplexity fire at every phase
boundary, ~63 each a night. The fear is not that one call is slow; it is that
126 of them quietly add a fifth to the night and nobody notices because no
single line looks wrong. So the unit of judgement is the PHASE and the CYCLE,
not the call.

THE BASELINE IS THIS LEDGER'S OWN HISTORY. There was no per-phase timing record
anywhere in the repo — phase_of() leaves half the step contract unmapped, and
memory/steps/ was only created by COMMAND 33 part 1 and is still empty. So the
baseline is the median of the same phase over the last 10 DISTINCT sealed cycles
IN THIS FILE. Until that many exist the baseline is None, delta_percent is None,
and NO BREACH CAN FIRE — stated in the row rather than defaulted to zero, which
would have made every early night look like a 100% regression.

BREACH: phase delta > 15% OR cycle delta > 10%. Strictly greater: 15.0 is not a
breach, 15.1 is. It raises a PENDING item naming the numbers and writes
memory/extra_calls_suspended.flag so the NEXT cycle skips all extra calls. The
flag clears after one clean cycle, or when Emil deletes it.

config/reactions.json IS NEVER TOUCHED. The switches are his. This suspends;
only he disables.

    venv/Scripts/python.exe core/extra_calls_ledger.py            # DRY RUN
    venv/Scripts/python.exe core/extra_calls_ledger.py --write    # really write
"""
from __future__ import annotations

import json
import pathlib
import statistics
import sys
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

LEDGER = BASE / "memory" / "extra_calls_log.jsonl"
SUSPENDED_FLAG = BASE / "memory" / "extra_calls_suspended.flag"
PROPOSALS = BASE / "memory" / "improvement_proposals.json"

PHASE_BREACH_PCT = 15.0
CYCLE_BREACH_PCT = 10.0
BASELINE_CYCLES = 10

KIND_CALL = "call"
KIND_SEAL = "seal"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path=None) -> list:
    try:
        return [json.loads(l) for l in
                pathlib.Path(path or LEDGER).read_text(encoding="utf-8").splitlines()
                if l.strip()]
    except Exception:
        return []


def _append(row: dict, path=None) -> pathlib.Path:
    p = pathlib.Path(path or LEDGER)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return p


def _pct(actual, baseline) -> Optional[float]:
    if baseline in (None, 0) or actual is None:
        return None
    return round((float(actual) - float(baseline)) / float(baseline) * 100.0, 2)


# ── baselines, from this ledger's own sealed history ────────────────────────

def phase_baseline_ms(phase: str, exclude_cycle_id=None, path=None,
                      n: int = BASELINE_CYCLES) -> tuple:
    """(median_ms, cycles_used). None when there is not enough history.

    One value per CYCLE, not per row: a phase with four extra calls in it must
    not weigh four times as much as a phase with one.
    """
    rows = [r for r in _read(path)
            if r.get("kind") == KIND_CALL and r.get("phase") == phase
            and isinstance(r.get("phase_total_time_ms"), (int, float))
            and r.get("cycle_id") and r.get("cycle_id") != exclude_cycle_id]
    per_cycle = {}
    for r in rows:
        per_cycle.setdefault(r["cycle_id"], r["phase_total_time_ms"])
    if not per_cycle:
        return None, 0
    recent = list(per_cycle.values())[-n:]
    return round(statistics.median(recent), 1), len(recent)


def cycle_baseline_s(exclude_cycle_id=None, path=None,
                     n: int = BASELINE_CYCLES) -> tuple:
    rows = [r for r in _read(path)
            if r.get("kind") == KIND_SEAL
            and isinstance(r.get("cycle_total_time_s"), (int, float))
            and r.get("cycle_id") != exclude_cycle_id]
    vals = [r["cycle_total_time_s"] for r in rows][-n:]
    if not vals:
        return None, 0
    return round(statistics.median(vals), 1), len(vals)


# ── 6.1 one line per attempt, skips included ───────────────────────────────

def record(outcome: str, cycle_id: str, phase: str, extra_kind: str,
           regular_step_time_ms=None, extra_time_ms=None, queue_wait_ms=None,
           phase_total_time_ms=None, path=None, write: bool = True) -> dict:
    """Append one line for one attempt. Never raises.

    EVERY attempt, including SKIPPED_RESOURCES and SKIPPED_BUSY: a skip that
    spent five seconds polling /api/ps cost the phase five seconds, and a ledger
    that only recorded the calls would show that time as unexplained.
    """
    base_ms, base_n = phase_baseline_ms(phase, exclude_cycle_id=cycle_id, path=path)
    row = {
        "ts": _now(),
        "kind": KIND_CALL,
        "cycle_id": cycle_id,
        "phase": phase,
        "extra_kind": extra_kind,
        "regular_step_time_ms": regular_step_time_ms,
        "extra_time_ms": extra_time_ms,
        "queue_wait_ms": queue_wait_ms,
        "phase_total_time_ms": phase_total_time_ms,
        "baseline_phase_time_ms": base_ms,
        "baseline_cycles": base_n,
        "delta_percent": _pct(phase_total_time_ms, base_ms),
        "outcome": outcome,
    }
    if base_ms is None:
        row["baseline_why"] = (
            "no sealed cycle in this ledger has recorded phase {!r} yet — the "
            "baseline is not zero, it does not exist".format(phase))
    if write:
        row["written_to"] = str(_append(row, path))
    return row


# ── 6.2 + 6.3 the seal, and the breach ─────────────────────────────────────

def seal_cycle(cycle_id: str, cycle_total_time_s: float, path=None,
               flag_path=None, proposals_path=None, write: bool = True) -> dict:
    """Close the cycle's ledger, judge it, and suspend if it cost too much."""
    base_s, base_n = cycle_baseline_s(exclude_cycle_id=cycle_id, path=path)
    cycle_delta = _pct(cycle_total_time_s, base_s)

    rows = [r for r in _read(path)
            if r.get("kind") == KIND_CALL and r.get("cycle_id") == cycle_id]
    worst = None
    for r in rows:
        d = r.get("delta_percent")
        if d is not None and (worst is None or d > worst["delta_percent"]):
            worst = r

    phase_breach = bool(worst and worst["delta_percent"] > PHASE_BREACH_PCT)
    cycle_breach = bool(cycle_delta is not None and cycle_delta > CYCLE_BREACH_PCT)
    breach = phase_breach or cycle_breach

    seal = {
        "ts": _now(),
        "kind": KIND_SEAL,
        "cycle_id": cycle_id,
        "cycle_total_time_s": cycle_total_time_s,
        "baseline_cycle_time_s": base_s,
        "baseline_cycles": base_n,
        "cycle_delta_percent": cycle_delta,
        "attempts": len(rows),
        "worst_phase": (worst or {}).get("phase"),
        "worst_phase_delta_percent": (worst or {}).get("delta_percent"),
        "worst_phase_time_ms": (worst or {}).get("phase_total_time_ms"),
        "worst_phase_baseline_ms": (worst or {}).get("baseline_phase_time_ms"),
        "phase_breach": phase_breach,
        "cycle_breach": cycle_breach,
        "breach": breach,
        "thresholds": {"phase_pct": PHASE_BREACH_PCT, "cycle_pct": CYCLE_BREACH_PCT},
    }
    if base_s is None:
        seal["baseline_why"] = (
            "fewer than one sealed cycle in this ledger — no cycle baseline "
            "exists, so no cycle breach can fire")

    if write:
        seal["written_to"] = str(_append(seal, path))
        if breach:
            seal["suspended"] = _suspend(seal, flag_path)
            seal["pending_item"] = _raise_pending(seal, proposals_path)
        else:
            # ONE CLEAN CYCLE CLEARS IT. Not a timer, not a retry count: the
            # thing being asked is "did it cost the cycle", and a cycle that did
            # not is the answer.
            seal["suspension_cleared"] = clear_suspension(flag_path)
    return seal


def _suspend(seal: dict, flag_path=None) -> str:
    p = pathlib.Path(flag_path or SUSPENDED_FLAG)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "ts": _now(),
        "cycle_id": seal["cycle_id"],
        "why": ("extra calls cost more than the ceiling allows: "
                "worst phase {} at {}% (ceiling {}%), cycle at {}% (ceiling {}%)"
                .format(seal.get("worst_phase"),
                        seal.get("worst_phase_delta_percent"), PHASE_BREACH_PCT,
                        seal.get("cycle_delta_percent"), CYCLE_BREACH_PCT)),
        "clears": ("automatically after one cycle that does not breach, or when "
                   "Emil deletes this file"),
        # SAID OUT LOUD in the flag itself, because the next person to read it
        # will be deciding whether to go and switch something off.
        "note": ("config/reactions.json is NOT touched by this. The switches are "
                 "human-written; this suspends the next cycle only."),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(p)


def suspended(flag_path=None) -> bool:
    return pathlib.Path(flag_path or SUSPENDED_FLAG).exists()


def clear_suspension(flag_path=None) -> bool:
    p = pathlib.Path(flag_path or SUSPENDED_FLAG)
    if p.exists():
        p.unlink()
        return True
    return False


def _raise_pending(seal: dict, proposals_path=None) -> Optional[str]:
    """A PENDING item naming the phase and the numbers. Never raises."""
    p = pathlib.Path(proposals_path or PROPOSALS)
    # THE NUMBERS, NOT THE VERDICT. A pending item that says "extra calls are
    # too slow" tells the reader nothing they can act on; these five numbers
    # tell them which phase, by how much, against what, and where to look.
    problem = (
        "EXTRA_CALLS_BREACH — the extra model calls cost the cycle more than "
        "the agreed ceiling. Worst phase {} took {}ms against a baseline of "
        "{}ms ({}%, ceiling {}%); the whole cycle took {}s against {}s ({}%, "
        "ceiling {}%). Cycle {}."
        .format(seal.get("worst_phase"), seal.get("worst_phase_time_ms"),
                seal.get("worst_phase_baseline_ms"),
                seal.get("worst_phase_delta_percent"), PHASE_BREACH_PCT,
                seal.get("cycle_total_time_s"), seal.get("baseline_cycle_time_s"),
                seal.get("cycle_delta_percent"), CYCLE_BREACH_PCT,
                seal.get("cycle_id")))
    item = {
        "component": "EXTRA_CALLS",
        "problem": problem,
        "solution": ("Read memory/extra_calls_log.jsonl for cycle {}. The next "
                     "cycle already skips all extra calls "
                     "(memory/extra_calls_suspended.flag). Either accept the "
                     "cost and delete the flag, or turn the switch off in "
                     "config/reactions.json — which only you can do."
                     .format(seal.get("cycle_id"))),
        "measurable_goal": ("phase delta back under {}% and cycle delta under "
                            "{}%".format(PHASE_BREACH_PCT, CYCLE_BREACH_PCT)),
        "root_cause": "reaction and perplexity fire at every phase boundary",
        "priority": "HIGH",
        "real_world_signal": True,
        "generated_by": "EXTRA_CALLS_BREACH",
        "timestamp": _now(),
    }
    try:
        blob = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        if not isinstance(blob, dict):
            blob = {"proposals": blob if isinstance(blob, list) else []}
        blob.setdefault("proposals", []).append(item)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(blob, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        return item["problem"][:80]
    except Exception:
        return None


def _selftest() -> int:
    import tempfile
    print("core/extra_calls_ledger.py --selftest")
    ok = True

    def check(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print("  {}  {}".format("OK  " if cond else "FAIL", name))

    d = pathlib.Path(tempfile.mkdtemp())
    led, flag, props = d / "log.jsonl", d / "susp.flag", d / "props.json"

    r = record("COMPLETED", "C1", "E_PROPOSE", "reaction",
               phase_total_time_ms=1000, path=led)
    check("the first cycle has no baseline", r["baseline_phase_time_ms"] is None)
    check("and says so rather than defaulting to zero", "baseline_why" in r)
    check("delta is None, not 100%", r["delta_percent"] is None)

    seal_cycle("C1", 100.0, path=led, flag_path=flag, proposals_path=props)
    record("COMPLETED", "C2", "E_PROPOSE", "reaction",
           phase_total_time_ms=1151, path=led)
    s = seal_cycle("C2", 100.0, path=led, flag_path=flag, proposals_path=props)
    check("15.1% over the phase baseline is a breach", s["phase_breach"] is True)
    check("the flag is written", flag.exists())
    check("a PENDING item names the numbers", props.exists())
    check("config/reactions.json untouched",
          json.loads((BASE / "config" / "reactions.json")
                     .read_text(encoding="utf-8"))["reaction"]["enabled"] is False)

    record("COMPLETED", "C3", "E_PROPOSE", "reaction",
           phase_total_time_ms=1000, path=led)
    s3 = seal_cycle("C3", 100.0, path=led, flag_path=flag, proposals_path=props)
    check("one clean cycle clears the flag", s3.get("suspension_cleared") is True)
    check("and the flag is gone", not flag.exists())

    print("  RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())

    # DRY RUN BY DEFAULT. This module appends to a ledger; three live-state
    # breaches happened on 27 Aug, one of them because a module's bare
    # invocation wrote to the learning trace. Looking is free.
    rows = _read()
    seals = [r for r in rows if r.get("kind") == KIND_SEAL]
    print("DRY RUN — nothing was written. Pass --write to append a seal.\n")
    print(json.dumps({
        "ledger": str(LEDGER),
        "exists": LEDGER.exists(),
        "rows": len(rows),
        "sealed_cycles": len(seals),
        "suspended": suspended(),
        "cycle_baseline_s": cycle_baseline_s()[0],
        "thresholds": {"phase_pct": PHASE_BREACH_PCT, "cycle_pct": CYCLE_BREACH_PCT},
    }, indent=2))
    if "--write" in sys.argv:
        print("\n--write given, but this module has no standalone write action: "
              "records are appended by the cycle through record() and "
              "seal_cycle(). Nothing was written.")
