# -*- coding: utf-8 -*-
"""A hand-copied constant goes stale silently. This makes it go stale loudly.

WHY THIS EXISTS (Emil, 28 August 2026, after the fourth instance in one day).
The goal tree was 25 axes / 173 weight until commit 8052397, "the observer steps
out of the observed", retired GENERAL_SELF_REVIEW on 2026-08-21 and left 24 axes
/ 167 weight. goal_score_calculator never carried the number: it sums the
denominator out of config/target_config.json and returned 167 from the moment
the config changed. Every wrong 173 in this repo was a human writing the number
down from memory — in a queue item, in a spec, in a docstring — and none of them
had any way to notice.

THE RULE. Outside config/, the literal 173 may not appear next to the word
"weight" (or "тегло") unless the correction travels with it: 167 must appear on
the same line or within five lines either side. That is deliberately a rule
about PROXIMITY, not about deletion. A sentence describing what was true in
August stays true and stays in the file; it just has to say what changed. A
number asserted as current has to be right.

THE DENOMINATOR ITSELF IS NEVER PINNED HERE. This test does not assert that the
total is 167 — it asserts that no file hard-codes a total at all without saying
where it came from. If the tree changes again to 24 axes / 160, the honest
sentences in this repo stay honest and this test keeps passing, because the
correction they carry is a history, not a claim about today. What it catches is
the next constant copied into prose by hand.
"""
from __future__ import annotations

import json
import pathlib
import re

BASE = pathlib.Path(__file__).resolve().parents[1]

# config/ is exempt: that is where the number is DEFINED, not copied.
# The rest are generated, archived, or runtime output — none is hand-written
# prose, and rewriting them would mean editing a record of what a day looked
# like. memory/ and snapshots/ hold live state a cycle overwrites.
SKIP_DIRS = {"venv", "venv312_metta", ".git", "node_modules", "__pycache__",
             "snapshots", "cortex_memory", "data", "news", "output",
             "config", "memory"}
EXT = {".py", ".md", ".json", ".txt", ".bat", ".html"}

WINDOW = 5
STALE = 173
CURRENT = "167"

# 173 alone, not 1730, not 4.173, not 21735.
_NUM = re.compile(r"(?<![\d.])%d(?![\d.])" % STALE)
_WEIGHT = re.compile(r"weight|тегло", re.IGNORECASE)


def _files():
    for p in sorted(BASE.rglob("*")):
        if not p.is_file() or p.suffix not in EXT:
            continue
        if set(p.relative_to(BASE).parts) & SKIP_DIRS:
            continue
        yield p


def _offences():
    out = []
    for p in _files():
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if not _NUM.search(line) or not _WEIGHT.search(line):
                continue
            lo, hi = max(0, i - WINDOW), min(len(lines), i + WINDOW + 1)
            if any(CURRENT in l for l in lines[lo:hi]):
                continue
            out.append((p.relative_to(BASE).as_posix(), i + 1, line.strip()[:120]))
    return out


def test_no_hand_copied_total_weight_outside_config():
    bad = _offences()
    assert not bad, (
        "a total weight of %d is written down without the correction beside it.\n"
        "The goal tree has been 24 axes / %s weight since commit 8052397 "
        "(2026-08-21).\n"
        "Either fix the number, or keep it and say within %d lines what it became:\n"
        % (STALE, CURRENT, WINDOW)
        + "\n".join(f"  {f}:{n}  {t}" for f, n, t in bad))


def test_the_scanner_can_actually_see_a_violation(tmp_path):
    """A guard nobody has watched fail is a guard nobody has tested."""
    global BASE
    real, BASE = BASE, tmp_path
    try:
        (tmp_path / "bad.md").write_text("the composite covers 100 of 173 weight\n",
                                         encoding="utf-8")
        assert _offences(), "the scanner missed a plain violation"
        (tmp_path / "bad.md").write_text(
            "the composite covers 100 of 173 weight\n(167 since 8052397)\n",
            encoding="utf-8")
        assert not _offences(), "the correction beside it should clear the line"
    finally:
        BASE = real


def test_the_number_it_guards_is_the_one_the_config_actually_sums():
    """The rule above is about proximity, but the CURRENT value quoted in its
    message has to be true today, or the guard teaches the next reader a second
    wrong number."""
    cfg = json.loads((BASE / "config" / "target_config.json").read_text(encoding="utf-8"))
    total = 0.0
    axes = 0
    for domain, block in cfg.items():
        if str(domain).startswith("_"):
            continue
        for _axis, spec in block.items():
            total += float(spec.get("weight", 1))
            axes += 1
    assert total == float(CURRENT), (
        f"config/target_config.json now sums to {total} across {axes} axes, not "
        f"{CURRENT}. The tree moved again: update CURRENT here and re-annotate "
        f"the sentences that quote the old denominator — do not delete them.")
