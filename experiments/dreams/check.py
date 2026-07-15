#!/usr/bin/env python3
"""
experiments/dreams/check.py — the PASS criterion, made mechanical.

Per the (G) lesson and the README: a criterion you cannot mechanically check is a
story you tell afterwards. This closes the measurement loop so a note's verdict is
COMPUTED, not narrated — and so the goalposts cannot quietly move on a day the
output happens to read beautifully.

WHAT "VERIFIABLE" MEANS HERE
----------------------------
The README states the operational test:

    Could this sentence have been written WITHOUT reading the day?

If yes, it is a FAIL, however well it reads. This module approximates that test the
only way code can: a line is VERIFIABLE if it contains a DAY-SPECIFIC ANCHOR —

  * a number that is true of THIS day and would be false of another
    (late_by_hours, the composite score, a cycle duration, a gap count, a RAM
    peak), OR
  * a word that refers to a ledger EVENT that actually happened this day
    (a catch-up, a kill, a stale-lock clear).

Generic prose — "processed data and continued to improve" — contains neither, and
scores zero. That is the intended discrimination.

HONEST ABOUT ITS OWN LIMITS
---------------------------
This is a HEURISTIC AID, not the judge. It can be fooled: a model that parrots a
number into an otherwise-empty sentence gets a point it may not deserve, and a true
line phrased without any anchor gets none. The README's operational test — a human
reading each line against its source — remains the authority. This tool exists to
make the easy cases automatic, flag the borderline ones, and keep a running score
across the 7 days, NOT to replace the read. Bare single digits are deliberately not
treated as anchors: "5 axes" must not pass for the catch-up that was "5.65h late".
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

# The five line labels, in order, as render_note writes them. Kept here so check.py
# can parse a note WITHOUT importing dream.py (each module reads its own inputs; the
# note is the shared artifact between them).
LINE_LABELS = [
    "What happened.",
    "What changed.",
    "What hurt or killed me.",
    "What I learned.",
    "What tomorrow holds.",
]

# Same map as dream.EVENT_CUES. Duplicated intentionally — check.py must be able to
# score a note from another process (the human, a later audit) with no dependency on
# dream.py's module state. If you add an event kind, add it in both places.
EVENT_CUES = {
    "CYCLE_STARTED": ["cycle", "started", "ran", "began", "woke"],
    "CYCLE_FINISHED": ["finished", "completed", "sealed", "done"],
    "CYCLE_KILLED": ["killed", "died", "crashed", "failed", "kill"],
    "MISSED_RUN_CATCHUP": ["catch", "caught", "late", "missed", "behind", "overslept"],
    "LOCK_STALE_CLEARED": ["stale", "lock", "cleared", "power", "corpse"],
    "CATCHUP_SUPPRESSED_BY_HUMAN": ["suppress", "human", "skipped", "marked"],
}

PASS_LINES = 3          # README: >= 3 of 5 lines verifiable => the note passes
PASS_EVENTS = 2         # and it must name >= this many real ledger events of the day


def _number_anchors(facts: dict) -> set[str]:
    """Day-specific numbers a truthful note might quote, as strings.

    Includes a couple of roundings per value (the model may write 5.7 for 5.65).
    Bare integers < 10 are excluded by the caller's matching rule — see _num_in_line.
    """
    anchors: set[str] = set()

    def add(x: Any) -> None:
        try:
            f = float(x)
        except (TypeError, ValueError):
            return
        anchors.add(f"{f:g}")
        anchors.add(f"{round(f, 1):g}")
        anchors.add(f"{round(f, 2):g}")
        anchors.add(f"{int(f)}")

    for ev in facts.get("ledger_events", []):
        for k in ("late_by_hours", "duration_sec"):
            if ev.get(k) is not None:
                add(ev[k])

    if facts.get("goal_score") is not None:
        add(facts["goal_score"])
    if facts.get("goal_delta") is not None:
        add(abs(facts["goal_delta"]))

    pulse = facts.get("pulse") or {}
    c1 = pulse.get("C1_continuity", {}) if isinstance(pulse, dict) else {}
    c4 = pulse.get("C4_cost", {}) if isinstance(pulse, dict) else {}
    for v in (c1.get("samples"), c1.get("awake_hours"),
              c4.get("system_ram_max_pct"), c4.get("daemon_cpu_mean_pct")):
        if v is not None:
            add(v)
    for bucket in ("unexplained_gaps", "daemon_death_gaps"):
        n = len(c1.get(bucket, []) or [])
        if n:
            add(n)

    return anchors


# A number token in the note: integers and decimals, optionally %-suffixed.
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _num_in_line(line: str, anchors: set[str]) -> Optional[str]:
    """Return the first day-specific number appearing in `line`, or None.

    A number counts ONLY if it is >= 10 or has a decimal point. A bare single digit
    ("5 axes", "1 source") is too generic to prove the day — precisely the sort of
    accidental match that would inflate the score. "5.65", "0.55", "1587" are
    specific enough to be false on another day.
    """
    for tok in _NUM_RE.findall(line):
        specific = ("." in tok) or (len(tok) >= 2 and float(tok) >= 10)
        if specific and tok in anchors:
            return tok
    return None


def _event_in_line(line_lc: str, events_today: set[str]) -> Optional[str]:
    """Return the name of a ledger event whose cue-word appears in `line`, else None.

    Only events that ACTUALLY happened this day count — a note that says "cycle
    finished cleanly" on a day with no CYCLE_FINISHED event is not remembering, it is
    guessing, and must not score.
    """
    for name in events_today:
        for cue in EVENT_CUES.get(name, []):
            if re.search(rf"\b{re.escape(cue)}", line_lc):
                return name
    return None


def _parse_note_lines(note: str) -> list[str]:
    """Extract the five body sentences from a rendered note, in order.

    Tolerant of the exact bolding: matches on the label text, returns whatever
    follows it on the line.
    """
    out = []
    for label in LINE_LABELS:
        m = re.search(rf"\*\*{re.escape(label)}\*\*\s*(.*)", note)
        out.append(m.group(1).strip() if m else "")
    return out


def check_note(note: str, facts: dict) -> dict:
    """Score a note against the day it claims to remember.

    Returns a dict with per-line verifiability, the two pass counts, and an overall
    pass/fail. `pass` is True iff >= PASS_LINES lines are anchored AND >= PASS_EVENTS
    distinct real ledger events of the day are named — the README's two conditions.
    """
    lines = _parse_note_lines(note)
    number_anchors = _number_anchors(facts)
    events_today = {ev.get("event") for ev in facts.get("ledger_events", [])
                    if ev.get("event")}

    per_line = []
    events_named: set[str] = set()
    verifiable = 0
    for label, text in zip(LINE_LABELS, lines):
        lc = text.lower()
        num = _num_in_line(text, number_anchors)
        evt = _event_in_line(lc, events_today)
        anchor = None
        if num and evt:
            anchor = f"event {evt} + number {num}"
        elif num:
            anchor = f"number {num}"
        elif evt:
            anchor = f"event {evt}"
        if evt:
            events_named.add(evt)
        is_ver = anchor is not None
        verifiable += int(is_ver)
        per_line.append({"label": label, "text": text,
                         "verifiable": is_ver, "anchor": anchor})

    passed = verifiable >= PASS_LINES and len(events_named) >= PASS_EVENTS
    summary = (f"{verifiable}/5 lines rest on a day-specific anchor; "
               f"{len(events_named)} distinct ledger event(s) named "
               f"({', '.join(sorted(events_named)) or 'none'}).")
    return {
        "lines": per_line,
        "lines_verifiable": verifiable,
        "events_referenced": len(events_named),
        "events_named": sorted(events_named),
        "pass": passed,
        "summary": summary,
    }


def _load_facts_for(day: str) -> dict:
    """Rebuild the day's facts for scoring an already-written note from the CLI."""
    import dream                                   # sibling; CLI-only, not on the hot path
    return dream.gather_facts(dream.Sources(), day)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="score a dream note against its day")
    ap.add_argument("note", help="path to a YYYY-MM-DD.md note")
    ap.add_argument("--date", help="date of the day to score against "
                                   "(default: parsed from the note filename)")
    args = ap.parse_args()

    path = Path(args.note)
    if not path.exists():
        print(f"no such note: {path}")
        raise SystemExit(2)
    note = path.read_text(encoding="utf-8")
    day = args.date or path.stem
    verdict = check_note(note, _load_facts_for(day))

    print(f"NOTE: {path.name}")
    print(verdict["summary"])
    for ln in verdict["lines"]:
        mark = "PASS" if ln["verifiable"] else " ·  "
        anchor = f"   ← {ln['anchor']}" if ln["anchor"] else ""
        print(f"  [{mark}] {ln['label']:<26}{anchor}")
    print(f"\nverifiable lines {verdict['lines_verifiable']}/5 (need >= {PASS_LINES}), "
          f"events named {verdict['events_referenced']} (need >= {PASS_EVENTS})")
    print("VERDICT:", "PASS" if verdict["pass"] else "FAIL")
    raise SystemExit(0 if verdict["pass"] else 1)


if __name__ == "__main__":
    main()
