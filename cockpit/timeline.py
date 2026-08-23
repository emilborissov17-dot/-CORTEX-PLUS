#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/timeline.py — THE SYSTEM ALREADY TALKS. THIS IS WHERE IT IS READ.

THE MISTAKE THIS UNDOES
------------------------
The expression window was built as a PRODUCER: one new channel, one rare blue
line, a thin voice of its own. Meanwhile the system talks all day and all night
in six other places — it writes a plan every cycle, a stance at every step, a
debrief at every phase, an autopsy when it dies, a decision when it reconsiders,
a report when it finishes — and every one of those went to Telegram and to a
file, and to no window. So the cockpit showed a trickle beside a torrent, and
the torrent was legible only on a phone, one message at a time, out of order.

This module does not produce anything. It READS what is already on disk and
merges it into ONE timeline, ordered by the timestamp each writer stamped, so a
stance four seconds before a phase debrief is four seconds before it on screen.
That ordering is the only reason anybody reads a stream at all.

Telegram becomes a notification that these lines exist. It stops being the only
place they exist.

WHERE EACH ROW COMES FROM, AND WHAT ITS REFLEXIVITY MEANS
-----------------------------------------------------------
cockpit/somatic.py fixed reflexivity 0 as "nothing interpreted this"; it "rises
only when the 3b compresses a reading" — when something INTERPRETED it. The
ladder is extended here to three rungs, declared per source in SOURCES below
rather than guessed per row:

    0   a measurement. No model touched it.
    1   one model pass over a state: the day's plan, a step stance, the
        expression line. The system talking ABOUT the world it just read.
    2   the system judging its own earlier output or its own run: a phase
        debrief, a cycle review, an autopsy, a reconsider decision, a mirror
        read. The system talking about ITSELF.

A source that is not on disk is REPORTED, with its path, not dropped. "No dream
last night" and "the dream reader is broken" must not look the same.

CYCLE SCOPING
--------------
memory/existence_ledger.jsonl gives a cycle its CYCLE_STARTED and CYCLE_FINISHED
timestamps, and every source here stamps UTC. So a cycle is a time window, and
each row either falls inside it or does not. phase_debriefs/ is additionally
filed under the cycle_id, and that is used directly — a directory name is a
stronger claim than a timestamp comparison.

NOTHING HERE WRITES. Not one path in this module is opened for writing.

    venv/Scripts/python.exe -m cockpit.timeline                    # last sealed
    venv/Scripts/python.exe -m cockpit.timeline <cycle_id>
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

MEM = BASE / "memory"

# The one stream the cockpit itself writes (pulse, mediation, the model line).
EXPRESSION_STREAM = MEM / "expression_stream.jsonl"
# The autonomic pulse: body/mind/spirit every few minutes, cycle or no cycle.
AUTONOMIC_PULSE = MEM / "pulse_stream.jsonl"
BRAIN_STEP_LOG = MEM / "brain_step_log.jsonl"
BRAIN_JOURNAL = MEM / "brain_journal.jsonl"
PHASE_DEBRIEFS = MEM / "phase_debriefs"
RECONSIDER_HISTORY = MEM / "reconsider_history.jsonl"
LEDGER = MEM / "existence_ledger.jsonl"
DREAMS = BASE / "experiments" / "dreams"

MEASUREMENT, INTERPRETATION, SELF_JUDGEMENT = 0, 1, 2

REFLEXIVITY_MEANING = {
    MEASUREMENT: "a measurement; no model touched it",
    INTERPRETATION: "one model pass over a state the system just read",
    SELF_JUDGEMENT: "the system judging its own output or its own run",
}

