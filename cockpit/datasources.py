#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cockpit/datasources.py — WHAT EACH PANEL READS, AND WHETHER IT IS THERE.

ONE TABLE, NOT TWO
-------------------
The recon that produced this list and the code that renders the cockpit are the
same object. A recon printed once into a commit message goes stale the first
time a file moves; a table the server actually reads cannot, because a panel
whose file has moved renders "no data yet" the moment it does.

    venv/Scripts/python.exe -m cockpit.datasources        # prints the table

THE HONEST-EMPTY RULE
----------------------
Every panel below names exactly the files it reads. If none of them exist, the
panel renders a "no data yet" card naming the missing path. It does NOT render
zeros, it does not render an example, and it does not borrow a neighbouring
file that happens to have the right shape. This repo's own audit history is a
list of the times something rendered a plausible number nobody had measured.

READ-ONLY, AND SAYING SO IN THE TYPE
--------------------------------------
Nothing in this module opens a file for writing. The cockpit has exactly three
writeful endpoints and they live elsewhere, named, in cockpit/server.py.
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

BASE = pathlib.Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Source:
    """One file a panel reads."""
    rel: str
    what: str
    required: bool = True

    @property
    def path(self) -> pathlib.Path:
        return BASE / self.rel

    def exists(self) -> bool:
        return self.path.exists()

    def size(self) -> Optional[int]:
        try:
            return self.path.stat().st_size
        except OSError:
            return None

    def mtime(self) -> Optional[str]:
        try:
            return datetime.fromtimestamp(
                self.path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            return None


@dataclass(frozen=True)
class Panel:
    """One cockpit panel and the files behind it."""
    key: str
    title: str
    sources: tuple
    note: str = ""

    def missing(self) -> list:
        return [s for s in self.sources if s.required and not s.exists()]

    def live(self) -> bool:
        """True when every REQUIRED source is present."""
        return not self.missing()

    def status(self) -> dict:
        return {
            "panel": self.key,
            "title": self.title,
            "live": self.live(),
            "note": self.note,
            "sources": [{"path": s.rel, "what": s.what, "required": s.required,
                         "exists": s.exists(), "bytes": s.size(),
                         "mtime_utc": s.mtime()}
                        for s in self.sources],
            "missing": [s.rel for s in self.missing()],
        }


# ---------------------------------------------------------------------------
# THE TABLE. Verified against this repo on 22 August 2026.
# ---------------------------------------------------------------------------

PANELS = (
    Panel("cycles", "Cycles as checklists", (
        Source("memory/cycle_resume.jsonl", "completed steps per cycle"),
        Source("memory/heartbeat.json", "the step running right now"),
        Source("memory/existence_ledger.jsonl", "CYCLE_FINISHED seals"),
        Source("memory/survival_state.json", "the survival latch badge", False),
        Source("memory/step_contract_latest.json", "per-step verdicts (DEGRADED count)"),
    ), note="the remaining grey steps come from core.cycle_map.STEPS (55 steps, code not a file)"),

    Panel("flow", "Flow Score needle", (
        Source("memory/flow_score.jsonl", "the score history"),
        Source("memory/step_contract_latest.json", "steps to compute a live score from"),
    ), note="flow_score.jsonl does not exist yet; core/flow_score.py can compute from the contract"),

    Panel("forks", "Forks of the public repo", (
        Source("memory/cockpit_forks_cache.json", "disk cache of the GitHub forks call", False),
    ), note="network call is manual-refresh only and fails soft; the cache is written by the refresh"),

    Panel("pending", "Pending-human queue", (
        Source("memory/proposal_sla_queue.json", "the SLA queue table", False),
        Source("memory/improvement_proposals.json", "unresolved proposals"),
        Source("memory/threshold_proposals.json", "unsigned threshold suggestions"),
        Source("patches/quarantine", "quarantined patches (directory)"),
        Source("memory/deferred_batch.json", "tasks deferred to the 8b window", False),
        Source("memory/openclaw_pending_l3.json", "level-3 actions awaiting approval", False),
    )),

    Panel("thoughts", "System thoughts", (
        Source("memory/phase_debriefs", "per-phase debriefs incl. rejected attempts"),
        Source("memory/brain_stance.json", "the current stance"),
        Source("memory/idea_stream.jsonl", "the creative tick"),
        Source("experiments/dreams", "the micro-cycle dream note (YYYY-MM-DD.md)", False),
        Source("memory/self_mirror_latest.json", "the mirror read", False),
        Source("memory/hypotheses.jsonl", "the hypotheses ledger", False),
        Source("memory/grounding_ledger.jsonl", "the divergence/grounding ledger", False),
    )),

    Panel("proposals", "Proposals by author", (
        Source("memory/improvement_proposals.json", "proposals, grouped by generated_by"),
    ), note="the author field is `generated_by`, NOT `authored_by`: 22 of 40 rows carry it"),

    Panel("goal", "Goal, 5 nerves, 25 axes, 7 continents", (
        Source("memory/goal_score_history.json", "composite history (49 points)"),
        Source("output/cortex_scores_latest.json", "latest per-axis scores"),
        Source("output/wellbeing_continent.json", "per-continent wellbeing (7 regions)"),
        Source("config/target_config.json", "the axis tree grouped by subgoal"),
    )),

    Panel("columns", "Five columns", (
        Source("memory/columns/track_record.json", "per-source track record", False),
        Source("memory/columns", "stored claim records (directory)", False),
        Source("config/reporter_independence.json", "org -> independence class"),
    ), note="core/three_columns.py is NOT WIRED: nothing writes memory/columns/ today"),

    Panel("expression", "Expression window", (
        Source("memory/expression_stream.jsonl", "the one stream", False),
        Source("memory/pending_expression.json", "unread indicator", False),
        Source("memory/human_input_queue.db", "PULL dialogue (sqlite)", False),
        Source("config_expression.yaml", "lexicon christening + SILENCE_MODE", False),
    ), note="all four are created by the expression module; none exist before its first run"),

    Panel("somatic", "Somatic map", (
        Source("memory/body_scan_latest.json", "the cycle's own body scan", False),
        Source("memory/somatic_latest.json", "the cockpit's own sensor read", False),
    ), note="most rows are read live from hardware, not from a file"),

    Panel("terminal", "Embedded terminal", (
        Source("memory/cockpit_terminal.log", "append-only terminal I/O", False),
    )),
)

PANELS_BY_KEY = {p.key: p for p in PANELS}


def table() -> list:
    return [p.status() for p in PANELS]


def _print_table() -> int:
    rows = table()
    print("PANEL -> DATA FILE -> EXISTS TODAY")
    print("=" * 96)
    print("{:<11} {:<52} {:<9} {:>10}".format("PANEL", "FILE", "REQUIRED", "EXISTS"))
    print("-" * 96)
    for r in rows:
        for i, s in enumerate(r["sources"]):
            print("{:<11} {:<52} {:<9} {:>10}".format(
                r["panel"] if i == 0 else "",
                s["path"][:52],
                "yes" if s["required"] else "optional",
                "YES" if s["exists"] else "NO"))
        if r["note"]:
            print("{:<11} note: {}".format("", r["note"]))
        print("-" * 96)

    live = [r["panel"] for r in rows if r["live"]]
    dead = [r["panel"] for r in rows if not r["live"]]
    print()
    print("PANELS WITH ALL REQUIRED DATA PRESENT ({}): {}".format(
        len(live), ", ".join(live) or "(none)"))
    print("PANELS THAT WILL RENDER 'no data yet' ({}): {}".format(
        len(dead), ", ".join(dead) or "(none)"))
    for r in rows:
        if not r["live"]:
            print("  {:<11} missing: {}".format(r["panel"], ", ".join(r["missing"])))
    return 0


if __name__ == "__main__":
    sys.exit(_print_table())
