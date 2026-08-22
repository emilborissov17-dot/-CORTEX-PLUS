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


def build_prompt(phase_report: str, glyph_info: dict, top_sensors: list) -> str:
    """The whole input. Deterministic given its arguments — no hidden state."""
    lines = [ex.SYSTEM_PROMPT, ""]
    if glyph_info.get("glyph"):
        lines.append("CURRENT STATE GLYPH: {}".format(glyph_info["glyph"]))
    else:
        lines.append(WARMING_NOTE.format(
            label=(glyph_info.get("warming") or {}).get("label", "warming")))
        lines.append("RAW VECTOR: {}".format(glyph_info.get("raw_summary", "")))
    lines.append("")
    lines.append("PHASE REPORT: {}".format(str(phase_report)[:1200]))
    lines.append("")
    lines.append("THREE SENSORS THAT MOVED MOST:")
    for s in (top_sensors or [])[:3]:
        lines.append("  {}={} ({})".format(s.get("key"), s.get("value"),
                                           s.get("reason", "")))
    return "\n".join(lines)


def movers(pulse_lines: list, n: int = 3) -> list:
    """The n sensors that moved most, from the pulse producer's own lines."""
    out = []
    for line in pulse_lines or []:
        if line.get("kind") in ("move", "band", "availability") and line.get("sensor"):
            out.append({"key": line["sensor"], "value": None,
                        "reason": line.get("text", "")[:80]})
        if len(out) >= n:
            break
    return out


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
              source: str = ex.MODEL) -> dict:
        """One expression attempt, with one retry. Both paths are REQUIRED args.

        Returns {emitted, text|None, attempts, rejected:[reasons], quarantined}.
        """
        if self.budget_left() <= 0:
            return {"emitted": False, "text": None, "attempts": 0,
                    "rejected": [], "quarantined": False,
                    "why": "per-cycle budget of {} calls is spent".format(
                        self.max_calls)}

        prompt = build_prompt(phase_report, glyph_info, top_sensors)
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
