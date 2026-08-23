#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_enum_migration.py — ENGLISH ON THE WAY OUT, BOTH ON THE WAY IN.

Two enums the model emits and the code compares against:

    stance   върви|следи|пропусни  ->  go|watch|skip
    action   напред|връщане        ->  forward|rollback

New writes are English. Reads accept both, because memory/brain_step_log.jsonl
holds over a thousand rows and memory/reconsider_history.jsonl is what
_empty_streak() counts from — a migration that made yesterday unreadable would
be deleting evidence by omission.

    venv/Scripts/python.exe -m pytest test/test_enum_migration.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import brain            # noqa: E402
from core import reconsider       # noqa: E402


# ── the stance enum ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,want", [
    ("върви", "go"), ("следи", "watch"), ("пропусни", "skip"),
    ("ПРОПУСНИ", "skip"), ("  следи  ", "watch"),
    ("пропусни, защото няма данни", "skip"),
])
def test_the_old_bulgarian_stance_still_parses(value, want):
    assert brain.normalise_stance(value) == want


@pytest.mark.parametrize("value,want", [
    ("go", "go"), ("watch", "watch"), ("skip", "skip"), ("SKIP", "skip"),
    ("skip, nothing downstream is waiting", "skip"),
])
def test_the_new_english_stance_parses(value, want):
    assert brain.normalise_stance(value) == want


def test_an_unrecognised_stance_is_empty_not_go():
    """A stance nobody recognises must not silently become 'proceed'."""
    for junk in ("maybe", "да", "", None, "  "):
        assert brain.normalise_stance(junk) == ""


def test_the_skip_decision_behaves_identically_for_both(monkeypatch, tmp_path):
    """brain.py:983 — the consumer that decides whether a step runs at all."""
    seen = []
    monkeypatch.setattr(brain, "remember", lambda *a, **k: seen.append(a))
    monkeypatch.setattr(brain, "STANCE", tmp_path / "stance.json")

    def _wants_skip(value):
        (tmp_path / "stance.json").write_text(
            json.dumps({"step": "scoring_engine", "stance": value}),
            encoding="utf-8")
        last = brain.stance("scoring_engine")
        return brain.normalise_stance(last.get("stance")) == brain.STANCE_SKIP

    assert _wants_skip("пропусни") is True
    assert _wants_skip("skip") is True
    assert _wants_skip("върви") is False
    assert _wants_skip("go") is False


def test_the_watch_decision_behaves_identically_for_both(monkeypatch, tmp_path):
    """brain.py:1012 — 'watch' means the step runs but is looked at."""
    monkeypatch.setattr(brain, "STANCE", tmp_path / "stance.json")
    for value, want in (("следи", True), ("watch", True),
                        ("върви", False), ("go", False)):
        (tmp_path / "stance.json").write_text(
            json.dumps({"step": "s", "stance": value}), encoding="utf-8")
        assert brain.watching("s") is want, value


def test_the_prompt_asks_for_the_english_enum():
    # Read from the FILE, not from inspect.getsource(brain.attend): conftest
    # neutralises that attribute suite-wide, so getsource returns the stub.
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert '"stance": "go|watch|skip"' in code
    assert "върви|следи|пропусни" not in code.split("STANCE_LEGACY")[0]


# ── the action enum ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,want", [
    ("напред", "forward"), ("връщане", "rollback"), ("връщ", "rollback"),
    ("ВРЪЩАНЕ", "rollback"), ("forward", "forward"), ("rollback", "rollback"),
    ("rollback to scoring_engine", "rollback"),
])
def test_both_action_vocabularies_parse(value, want):
    assert reconsider.normalise_action(value) == want


def test_an_unrecognised_action_is_never_a_rollback():
    for junk in ("perhaps", "да", "", None):
        assert reconsider.normalise_action(junk) == ""
        assert reconsider.normalise_action(junk) != reconsider.ACTION_ROLLBACK


def test_the_empty_streak_still_counts_a_bulgarian_history(tmp_path,
                                                           monkeypatch):
    """memory/reconsider_history.jsonl is entirely Bulgarian today."""
    hist = tmp_path / "reconsider_history.jsonl"
    hist.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"action": "връщане", "changed_anything": False},
        {"action": "връщане", "changed_anything": False},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(reconsider, "HISTORY", hist)
    assert reconsider._empty_streak() == 2


def test_the_empty_streak_counts_a_mixed_history(tmp_path, monkeypatch):
    """The realistic case for the next weeks: old rows Bulgarian, new English."""
    hist = tmp_path / "h.jsonl"
    hist.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"action": "връщане", "changed_anything": False},
        {"action": "rollback", "changed_anything": False},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(reconsider, "HISTORY", hist)
    assert reconsider._empty_streak() == 2


def test_the_runner_reads_the_action_through_the_normaliser():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert '_rc.get("action") == "връщане"' not in code
    assert "_norm_action(_rc.get(\"action\"))" in code


def test_a_forward_verdict_is_written_in_english(tmp_path, monkeypatch):
    monkeypatch.setattr(reconsider, "_replayable", lambda: {})
    monkeypatch.setattr(reconsider, "_state", lambda: "{}")
    monkeypatch.setattr(reconsider, "_note", lambda *a, **k: None)
    monkeypatch.setattr(reconsider, "HISTORY", tmp_path / "h.jsonl")
    import core.brain as b
    monkeypatch.setattr(b, "think", lambda **kw: {"action": "forward",
                                                  "why": "nothing changed"})
    rep = reconsider.run()
    assert rep["action"] == reconsider.ACTION_FORWARD == "forward"


# ── the seed that this unblocked ────────────────────────────────────────────

def test_step_stance_is_seeded_now():
    blob = json.loads((REPO / "config" / "few_shot_seed.json").read_text(
        encoding="utf-8"))
    assert "step_stance" in blob, (
        "the enum was the blocker and it is gone; the seed should be here")
    assert 3 <= len(blob["step_stance"]) <= 5


def test_every_step_stance_seed_uses_the_english_enum():
    blob = json.loads((REPO / "config" / "few_shot_seed.json").read_text(
        encoding="utf-8"))
    for row in blob["step_stance"]:
        parsed = json.loads(row)
        assert parsed["stance"] in ("go", "watch", "skip"), parsed
        assert set(parsed) <= {"prev_ok", "prev_note", "stance", "expect",
                               "serves_goal"}, parsed
        assert not any(0x0400 <= ord(c) <= 0x052F for c in row)


def test_the_stance_exemplar_block_is_clean_and_seeded():
    block = brain._memory("step_stance", n=3)
    assert "[AMNESIA MODE:" in block
    assert not any(0x0400 <= ord(c) <= 0x052F for c in block)
    assert '"stance": "go"' in block
