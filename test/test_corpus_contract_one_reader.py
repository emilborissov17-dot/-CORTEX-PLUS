# -*- coding: utf-8 -*-
"""
test/test_corpus_contract_one_reader.py — one key contract, and every consumer
of it reads it the same way.

THE DEFECT THIS EXISTS FOR, measured not supposed. training/corpus_from_merkle.py
declares CONTRACT: a frozen map from a decision record's key-set signature to
which field is the prompt and which is the target. Two modules read it.

  c8ab870  4 Sep 19:58:33  CONTRACT's values are 2-tuples
                           (_PROBLEM_SOLUTION = ("problem", "solution"))
  eb4b517  4 Sep 19:59:45  merkle_to_training delegates to it and unpacks the
                           2-tuple: `_prompt_key, target_key = entry`. CORRECT.
  3ac2f1f  4 Sep 20:12:22  record_kind is added; every value becomes a Mapping
                           object with __slots__ — NOT iterable.
                           corpus_from_merkle.py is updated to attribute access
                           in the same commit. merkle_to_training.py is not.

Thirteen minutes turned a correct caller into one that raised
`TypeError: cannot unpack non-iterable Mapping object` on every night from 4 Sep
to 10 Sep. The commit that broke it was titled "one contract, not two that
disagree" — the contract was unified and the READING of it was not.

WHAT A REFUSAL LOOKS LIKE HERE, so it is not confused with the bug: a signature
the contract does not know, or a Refuse entry, is SKIPPED and counted, and a
cycle with no mapped decision returns None rather than a pair with a blank
target. That refusal is correct behaviour and is asserted below, so a fix that
"works" by accepting everything fails too.

The forbidden fallback is the one that actually shipped: reading the contract in
a way that happens to match today's value type, so a change to the contract
breaks a caller silently at runtime instead of here.

These are BEHAVIOURAL tests. They call the real functions against real archived
cycles and never grep source or read docstrings, and they never write to the live
corpus — build_pair() is pure; append_latest_cycle() is the writer and is not
called.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import merkle_to_training as m2t                       # noqa: E402
from training.corpus_from_merkle import CONTRACT, Mapping, Refuse  # noqa: E402

ARCHIVE = REPO / "cortex_memory" / "archive"


def _cycles_with_all_three_files():
    if not ARCHIVE.exists():
        return []
    out = []
    for d in sorted(ARCHIVE.glob("cycle_*")):
        if all((d / f).exists() for f in ("signals.json", "decisions.json", "results.json")):
            out.append(d)
    return out


# ── the contract's shape is the thing that changed under the caller ──────────

def test_no_contract_entry_is_tuple_unpackable():
    """The 2-tuple era is over. If any entry were unpackable again, the old
    `prompt, target = entry` would start working and the two readers could drift
    apart once more without anything failing."""
    assert CONTRACT, "the contract is empty"
    for sig, entry in CONTRACT.items():
        assert isinstance(entry, (Mapping, Refuse)), \
            f"{sig[:2]}... maps to a bare {type(entry).__name__}"
        with pytest.raises(TypeError):
            _a, _b = entry            # noqa: F841 — unpacking must be impossible


def test_every_mapping_declares_all_three_fields():
    for sig, entry in CONTRACT.items():
        if isinstance(entry, Mapping):
            assert entry.prompt_key and entry.target_key and entry.kind, \
                f"{entry.kind or sig[:2]} has a blank declared field"


# ── the behaviour that was broken for six nights ─────────────────────────────

@pytest.mark.skipif(not _cycles_with_all_three_files(),
                    reason="no archived cycle with all three files in this checkout")
def test_build_pair_produces_a_non_empty_target_on_a_real_cycle():
    """The regression itself. Before the fix this raised TypeError on every
    archived cycle whose decisions matched the contract."""
    pairs = []
    for d in _cycles_with_all_three_files():
        pair = m2t.build_pair(d)      # pure: returns a pair, writes nothing
        if pair is not None:
            pairs.append((d.name, pair))
    assert pairs, "no archived cycle produced a pair — the corpus builder is inert"
    for name, pair in pairs:
        assert pair.get("output", "").strip(), f"{name} produced a blank target"
        assert pair.get("input", "").strip(), f"{name} produced a blank prompt"


@pytest.mark.skipif(not _cycles_with_all_three_files(),
                    reason="no archived cycle with all three files in this checkout")
def test_both_readers_choose_the_same_target_field():
    """One contract, not two that disagree — asserted on real records rather than
    on the commit message that claimed it. For every archived decision record,
    the field merkle_to_training's pair ends up carrying must be the field the
    contract declares, which is what corpus_from_merkle reads."""
    checked = 0
    for d in _cycles_with_all_three_files():
        dec = json.loads((d / "decisions.json").read_text(encoding="utf-8"))
        decisions = dec.get("decisions")
        if not isinstance(decisions, list):
            continue
        pair = m2t.build_pair(d)
        if pair is None:
            continue
        for rec in decisions:
            if not isinstance(rec, dict):
                continue
            entry = CONTRACT.get(tuple(sorted(rec.keys())))
            if not isinstance(entry, Mapping):
                continue                      # unknown or deliberately refused
            text = rec.get(entry.target_key)
            if isinstance(text, str) and text.strip():
                assert text.strip() in pair["output"], (
                    f"{d.name}: the contract declares '{entry.target_key}' as the "
                    f"target for {entry.kind}, but that text is not in the pair")
                checked += 1
    assert checked, "no record was actually compared — the test proved nothing"


# ── the refusals must survive the fix ────────────────────────────────────────

def test_an_unknown_signature_is_refused_not_guessed(tmp_path):
    """A key-set the contract does not know must produce NO pair, rather than a
    pair with a blank or guessed target. This is the failure the 4 Sep audit
    found: 46 of 46 records written with an empty target and reported as success."""
    d = tmp_path / "cycle_999999"
    d.mkdir()
    (d / "signals.json").write_text(json.dumps(
        {"cycle_id": "x", "timestamp": "2026-09-10T00:00:00+00:00",
         "count": 1, "signals": [{"axis": "WATER", "score": 50}]}), encoding="utf-8")
    (d / "decisions.json").write_text(json.dumps(
        {"decisions": [{"totally": "unknown", "key": "set"}]}), encoding="utf-8")
    (d / "results.json").write_text(json.dumps(
        {"goal_score": 50, "results": []}), encoding="utf-8")
    assert m2t.build_pair(d) is None, \
        "an unknown signature produced a pair — the refusal is gone"


def test_a_known_signature_with_a_blank_target_is_refused(tmp_path):
    """NEGATIVE CONTROL for the test above: the signature IS in the contract, so
    the refusal must come from the blank target, not from an unknown key-set."""
    sig = next(s for s, e in CONTRACT.items() if isinstance(e, Mapping))
    entry = CONTRACT[sig]
    rec = {k: "filler" for k in sig}
    rec[entry.target_key] = "   "                 # known shape, empty target
    d = tmp_path / "cycle_999998"
    d.mkdir()
    (d / "signals.json").write_text(json.dumps(
        {"cycle_id": "y", "timestamp": "2026-09-10T00:00:00+00:00",
         "count": 1, "signals": [{"axis": "WATER", "score": 50}]}), encoding="utf-8")
    (d / "decisions.json").write_text(json.dumps({"decisions": [rec]}), encoding="utf-8")
    (d / "results.json").write_text(json.dumps(
        {"goal_score": 50, "results": []}), encoding="utf-8")
    assert m2t.build_pair(d) is None, "a blank target was written as a pair"

    rec[entry.target_key] = "a real decision"     # same shape, real target
    (d / "decisions.json").write_text(json.dumps({"decisions": [rec]}), encoding="utf-8")
    pair = m2t.build_pair(d)
    assert pair is not None and "a real decision" in pair["output"], \
        "the same signature with a real target was refused — the guard is too wide"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
