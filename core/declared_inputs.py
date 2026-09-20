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

A SECOND CLASS OF INPUT: THE LIVE FETCH (20 September 2026)
-----------------------------------------------------------
The rule above ages a step by the files it opens, and for a year that covered
every step. It does not cover `browser_scout`, which opens no file on the cycle
path at all: run_all() loops a table of URLs and fetches each one over HTTP. Its
input is the world. An AST census found one write_text (its own output) and one
read_text behind sys.argv, which the cycle never takes.

That step is in VERIFIERS — the short list of steps allowed to BREAK inherited
provenance, precisely because they check against a live external source. So the
model had it both ways: the step held that right for verifying against the live
world, and was scored UNKNOWN(0) for having no file to be aged by. The
configuration was not what was wrong. The model was.

Both available remedies were worse than the defect. Declaring a file it does not
read is fabricated provenance. Declaring the directory it WRITES makes a step
grade itself off its own cache.

The fix is a category the model was missing. A live fetch is aged by ITS OWN
FETCH TIMESTAMP, written into the record at the moment of fetching — which is
the observation date, which is exactly what the age dimension asks every other
step for. `live_fetch` is a separate key from `inputs` and carries exactly two
things: which records to read, and which field in them holds that timestamp.
Nothing else about those records is looked at — not their value, not their mtime.

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
SOURCE_LIVE_FETCH = f"the live-fetch declaration in {REL}"


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


def _clean_live(entry) -> dict | None:
    """A usable live-fetch declaration, or None.

    A LIVE FETCH is a step whose input is not a file in this repo but the world.
    It opens a URL; the answer exists only in the moment it was asked. Such a step
    cannot be aged by a file's mtime, because on the cycle path it opens no file —
    and it must not be HANDED one to be aged by, which would be provenance it did
    not earn and is the exact fabrication the whole subsystem refuses.

    What it can state honestly is WHEN IT LAST LOOKED, because the fetch writes
    that timestamp into the record it produces, at the moment of fetching. The age
    dimension asks for the observation date of what enters the composite; for a
    live fetch the observation date IS the fetch timestamp. Nothing else about the
    record is read — not its value, not its size, not its mtime.

    THE SELF-GRADING TRAP, AND WHY THIS IS NOT IT. A step must not be aged by its
    own cache: a cache is a copy of an older observation, so one missed night would
    hold the step down for ever over data that never changed. A fetch record is the
    opposite — if the scout did not fetch last night, its picture of the live world
    IS a night old, and saying so is the measurement, not a penalty. That is why
    this lives in its own key and not in `inputs`, where a path a step writes is
    still forbidden.

    Refuses anything it cannot fully resolve: `records` that is not a non-empty
    list of repo-relative paths, or a `timestamp_field` that is not a non-empty
    string. A half-read declaration leaves the step exactly where it was — with no
    declaration at all, which scores UNKNOWN.
    """
    if not isinstance(entry, dict):
        return None
    raw = entry.get("records")
    field = entry.get("timestamp_field")
    if not isinstance(raw, list) or not raw:
        return None
    if not isinstance(field, str) or not field.strip():
        return None
    cleaned = [c for c in (_clean(r) for r in raw) if c]
    # All or nothing, for the same reason as _load(): a shrunken list is a WIDER
    # grade, and the record a typo drops is exactly the one that would have been
    # oldest.
    if len(cleaned) != len(raw):
        return None
    return {"records": cleaned, "timestamp_field": field.strip()}


def _load_live() -> dict:
    """{step: {records, timestamp_field}} for every step that declares a live fetch.

    Fails closed on every path, exactly like _load(): a step whose live-fetch
    declaration is missing, malformed or unresolvable simply does not appear here,
    and is then graded by its file inputs — which for a live fetch is [], which is
    UNKNOWN. Nothing here can raise a step's provenance by being broken.
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
        if not isinstance(entry, dict) or "live_fetch" not in entry:
            continue
        spec = _clean_live(entry["live_fetch"])
        if spec:
            out[step] = spec
    return out


def live_fetch_for(step: str) -> dict | None:
    """The live-fetch record set of `step`, or None if it does not declare one."""
    return _load_live().get(step)


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
    if live_fetch_for(step) is not None:
        return SOURCE_LIVE_FETCH
    return SOURCE_WRITTEN if for_step(step) is not None else SOURCE_SCANNER


# ── SELFTEST ────────────────────────────────────────────────────────────────
# Reports which integrations are LIVE in the repo it finds itself in. A module wired
# into nothing must say so out loud rather than let a docstring claim otherwise.

def selftest() -> dict:
    rep: dict = {"declaration": REL, "exists": PATH.exists(),
                 "declared_steps": sorted(_load()),
                 "live_fetch_steps": sorted(_load_live()), "integrations": {}}

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
        rep["integrations"]["core.notary live_fetch"] = (
            "LIVE - a live fetch is aged by its fetch timestamp"
            if "_fetch_age_state" in src else
            "INERT - core/notary.py still ages every step by file mtime, so a step "
            "that reads only the world scores UNKNOWN")
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
    for step, spec in sorted(_load_live().items()):
        rep.setdefault("steps", {}).setdefault(step, {})["live_fetch"] = {
            "records": spec["records"], "timestamp_field": spec["timestamp_field"],
            "missing_on_disk": [f for f in spec["records"]
                                if not (BASE / f).exists()]}
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
