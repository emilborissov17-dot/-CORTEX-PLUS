#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/answered_by.py — WHICH BACKEND ANSWERED THIS, stamped where it is written.

ITEM 43.1, 29 August 2026.

NOT TO BE CONFUSED WITH core/provenance.py, AND THE NAME IS THE FIX FOR THAT.
core/provenance.py (15 Aug 2026) answers "where did this NUMBER come from" —
upstream host, observation date, MEASURED/ANNUAL/CONSTANT/UNKNOWN, staleness.
This module answers a different question: "which MODEL produced this answer, and
was the step degraded when it did". Both are provenance in English; conflating
them in one file would put a data-lineage module and an LLM-backend module under
one import, and the first draft of this work did exactly that by overwriting the
older file. Different question, different name.

THE DEFECT THIS EXISTS FOR. On the night of 2026-08-29 all three cloud tiers were
unavailable — Groq rate-limited, Cerebras 402 Payment Required, OpenRouter
rate-limited — and nine agents fell through to local qwen2.5:3b, 29 calls in one
cycle. Every degradation was announced on stdout and recorded in the step
contract. NONE of it reached the JSON that scoring reads. An axis snapshot
answered by a 3B model at the bottom of a collapsed ladder is
byte-indistinguishable, to every downstream reader, from one answered by a
frontier model.

Kimi's ruling, implemented here verbatim:
    "Standardize on a provenance object {backend, model, degraded} rather than
     cosmos's flat source_type - adopt cosmos's honesty pattern but add the
     backend/degradation dimension that source_type lacks."

WHY IT READS step_contract AND NOT THE LLM LAYER. core/groq_backend.call_groq
returns a bare string: the meta carrying `degraded` and `model` is built and then
discarded by the wrapper at groq_backend.py:861 (`content, _meta = ...`). 41
production call sites go through that wrapper, 3 through call_groq_meta. So the
identity is NOT reachable at the writer through the call path — but
_note_degraded() has already pushed it into the open StepContract, and
step_contract.current() is a public accessor. That is the one place a writer can
ask, at write time, without touching 41 call sites.

THREE STATES, NOT TWO, AND THIS IS THE WHOLE POINT OF THE MODULE:

    degraded=True    a degradation was recorded against the open step
    degraded=False   a step contract is open and recorded no degradation
    degraded=None    THERE IS NO OPEN STEP — a script, a selftest, a manual run

The third is not "not degraded". Conflating "nothing degraded" with "nobody was
watching" is precisely the bug ITEM 43 exists to kill, and it is the same shape
as step_contract.note_degraded_on_current() returning False for "no contract"
rather than raising.

PARSE *AND* KEEP THE PROSE — the choice this docstring is required to declare.
The contract stores a human sentence, built at groq_backend.py:826:

    f"answered by {res.tier} ({meta.get('model')}) after the cloud "
    f"tier was abandoned at its slice of B={res.budget_sec:.0f}s"

