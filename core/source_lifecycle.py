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

# ── BOOTSTRAP: TRUST THAT WAS ENTERED, NOT EARNED — AND NOW EXPIRES ──────────
#
# Measured 13 Sep 2026: of 20 TRUSTED sources, 18 carry clean_streak 0 and
# cv 0.000. They did not pass the gate below; they were written in as trusted.
# Only four sources in the whole register have ever accumulated a streak.
#
# THE ENTERED TRUST IS NOT DELETED, and that decision is the point. Deleting it
# leaves twenty candidates and no criterion for any of them — the register would
# lose what little it knows in exchange for tidiness. Instead the grant becomes a
# CONTRACT WITH AN END DATE: who granted it, when, on what grounds, and until
# when. Unrenewed, it lapses to CANDIDATE automatically, and the source then asks
# for trust by the same means as everyone else — just with a running start.
#
# WHY EXPIRY AND NOT A REVIEW FLAG. A flag needs somebody to look at it, and the
# whole finding of this week is that nobody looks: six machines wrote their own
# failure honestly and none of the sentences were read. An expiry needs nobody.
# The default outcome of being ignored is losing the privilege, which is the only
# direction that is safe when the reader is absent.
#
# THE FORBIDDEN FALLBACK is renewing on activity. A source that keeps answering is
# not thereby trustworthy — 326 of the 435 ledger events are refusals from sources
# that answered something. Renewal is an act with a name attached, or it is expiry.

BOOTSTRAP_DAYS = 90


