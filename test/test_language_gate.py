#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_language_gate.py — THE GATE FILTERS EXEMPLARS AND TOUCHES NOTHING.

Two properties, and the second matters as much as the first:

  the model is never shown a contaminated exemplar again;
  the journal on disk is byte-identical afterwards.

The existence ledger and memory/brain_journal.jsonl are append-only history.
History that lied is still evidence — it is the only record of the six days of
Russian, and a "fix" that cleaned it would have destroyed the proof that the
fix was needed. So the filter is a READ-TIME filter, and this file asserts the
bytes have not moved.

    venv/Scripts/python.exe -m pytest test/test_language_gate.py -v
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import brain            # noqa: E402
from core import language_gate as lg   # noqa: E402

RU = ("Показателята 'co2_annual_mean' оставя без изменений за 48 дней подряд, "
      "что указывает на возможную замръзнала сензор или застой.")
ZH = "确认并修复NOAA锚点在气候和材料废物审查中的重复使用，以提高受影响审查的准确性"
EN1 = ("The indicator co2_annual_mean has not moved for 48 days, which suggests "
       "a frozen sensor rather than a stable measurement.")
EN2 = ("The NOAA anchor is reused by two reviews, so their accuracy scores are "
       "not independent of each other.")


def _write(path, rows):
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return path


@pytest.fixture
def journal(tmp_path, monkeypatch):
    """3 Russian and 2 English entries of the same kind, oldest first."""
    path = tmp_path / "brain_journal.jsonl"
    _write(path, [
        {"ts": "2026-08-20T10:00:00+00:00", "kind": "constancy", "summary": EN1},
        {"ts": "2026-08-21T10:00:00+00:00", "kind": "constancy", "summary": RU},
        {"ts": "2026-08-22T10:00:00+00:00", "kind": "constancy", "summary": EN2},
        {"ts": "2026-08-23T10:00:00+00:00", "kind": "constancy", "summary": RU},
        {"ts": "2026-08-23T11:00:00+00:00", "kind": "constancy", "summary": RU},
    ])
    monkeypatch.setattr(brain, "JOURNAL", path)
    return path


# ── layer 1, on its own ─────────────────────────────────────────────────────

def test_the_profile_counts_letters_not_characters():
    p = lg.script_profile('{"n": 42, "text": "hello"}')
    assert p["letters"] == 10         # n(1) + text(4) + hello(5)
    assert p["latin"] == 1.0
    # 26 characters, 10 letters: judging by characters would drown the words in
    # braces and digits, which is why the fraction is over letters.
    assert len('{"n": 42, "text": "hello"}') == 26


def test_russian_and_chinese_are_rejected_with_a_machine_reason():
    ok, reason = lg.is_english_enough(RU)
    assert not ok and reason.startswith("CYRILLIC_")
    ok, reason = lg.is_english_enough(ZH)
    assert not ok and reason.startswith("HAN_")


def test_english_passes():
    for text in (EN1, EN2):
        ok, reason = lg.is_english_enough(text)
        assert ok and reason == lg.OK


def test_a_summary_with_no_letters_is_not_a_language_failure():
    ok, reason = lg.is_english_enough("{ 0.6282, 11, -3 }")
    assert ok and reason == lg.NO_LETTERS
    # and a key name IS letters, so this one is judged normally
    ok, reason = lg.is_english_enough('{"composite": 0.6282}')
    assert ok and reason == lg.OK


def test_the_active_layers_are_reported_not_assumed():
    layers = {l["layer"]: l for l in lg.active_layers()}
    assert layers["script_census"]["active"] is True
    # Whether a detector is installed is a fact about this machine, not a
    # requirement. What must be true is that the module SAYS which it is.
    assert isinstance(layers["statistical_detector"]["active"], bool)
    assert layers["statistical_detector"]["detail"]


# ── the filter, and the bytes ───────────────────────────────────────────────

def test_memory_returns_exactly_the_two_english_entries(journal, monkeypatch):
    """The filter on its own, with the seeds out of the way.

    Part 3 added amnesia mode, which prepends hand-written seed exemplars when
    the clean pool is under MIN_POOL — and a five-row fixture is always under
    it. That is correct behaviour and it is tested in test_amnesia_mode.py; what
    THIS file is about is the filter, so the seed file is pointed at nothing and
    the block is only what survived the gate.
    """
    monkeypatch.setattr(brain, "SEED_FILE", journal.parent / "no_seeds.json")
    block = brain._memory("constancy", n=5)
    lines = [l for l in block.splitlines() if l.strip()]
    assert len(lines) == 2, block
    assert EN1[:40] in block and EN2[:40] in block
    assert RU[:20] not in block


