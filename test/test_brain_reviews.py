# -*- coding: utf-8 -*-
"""test/test_brain_reviews.py — A-1: the brain remembers its own verdict (11 Sep 2026).

Measured 7–11 Sep: the same focus five nights, the same failed verdict, the same
blind spot — and nothing carried to the next briefing, because debrief_cycle()
only returned a dict that the runner printed. This pins the three edges:
the review is WRITTEN, the next briefing READS it first, and a focus that failed
REPEAT_LIMIT nights in a row is marked as repetition unless the plan says what
will be different. No LLM is called: think() is monkeypatched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import brain as B  # noqa: E402


def _reviews(tmp_path, monkeypatch, rows):
    p = tmp_path / "brain_cycle_reviews.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(B, "REVIEWS", p)
    return p


def _fail(day, focus="Resolve sensor conflicts"):
    return {"ts": f"2026-09-{day:02d}T02:00:00+00:00", "focus": focus, "success": "false",
            "verdict": "the success_test failed", "blind_spot": "DEEP_TIME unmeasured",
            "carry_forward": "measure DEEP_TIME"}


# ── the review is written ─────────────────────────────────────────────────────

def test_debrief_writes_the_review_next_to_the_plan_it_judged(tmp_path, monkeypatch):
    p = _reviews(tmp_path, monkeypatch, [])
    monkeypatch.setattr(B, "current_plan", lambda: {"cycle_id": "c1", "focus": "X", "success_test": "T"})
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "think", lambda **kw: {"success": "false", "verdict": "V", "blind_spot": "B",
                                                   "carry_forward": "C", "_model": "test"})
    d = B.debrief_cycle("tail")
    assert d["verdict"] == "V"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["focus"] == "X" and rows[0]["carry_forward"] == "C"
    assert rows[0]["cycle_id"] == "c1" and rows[0]["success_test"] == "T"


def test_a_silent_brain_writes_nothing(tmp_path, monkeypatch):
    p = _reviews(tmp_path, monkeypatch, [])
    monkeypatch.setattr(B, "current_plan", lambda: {"cycle_id": "c1", "focus": "X"})
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "think", lambda **kw: None)
    assert B.debrief_cycle("") is None
    assert p.read_text(encoding="utf-8") == ""


# ── the next briefing reads it FIRST ──────────────────────────────────────────

def test_the_briefing_evidence_opens_with_the_last_reviews(tmp_path, monkeypatch):
    _reviews(tmp_path, monkeypatch, [_fail(7), _fail(8), _fail(9)])
    monkeypatch.setattr(B, "BASE", tmp_path)          # no other state files -> only the reviews
    ev = B._state_for_briefing()
    assert ev.startswith("--- YOUR OWN LAST REVIEWS")
    assert "Resolve sensor conflicts" in ev and "measure DEEP_TIME" in ev
    assert "FAILED 3 nights in a row" in ev and "changed_because" in ev


def test_no_reviews_means_no_review_block(tmp_path, monkeypatch):
    _reviews(tmp_path, monkeypatch, [])
    monkeypatch.setattr(B, "BASE", tmp_path)
    assert "LAST REVIEWS" not in B._state_for_briefing()


# ── repetition is named ───────────────────────────────────────────────────────

def test_repeated_failure_needs_same_focus_and_all_failed():
    assert B.repeated_failure([_fail(7), _fail(8), _fail(9)]) == {"focus": "Resolve sensor conflicts", "n": 3}
    assert B.repeated_failure([_fail(7), _fail(8)]) is None                          # too few
    assert B.repeated_failure([_fail(7), _fail(8, focus="Other"), _fail(9)]) is None  # focus changed
    ok = dict(_fail(9)); ok["success"] = "true"
    assert B.repeated_failure([_fail(7), _fail(8), ok]) is None                        # one success breaks it


def test_the_plan_that_repeats_a_failed_focus_without_change_is_marked(tmp_path, monkeypatch):
    _reviews(tmp_path, monkeypatch, [_fail(7), _fail(8), _fail(9)])
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(B, "think", lambda **kw: {"focus": "resolve sensor conflicts", "why": "w",
                                                   "watch": [], "suspicion": "", "success_test": "t",
                                                   "changed_because": "", "_model": "test"})
    d = B.brief_cycle()
    assert d["_repeat_of_failed_focus"] is True and d["_repeat_nights"] == 3
    assert "repetition, not a plan" in d["_warning"]


def test_a_repeated_focus_with_a_stated_change_is_not_a_warning(tmp_path, monkeypatch):
    _reviews(tmp_path, monkeypatch, [_fail(7), _fail(8), _fail(9)])
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(B, "think", lambda **kw: {"focus": "Resolve sensor conflicts", "why": "w",
                                                   "watch": [], "suspicion": "", "success_test": "t",
                                                   "changed_because": "tonight I will file a repair proposal "
                                                                      "for MATERIALS_WASTE's metric", "_model": "test"})
    d = B.brief_cycle()
    assert d["_repeat_of_failed_focus"] is True and "_warning" not in d


def test_a_new_focus_after_failures_carries_no_repeat_mark(tmp_path, monkeypatch):
    _reviews(tmp_path, monkeypatch, [_fail(7), _fail(8), _fail(9)])
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(B, "think", lambda **kw: {"focus": "Ground the targets", "why": "w", "watch": [],
                                                   "suspicion": "", "success_test": "t", "changed_because": "",
                                                   "_model": "test"})
    d = B.brief_cycle()
    assert d["_repeat_of_failed_focus"] is False and "_warning" not in d


def test_mutation_without_record_review_the_loop_is_open_again(tmp_path, monkeypatch):
    """The whole defect was a printed dict. Neuter the write and the briefing goes blind."""
    p = _reviews(tmp_path, monkeypatch, [])
    monkeypatch.setattr(B, "current_plan", lambda: {"cycle_id": "c1", "focus": "X"})
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "think", lambda **kw: {"success": "false", "verdict": "V", "_model": "t"})
    monkeypatch.setattr(B, "record_review", lambda plan, review: None)
    B.debrief_cycle("")
    assert p.read_text(encoding="utf-8") == "" and B.recent_reviews() == []


# ── A-2: the canon learns only from repetition ────────────────────────────────

def _cf(day, lesson):
    r = _fail(day); r["carry_forward"] = lesson; return r


def test_a_lesson_repeated_three_times_enters_the_canon(tmp_path, monkeypatch):
    from core import canon as C
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "canon_invariants.json")
    L = "Measure DEEP_TIME_RISKS_REVIEW through the USGS indicator band, not a qualitative level."
    out = B.promote_repeated_lesson([_cf(7, L), _cf(8, L + " "), _cf(9, L.lower())])
    assert out and out["added"] is True and out["n"] == 1
    inv = json.loads((tmp_path / "canon_invariants.json").read_text(encoding="utf-8"))["invariants"]
    assert inv[0]["lesson"] == L.lower() and inv[0]["source"] == "cycle_review×3"


def test_two_repeats_or_a_changed_lesson_promote_nothing(tmp_path, monkeypatch):
    from core import canon as C
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "canon_invariants.json")
    assert B.promote_repeated_lesson([_cf(8, "A"), _cf(9, "A")]) is None
    assert B.promote_repeated_lesson([_cf(7, "A"), _cf(8, "B"), _cf(9, "A")]) is None
    assert B.promote_repeated_lesson([_cf(7, ""), _cf(8, ""), _cf(9, "")]) is None
    assert not (tmp_path / "canon_invariants.json").exists()


def test_the_same_lesson_is_not_added_twice(tmp_path, monkeypatch):
    from core import canon as C
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "canon_invariants.json")
    rows = [_cf(7, "Keep the anchor"), _cf(8, "Keep the anchor"), _cf(9, "Keep the anchor")]
    assert B.promote_repeated_lesson(rows)["added"] is True
    assert B.promote_repeated_lesson(rows)["added"] is False


def test_debrief_calls_the_promotion(tmp_path, monkeypatch):
    _reviews(tmp_path, monkeypatch, [])
    monkeypatch.setattr(B, "current_plan", lambda: {"cycle_id": "c1", "focus": "X"})
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "think", lambda **kw: {"success": "false", "verdict": "V", "carry_forward": "L", "_model": "t"})
    called = []
    monkeypatch.setattr(B, "promote_repeated_lesson", lambda *a, **k: called.append(1))
    B.debrief_cycle("")
    assert called == [1]
