#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/declared_inputs.py — WHAT A STEP READS, WRITTEN DOWN INSTEAD OF GUESSED.

THE HOLE THIS CLOSES (18 August 2026)
-------------------------------------
`core/notary.py:_age_state` grades a step by the age of the files it reads, and it
takes that list from `core/metta_check._REQ`, which is built by the static scanner in
`core/cycle_graph.scan_requires()`. The scanner greps a step's region of
fast_cycle_runner.py, and the raw source of the modules imported there, for LITERAL
paths matching `(memory|snapshots|config|output|data|news)/...`.

For `github_publish` that scanner resolves NOTHING:

    >>> core.cycle_graph.scan_requires()["github_publish"]
    []

...and it is right not to. The two paths the step really reads are built at runtime —
`_find_latest_web_intel_dir()` walks `memory/web_intelligence` and picks the newest
dated folder, and the hypothesis store lives under `cortex_memory/`, a prefix the
regex does not even contain. Since 17 Aug an empty list correctly means UNKNOWN
rather than FULL, so the gate refuses `github_publish` every night — for ignorance,
not for a fault. The contract was being INFERRED where it should have been WRITTEN.

THE RULE
--------
    A written declaration WINS over the scanner for the steps it names.
    A step it does not name is untouched — scanner only, and the scanner's
    silence still means UNKNOWN, which still means refuse.

That asymmetry is the whole safety property. `config/step_inputs.json` can only speak
for steps it mentions; it has no syntax for weakening one it does not. And a
declaration that is absent, unreadable or malformed degrades to exactly today's
behaviour rather than to trust — every failure path below returns None or [], and
both of those score UNKNOWN at the gate.

WHO OWNS THE FILE
-----------------
A human. `config/step_inputs.json` is named in `safety/protected_paths.py`, so no
generated patch can write it, at either enforcement layer. That matters more here
than for an ordinary config: this file is the ONE place in the repo where a step can
be handed provenance it did not earn from a scan. If the system could edit it, the
system could declare itself trustworthy and the notary would be a mirror.

    venv\\Scripts\\python.exe -m core.declared_inputs --selftest
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

REL = "config/step_inputs.json"          # quoted verbatim in reason strings
PATH = BASE / REL

# What a reason string calls each origin. The notary prints these as they stand, so
# the attestation record says WHERE the trust came from, not merely how much of it.
SOURCE_WRITTEN = f"the written declaration in {REL}"
SOURCE_SCANNER = "the static scanner in core/cycle_graph.scan_requires()"


def _clean(rel) -> str | None:
    """A usable repo-relative path, or None.

    Refuses absolute paths and anything containing '..'. A declaration is a trust
    input, and a trust input that can point outside the repo is not one: the age of
    C:/somewhere/else says nothing about this cycle.
    """
    if not isinstance(rel, str):
        return None
    norm = rel.replace("\\", "/").strip().strip("/")
    if not norm or norm.startswith("/"):
        return None
    if norm[1:2] == ":" or ".." in norm.split("/"):
        return None
    return norm


def _load() -> dict:
    """{step: [paths]} for every entry the file carries. {} if it is gone or broken.

    Fail closed on every path: an unreadable declaration must leave the system in the
    state it was in before the declaration existed, which is scanner-only.
    """
    try:
        doc = json.loads(PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    steps = doc.get("steps")
    if not isinstance(steps, dict):
        return {}
    out: dict = {}
    for step, entry in steps.items():
        if not isinstance(step, str) or not step.strip():
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get("inputs"), list):
            # Named, but unreadable. NOT skipped — skipping would hand the step back
            # to the scanner, and a human who wrote a broken entry was trying to say
            # something. An empty list scores UNKNOWN, so the step is refused.
            out[step] = []
            continue
        raw = entry["inputs"]
        cleaned = [c for c in (_clean(r) for r in raw) if c]
        # All or nothing: one unusable path invalidates the entry rather than
        # silently shrinking it, because a shrunken list is a WIDER grade — the
        # oldest input is exactly the one a typo would drop.
        out[step] = cleaned if len(cleaned) == len(raw) else []
    return out


def for_step(step: str) -> list | None:
    """The written inputs of `step`, or None if nobody wrote any.

    None and [] are DIFFERENT and every caller depends on it:
      None -> no declaration; fall back to the scanner, behaviour unchanged.
      []   -> a declaration exists and is empty or broken; provenance UNKNOWN.
    """
    return _load().get(step)


def all_declared() -> dict:
    """{step: [paths]} — everything the file speaks for. Overlays the scanner."""
    return _load()


def source_for(step: str) -> str:
    """Which origin a reason string should name for this step's input list."""
    return SOURCE_WRITTEN if for_step(step) is not None else SOURCE_SCANNER


# ── SELFTEST ────────────────────────────────────────────────────────────────
# Reports which integrations are LIVE in the repo it finds itself in. A module wired
# into nothing must say so out loud rather than let a docstring claim otherwise.

def selftest() -> dict:
    rep: dict = {"declaration": REL, "exists": PATH.exists(),
                 "declared_steps": sorted(_load()), "integrations": {}}

    try:
        from core.cycle_graph import scan_requires
        harvest = scan_requires()
        agrees = all(harvest.get(s) == list(f) for s, f in _load().items())
        rep["integrations"]["core.cycle_graph.scan_requires"] = (
            "LIVE - the written declaration overlays the scan" if agrees else
            "INERT - scan_requires does not prefer the declaration")
    except Exception as e:
        rep["integrations"]["core.cycle_graph.scan_requires"] = (
            f"INERT - {type(e).__name__}: {e}")

    try:
        from core import notary
        src = Path(notary.__file__).read_text(encoding="utf-8")
        rep["integrations"]["core.notary"] = (
            "LIVE - the gate reads the declaration" if "declared_inputs" in src else
            "INERT - core/notary.py does not consult this module")
    except Exception as e:
        rep["integrations"]["core.notary"] = f"INERT - {type(e).__name__}: {e}"

    try:
        from safety.protected_paths import is_protected
        rep["integrations"]["safety.protected_paths"] = (
            "LIVE - the declaration is human-only" if is_protected(REL) else
            "INERT - a generated patch could widen the declaration")
    except Exception as e:
        rep["integrations"]["safety.protected_paths"] = f"INERT - {type(e).__name__}: {e}"

    for step, files in sorted(_load().items()):
        rep.setdefault("steps", {})[step] = {
            "inputs": files,
            "missing_on_disk": [f for f in files if not (BASE / f).exists()]}
    return rep


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        print(json.dumps(selftest(), ensure_ascii=False, indent=2))
    else:
        arg = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
        if arg:
            print(json.dumps({"step": arg, "inputs": for_step(arg),
                              "source": source_for(arg)}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(all_declared(), ensure_ascii=False, indent=2))
