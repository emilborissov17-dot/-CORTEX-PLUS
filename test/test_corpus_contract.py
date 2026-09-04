# -*- coding: utf-8 -*-
"""
training/corpus_from_merkle.py — the properties that make the corpus worth training on.

Every one of these guards a failure that ALREADY HAPPENED here. merkle_to_training.py
read d.get("action", "") against records that carry "solution"; 99.8% of the archive
mapped to the empty string, and because the default was "" rather than an error, 46
empty pairs were written to disk and reported as success for two months.

So: an empty target is a test failure, an unknown key-set is a test failure, and a
random split is a test failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import training.corpus_from_merkle as C   # noqa: E402


@pytest.fixture(scope="module")
def built():
    return C.build()


@pytest.fixture(scope="module")
def split(built):
    return C.split_by_time(built["pairs"])


# ── the defect that produced 46 empty rows ───────────────────────────────────

def test_no_emitted_record_has_an_empty_target(built):
    """THE ORIGINAL BUG, as a test. Not one emitted pair may carry a blank target."""
    bad = [p["id"] for p in built["pairs"] if not p["target"].strip()]
    assert bad == [], f"{len(bad)} emitted pairs have an empty target: {bad[:5]}"


def test_no_emitted_record_has_an_empty_prompt(built):
    bad = [p["id"] for p in built["pairs"] if not p["prompt"].strip()]
    assert bad == [], f"{len(bad)} emitted pairs have an empty prompt: {bad[:5]}"


def test_something_is_actually_emitted(built):
    """A contract that refuses everything is not a contract, it is a wall."""
    assert built["pairs"], "the builder emitted nothing at all"


# ── the split ────────────────────────────────────────────────────────────────

def test_no_record_appears_in_both_train_and_holdout(split):
    train, holdout = split
    overlap = {p["id"] for p in train} & {p["id"] for p in holdout}
    assert overlap == set(), f"{len(overlap)} ids leak across the split"


def test_every_holdout_cycle_is_later_than_every_train_cycle(split):
    """Split by TIME. Consecutive cycles are near-duplicates — the same axes, the
    same sources, often bit-identical values — so a random split puts a near-copy
    of every holdout row into train and scores memorisation."""
    train, holdout = split
    if not train or not holdout:
        pytest.skip("not enough cycles to split")
    max_train = max(p["cycle"] for p in train if p["cycle"] is not None)
    min_hold = min(p["cycle"] for p in holdout if p["cycle"] is not None)
    assert min_hold > max_train, (
        f"holdout cycle {min_hold} is not later than train cycle {max_train} — "
        f"the split is not chronological")


# ── the contract refuses what it does not know ───────────────────────────────

def test_an_unknown_key_set_is_refused_with_a_reason(tmp_path):
    """The guard against the next schema drift. A made-up key must not be silently
    emptied — it must come back as a refusal naming the observed key set."""
    arch = tmp_path / "archive"
    d = arch / "cycle_000001"
    d.mkdir(parents=True)
    (d / "decisions.json").write_text(json.dumps({"decisions": [
        {"totally_made_up_key": "hello", "another_invention": "world"},
    ]}), encoding="utf-8")

    out = C.build(archive=arch)

    assert out["pairs"] == [], "an unknown key-set was emitted instead of refused"
    assert len(out["refusals"]) == 1
    rid, observed, reason = out["refusals"][0]
    assert reason == "key_set_not_in_contract"
    assert "totally_made_up_key" in observed, \
        "the refusal does not report the key set it actually saw"


def test_a_known_signature_with_a_blank_target_is_refused_not_emitted(tmp_path):
    """empty_target_after_mapping: the contract matched, but the value was blank."""
    arch = tmp_path / "archive"
    d = arch / "cycle_000002"
    d.mkdir(parents=True)
    rec = {"component": "X", "generated_by": "g", "measurable_goal": "m",
           "priority": "HIGH", "problem": "a real problem", "real_world_signal": "s",
           "root_cause": "r", "solution": "   ", "timestamp": "t"}
    assert tuple(sorted(rec.keys())) in C.CONTRACT, "fixture drifted from the contract"
    (d / "decisions.json").write_text(json.dumps({"decisions": [rec]}),
                                      encoding="utf-8")

    out = C.build(archive=arch)

    assert out["pairs"] == []
    assert out["refusals"][0][2] == "empty_target_after_mapping"


def test_the_bare_action_stub_is_refused_on_purpose(tmp_path):
    """SIG 9 — {"action","priority"} — is the ONLY shape the old extractor could
    read, and it has no problem statement to pair a target with. It is named in the
    contract so it is refused deliberately rather than by omission."""
    arch = tmp_path / "archive"
    d = arch / "cycle_000003"
    d.mkdir(parents=True)
    (d / "decisions.json").write_text(json.dumps({"decisions": [
        {"action": "monitor", "priority": "HIGH"}]}), encoding="utf-8")

    out = C.build(archive=arch)

    assert out["pairs"] == []
    assert out["refusals"][0][2] == "bare_action_stub_no_problem_field"


def test_the_source_uses_no_get_with_a_default(built):
    """STRUCTURAL. `.get(key, "")` is what turned a schema mismatch into two months
    of silent garbage. It may not reappear in the mapping path."""
    src = (REPO / "training" / "corpus_from_merkle.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[2]          # skip the module docstring
    assert '.get("' not in body.replace('.get("decisions")', ''), \
        "a .get with a default crept back into the mapping path"


# ── provenance ───────────────────────────────────────────────────────────────

def test_every_pair_carries_checkable_provenance(built):
    for p in built["pairs"][:200]:
        pr = p["provenance"]
        assert pr["source_file"].endswith("decisions.json")
        assert pr["record_id"] == p["id"]
        assert isinstance(pr["cycle_number"], int)
        assert len(pr["record_sha256"]) == 64
        assert pr["target_key"] == "solution"
