#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/claim_scan.py — find prose that ASSERTS how the code behaves.

WHY (19 September 2026). test_heartbeat_coverage's docstring said "the watchdog's
per-step ceiling is keyed on that id, so a slow step reporting a fast step's
number gets killed early". Every identifier in it was real. The RELATION was
invented: supervisor.ceiling_for() keys on the step NAME, and
config/scheduler.json carries seventeen ceiling keys, all names and no ids. That
sentence was copied into a triage report as rank-1 evidence and planned against.

WHAT THIS CAN AND CANNOT DO, stated plainly because the distinction is the whole
point. It finds SENTENCES THAT MAKE BEHAVIOUR CLAIMS. It does not, and cannot,
decide whether a claim is TRUE — the watchdog sentence would have passed any
existence check, because everything it named existed. Measured the same day: an
automated attempt to falsify 188 such claims produced 17 flags of which
essentially all were false positives, while the four genuinely false sentences
were found only by reading the code.

So this is a POPULATION net, in the shape of test/known_failures.txt: it freezes
the inventory that exists today and names anything NEW. It stops the population
growing in silence. It makes no claim about the sentences already in it.

A sentence qualifies when it BOTH
  (a) names a code entity — snake_case, a dotted path, a *.py/*.json file, a
      CamelCase class or a CONSTANT — and
  (b) uses a present-tense indicative verb of behaviour about it.

Normative sentences (must, should, never write, "rule", "decision") are DECISIONS
and RULES, which CLAUDE.md allows freely. Past-tense narration is history, also
allowed. Both are excluded.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCOPE = ("test", "core")

ENTITY = re.compile(
    r"(\b[a-z_][a-z0-9_]*\.(?:py|json|jsonl|txt|md)\b"
    r"|\b[a-z_][a-z0-9_]{3,}\.[a-z_][a-z0-9_]{2,}\b"
    r"|\b[a-z][a-z0-9]*_[a-z0-9_]{2,}\b"
    r"|\b[A-Z][a-z]+[A-Z][A-Za-z]+\b"
    r"|\b[A-Z][A-Z0-9_]{4,}\b)")

VERB = re.compile(
    r"\b(is keyed on|keys on|is read by|reads|is written by|writes|is called by"
    r"|calls|returns|raises|fires|refuses|guarantees|counts|holds|stores"
    r"|records|emits|produces|consumes|loads|parses|appends|overwrites"
    r"|defaults to|falls back to|resolves to|points at|maps to|lives in"
    r"|is set by|sets|is passed|passes|feeds|drives|gates|blocks)\b", re.I)

NORM = re.compile(
    r"\b(must|should|shall|do not|don't|never write|never add|never use|never put"
    r"|rule|decision|ruling|norm|forbidden|allowed|policy|WHY|because we"
    r"|TODO|will be|would be|could be|may be|plan|intend)\b", re.I)

PAST = re.compile(
    r"\b(was|were|had|did|used to|until|before|on \d{1,2} [A-Z][a-z]{2}"
    r"|\d{4}-\d{2}-\d{2}|измер|беше|бяха)\b")


def _sentences(text: str):
    text = re.sub(r"\s+", " ", text).strip()
    for s in re.split(r"(?<=[.!?])\s+(?=[A-ZА-Я])", text):
        s = s.strip()
        if 25 <= len(s) <= 320:
            yield s


def _prose(path: Path):
    """(line, owner, text) for every docstring and contiguous comment block."""
    out = []
    try:
        src = io.open(path, encoding="utf-8", errors="replace").read()
        tree = ast.parse(src)
    except Exception:                                        # noqa: BLE001
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            d = ast.get_docstring(node)
            if d:
                out.append((getattr(node, "lineno", 1),
                            getattr(node, "name", "<module>"), d))
    block, start = [], None
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            if start is None:
                start = i
            block.append(s.lstrip("#").strip())
        else:
            if block:
                out.append((start, "<comment>", " ".join(block)))
            block, start = [], None
    if block:
        out.append((start, "<comment>", " ".join(block)))
    return out


def fingerprint(rel: str, sentence: str) -> str:
    """File plus a hash of the sentence. Not the line number: a claim that only
    MOVED is the same claim, and a net that fires on every insertion above it
    would be noise within a day."""
    norm = re.sub(r"\s+", " ", sentence).strip().lower()
    return "%s %s" % (rel, hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12])


def scan(repo: Path | None = None):
    repo = repo or REPO
    found = []
    for d in SCOPE:
        for f in sorted((repo / d).glob("*.py")):
            rel = f.relative_to(repo).as_posix()
            for lineno, owner, text in _prose(f):
                for s in _sentences(text):
                    if NORM.search(s) or PAST.search(s):
                        continue
                    if ENTITY.search(s) and VERB.search(s):
                        found.append({"file": rel, "line": lineno, "owner": owner,
                                      "sentence": s, "fp": fingerprint(rel, s)})
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args()
    hits = scan()
    print("behaviour-asserting sentences in %s/: %d" % ("/, ".join(SCOPE), len(hits)))
    if a.write_baseline:
        out = REPO / "test" / "behaviour_claims.txt"
        lines = [
            "# test/behaviour_claims.txt — the behaviour claims this repo has ACCEPTED.",
            "#",
            "# One per line: <file> <sha1-12 of the sentence>, then the sentence.",
            "# Produced by tools/claim_scan.py --write-baseline and checked by",
            "# test/test_behaviour_claims_are_backed.py.",
            "#",
            "# A LINE HERE IS A DEBT, NOT A CERTIFICATE. It does not say the sentence is",
            "# true; it says nobody has yet pointed at an assertion that would fail if it",
            "# stopped being true. Four of these were found FALSE on 19 Sep by reading the",
            "# code, and no scanner found them.",
            "#",
            "# Adding a behaviour sentence without a test means adding a line here, in the",
            "# same commit, on purpose. Removing one because it now has a test, or because",
            "# it was deleted, is the direction this file is supposed to move.",
            "",
        ]
        for h in sorted(hits, key=lambda x: (x["file"], x["fp"])):
            lines.append("%s  # %s" % (h["fp"], h["sentence"][:150]))
        io.open(out, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
        print("wrote %s (%d entries)" % (out, len(hits)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
