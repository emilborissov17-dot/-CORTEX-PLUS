#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_debrief_language_tag.py — TAGGED, COUNTED, NOT REJECTED.

core/phase_debrief.py's comment said "Cyrillic and Latin are both fine — the
system is bilingual by design". That stopped being the design when COMMAND 25
made everything the model reads English.

The validator still does NOT reject Cyrillic, and that is deliberate: refusing
it tonight would throw away every debrief of a model that is still drifting, and
a rejected debrief leaves the phase with no account of itself at all. The
exemplar gate already stops the harm. So the language is measured, stamped on
the record, and left to the 24-hour purity ratio to alarm on.

    venv/Scripts/python.exe -m pytest test/test_debrief_language_tag.py -v
"""
from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import phase_debrief as pd  # noqa: E402

EN = {"what": "Nine steps ran and six artefacts are fresh at 41 seconds.",
      "verdict": "OK", "risk": "none worth naming", "do": "nothing"}
BG = {"what": "Фазата приключи с 9 налични артефакта",
      "verdict": "OK", "risk": "няма", "do": "нищо"}
ZH = {"what": "已评分25个轴。", "verdict": "OK", "risk": "无", "do": "无"}


def test_an_english_debrief_is_tagged_clean():
    tag = pd._language_profile(EN)
    assert tag["ok"] is True
    assert tag["profile"]["cyrillic"] == 0.0


def test_a_bulgarian_debrief_is_tagged_dirty_with_a_reason():
    tag = pd._language_profile(BG)
    assert tag["ok"] is False
    assert tag["reason"].startswith("CYRILLIC_")
    assert tag["profile"]["cyrillic"] > 0.5


def test_the_tag_uses_the_same_gate_as_the_purity_ratio():
    """Two independent judgements of 'is this English' would eventually produce
    a debrief the ratio counts as dirty and the record calls clean."""
    from core import language_gate as lg
    blob = " ".join(str(BG[f]) for f in pd.FIELDS)
    assert pd._language_profile(BG) == lg.verdict(blob)


def test_a_broken_gate_does_not_break_the_debrief(monkeypatch):
    import core
    monkeypatch.delattr(core, "language_gate", raising=False)
    monkeypatch.setitem(sys.modules, "core.language_gate", None)
    tag = pd._language_profile(EN)
    assert tag["ok"] is True
    assert tag["reason"].startswith("GATE_UNAVAILABLE_")


# ── the part that must NOT change ───────────────────────────────────────────

def test_a_bulgarian_debrief_is_still_ACCEPTED_by_the_validator():
    """The whole point of tagging instead of rejecting."""
    ok, reasons = pd.validate(
        {**BG, "what": "Фазата приключи с 9 налични артефакта"},
        evidence={"artefacts": 9}, own_numbers=set(), must_cite=set())
    assert ok, reasons


def test_cjk_is_still_rejected():
    """An operator who cannot read the verdict cannot act on it."""
    ok, reasons = pd.validate(ZH, evidence={"axes": 25},
                              own_numbers=set(), must_cite=set())
    assert not ok
    assert any("CJK" in r for r in reasons)


def test_the_comment_says_what_is_now_true():
    src = (REPO / "core" / "phase_debrief.py").read_text(encoding="utf-8")
    assert "the system is bilingual by design" not in src
    assert "THE DESIGN IS NO LONGER BILINGUAL" in src
    assert "TAGGED, NOT REJECTED" in src
    assert "REVISIT AFTER A WEEK OF CLEAN CYCLES" in src


def test_the_render_layer_is_still_bulgarian():
    """Emil reads this one. It stays his language."""
    rendered = pd.render_telegram("A_ORIENT", EN)
    assert "Какво:" in rendered
    assert "Риск:" in rendered
    assert "Да се направи:" in rendered
    # ...and the model's own words pass through untouched
    assert EN["what"] in rendered


def test_every_record_carries_the_tag_accepted_or_not(tmp_path, monkeypatch):
    """A rejected debrief is still a model output and still counts."""
    monkeypatch.setattr(pd, "debrief_model", lambda: "qwen2.5:3b")

    def _asker(phase, evidence, why=None, own=None):
        return dict(BG)

    rec = pd.debrief_phase("A_ORIENT", "cycle-1", {"artefacts": 9},
                           base=tmp_path, asker=_asker,
                           own_numbers=set(), must_cite=set())
    assert "lang" in rec, sorted(rec)
    assert rec["lang"]["ok"] is False
    assert rec["lang"]["reason"].startswith("CYRILLIC_")


def test_the_tag_is_on_the_record_even_when_the_debrief_is_accepted(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "debrief_model", lambda: "qwen2.5:3b")
    rec = pd.debrief_phase("A_ORIENT", "cycle-1", {"artefacts": 9},
                           base=tmp_path,
                           asker=lambda *a, **k: dict(EN),
                           own_numbers=set(), must_cite=set())
    assert rec["lang"]["ok"] is True
