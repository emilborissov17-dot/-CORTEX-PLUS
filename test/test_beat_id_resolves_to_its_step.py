# -*- coding: utf-8 -*-
"""test/test_beat_id_resolves_to_its_step.py — a beat names the boundary it is inside.

THE DEFECT, 19 September 2026. Six step-boundary comments in fast_cycle_runner.py
did not sit above their own beat:

    # ── 12.6. Goal score calculator ──
    # ── 12.56. THE INDICATOR HISTORY STARTS TONIGHT ──
    ...
    beat("axis_history", "12.56")        <- eleven lines before 12.6's own beat

Four headings (12.45, 12.6, 12.7, 25.37) were printed above the PRECEDING step's
block, and two were not steps at all: `# ── 2. ...` was stale (its work moved to
2.75 and no beat(..., "2") exists) and `# ── 25.4. ...` was a section heading over
two real steps.

WHAT IT DID AND DID NOT COST. It did NOT mis-key the watchdog. supervisor
.ceiling_for() takes beat["step"], the NAME, and config/scheduler.json's
step_ceilings_sec had seventeen keys (sixteen since 26 Sep 2026), all names and no fractional ids — the
step_index is carried for the log and nothing else. The triage report that ranked
this first said otherwise; it repeated the old test's docstring instead of reading
ceiling_for, and this file records the correction.

What it DID cost is worse for being quiet: because the mis-parse handed the wrong
beat to each heading, `test_every_step_boundary_beats` passed for `2` and `25.4`,
which have NO beat of their own. A test whose whole job is finding un-beaten
boundaries could not see two of them. And 2.75, 25.35 and 25.36 — three steps that
DO beat — had no heading at all, so the map of the cycle was wrong in both
directions at once.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RUNNER = REPO / "fast_cycle_runner.py"
STEP_COMMENT_RE = re.compile(r'^    # ── ([\d.]+)\.\s*(.+?)\s*─*\s*$')
BEAT_RE = re.compile(r'^\s*beat\(\s*"([^"]+)"\s*,\s*"([\d.]+)"')


def _lines():
    return RUNNER.read_text(encoding="utf-8").splitlines()


def _beats():
    """(line_no, name, id) for every literal beat() call in the runner."""
    out = []
    for i, l in enumerate(_lines()):
        m = BEAT_RE.match(l)
        if m:
            out.append((i, m.group(1), m.group(2)))
    return out


def _boundaries():
    """(line_no, id, desc) for every step-boundary comment."""
    out = []
    for i, l in enumerate(_lines()):
        m = STEP_COMMENT_RE.match(l)
        if m:
            out.append((i, m.group(1), m.group(2)))
    return out


# ── 1. a beat between two steps carries the ENCLOSING boundary's id ─────────

def test_a_beat_carries_the_id_of_the_boundary_it_is_inside_not_a_fraction():
    """THE ONE THIS FILE EXISTS FOR.

    For every beat, the nearest boundary ABOVE it is the boundary it is inside.
    That boundary's id must be the beat's own id. Before the fix, six beats were
    enclosed by a heading belonging to a different step, which is exactly the
    'a beat emitted between two steps carries a fraction' shape.
    """
    bounds = _boundaries()
    assert bounds, "no step boundaries found — did the comment format change?"
    wrong = []
    for line_no, name, bid in _beats():
        above = [b for b in bounds if b[0] < line_no]
        if not above:
            continue
        enclosing = above[-1]
        if enclosing[1] != bid:
            wrong.append(
                "beat(%r, %r) at line %d is enclosed by boundary %s (%s) at line %d"
                % (name, bid, line_no + 1, enclosing[1], enclosing[2][:40],
                   enclosing[0] + 1))
    assert not wrong, (
        "these beats report an id that is not the boundary enclosing them:\n  "
        + "\n  ".join(wrong))


def test_every_boundary_id_is_claimed_by_a_beat_of_its_own():
    """The other direction: a heading in the `# ── <id>. ──` form asserts that a
    step begins there, so some beat must carry that id. `2` and `25.4` failed
    this silently, because each was handed a neighbour's beat."""
    ids = {bid for _l, _n, bid in _beats()}
    orphan = [(b[1], b[2][:50]) for b in _boundaries() if b[1] not in ids]
    assert not orphan, (
        "these boundaries claim a step that never beats — either give them a "
        "beat or stop writing them in the step-boundary form:\n  "
        + "\n  ".join("%s  %s" % o for o in orphan))


