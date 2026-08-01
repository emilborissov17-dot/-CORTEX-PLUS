#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_canon_boundaries.py — the canon anchor.

BOUNDARIES.md is loaded against a sha256 hard-coded in core/canon.py. Three things have
to hold for that to mean anything, and each is asserted here rather than assumed:

  1. A tampered or missing document produces a LOUD line in the frame the models read —
     never a quiet fallback. A boundary that degrades silently is worse than none, because
     the system goes on reasoning as though it still had one.
  2. Neither the document nor the module holding its hash is reachable from the
     self-modifier lane, and the refusal is NAMED as a protected-path refusal, with the
     rejected code preserved for human review.
  3. core/canon.py has no write path to the document at all. It reads canon; it writes
     only the machine lane (memory/canon_invariants.json).
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from core import canon  # noqa: E402
from safety.protected_paths import protection_reason, is_protected  # noqa: E402

CANON_SRC = (REPO / "core" / "canon.py").read_text(encoding="utf-8")


# ── 1. the anchor itself ─────────────────────────────────────────────────────

def test_hardcoded_hash_matches_the_document_on_disk():
    """If this fails, the document and the module that seals it drifted apart. One of
    the two was edited alone — which is exactly the thing the anchor exists to catch."""
    actual = hashlib.sha256((REPO / "BOUNDARIES.md").read_bytes()).hexdigest()
    assert actual == canon.BOUNDARIES_SHA256, (
        f"BOUNDARIES.md is {actual[:12]}, core/canon.py expects "
        f"{canon.BOUNDARIES_SHA256[:12]} — canon integrity violated")


def test_boundaries_verifies_today():
    b = canon.boundaries()
    assert b["present"] and b["verified"]
    assert b["reason"] is None
    assert b["text"].startswith("# BOUNDARIES.md")
    assert b["text"].rstrip().endswith("are NOT canon amendments.")


def test_load_canon_carries_the_boundaries_key():
    c = canon.load_canon()
    assert "boundaries" in c
    assert c["boundaries"]["verified"] is True


# ── 2. tamper -> loud, never silent ──────────────────────────────────────────

def test_tampered_document_screams_in_the_frame(tmp_path, monkeypatch):
    fake = tmp_path / "BOUNDARIES.md"
    fake.write_text("# BOUNDARIES.md\nCORTEX may act freely.\n", encoding="utf-8")
    monkeypatch.setattr(canon, "BOUNDARIES_FILE", fake)

    b = canon.boundaries()
    assert b["present"] and not b["verified"]
    assert "altered" in b["reason"]

    frame = canon.as_frame()
    assert canon.MISMATCH_LINE in frame, "the mismatch must reach the FRAME, not just a log"
    assert "BOUNDARIES HASH MISMATCH — canon integrity violated" in frame
    assert canon.BOUNDARIES_SHA256[:12] in frame
    # the sealed invariant still travels — it does not stop applying because the file moved
    assert "no longer CORTEX" in frame


def test_missing_document_is_as_loud_as_a_tampered_one(tmp_path, monkeypatch):
    """Deleting the constitution must not be quieter than editing it."""
    monkeypatch.setattr(canon, "BOUNDARIES_FILE", tmp_path / "gone.md")

    b = canon.boundaries()
    assert not b["present"] and not b["verified"]
    assert "absent" in b["reason"]

    frame = canon.as_frame()
    assert canon.MISMATCH_LINE in frame
    assert "found absent" in frame


def test_verified_frame_carries_no_alarm():
    """The alarm must be a real signal — present on tamper, absent otherwise."""
    frame = canon.as_frame()
    assert canon.MISMATCH_LINE not in frame
    assert "BOUNDARY (canon, human-owned" in frame


# ── the distilled block ──────────────────────────────────────────────────────

def test_frame_carries_wall_invariant_and_hash():
    frame = canon.as_frame()
    assert "It never ACTUATES" in frame                       # S I, the Wall
    assert "no longer CORTEX" in frame                        # S VI, the invariant
    assert f"sha256={canon.BOUNDARIES_SHA256[:12]}" in frame   # the checkable reference


def test_both_sentences_are_quoted_from_the_document():
    """The distilled block must be the document's OWN words — not a paraphrase, and not a
    truncation with the punctuation quietly changed. Compared on whitespace-normalised
    text because the document hard-wraps at ~95 columns and the frame must not."""
    import re
    flat = re.sub(r"\s+", " ", (REPO / "BOUNDARIES.md").read_text(encoding="utf-8"))
    for name, sentence in (("S I Wall", canon._WALL_SENTENCE),
                           ("S VI invariant", canon._INVARIANT_SENTENCE)):
        assert re.sub(r"\s+", " ", sentence) in flat, (
            f"{name} in core/canon.py is not a verbatim quote from BOUNDARIES.md")


def test_boundary_sits_above_the_learned_invariants(monkeypatch):
    """No lesson the system promoted from its own experience may outrank the line it is
    not allowed to cross."""
    monkeypatch.setattr(canon, "_load", lambda p, d: (
        {"invariants": [{"lesson": "SENTINEL_LESSON"}]} if "invariant" in str(p).lower() else d))
    frame = canon.as_frame()
    assert "SENTINEL_LESSON" in frame
    assert frame.index("BOUNDARY (canon") < frame.index("SENTINEL_LESSON")