Both options were on the table: parse it, or carry it raw. THIS MODULE DOES BOTH,
because each alone loses something. A strict ANCHORED regex extracts backend and
model when the sentence has the known shape; the FULL RAW REASON is always kept
under "why". So:
  * when the parse succeeds, downstream gets structured, weightable fields;
  * when it fails — a reworded message, the other reason string ("no tier
    answered within B=..."), an accumulated note — backend and model are None
    and the prose survives for a human, instead of a confident wrong parse.
A parser that guessed on an unrecognised sentence would manufacture exactly the
false provenance this module was written to remove.

WHAT THIS OBJECT DOES *NOT* CLAIM, said here because an over-read would recreate
the defect in a new field. The stamp describes THE STEP the artifact was written
inside, not the individual number. A step that makes twelve model calls and
degrades on one is degraded; a REAL_DATA payload fetched over HTTP inside that
same step will carry degraded=True although no model touched its value. The
honest reading is "this artifact was produced inside a degraded step", and the
"why" text says so in words. Narrowing it to per-value provenance needs a join
key that does not exist today: memory/llm_provenance.jsonl carries ts, backend,
model and prompt_sha1 but NO step name and NO artifact id, so a record cannot be
tied to the thing it produced.

NO THRESHOLD LIVES HERE. This module reports; it does not decide what a degraded
answer is worth. Whether scoring weights, excludes or ignores it is a policy
decision and is deliberately not encoded anywhere in this file.
"""
from __future__ import annotations

import re

# ANCHORED on purpose: it matches the head of the known sentence and nothing
# else. `\S+` for the tier (cloud / local_3b / local_8b, from core.step_budget)
# and a bounded group for the model id, which may contain colons and dots
# (qwen2.5:3b).
_REASON_RE = re.compile(r"^answered by (\S+) \(([^)]*)\)")

NO_STEP = "no open step contract"


def stamp() -> dict:
    """{"backend", "model", "degraded", "why"} for the step being written inside.

    Never raises. A stamp that can take down a writer is worse than no stamp, and
    this sits on the write path of every axis snapshot.
    """
    try:
        from core.step_contract import current
        c = current()
    except Exception as e:                       # import cycles, partial installs
        return {"backend": None, "model": None, "degraded": None,
                "why": f"{NO_STEP} (step_contract unavailable: "
                       f"{type(e).__name__})"}

    if c is None:
        # THE THIRD STATE. Not False.
        return {"backend": None, "model": None, "degraded": None,
                "why": NO_STEP}

    reason = getattr(c, "degraded", None)
    if not reason:
        return {
            "backend": None,
            "model": None,
            "degraded": False,
            # Stated rather than left blank: a clean step tells us nothing fell
            # through the ladder, and NOT which cloud backend answered. The
            # contract records degradations, not successes.
            "why": ("step contract open, no degradation recorded; the backend "
                    "that answered is not recoverable from the contract when "
                    "nothing degraded"),
        }

    m = _REASON_RE.match(str(reason))
    backend = m.group(1) if m else None
    model = m.group(2) if m else None
    if model in ("", "None"):        # meta.get('model') was None at the source
        model = None

    out = {"backend": backend, "model": model, "degraded": True,
           "why": str(reason)}
    n = getattr(c, "degraded_count", None)
    if isinstance(n, int) and n > 0:
        # "3 of 12 calls fell to the local model" is a different fact from "one
        # did" — step_contract.note_degraded says so in its own docstring, and
        # the count is the only place that fact survives.
        out["degraded_calls"] = n
    return out


def selftest() -> int:
    """Reports which integrations are LIVE and which are INERT in THIS repo."""
    checks, failed = [], 0

    def want(ok, why, detail=""):
        nonlocal failed
        if not ok:
            failed += 1
        checks.append((ok, why, detail))

    import core.step_contract as sc

    saved = sc._CURRENT
    sc._CURRENT = None
    s = stamp()
    want(s["degraded"] is None and s["why"] == NO_STEP,
         "outside any step, degraded is None — NOT False", str(s))

    class _Fake:
        degraded = None
        degraded_count = 0

    f = _Fake()
    sc._CURRENT = f
    s = stamp()
    want(s["degraded"] is False and s["backend"] is None,
         "inside a clean step, degraded is False and no backend is invented",
         str(s))

    f.degraded = ("answered by local_3b (qwen2.5:3b) after the cloud tier was "
                  "abandoned at its slice of B=3416s")
    f.degraded_count = 3
    s = stamp()
    want(s["degraded"] is True and s["backend"] == "local_3b"
         and s["model"] == "qwen2.5:3b",
         "a degraded step parses backend and model out of the real sentence",
         str(s))
    want(s["why"] == f.degraded and s["degraded_calls"] == 3,
         "and keeps the raw reason plus the call count")

    f.degraded = "no tier answered within B=900s (budget exhausted)"
    s = stamp()
    want(s["degraded"] is True and s["backend"] is None and s["model"] is None,
         "an unrecognised reason yields degraded=True with NO guessed backend",
         str(s))
    want(s["why"] == f.degraded,
         "and the prose survives for a human to read")

    sc._CURRENT = saved

    for ok, why, detail in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {why}")
        if not ok and detail:
            print(f"         got {detail}")

    print("\n  integrations, in THIS repo:")
    try:
        from core.step_contract import current as _c  # noqa: F401
        print("    core.step_contract.current()   LIVE")
    except Exception as e:
        print(f"    core.step_contract.current()   INERT — {type(e).__name__}")
    import pathlib
    base = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("agents/planet/planet_snapshots_agent_qwen.py",
                "agents/cosmos/cosmos_snapshots_agent_qwen.py",
                "_refresh_three_axes.py"):
        p = base / rel
        wired = p.exists() and "answered_by" in p.read_text(
            encoding="utf-8", errors="replace")
        print(f"    {rel:<48} {'LIVE — stamps' if wired else 'INERT — does not stamp'}")
    other = base / "core" / "provenance.py"
    print(f"    core/provenance.py (the OTHER one) "
          f"{'present and untouched' if other.exists() else 'MISSING'}")

    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(selftest())
