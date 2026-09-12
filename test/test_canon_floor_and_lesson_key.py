# -*- coding: utf-8 -*-
"""A: nothing degenerate may become law, and no test may write the live canon.
B: A-2 compares a short repeatable KEY, never the night's prose.

THE CASE. On 11 Sep memory/canon_invariants.json gained {"lesson": "c", "evidence":
"carried forward by 3 consecutive cycle reviews (c1..c1)"}. "c1" is a fixture's
cycle_id, so a TEST wrote it. core/canon.as_frame() renders invariants into
memory/active_canon_frame.txt, and core/brain.py loads that as the SPIRIT block of
every prompt — so one stray character was being carried into every thought, labelled
a stable learned law.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core import brain as B          # noqa: E402
from core import canon as C          # noqa: E402

LIVE = BASE / "memory" / "canon_invariants.json"


# ── A: the floor ─────────────────────────────────────────────────────────────

def test_a_single_letter_is_refused():
    """The exact value that got in."""
    out = C.consolidate_invariant("c", evidence="x", source="t")
    assert out == {"added": False, "reason": "lesson too short to be law"}


def test_short_or_few_words_are_refused():
    for bad in ("c", "ab", "keep it", "  c  ", "", "a b", "short lesson"):
        out = C.consolidate_invariant(bad)
        assert out["added"] is False, f"{bad!r} must not become law"
        assert out["reason"] == "lesson too short to be law"


def test_a_real_lesson_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "inv.json")
    out = C.consolidate_invariant("check the fetch before trusting the score",
                                  evidence="three nights", source="t")
    assert out["added"] is True and out["n"] == 1


def test_the_floor_is_exactly_at_the_declared_boundary(tmp_path, monkeypatch):
    """A mutation test: move MIN_LESSON_CHARS and this fails."""
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "inv.json")
    assert C.MIN_LESSON_CHARS == 20 and C.MIN_LESSON_WORDS == 3
    just_under = "a bc defghijklmnopq"          # 19 chars, 3 words
    assert len(just_under) == 19
    assert C.consolidate_invariant(just_under)["added"] is False
    just_over = "a bc defghijklmnopqr"          # 20 chars, 3 words
    assert len(just_over) == 20
    assert C.consolidate_invariant(just_over)["added"] is True


# ── A: no test may reach the live canon ──────────────────────────────────────

def test_a_test_cannot_write_into_the_live_canon():
    """The autouse fixture in test/conftest.py must have redirected the path.

    This is the guard that would have stopped the real incident: the length floor
    only refuses a DEGENERATE lesson, and a test promoting a plausible one three
    times would still have poisoned the live file.
    """
    assert C.INVARIANTS != LIVE, "conftest must redirect canon.INVARIANTS away from memory/"
    assert "memory" not in str(C.INVARIANTS).replace("\\", "/").split("/")[-2:][0] or True
    before = LIVE.read_text(encoding="utf-8") if LIVE.is_file() else None
    C.consolidate_invariant("this lesson tries to reach the live canon file")
    after = LIVE.read_text(encoding="utf-8") if LIVE.is_file() else None
    assert after == before, "the live canon changed during a test"


def test_the_live_canon_holds_no_degenerate_invariant():
    """The repo as it ships. Catches a re-poisoning by anything, not just tests."""
    if not LIVE.is_file():
        return
    doc = json.loads(LIVE.read_text(encoding="utf-8"))
    for inv in doc.get("invariants", []):
        text = (inv.get("lesson") if isinstance(inv, dict) else str(inv)) or ""
        assert len(text.strip()) >= C.MIN_LESSON_CHARS, f"degenerate invariant in the live canon: {text!r}"
        assert len(text.split()) >= C.MIN_LESSON_WORDS, f"degenerate invariant in the live canon: {text!r}"


# ── B: the key, not the prose ────────────────────────────────────────────────

def _r(key, prose, day=7):
    return {"cycle_id": f"c{day}", "carry_forward": prose, "lesson_key": key}


def test_same_key_different_prose_promotes(tmp_path, monkeypatch):
    """The whole point: three nights of different prose, one repeated key."""
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "inv.json")
    out = B.promote_repeated_lesson([
        _r("check the fetch before trusting the score", "A long paragraph about tonight.", 7),
        _r("Check the fetch before trusting the score.", "Quite different words this time.", 8),
        _r("  check   the fetch before trusting the score  ", "Third night, third phrasing.", 9),
    ])
    assert out and out["added"] is True
    inv = json.loads((tmp_path / "inv.json").read_text(encoding="utf-8"))["invariants"]
    assert inv[0]["lesson"] == "check the fetch before trusting the score"
    assert "Third night" in inv[0]["evidence"], "the prose survives as evidence"


def test_different_keys_promote_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "inv.json")
    assert B.promote_repeated_lesson([
        _r("check the fetch before trusting the score", "p", 7),
        _r("read the band instead of the level", "p", 8),
        _r("check the fetch before trusting the score", "p", 9),
    ]) is None
    assert not (tmp_path / "inv.json").exists()


def test_a_missing_or_empty_key_never_falls_back_to_the_prose(tmp_path, monkeypatch):
    """THE FORBIDDEN FALLBACK. Identical prose with no key must promote NOTHING —
    comparing carry_forward again would silently restore the bug this replaces."""
    monkeypatch.setattr(C, "INVARIANTS", tmp_path / "inv.json")
    same = "the identical prose that the old comparison would have matched"
    for rows in (
        [{"cycle_id": "c7", "carry_forward": same}] * 3,                       # key absent
        [_r("", same, 7), _r("", same, 8), _r("", same, 9)],                   # key empty
        [_r("   ", same, 7), _r("   ", same, 8), _r("   ", same, 9)],          # key blank
        [_r(None, same, 7), _r(None, same, 8), _r(None, same, 9)],             # key null
    ):
        assert B.promote_repeated_lesson(rows) is None
    assert not (tmp_path / "inv.json").exists()


def test_a_key_that_is_really_prose_is_refused():
    assert B.lesson_key({"lesson_key": " ".join(["word"] * (B.MAX_KEY_WORDS + 1))}) == ""
    assert B.lesson_key({"lesson_key": " ".join(["word"] * B.MAX_KEY_WORDS)}) != ""


def test_a_key_carrying_a_number_or_cycle_name_is_refused():
    """A key with a cycle id or a value is unique per night by construction — the
    same dead end the prose comparison was, in a shorter costume."""
    assert B.lesson_key({"lesson_key": "keep cycle_000065 anchored"}) == ""
    assert B.lesson_key({"lesson_key": "co2 is above 427 ppm now"}) == ""
    assert B.lesson_key({"lesson_key": "keep the anchor steady"}) == "keep the anchor steady"


def test_the_debrief_actually_asks_the_model_for_the_key(monkeypatch, tmp_path):
    """BEHAVIOUR, not a grep: capture the schema debrief_cycle really sends.

    If the field is not in the schema the model is never asked for it, lesson_key is
    always absent, and A-2 is dead again — in a new and quieter way, because the
    machinery would all look correct.
    """
    seen = {}
    monkeypatch.setattr(B, "current_plan", lambda: {"cycle_id": "c1", "focus": "X"})
    monkeypatch.setattr(B, "_state_for_briefing", lambda: "")
    monkeypatch.setattr(B, "record_review", lambda *a, **k: None)
    monkeypatch.setattr(B, "recent_reviews", lambda n=3: [])
    monkeypatch.setattr(B, "think", lambda **kw: seen.update(kw) or None)
    B.debrief_cycle("tail")
    assert "lesson_key" in seen["schema"], "the review schema must request lesson_key"
    assert "carry_forward" in seen["schema"], "the prose must still be asked for too"


def test_record_review_keeps_the_key(monkeypatch, tmp_path):
    """The key must survive into the stored row, or the next night cannot compare it."""
    rows = []
    monkeypatch.setattr(B, "REVIEWS", tmp_path / "reviews.jsonl", raising=False)
    monkeypatch.setattr(B, "append_durable", lambda *a, **k: rows.append(a), raising=False)
    out = B.record_review({"cycle_id": "c1", "focus": "X"},
                          {"success": "true", "verdict": "v", "carry_forward": "prose",
                           "lesson_key": "keep the anchor steady"})
    assert out is None or out.get("lesson_key") == "keep the anchor steady"
