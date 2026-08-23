#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/reflex.py — THE PRODUCER OF THE RARE BLUE LINE. ONE RETRY, THEN SILENCE.

WHEN IT SPEAKS
---------------
At each phase boundary and once at cycle end — about 8 calls per cycle, never
more, enforced by a counter rather than by intention. Plus answers to items in
human_input_queue. That budget is the point: an expression line is rare because
rarity is what makes it worth reading, and a producer that could fire per step
would fill the window with the same voice the pulse lines already carry.

WHAT IT IS GIVEN
-----------------
    the phase's report
    the current glyph, or the RAW VECTOR while the lexicon is warming
    the three sensors that moved most

Nothing else. It cannot see the whole stream, cannot see previous expressions,
and has no memory between calls — so a line is a function of this moment, and
two identical moments produce the same line.

ONE RETRY, AND THE RETRY IS TOLD WHY
--------------------------------------
Output goes through the existing deterministic validator. On rejection there is
EXACTLY ONE retry, with the reason appended:

    your previous output was rejected because X; the first token must be one of...

A second failure goes to quarantine and the stream gets a MEDIATION line saying
an expression was rejected twice and where to read it. NO THIRD ATTEMPT. Three
attempts is a model being coached until it produces something acceptable, and
what comes out the far end is the coaching rather than the state.

The MEDIATION line matters more than the expression it replaces: silence with no
explanation reads as nothing to say, and "rejected twice, here is the file" reads
as a producer that failed. Those are different facts about the system.

WHILE THE LEXICON IS WARMING
------------------------------
STATUS requires exactly one glyph and there is none, so STATUS is impossible.
The prompt is told to use QUERY, HYPOTHESIS or ANOMALY instead, and the raw
vector summary is passed in place of a glyph. Nothing fabricates a Δ.

    venv/Scripts/python.exe -m cockpit.reflex --selftest      # no model called
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import expression as ex        # noqa: E402

# Calls per cycle. Eight phases plus the cycle-end line.
MAX_CALLS_PER_CYCLE = 9

MAX_RETRIES = 1          # one retry. Not two, not "until it works".

RETRY_PREFIX = ("your previous output was rejected because {reason}; "
                "the first token must be one of STATUS QUERY HYPOTHESIS ANOMALY, "
                "and the other rules in the instructions still apply. "
                "Emit one corrected line and nothing else.")

