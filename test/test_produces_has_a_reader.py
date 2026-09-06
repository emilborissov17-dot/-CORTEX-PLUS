# -*- coding: utf-8 -*-
"""
Every path the cycle promises to leave behind must have a NAMED reader.

A file the cycle writes and nothing reads is a file the cycle does not need. The rule
from 6 Sep is that nothing new is written without a named reader in the same commit,
and this is what makes the rule enforceable rather than aspirational.

WHY A DECLARATION AND NOT A SCAN. Four static classifiers were written on 6 Sep and all
four were wrong, each in a different direction: literal basenames gave 176 false
"never read"; a parent-directory walk gave 0; a read/write window classifier gave 17, of
which the entire snapshot family was false because they are read by
rglob("*_snapshot_latest.json"); and a glob-aware version gave 0 again because "*.json"
matches everything. Even writer detection failed - memory/belief_state.json reads as
"nothing writes it" because the write goes through a module constant far from the
literal. Reads in this repo happen through constants, through globs and through helpers
far from the path. The question is not decidable by grep here, so it is DECLARED, and
the 21 entries nobody has confirmed yet are carried BY NAME rather than quietly counted
as fine.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PHASES = REPO / "config" / "cycle_phases.json"
READERS = REPO / "config" / "produces_readers.json"


def _promised() -> dict:
    d = json.loads(PHASES.read_text(encoding="utf-8"))
    out = {}
    for phase, body in d["phases"].items():
        for p in body.get("produces", []) or []:
            out.setdefault(p, []).append(phase)
    return out


def _declared() -> dict:
    return json.loads(READERS.read_text(encoding="utf-8"))["paths"]


def test_every_promised_path_has_an_entry():
    """THE RULE. A produces path with no entry here is a file nobody has said they
    need."""
    missing = sorted(set(_promised()) - set(_declared()))
    assert not missing, (
        "these paths are promised by config/cycle_phases.json and have NO entry in "
        "config/produces_readers.json. Name a reader, or stop producing them:\n  "
        + "\n  ".join(missing))


def test_every_entry_names_at_least_one_reader():
    empty = sorted(p for p, v in _declared().items() if not v.get("readers"))
    assert not empty, (
        "these paths are declared with an EMPTY reader list, which is the same as no "
        "declaration:\n  " + "\n  ".join(empty))


def test_the_declaration_has_not_drifted_from_the_phases_file():
    """A path that stops being produced must be removed here too, or the declaration
    slowly becomes a list of files that no longer exist."""
    stale = sorted(set(_declared()) - set(_promised()))
    assert not stale, (
        "these paths are declared but no longer promised by config/cycle_phases.json:\n  "
        + "\n  ".join(stale))


def test_the_declared_phases_match_the_phases_file():
    promised, declared = _promised(), _declared()
    wrong = {p: (declared[p].get("phases"), promised[p])
             for p in promised if p in declared
             and sorted(declared[p].get("phases", [])) != sorted(promised[p])}
    assert not wrong, f"phase attribution drifted: {wrong}"


def test_the_unverified_entries_are_carried_by_name():
    """THE POINT OF THE STATUS FIELD. 21 of the 47 readers were seeded by a scan that
    has been wrong four times and have NOT been confirmed by a human. They are allowed
    to exist; they are not allowed to disappear into a count. This test prints them, so
    every run of the suite re-states the debt."""
    unver = sorted(p for p, v in _declared().items() if v.get("status") == "UNVERIFIED")
    total = len(_declared())
    print(f"\nUNVERIFIED readers: {len(unver)} of {total} — seeded by a scan, "
          f"not confirmed by a human:")
    for p in unver:
        print(f"  {p}  <- {', '.join(_declared()[p]['readers'])}")
    # The count is asserted so that adding a new UNVERIFIED entry, or silently
    # promoting one to 'verified' without doing the work, both fail here.
    assert len(unver) == 21, (
        f"the UNVERIFIED count changed from 21 to {len(unver)}. If a reader was "
        f"confirmed, lower this number in the same commit; if a path was added, "
        f"confirm its reader instead of raising it.")


def test_status_values_are_from_the_declared_set():
    allowed = {"glob", "named", "UNVERIFIED"}
    bad = {p: v.get("status") for p, v in _declared().items()
           if v.get("status") not in allowed}
    assert not bad, f"unknown status values: {bad}"
