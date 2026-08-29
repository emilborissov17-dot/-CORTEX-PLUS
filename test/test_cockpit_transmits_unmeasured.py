# -*- coding: utf-8 -*-
"""ITEM 33 — the API stops hiding unmeasured points.

ITEM 12(c) stopped memory/trend_tracker.py deleting points whose metrics are
empty, and marked them "measured": false. Nothing rendered the marker, so the
invisibility moved from the write path to the read path — cockpit/server.py:1337
filtered every score-null point out of the history array and the plot simply
got shorter with no explanation.

    1337:  history = [h for h in (hist_blob.get(name) or [])
    1338:             if isinstance(h, dict) and isinstance(h.get("score"), (int, float))]

SCOPE, set by Kimi and deliberately narrow: "ITEM 33's scope is the
data-to-API boundary ... The front-end is a distinct consumer with its own test
surface and release cadence." So this item makes the API TRANSMIT the truth. It
does not make a human see it — that is ITEM 36, and until 36 lands the operator
sees no difference.

THE TRAP THIS ITEM HAD TO AVOID, caught by Kimi before it was written: `points`
is consumed at five places, and two of them test bool(points) —
    1362:  "known": latest is not None or bool(points)
    1387:  "empty_because": (None if (latest is not None or points) else ...)
so simply unfiltering would make an axis with ONLY unmeasured points report
known:true and empty_because:null. It would read as KNOWN while carrying no
measurement — a new lie, created by the fix for the old one.

AND A THIRD SITE NEITHER KIMI NOR THE THIRD SEAT NAMED, found by opening the
file: :1380 takes points[-1].get("score_source"). Once unfiltered, points[-1] is
the unmeasured point, so the axis would advertise score_source
'fallback_metric_mean' while holding no score at all. Same class of lie, same
commit.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from cockpit import server as srv  # noqa: E402

LIVE_HIST = BASE / "memory" / "axis_history.json"
_LIVE_BEFORE = (hashlib.sha256(LIVE_HIST.read_bytes()).hexdigest()
                if LIVE_HIST.exists() else "ABSENT")

MEASURED = {"date": "2026-08-28", "score": 55.0, "score_source": "engine",
            "metrics": {"co2": 1.0}, "measured": True}
UNMEASURED = {"date": "2026-08-29", "score": None,
              "score_source": "fallback_metric_mean", "metrics": {},
              "measured": False}


def _axis(monkeypatch, series, latest=None):
    """Drive api_axis against a fixed history, touching no live file."""
    real = srv._read_json

    def fake(path, default=None):
        p = str(path).replace("\\", "/")
        if p.endswith("memory/axis_history.json"):
            return {"ENERGY_REVIEW": series}
        if p.endswith("output/cortex_scores_latest.json"):
            # the endpoint reads scores_blob["scores"], not the top level
            return {"scores": {"ENERGY_REVIEW": latest}} if latest is not None else {}
        return real(path, default)

    monkeypatch.setattr(srv, "_read_json", fake)
    return srv.app.test_client().get("/api/axis/ENERGY_REVIEW").get_json()


# ── the requirement ────────────────────────────────────────────────────────

def test_unmeasured_points_are_emitted_not_filtered(monkeypatch):
    d = _axis(monkeypatch, [MEASURED, UNMEASURED])
    dates = [h["date"] for h in d["history"]]
    assert dates == ["2026-08-28", "2026-08-29"], (
        "the unmeasured point was filtered out — the defect this item exists for")


def test_each_emitted_point_carries_the_measured_flag(monkeypatch):
    d = _axis(monkeypatch, [MEASURED, UNMEASURED])
    assert [h["measured"] for h in d["history"]] == [True, False]


def test_an_axis_with_only_unmeasured_points_returns_them(monkeypatch):
    d = _axis(monkeypatch, [UNMEASURED])
    assert len(d["history"]) == 1
    assert d["history"][0]["measured"] is False
    assert d["history"][0]["score"] is None


# ── the lies the change would otherwise create ─────────────────────────────

def test_an_all_unmeasured_axis_is_not_reported_as_known(monkeypatch):
    """Kimi's WATCH. bool(points) would now be True for an axis holding nothing."""
    d = _axis(monkeypatch, [UNMEASURED])
    assert d["known"] is False, (
        "an axis whose every point is unmeasured is not KNOWN")


def test_an_all_unmeasured_axis_says_why_it_is_empty(monkeypatch):
    d = _axis(monkeypatch, [UNMEASURED])
    assert d["empty_because"], "empty_because went null on an axis with no measurement"
    assert "measure" in d["empty_because"].lower()


def test_an_all_unmeasured_axis_does_not_advertise_a_score_source(monkeypatch):
    """The third site: points[-1] is now the unmeasured point."""
    d = _axis(monkeypatch, [UNMEASURED])
    assert d["score_source"] is None, (
        "the axis advertised the score_source of a point that has no score")


def test_score_source_comes_from_the_last_measured_point(monkeypatch):
    d = _axis(monkeypatch, [MEASURED, UNMEASURED])
    assert d["score_source"] == "engine"


def test_a_live_score_still_makes_an_axis_known(monkeypatch):
    """known must not collapse to 'has measured history' — a current score counts."""
    d = _axis(monkeypatch, [UNMEASURED], latest={"score": 0.2})
    assert d["known"] is True
    assert d["empty_because"] is None


# ── the negative control ───────────────────────────────────────────────────

def test_a_fully_measured_axis_is_unchanged(monkeypatch):
    """Byte-for-byte, but for the additive flags. If this moves, the item has
    reached past its scope."""
    d = _axis(monkeypatch, [MEASURED, dict(MEASURED, date="2026-08-27")])
    assert d["known"] is True
    assert d["empty_because"] is None
    assert d["score_source"] == "engine"
    assert d["history_len"] == 2
    for h in d["history"]:
        assert h["measured"] is True
        assert set(h) == {"date", "score", "source", "measured"}


def test_history_len_still_matches_the_array_it_describes(monkeypatch):
    d = _axis(monkeypatch, [MEASURED, UNMEASURED])
    assert d["history_len"] == len(d["history"])


def test_the_measured_count_is_available_separately(monkeypatch):
    """history_len counts what is transmitted; a reader needs the measured count
    to know how much of it is real."""
    d = _axis(monkeypatch, [MEASURED, UNMEASURED, UNMEASURED])
    assert d["measured_len"] == 1
    assert d["unmeasured_len"] == 2


# ── live state ─────────────────────────────────────────────────────────────

def test_no_live_file_was_touched():
    after = (hashlib.sha256(LIVE_HIST.read_bytes()).hexdigest()
             if LIVE_HIST.exists() else "ABSENT")
    assert after == _LIVE_BEFORE