# Journal kinds that belong on the timeline, and what each one IS.
# phase_debrief is deliberately absent: it is read from phase_debriefs/, which
# is filed by cycle_id and is the authoritative copy. Reading both would put
# every debrief on the timeline twice.
JOURNAL_KINDS = {
    "cycle_plan":    ("rationale", INTERPRETATION,
                      "the day's plan: focus, suspicion, its own test"),
    "autopsy":       ("autopsy", SELF_JUDGEMENT, "why the cycle died"),
    "reconsider":    ("reconsider", SELF_JUDGEMENT,
                      "carry on, or recompute one step"),
    "cycle_review":  ("digest", SELF_JUDGEMENT,
                      "did the test it set itself come true"),
    "cycle_report":  ("digest", SELF_JUDGEMENT, "the report to the human"),
    "mirror_read":   ("digest", SELF_JUDGEMENT, "what it saw in the mirror"),
    "constellation": ("digest", SELF_JUDGEMENT, "all the indicators read together"),
}


def _rel(path: pathlib.Path) -> str:
    """Repo-relative where possible, absolute otherwise. Never raises.

    relative_to() throws for anything outside the repo, which is every path a
    test hands in — and a status reader that raises on an unfamiliar path is a
    status reader that cannot report the one case it exists for.
    """
    try:
        return str(pathlib.Path(path).relative_to(BASE))
    except ValueError:
        return str(path)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _jsonl(path: pathlib.Path, limit: Optional[int] = None) -> list:
    """Read a .jsonl, skipping torn lines. Never raises."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if limit:
        raw = raw[-limit:]
    out = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _text(value, cap: int = 400) -> str:
    """A row's words, however that writer chose to store them.

    Several writers put a JSON blob in `summary`. Rendering the blob verbatim is
    what makes a stream unreadable, so the known fields are pulled out in a
    declared order and the rest is dropped rather than dumped.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                value = json.loads(stripped)
            except ValueError:
                # core/brain.remember() stores summary[:600], so a long verdict
                # arrives as TRUNCATED JSON and never parses. Rendering the raw
                # braces is what made the day's plan the least readable row on
                # a timeline built to be read, so the pairs are pulled out with
                # a scan instead of being given up on.
                pairs = re.findall(r'"([A-Za-z_]+)"\s*:\s*"([^"]*)"', stripped)
                if pairs:
                    return " · ".join(
                        "{}: {}".format(k, v) for k, v in pairs)[:cap]
                return stripped[:cap]
        else:
            return stripped[:cap]
    if isinstance(value, dict):
        prefer = ("what", "verdict", "opening", "focus", "why", "cause",
                  "action", "saw", "reading", "note", "text", "summary",
                  "risk", "success_test", "expect")
        bits = []
        for key in prefer:
            v = value.get(key)
            if v not in (None, "", [], {}):
                bits.append("{}: {}".format(key, v))
            if sum(len(b) for b in bits) > cap:
                break
        if not bits:
            bits = ["{}: {}".format(k, v) for k, v in list(value.items())[:3]]
        return " · ".join(bits)[:cap]
    return str(value)[:cap]


# ---------------------------------------------------------------------------
# Cycle bounds
# ---------------------------------------------------------------------------

def cycle_window(cycle_id: Optional[str] = None,
                 ledger_path: pathlib.Path = LEDGER) -> dict:
    """(cycle_id, started, finished) for a cycle, from the existence ledger.

    `finished` is None for a cycle still running, which the callers read as
    "open-ended" rather than "empty".
    """
    rows = _jsonl(ledger_path)
    if cycle_id is None:
        for row in reversed(rows):
            if str(row.get("event", "")).upper() == "CYCLE_FINISHED":
                cycle_id = row.get("cycle_id")
                break
    started = finished = None
    for row in rows:
        if row.get("cycle_id") != cycle_id:
            continue
        event = str(row.get("event", "")).upper()
        if event == "CYCLE_STARTED":
            started = row.get("ts")
        elif event in ("CYCLE_FINISHED", "CYCLE_DIED", "CYCLE_KILLED"):
            finished = row.get("ts")
    return {"cycle_id": cycle_id, "started": started, "finished": finished}


def _inside(ts, started, finished) -> bool:
    if not ts:
        return False
    if started and str(ts) < str(started):
        return False
    if finished and str(ts) > str(finished):
        return False
    return True