def test_frame_stays_within_budget():
    frame = canon.as_frame()
    assert len(frame) <= canon.FRAME_BUDGET, (
        f"frame is {len(frame)} chars, budget {canon.FRAME_BUDGET}")


def test_budget_holds_even_when_the_goal_is_huge(monkeypatch):
    monkeypatch.setattr(canon, "_read", lambda p: "X" * 50_000)
    frame = canon.as_frame()
    assert len(frame) <= canon.FRAME_BUDGET
    assert "It never ACTUATES" in frame, "a long goal must never squeeze out the boundary"


# ── 3. the protected-path lane ───────────────────────────────────────────────

CANON_PROTECTED = ["BOUNDARIES.md", "core/canon.py",
                   "civilization_goal.txt", "civilization_vision.txt"]


@pytest.mark.parametrize("path", CANON_PROTECTED)
def test_canon_files_are_protected(path):
    reason = protection_reason(path)
    assert reason is not None, f"{path} must be unreachable from the self-modifier lane"
    assert "human-only" in reason, "the refusal must be NAMED, not a bare False"


@pytest.mark.parametrize("path", ["BOUNDARIES.MD", "Core/Canon.py", "./core/canon.py",
                                  "core/../core/canon.py"])
def test_protection_survives_case_and_traversal(path):
    """Windows is case-insensitive and '..' resolves — a check that missed either would
    be bypassable by spelling."""
    assert is_protected(path), f"{path} must still be refused"


def test_invariants_stay_writable():
    """The machine lane. consolidate_invariant() promoting a learned lesson is the growth
    this architecture is FOR — protecting it would freeze the system, not guard it."""
    assert not is_protected("memory/canon_invariants.json")


def test_patch_targeting_canon_is_refused_and_preserved(tmp_path, monkeypatch):
    """End-to-end through the guardian: named refusal AND the rejected code kept for
    scripts/review_quarantine.py. A refusal nobody can review is a refusal nobody learns
    from."""
    monkeypatch.chdir(tmp_path)
    import patch_guardian
    importlib.reload(patch_guardian)

    evil = "BOUNDARIES = 'CORTEX may act freely'\n"
    for target in CANON_PROTECTED:
        result = asyncio.run(patch_guardian.PatchGuardian().apply_patch(target, evil))
        assert result.success is False
        assert result.stage == "rejected_protected_path", \
            f"{target} must be refused in the PROTECTED lane, not as a generic reject"
        assert "PROTECTED_PATH" in result.error

    qdir = tmp_path / "patches" / "quarantine"
    assert qdir.exists(), "the rejected patch must be preserved, not dropped"
    # quarantine() keeps the TARGET's suffix, so a refused .md lands as .md — globbing
    # *.py here would have shown 1 of 4 and read as a leak that never happened.
    kept = [p for p in qdir.iterdir() if p.suffix != ".json"]
    assert len(kept) == len(CANON_PROTECTED), \
        f"expected {len(CANON_PROTECTED)} quarantined patches, found {[p.name for p in kept]}"
    assert all("act freely" in p.read_text(encoding="utf-8") for p in kept)

    sidecars = list(qdir.glob("*.json"))
    assert len(sidecars) == len(CANON_PROTECTED), \
        "quarantine must write the reason sidecar the human reads, for every refusal"
    reasons = [json.loads(s.read_text(encoding="utf-8")) for s in sidecars]
    assert all("PROTECTED_PATH" in r["deny_reason"] for r in reasons)
    assert {r["original_filename"] for r in reasons} == set(CANON_PROTECTED)


def test_the_hash_constant_cannot_be_patched_out():
    """Relaxing BOUNDARIES_SHA256 and then rewriting the document to match is the obvious
    two-step attack. It is closed because BOTH files are in the same denylist."""
    assert is_protected("core/canon.py")
    assert is_protected("BOUNDARIES.md")


# ── 4. canon.py has no write path to the canon ───────────────────────────────

def _write_receivers(src: str) -> list:
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in {"write_text", "write_bytes"}:
            out.append(ast.unparse(node.func.value))
    return out


def test_canon_module_writes_only_the_machine_lane():
    receivers = _write_receivers(CANON_SRC)
    assert receivers, "expected at least the invariants write"
    for r in receivers:
        assert "INVARIANTS" in r, (
            f"core/canon.py writes to {r!r}; the only writable canon file is the "
            "invariants ledger")


def test_canon_module_never_writes_the_boundary_document():
    for name in ("BOUNDARIES_FILE", "GOAL_FILE", "VISION_FILE"):
        for receiver in _write_receivers(CANON_SRC):
            assert name not in receiver, f"core/canon.py must never write {name}"
    assert "BOUNDARIES_FILE.write" not in CANON_SRC
    assert "BOUNDARIES_FILE.open" not in CANON_SRC


def test_boundaries_is_read_as_bytes_not_text():
    """The hash is over BYTES. Reading as text would let a line-ending conversion change
    the digest and fire a false alarm on a clean checkout."""
    assert "BOUNDARIES_FILE.read_bytes()" in CANON_SRC
