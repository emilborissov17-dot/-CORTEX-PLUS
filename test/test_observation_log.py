# -*- coding: utf-8 -*-
"""test/test_observation_log.py — "unchanged" is a registered fact (C-NEED-1 Part 1b).

A re-observation is never silent: the same identity logs UNCHANGED and writes no
atom; a new value or period for the same (source, key, place) writes an atom
carrying changed_from and logs CHANGED; a first reading logs NEW. Atoms and the
log live under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import atoms as at  # noqa: E402


@pytest.fixture
def root(tmp_path, monkeypatch):
    from core import card_intake as ci
    monkeypatch.setattr(ci, "RETRACTIONS", tmp_path / "retractions.jsonl")
    return tmp_path / "atoms"


def _row(value, period, ck, judged="2026-10-01T12:00:00+00:00"):
    rec = {"axis": "A", "key": "forest_area_pct", "value": value, "unit": "pct", "url": "https://x.org",
           "quote": str(value), "period": period, "place": "WLD", "subcategory": "C2.1"}
    return {"card_key": ck, "judged_utc": judged, "verdict": "ACCEPTED", "source_id": "wb", "record": rec}


def _log(root):
    p = at.obs_log_for(root)
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_the_log_for_a_test_root_is_beside_it_never_in_memory(root):
    assert at.obs_log_for(root) == root.parent / "observation_log.jsonl"
    assert at.obs_log_for(None) == at.OBS_LOG


def test_a_first_reading_logs_new(root):
    at.write(_row(31.1, "2022", "c1"), root=root)
    assert [r["verdict"] for r in _log(root)] == ["NEW"]


def test_an_unchanged_reading_logs_unchanged_and_writes_no_atom(root):
    at.write(_row(31.1, "2022", "c1"), root=root)
    out = at.write(_row(31.1, "2022", "c2", judged="2026-10-02T12:00:00+00:00"), root=root)
    assert out["written"] is False and out.get("seen_again")
    log = _log(root)
    assert log[-1]["verdict"] == "UNCHANGED" and log[-1]["since"] == "2026-10-01T12:00:00+00:00"
    assert len(list(at.read(root=root))) == 1


def test_a_changed_reading_carries_changed_from_and_logs_changed(root):
    at.write(_row(31.1, "2022", "c1"), root=root)
    out = at.write(_row(31.0, "2023", "c2", judged="2026-10-02T12:00:00+00:00"), root=root)
    assert out["written"] is True
    new = [a for a in at.read(root=root) if a["card_key"] == "c2"][0]
    assert new["changed_from"] == {"value": 31.1, "period": "2022", "card_key": "c1"}
    assert _log(root)[-1]["verdict"] == "CHANGED"
    assert _log(root)[-1]["changed_from"]["value"] == 31.1


def test_mutation_without_the_log_an_unchanged_reading_leaves_no_trace(root, monkeypatch):
    monkeypatch.setattr(at, "_log_observation", lambda *a, **k: None)
    at.write(_row(31.1, "2022", "c1"), root=root)
    at.write(_row(31.1, "2022", "c2"), root=root)
    assert _log(root) == []


def test_mutation_without_the_prior_lookup_a_change_looks_new(root, monkeypatch):
    monkeypatch.setattr(at, "_prior_reading", lambda existing, a: None)
    at.write(_row(31.1, "2022", "c1"), root=root)
    at.write(_row(31.0, "2023", "c2"), root=root)
    assert _log(root)[-1]["verdict"] == "NEW"
