"""
test/test_cycle_report_series_breaks.py — a series break never takes the cycle report down.

24 Sep 2026: the 15:14 cycle logged "cycle_report -> FAILED: AttributeError: 'str'
object has no attribute 'get'" and wrote no report. core/cycle_report.to_markdown
read measured_effect as a dict of before/after numbers, which is the shape of a
'tree' break. config/series_breaks.json has also carried 'instrument' breaks since
18 Sep, whose measured_effect is prose by the file's own contract.

Failure shapes, before the happy path:
  * an instrument break (prose measured_effect) raising instead of rendering;
  * a tree break with a prose measured_effect raising instead of being refused by
    name, or being refused silently (no note_failure, nothing in the report).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import cycle_report, phase_tracker  # noqa: E402

INSTRUMENT = {
    "id": "2026-09-17-energy-total-final-not-electricity", "break_kind": "instrument",
    "date_utc": "2026-09-17", "rule": "1.3", "cause": "ENERGY series swapped",
    "config_fingerprint_before": "abc", "config_fingerprint_after": "abc",
    "instrument_before": "EG.ELC.RNEW.ZS", "instrument_after": "EG.FEC.RNEW.ZS",
    "measured_effect": "World Bank WLD, verified against the live API on 17 Sep 2026: "
                       "EG.ELC.RNEW.ZS latest 27.8357; EG.FEC.RNEW.ZS 2020 = 19.7355641050053.",
    "why": "the axis names total final energy",
}


def test_a_prose_measured_effect_renders_or_is_refused_by_name(monkeypatch):
    failures = []
    monkeypatch.setattr(phase_tracker, "note_failure", lambda step, exc: failures.append((step, str(exc))))

    lines = "\n".join(cycle_report._series_break_lines(INSTRUMENT))
    assert "EG.ELC.RNEW.ZS → EG.FEC.RNEW.ZS" in lines and "27.8357" in lines
    assert failures == [], "a valid instrument break was refused"

    tree_with_prose = {**INSTRUMENT, "id": "bad-tree", "break_kind": "tree"}
    lines = "\n".join(cycle_report._series_break_lines(tree_with_prose))
    assert "ОТКАЗАН ЗАПИС" in lines and "'bad-tree'" in lines
    assert failures and failures[0][0] == "cycle_report" and "bad-tree" in failures[0][1]
