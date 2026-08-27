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
# CYCLE_KILLED and CYCLE_DIED are NOT the same event, and conflating them would
# lose the distinction that matters most in a post-mortem. CYCLE_KILLED is a
# DELIBERATE act: the supervisor watched a still-alive cycle go stale past its
# ceiling and terminated it on purpose, and it records WHY (which step wedged,
# how stale, against what ceiling). CYCLE_DIED is a DISCOVERY: the cycle vanished
# on its own — OOM under memory pressure, a hard power loss, an uncaught crash —
# and the supervisor only learned of it after the fact, finding a stale lock with
# no CYCLE_FINISHED behind it. It cannot say how or exactly when; it can only
# record the death and the last step the heartbeat named. Before 2026-07-15 such
# a death left NO event at all: the dead cycle still satisfied the daily gate, so
# nothing retried and total_kills stayed 0 while a cycle had actually died.
CYCLE_DIED       = "CYCLE_DIED"
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
# A gate read a threshold, found it crossed, and declined to start the night.
# This is an ENDING, not a death: nothing ran, nothing crashed, and a human
# decision — a threshold somebody set — is the whole cause. It was terminal in
# core.unclean_stop and defined in core/survival_gate.py long before any code on
# the homeostasis path produced it, which is how the 24 Aug 2026 refusal came to
# be recorded as CYCLE_DIED.
CYCLE_REFUSED    = "CYCLE_REFUSED_SURVIVAL_GATE"
LOCK_STALE       = "LOCK_STALE_CLEARED"
# THE ONLY WAY TO CORRECT THIS LEDGER. A line already written is never edited and
# never deleted — the chain is the whole value, and a history that can be revised
# to match today's understanding is not evidence of anything. When a past event
# is found to have been misclassified, the correction is APPENDED: it names the
# seq and the hash of the line it corrects and what the event should have been.
# Both readings stay on the record, and which one is later is not in doubt.
CORRECTION       = "LEDGER_CORRECTION"
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

    Append-only: this module never rewrites or deletes a line.

    There are exactly TWO writers, and the split is deliberate:
      * supervisor.py       — everything it can observe from OUTSIDE a cycle:
                              starts, kills, restarts, missed runs, stale locks.
      * fast_cycle_runner.py — CYCLE_FINISHED, and only that. A clean exit is the
                              one fact no outside observer can establish: from the
                              supervisor's vantage, "finished" and "died quietly"
                              look identical. The cycle is the sole witness to its
                              own completion, so it must be the one to say so.
                              (Before 2026-07-14 nobody said so, and every
                              successful cycle was recorded as a probable crash.)

    memory/existence_ledger.jsonl is in the protected-path denylist, so no
    self-generated patch can forge or edit it — the runner may APPEND its own
    completion through this module, but it cannot rewrite the history.
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


def record_death(cycle_id: str, pid: int, last_step: Optional[str],
                 detail: Optional[str] = None) -> dict:
    """A cycle that DIED — witnessed after the fact, not deliberately killed.

    Unlike record_kill(), there is no heartbeat-age or ceiling to record: the
    supervisor never measured this cycle going stale, it simply found the body (a
    stale lock with no CYCLE_FINISHED). What it CAN preserve is the last step the
    heartbeat named before the cycle vanished — which is what makes 'which step
    kills me?' answerable for deaths, not only for kills. `last_step` falls back
    to "unknown" when no heartbeat survived the death.
    """
    return append(
        CYCLE_DIED,
        cycle_id=cycle_id,
        pid=pid,
        last_step=last_step or "unknown",
        detail=detail,
    )


def has_finished(cycle_id: Optional[str]) -> bool:
    """True iff the ledger already holds a CYCLE_FINISHED for this cycle.

    This is how the supervisor, on finding a stale lock, tells the two unclean
    endings apart. A cycle that DIED mid-run has no CYCLE_FINISHED, so it must be
    retried. A cycle that finished cleanly and then died before it could unlink
    its own lock DOES have one — its work is done, and it must NOT be retried.
    (The runner writes CYCLE_FINISHED before it releases the lock, so this race is
    real: the seal can land while the unlink does not.)

    With no cycle_id there is nothing to match on, and the honest answer is False:
    we cannot prove a nameless cycle finished, so we do not claim it did.
    """
    if not cycle_id:
        return False
    for e in read_all():
        if e.get("event") == CYCLE_FINISHED and e.get("cycle_id") == cycle_id:
            return True
    return False


def record_correction(corrects_seq: int, should_have_been: str, detail: str,
                      recorded_by: str, cycle_id: Optional[str] = None) -> dict:
    """Append one correction for an earlier, misclassified event.

    Refuses to write a correction for a seq that is not there, or one whose hash
    cannot be read: a correction pointing at nothing is worse than no correction,
    because it looks like the record has been reconciled when it has not.
    """
    target = None
    for e in read_all():
        if e.get("seq") == corrects_seq:
            target = e
            break
    if target is None:
        raise ValueError(f"no event with seq {corrects_seq} — refusing to "
                         f"correct a line that is not on the record")
    return append(
        CORRECTION,
        corrects_seq=corrects_seq,
        corrects_event=target.get("event"),
        corrects_hash=target.get("hash"),
        corrects_ts=target.get("ts"),
        should_have_been=should_have_been,
        cycle_id=cycle_id if cycle_id is not None else target.get("cycle_id"),
        detail=detail,
        recorded_by=recorded_by,
    )


def was_refused(cycle_id: Optional[str]) -> bool:
    """True iff a gate recorded CYCLE_REFUSED_SURVIVAL_GATE for this cycle.

    The companion to has_finished(), and the reason it is separate rather than
    folded in: both mean "this cycle's ending is already accounted for, do not
    write a death for it", but they mean OPPOSITE things about the day. A
    FINISHED cycle did the night's work and must not be retried. A REFUSED cycle
    did none of it — the night is still owed — so the supervisor clears the lock
    and lets the ordinary daily logic start a replacement.

    Answering False for a nameless cycle for the same reason has_finished() does:
    we cannot prove a nameless cycle was refused, so we do not claim it was.
    """
    if not cycle_id:
        return False
    for e in read_all():
        if e.get("event") == CYCLE_REFUSED and e.get("cycle_id") == cycle_id:
            return True
    return False


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
    deaths   = [e for e in events if e["event"] == CYCLE_DIED]
    skipped  = [e for e in events if e["event"] == MISSED_SKIPPED]
    catchups = [e for e in events if e["event"] == MISSED_CATCHUP]

    kills_by_step: dict[str, int] = {}
    for k in kills:
        step = (k.get("reason") or {}).get("wedged_step") or "unknown"
        kills_by_step[step] = kills_by_step.get(step, 0) + 1

    # Deaths carry their last known step directly (no reason block — nobody
    # measured them). Kept separate from kills_by_step: a step the supervisor
    # kills for going stale is a different fact from a step the machine died in.
    deaths_by_step: dict[str, int] = {}
    for d in deaths:
        step = d.get("last_step") or "unknown"
        deaths_by_step[step] = deaths_by_step.get(step, 0) + 1

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
        "total_deaths":         len(deaths),
        "total_missed_skipped": len(skipped),
        "total_catchups":       len(catchups),
        # Which step kills me? — answerable by GROUP BY because record_kill()
        # stores the reason, not just the fact.
        "kills_by_step":        dict(sorted(kills_by_step.items(),
                                            key=lambda kv: -kv[1])),
        # Which step do I die in? — the same question for abrupt deaths.
        "deaths_by_step":       dict(sorted(deaths_by_step.items(),
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