# ---------------------------------------------------------------------------
# The readers — one per stream, each returning rows in a common shape
# ---------------------------------------------------------------------------

def _row(ts, source: str, reflexivity: int, text: str, where: str,
         **extra) -> dict:
    return {"ts": ts, "source": source, "reflexivity": reflexivity,
            "text": text, "where": where, **extra}


def read_cockpit_stream(path: pathlib.Path = EXPRESSION_STREAM) -> list:
    """Pulse, mediation and the model's own line. Depth decides which is which."""
    out = []
    for line in _jsonl(path):
        depth = line.get("depth")
        if depth == "expression":
            src, refl = "expression", INTERPRETATION
        elif depth == "mediation":
            src, refl = "mediation", MEASUREMENT
        else:
            src, refl = "pulse", MEASUREMENT
        out.append(_row(line.get("ts"), src, refl, line.get("text", ""),
                        path.name, kind=line.get("kind"),
                        sensor=line.get("sensor"), band=line.get("band"),
                        visual=line.get("visual")))
    return out


def read_autonomic_pulse(path: pathlib.Path = AUTONOMIC_PULSE,
                         tail: int = 4000) -> list:
    """The pulse that runs whether or not anyone has the cockpit open.

    memory/expression_stream.jsonl only has pulse lines while the page is being
    polled, so for a 3am cycle it is empty. This one samples body, mind and
    spirit every few minutes regardless, which is what makes it the pulse a
    NIGHT timeline actually has between its debriefs.
    """
    out = []
    for line in _jsonl(path, limit=tail):
        body = line.get("body") or {}
        spirit = line.get("spirit") or {}
        nec = line.get("necessity") or {}
        text = "ram {}% · disk {} GB · ollama {} · composite {} · necessity {}".format(
            body.get("ram_pct"), body.get("disk_gb"),
            "up" if body.get("ollama_alive") else "DOWN",
            spirit.get("composite"), nec.get("score"))
        out.append(_row(line.get("ts"), "pulse", MEASUREMENT, text, path.name,
                        kind="autonomic"))
    return out


def read_stances(path: pathlib.Path = BRAIN_STEP_LOG, tail: int = 4000) -> list:
    """One stance per step: what it expects, and how it read the step before."""
    out = []
    for line in _jsonl(path, limit=tail):
        text = "[{}] {} — {}".format(line.get("step"), line.get("stance"),
                                     line.get("expect", ""))
        if line.get("prev_note"):
            text += "  (on {}: {})".format(line.get("prev_step"),
                                           str(line["prev_note"])[:120])
        out.append(_row(line.get("ts"), "brain_stance", INTERPRETATION,
                        text[:400], path.name, step=line.get("step"),
                        model=line.get("model")))
    return out


def read_phase_debriefs(cycle_id: Optional[str],
                        root: pathlib.Path = PHASE_DEBRIEFS) -> list:
    """The phase debriefs of ONE cycle, from the directory filed under its id.

    A directory name is a stronger claim than a timestamp comparison, so when a
    cycle_id is given this reads only that cycle's folder. The folder name is
    the cycle_id with ':' and '+' replaced — the same mangling supervisor uses.
    """
    out = []
    if not root.is_dir():
        return out
    wanted = None
    if cycle_id:
        wanted = "".join(c if c.isalnum() or c in "-_." else "_"
                         for c in str(cycle_id))
    for folder in sorted(root.iterdir()):
        if not folder.is_dir():
            continue
        if wanted and folder.name != wanted:
            continue
        for blob_path in sorted(folder.glob("*.json")):
            try:
                blob = json.loads(blob_path.read_text(encoding="utf-8",
                                                      errors="replace"))
            except Exception:
                continue
            said = {}
            for attempt in (blob.get("attempt_log") or []):
                if isinstance(attempt, dict) and attempt.get("said"):
                    said = attempt["said"]
            text = "{} {} — {}".format(
                blob.get("phase"),
                "accepted" if blob.get("accepted") else "REJECTED",
                _text(said or blob.get("rejected_because") or "", 300))
            out.append(_row(blob.get("ts"), "phase_debrief", SELF_JUDGEMENT,
                            text, "phase_debriefs/{}".format(folder.name),
                            phase=blob.get("phase"),
                            accepted=bool(blob.get("accepted")),
                            model=blob.get("model")))
    return out


