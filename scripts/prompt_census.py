#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/prompt_census.py — MEASURE THE ROOM. NO MODEL IS CONTACTED.

COMMAND 24 pinned the output language on the wire and the drift did not stop,
because nine of the ten prompt blocks were still Bulgarian: one English sentence
arguing with 2,700 characters of context. A 3B model follows the room, not the
order.

So the room needs an instrument. This assembles the REAL prompt for a kind — by
capturing what core/brain.py hands to the HTTP layer, not by reading the source
— and reports the script census, whole and per block.

    PASS   Cyrillic 0.00% and Han 0.00%
    FAIL   anything else, with the offending BLOCK named, because "the prompt
           has Cyrillic in it" is not actionable and "_spirit() has Cyrillic in
           it" is.

Blocks are measured by CALLING each component, never by slicing the assembled
string on its labels. Slicing was wrong here and quietly so: "ПАМЕТ" occurred
inside the canon frame as well as in the memory label, and a first-index split
put ~1,880 characters of canon into the memory block's bill.

    venv/Scripts/python.exe scripts/prompt_census.py
    venv/Scripts/python.exe scripts/prompt_census.py constancy
    venv/Scripts/python.exe scripts/prompt_census.py --all
"""
from __future__ import annotations

import argparse
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

# Every kind that reaches a brain prompt, with a representative question. The
# question is the caller's, so it is measured as its own block.
KINDS = ("constancy", "cycle_plan", "cycle_review", "constellation",
         "cycle_report", "mirror_read", "phase_debrief", "reconsider",
         "autopsy", "degraded_mode", "step_stance")

DEFAULT_KIND = "constancy"


def profile(text) -> dict:
    """Fractions of LETTER characters by script. Digits and punctuation ignored."""
    latin = cyrillic = han = other = 0
    for ch in str(text or ""):
        if not ch.isalpha():
            continue
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            han += 1
        elif 0x0400 <= o <= 0x052F:
            cyrillic += 1
        elif o < 0x0250:
            latin += 1
        else:
            other += 1
    n = latin + cyrillic + han + other
    return {"chars": len(str(text or "")), "letters": n,
            "cyrillic": (cyrillic / n) if n else 0.0,
            "han": (han / n) if n else 0.0,
            "latin": (latin / n) if n else 0.0}


def runs(text, limit: int = 6) -> list:
    """The actual non-Latin fragments, so a FAIL names the words."""
    import re
    out = []
    for m in re.finditer(r"[Ѐ-ԯ一-鿿]+[^\x00-\x7F]*", str(text)):
        frag = m.group().strip()
        if len(frag) > 1:
            out.append(frag)
        if len(out) >= limit:
            break
    return out


class _Recorder:
    """Stands in for `requests`. Captures the body, contacts nothing."""

    def __init__(self):
        self.prompts = []

    def post(self, url, timeout=None, json=None):
        for msg in (json or {}).get("messages", []):
            self.prompts.append(msg.get("content", ""))
        raise RuntimeError("prompt_census contacts no model")


def assemble(kind: str, attend=None) -> tuple:
    """(prompt, blocks) for one kind. Nothing is sent anywhere.

    `attend` is a seam and it exists for exactly one reason: test/conftest.py
    neutralises core.brain.attend for the whole suite — rightly, since a
    heartbeat must not talk to a model in a test — so a census run from inside
    pytest would measure the stub and report an empty prompt. The default is the
    real function; the tests hand in the one they captured at import.
    """
    rec = _Recorder()
    sys.modules["requests"] = rec
    from core import brain

    real = (brain.models, brain._pick_model, brain._fast_model, brain._smaller)
    brain.models = lambda: ["census"]
    brain._pick_model = lambda: ("census", "http://127.0.0.1:0")
    brain._fast_model = lambda: "census"
    brain._smaller = lambda m: None
    try:
        if kind == "step_stance":
            real_silence = brain._record_silence
            real_prev, real_plan = brain._prev_step_output, brain.current_plan
            brain._record_silence = lambda *a, **k: None
            brain._prev_step_output = lambda: ("scoring_engine", "score 0.62")
            brain.current_plan = lambda: {"focus": "anchors", "watch": ["NOAA"],
                                          "success_test": "the reuse is resolved"}
            brain._AVAILABLE = True
            try:
                (attend or brain.attend)("cycle_report")
            finally:
                brain._record_silence = real_silence
                brain._prev_step_output, brain.current_plan = real_prev, real_plan
        else:
            brain.think(
                role="census probe",
                question="This is a census probe. It is never answered.",
                evidence='{"axis": "CENSUS", "metric": "census"}',
                schema={"verdict": "what you conclude"},
                kind=kind, remember_it=False)
    finally:
        (brain.models, brain._pick_model, brain._fast_model,
         brain._smaller) = real

    prompt = rec.prompts[0] if rec.prompts else ""

    from core import canon
    blocks = [
        ("LANGUAGE_PIN", brain.LANGUAGE_PIN),
        ("_body()", brain._body()),
        ("_self_state()", brain._self_state()),
        ("_spirit() law", brain._spirit().split("CANON")[0]),
        ("_spirit() canon", canon.as_frame()),
        ("_memory({!r})".format(kind), brain._memory(kind, n=5)),
    ]
    return prompt, blocks


def census(kind: str, attend=None) -> int:
    prompt, blocks = assemble(kind, attend)
    if not prompt:
        print("  kind={}: no prompt was assembled".format(kind))
        return 1

    whole = profile(prompt)
    print("  kind={}".format(kind))
    print("    {:<28} {:>7} {:>8} {:>9} {:>8}".format(
        "block", "chars", "letters", "Cyrillic", "Han"))
    print("    " + "-" * 66)
    print("    {:<28} {:>7} {:>8} {:>8.2%} {:>8.2%}".format(
        "WHOLE PROMPT", whole["chars"], whole["letters"], whole["cyrillic"],
        whole["han"]))
    offenders = []
    for name, text in blocks:
        p = profile(text)
        flag = "  <--" if (p["cyrillic"] or p["han"]) else ""
        print("    {:<28} {:>7} {:>8} {:>8.2%} {:>8.2%}{}".format(
            name, p["chars"], p["letters"], p["cyrillic"], p["han"], flag))
        if p["cyrillic"] or p["han"]:
            offenders.append((name, runs(text)))

    if whole["cyrillic"] == 0.0 and whole["han"] == 0.0:
        print("    PASS")
        return 0

    print("    FAIL — the room is not English")
    if offenders:
        for name, frags in offenders:
            print("      {}: {}".format(name, ", ".join(frags)))
    else:
        # Not in a named block, so it came from the scaffold or the caller's
        # role/question. Say where rather than leaving the reader to grep.
        print("      not in any named block — the scaffold in core/brain.py or "
              "the role/question this call site passes in:")
        for frag in runs(prompt, limit=8):
            print("        {}".format(frag))
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("kind", nargs="?", default=None,
                    help="which kind to assemble (default: {})".format(
                        DEFAULT_KIND))
    ap.add_argument("--all", action="store_true",
                    help="every kind that reaches a brain prompt")
    args = ap.parse_args(argv)

    kinds = KINDS if args.all else [args.kind or DEFAULT_KIND]
    print("scripts/prompt_census.py — no model is contacted")
    print()
    failed = 0
    for kind in kinds:
        failed += census(kind)
        print()
    if len(kinds) > 1:
        print("  {}/{} kind(s) PASS".format(len(kinds) - failed, len(kinds)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
