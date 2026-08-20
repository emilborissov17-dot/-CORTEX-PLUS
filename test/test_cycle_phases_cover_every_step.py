#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_cycle_phases_cover_every_step.py — THE MAP MUST MATCH THE TERRITORY.

WHY THIS EXISTS
----------------
config/cycle_phases.json groups the cycle's 53 beat() calls into 7 phases so a
failure costs one phase instead of a whole 1h47m run. That grouping is only
worth something if it is COMPLETE. A step that belongs to no phase cannot be
re-run by --only or --from; it would simply be skipped, silently, forever.

So this test does not read the phase file and check it against itself. It
re-parses fast_cycle_runner.py for every beat() call and demands that the two
agree in both directions:

    every beat in the code   -> in exactly one phase
    every step in the phases -> a beat that really exists in the code

IDENTITY IS (name, index), NOT name
------------------------------------
body_scan runs twice: index 0 in A_ORIENT (can this machine start?) and index
13 in E_PROPOSE (what should the body do next?). 53 calls, 52 distinct names.
Keying by name alone cannot express that, and a test that asserted "52 names,
52 assignments" would have to either drop a real step or invent a phantom one.

NEGATIVE CONTROL (proven both ways before commit)
--------------------------------------------------
Delete any step from config/cycle_phases.json and
test_every_beat_in_the_runner_belongs_to_exactly_one_phase goes red, naming the
step that lost its home. Restore it and it goes green.

    venv\\Scripts\\python.exe -m pytest test/test_cycle_phases_cover_every_step.py -v
"""
from __future__ import annotations

import collections
import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNNER = REPO / "fast_cycle_runner.py"
PHASES_FILE = REPO / "config" / "cycle_phases.json"

BEAT_CALL = re.compile(r'beat\("([^"]+)",\s*"([^"]+)"')


def beats_in_the_runner() -> list[tuple[str, str]]:
    """Every (name, index) the runner actually beats, in file order."""
    return BEAT_CALL.findall(RUNNER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def phases() -> dict:
    return json.loads(PHASES_FILE.read_text(encoding="utf-8"))["phases"]


@pytest.fixture(scope="module")
def mapped(phases) -> dict[tuple[str, str], str]:
    """{(name, index): phase} across the whole map."""
    out: dict[tuple[str, str], str] = {}
    for phase, body in phases.items():
        for step in body["steps"]:
            key = (step["name"], step["index"])
            assert key not in out, (
                f"{key} is claimed by both {out[key]} and {phase} — a step may "
                f"belong to exactly one phase or --from would run it twice"
            )
            out[key] = phase
    return out


# ---------------------------------------------------------------------------
# (a) Coverage, both directions
# ---------------------------------------------------------------------------

def test_every_beat_in_the_runner_belongs_to_exactly_one_phase(mapped):
    """THE NEGATIVE CONTROL. Remove a step from the phase map and this fails."""
    orphans = [b for b in beats_in_the_runner() if b not in mapped]

    assert not orphans, (
        f"\n"
        f"  {len(orphans)} step(s) in fast_cycle_runner.py belong to NO phase:\n"
        + "".join(f"    beat({n!r}, {i!r})\n" for n, i in orphans)
        + f"  An unmapped step cannot be re-run by --only or --from. It would be\n"
          f"  skipped without anyone noticing. Add it to config/cycle_phases.json.\n"
    )


def test_no_phase_claims_a_step_that_does_not_exist(mapped):
    """The other direction: a renamed or deleted beat must not linger in the map,
    or --from would wait for a step that can never run."""
    real = set(beats_in_the_runner())
    phantom = [k for k in mapped if k not in real]

    assert not phantom, (
        f"\n"
        f"  config/cycle_phases.json claims steps the runner does not have:\n"
        + "".join(f"    {n!r} at index {i!r} (phase {mapped[(n, i)]})\n"
                  for n, i in phantom)
        + f"  A beat was renamed, re-indexed or deleted and the map was not told.\n"
    )


def test_the_counts_agree(mapped):
    """53 beat() calls carrying 52 distinct names — the duplicate is body_scan,
    which genuinely runs twice. Pinned so a change to either number is noticed."""
    beats = beats_in_the_runner()
    names = [n for n, _ in beats]
    duplicated = sorted(n for n, c in collections.Counter(names).items() if c > 1)

    assert len(beats) == len(mapped)
    assert len(set(names)) == len(beats) - 1
    assert duplicated == ["body_scan"], (
        f"a second step now runs twice: {duplicated}. That is allowed, but the "
        f"phase map must place each occurrence deliberately — check both indices."
    )


# ---------------------------------------------------------------------------
# (b) The map is ordered and contiguous
# ---------------------------------------------------------------------------

def test_steps_are_in_execution_order_within_each_phase(phases):
    """--only must run a phase in the order the runner would have."""
    order = {b: n for n, b in enumerate(beats_in_the_runner())}
    for phase, body in phases.items():
        positions = [order[(s["name"], s["index"])] for s in body["steps"]]
        assert positions == sorted(positions), (
            f"{phase} lists its steps out of execution order: {body['steps']}"
        )


def test_phases_do_not_interleave(phases):
    """Each phase must be a contiguous run of the cycle. If two phases interleave,
    resuming from one of them cannot mean anything."""
    order = {b: n for n, b in enumerate(beats_in_the_runner())}
    spans = {}
    for phase, body in phases.items():
        positions = [order[(s["name"], s["index"])] for s in body["steps"]]
        spans[phase] = (min(positions), max(positions))
        assert positions == list(range(spans[phase][0], spans[phase][1] + 1)), (
            f"{phase} is not contiguous — another phase's steps run inside it"
        )

    ordered = sorted(spans.items(), key=lambda kv: kv[1][0])
    for (a, (_, a_end)), (b, (b_start, _)) in zip(ordered, ordered[1:]):
        assert a_end + 1 == b_start, f"{a} and {b} overlap or leave a gap between them"


def test_the_declared_index_range_matches_the_steps(phases):
    for phase, body in phases.items():
        first, last = body["steps"][0]["index"], body["steps"][-1]["index"]
        assert body["index_range"] == [first, last], (
            f"{phase} declares index_range {body['index_range']} but its steps run "
            f"{first}..{last}"
        )


# ---------------------------------------------------------------------------
# (c) requires / produces are usable
# ---------------------------------------------------------------------------

def test_every_phase_declares_requires_and_produces(phases):
    for phase, body in phases.items():
        assert isinstance(body["requires"], list)
        assert body["produces"], (
            f"{phase} promises nothing, so its report can never be PARTIAL and the "
            f"phase can never be shown to have failed quietly"
        )


def test_the_first_phase_requires_nothing_and_the_rest_require_something(phases):
    ordered = list(phases)
    assert phases[ordered[0]]["requires"] == [], (
        f"{ordered[0]} runs first — it cannot require an artifact of this cycle"
    )
    for phase in ordered[1:]:
        assert phases[phase]["requires"], (
            f"{phase} requires nothing, so --from {phase} would start on an empty "
            f"repo and produce confident nonsense"
        )


def test_what_a_phase_requires_is_produced_by_an_earlier_phase(phases):
    """A require nobody produces can never be satisfied, and --from would refuse
    forever."""
    ordered = list(phases)
    produced_so_far: set[str] = set()
    for phase in ordered:
        for need in phases[phase]["requires"]:
            assert need in produced_so_far, (
                f"{phase} requires {need!r}, which no earlier phase produces. "
                f"--from {phase} could never be satisfied."
            )
        produced_so_far.update(phases[phase]["produces"])
