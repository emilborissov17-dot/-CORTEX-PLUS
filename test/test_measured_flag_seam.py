# -*- coding: utf-8 -*-
"""THE SEAM between ITEM 12(c) and ITEM 33 — one writer, one reader, one meaning.

WHY THIS FILE EXISTS, and it is not a formality. ITEM 12(c) and ITEM 33 were
implemented in overlap and shared a single suite run. Kimi named the exact cost:
"a clean shared run means neither item was tested in isolation; an undetected
cross-file interaction could ship on a joint positive that future auditors
mistake for independent verification."

The interaction is concrete. memory/trend_tracker.py WRITES "measured";
cockpit/server.py READS it. A green shared run proves neither side broke its own
old tests. It does not prove the two agree about what the flag MEANS — and every
other test on both sides hand-writes the flag, so both could drift together and
stay green.

So this test never writes the flag by hand. It takes raw history in the shape
trend_tracker actually receives, passes it through retain(), and feeds THAT —
the writer's real output — to the reader. If the two ever disagree, this is the
only test that fails.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import server as srv  # noqa: E402
from memory import trend_tracker as tt  # noqa: E402

LIVE = BASE / "memory" / "axis_history.json"
_LIVE_BEFORE = hashlib.sha256(LIVE.read_bytes()).hexdigest() if LIVE.exists() else "ABSENT"

# The shapes trend_tracker really receives. NO "measured" key — that is the
# writer's job, and hand-writing it here would defeat the whole test.
RAW_MEASURED = {"date": "2026-08-28", "score": 55.0, "score_source": "engine",
                "metrics": {"co2": 1.0}}
RAW_EMPTY_DICT = {"date": "2026-08-29", "score": None,
                  "score_source": "fallback_metric_mean", "metrics": {}}
RAW_NO_KEY = {"date": "2026-08-30", "score": None,
              "score_source": "fallback_metric_mean"}


def _through_the_seam(monkeypatch, raw_series):
    """retain() writes the flag; the API reads it. Nothing in between."""
    written = tt.retain({"ENERGY_REVIEW": list(raw_series)})

    real = srv._read_json

    def fake(path, default=None):
        p = str(path).replace("\\", "/")
        if p.endswith("memory/axis_history.json"):
            return written
        if p.endswith("output/cortex_scores_latest.json"):
            return {}
        return real(path, default)

    monkeypatch.setattr(srv, "_read_json", fake)
    served = srv.app.test_client().get("/api/axis/ENERGY_REVIEW").get_json()
    return written["ENERGY_REVIEW"], served


def test_the_flag_written_is_the_flag_served(monkeypatch):
    written, served = _through_the_seam(
        monkeypatch, [RAW_MEASURED, RAW_EMPTY_DICT, RAW_NO_KEY])

    assert [e["measured"] for e in written] == [True, False, False], (
        "trend_tracker.retain() did not mark the points as expected")
    assert [h["measured"] for h in served["history"]] == [True, False, False], (
        "the API served a different answer than the writer wrote — the two "
        "sides of the seam disagree about what 'measured' means")
    assert [e["date"] for e in written] == [h["date"] for h in served["history"]], (
        "a point was lost or reordered crossing the seam")


def test_both_absence_shapes_survive_the_seam_identically(monkeypatch):
    """metrics {} and no metrics key must be indistinguishable end to end.
    The live file uses the first; a test written against the second matches
    nothing. If the writer and reader ever treat them differently, that
    difference would surface here and nowhere else."""
    _, served = _through_the_seam(monkeypatch, [RAW_EMPTY_DICT, RAW_NO_KEY])
    flags = [h["measured"] for h in served["history"]]
    assert flags == [False, False], flags


def test_an_all_unmeasured_axis_crosses_the_seam_as_not_known(monkeypatch):
    """The writer says every point is unmeasured; the reader must not call the
    axis KNOWN. This is the interaction Kimi's objection is about."""
    written, served = _through_the_seam(monkeypatch, [RAW_EMPTY_DICT, RAW_NO_KEY])
    assert all(e["measured"] is False for e in written)
    assert served["known"] is False
    assert served["measured_len"] == 0
    assert served["unmeasured_len"] == 2
    assert served["history_len"] == 2, "the points were dropped, not transmitted"
    assert served["score_source"] is None
    assert served["empty_because"], "an axis with no measurement must say so"


def test_a_measured_axis_crosses_the_seam_intact(monkeypatch):
    """The negative control. If this fails the seam is over-blocking."""
    _, served = _through_the_seam(monkeypatch, [RAW_MEASURED])
    assert served["known"] is True
    assert served["measured_len"] == 1
    assert served["unmeasured_len"] == 0
    assert served["score_source"] == "engine"
    assert served["empty_because"] is None


def test_the_live_file_was_not_touched():
    after = hashlib.sha256(LIVE.read_bytes()).hexdigest() if LIVE.exists() else "ABSENT"
    assert after == _LIVE_BEFORE
