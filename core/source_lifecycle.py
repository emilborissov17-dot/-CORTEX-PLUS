#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/source_lifecycle.py — BELIEF IN A SOURCE IS EARNED, LOGGED, AND REVOCABLE.

WHY THE ALLOWLIST HAD TO GO
----------------------------
The first version of the DMZ worker had a hand-written allowlist: a human wrote
four URLs into a config and only those were fetched. That is safe and it is
also a dead end — data_scout has been finding sources on its own since June and
44 active JSON candidates sit in memory/discovered_data_sources.json, unused,
because nothing decided whether to believe them. Some are from 31 July.

A hand-written list cannot grow. What can grow is a PROCESS for earning trust:

    CANDIDATE   fetched every cycle, recorded, and kept OUT of the composite
                |
                |  PROMOTE_AFTER clean observations, and not chaotic
                v
    TRUSTED     enters the composite as MEASURED
                |
                |  DEMOTE_AFTER contradictions
                v
    DEMOTED     out again, and it does not walk back in by itself

Nothing is trusted because it was written down. Everything is trusted because
it behaved, and the behaviour is on disk in source_lifecycle_ledger.jsonl.

WHAT COUNTS AS EVIDENCE
------------------------
  clean          a finite number came back
  refusal        no number: HTTP error, unreadable body, bad path, wrong type
  contradiction  a number came back that disagrees with the trusted reading for
                 the same axis by more than CONTRADICTION_TOLERANCE

A refusal breaks the promotion streak but is NOT a contradiction. An endpoint
that is down is not an endpoint that is lying, and conflating the two would
demote every source behind a flaky network.

CHAOS BLOCKS PROMOTION
-----------------------
A source can return a number every single time and still be worthless: if its
own readings swing wildly, its next reading tells you nothing. So promotion
also requires the coefficient of variation over the window to sit under
CHAOS_CV. A source that alternates 1, 900, 3, 700 never promotes, however
reliably it answers.

    venv\\Scripts\\python.exe core/source_lifecycle.py --selftest
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]
STATE = BASE / "memory" / "source_lifecycle.json"
LEDGER = BASE / "memory" / "source_lifecycle_ledger.jsonl"

CANDIDATE, TRUSTED, DEMOTED = "CANDIDATE", "TRUSTED", "DEMOTED"

# Clean observations needed before a candidate is believed. Five cycles is
# roughly five nights: long enough that a source has to survive a weekend, short
# enough that a find from 31 July is not still waiting in September.
PROMOTE_AFTER = 5

# Contradictions that end trust. Three, not one: a single disagreement is as
# likely to be the incumbent being wrong as the challenger.
DEMOTE_AFTER = 3

# Relative disagreement with the axis's trusted reading, above which the two
# cannot both be right.
CONTRADICTION_TOLERANCE = 0.25

# Coefficient of variation over the promotion window, above which the source is
# too unstable for its next reading to mean anything.
CHAOS_CV = 0.5

WINDOW = PROMOTE_AFTER


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: pathlib.Path | None = None) -> dict:
    try:
        return json.loads((path or STATE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(state: dict, path: pathlib.Path | None = None) -> None:
    p = path or STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


def log(entry: dict, ledger: pathlib.Path | None = None) -> None:
    """Append-only evidence. A promotion nobody can audit is a promotion nobody
    should trust."""
    p = ledger or LEDGER
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), **entry}, ensure_ascii=False) + "\n")
    except Exception:
        pass  # the ledger must never take the cycle down


def record_for(state: dict, source_id: str, axis: str | None = None) -> dict:
    rec = state.setdefault(source_id, {
        "source_id": source_id, "axis": axis, "state": CANDIDATE,
        "clean_streak": 0, "contradictions": 0,
        "observations": 0, "refusals": 0,
        "recent_values": [], "first_seen": _now(), "history": [],
    })
    if axis and not rec.get("axis"):
        rec["axis"] = axis
    return rec


# ---------------------------------------------------------------------------
# The judgements
# ---------------------------------------------------------------------------

def cv(values: list[float]) -> float | None:
    """Coefficient of variation. None when it cannot be computed."""
    vals = [float(v) for v in values if isinstance(v, (int, float))
            and not isinstance(v, bool) and math.isfinite(float(v))]
    if len(vals) < 2:
        return None
    mean = statistics.fmean(vals)
    if mean == 0:
        return None if all(v == 0 for v in vals) else float("inf")
    return abs(statistics.pstdev(vals) / mean)


def is_chaotic(values: list[float]) -> bool:
    c = cv(values)
    return c is not None and c > CHAOS_CV


def contradicts(value, peer) -> bool:
    """Does this reading disagree with the trusted reading for the same axis?"""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    if not isinstance(peer, (int, float)) or isinstance(peer, bool):
        return False
    if peer == 0:
        return abs(value) > CONTRADICTION_TOLERANCE
    return abs(value - peer) / abs(peer) > CONTRADICTION_TOLERANCE


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

