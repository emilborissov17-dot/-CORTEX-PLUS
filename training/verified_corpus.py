#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
training/verified_corpus.py — THE ONLY CORPUS THE LOCAL STUDENT MAY LEARN FROM.
(10 Sep 2026. Emil: "кой е нашият локален мозък, той как ще се учи?")

The archive-LoRA died on 6 Sep because its corpus was the system's own
LLM-written decisions: no world in it. This corpus is built from the two places
where the world has ANSWERED:

  A. memory/verified_observations.jsonl — task cards whose quote the gate found
     on the live page (core/card_intake.py). Example: (card -> verified JSON).
     This is the sensor task: short input, number out — the first task a 3B
     student on 4 GB can carry, and the one an external teacher (Opus today)
     already performs; every accepted card is one distillation pair.
  B. experiments/prophecy/prophecy_ledger.jsonl — sealed predictions that have
     been SCORED. Example: (state at seal time -> outcome). The student learns
     to predict what the ledger later confirmed, never what a model asserted.

Nothing else. No decisions.json, no proposals, no LLM prose. A row that cannot
be traced to a gate verdict or a scored outcome is refused at build time, and
test/test_verified_corpus.py holds a negative control: a record that merely
LOOKS verified (right shape, no verdict) must not enter.

Output: training/verified_corpus.jsonl, one {"task","input","target","provenance"}
per line, plus a manifest with counts and the sha256 of the file — so Run C, when
it comes, trains on a corpus whose every row can be pointed back to the world.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERIFIED = REPO / "memory" / "verified_observations.jsonl"
LEDGER = REPO / "experiments" / "prophecy" / "prophecy_ledger.jsonl"
OUT = REPO / "training" / "verified_corpus.jsonl"
MANIFEST = REPO / "training" / "verified_corpus.manifest.json"


def _jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def rows_from_observations(obs: list[dict]) -> list[dict]:
    out = []
    for o in obs:
        v = o.get("verdict")
        rec = o.get("record") or {}
        if v not in ("ACCEPTED", "NULL_WITH_REASON") or not o.get("card_key"):
            continue                      # not confirmed by the world -> not a lesson
        task = {"axis": rec.get("axis"), "key": rec.get("key"), "url": rec.get("url"),
                "date": rec.get("observed_date")}
        target = {"value": rec.get("value"), "unit": rec.get("unit"), "quote": rec.get("quote"),
                  "reason": rec.get("reason")}
        out.append({"task": "sensor_card", "input": task, "target": target,
                    "provenance": {"card_key": o["card_key"], "verdict": v, "page_sha256": o.get("page_sha256"),
                                   "judged_utc": o.get("judged_utc")}})
    return out


def rows_from_ledger(records: list[dict]) -> list[dict]:
    sealed = {r.get("hash"): r for r in records if r.get("event") == "PREDICTION_SEALED"}
    out = []
    for r in records:
        if r.get("event") != "OUTCOME_SCORED":
            continue
        s = sealed.get(r.get("ref_hash"))
        if not s or s.get("degenerate") is True:
            continue
        out.append({"task": f"predict:{s.get('target_kind')}",
                    "input": {k: s.get(k) for k in ("target_id", "basis", "seen", "seen_cycles", "current_score",
                                                     "indicator", "step", "axis") if s.get(k) is not None},
                    "target": {"actual": r.get("actual"), "learner": s.get("learner"), "baseline": s.get("baseline"),
                               "learner_err": r.get("learner_err"), "baseline_err": r.get("baseline_err")},
                    "provenance": {"sealed_hash": s.get("hash"), "outcome_hash": r.get("hash"), "sealed_ts": s.get("ts"),
                                   "scored_ts": r.get("ts")}})
    return out


def build(write: bool = True) -> dict:
    rows = rows_from_observations(_jsonl(VERIFIED)) + rows_from_ledger(_jsonl(LEDGER))
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    by_task: dict = {}
    for r in rows:
        by_task[r["task"]] = by_task.get(r["task"], 0) + 1
    manifest = {"built_utc": datetime.now(timezone.utc).isoformat(), "rows": len(rows), "by_task": by_task,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "sources": {"verified_observations": str(VERIFIED.relative_to(REPO)), "prophecy_ledger": str(LEDGER.relative_to(REPO))},
                "rule": "only gate-ACCEPTED/NULL_WITH_REASON cards and SCORED non-degenerate predictions; nothing asserted by a model"}
    if write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(write="--dry" not in sys.argv), ensure_ascii=False, indent=2))