WARMING_NOTE = ("The state lexicon is still warming ({label}), so NO GLYPH "
                "EXISTS. Do not invent one and do not use STATUS, which requires "
                "a glyph. Use QUERY, HYPOTHESIS or ANOMALY.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


NOTHING_MOVED = ("no sensor moved beyond its band since the last line")


def movers(pulse_lines: list, n: int = 3) -> list:
    """The n sensors that moved MOST, from the pulse producer's own lines.

    THIS FUNCTION USED TO LIE TWICE. It returned value=None for every sensor —
    the value was only ever in the display string — and it took the FIRST n
    lines rather than the largest, so "the three that moved most" was really
    "the three that happened to be emitted first". Both are fixed by the
    structured fields the pulse line now carries: value, unit and magnitude.

    Ranked by magnitude, and a line without one (a band change on a value with
    no previous reading, an availability flip) sorts last rather than being
    dropped — an availability flip is often the most important thing on the
    list even though it has no percentage.
    """
    rows = []
    for line in pulse_lines or []:
        if line.get("kind") not in ("move", "band", "availability", "first"):
            continue
        if not line.get("sensor"):
            continue
        rows.append({
            "key": line["sensor"],
            "value": line.get("value"),
            "unit": line.get("unit") or "",
            "magnitude": line.get("magnitude"),
            "kind": line.get("kind"),
            "reason": line.get("why") or line.get("text", "")[:80],
        })
    # newest wins for a sensor that moved more than once in the window
    latest = {}
    for r in rows:
        latest[r["key"]] = r
    ranked = sorted(latest.values(),
                    key=lambda r: (r["magnitude"] is None, -(r["magnitude"] or 0.0)))
    return ranked[:n]


def recent_pulse(stream_path: pathlib.Path, limit: int = 120) -> list:
    """The tail of the stream. `stream_path` is REQUIRED — no default."""
    return [l for l in ex.read_stream(stream_path, limit=limit)
            if l.get("depth") == ex.PULSE]


def current_state(stream_path: pathlib.Path, glyph_info: dict,
                  heartbeat: Optional[dict] = None,
                  flow: Optional[dict] = None,
                  degraded: Optional[int] = None,
                  unusual: Optional[dict] = None) -> dict:
    """Everything the model is told about NOW. All of it, or a named absence.

    THE FAULT THIS REPLACES: drain() passed [] where speak() expected the three
    sensors that moved most, so the 3b was handed a grammar, a question and no
    state — and it filled the shape. Asked "how are you" it answered
    "QUERY sensor_id=disk_read_mb threshold_crossed=false", which is form-valid
    and says nothing, because there was nothing to say anything about.

    An empty list is the worst possible way to express "nothing moved": it is
    indistinguishable from "nobody looked". So a quiet system reports
    NOTHING_MOVED as a sentence the model can answer WITH, rather than an
    absence it has to guess the meaning of.
    """
    return {
        "movers": movers(recent_pulse(stream_path)),
        # WHICH READING IS UNUSUAL FOR THIS MACHINE (23 Aug 2026). `movers` is
        # ranked by raw relative movement against a flat 15%, which made
        # idle_seconds — a laptop being left alone — the loudest thing on the
        # list at "moved 4800%". cockpit/norms.py ranks by deviation from each
        # sensor's OWN median, and says per row which rule judged it. Both are
        # carried: the mover list is what the stream showed, the unusual list is
        # what it means here.
        "unusual": (unusual or {}).get("rows") or [],
        "unusual_rules": (unusual or {}).get("rule_meaning") or {},
        "nothing_moved": NOTHING_MOVED,
        "glyph": glyph_info.get("glyph"),
        "warming": (glyph_info.get("warming") or {}).get("label"),
        "raw_summary": glyph_info.get("raw_summary"),
        "step": (heartbeat or {}).get("step"),
        "step_index": (heartbeat or {}).get("step_index"),
        "cycle_id": (heartbeat or {}).get("cycle_id"),
        "flow_score": (flow or {}).get("flow_score"),
        "flow_band": (flow or {}).get("band"),
        "degraded_steps": degraded,
    }


def render_state(state: dict) -> str:
    """The state, as the lines the model actually sees."""
    out = []
    if state.get("glyph"):
        out.append("CURRENT STATE GLYPH: {}".format(state["glyph"]))
    else:
        out.append(WARMING_NOTE.format(label=state.get("warming") or "warming"))
        if state.get("raw_summary"):
            out.append("RAW VECTOR: {}".format(state["raw_summary"]))

    cyc = []
    if state.get("step"):
        cyc.append("step {} {}".format(state.get("step_index") or "",
                                       state["step"]).strip())
    if state.get("flow_score") is not None:
        cyc.append("flow score {} ({})".format(
            state["flow_score"], state.get("flow_band") or "unbanded"))
    if state.get("degraded_steps") is not None:
        cyc.append("{} DEGRADED step(s)".format(state["degraded_steps"]))
    out.append("CYCLE: {}".format("; ".join(cyc) if cyc else "no cycle is running"))

    unusual = state.get("unusual") or []
    if unusual:
        # FIRST, because it is the question worth answering. "Which moved most"
        # is arithmetic about the last two readings; "which is unusual here" is
        # arithmetic about this machine's own history, and only the second one
        # tells the model anything it could not have guessed.
        out.append("WHAT IS UNUSUAL FOR THIS MACHINE RIGHT NOW:")
        for u in unusual:
            out.append("  {}={}{} — {} [judged by the {} rule]".format(
                u.get("key"), u.get("value"),
                (" " + u["unit"]) if u.get("unit") else "",
                u.get("why", ""), u.get("rule")))

    movers_ = state.get("movers") or []
    if movers_:
        out.append("SENSORS THAT MOVED MOST (raw movement, not a norm):")
        for m in movers_:
            mag = ("{:.0%}".format(m["magnitude"])
                   if m.get("magnitude") is not None else "no prior reading")
            out.append("  {}={}{} moved {} — {}".format(
                m["key"], m.get("value"),
                (" " + m["unit"]) if m.get("unit") else "", mag,
                m.get("reason", "")))
    elif not unusual:
        # NOT AN EMPTY LIST. See current_state().
        out.append("SENSORS: {}. That is itself a fact about the system and a "
                   "valid thing to report.".format(state.get(
                       "nothing_moved", NOTHING_MOVED)))
    return "\n".join(out)


def build_prompt(phase_report: str, glyph_info: dict, top_sensors: list = None,
                 state: Optional[dict] = None) -> str:
    """The whole input. Deterministic given its arguments — no hidden state.

    `state` is the modern argument. `top_sensors` is kept so the older two-arg
    calls and their tests still mean what they meant, and is folded into a state
    when no state is given.
    """
    st = state if state is not None else {
        "movers": list(top_sensors or []),
        "glyph": glyph_info.get("glyph"),
        "warming": (glyph_info.get("warming") or {}).get("label"),
        "raw_summary": glyph_info.get("raw_summary"),
    }
    return "\n".join([ex.SYSTEM_PROMPT, "", render_state(st), "",
                      "PHASE REPORT: {}".format(str(phase_report)[:1200])])


def call_3b(prompt: str, max_tokens: int = 160) -> str:
    """The warm small model, through the existing ladder. No new call path."""
    from core.groq_backend import _call_local_as              # noqa: PLC0415
    from core import model_window as mw                        # noqa: PLC0415
    content, _meta = _call_local_as(mw.small_model(), prompt, max_tokens)
    return content


class ReflexProducer:
    """Counts its own calls so the per-cycle budget is enforced, not intended."""

    def __init__(self, caller: Optional[Callable] = None,
                 max_calls: int = MAX_CALLS_PER_CYCLE):
        self.caller = caller or call_3b
        self.max_calls = max_calls
        self.calls = 0

    def budget_left(self) -> int:
        return max(0, self.max_calls - self.calls)

    def speak(self, phase_report: str, glyph_info: dict, top_sensors: list,
              stream_path: pathlib.Path, quarantine_root: pathlib.Path,
              source: str = ex.MODEL, state: Optional[dict] = None) -> dict:
        """One expression attempt, with one retry. Both paths are REQUIRED args.

        Returns {emitted, text|None, attempts, rejected:[reasons], quarantined}.
        """
        if self.budget_left() <= 0:
            return {"emitted": False, "text": None, "attempts": 0,
                    "rejected": [], "quarantined": False,
                    "why": "per-cycle budget of {} calls is spent".format(
                        self.max_calls)}

        prompt = build_prompt(phase_report, glyph_info, top_sensors,
                              state=state)
        rejected = []
        raw = None

        for attempt in range(MAX_RETRIES + 1):
            self.calls += 1
            try:
                raw = self.caller(prompt)
            except Exception as e:                             # noqa: BLE001
                rejected.append("caller failed: {}: {}".format(type(e).__name__, e))
                break
            verdict = ex.validate(raw)
            if verdict.ok:
                line = ex.make_line(source, ex.EXPRESSION, raw.strip(),
                                    source_tag="model", reflexivity=1,
                                    form=verdict.form, glyphs=list(verdict.glyphs))
                ex.append_line(line, path=stream_path)
                return {"emitted": True, "text": raw.strip(),
                        "attempts": attempt + 1, "rejected": rejected,
                        "quarantined": False, "line": line}
            rejected.append(verdict.reason)
            ex.quarantine_rejected(raw, verdict, prompt, root=quarantine_root)
            if attempt < MAX_RETRIES:
                prompt = "{}\n\n{}".format(
                    prompt, RETRY_PREFIX.format(reason=verdict.reason))

        # TWO FAILURES. The stream says so rather than going quiet — silence with
        # no explanation reads as nothing to say, which is a different fact.
        day = datetime.now(timezone.utc).date().isoformat()
        note = ex.make_line(
            ex.SYS, ex.MEDIATION,
            "an expression was rejected twice and was not emitted; "
            "read it in {}".format(
                ex.quarantine_path(day, quarantine_root).name),
            source_tag="sys", reflexivity=0, kind="rejection_notice",
            reasons=rejected)
        ex.append_line(note, path=stream_path)
        return {"emitted": False, "text": None, "attempts": len(rejected),
                "rejected": rejected, "quarantined": True, "line": note}

    def answer_questions(self, rows: list, glyph_info: dict,
                         stream_path: pathlib.Path,
                         quarantine_root: pathlib.Path) -> list:
        """Answer human_input_queue items routed to the 3b. Same grammar, same retry."""
        out = []
        for row in rows or []:
            if row.get("route") != ex.ROUTE_3B or row.get("answered"):
                continue
            if self.budget_left() <= 0:
                break
            out.append(self.speak(
                "A human asked: {}".format(row.get("text", ""))[:600],
                glyph_info, [], stream_path=stream_path,
                quarantine_root=quarantine_root))
        return out


def _selftest() -> int:
    """No model is called. A stub caller drives every branch."""
    import tempfile
    print("cockpit/reflex.py --selftest   (stubbed caller; no model contacted)")
    tmp = pathlib.Path(tempfile.mkdtemp())
    stream, quar = tmp / "stream.jsonl", tmp / "quar"

    good = ReflexProducer(caller=lambda p: "QUERY which axis lacks a physical column")
    r = good.speak("phase A ok", {"glyph": None, "warming": {"label": "warming: 3/20"},
                                  "raw_summary": "25/25 dims"}, [],
                   stream_path=stream, quarantine_root=quar)
    print("  valid first try      emitted={} attempts={}".format(r["emitted"], r["attempts"]))

    seq = iter(["I feel odd", "QUERY what changed"])
    retry = ReflexProducer(caller=lambda p: next(seq))
    r2 = retry.speak("phase B", {"glyph": "Δ7"}, [], stream_path=stream,
                     quarantine_root=quar)
    print("  rejected then fixed  emitted={} attempts={} first_reason={}".format(
        r2["emitted"], r2["attempts"], r2["rejected"][0][:44]))

    bad = ReflexProducer(caller=lambda p: "I feel uneasy about everything")
    r3 = bad.speak("phase C", {"glyph": "Δ7"}, [], stream_path=stream,
                   quarantine_root=quar)
    print("  rejected twice       emitted={} quarantined={} attempts={}".format(
        r3["emitted"], r3["quarantined"], r3["attempts"]))
    print("  no third attempt     {}".format(bad.calls == 2))
    print("  mediation line       {}".format(r3["line"]["text"][:70]))

    budget = ReflexProducer(caller=lambda p: "QUERY x", max_calls=1)
    budget.speak("a", {"glyph": "Δ1"}, [], stream_path=stream, quarantine_root=quar)
    r4 = budget.speak("b", {"glyph": "Δ1"}, [], stream_path=stream, quarantine_root=quar)
    print("  budget enforced      emitted={} why={}".format(r4["emitted"], r4["why"][:40]))

    p = build_prompt("report", {"glyph": None, "warming": {"label": "warming: 3/20"},
                                "raw_summary": "s"}, [])
    print("  warming prompt bans STATUS: {}".format("do not use STATUS" in p))
    print("  RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