def observe(source_id: str, *, axis: str | None = None, ok: bool,
            value=None, reason: str | None = None, peer=None,
            state: dict | None = None, ledger: pathlib.Path | None = None) -> dict:
    """Record one observation and return the source's record after it."""
    own = state is None
    st = load() if own else state
    rec = record_for(st, source_id, axis)
    rec["observations"] += 1
    rec["last_seen"] = _now()

    was = rec["state"]
    event = None

    if not ok:
        rec["refusals"] += 1
        rec["clean_streak"] = 0
        rec["last_refusal"] = reason
        event = "refusal"
    else:
        rec["last_value"] = value
        rec["recent_values"] = (rec["recent_values"] + [value])[-WINDOW:]
        if peer is not None and contradicts(value, peer):
            rec["contradictions"] += 1
            rec["clean_streak"] = 0
            rec["last_contradiction"] = {"value": value, "peer": peer}
            event = "contradiction"
        else:
            rec["clean_streak"] += 1
            event = "clean"

    # ── transitions ────────────────────────────────────────────────────────
    chaotic = is_chaotic(rec["recent_values"])
    rec["cv"] = cv(rec["recent_values"])
    rec["chaotic"] = chaotic

    if rec["state"] == CANDIDATE:
        if rec["clean_streak"] >= PROMOTE_AFTER and not chaotic:
            rec["state"] = TRUSTED
            rec["promoted_at"] = _now()
    elif rec["state"] == TRUSTED:
        if rec["contradictions"] >= DEMOTE_AFTER:
            rec["state"] = DEMOTED
            rec["demoted_at"] = _now()

    entry = {
        "source_id": source_id, "axis": rec.get("axis"), "event": event,
        "ok": ok, "value": value, "peer": peer, "reason": reason,
        "clean_streak": rec["clean_streak"],
        "contradictions": rec["contradictions"],
        "cv": rec["cv"], "chaotic": chaotic,
        "state_before": was, "state_after": rec["state"],
    }
    if was != rec["state"]:
        entry["transition"] = f"{was} -> {rec['state']}"
        entry["why"] = (
            f"{rec['clean_streak']} clean observations, cv={rec['cv']}"
            if rec["state"] == TRUSTED else
            f"{rec['contradictions']} contradictions")
        print(f"[LIFECYCLE] {source_id}: {entry['transition']} — {entry['why']}")
    log(entry, ledger)

    if own:
        save(st)
    return rec


def state_of(source_id: str, state: dict | None = None) -> str:
    st = state if state is not None else load()
    return (st.get(source_id) or {}).get("state", CANDIDATE)


def is_trusted(source_id: str, state: dict | None = None) -> bool:
    return state_of(source_id, state) == TRUSTED


def summary(state: dict | None = None) -> dict:
    st = state if state is not None else load()
    out = {CANDIDATE: 0, TRUSTED: 0, DEMOTED: 0}
    for rec in st.values():
        if isinstance(rec, dict) and rec.get("state") in out:
            out[rec["state"]] += 1
    return out


def _selftest() -> int:
    print("core/source_lifecycle.py --selftest")
    ok = True
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        led = pathlib.Path(tmp) / "ledger.jsonl"

        st = {}
        for i in range(PROMOTE_AFTER):
            observe("steady", axis="AX", ok=True, value=100 + i,
                    state=st, ledger=led)
        checks = [("a steady source promotes", state_of("steady", st) == TRUSTED)]

        st2 = {}
        for v in (1, 900, 3, 700, 2, 850, 4):
            observe("chaotic", axis="AX", ok=True, value=v, state=st2, ledger=led)
        checks.append(("a chaotic source never promotes",
                       state_of("chaotic", st2) == CANDIDATE))

        st3 = {}
        for i in range(PROMOTE_AFTER):
            observe("faller", axis="AX", ok=True, value=100, state=st3, ledger=led)
        promoted = state_of("faller", st3) == TRUSTED
        for _ in range(DEMOTE_AFTER):
            observe("faller", axis="AX", ok=True, value=500, peer=100,
                    state=st3, ledger=led)
        checks += [("it promoted first", promoted),
                   ("3 contradictions demote", state_of("faller", st3) == DEMOTED)]

        st4 = {}
        for i in range(PROMOTE_AFTER - 1):
            observe("flaky", axis="AX", ok=True, value=100, state=st4, ledger=led)
        observe("flaky", axis="AX", ok=False, reason="HTTP 503", state=st4, ledger=led)
        checks.append(("a refusal breaks the streak but does not contradict",
                       st4["flaky"]["clean_streak"] == 0
                       and st4["flaky"]["contradictions"] == 0))

        rows = [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines() if l.strip()]
        checks.append(("every observation is in the ledger", len(rows) >= 20))
        checks.append(("transitions carry their evidence",
                       any(r.get("transition") and r.get("why") for r in rows)))

    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
