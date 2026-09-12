#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logs/supervisor.log must contain OBSERVATIONS, not fixtures.

WHY THIS FILE EXISTS. The watchdog's log is the only narrative record of why a
cycle was killed, and a passport column was built on it. Measured on 12 Sep 2026
it held 720+ synthetic KILL POLICY lines: web_intelligence x144, trend_tracker
x144, and step='x' x432 — and 'x' is not a step in any table in this repo. A
reader counting kills from that file would have concluded that web_intelligence
is the most-killed step in the system. The existence ledger says it has never
been killed once.

WHAT A REFUSAL LOOKS LIKE HERE. These tests FAIL while the live log is still
poisoned, and that is the intended state until the quarantine lands. They are
not "expected failures" to be marked xfail — a green tick from an xfail would be
the same lie in a smaller font. When the fix moves the synthetic lines to
logs/supervisor.synthetic.log, they go green because the file changed, not
because the test was softened.

THE FORBIDDEN FALLBACK: deleting the lines. That is rewriting history, and the
supervisor log is evidence. The lines move to a quarantine file with a header
saying where they came from; nothing is destroyed.

HOW A FIXTURE IS RECOGNISED — mechanically, not by taste. A real observation
carries a measured heartbeat age (2761.8s) and a live cpu/io sample; two of them
agreeing to the digit does not happen. A fixture is a literal in a test file and
therefore repeats VERBATIM. So: an exact duplicate of the same KILL POLICY line,
timestamp removed, is the signature.
"""
from __future__ import annotations

import collections
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "logs" / "supervisor.log"
QUARANTINE = REPO / "logs" / "supervisor.synthetic.log"

# The line the watchdog writes when it consults core/kill_policy.
KILL_LINE = re.compile(
    r"KILL POLICY: step='(?P<step>[^']*)' age=(?P<age>[\d.]+)s "
    r"ceiling=(?P<ceiling>[\d.]+)s cpu=(?P<cpu>\S+) io_idle=(?P<io>\S+) "
    r"degraded=(?P<degraded>\S+) -> (?P<verdict>[A-Z]+) \((?P<cause>[^)]*)\)")

# Leading "[2026-09-12T10:22:10.671539+00:00] " — the only part of a repeated
# fixture that legitimately differs between two writes of the same literal.
STAMP = re.compile(r"^\[[^\]]+\]\s*")


def _kill_lines(path: Path) -> list:
    if not path.is_file():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = KILL_LINE.search(raw)
        if m:
            out.append((m, STAMP.sub("", raw).strip()))
    return out


def _step_names() -> set:
    """Every name the repo itself recognises: step, alias or substep."""
    from core.cycle_map import STEPS, ALIASES, SUBSTEPS
    return ({s[0] for s in STEPS} | set(ALIASES) | set(SUBSTEPS)
            | {a for a in ALIASES.values()} | {s for s in SUBSTEPS.values()})


@pytest.mark.skipif(not LOG.is_file(), reason="no supervisor.log on this machine")
def test_no_kill_line_names_a_step_that_does_not_exist():
    """step='x' is not a step. A line naming one was written by a test."""
    known = _step_names()
    unknown = collections.Counter(
        m.group("step") for m, _ in _kill_lines(LOG) if m.group("step") not in known)
    assert not unknown, (
        f"logs/supervisor.log has KILL POLICY lines for names that are not steps, "
        f"aliases or substeps in core/cycle_map: {dict(unknown)}. "
        f"These were written by tests. Move them to {QUARANTINE.name} — do not "
        f"delete them.")


@pytest.mark.skipif(not LOG.is_file(), reason="no supervisor.log on this machine")
def test_no_kill_line_repeats_verbatim():
    """Two observations never agree to the digit; a fixture repeats exactly."""
    counts = collections.Counter(text for _, text in _kill_lines(LOG))
    repeated = {t[:110]: n for t, n in counts.items() if n > 1}
    assert not repeated, (
        f"{len(repeated)} KILL POLICY line(s) appear more than once with identical "
        f"age/ceiling/cpu/io/degraded — a measured observation does not repeat to "
        f"the digit, a test literal does. Worst offenders: "
        f"{sorted(repeated.items(), key=lambda kv: -kv[1])[:3]}")


@pytest.mark.skipif(not LOG.is_file(), reason="no supervisor.log on this machine")
def test_kill_counts_agree_with_the_ledger():
    """The authoritative record is the ledger; the log may not out-claim it.

    Not "the two must match": the log legitimately records DEGRADE and WAIT
    verdicts the ledger never sees, and a KILL the supervisor decided but could
    not carry out. What it may NOT do is show a step killed dozens of times that
    the hash-chained ledger has never killed at all.
    """
    import json
    ledger = REPO / "memory" / "existence_ledger.jsonl"
    if not ledger.is_file():
        pytest.skip("no existence ledger on this machine")
    real = collections.Counter()
    for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("event") == "CYCLE_KILLED":
            real[str((rec.get("reason") or {}).get("wedged_step"))] += 1
    claimed = collections.Counter(
        m.group("step") for m, _ in _kill_lines(LOG) if m.group("verdict") == "KILL")
    phantom = {s: n for s, n in claimed.items() if n > 0 and real.get(s, 0) == 0}
    assert not phantom, (
        f"logs/supervisor.log claims KILL for step(s) the ledger has never killed: "
        f"{phantom}. The ledger is the record; the log is text anyone can write.")


def test_the_quarantine_file_says_what_it_is():
    """If the quarantine exists, its first line must disown its own contents.

    A second log full of KILL POLICY lines and no header is a trap for the next
    reader, who would count it as a second source. It has to announce that it is
    not one.
    """
    if not QUARANTINE.is_file():
        pytest.skip("no quarantine file yet — nothing has been moved")
    head = QUARANTINE.read_text(encoding="utf-8", errors="ignore").splitlines()[:1]
    assert head, f"{QUARANTINE.name} is empty but present"
    first = head[0].lower()
    assert ("synthetic" in first or "fixture" in first or "not observations" in first), (
        f"{QUARANTINE.name} must open with a line saying these lines are test "
        f"fixtures moved out of supervisor.log, not observations. First line was: "
        f"{head[0][:120]!r}")