def read_journal(path: pathlib.Path = BRAIN_JOURNAL, tail: int = 4000) -> list:
    """The plan, the autopsy, the reconsider, the report — one file, many kinds."""
    out = []
    for line in _jsonl(path, limit=tail):
        spec = JOURNAL_KINDS.get(line.get("kind"))
        if not spec:
            continue
        source, refl, _why = spec
        out.append(_row(line.get("ts"), source, refl,
                        _text(line.get("summary")), path.name,
                        kind=line.get("kind")))
    return out


def read_reconsider(path: pathlib.Path = RECONSIDER_HISTORY) -> list:
    """The reconsider file. Its rows also reach the journal, so ts dedupes them."""
    out = []
    for line in _jsonl(path):
        text = "{} {} — {}".format(line.get("action"),
                                   line.get("replayed") or line.get("step") or "",
                                   str(line.get("why", ""))[:280])
        out.append(_row(line.get("ts"), "reconsider", SELF_JUDGEMENT,
                        text.strip(), path.name, kind="reconsider"))
    return out


def read_dreams(root: pathlib.Path = DREAMS) -> list:
    """The night's dream, one markdown file per day. Its ts is the file's mtime."""
    from datetime import datetime, timezone
    out = []
    if not root.is_dir():
        return out
    for md in sorted(root.glob("2*.md")):
        try:
            body = md.read_text(encoding="utf-8", errors="replace")
            ts = datetime.fromtimestamp(md.stat().st_mtime,
                                        timezone.utc).isoformat()
        except OSError:
            continue
        out.append(_row(ts, "dream", INTERPRETATION,
                        " ".join(body.split())[:400], _rel(md),
                        kind="dream"))
    return out


# Declared here so a source that said nothing is REPORTED rather than absent.
# Order is the order the module docstring lists them in. `feeds` names the row
# sources this file can produce, so "the file is there and it contributed
# nothing to THIS cycle" is a statement the status can make.
SOURCES = (
    ("pulse (autonomic)", AUTONOMIC_PULSE, MEASUREMENT, ("pulse",)),
    ("pulse / expression / mediation", EXPRESSION_STREAM, MEASUREMENT,
     ("pulse", "expression", "mediation")),
    ("brain_stance", BRAIN_STEP_LOG, INTERPRETATION, ("brain_stance",)),
    ("phase_debrief", PHASE_DEBRIEFS, SELF_JUDGEMENT, ("phase_debrief",)),
    ("rationale / autopsy / reconsider / digest", BRAIN_JOURNAL,
     SELF_JUDGEMENT, ("rationale", "autopsy", "reconsider", "digest")),
    ("reconsider", RECONSIDER_HISTORY, SELF_JUDGEMENT, ("reconsider",)),
    ("dream", DREAMS, INTERPRETATION, ("dream",)),
)


def sources_status(by_where: Optional[dict] = None) -> list:
    """Which declared sources are on disk, and which of them said anything.

    THREE STATES, NOT TWO. A source can be missing (nobody has ever written it),
    present and silent for this cycle (nothing happened, or nothing was read),
    or present and speaking. Collapsing the middle one into either of the others
    is how "no dream last night" and "the dream reader is broken" end up looking
    the same on a page built to tell them apart.
    """
    by_where = by_where or {}
    out = []
    for name, path, refl, feeds in SOURCES:
        exists = path.exists()
        rows = by_where.get(path.name, 0)
        if not exists:
            state, why = "missing", "nothing has ever written {}".format(path.name)
        elif rows:
            state, why = "speaking", None
        else:
            state, why = "silent", ("on disk, but contributed no row inside "
                                    "this cycle's window")
        out.append({"source": name, "path": _rel(path),
                    "exists": exists, "state": state, "rows": rows,
                    "feeds": list(feeds), "reflexivity": refl, "why": why})
    return out


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------

