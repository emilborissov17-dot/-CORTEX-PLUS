#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
training/corpus_from_merkle.py — the K1b corpus, on an explicit key contract.

WHY THIS EXISTS (audited 4 September 2026)
------------------------------------------
merkle_to_training.py:183 reads a decision's text with

    action = d.get("action", "")

Across all 57 archived cycles there are 1326 decision records. `action` appears in
THREE of them (0.2%, all in cycle_000001). `solution` appears in 1323 (99.8%). So
for 99.8% of the corpus that line produced the empty string, and because the
default was "" rather than an error, every one of them was written to disk as a
valid-looking training pair whose target was

    "РЕШЕНИЕ:  (priority=MEDIUM) |  (priority=MEDIUM) | ... РЕЗУЛТАТ: goal_score=0.63"

46 of 46 records in cortex_memory/training/training_data.jsonl are that shape. The
file has been accumulating since 11 July and contains no supervision signal at all.
Nothing consumed it, so nothing complained.

THE RULE THIS FILE ENFORCES: a key that is not in the contract is a REFUSAL with a
named reason, never a default. `.get(key, "")` is what turned a schema mismatch into
2 months of silent garbage, and it does not appear anywhere below.

THE CONTRACT is frozen and explicit: one entry per key-set signature actually
observed in the archive, each naming the exact key that supplies the prompt and the
exact key that supplies the target. A signature not listed here is refused and
reported. When the archive grows a new decision shape, this file fails loudly on it
rather than quietly emitting empty targets — which is the whole point.

  venv\\Scripts\\python.exe training/corpus_from_merkle.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO / "cortex_memory" / "archive"
OUT_DIR = REPO / "cortex_memory" / "training"
TRAIN_FILE = OUT_DIR / "train.jsonl"
HOLDOUT_FILE = OUT_DIR / "holdout.jsonl"
MANIFEST_FILE = OUT_DIR / "corpus_manifest.json"

HOLDOUT_FRACTION = 0.20


# ── THE KEY CONTRACT ─────────────────────────────────────────────────────────
# Keyed by the exact sorted tuple of a decision record's top-level keys.
#   ("problem", "solution")  -> prompt key, target key
#   REFUSE(reason)           -> this signature is known and deliberately excluded
# Built from the 4 Sep 2026 audit: 9 signatures over 1326 records.
class Refuse:
    __slots__ = ("reason",)

    def __init__(self, reason: str):
        self.reason = reason


class Mapping:
    """prompt key, target key, and the STRATUM LABEL for this signature.

    record_kind is derived from the key-set signature the contract matched — it is
    the declared id of the entry that accepted the record, never inferred from the
    content and never defaulted. eval_adapter strata by it, so a wrong or missing
    kind silently merges two populations; there is no default anywhere.
    """
    __slots__ = ("prompt_key", "target_key", "kind")

    def __init__(self, prompt_key: str, target_key: str, kind: str):
        self.prompt_key = prompt_key
        self.target_key = target_key
        self.kind = kind

