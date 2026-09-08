#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/blind_producers.py — NO STEP FEEDS A DECISION BLIND, AND IF ONE DOES, IT IS
NAMED.

WHAT A "BLIND PRODUCER" IS
---------------------------
A step whose artifact reaches a notary-gated decision, and which cannot say what
it reads. core/notary._age_state([]) fails closed on an empty input list — "an
empty list does not mean the step reads nothing, it means we do not know what it
reads" — so such a step stamps UNKNOWN(0) on everything it produces, and every
irreversible step downstream inherits that 0 and is refused.

THE DEFECT THIS CLOSES (8 Sep 2026)
------------------------------------
On 2026-09-08T01:35:34 the notary refused self_modifier. Its reason names the
blind step, because core/notary._blindness() puts it there — but ONLY inside the
refusal sentence, and only when the level was actually inherited. So the fact
"hyperclaw_plan is blind and its output gates step 18" existed exactly once a
night, inside a string, inside a log nobody reads, and only on the nights the
gate happened to refuse for that particular reason.

Measured against the live chain the same night: 2675 attestations, and the vast
majority carry own=0. This is not one blind step; it is the normal state of the
cycle. A fact that common has to be COUNTABLE, not narrated.

So this module answers one question, mechanically, at any time:

    which steps feed `step` an artifact whose producer cannot say what it reads?

and the runner writes the answer to memory/night_events.jsonl as its own event —
on every gate crossing, PASS OR REFUSE. Not only when it refuses: a gate that
opens while standing on unknown provenance is the more dangerous of the two, and
it is the one that used to print nothing at all.

WHAT THIS IS NOT
-----------------
It grants nothing, lifts nothing and decides nothing. It appends no attestation.
It is a read-only query over the same two tables the notary itself uses —
core/cycle_map.STEPS for "who produces this artifact" and
core.notary._inputs_for for "can that step say what it reads" — deliberately
imported rather than reimplemented, because a second copy of that lookup would
drift from the notary's and start reporting a blindness the gate does not act on.

    venv\\Scripts\\python.exe core/blind_producers.py --selftest
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _lookups():
    """The notary's own two lookups, or a loud failure.

    Imported, never reimplemented: this module's whole claim is that it sees what
    the gate sees. Raises rather than returning empty, because a blindness census
    that silently finds nothing is indistinguishable from a healthy cycle — and
    that is the exact failure mode this file exists to end.
    """
    from core.notary import _inputs_for, _producers_of
    return _inputs_for, _producers_of


def blind_producers_for(step: str) -> list[dict]:
    """[{artifact, producer}] — the steps feeding `step` that cannot say what
    they read.

    Empty list means every producer of every declared input of `step` has a
    declared input list of its own. It does NOT mean the step is trusted; the
    notary decides that, on five dimensions, and this is one contributor to one
    of them.
    """
    inputs_for, producers_of = _lookups()
    mine, _src = inputs_for(step)
    out: list[dict] = []
    for artifact in mine:
        for producer in producers_of(artifact):
            if producer == step:
                continue                       # its own product is not evidence
            declared, _s = inputs_for(producer)
            if not declared:
                out.append({"artifact": artifact, "producer": producer})
    # Stable order so two runs of the same night produce the same event text.
    return sorted(out, key=lambda d: (d["producer"], d["artifact"]))


def describe(step: str, blind: list[dict] | None = None) -> str:
    """One line naming every blind producer, for the night event.

    Names the STEP and the ARTIFACT both. "provenance unknown" without the
    artifact sends a reader hunting; the pair says where to go and what to
    declare.
    """
    blind = blind_producers_for(step) if blind is None else blind
    if not blind:
        return f"{step}: every declared input has a producer that declares its own"
    parts = "; ".join(f"{b['producer']} -> {b['artifact']}" for b in blind)
    return (f"{step}: {len(blind)} blind producer(s) feeding this gate — {parts}. "
            f"Each stamps level_0 (unknown origin) on what it produces, and this "
            f"step inherits it. Declare their inputs in config/step_inputs.json.")


def _selftest() -> int:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))

    print("core/blind_producers.py --selftest")
    try:
        inputs_for, producers_of = _lookups()
        print("  core.notary lookups      : LIVE")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  core.notary lookups      : INERT ({type(exc).__name__}: {exc})")
        print("  RESULT: BROKEN — the census cannot see what the gate sees")
        return 1

    try:
        from core.cycle_map import STEPS
        print(f"  core/cycle_map.STEPS     : LIVE ({len(STEPS)} steps)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"  core/cycle_map.STEPS     : INERT ({type(exc).__name__}: {exc})")
        return 1

    ok = True
    for step in ("self_modifier", "execute_patches", "github_publish"):
        blind = blind_producers_for(step)
        print(f"  {step}: {len(blind)} blind producer(s)")
        for b in blind:
            print(f"      {b['producer']} -> {b['artifact']}")

    # The census must be able to SEE a blind producer, or it proves nothing.
    # self_modifier declares memory/improvement_proposals.json as an input and
    # hyperclaw_plan produces it, so this pair is the live check.
    everything = {b["producer"] for s in ("self_modifier", "execute_patches",
                                          "github_publish")
                  for b in blind_producers_for(s)}
    print(f"  distinct blind producers feeding the three gated steps: "
          f"{len(everything)} {sorted(everything)}")
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
