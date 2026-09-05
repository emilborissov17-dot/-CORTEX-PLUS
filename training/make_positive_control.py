#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
training/make_positive_control.py — CAN THE BENCH SEE LEARNING WHEN IT EXISTS? (5 Sep 2026)

We have a NEGATIVE control: deranged targets train to chance on the K=4 ranking bench.
We have no POSITIVE control: nothing shows that an adapter trained with the Run A recipe
on this card, and graded by this bench, can pick up a mapping that is definitely there.
Without it, a chance result on Run A / B / C cannot be told apart from a bench that is
blind. This script writes that control.

THE RULE (known, deterministic, unknown to the base model):
  prompt: four axes with a value in [0,1] and a night-over-night delta, in random order.
  target: one of 12 PROTOCOL codes, chosen by
      group     = which axis has the LOWEST value            (4 groups)
      direction = that axis's delta: down / flat / up        (3 directions)
  Each code's text is arbitrary and mentions NO axis, so the axis-name rule that reads
  the prompt and matches a name in the target (the 0.57 ceiling on the real corpus) is
  at chance here, and so is the base model. Only the learned mapping can rise above 0.20.

WHAT THIS PROVES AND DOES NOT PROVE. Above chance = the recipe + bench can detect a real
mapping of this size (300 rows, 12 classes, 1 epoch). At chance = the bench is blind or
the recipe is too thin - and then a chance result on the real corpus means NOTHING.
It says nothing about the world; it is a test of the instrument.

SEEN IS THE VERDICT HERE. Every holdout target is one of the same 12 codes, so the
bench's SEEN/UNSEEN split (built for free-text duplicates) marks everything SEEN. For a
finite label set that is correct and harmless: memorising a target STRING does not help
choose among 5 codes drawn from the same pool. Pre-registered before any number exists.

  venv\\Scripts\\python.exe training/make_positive_control.py
  -> cortex_memory/training/positive_control/{train,holdout}.jsonl + manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "cortex_memory" / "training" / "positive_control"

AXES = ("CLIMATE", "CONFLICT", "ENERGY", "HEALTH")
DIRECTIONS = ("down", "flat", "up")
FLAT_EPS = 0.01
RECORD_KIND = "pc01_rule"

# 12 codes. Similar token length (the bench draws distractors within a +/-25% length
# band), no axis names, no shared keywords with the direction words.
CODES = {
    ("CLIMATE", "down"):  "PROTOCOL-K: hold the scout budget and re-verify the three oldest sources.",
    ("CLIMATE", "flat"):  "PROTOCOL-M: publish the weekly digest and defer every new source request.",
    ("CLIMATE", "up"):    "PROTOCOL-R: widen the interval on the slow tier and log the reason.",
    ("CONFLICT", "down"): "PROTOCOL-D: rotate the reporter set and archive the stale feeds.",
    ("CONFLICT", "flat"): "PROTOCOL-V: freeze the composite and request a human read of the ledger.",
    ("CONFLICT", "up"):   "PROTOCOL-B: move the fast tier to hourly and suspend the extra calls.",
    ("ENERGY", "down"):   "PROTOCOL-T: reopen the quarantine folder and grade the oldest patch.",
    ("ENERGY", "flat"):   "PROTOCOL-J: rebuild the provenance closure and post it to the journal.",
    ("ENERGY", "up"):     "PROTOCOL-Q: cap the token budget and skip the media worker tonight.",
    ("HEALTH", "down"):   "PROTOCOL-W: escalate once by name and keep the lock until morning.",
    ("HEALTH", "flat"):   "PROTOCOL-F: re-run the notary on the last sealed cycle and diff it.",
    ("HEALTH", "up"):     "PROTOCOL-N: lower the ratchet by one and write the named set to disk.",
}


def rule(readings: dict) -> str:
    """readings: axis -> (value, delta). Deterministic; the whole point."""
    lowest = min(AXES, key=lambda a: (readings[a][0], a))
    d = readings[lowest][1]
    direction = "flat" if abs(d) <= FLAT_EPS else ("down" if d < 0 else "up")
    return CODES[(lowest, direction)]


def render(readings: dict, order: list) -> str:
    parts = []
    for a in order:
        v, d = readings[a]
        arrow = "flat" if abs(d) <= FLAT_EPS else (f"down {abs(d):.2f}" if d < 0 else f"up {d:.2f}")
        parts.append(f"{a} {v:.2f} ({arrow})")
    return "Night reading. " + ". ".join(parts) + ". Which protocol applies?"


