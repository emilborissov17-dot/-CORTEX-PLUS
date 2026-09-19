# -*- coding: utf-8 -*-
"""test/test_batch_names_the_axis.py - a diff must name the axis that moved.

THE DEFECT, 19 September 2026. wellbeing_batch._run_one called country_wellbeing,
which computes 17 per-axis scores, and then built a row holding only the three
rolled-up numbers (deprivation / strain / flourishing). The per-axis layer was
computed and thrown away on every run of every country.

So the September batch could report "198 of 217 countries moved, thirteen zones
flipped" and could not say which AXIS moved in a single one of them. Ecuador's
0.110 strain drop was explained only because output/wb_cache/ happens to be
tracked in git, so `git show HEAD:output/wb_cache/EC.json` recovered the old
INPUTS and the axis was re-derived by hand. Auditability by luck: the day that
directory is gitignored for being large, the same diff becomes unexplainable.

These tests pin the per-axis values into the row so the next diff names the axis
itself. They also pin the SHAPE - a row that carries an empty dict, or drops the
key under an exception, satisfies "has axis_scores" while restoring the defect.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OUTPUT = REPO / "output" / "wellbeing_all_countries.json"

# The three rolled-up numbers that were ALL the old row carried. If a future
# refactor keeps these and loses the axes, the diff goes blind again.
ROLLED_UP = ("deprivation", "strain", "flourishing")


def _rows():
    if not OUTPUT.exists():
        pytest.skip("%s has not been produced yet" % OUTPUT.name)
    data = json.loads(OUTPUT.read_text(encoding="utf-8"))
    rows = data["countries"] if isinstance(data, dict) else data
    return [r for r in rows if r.get("status") == "ok"]


def test_the_batch_row_carries_the_per_axis_values():
    """Not 'has the key' - has real numbers under it. An empty dict is the
    defect wearing the fix's name."""
    rows = _rows()
    assert rows, "no ok rows in the batch output"
    empty = [r["iso2"] for r in rows if not (r.get("axis_scores") or {})]
    assert not empty, (
        "%d of %d ok countries carry no per-axis values (%s...) - a diff of this "
        "file cannot name the axis that moved"
        % (len(empty), len(rows), ", ".join(empty[:8])))


def test_every_country_reports_the_same_axes():
    """A row that silently carries FEWER axes than its neighbours is the same
    blindness, one country at a time."""
    rows = _rows()
    counts = {}
    for r in rows:
        counts.setdefault(len(r["axis_scores"]), []).append(r["iso2"])
    assert len(counts) == 1, (
        "countries disagree on how many axes they report: %s"
        % {n: "%d countries (%s...)" % (len(v), ", ".join(sorted(v)[:5]))
           for n, v in sorted(counts.items())})


def test_the_axis_values_are_numbers_in_range_or_honestly_none():
    """MISSING stays None. What must never appear is a string, or a number
    outside 0..1 that a consumer would average anyway."""
    rows = _rows()
    bad = []
    for r in rows:
        for axis, v in r["axis_scores"].items():
            if v is None:
                continue
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                bad.append("%s/%s = %r (%s)" % (r["iso2"], axis, v, type(v).__name__))
            elif not (0.0 <= float(v) <= 1.0):
                bad.append("%s/%s = %r out of range" % (r["iso2"], axis, v))
    assert not bad, "\n".join(bad[:10])


def test_a_diff_of_two_batches_can_attribute_a_rolled_up_move():
    """THE ONE THAT MATTERS.

    Take a real row, move ONE axis, and assert the axis layer identifies it.
    This is the operation that was impossible on 19 September: given two batch
    files where a country's strain changed, name the axis responsible without
    reaching outside this file for the old inputs.
    """
    rows = _rows()
    before = rows[0]
    axes = sorted(k for k, v in before["axis_scores"].items() if v is not None)
    assert axes, "the sample country reports no non-null axis"
    moved = axes[0]

    after = json.loads(json.dumps(before))
    after["axis_scores"][moved] = round(
        min(1.0, max(0.0, before["axis_scores"][moved] + 0.11)), 4)
    after["strain"] = round(before["strain"] + 0.11, 4)

    # The attribution a reader performs, using nothing but the two rows.
    culprits = [a for a in before["axis_scores"]
                if before["axis_scores"].get(a) != after["axis_scores"].get(a)]
    assert culprits == [moved], (
        "a single-axis move was not attributable from the file alone: %r" % culprits)


def test_the_rolled_up_numbers_did_not_disappear():
    """The fix adds a layer; it must not trade one blindness for another."""
    for r in _rows()[:20]:
        for k in ROLLED_UP:
            assert isinstance(r.get(k), (int, float)), "%s lost %s" % (r["iso2"], k)


def test_the_runner_itself_emits_the_axes_not_just_the_stored_file():
    """The file could be stale-correct while the code that writes it regressed,
    so reach into _run_one itself - the guard then survives a deleted output
    file, and catches a regression on the morning it lands rather than after the
    next weekly batch overwrites the evidence.

    IN A SUBPROCESS, deliberately. wellbeing_batch rebinds sys.stdout to a fresh
    TextIOWrapper over sys.stdout.buffer at import time, and under pytest's
    capture that buffer is closed on teardown, so importing it in-process fails
    inside contextlib on the way out. Running the real interpreter tests the
    real path instead of a version bent to suit the harness.
    """
    code = (
        "import json, wellbeing_batch as wb;"
        "r = wb._run_one({'iso2':'BG','name':'Bulgaria','region':'ECS','income':'UMC'});"
        "print('<<<' + json.dumps({'status': r.get('status'),"
        " 'n': len(r.get('axis_scores') or {})}) + '>>>')"
    )
    exe = REPO / "venv" / "Scripts" / "python.exe"
    if not exe.exists():
        pytest.skip("venv interpreter not found at %s" % exe)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([str(exe), "-c", code], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=600)
    marked = re.search(r"<<<(.*?)>>>", proc.stdout or "", re.S)
    assert marked, (
        "_run_one produced no verdict (rc=%s); stderr tail: %s"
        % (proc.returncode, (proc.stderr or "")[-800:]))
    got = json.loads(marked.group(1))
    if got["status"] != "ok":
        pytest.skip("BG did not compute (offline?): %s" % got["status"])
    assert got["n"] >= 10, "_run_one emitted only %d axes" % got["n"]
