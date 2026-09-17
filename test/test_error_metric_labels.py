"""A number must be printed under the name of the statistic that produced it.

THE DEFECT, 17 Sep 2026. Two reports carried two different numbers for one quantity,
both labelled Brier, both saying n=60:

    AGI_14_SCOREBOARD.md     Brier self_failure 0.26  vs 0.5351
    PROPHECY_SCOREBOARD.md   self_failure brier 0.176 vs 0.3202

Recomputed from the sealed predictions in the ledger, both reproduce exactly:

    MEAN ABSOLUTE ERROR   learner 0.2600  baseline 0.5351
    BRIER (mean squared)  learner 0.1760  baseline 0.3202

experiments/prophecy/scoreboard.py:103 squares the error — that is a Brier score.
prophecy_ledger._abs_err() takes the absolute value — that is MAE.
scripts/agi_scoreboard.py read `learner_mean_err`, the MAE, and printed the word
Brier over it. They are consistent with each other precisely because squared error
is at most absolute error on [0,1], which is why nobody noticed: both numbers looked
plausible and both pointed the same way.

WHAT THIS FILE GUARDS is narrow and mechanical: the word "Brier" must not be printed
next to a value that came from _abs_err. It does NOT check that the prose is nice, and
it is not a grep over documentation — it drives the row builder with known values and
reads what comes out.

The finding was never in doubt. The learner beats the control by a wide margin on
either metric. Only the label was false, and a false label on a true number is the
kind of thing that survives for months because everything about it looks right.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "experiments" / "prophecy"))

import agi_scoreboard as A     # noqa: E402


# The two statistics, computed here so the test does not depend on either module's
# spelling of them. These are the definitions, not a copy of the implementations.
def _mae(pairs):
    return sum(abs(p - a) for p, a in pairs) / len(pairs)


def _brier(pairs):
    return sum((p - a) ** 2 for p, a in pairs) / len(pairs)


PAIRS = [(0.9, 1.0), (0.2, 0.0), (0.7, 0.0), (0.4, 1.0), (0.55, 1.0)]


def test_the_two_statistics_are_actually_different():
    """If MAE and Brier ever coincide on this fixture the rest of the file proves
    nothing, so it is asserted rather than assumed."""
    assert abs(_mae(PAIRS) - _brier(PAIRS)) > 0.05


def _point7(learner, baseline, scored=60):
    """Build scoreboard row 7 with a known learner/baseline pair.

    Uses the REAL bundle and substitutes only self_failure's two error values. An
    earlier version hand-built a minimal dict, rows() raised on the parts it did not
    contain, and the guard SKIPPED — a guard that skips is decoration, so it reads
    the live bundle instead and is skipped only if that is genuinely unavailable.
    """
    try:
        g = A.gather()
    except Exception as e:                                       # noqa: BLE001
        pytest.skip(f"the live bundle cannot be gathered here: {e}")
    sf = dict((g.get("ledger", {}).get("by_kind") or {}).get("self_failure") or {})
    sf.update({"learner_mean_err": learner, "baseline_mean_err": baseline,
               "scored": scored})
    g = {**g, "ledger": {**g.get("ledger", {}),
                         "by_kind": {**(g.get("ledger", {}).get("by_kind") or {}),
                                     "self_failure": sf}}}
    return next((r for r in A.rows(g) if r["point"] == 7), None)


def test_row_seven_does_not_call_an_absolute_error_a_brier_score():
    """THE GUARD. learner_mean_err is _abs_err's output — mean ABSOLUTE error. The
    row may print it, and may not print the word Brier over it."""
    row = _point7(_mae(PAIRS), _brier(PAIRS))
    if row is None:
        pytest.skip("row 7 not produced by this fixture")
    number = row["number"]
    assert "brier" not in number.lower(), (
        f"row 7 prints the word 'Brier' over learner_mean_err, which is "
        f"prophecy_ledger._abs_err — a mean ABSOLUTE error. Either label it MAE, or "
        f"change the row to read the real Brier from "
        f"experiments/prophecy/scoreboard.py. Row reads: {number!r}")


def test_row_seven_names_the_statistic_it_prints():
    """Not merely 'does not say Brier' — it has to say what it IS. A row that named
    no statistic would pass the test above and tell a reader nothing."""
    row = _point7(0.26, 0.5351)
    if row is None:
        pytest.skip("row 7 not produced by this fixture")
    assert "mae" in row["number"].lower(), \
        f"row 7 prints two error values under no named statistic: {row['number']!r}"


def test_the_source_line_reads_the_field_this_test_assumes():
    """Pins the wiring the guard depends on. If row 7 stopped reading
    learner_mean_err, this file would be guarding something that no longer happens
    and would pass for the wrong reason."""
    src = (REPO / "scripts" / "agi_scoreboard.py").read_text(encoding="utf-8")
    i = src.index("add(7,")
    line = src[i:src.index("\n", i + 200)]
    assert "learner_mean_err" in line, \
        "row 7 no longer reads learner_mean_err — re-check what this test is guarding"


def test_abs_err_is_still_absolute_not_squared():
    """The other end of the wire. If _abs_err ever became squared, the MAE label
    would turn false in the opposite direction and this file must notice."""
    import prophecy_ledger as pl
    assert pl._abs_err(0.7, 0.0) == pytest.approx(0.7), \
        "_abs_err no longer returns an absolute error; row 7's MAE label is now wrong"
    assert pl._abs_err(0.7, 0.0) != pytest.approx(0.49), "it is returning a square"
