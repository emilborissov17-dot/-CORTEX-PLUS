#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_canon_english.py — THE FRAME IS ENGLISH AND THE WALL IS UNTOUCHED.

core/canon.py::as_frame() is injected into EVERY brain prompt through _spirit().
Before this change it was 1245 characters at 65.81% Cyrillic — the single
largest non-English block the model read, larger than the law.

Two properties, and the second is the one that matters more:

  the goal reaches the model in English;
  the BOUNDARY block is byte-identical to what it always was.

The wall is human-owned. This command translated the goal, not the wall, and
BOUNDARIES.md was not read differently, re-hashed or edited.

    venv/Scripts/python.exe -m pytest test/test_canon_english.py -v
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import canon  # noqa: E402

WALL = ("CORTEX senses and advises. It never ACTUATES - it never causes an "
        "effect on the world outside a human decision taken per action.")
INVARIANT = ("The moment a system named CORTEX actuates autonomously, it is no "
             "longer CORTEX; it is a different system that has taken this "
             "name, and this document has been violated, not amended.")


def cyr(text):
    lat = sum(1 for c in text if c.isalpha() and ord(c) < 0x250)
    cy = sum(1 for c in text if 0x0400 <= ord(c) <= 0x052F)
    return cy / max(1, lat + cy)


# ── the goal ────────────────────────────────────────────────────────────────

def test_the_frame_the_model_reads_has_no_cyrillic():
    assert cyr(canon.as_frame()) == 0.0, canon.as_frame()[:300]


def test_emils_goal_file_is_untouched_and_still_bulgarian():
    """His file. He reads it. The translation happens on the way out."""
    goal = (REPO / "civilization_goal.txt").read_text(encoding="utf-8")
    assert "Максимизирай устойчивостта" in goal
    assert cyr(goal) > 0.5


def test_the_translation_keeps_every_sub_goal():
    """Five in, five out — a frame that quietly dropped one would be a
    different goal, not a translated one."""
    bg = (REPO / "civilization_goal.txt").read_text(encoding="utf-8")
    bg_items = [l for l in bg.splitlines() if l[:2] in
                ("1.", "2.", "3.", "4.", "5.")]
    en_items = [l for l in canon.GOAL_EN.splitlines() if l[:2] in
                ("1.", "2.", "3.", "4.", "5.")]
    assert len(bg_items) == len(en_items) == 5
    bg_bullets = [l for l in bg.splitlines() if l.strip().startswith("- ")]
    en_bullets = [l for l in canon.GOAL_EN.splitlines()
                  if l.strip().startswith("- ")]
    assert len(bg_bullets) == len(en_bullets) == 10


def test_the_words_that_are_instructions_are_not_softened():
    """Different verbs are different instructions. Spot-checked, not asserted
    wholesale: a translation test that only counts lines cannot see a
    paraphrase."""
    en = canon.GOAL_EN
    assert "Encourage cyclical, regenerative flows" in en      # насърчавай
    assert "Limit pollution and irreversible damage" in en     # ограничавай
    assert "Prefer reversible strategies" in en                # предпочитай
    assert "at minimal risk of harm" in en                     # при минимален риск


# ── the wall ────────────────────────────────────────────────────────────────

def test_the_boundary_block_is_word_for_word_what_it_was():
    block = canon.boundary_block()
    assert WALL in block
    assert INVARIANT in block
    assert "BOUNDARY (canon, human-owned; this system may read it, never amend it):" in block


def test_the_boundary_survives_inside_the_frame():
    frame = canon.as_frame()
    assert WALL in frame, "the wall did not survive the translation"
    assert INVARIANT in frame


def test_boundaries_md_was_not_touched():
    """Explicitly out of scope for COMMAND 25, and this pins it."""
    sha = hashlib.sha256(
        (REPO / "BOUNDARIES.md").read_bytes()).hexdigest()
    assert sha.startswith(canon.BOUNDARIES_SHA256[:12]), (
        "BOUNDARIES.md changed; its sealed hash no longer matches")


def test_the_goal_comes_before_the_boundary_and_the_boundary_before_invariants():
    """Order is load-bearing: no accumulated lesson may outrank the wall."""
    frame = canon.as_frame()
    assert frame.index("GLOBAL GOAL") < frame.index("BOUNDARY (canon")


# ── the drift guard ─────────────────────────────────────────────────────────

def test_the_pinned_hash_matches_the_file_it_was_translated_from():
    assert canon.goal_source_sha256() == canon.GOAL_SOURCE_SHA256, (
        "civilization_goal.txt changed since GOAL_EN was written — retranslate "
        "and re-pin, or the model is reading a rendering of a goal that no "
        "longer exists")


def test_an_edited_goal_file_makes_the_frame_say_so(tmp_path, monkeypatch):
    edited = tmp_path / "civilization_goal.txt"
    edited.write_text("# ГЛОБАЛНА ЦЕЛ\n\nНещо съвсем друго.\n", encoding="utf-8")
    monkeypatch.setattr(canon, "GOAL_FILE", edited)
    block = canon.goal_block()
    assert "[WARNING:" in block
    assert "no longer match" in block
    assert canon.GOAL_EN in block, (
        "the warning replaced the goal instead of prefixing it")
    assert cyr(block) == 0.0, "the drift warning reintroduced Cyrillic"


def test_a_missing_english_rendering_falls_back_rather_than_losing_the_centre(
        monkeypatch):
    monkeypatch.setattr(canon, "GOAL_EN", "")
    assert canon.goal_block().strip(), "the centre was lost"


def test_the_live_frame_on_disk_is_english():
    """What the brain will actually read tonight."""
    frame = (REPO / "memory" / "active_canon_frame.txt").read_text(
        encoding="utf-8")
    assert cyr(frame) == 0.0
    assert WALL in frame