def _parse_ts(s):
    from datetime import datetime, timezone
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def grant_bootstrap(rec: dict, by: str, because: str,
                    days: int = BOOTSTRAP_DAYS) -> dict:
    """Write the grant onto a record that is TRUSTED without having earned it."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    rec["bootstrap"] = {"granted_at": now.isoformat(), "granted_by": str(by),
                        "because": str(because),
                        "valid_until": (now + timedelta(days=int(days))).isoformat(),
                        "renewals": rec.get("bootstrap", {}).get("renewals", 0)}
    return rec


def bootstrap_expired(rec: dict, now=None) -> bool:
    """True when a grant exists and its date has passed. No grant is not expiry."""
    from datetime import datetime, timezone
    b = (rec or {}).get("bootstrap")
    if not isinstance(b, dict):
        return False
    until = _parse_ts(b.get("valid_until"))
    if until is None:
        return True                      # a grant with no end date is not a grant
    return (now or datetime.now(timezone.utc)) > until


def earned(rec: dict) -> bool:
    """Did this source reach TRUSTED through the gate, rather than by being entered?"""
    return bool(rec) and int(rec.get("clean_streak") or 0) >= PROMOTE_AFTER


def expire_bootstraps(state: dict | None = None, now=None,
                      ledger: pathlib.Path | None = None) -> list:
    """Lapse every expired grant to CANDIDATE. Returns what moved, with reasons.

    A source that has EARNED its streak in the meantime keeps TRUSTED and simply
    loses the grant: the grant was a loan against evidence that has since arrived.
    """
    own = state is None
    st = load() if own else state
    moved = []
    for sid, rec in st.items():
        if not isinstance(rec, dict) or not rec.get("bootstrap"):
            continue
        if not bootstrap_expired(rec, now):
            continue
        if earned(rec):
            rec.pop("bootstrap", None)
            moved.append({"source_id": sid, "was": rec.get("state"),
                          "now": rec.get("state"), "why": "grant lapsed, but the "
                          "streak was earned in the meantime"})
            continue
        was = rec.get("state")
        rec["state"] = CANDIDATE
        rec["demoted_at"] = _now()
        rec["bootstrap_lapsed_at"] = _now()
        moved.append({"source_id": sid, "was": was, "now": CANDIDATE,
                      "why": f"bootstrap granted {rec['bootstrap'].get('granted_at')} "
                             f"expired {rec['bootstrap'].get('valid_until')} unrenewed"})
        log({"source_id": sid, "event": "bootstrap_lapsed",
             "was": was, "now": CANDIDATE,
             "bootstrap": rec.get("bootstrap")}, ledger)
    if own and moved:
        save(st)
    return moved


def backfill_bootstraps(state: dict | None = None, by: str = "unknown",
                        days: int = BOOTSTRAP_DAYS) -> list:
    """Mark every TRUSTED record that never earned its streak as a bootstrap grant.

    WHO granted it is honestly recorded as unknown: the register carries no
    author for these rows, and inventing one would be the same kind of fiction
    the grant itself is. What IS recorded is the evidence that it was entered —
    the streak and the cv at the moment of backfill.
    """
    own = state is None
    st = load() if own else state
    done = []
    for sid, rec in st.items():
        if not isinstance(rec, dict) or rec.get("state") != TRUSTED:
            continue
        if earned(rec) or rec.get("bootstrap"):
            continue
        grant_bootstrap(rec, by, (
            f"entered as TRUSTED before the bootstrap contract existed; at backfill "
            f"clean_streak={rec.get('clean_streak', 0)} cv={rec.get('cv')} "
            f"observations={rec.get('observations', 0)} — it did not pass the gate"),
            days)
        done.append({"source_id": sid, "clean_streak": rec.get("clean_streak", 0),
                     "cv": rec.get("cv"),
                     "valid_until": rec["bootstrap"]["valid_until"]})
    if own and done:
        save(st)
    return done


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


# ── SOURCE CLASSES (22 Aug 2026) ────────────────────────────────────────────
# What KIND of pipeline this source is, recorded at intake so the cockpit's five
# columns can be built without re-guessing it later from a url.
#
# This is NOT the trust ladder and NOT an independence class. The ladder is the
# `state` field below — CANDIDATE -> TRUSTED -> DEMOTED — and it is untouched by
# anything here. The independence classes live in
# config/reporter_independence.json and stay at four. A source class says where
# the numbers physically come from; a source may be PHYSICAL and still be
# DEMOTED, and often should be.
#
# PHYSICAL and SCIENCE are the two added now, because they are the two the
# columns panel cannot infer: a hardware sensor and a peer-reviewed archive look
# like any other url from the outside.
PHYSICAL_CLASS = "physical"      # a sensor this machine can read
SCIENCE_CLASS = "science"        # peer review: arXiv, DOI, journals
OFFICIAL_CLASS = "official"      # international institution aggregating states
NATIONAL_CLASS = "national"      # the state measuring itself
FREE_CLASS = "free"              # press, NGOs, anyone with no seat at the table
UNCLASSED = "unclassed"          # the default. Never inferred to be physical.

SOURCE_CLASSES = (PHYSICAL_CLASS, SCIENCE_CLASS, OFFICIAL_CLASS,
                  NATIONAL_CLASS, FREE_CLASS, UNCLASSED)


def record_for(state: dict, source_id: str, axis: str | None = None,
               source_class: str | None = None) -> dict:
    """The CANDIDATE intake. Creates a record; moves nothing on the ladder.

    `source_class` is written once, on first sight, and then only FILLED IN if
    it was left unclassed — never overwritten. A source that has been recorded
    as PHYSICAL and later arrives tagged FREE is a collision worth noticing, not
    a correction to apply silently, so the first tag stands and the caller can
    compare. An unknown class is stored as `unclassed` rather than rejected: the
    intake refusing rows would lose the source entirely, and `unclassed` is
    exactly the honest answer.
    """
    rec = state.setdefault(source_id, {
        "source_id": source_id, "axis": axis, "state": CANDIDATE,
        "source_class": UNCLASSED,
        "clean_streak": 0, "contradictions": 0,
        "observations": 0, "refusals": 0,
        "recent_values": [], "first_seen": _now(), "history": [],
    })
    if axis and not rec.get("axis"):
        rec["axis"] = axis
    rec.setdefault("source_class", UNCLASSED)
    if source_class and rec["source_class"] == UNCLASSED:
        rec["source_class"] = (source_class if source_class in SOURCE_CLASSES
                               else UNCLASSED)
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
