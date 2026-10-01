# -*- coding: utf-8 -*-
"""test/test_observation_retractions.py — a retraction is a row, and every reader
sees one truth (1 Oct 2026, command C-OC-1 Part 2).

memory/verified_observations.jsonl is append-only and is NEVER edited. A false
ACCEPTED row (the Forest-area 17490, the World Bank header's row count) is
withdrawn by appending a row to memory/observation_retractions.jsonl, and every
reader goes through core.card_intake.accepted_rows(), which subtracts it.

Refusals first: an unreadable retractions file RAISES (a silent [] would bring
every retracted row back), and a module that opens the observations file itself
fails the single-reader test, found by tools/ask.py, not by a grep.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
from core import card_intake as ci  # noqa: E402


def _row(key, verdict="ACCEPTED", value=1.0, rkey="k"):
    return {"card_key": key, "judged_utc": "2026-09-28T00:00:00+00:00", "verdict": verdict,
            "gate": {"verdict": verdict}, "record": {"key": rkey, "value": value}}


@pytest.fixture
def files(tmp_path, monkeypatch):
    obs = tmp_path / "verified_observations.jsonl"
    ret = tmp_path / "observation_retractions.jsonl"
    obs.write_text("".join(json.dumps(r) + "\n" for r in [
        _row("good", rkey="forest_ok", value=31.09), _row("bad", rkey="Forest area", value=17490.0),
        _row("null", verdict="NULL_WITH_REASON", value=None)]), encoding="utf-8")
    monkeypatch.setattr(ci, "ACCEPTED", obs)
    monkeypatch.setattr(ci, "RETRACTIONS", ret)
    return obs, ret


# ── refusals ────────────────────────────────────────────────────────────────
def test_an_unreadable_retractions_file_raises_rather_than_bringing_rows_back(files):
    obs, ret = files
    ret.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ci.RetractionsUnreadable):
        ci.accepted_rows()


def test_retracting_a_key_that_was_never_accepted_is_refused(files):
    with pytest.raises(ValueError):
        ci.retract("no-such-key", reason="x", by="test")


def test_a_retraction_needs_a_reason_and_a_name(files):
    for reason, by in (("", "t"), ("r", "")):
        with pytest.raises(ValueError):
            ci.retract("bad", reason=reason, by=by)


def test_retraction_never_edits_the_observations_file(files):
    obs, ret = files
    before = obs.read_bytes()
    ci.retract("bad", reason="header row count", by="test")
    assert obs.read_bytes() == before
    row = json.loads(ret.read_text(encoding="utf-8").splitlines()[-1])
    assert set(row) >= {"card_key", "retracted_utc", "reason", "by"} and row["card_key"] == "bad"


# ── the rule ────────────────────────────────────────────────────────────────
def test_accepted_rows_subtracts_retractions(files):
    assert {r["card_key"] for r in ci.accepted_rows()} == {"good", "bad"}
    ci.retract("bad", reason="header row count", by="test")
    assert {r["card_key"] for r in ci.accepted_rows()} == {"good"}
    assert {r["card_key"] for r in ci.accepted_rows(verdicts=ci.OK_VERDICTS)} == {"good", "null"}


def test_mutation_without_the_subtraction_the_retracted_row_comes_back(files, monkeypatch):
    ci.retract("bad", reason="header row count", by="test")
    monkeypatch.setattr(ci, "retracted_keys", lambda path=None: set())
    assert "bad" in {r["card_key"] for r in ci.accepted_rows()}


# ── every reader honours it ─────────────────────────────────────────────────
def test_alarm_bands_does_not_see_a_retracted_row(files):
    from core import alarm_bands as ab
    obs, _ = files
    ci.retract("bad", reason="header row count", by="test")
    vals = ab.indicator_values(obs)
    assert "Forest area" not in vals and "forest_ok" in vals


def test_scoreboard_counts_only_unretracted_accepted(files, monkeypatch):
    from scripts import agi_scoreboard as sb
    obs, _ = files
    monkeypatch.setattr(ci, "REPO", obs.parent)      # the scoreboard resolves both under its own REPO
    monkeypatch.setattr(sb, "REPO", obs.parent)
    ci.retract("bad", reason="header row count", by="test")
    assert sb.verified_counts()["accepted"] == 1
    assert sb.verified_counts()["retracted"] == 1


def test_corpus_does_not_train_on_a_retracted_row(files):
    from training import verified_corpus as vc
    ci.retract("bad", reason="header row count", by="test")
    rows = vc.observation_rows()
    keys = {json.dumps(r, sort_keys=True) for r in rows}
    assert not any("17490" in k for k in keys)
    assert any("31.09" in k for k in keys)


# ── one reader, found by tools/ask.py ───────────────────────────────────────
def _live_readers(base: Path) -> set:
    import ask
    r = ask.readers("memory/verified_observations.jsonl", base)
    return {h["file"] for h in r["direct"] if not h["file"].startswith("test")}


def test_only_core_card_intake_opens_the_observations_file():
    assert _live_readers(REPO) == {"core/card_intake.py"}


def test_mutation_a_module_that_opens_it_directly_is_caught(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "sneaky.py").write_text(
        'from pathlib import Path\n'
        'ROWS = (Path(__file__).parents[1] / "memory" / "verified_observations.jsonl").read_text()\n',
        encoding="utf-8")
    assert _live_readers(tmp_path) == {"core/sneaky.py"}