def test_every_beat_id_has_a_boundary_of_its_own():
    """And the reverse: a step that beats must be findable in the map. 2.75,
    25.35 and 25.36 beat for themselves and had no heading at all."""
    bids = {b[1] for b in _boundaries()}
    unheaded = sorted({(bid, name) for _l, name, bid in _beats() if bid not in bids})
    assert not unheaded, (
        "these steps beat but appear nowhere in the boundary map, so a reader "
        "scanning the comments cannot find them:\n  "
        + "\n  ".join("%s  %s" % u for u in unheaded))


def test_no_two_boundaries_are_adjacent_with_no_beat_between_them():
    """The mechanism of the original defect, pinned directly: two headings in a
    row means the first one's step has no body, and its beat — if any — belongs
    to the second."""
    lines = _lines()
    bounds = _boundaries()
    bad = []
    for k in range(len(bounds) - 1):
        i, bid, desc = bounds[k]
        j = bounds[k + 1][0]
        between = lines[i + 1:j]
        if not any(BEAT_RE.match(b) for b in between):
            if not any(b.strip() and not b.lstrip().startswith("#") for b in between):
                bad.append("%s (%s) at line %d is followed by boundary %s with "
                           "no beat and no code between them"
                           % (bid, desc[:36], i + 1, bounds[k + 1][1]))
    assert not bad, "\n  ".join(bad)


# ── 2. the watchdog resolves a beat to the step its boundary names ──────────

def test_the_watchdog_resolves_a_beat_to_the_same_step_the_boundary_names():
    """supervisor.ceiling_for() must land on the step that is actually running.

    It keys on beat["step"] — the NAME — so this walks every beat in the runner,
    hands the recorded heartbeat shape to ceiling_for, and requires the ceiling
    it returns to be the one configured for THAT step rather than a neighbour's
    or the default standing in for a missing key.
    """
    sys.path.insert(0, str(REPO))
    import supervisor as sup

    cfg = {"step_ceilings_sec": {"_default": 900,
                                 "goal_score_calculator": 111,
                                 "axis_history": 222,
                                 "metta_column": 333}}
    for name, expected in (("goal_score_calculator", 111),
                           ("axis_history", 222),
                           ("metta_column", 333)):
        hb = {"step": name, "step_index": "irrelevant"}
        got = sup.ceiling_for(hb.get("step"), cfg)
        assert got == expected, (
            "the watchdog gave %s a ceiling of %ss, not its own %ss"
            % (name, got, expected))


def test_the_ceiling_ignores_the_fractional_index_entirely():
    """The correction to the triage, made mechanical.

    If the ceiling were keyed on the fractional id, passing one would find a
    ceiling and passing the name would not. It is the other way round, and
    config/scheduler.json carries no fractional keys at all.
    """
    sys.path.insert(0, str(REPO))
    import supervisor as sup

    cfg = {"step_ceilings_sec": {"_default": 900, "axis_history": 222}}
    assert sup.ceiling_for("axis_history", cfg) == 222
    # a fractional id is not a key and must fall to the default, never to some
    # other step's number
    assert sup.ceiling_for("12.56", cfg) == 900

    live = json.loads((REPO / "config" / "scheduler.json").read_text(encoding="utf-8"))
    keys = list(live.get("step_ceilings_sec", {}))
    fractional = [k for k in keys if k.replace(".", "").isdigit()]
    assert not fractional, (
        "config/scheduler.json now keys ceilings by fractional id (%r). If that "
        "is intended, the beat ids become load-bearing and this file's premise "
        "changes." % fractional[:5])


def test_every_beat_name_in_the_runner_is_resolvable_by_the_watchdog():
    """A beat whose NAME has no ceiling entry silently gets _default. That is
    allowed, but it must be the default and never another step's budget."""
    sys.path.insert(0, str(REPO))
    import supervisor as sup

    live = json.loads((REPO / "config" / "scheduler.json").read_text(encoding="utf-8"))
    ceilings = live.get("step_ceilings_sec", {})
    default = int(ceilings.get("_default", 900))
    for _l, name, bid in _beats():
        got = sup.ceiling_for(name, {"step_ceilings_sec": ceilings})
        if name in ceilings:
            continue                      # has its own, checked above
        assert got == default or got < default, (
            "beat %r (id %s) resolved to %ss, which is neither its own entry "
            "nor the default %ss" % (name, bid, got, default))
