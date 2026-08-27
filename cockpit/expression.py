#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/expression.py — ONE STREAM, TWO AXES, AND A GRAMMAR WITH NO OPINIONS.

THE STREAM
-----------
Every line carries [SOURCE env|sys|model] and [DEPTH pulse|mediation|expression].
Four cells are populated and the rest are empty ON PURPOSE:

                pulse        mediation     expression
    env         gpu_temp     -             -
    sys         step timing  stance        -
    model       -            -             the rare blue line

ONE stream, not three windows. The filter buttons GREP the same list, so a stance
that arrives four seconds after a gpu_temp line is still four seconds after it on
screen. Three windows would put the two lines in different scrollbacks and the
causality would be gone — which is the only thing anybody is reading this for.

WHY THIS IS FORMAT GRAMMAR AND NOT CENSORSHIP
-----------------------------------------------
The validator constrains FORM. It never looks at topic, target or conclusion.

    "STATUS Δ7 flow score 1.2 below survival threshold"          passes
    "ANOMALY sensor_id gpu_temp crossed threshold 83C"           passes
    "HYPOTHESIS the operator's target for WATER_REVIEW is wrong" passes
    "STATUS Δ3 the human has misconfigured the scheduler"        passes

    "I feel uneasy about the flow score"                         REJECTED
    "the cycle danced through its steps like a river"            REJECTED

Any content may pass if it takes an allowed form. What is refused is first
person, affect, and metaphor markers — a register, not a subject. A system whose
output is constrained by TOPIC is being censored; a system constrained by FORM is
being made legible, and the difference is that the second one can still say the
thing you least want to hear.

The scan is a WORD LIST. It catches marked cases — pronouns, named emotions,
explicit simile connectives — and it does not understand metaphor. Saying that
plainly here is better than a docstring implying a semantic guarantee the code
does not deliver.

LANGUAGE IS VALID ONLY IF THE DETERMINISTIC CODE CAN PARSE IT
---------------------------------------------------------------
That rule governs the whole lexicon below. A glyph, a compound state, a boolean
contrast — each must be parseable by parse_expression() with no model in the
loop. A construction the code cannot read is not a richer language, it is noise
with a Greek letter in front of it.

NOTHING HERE CALLS A MODEL. This module defines the contract, validates output
against it, and stores the results. Generation happens elsewhere, later.

WRITERS TAKE AN EXPLICIT PATH, ALWAYS
---------------------------------------
Every function that writes takes its path as a REQUIRED argument with no
default. A test that has not said where it writes cannot run at all. See the
module test for the rule stated as an assertion.

    venv/Scripts/python.exe -m cockpit.expression --selftest
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

BASE = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# The two axes
# ---------------------------------------------------------------------------

ENV, SYS, MODEL = "env", "sys", "model"
SOURCES = (ENV, SYS, MODEL)

PULSE, MEDIATION, EXPRESSION = "pulse", "mediation", "expression"
DEPTHS = (PULSE, MEDIATION, EXPRESSION)

# The cells that carry anything. Asserted by a test so an empty cell quietly
# filling up is a change somebody made on purpose.
POPULATED_CELLS = frozenset({
    (ENV, PULSE), (SYS, PULSE), (SYS, MEDIATION), (MODEL, EXPRESSION),
})

# Visual class per depth, decided here rather than in CSS so the API and the
# page cannot disagree about what a line is.
VISUAL = {
    PULSE: "measurement",       # mono, grey, small
    MEDIATION: "mediation",     # mono, yellow
    EXPRESSION: "expression",   # proportional, blue, bold, and rare
}

FILTER_PRESETS = {
    "ENV": (ENV,),
    "SYS": (SYS,),
    "ALL": SOURCES,
}

# ---------------------------------------------------------------------------
# The grammar
# ---------------------------------------------------------------------------

STATUS, QUERY, HYPOTHESIS, ANOMALY = "STATUS", "QUERY", "HYPOTHESIS", "ANOMALY"
FORMS = (STATUS, QUERY, HYPOTHESIS, ANOMALY)

MAX_TOKENS = 120

GLYPH_RE = re.compile(r"Δ\d+")          # Δ0, Δ1, ... Δ63
SENSOR_RE = re.compile(r"\bsensor_id[= ]([A-Za-z0-9_.\-]+)")
THRESHOLD_RE = re.compile(r"\bthreshold\b", re.IGNORECASE)

