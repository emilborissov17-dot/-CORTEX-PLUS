#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_morning_read.py — the seventh machine must not go quiet.

The reader exists because six machines wrote their failure honestly and nobody
read them. claude/CLAUDE_ERRORS.md is the seventh, and it is the one most likely
to fall out unnoticed: the other five are keyed on events that fire by themselves,
while this one is a hand-kept table that would simply stop appearing.

So there is one behavioural test that the newest row reaches the morning, and one
that it is the NEWEST and not the first — an off-by-one here reads as "Claude's
worst mistake was the one it made first", which is exactly wrong for a register
that grows downward.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REG = REPO / "claude" / "CLAUDE_ERRORS.md"


def _rows():
    return [[c.strip() for c in l.strip().strip("|").split("|")]
            for l in REG.read_text(encoding="utf-8").splitlines()
            if l.startswith("|") and "твърдях" not in l and set(l.strip()) - set("|- ")]


def _run():
    p = subprocess.run([sys.executable, str(REPO / "tools" / "morning_read.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(REPO), timeout=120)
    assert p.returncode == 0, p.stderr[-500:]
    return p.stdout


@pytest.mark.skipif(not REG.is_file(), reason="the register has not been written yet")
def test_the_register_reaches_the_morning():
    out = _run()
    assert "CLAUDE ERROR:" in out, (
        "the seventh machine writes its failures and the reader no longer reads them")


@pytest.mark.skipif(not REG.is_file() or len(_rows()) < 2,
                    reason="needs at least two rows to tell first from last")
def test_it_is_the_NEWEST_row_and_not_the_first():
    rows = _rows()
    line = next(l for l in _run().splitlines() if "CLAUDE ERROR:" in l)
    assert rows[-1][1][:40] in line, f"expected the last row, got: {line}"
    assert rows[0][1][:40] not in line, "it is printing the oldest mistake"


@pytest.mark.skipif(not REG.is_file(), reason="the register has not been written yet")
def test_the_register_is_printed_beside_the_three_and_does_not_displace_them():
    """It is not ranked against the other five. Only one of them can be the worst
    thing that happened last night; this is not that kind of claim."""
    out = _run().splitlines()
    body = [l for l in out if l.startswith("  ")]
    assert len([l for l in body if "CLAUDE ERROR:" not in l]) <= 3
    assert len([l for l in body if "CLAUDE ERROR:" in l]) == 1
