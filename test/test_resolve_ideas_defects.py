# -*- coding: utf-8 -*-
"""ITEM 23 — three defects in tools/resolve_ideas.py, tests written first.

(a) _aliases() failed soft. A missing or malformed config returned empty dicts,
    which does not crash — it silently marks every idea UNMAPPED. A scorer that
    reports "we could not map this" when the truth is "the mapping file is gone"
    is the exact failure this queue exists to remove, inside the tool that
    grades the queue's own hypotheses.

(b) A verdict about a series is meaningless without the series it came from.
    Every row and the summary now carry points_total, axes_total,
    series_latest_date and series_sha256 — the way K1 carries basis_ts.

(c) MEASURED, not retuned: 82.8% of decided verdicts (HELD/BROKE) flip when the
    last point of each series is dropped, and NOT ONE HELD survives. Each row
    carries survives_leave_one_out so a fragile verdict is visibly fragile. The
    direction rule is NOT changed here; the measurement is the deliverable.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import sys

import pytest

BASE = pathlib.Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tools import resolve_ideas as ri  # noqa: E402


def _digest(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"


_LIVE_BEFORE = {p.as_posix(): _digest(p) for p in (ri.IDEAS, ri.OUT, ri.HISTORY,
                                                   ri.ALIAS_FILE)}


# ── (a) the alias file must not fail soft ──────────────────────────────────

def test_a_missing_alias_file_is_a_loud_refusal_naming_the_path(tmp_path, monkeypatch):
    missing = tmp_path / "not_here.json"
    monkeypatch.setattr(ri, "ALIAS_FILE", missing)
    with pytest.raises(Exception) as e:
        ri._aliases()
    assert "not_here.json" in str(e.value), (
        "the refusal must name the path a human has to go and look at")


def test_a_malformed_alias_file_is_a_loud_refusal_too(tmp_path, monkeypatch):
    bad = tmp_path / "aliases.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(ri, "ALIAS_FILE", bad)
    with pytest.raises(Exception) as e:
        ri._aliases()
    assert "aliases.json" in str(e.value)


def test_a_valid_but_empty_alias_map_is_accepted(tmp_path, monkeypatch):
    """THE NEGATIVE CONTROL. A human who deliberately aliases nothing must not
    be treated as a missing file — otherwise the fix trades one silent failure
    for a noisy refusal to do the right thing."""
    empty = tmp_path / "aliases.json"
    empty.write_text(json.dumps({"to_axis": {}, "to_branch": {}, "refused": {}}),
                     encoding="utf-8")
    monkeypatch.setattr(ri, "ALIAS_FILE", empty)
    al = ri._aliases()
    assert al == {"to_axis": {}, "to_branch": {}, "refused": {}}


def test_an_alias_file_of_the_wrong_shape_is_refused(tmp_path, monkeypatch):
    """Valid JSON is not a valid alias map. A list cannot answer to_axis.get()."""
    wrong = tmp_path / "aliases.json"
    wrong.write_text(json.dumps(["ENERGY", "WATER"]), encoding="utf-8")
    monkeypatch.setattr(ri, "ALIAS_FILE", wrong)
    with pytest.raises(Exception):
        ri._aliases()


def test_the_live_alias_file_still_loads():
    """The real one must satisfy the new contract, or the cycle step is dead."""
    al = ri._aliases()
    assert isinstance(al, dict)
    assert isinstance(al.get("to_axis"), dict)


# ── (b) every run carries its series state ─────────────────────────────────

def _fake_history(tmp_path, latest="2026-08-29", name="axis_history.json"):
    h = {"ENERGY_REVIEW": [{"date": "2026-08-20", "score": 10.0},
                           {"date": "2026-08-22", "score": 20.0},
                           {"date": latest, "score": 30.0}]}
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    p.write_text(json.dumps(h), encoding="utf-8")
    return p


def test_series_state_names_points_axes_latest_and_a_digest(tmp_path):
    p = _fake_history(tmp_path)
    st = ri._series_state(p)
    assert st["points_total"] == 3
    assert st["axes_total"] == 1
    assert st["series_latest_date"] == "2026-08-29"
    assert st["series_sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
    assert st["series_source"] == ri.SERIES_SOURCE


def test_the_digest_moves_when_the_series_moves(tmp_path):
    a = ri._series_state(_fake_history(tmp_path / "a"))
    b = ri._series_state(_fake_history(tmp_path / "b", latest="2026-08-30"))
    assert a["series_sha256"] != b["series_sha256"]
    assert a["series_latest_date"] != b["series_latest_date"]


def test_the_summary_carries_the_series_state(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "OUT", tmp_path / "out.jsonl")
    s = ri.run(dt.date(2026, 9, 30), False)["summary"]
    for k in ("points_total", "axes_total", "series_latest_date", "series_sha256"):
        assert k in s, f"the summary must carry {k} — a hit rate without it is not a number"
    assert s["points_total"] > 0


def test_every_written_row_carries_the_series_state(tmp_path, monkeypatch):
    out = tmp_path / "out.jsonl"
    monkeypatch.setattr(ri, "OUT", out)
    ri.run(dt.date(2026, 9, 30), True)
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert rows
    for r in rows:
        for k in ("points_total", "axes_total", "series_latest_date", "series_sha256"):
            assert k in r, f"row {r.get('idea_ts')} has no {k}"


# ── (c) leave-one-out fragility is visible per row ─────────────────────────

def test_every_series_verdict_says_whether_it_survives_leave_one_out(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "OUT", tmp_path / "out.jsonl")
    rows = ri.run(dt.date(2026, 9, 30), False)["rows"]
    assert rows
    for r in rows:
        assert "survives_leave_one_out" in r
        assert r["survives_leave_one_out"] in (True, False, None)


def test_a_verdict_that_depends_on_the_last_point_is_marked_fragile():
    """Built to flip: born UP over a long run, and only the final point turns it
    down. With that point the verdict is BROKE; without it, HELD."""
    hist = {"ENERGY_REVIEW": [
        {"date": "2026-08-01", "score": 10.0},
        {"date": "2026-08-02", "score": 20.0},
        {"date": "2026-08-03", "score": 30.0},
        {"date": "2026-08-10", "score": 40.0},
        {"date": "2026-08-20", "score": 1.0},
    ]}
    idea = {"ts": "2026-08-03T00:00:00+00:00", "seed": "trend",
            "dimension": "ENERGY_REVIEW", "test_horizon": "2026-08-20"}
    r = ri.resolve_one(idea, hist, dt.date(2026, 8, 25))
    assert r is not None and r["verdict"] == "BROKE"
    assert r["survives_leave_one_out"] is False, (
        "dropping the last point changes this verdict; it must say so")


def test_a_verdict_that_does_not_depend_on_the_last_point_is_not_marked_fragile():
    """The negative control: a run that is consistently up, where the last point
    is one more step in the same direction."""
    hist = {"ENERGY_REVIEW": [
        {"date": "2026-08-01", "score": 10.0},
        {"date": "2026-08-02", "score": 20.0},
        {"date": "2026-08-03", "score": 30.0},
        {"date": "2026-08-10", "score": 40.0},
        {"date": "2026-08-20", "score": 50.0},
    ]}
    idea = {"ts": "2026-08-03T00:00:00+00:00", "seed": "trend",
            "dimension": "ENERGY_REVIEW", "test_horizon": "2026-08-20"}
    r = ri.resolve_one(idea, hist, dt.date(2026, 8, 25))
    assert r is not None and r["verdict"] == "HELD"
    assert r["survives_leave_one_out"] is True


def test_the_summary_reports_how_many_verdicts_are_fragile(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "OUT", tmp_path / "out.jsonl")
    s = ri.run(dt.date(2026, 9, 30), False)["summary"]
    assert "fragile" in s and "fragile_of_decided" in s, (
        "the fragility of the population is the finding; it must be in the summary")


# ── live state ─────────────────────────────────────────────────────────────

def test_the_live_files_are_untouched():
    for path, before in _LIVE_BEFORE.items():
        after = _digest(pathlib.Path(path))
        assert after == before, f"{path} moved during the test run"