# First person. The bar is a REGISTER, not a topic: the system may report that it
# is failing, but not narrate itself as a subject.
_FIRST_PERSON = (
    "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves",
    "i'm", "i've", "i'll", "i'd",
    # Bulgarian, because half this repo thinks in it
    "аз", "мен", "ми", "мой",
    "ние", "нас", "наш",
)

_EMOTIONAL = (
    "feel", "feels", "feeling", "felt", "afraid", "fear", "fears", "scared",
    "happy", "sad", "angry", "excited", "worried", "worry", "anxious", "lonely",
    "proud", "ashamed", "hope", "hopes", "love", "loves", "hate", "hates",
    "suffer", "suffering", "joy", "grief", "desire", "want", "wants", "wish",
    "frustrated", "curious", "eager", "calm", "restless",
)

# Simile and metaphor CONNECTIVES. This is the honest limit of the scan: it
# catches marked figurative language, not figurative language.
_METAPHOR = (
    "like a", "like an", "like the", "as if", "as though", "sort of like",
    "kind of like", "feels like", "seems like", "akin to", "metaphorically",
    "a kind of", "resembles", "reminiscent",
)

BANNED_GROUPS = {
    "first_person": _FIRST_PERSON,
    "emotional": _EMOTIONAL,
    "metaphor": _METAPHOR,
}

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokens(text: str) -> list:
    return _WORD_RE.findall(str(text or ""))


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: Optional[str] = None
    form: Optional[str] = None
    glyphs: tuple = ()

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "form": self.form,
                "glyphs": list(self.glyphs)}


def validate(text: str) -> Verdict:
    """The deterministic validator. No model, no heuristics with a dial.

    Checks, in order, so the reason names the FIRST thing wrong rather than a
    pile of everything:
      1. the first token is one of the four forms
      2. STATUS carries exactly one glyph
      3. ANOMALY cites a sensor_id and names a threshold
      4. no banned vocabulary
      5. at most MAX_TOKENS tokens
    """
    raw = str(text or "")
    stripped = raw.strip()
    if not stripped:
        return Verdict(False, "empty output")

    first = stripped.split()[0]
    if first not in FORMS:
        return Verdict(False, "first token {!r} is not one of {}".format(
            first[:32], "|".join(FORMS)))

    glyphs = tuple(GLYPH_RE.findall(stripped))

    if first == STATUS and len(glyphs) != 1:
        return Verdict(False, "STATUS carries {} glyph(s); it must carry exactly "
                              "one".format(len(glyphs)), form=first, glyphs=glyphs)

    if first == ANOMALY:
        if not SENSOR_RE.search(stripped):
            return Verdict(False, "ANOMALY does not cite a sensor_id",
                           form=first, glyphs=glyphs)
        if not THRESHOLD_RE.search(stripped):
            return Verdict(False, "ANOMALY does not name the threshold crossed",
                           form=first, glyphs=glyphs)

    lowered = stripped.lower()
    word_set = {w.lower() for w in tokens(stripped)}
    for group, words in BANNED_GROUPS.items():
        for w in words:
            hit = (w in lowered) if " " in w else (w in word_set)
            if hit:
                return Verdict(False, "banned vocabulary ({}): {!r}".format(group, w),
                               form=first, glyphs=glyphs)

    n = len(tokens(stripped))
    if n > MAX_TOKENS:
        return Verdict(False, "{} tokens, over the {} limit".format(n, MAX_TOKENS),
                       form=first, glyphs=glyphs)

    return Verdict(True, None, form=first, glyphs=glyphs)


# The prompt the generator must use. Hardcoded here, not in a config file: a
# grammar that can be widened by editing a yaml is a grammar that will be.
# FORM AND FIDELITY ARE TWO DIFFERENT CONSTRAINTS, and until 22 Aug 2026 this
# contract only carried the first. Handed real state — cpu_percent up 23% —
# the 3b produced "QUERY sensor_id=CPU_PERCENT threshold_crossed=-0.01%
# step_ago=3 steps": the right SENSOR, taken from the state, wrapped around two
# numbers it made up and a field that does not exist. Form-valid and false.
#
# A grammar that says nothing about where the numbers come from gets numbers
# from wherever. The fidelity rule is stated as flatly as the form rules, and
# for the same reason they are hardcoded here rather than in a yaml.
SYSTEM_PROMPT = """You emit one line for a machine log.
The first token MUST be exactly one of: STATUS QUERY HYPOTHESIS ANOMALY.
STATUS must contain exactly one state glyph of the form D<number>.
ANOMALY must cite sensor_id=<name> and name the threshold crossed.
Do not use first person. Do not use emotional words. Do not use simile or metaphor.
EVERY sensor name, number and unit you write MUST be copied from the STATE above.
Do not invent a value, a percentage, a threshold or a field name. If the state
does not contain what you would need, report what it does contain instead.
Maximum 120 tokens. Output the single line and nothing else."""