def test_the_history_entries_survive_alongside_the_seeds(journal):
    """And with the real seed file, the two clean entries are still in there."""
    block = brain._memory("constancy", n=5)
    assert "[AMNESIA MODE:" in block
    assert "clean history pool = 2 < 8" in block
    assert EN1[:40] in block and EN2[:40] in block
    assert RU[:20] not in block


def test_the_returned_block_has_no_cyrillic_at_all(journal):
    block = brain._memory("constancy", n=5)
    assert not any(0x0400 <= ord(c) <= 0x052F for c in block)
    assert not any(0x4E00 <= ord(c) <= 0x9FFF for c in block)


def test_the_journal_is_byte_identical_afterwards(journal):
    before = journal.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    brain._memory("constancy", n=5)
    brain._memory("constancy", n=5)
    after = journal.read_bytes()
    assert after == before
    assert hashlib.sha256(after).hexdigest() == digest


def test_an_all_rejected_kind_says_why_it_is_empty(tmp_path, monkeypatch):
    """A kind with NO seed behind it. `autopsy` has one since Part 3, so using
    it here would test amnesia mode rather than the message."""
    path = _write(tmp_path / "j.jsonl", [
        {"ts": "2026-08-23T10:00:00+00:00", "kind": "consult", "summary": RU},
        {"ts": "2026-08-23T11:00:00+00:00", "kind": "consult", "summary": ZH},
    ])
    monkeypatch.setattr(brain, "JOURNAL", path)
    block = brain._memory("consult", n=5)
    assert "rejected by the language gate" in block
    assert "2 entries" in block
    assert "no seed template exists for it" in block


def test_a_kind_that_never_existed_says_something_different(journal):
    block = brain._memory("no_such_kind", n=5)
    assert "no memories of this kind" in block
    assert "rejected" not in block


# ── the write side ──────────────────────────────────────────────────────────

def test_remember_stamps_the_verdict_and_still_writes_the_line(tmp_path,
                                                               monkeypatch):
    path = tmp_path / "j.jsonl"
    monkeypatch.setattr(brain, "JOURNAL", path)
    brain.remember("constancy", RU)
    brain.remember("constancy", EN1)
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2, "a rejected thought was dropped instead of flagged"
    assert rows[0]["summary"] == RU, "the summary was rewritten"
    assert rows[0]["lang"]["ok"] is False
    assert rows[0]["lang"]["reason"].startswith("CYRILLIC_")
    assert rows[0]["lang"]["profile"]["cyrillic"] > 0.5
    assert rows[1]["lang"]["ok"] is True


def test_a_stored_verdict_is_trusted_over_recomputing_it(tmp_path, monkeypatch):
    """The stored flag is the record of what the gate thought at write time."""
    path = _write(tmp_path / "j.jsonl", [
        {"ts": "2026-08-23T10:00:00+00:00", "kind": "k", "summary": EN1,
         "lang": {"ok": False, "reason": "DETECTOR_FR"}},
    ])
    monkeypatch.setattr(brain, "JOURNAL", path)
    assert "rejected by the language gate" in brain._memory("k", n=5)


def _break_the_gate(monkeypatch):
    """Make `from core import language_gate` raise, the way a real breakage would.

    Setting sys.modules alone is NOT enough and the first version of this test
    was green because of it: `from core import language_gate` finds the already
    bound attribute on the `core` package and never consults sys.modules. Both
    have to go for the import to actually fail.
    """
    import core
    monkeypatch.delattr(core, "language_gate", raising=False)
    monkeypatch.setitem(sys.modules, "core.language_gate", None)


def test_the_read_side_fails_closed(tmp_path, monkeypatch):
    """If the gate cannot answer, nothing is offered as an example."""
    _break_the_gate(monkeypatch)
    assert brain._entry_is_clean({"summary": EN1}) is False, (
        "an unvalidated exemplar was offered to the model")
    path = _write(tmp_path / "j.jsonl", [
        {"ts": "2026-08-23T10:00:00+00:00", "kind": "k", "summary": EN1}])
    monkeypatch.setattr(brain, "JOURNAL", path)
    assert "rejected by the language gate" in brain._memory("k", n=5)


def test_the_write_side_fails_open(tmp_path, monkeypatch):
    """A broken gate must not stop the brain from recording what it thought."""
    _break_the_gate(monkeypatch)
    v = brain._lang_verdict("anything")
    assert v["ok"] is True
    assert v["reason"].startswith("GATE_UNAVAILABLE_")

    path = tmp_path / "j.jsonl"
    monkeypatch.setattr(brain, "JOURNAL", path)
    brain.remember("k", RU)
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["summary"] == RU, (
        "a broken gate silenced the journal")
