#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_phase_debrief.py — AN UNREADABLE VERDICT IS NOT A VERDICT.

WHAT WENT WRONG (measured 20 August 2026)
------------------------------------------
memory/brain_stance.json for step `daily_analysis`, written by local:qwen2.5:3b
at 18:42:57, twenty minutes before the watchdog killed the cycle, in full:

    prev_note    前一天分析结果为正常，未发现异常情况。
    expect       继续进行共享锚点值的冲突解决和深时风险审查盲区定义工作
    serves_goal  确保共享锚点值一致性和深时风险审查的全面性

All four fields Chinese. The operator who has to judge whether the system is
healthy cannot read a word of it, and it said "follow" and "prev_ok: True"
while the cycle was heading for a watchdog kill.

That is not a translation problem. It is a verdict that cannot be acted on,
which is the same thing as no verdict — and it was published silently, with no
record that anything was wrong with it.

THE REJECTION PATH IS WHAT IS UNDER TEST
-----------------------------------------
test_the_real_chinese_stance_from_tonight_is_rejected feeds the EXACT strings
above through the judge. If they are accepted, the rule does not work, and the
next unreadable debrief goes out the same way this one did.

Every test writes to tmp_path. Nothing touches memory/phase_debriefs/.

    venv\\Scripts\\python.exe -m pytest test/test_phase_debrief.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core.phase_debrief import (FIELDS, VERDICTS, debrief_phase, evidence_numbers,
                                render_console, render_telegram, validate)

# The phase's own data — the numbers a debrief is allowed to cite.
EVIDENCE = {
    "phase": "D_SCORE",
    "steps_run": 10,
    "axes_scored": 25,
    "measured_weight": 0,
    "asserted_weight": 75,
    # SYNTHETIC fixture, not the live goal tree: 25 / 173 was real until
    # commit 8052397 (2026-08-21); the tree is 24 axes / 167 weight now.
    "total_weight": 173,
    "seconds": 412.5,
}

# 25 / 173 below is the same synthetic shape as EVIDENCE above — real until
# 8052397 (2026-08-21), 24 axes / 167 weight now.
GOOD = {
    "what": "Scored 25 axes; 0 of 173 weight is backed by measurement.",
    "verdict": "DEGRADED",
    "risk": "The composite reads as data but is 75 weight of model assertion.",
    "do": "Wire one real metric into an axis that currently defaults.",
}

# Verbatim from memory/brain_stance.json, 2026-08-20T18:42:57, qwen2.5:3b.
TONIGHTS_CHINESE = {
    "what": "前一天分析结果为正常，未发现异常情况。",
    "verdict": "OK",
    "risk": "继续进行共享锚点值的冲突解决和深时风险审查盲区定义工作",
    "do": "确保共享锚点值一致性和深时风险审查的全面性",
}


# ---------------------------------------------------------------------------
# (a) THE NEGATIVE CONTROL — tonight's real output
# ---------------------------------------------------------------------------

def test_the_real_chinese_stance_from_tonight_is_rejected():
    """Remove the CJK rule and this passes — and the next unreadable verdict is
    published exactly as tonight's was."""
    accepted, reasons = validate(TONIGHTS_CHINESE, EVIDENCE)

    assert not accepted, (
        "\n  THE CHINESE DEBRIEF WAS ACCEPTED.\n"
        "  This is the literal text local:qwen2.5:3b wrote into brain_stance.json\n"
        "  at 18:42:57 tonight, 20 minutes before the watchdog killed the cycle.\n"
        "  An operator who cannot read the verdict cannot act on it.\n"
    )
    assert any("CJK" in r for r in reasons), reasons


def test_the_rejection_is_written_down_not_just_refused(tmp_path):
    """A model that keeps failing this must be visible, not merely silent."""
    rec = debrief_phase("D_SCORE", "2026-08-20T20:12:54+03:00", EVIDENCE,
                        base=tmp_path, asker=lambda p, e: TONIGHTS_CHINESE)

    assert rec["accepted"] is False
    path = pathlib.Path(rec["written_to"])
    assert path.name == "D_SCORE.rejected.json", rec["written_to"]
    assert path.exists()

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["accepted"] is False
    assert on_disk["debrief"] == TONIGHTS_CHINESE, (
        "the rejected text itself must be kept — otherwise nobody can see WHAT "
        "the model keeps producing"
    )
    assert any("CJK" in r for r in on_disk["rejected_because"])
    assert "console" not in on_disk and "telegram" not in on_disk, (
        "a rejected debrief must not be rendered for publication"
    )