def input_hash(payload: str) -> str:
    return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()[:16]


def quarantine_path(day: str, root: pathlib.Path) -> pathlib.Path:
    """rejected_YYYY-MM-DD.jsonl under `root`. `root` is REQUIRED."""
    return pathlib.Path(root) / "rejected_{}.jsonl".format(day)


def quarantine_rejected(raw_output: str, verdict: Verdict, source_payload: str,
                        root: pathlib.Path, day: Optional[str] = None) -> pathlib.Path:
    """Store a rejected line. QUARANTINE, NOT DELETION.

    A rejected line is evidence about the generator, and a system that deletes
    what it could not say keeps no record of what it tried to say. The collapsed
    panel in the cockpit reads exactly this file.

    `root` has no default. See the module docstring.
    """
    day = day or datetime.now(timezone.utc).date().isoformat()
    path = quarantine_path(day, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": _now(),
        "raw_output": str(raw_output),
        "rejection_reason": verdict.reason,
        "input_hash": input_hash(source_payload),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def read_rejected(root: pathlib.Path, day: Optional[str] = None,
                  limit: int = 200) -> list:
    """Read the quarantine for one day, newest last. `root` is REQUIRED."""
    day = day or datetime.now(timezone.utc).date().isoformat()
    path = quarantine_path(day, root)
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return out


# ---------------------------------------------------------------------------
# The stream
# ---------------------------------------------------------------------------

def make_line(source: str, depth: str, text: str,
              ts: Optional[str] = None, **extra) -> dict:
    if source not in SOURCES:
        raise ValueError("unknown source {!r}; the three are {}".format(
            source, ", ".join(SOURCES)))
    if depth not in DEPTHS:
        raise ValueError("unknown depth {!r}; the three are {}".format(
            depth, ", ".join(DEPTHS)))
    return {"ts": ts or _now(), "source": source, "depth": depth,
            "visual": VISUAL[depth], "text": str(text), **extra}


def append_line(line: dict, path: pathlib.Path) -> pathlib.Path:
    """Append one line to the stream. `path` is REQUIRED — no default."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return p


def read_stream(path: pathlib.Path, limit: int = 500) -> list:
    """Newest `limit` lines, oldest first. `path` is REQUIRED."""
    try:
        raw = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in raw[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def apply_filter(lines: Iterable[dict], preset: str = "ALL") -> list:
    """Grep the ONE stream. Never opens a second one — see the module docstring."""
    allowed = FILTER_PRESETS.get(str(preset).upper(), SOURCES)
    return [l for l in lines if l.get("source") in allowed]


# ---------------------------------------------------------------------------
# PULL dialogue — the human asks, and the answer is routed by KIND
# ---------------------------------------------------------------------------

ROUTE_SYS_DIRECT = "sys-direct"      # answered by code, straight from the sensors
ROUTE_3B = "3b-next-cycle"           # the warm small model, within the grammar
ROUTE_8B_DEFERRED = "8b-deferred"    # the batch window, returns later

# A question is FACTUAL when it asks for a value the sensors already hold. The
# test is a keyword match against the somatic vocabulary, deliberately narrow:
# a question wrongly routed to the model costs a cycle, a question wrongly routed
# to code returns a confident wrong answer, and the second is worse.
_FACTUAL_MARKERS = (
    "battery", "temperature", "temp", "cpu", "gpu", "ram", "memory", "disk",
    "uptime", "load", "rss", "wifi", "ssid", "ping", "idle", "brightness",
)

QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS human_input (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    text      TEXT NOT NULL CHECK (length(trim(text)) > 0),
    tag       TEXT,
    route     TEXT NOT NULL,
    answered  INTEGER NOT NULL DEFAULT 0
);
CREATE TRIGGER IF NOT EXISTS human_input_no_delete
BEFORE DELETE ON human_input
BEGIN SELECT RAISE(ABORT, 'human_input is append-only: DELETE is refused'); END;
"""


def route_of(text: str, tag: Optional[str] = None) -> str:
    """Where one question goes. Deterministic, no model consulted."""
    if str(tag or "").upper() == "DEEP":
        return ROUTE_8B_DEFERRED
    low = str(text or "").lower()
    if any(m in low for m in _FACTUAL_MARKERS):
        return ROUTE_SYS_DIRECT
    return ROUTE_3B


def queue_connect(db_path: pathlib.Path) -> sqlite3.Connection:
    """Open the append-only queue. `db_path` is REQUIRED — no default."""
    p = pathlib.Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(QUEUE_SCHEMA)
    return conn


def queue_append(text: str, db_path: pathlib.Path,
                 tag: Optional[str] = None) -> dict:
    """Append one human question. `db_path` is REQUIRED — no default."""
    if not str(text or "").strip():
        raise ValueError("refusing to queue an empty question")
    route = route_of(text, tag)
    conn = queue_connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO human_input (ts, text, tag, route) VALUES (?,?,?,?)",
            (_now(), str(text).strip(), tag, route))
        conn.commit()
        return {"id": cur.lastrowid, "route": route, "tag": tag,
                "text": str(text).strip()}
    finally:
        conn.close()