def collect(cycle_id: Optional[str] = None, limit: int = 600,
            include_pulse: bool = True) -> dict:
    """Every stream, merged, ordered by the timestamp its writer stamped."""
    window = cycle_window(cycle_id, LEDGER)
    cid, started, finished = (window["cycle_id"], window["started"],
                              window["finished"])

    # EVERY PATH PASSED EXPLICITLY, not left to a default argument. A default
    # is bound when the function is DEFINED, so a caller that repoints the
    # module constants — every test in test/test_timeline.py, and any future
    # reader of another repo's memory/ — would silently go on reading the live
    # desk while believing it was reading the tree it just built.
    rows = []
    rows += read_stances(BRAIN_STEP_LOG)
    rows += read_journal(BRAIN_JOURNAL)
    rows += read_reconsider(RECONSIDER_HISTORY)
    rows += read_dreams(DREAMS)
    rows += read_phase_debriefs(cid, PHASE_DEBRIEFS)
    if include_pulse:
        rows += read_autonomic_pulse(AUTONOMIC_PULSE)
        rows += read_cockpit_stream(EXPRESSION_STREAM)

    # Phase debriefs come from the cycle's own directory and are in by name; the
    # rest are in by time. A row with no timestamp cannot be placed and is
    # counted rather than guessed at.
    undated = sum(1 for r in rows if not r.get("ts"))
    inside = [r for r in rows
              if r["source"] == "phase_debrief"
              or _inside(r.get("ts"), started, finished)]

    seen, merged = set(), []
    for row in sorted(inside, key=lambda r: str(r.get("ts") or "")):
        key = (str(row.get("ts")), row["source"], row["text"][:80])
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)

    tail = merged[-limit:] if limit else merged
    counts, by_where = {}, {}
    for row in tail:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
        # BY FILE, not by source name: memory/pulse_stream.jsonl and
        # memory/expression_stream.jsonl both produce rows called "pulse", so a
        # count keyed on the name lets a silent file hide behind a busy one.
        where = str(row.get("where", "")).split("/")[0]
        by_where[where] = by_where.get(where, 0) + 1

    return {
        "ts": _now_iso(),
        "cycle_id": cid,
        "started": started,
        "finished": finished,
        "rows": tail,
        "row_count": len(tail),
        "total_before_limit": len(merged),
        "undated_rows_dropped": undated,
        "counts_by_source": counts,
        "reflexivity_meaning": REFLEXIVITY_MEANING,
        "sources": sources_status(by_where),
        "empty_because": (None if tail else
                          "no stream wrote anything inside this cycle's window"),
    }


def render(blob: dict, width: int = 118) -> str:
    """The timeline as lines. One row per line, in the order it happened."""
    out = ["cycle {}  [{} -> {}]".format(blob.get("cycle_id"),
                                         blob.get("started"),
                                         blob.get("finished") or "still running"),
           "{} row(s); by source: {}".format(
               blob.get("row_count"),
               ", ".join("{}={}".format(k, v) for k, v in
                         sorted(blob.get("counts_by_source", {}).items()))),
           ""]
    for row in blob.get("rows", []):
        out.append("{}  r{}  {:<14}  {}".format(
            str(row.get("ts", ""))[11:23], row.get("reflexivity"),
            row.get("source", ""), row.get("text", "")[:width]))
    quiet = [s for s in blob.get("sources", []) if s["state"] != "speaking"]
    if quiet:
        out.append("")
        out.append("sources that said nothing:")
        for s in quiet:
            out.append("  {:<9} {:<42} {}".format(s["state"], s["source"],
                                                  s["why"]))
    return "\n".join(out)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cid = argv[0] if argv else None
    print(render(collect(cid)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
