#!/usr/bin/env python3
"""
experiments/goalcraft/measurable_goal.py — the (G) rule as a value/goal-loop probe.

VALUE/GOAL LOOP (organism_loops.md #6): a system that sets its OWN goals must
distinguish a measurable goal ("reduce heavy-metal incidents by 40% by 2028")
from a restated problem ("water scarcity management"). The 12 junk patches that
flooded the quarantine were exactly the latter. This is the gate at the INPUT —
the logical twin of the AST gate we loosened at the write side.

FALSIFIABLE TEST (ground truth = the human's own quarantine decisions):
does this rule agree with the human on which proposed goals are genuinely
measurable, and does it BEAT the majority-class baseline (which, since most were
junk, gets high accuracy by rejecting everything — and therefore approves NO real
goal, recall 0)? The rule earns its place only if it keeps recall on real goals
while rejecting junk.

A measurable goal needs a QUANTITY (a percentage or a count) AND either a
DEADLINE (a year) or a DIRECTION of change — and must not be dominated by vague
task/meta language with no number in it.
"""
from __future__ import annotations

import re

_PERCENT = re.compile(r"\d+\s*%|%")
_YEAR = re.compile(r"\b20\d\d\b")
_NUMBER = re.compile(r"\b\d+\b")
_DIRECTION = re.compile(
    r"намал|редуц|reduce|increas|увелич|подобр|improv|поне|най-малко|минимум|≥|at least|to\s+\d", re.I)
_VAGUE = re.compile(
    r"strateg|management|разработване|оценка на|преглед|review|update|стратеги|"
    r"не са оптимизирани|not optimi|insufficient|scarcity|стартирайте|устойчив|assessment", re.I)


def measurable_signals(text: str) -> dict:
    t = (text or "").lower()
    has_percent = bool(_PERCENT.search(t))
    has_year = bool(_YEAR.search(t))
    non_year_nums = [n for n in _NUMBER.findall(t) if not re.fullmatch(r"20\d\d", n)]
    has_number = has_percent or bool(non_year_nums)
    has_direction = bool(_DIRECTION.search(t))
    vague = bool(_VAGUE.search(t))
    return {"percent": has_percent, "year": has_year, "number": has_number,
            "direction": has_direction, "vague": vague}


def is_measurable(text: str) -> tuple[bool, dict]:
    s = measurable_signals(text)
    quantity = s["percent"] or s["number"]
    deadline_or_direction = s["year"] or s["direction"]
    measurable = quantity and deadline_or_direction
    # Vague task/meta language with no hard number or year can never be a goal.
    if s["vague"] and not (s["percent"] or s["year"]):
        measurable = False
    return measurable, s


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        ok, sig = is_measurable(arg)
        print(f"{'MEASURABLE' if ok else 'not-measurable':16} {arg[:60]!r}  {sig}")