CONTRACT: dict[tuple, object] = {
    # SIG 1 — 786 records. The plain shape.
    ("component", "generated_by", "measurable_goal", "priority", "problem",
     "real_world_signal", "root_cause", "solution", "timestamp"): Mapping("problem", "solution", "sig01_plain"),
    # SIG 2 — 470 records. Adds the approval/impact block.
    ("agi_characteristic", "approved", "component", "downstream_impact",
     "measurable_goal", "priority", "problem", "real_world_signal", "rejected",
     "root_cause", "solution", "source", "timestamp"): Mapping("problem", "solution", "sig02_approved_with_impact"),
    # SIG 3 — 18 records. Experiment-authored.
    ("authored_by", "component", "experiment_id", "generated_by",
     "measurable_goal", "priority", "problem", "real_world_signal", "solution",
     "timestamp"): Mapping("problem", "solution", "sig03_experiment_authored"),
    # SIG 4 — 18 records. Moral-checked.
    ("accepted_by", "authored_by", "component", "generated_by",
     "measurable_goal", "moral_check", "priority", "problem",
     "real_world_signal", "root_cause", "solution", "timestamp"): Mapping("problem", "solution", "sig04_moral_checked"),
    # SIG 5 — 13 records. Gate-signalled.
    ("authored_by", "component", "gate_signals", "generated_by",
     "measurable_goal", "moral_check", "passes_measurable_gate", "priority",
     "problem", "real_world_signal", "root_cause", "solution", "timestamp",
     "why"): Mapping("problem", "solution", "sig05_gate_signalled"),
    # SIG 6 — 8 records. Feedback note, no component.
    ("agi_characteristic", "approved", "feedback_note", "measurable_goal",
     "priority", "problem", "real_world_signal", "rejected", "root_cause",
     "solution", "source", "timestamp"): Mapping("problem", "solution", "sig06_feedback_no_component"),
    # SIG 7 — 6 records. Dependency check.
    ("approved", "component", "generated_by", "measurable_goal", "priority",
     "problem", "real_world_signal", "rejected", "root_cause", "solution",
     "timestamp"): Mapping("problem", "solution", "sig07_dependency_check"),
    # SIG 8 — 4 records. No component.
    ("agi_characteristic", "approved", "measurable_goal", "priority", "problem",
     "real_world_signal", "rejected", "root_cause", "solution", "source",
     "timestamp"): Mapping("problem", "solution", "sig08_approved_no_component"),
    # SIG 9 — 3 records, all cycle_000001: {"action": "monitor", "priority": "HIGH"}.
    # This is the ONLY signature the old extractor could read, and it is a bare
    # stub: no problem statement, so there is no prompt to pair a target with.
    # Named here so it is refused ON PURPOSE rather than by omission.
    ("action", "priority"): Refuse(
        "bare_action_stub_no_problem_field"),
}


def _cycle_number(dir_name: str) -> int | None:
    m = re.fullmatch(r"cycle_(\d{6})", dir_name)
    return int(m.group(1)) if m else None


