#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
training/make_shuffled_control.py — the negative control.

Reads cortex_memory/training/train.jsonl and writes train_shuffled.jsonl with every
target reassigned to a DIFFERENT prompt. Prompts, record count, record_kind, ids and
the holdout are untouched. There is nothing true to learn in it.

WHY IT EXISTS, AND WHY IT RUNS FIRST. An eval that reports IMPROVED on a corpus whose
targets have been randomised is not measuring learning — it is measuring a defect in
the bench. Running the control BEFORE the real training is the whole point: a control
added afterwards, once a result is in hand, can always be accused of having been
shaped to excuse it. This one is dated and committed before any real number exists.

EXPECTED: NO EFFECT or WORSE on UNSEEN. If it reports IMPROVED, the fault is in
eval_adapter.py or train_lora.py, not in the data.

THE DERANGEMENT is a single cyclic shift under a seeded permutation, which guarantees
by construction that no index keeps its own target — no rejection sampling, no chance
of a fixed point surviving. It is asserted afterwards anyway.

A HONEST LIMIT, REPORTED NOT HIDDEN: 44% of targets in this corpus are exact
duplicates of another target. Where a row is handed a target that happens to be the
same STRING it already had, the row is not really scrambled. The count is reported as
`unchanged_target_string` — the control is weaker by exactly that fraction, and the
number is printed rather than left for a reader to discover.

  venv\\Scripts\\python.exe training/make_shuffled_control.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
TRAIN = REPO / "cortex_memory" / "training" / "train.jsonl"
OUT = REPO / "cortex_memory" / "training" / "train_shuffled.jsonl"
SEED = 20260904


def derange(n: int, seed: int = SEED) -> list[int]:
    """A permutation with NO fixed point, by construction.

    Take a seeded shuffle of the indices and rotate it by one. Position i receives
    order[(i+1) % n], and since order is a bijection and the rotation moves every
    element, no position can receive its own index.
    """
    if n < 2:
        raise SystemExit("cannot derange fewer than two records")
    order = list(range(n))
    random.Random(seed).shuffle(order)
    mapping = [0] * n
    for i, src in enumerate(order):
        mapping[src] = order[(i + 1) % n]
    return mapping


def main() -> int:
    rows = [json.loads(l) for l in TRAIN.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    n = len(rows)
    mapping = derange(n)

    # every index receives a different index's target
    assert all(mapping[i] != i for i in range(n)), "a fixed point survived"
    assert sorted(mapping) == list(range(n)), "the mapping is not a permutation"

    unchanged_string = 0
    out_rows = []
    for i, r in enumerate(rows):
        donor = rows[mapping[i]]
        if donor["target"] == r["target"]:
            unchanged_string += 1
        out_rows.append({
            **r,
            "target": donor["target"],
            "control": {
                "shuffled": True,
                "seed": SEED,
                "target_taken_from": donor["id"],
                "original_target_sha256_prefix": r["target"][:0],  # never leak it
            },
        })

    # the record set is otherwise identical
    assert len(out_rows) == n
    assert [r["id"] for r in out_rows] == [r["id"] for r in rows]
    assert [r["prompt"] for r in out_rows] == [r["prompt"] for r in rows]
    assert [r["record_kind"] for r in out_rows] == [r["record_kind"] for r in rows]

    with OUT.open("w", encoding="utf-8") as fh:
        for r in out_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(json.dumps({
        "in": str(TRAIN.relative_to(REPO)).replace("\\", "/"),
        "out": str(OUT.relative_to(REPO)).replace("\\", "/"),
        "records": n,
        "seed": SEED,
        "fixed_points": 0,
        "unchanged_target_string": unchanged_string,
        "unchanged_target_pct": round(100 * unchanged_string / n, 2),
        "note": ("rows whose new target is the same STRING as their old one are not "
                 "really scrambled; the corpus has a 44% exact-duplicate target rate, "
                 "so the control is weaker by this fraction and the number is stated "
                 "rather than hidden"),
        "prompts_untouched": True,
        "record_kind_untouched": True,
        "holdout_untouched": True,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
