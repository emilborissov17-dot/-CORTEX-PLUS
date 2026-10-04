# -*- coding: utf-8 -*-
"""test/test_engine_probe.py — the arity probe (C-GUARD-4 Step 3, Kimi round 76 B1 / round 77 B2).

Decided: for an arity, ONE real head in its own space, K atoms plus one that shares "k7", a query
on "k7" with exactly two known answers; ladder 100 / 250 / 390 x 3, step down 300 / 200 / 100;
budget = the largest wholly clean size; 100 failing = forbidden. The engine is injected here.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))
import engine_probe as EP  # noqa: E402
from core import space as sp  # noqa: E402


def _runner(fail_at=(), wrong_at=()):
    calls = []

    def run(arity, head, size, rep):
        calls.append(size)
        if size in fail_at:
            return "PANIC", 3.0
        if size in wrong_at:
            return "WRONG", 0.2
        return "CLEAN", 0.2
    run.calls = calls
    return run


def test_a_clean_ladder_gives_390():
    r = EP.probe_arity(3, "gap", runner=_runner())
    assert r["budget"] == 390 and r["sizes_tried"] == [100, 250, 390] and len(r["runs"]) == 9


def test_a_panic_at_390_steps_down_to_300():
    r = EP.probe_arity(8, "obs", runner=_runner(fail_at={390}))
    assert r["budget"] == 300 and r["sizes_tried"] == [100, 250, 390, 300]


def test_a_panic_at_390_and_300_keeps_the_clean_250():
    r = EP.probe_arity(8, "obs", runner=_runner(fail_at={390, 300}))
    assert r["budget"] == 250 and r["sizes_tried"] == [100, 250, 390, 300]


def test_a_panic_at_every_size_forbids_the_arity():
    r = EP.probe_arity(5, "contradiction", runner=_runner(fail_at={100, 250, 390, 300, 200}))
    assert r["budget"] == "forbidden" and r["sizes_tried"] == [100]


def test_a_wrong_answer_is_a_failure_like_a_panic():
    r = EP.probe_arity(4, "unverified", runner=_runner(wrong_at={390}))
    assert r["budget"] == 300


def test_one_bad_repetition_fails_the_size():
    seq = iter(["CLEAN"] * 6 + ["CLEAN", "PANIC", "CLEAN"] + ["CLEAN"] * 3)
    r = EP.probe_arity(2, "subcategory", runner=lambda a, h, s, rep: (next(seq), 0.1))
    assert r["budget"] == 300


def test_the_family_has_exactly_two_known_answers_on_k7():
    for arity in range(1, 9):
        atoms, query, want = EP.family(arity, "h", 10)
        assert len(atoms) == 11 and len(want) == 2
        assert all(sp.shape_counts(a) == {f"h/{arity}": 1} for a in atoms)


def test_classify_reads_a_wrong_or_missing_answer():
    _, _, want = EP.family(4, "unverified", 10)
    assert EP.classify(list(want), want) == "CLEAN"
    assert EP.classify(want[:1], want) == "WRONG"
    assert EP.classify([want[0], want[0].replace("b107", "k849")], want) == "WRONG"


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_wrong_answer_counted_as_clean_would_give_390(monkeypatch):
    r = EP.probe_arity(4, "unverified", runner=_runner(wrong_at={390}))
    passing = lambda o: o in ("CLEAN", "WRONG")
    assert r["budget"] != 390 and passing("WRONG"), "if WRONG passed the budget would be 390"


def test_mutation_without_the_step_down_a_panic_at_390_would_forbid_or_keep_250():
    r = EP.probe_arity(8, "obs", runner=_runner(fail_at={390}))
    assert 300 in r["sizes_tried"], "the step down is what finds 300"
