#!/usr/bin/env python3
"""
memory/existence_ledger.py — the system's record of its own continuous existence.

WHY THIS IS NOT MerkleMemory.commit()
-------------------------------------
MerkleMemory.commit() is the CYCLE's self-report. It increments total_cycles,
appends goal_score to the trend vectors, and updates avg_goal_score in the
self-profile. If the supervisor logged "cycle killed" through it, the system
would register a FAKE CYCLE: total_cycles inflates, a goal_score of 0.0 is
pushed into the trends, and the self-profile is dragged down by an event that
was never a cycle. The system's self-model would be poisoned by its own
supervision.

So supervision gets its own ledger. It is Merkle-ANCHORED (§ anchoring below)
but never Merkle-COMMITTED as a cycle. Supervision is recorded, not mistaken for
living.

WHY IT IS HASH-CHAINED
----------------------
A killed cycle cannot report its own death — the Merkle commit is step 24, the
END of the cycle, and a cycle wedged at step 11 never reaches it. Only the
supervisor, as a separate surviving process, can witness a death. That means the
death record is written by a process the cycle cannot vouch for, and it lands in
a plain file under memory/. The hash chain makes that file tamper-evident on its
own terms:

    hash = sha256(prev_hash + canonical_json(event_without_hash))

Any edit to any past line breaks every hash after it.

ANCHORING
---------
At step 24 the cycle passes this ledger's HEAD HASH and the events since the
last commit into MerkleMemory.commit(results=[...]) — a list that already
carries arbitrary event dicts (patch executions, quarantine events). The head
hash therefore lands inside archive/cycle_NNNNNN/ and is sealed into the Merkle
root. Any later edit to the ledger's history breaks the chain against a hash
already sealed in the tree.

Events from a KILLED cycle are anchored by the NEXT successful cycle. There is
therefore a window in which a death is in the ledger but not yet in the Merkle
tree. That is unavoidable — the dead cannot seal their own record — and it is
precisely why the ledger is independently hash-chained.

DESIGNED AS DATA, NOT LOG LINES
-------------------------------
So a future agent can read its own existence history and answer:
  "How long have I existed continuously?"   "When did I stop existing, and why?"
  "Which step kills me?"                    "Am I getting less reliable?"
  "Was my history edited?"
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

BASE = Path(__file__).resolve().parent.parent
LEDGER_PATH = BASE / "memory" / "existence_ledger.jsonl"

GENESIS_HASH = "0" * 64

# ── Event vocabulary ────────────────────────────────────────────────────────
CYCLE_STARTED    = "CYCLE_STARTED"
CYCLE_FINISHED   = "CYCLE_FINISHED"
CYCLE_KILLED     = "CYCLE_KILLED"
CYCLE_RESTARTED  = "CYCLE_RESTARTED"
MISSED_CATCHUP   = "MISSED_RUN_CATCHUP"
MISSED_SKIPPED   = "MISSED_RUN_SKIPPED"
# A human told the supervisor to treat today as already-run, suppressing the
# catch-up. Distinct from MISSED_RUN_SKIPPED (which the supervisor decides on its
# own, past the grace window): this one has a person behind it. A day with no
# cycle is a fact about the system's existence either way — but WHO decided it is
# part of the record, and a future agent reading its history must not mistake a
# human's choice for its own.
CATCHUP_SUPPRESSED = "CATCHUP_SUPPRESSED_BY_HUMAN"
BUDGET_EXHAUSTED = "CYCLE_FAILED_BUDGET_EXHAUSTED"
LOCK_STALE       = "LOCK_STALE_CLEARED"
SUPERVISOR_BOOT  = "SUPERVISOR_STARTED_AFTER_REBOOT"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(event: dict) -> str:
    """Deterministic serialisation for hashing: sorted keys, no whitespace drift.
    The 'hash' field itself is excluded — it is the output, not an input."""
    payload = {k: v for k, v in event.items() if k != "hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(prev_hash: str, event: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(event)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_all(skip_torn: bool = True) -> list[dict]:
    """Every event, oldest first.

    A torn final line (power loss mid-append) is skipped rather than treated as
    corruption of the whole ledger — the chain before it is still intact and
    still verifiable.
    """
    if not LEDGER_PATH.exists():
        return []

    events = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if skip_torn:
                continue      # torn line — see docstring
            raise
    return events


def head() -> Optional[dict]:
    events = read_all()
    return events[-1] if events else None


def head_hash() -> str:
    h = head()
    return h["hash"] if h else GENESIS_HASH


# ---------------------------------------------------------------------------
# Appending
# ---------------------------------------------------------------------------

def append(event_type: str, **fields: Any) -> dict:
    """Append one event, chained to the current head. Returns the written event.

    Append-only: this module never rewrites or deletes a line. The supervisor is
    the only writer, and memory/existence_ledger.jsonl is in the protected-path
    denylist, so no self-generated patch can forge or edit it.
    """
    prev = head_hash()
    seq = (head() or {}).get("seq", 0) + 1

    event = {
        "seq":       seq,
        "ts":        _utc_now(),
        "event":     event_type,
        **fields,
        "prev_hash": prev,
    }
    event["hash"] = _hash(prev, event)

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())   # a death record that is lost in the page cache
                                # when the machine dies is not a record at all
    return event


def record_kill(cycle_id: str, pid: int, step: Optional[str],
                heartbeat_age_sec: Optional[float], ceiling_sec: Optional[int],
                step_index: Optional[str] = None, restart_number: int = 0) -> dict:
    """A kill, with its REASON — not merely the fact of it.

    A future agent reading its own existence history needs to know not just THAT
    it was restarted but WHY: which step wedged, how stale the heartbeat had gone,
    and what ceiling it was measured against. "I was killed" is an event;
    "I was killed because internet_agent stopped beating for 47 minutes against a
    45-minute ceiling" is evidence — and it is what makes 'which step kills me?'
    answerable by GROUP BY rather than by guesswork.
    """
    return append(
        CYCLE_KILLED,
        cycle_id=cycle_id,
        pid=pid,
        reason={
            "wedged_step":        step,
            "wedged_step_index":  step_index,
            "heartbeat_age_sec":  round(heartbeat_age_sec, 1) if heartbeat_age_sec is not None else None,
            "ceiling_sec":        ceiling_sec,
            "exceeded_by_sec":    (round(heartbeat_age_sec - ceiling_sec, 1)
                                   if (heartbeat_age_sec is not None and ceiling_sec is not None)
                                   else None),
        },
        restart_number=restart_number,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify() -> dict:
    """Re-derive the whole chain. Returns {"valid": bool, "broken_at": seq|None, ...}.

    This is how the system answers "was my history edited?" — and how a human
    audits it. Cross-check the returned head_hash against the one sealed into
    the Merkle archive to detect an edit that rewrote the chain wholesale.
    """
    events = read_all()
    if not events:
        return {"valid": True, "events": 0, "broken_at": None, "head_hash": GENESIS_HASH}

    prev = GENESIS_HASH
    for e in events:
        if e.get("prev_hash") != prev:
            return {"valid": False, "events": len(events), "broken_at": e.get("seq"),
                    "error": "prev_hash does not match the previous event's hash",
                    "head_hash": None}
        expected = _hash(prev, e)
        if e.get("hash") != expected:
            return {"valid": False, "events": len(events), "broken_at": e.get("seq"),
                    "error": "hash does not match the event's own content (edited?)",
                    "head_hash": None}
        prev = e["hash"]

    return {"valid": True, "events": len(events), "broken_at": None, "head_hash": prev}


# ---------------------------------------------------------------------------
# Derived view — "what is my life like?"
# ---------------------------------------------------------------------------

def summary() -> dict:
    """Existence as data. The natural input to a future self_awareness question,
    answered from evidence rather than from a prompt."""
    events = read_all()
    if not events:
        return {"total_cycles_started": 0, "exists": False}

    starts   = [e for e in events if e["event"] == CYCLE_STARTED]
    finishes = [e for e in events if e["event"] == CYCLE_FINISHED]
    kills    = [e for e in events if e["event"] == CYCLE_KILLED]
    skipped  = [e for e in events if e["event"] == MISSED_SKIPPED]
    catchups = [e for e in events if e["event"] == MISSED_CATCHUP]

    kills_by_step: dict[str, int] = {}
    for k in kills:
        step = (k.get("reason") or {}).get("wedged_step") or "unknown"
        kills_by_step[step] = kills_by_step.get(step, 0) + 1

    first_ts = events[0]["ts"]
    try:
        age_days = (datetime.now(timezone.utc) - datetime.fromisoformat(first_ts)).days
    except Exception:
        age_days = None

    return {
        "exists": True,
        "first_event_utc":      first_ts,
        "last_event_utc":       events[-1]["ts"],
        "existence_age_days":   age_days,
        "total_cycles_started": len(starts),
        "total_cycles_finished": len(finishes),
        "total_kills":          len(kills),
        "total_missed_skipped": len(skipped),
        "total_catchups":       len(catchups),
        # Which step kills me? — answerable by GROUP BY because record_kill()
        # stores the reason, not just the fact.
        "kills_by_step":        dict(sorted(kills_by_step.items(),
                                            key=lambda kv: -kv[1])),
        "chain_valid":          verify()["valid"],
        "head_hash":            head_hash(),
    }


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        print(json.dumps(verify(), indent=2))
    else:
        print(json.dumps(summary(), indent=2, ensure_ascii=False))