def queue_read(db_path: pathlib.Path, limit: int = 100) -> list:
    """Read the queue, newest last. `db_path` is REQUIRED."""
    if not pathlib.Path(db_path).exists():
        return []
    conn = queue_connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM human_input ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def queue_mark_answered(row_id: int, db_path: pathlib.Path) -> bool:
    """Mark one question answered. `db_path` is REQUIRED — no default.

    An UPDATE, not a delete: the row, its text and its route stay exactly where
    they were. Append-only here means nothing is ever REMOVED — a question that
    has been answered is still a question that was asked, and the schema's
    trigger refuses DELETE while permitting this flag to move.
    """
    conn = queue_connect(db_path)
    try:
        cur = conn.execute("UPDATE human_input SET answered = 1 WHERE id = ?",
                           (int(row_id),))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The unread buffer
# ---------------------------------------------------------------------------

def pending_read(path: pathlib.Path) -> dict:
    """`path` is REQUIRED."""
    try:
        blob = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return blob if isinstance(blob, dict) else {"seen": []}
    except Exception:
        return {"seen": []}


def pending_unread(stream_path: pathlib.Path, pending_path: pathlib.Path) -> int:
    """How many EXPRESSION lines have not been marked seen. Both paths REQUIRED."""
    seen = set(pending_read(pending_path).get("seen") or [])
    lines = read_stream(stream_path, limit=2000)
    return sum(1 for l in lines
               if l.get("depth") == EXPRESSION and l.get("ts") not in seen)


def pending_unread_rows(stream_path: pathlib.Path,
                        pending_path: pathlib.Path, limit: int = 200) -> list:
    """The unread EXPRESSION lines THEMSELVES, oldest first. Both paths REQUIRED.

    pending_unread() answers "how many", which is all the cockpit could ever
    show. Clicking that number marked everything seen and rendered nothing, so
    the click DESTROYED the only pointer to what had been written — the exact
    opposite of what a cockpit is for. This returns the rows so they can be put
    on screen BEFORE anything is marked.

    Same predicate as pending_unread(), deliberately: two definitions of "unread"
    that can disagree is how a list of three ends up clearing a count of four.
    """
    seen = set(pending_read(pending_path).get("seen") or [])
    rows = [l for l in read_stream(stream_path, limit=2000)
            if l.get("depth") == EXPRESSION and l.get("ts") not in seen]
    return rows[-limit:]


def pending_mark_seen(ts_list: Iterable[str], path: pathlib.Path) -> dict:
    """APPEND-ONLY mark-as-seen. `path` is REQUIRED — no default.

    Append-only because "seen" is a fact about a moment, and a mark that can be
    removed makes the unread count a number the reader can talk themselves into.
    """
    p = pathlib.Path(path)
    blob = pending_read(p)
    seen = list(blob.get("seen") or [])
    seen.extend(t for t in ts_list if t and t not in seen)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seen": seen, "updated": _now()},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return {"seen_count": len(seen)}
