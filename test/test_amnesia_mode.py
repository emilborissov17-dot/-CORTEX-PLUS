#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_amnesia_mode.py — WHEN THE CLEAN POOL IS TOO THIN, SEEDS HOLD THE SHAPE.

The gate in core/language_gate.py is correct and it empties two pools outright.
The failure mode of a 3B model handed two exemplars instead of eight is not
"slightly worse content" — it loses the SHAPE and starts inventing structure,
which is how empty cells got filled with plausible prose in the first place.

COMMAND 24 Part 3 names the kind "stance". The kind that actually reaches
_memory() with a seed behind it is `constancy`; `step_stance` is deliberately
unseeded because attend()'s schema demands a Bulgarian enum
("върви|следи|пропусни") that core/brain.py:927 and :956 compare against, and
an all-English seed there would teach the model to break that contract. Both are
asserted below rather than left as prose.

    venv/Scripts/python.exe -m pytest test/test_amnesia_mode.py -v
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
from core import language_gate as lg   # noqa: E402

RU = ("Показателята 'co2_annual_mean' оставя без изменений за 48 дней подряд, "
      "что указывает на возможную замръзнала сензор или застой.")
EN = ("The indicator has not moved for 48 days, which suggests a frozen sensor "
      "rather than a stable measurement of a slow quantity.")

SEED_FILE = REPO / "config" / "few_shot_seed.json"


def _journal(tmp_path, monkeypatch, rows):
    path = tmp_path / "brain_journal.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(brain, "JOURNAL", path)
    return path


def _rows(kind, summary, n):
    return [{"ts": "2026-08-23T{:02d}:00:00+00:00".format(i % 24),
             "kind": kind, "summary": summary} for i in range(n)]


# ── the headline case ───────────────────────────────────────────────────────

def test_an_all_russian_journal_falls_back_to_seeds(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _rows("constancy", RU, 30))
    block = brain._memory("constancy", n=5)
    assert "[AMNESIA MODE:" in block
    assert "clean history pool = 0 < 8" in block


def test_the_returned_block_has_zero_cyrillic(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _rows("constancy", RU, 30))
    block = brain._memory("constancy", n=5)
    assert not any(0x0400 <= ord(c) <= 0x052F for c in block), block
    assert not any(0x4E00 <= ord(c) <= 0x9FFF for c in block)
    assert RU[:20] not in block


def test_the_seeds_are_the_ones_from_the_config_file(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _rows("constancy", RU, 30))
    block = brain._memory("constancy", n=5)
    seeds = json.loads(SEED_FILE.read_text(encoding="utf-8"))["constancy"]
    assert len(seeds) >= 3
    for seed in seeds:
        assert seed[:60] in block


# ── the boundary ────────────────────────────────────────────────────────────

def test_below_the_floor_seeds_are_used(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _rows("constancy", EN, brain.MIN_POOL - 1))
    assert "[AMNESIA MODE:" in brain._memory("constancy", n=5)


def test_at_the_floor_the_real_history_stands_alone(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _rows("constancy", EN, brain.MIN_POOL))
    block = brain._memory("constancy", n=5)
    assert "[AMNESIA MODE:" not in block
    assert "[seed]" not in block


def test_the_pool_counts_what_exists_not_what_is_shown(tmp_path, monkeypatch):
    """The bug this caught: picked is capped at n, so a floor of 8 measured
    against it could never be reached and every kind was in amnesia forever."""
    _journal(tmp_path, monkeypatch, _rows("constancy", EN, 20))
    block = brain._memory("constancy", n=5)
    assert "[AMNESIA MODE:" not in block, (
        "20 clean entries and still in amnesia: the floor is being measured "
        "against the display cap")
    assert len([l for l in block.splitlines() if l.strip()]) == 5


def test_a_thin_pool_keeps_its_real_entries_alongside_the_seeds(tmp_path,
                                                                monkeypatch):
    _journal(tmp_path, monkeypatch,
             _rows("constancy", RU, 10) + _rows("constancy", EN, 2))
    block = brain._memory("constancy", n=5)
    assert "[AMNESIA MODE:" in block
    assert "clean history pool = 2 < 8" in block
    assert EN[:40] in block, "the two real clean entries were thrown away"


# ── the invariant that must never break ─────────────────────────────────────

def test_a_flagged_entry_never_enters_the_block_even_in_amnesia(tmp_path,
                                                                monkeypatch):
    _journal(tmp_path, monkeypatch, [
        {"ts": "2026-08-23T01:00:00+00:00", "kind": "constancy", "summary": RU,
         "lang": {"ok": False, "reason": "CYRILLIC_0.88"}},
        {"ts": "2026-08-23T02:00:00+00:00", "kind": "constancy", "summary": EN},
    ])
    block = brain._memory("constancy", n=5)
    assert RU[:20] not in block
    assert EN[:40] in block


def test_every_seed_in_the_config_passes_the_gate():
    """A seed that is not English would reintroduce the problem it exists for."""
    blob = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    checked = 0
    for kind, rows in blob.items():
        if kind.startswith("_"):
            continue
        assert isinstance(rows, list) and 3 <= len(rows) <= 5, (
            "{}: {} seeds, the brief says 3 to 5".format(kind, len(rows)))
        for row in rows:
            ok, reason = lg.is_english_enough(row)
            assert ok, "{}: seed rejected by the gate ({})".format(kind, reason)
            checked += 1
    assert checked >= 27, "only {} seeds in the file".format(checked)


def test_every_seed_is_valid_json_in_its_call_sites_shape():
    """A format anchor that is not the format anchors nothing."""
    blob = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    shapes = {
        "cycle_plan": {"focus", "why", "watch", "suspicion", "success_test"},
        "cycle_review": {"success", "verdict", "blind_spot", "carry_forward"},
        "constancy": {"expected_regime", "why_expected", "healthy", "alarm",
                      "reading"},
        "constellation": {"relations", "most_telling",
                          "what_would_change_my_mind"},
        "cycle_report": {"opening", "decisions", "worry", "closing"},
        "mirror_read": {"saw", "worries", "numbers"},
        "phase_debrief": {"what", "verdict", "risk", "do"},
        "reconsider": {"action", "step", "why", "expect", "wants"},
        "autopsy": {"failure", "cause", "why", "transient", "retry_after_sec",
                    "halt_and_call_human", "remedy"},
    }
    for kind, want in shapes.items():
        assert kind in blob, "no seed for {}".format(kind)
        for row in blob[kind]:
            parsed = json.loads(row)
            assert set(parsed) == want, (
                "{}: seed keys {} != schema {}".format(kind, set(parsed), want))


def test_step_stance_is_unseeded_on_purpose_and_says_why():
    blob = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    assert "step_stance" not in blob
    readme = " ".join(blob["_README"])
    assert "step_stance IS DELIBERATELY ABSENT" in readme
    # the reason has to still be true
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    assert "върви|следи|пропусни" in src
    assert 'startswith("пропусни")' in src


def test_a_missing_seed_file_does_not_break_the_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "SEED_FILE", tmp_path / "absent.json")
    _journal(tmp_path, monkeypatch, _rows("constancy", RU, 5))
    block = brain._memory("constancy", n=5)
    assert "rejected by the language gate" in block
    assert "no seed template exists for it" in block