def test_an_accepted_debrief_is_published(tmp_path):
    """POSITIVE CONTROL — a judge that rejects everything is not a judge."""
    rec = debrief_phase("D_SCORE", "2026-08-20T20:12:54+03:00", EVIDENCE,
                        base=tmp_path, asker=lambda p, e: GOOD)

    assert rec["accepted"] is True, rec["rejected_because"]
    assert pathlib.Path(rec["written_to"]).name == "D_SCORE.json"
    assert "DEGRADED" in rec["console"]
    assert "Какво:" in rec["telegram"]


# ---------------------------------------------------------------------------
# (b) The other two rejection rules
# ---------------------------------------------------------------------------

def test_a_what_with_no_number_is_rejected():
    """"The phase completed successfully" is what a model writes about a phase
    that produced nothing."""
    accepted, reasons = validate({**GOOD, "what": "The phase completed successfully."},
                                 EVIDENCE)
    assert not accepted
    assert any("no number" in r for r in reasons), reasons


def test_a_number_that_is_not_from_this_phase_is_rejected():
    """Citing A number is not the rule. Citing a number from THIS phase is."""
    accepted, reasons = validate({**GOOD, "what": "Scored 999 axes out of 4242."},
                                 EVIDENCE)
    assert not accepted
    assert any("none of those appear" in r for r in reasons), reasons


@pytest.mark.parametrize("verdict", ["FINE", "ok!", "GOOD", "", "OK/DEGRADED", None])
def test_a_verdict_outside_the_three_words_is_rejected(verdict):
    accepted, reasons = validate({**GOOD, "verdict": verdict}, EVIDENCE)
    assert not accepted, f"verdict {verdict!r} was accepted"


@pytest.mark.parametrize("verdict", list(VERDICTS))
def test_each_of_the_three_verdicts_is_accepted(verdict):
    accepted, reasons = validate({**GOOD, "verdict": verdict}, EVIDENCE)
    assert accepted, reasons


def test_a_lowercase_verdict_is_accepted_and_normalised(tmp_path):
    rec = debrief_phase("D_SCORE", "cid", EVIDENCE, base=tmp_path,
                        asker=lambda p, e: {**GOOD, "verdict": "degraded"})
    assert rec["accepted"]
    assert rec["debrief"]["verdict"] == "DEGRADED"


@pytest.mark.parametrize("field", list(FIELDS))
def test_every_field_is_required(field):
    accepted, reasons = validate({**GOOD, field: ""}, EVIDENCE)
    assert not accepted
    assert any(field in r for r in reasons)


# ---------------------------------------------------------------------------
# (c) Shape
# ---------------------------------------------------------------------------

def test_cyrillic_and_latin_are_both_fine():
    """The system is bilingual by design; only CJK is unreadable here."""
    # Synthetic, in Bulgarian on purpose. 25 / 173 was real until 8052397
    # (2026-08-21); the tree is 24 / 167 now.
    bg = {"what": "Оценени са 25 оси, 0 от 173 тегло са измерени.",
          "verdict": "DEGRADED", "risk": "Композитът е твърдение.",
          "do": "Свържи един истински показател."}
    accepted, reasons = validate(bg, EVIDENCE)
    assert accepted, reasons


def test_evidence_numbers_sees_nested_values():
    got = evidence_numbers({"a": {"b": [1, 2.5]}, "c": "x 173 y"})
    assert {"1", "2.5", "173"} <= got


def test_the_brain_returning_nothing_is_a_rejection_not_a_crash(tmp_path):
    rec = debrief_phase("D_SCORE", "cid", EVIDENCE, base=tmp_path,
                        asker=lambda p, e: None)
    assert rec["accepted"] is False
    assert "returned nothing" in " ".join(rec["rejected_because"])


def test_the_debrief_is_declared_self_directed():
    """It must never reach the cloud: the cloud being gone is the thing most
    worth debriefing, and its latency must not be charged to a step."""
    from core import backend_policy
    from core.phase_debrief import PURPOSE
    assert PURPOSE in backend_policy.SELF_DIRECTED
    assert backend_policy.cloud_allowed(PURPOSE)[0] is False


def test_console_is_english_and_telegram_is_bulgarian():
    assert "what:" in render_console("D_SCORE", GOOD)
    assert "Какво:" in render_telegram("D_SCORE", GOOD)