def _sha256(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def build(archive: Path | None = None) -> dict:
    """Returns (pairs, refusals, stats). Pure — writes nothing."""
    root = archive or ARCHIVE
    pairs: list[dict] = []
    refusals: list[tuple] = []
    total_in = 0

    dirs = sorted(d for d in root.glob("cycle_*") if d.is_dir())
    for d in dirs:
        n = _cycle_number(d.name)
        f = d / "decisions.json"
        if not f.is_file():
            continue
        try:
            blob = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            refusals.append((d.name, "<unreadable>",
                             f"decisions_json_unreadable:{type(exc).__name__}"))
            continue
        records = blob.get("decisions")
        if not isinstance(records, list):
            refusals.append((d.name, "<no decisions list>",
                             "decisions_key_missing_or_not_a_list"))
            continue

        for i, rec in enumerate(records):
            total_in += 1
            rid = f"{d.name}#decisions[{i}]"
            if not isinstance(rec, dict):
                refusals.append((rid, type(rec).__name__, "record_is_not_an_object"))
                continue

            signature = tuple(sorted(rec.keys()))
            entry = CONTRACT.get(signature)

            if entry is None:
                refusals.append((rid, ",".join(signature),
                                 "key_set_not_in_contract"))
                continue
            if isinstance(entry, Refuse):
                refusals.append((rid, ",".join(signature), entry.reason))
                continue

            prompt_key, target_key = entry.prompt_key, entry.target_key
            # No .get with a default anywhere: the contract asserted these keys
            # exist for this signature, and if that is wrong we want the failure.
            prompt = rec[prompt_key]
            target = rec[target_key]

            if not isinstance(target, str) or not target.strip():
                refusals.append((rid, ",".join(signature),
                                 "empty_target_after_mapping"))
                continue
            if not isinstance(prompt, str) or not prompt.strip():
                refusals.append((rid, ",".join(signature),
                                 "empty_prompt_after_mapping"))
                continue

            pairs.append({
                "id": rid,
                "cycle": n,
                # THE STRATUM KEY. Declared by the contract entry that matched this
                # record's key set — never inferred from content, never defaulted.
                # eval_adapter strata by it: a missing or guessed kind silently
                # merges two populations and reports one number for both.
                "record_kind": entry.kind,
                "prompt": prompt.strip(),
                "target": target.strip(),
                "provenance": {
                    "source_file": str(f.relative_to(REPO)).replace("\\", "/"),
                    "record_id": rid,
                    "cycle_number": n,
                    "record_sha256": _sha256(rec),
                    "prompt_key": prompt_key,
                    "target_key": target_key,
                    "record_kind": entry.kind,
                    "key_signature": list(signature),
                },
            })

    return {"pairs": pairs, "refusals": refusals, "total_in": total_in}


def split_by_time(pairs: list[dict], fraction: float = HOLDOUT_FRACTION) -> tuple:
    """Last `fraction` of CYCLES is held out.

    Split by time, never at random. Consecutive cycles are near-duplicates — the
    same axes, the same sources, often the same unchanged values — so a random
    split puts a near-copy of every holdout row into train and reports a score
    that measures memorisation.
    """
    ordered = sorted(pairs, key=lambda p: (p["cycle"] if p["cycle"] is not None
                                           else -1, p["id"]))
    cycles = sorted({p["cycle"] for p in ordered if p["cycle"] is not None})
    if not cycles:
        return ordered, []
    n_hold = max(1, int(round(len(cycles) * fraction)))
    hold_cycles = set(cycles[-n_hold:])
    train = [p for p in ordered if p["cycle"] not in hold_cycles]
    holdout = [p for p in ordered if p["cycle"] in hold_cycles]
    return train, holdout


def _lengths(pairs: list[dict]) -> dict:
    if not pairs:
        return {"min": None, "median": None, "max": None}
    lens = sorted(len(p["target"]) for p in pairs)
    return {"min": lens[0],
            "median": int(statistics.median(lens)),
            "max": lens[-1]}


def main() -> int:
    built = build()
    pairs, refusals, total_in = built["pairs"], built["refusals"], built["total_in"]

    by_reason = Counter(r[2] for r in refusals)

    if not pairs:
        print(json.dumps({
            "status": "FAILED",
            "reason": "no_pairs_emitted",
            "total_in": total_in,
            "refused": dict(by_reason),
        }, ensure_ascii=False, indent=2))
        print("\nEXIT 1: emitted 0 pairs — refusing to write an empty corpus and "
              "call it success.", file=sys.stderr)
        return 1

    train, holdout = split_by_time(pairs)
    targets = [p["target"] for p in pairs]
    dup_rate = round(1.0 - len(set(targets)) / len(targets), 4)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, rows in ((TRAIN_FILE, train), (HOLDOUT_FILE, holdout)):
        with path.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    train_cycles = [p["cycle"] for p in train if p["cycle"] is not None]
    hold_cycles = [p["cycle"] for p in holdout if p["cycle"] is not None]

    manifest = {
        "built_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "source": "cortex_memory/archive/cycle_*/decisions.json",
        "contract_signatures": len(CONTRACT),
        "total_in": total_in,
        "emitted": len(pairs),
        "refused_total": len(refusals),
        "refused_by_reason": dict(by_reason.most_common()),
        "train_count": len(train),
        "holdout_count": len(holdout),
        "split": "by cycle number, last 20% of cycles held out (never random)",
        "train_cycle_range": [min(train_cycles), max(train_cycles)] if train_cycles else None,
        "holdout_cycle_range": [min(hold_cycles), max(hold_cycles)] if hold_cycles else None,
        "target_len_chars": _lengths(pairs),
        "exact_duplicate_target_rate": dup_rate,
        "record_kind_distribution": dict(
            Counter(p["record_kind"] for p in pairs).most_common()),
        "record_kind_train": dict(
            Counter(p["record_kind"] for p in train).most_common()),
        "record_kind_holdout": dict(
            Counter(p["record_kind"] for p in holdout).most_common()),
        "distinct_targets": len(set(targets)),
        "files": {
            "train": str(TRAIN_FILE.relative_to(REPO)).replace("\\", "/"),
            "holdout": str(HOLDOUT_FILE.relative_to(REPO)).replace("\\", "/"),
        },
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if refusals:
        print("\nREFUSALS (a real result, not a hidden failure)")
        print(f"  {'reason':44s} {'count':>6s}")
        for reason, c in by_reason.most_common():
            print(f"  {reason:44s} {c:6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