def make_row(rng: random.Random, i: int, split: str) -> dict:
    # Values spread so the minimum is usually unambiguous; deltas so all three
    # directions occur (flat ~1/3 by construction).
    readings = {}
    for a in AXES:
        v = round(rng.uniform(0.05, 0.95), 2)
        kind = rng.random()
        if kind < 0.34:
            d = round(rng.uniform(-FLAT_EPS, FLAT_EPS), 3)
        elif kind < 0.67:
            d = -round(rng.uniform(0.02, 0.12), 2)
        else:
            d = round(rng.uniform(0.02, 0.12), 2)
        readings[a] = (v, d)
    vals = sorted(r[0] for r in readings.values())
    if vals[1] - vals[0] < 0.03:  # tie-ish minimum: make the rule readable
        lowest = min(AXES, key=lambda a: (readings[a][0], a))
        readings[lowest] = (round(max(0.01, vals[0] - 0.05), 2), readings[lowest][1])
    order = list(AXES)
    rng.shuffle(order)
    prompt = render(readings, order)
    target = rule(readings)
    rec = {
        "id": f"pc_{split}_{i:04d}",
        "cycle": 100000 + i,                      # never collides with the archive
        "record_kind": RECORD_KIND,
        "prompt": prompt,
        "target": target,
        "provenance": {
            "source_file": "training/make_positive_control.py",
            "record_id": f"pc_{split}_{i:04d}",
            "cycle_number": 100000 + i,
            "record_sha256": hashlib.sha256((prompt + "\n" + target).encode("utf-8")).hexdigest(),
            "prompt_key": "synthetic",
            "target_key": "rule",
            "record_kind": RECORD_KIND,
            "readings": {a: {"value": readings[a][0], "delta": readings[a][1]} for a in AXES},
        },
    }
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=300)
    ap.add_argument("--holdout", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260905)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(a.seed)
    train = [make_row(rng, i, "train") for i in range(a.train)]
    hold = [make_row(rng, i, "holdout") for i in range(a.holdout)]

    # Sanity, printed and refused-on-failure: every code occurs in train, every
    # holdout code occurs in train (SEEN by construction), all 12 codes reachable.
    tr_codes = {r["target"] for r in train}
    ho_codes = {r["target"] for r in hold}
    if tr_codes != set(CODES.values()):
        print(f"REFUSED: train covers {len(tr_codes)}/12 codes; raise --train or change the seed")
        return 2
    if not ho_codes <= tr_codes:
        print("REFUSED: a holdout code never occurs in train")
        return 2

    for name, rows in (("train.jsonl", train), ("holdout.jsonl", hold)):
        with (out / name).open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    from collections import Counter
    manifest = {
        "written_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "seed": a.seed, "train": a.train, "holdout": a.holdout,
        "record_kind": RECORD_KIND, "codes": 12,
        "rule": "lowest of 4 axes x direction of its delta (down/flat/up, |d|<=0.01 flat) -> code",
        "chance_k4": 0.20,
        "expected_base": "chance (codes name no axis; no language prior can pick them)",
        "verdict_table": "SEEN (finite label set: every holdout target is in train by construction)",
        "pass": "adapter accuracy CI entirely above 0.20 AND above base CI on SEEN pc01_rule",
        "fail_means": "the bench or the Run A recipe cannot see a real 12-way mapping in 300 rows; "
                      "then chance on the real corpus is uninterpretable",
        "train_code_counts": dict(Counter(r["target"].split(":")[0] for r in train)),
        "holdout_code_counts": dict(Counter(r["target"].split(":")[0] for r in hold)),
        "sha256": {"train.jsonl": sha(out / "train.jsonl"), "holdout.jsonl": sha(out / "holdout.jsonl")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"positive control -> {out}")
    print(f"  train {a.train} rows, holdout {a.holdout} rows, 12 codes, record_kind {RECORD_KIND}")
    print(f"  train code counts  : {manifest['train_code_counts']}")
    print(f"  holdout code counts: {manifest['holdout_code_counts']}")
    print(f"  sha256 train {manifest['sha256']['train.jsonl'][:16]}  holdout {manifest['sha256']['holdout.jsonl'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
