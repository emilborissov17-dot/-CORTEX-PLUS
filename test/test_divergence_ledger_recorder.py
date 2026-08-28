"""The grounding ledger is a PURE RECORDER — four defects, each named.

PROVENANCE. The requirement is RECOVERED; the implementation is NEW WORK dated
2026-08-28. A `git reset --hard` over uncommitted work destroyed the version that
carried these four fixes. The source is unrecoverable — no decompiler supports
CPython 3.14 bytecode — but experiments/grounding/__pycache__/divergence_ledger
.cpython-314.pyc, compiled 2026-08-17 14:16:18, kept the whole module docstring
as a single string constant, and that docstring IS the specification. 76 string
constants and 9 function names came back with it. Nothing below was reassembled
from bytecode; the tests were written from the recovered docstring, then code was
written to satisfy them.

THE FOUR DEFECTS, quoted from the recovered docstring:

 1. "DIVERGENCE_ALERT = 0.5 IS GONE. A hardcoded 0.5 is a verdict smuggled in as
    a constant." Replaced by `divergence_z` — how far today's divergence sits
    from this axis's own rolling mean, in this axis's own sigmas. The sigma that
    turns z into a verdict lives in config/source_trust_rules.json, "so no second
    threshold exists anywhere in the system".
 2. "THE RECORD NOW CARRIES def_hash." Rows are compared only against rows with
    the SAME definition fingerprint. "The fingerprint is deliberately
    over-sensitive — even a comment flips it. That errs in the safe direction: it
    may say 'not comparable' too often, never 'comparable' wrongly."
 3. "WITH TOO LITTLE HISTORY IT STILL WRITES." Below grounding_min_history the
    row carries insufficient_history: true and no z, but keeps the raw number.
    "Silence would be data loss, and data loss is not caution."
 4. "THE TAMPER CHECK NOW CHECKS THE CONTENT." The old verify walked prev_hash
    only, so any record's body could be rewritten with its stored hash left
    untouched and the chain still reported intact. It guarded the ORDER and not
    the CONTENT. Kimi, quoted: "иначе е театър."

Plus two found while reading rather than reported:
  * composers' `daily` is a slot DICT, not a scalar, so "axes with live daily"
    counted a dict that is truthy whenever a slot exists at all.
  * `divergence_blocked` — "no daily source at all" and "subtraction refused as a
    category error" both recorded divergence=None and were indistinguishable,
    "a blind spot masquerading as a missing measurement".
"""
import hashlib
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from experiments.grounding import divergence_ledger as dl   # noqa: E402


# ── 1. the smuggled verdict ────────────────────────────────────────────────

def test_no_hardcoded_divergence_threshold_survives():
    """A recorder holds no threshold. The sigma lives in the human rules file."""
    import ast
    src = (REPO / "experiments" / "grounding" / "divergence_ledger.py").read_text(
        encoding="utf-8")
    # BY AST, not by substring: the docstring NAMES the constant in order to
    # record that it is gone, and a substring search cannot tell an explanation
    # from a definition. Same lesson as the REAL_DATA ordering check.
    tree = ast.parse(src)
    assigned = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert "DIVERGENCE_ALERT" not in assigned, (
        "a hardcoded alert threshold is a verdict smuggled in as a constant")
    assert not hasattr(dl, "DIVERGENCE_ALERT")


def test_the_row_carries_divergence_z_against_its_own_history():
    rows = [{"divergence": 1.0}, {"divergence": 1.2}, {"divergence": 0.8},
            {"divergence": 1.1}, {"divergence": 0.9}]
    z = dl._z(3.0, [r["divergence"] for r in rows])
    assert z is not None and z > 2, "a clear outlier must show a large z"
    assert dl._z(1.0, [1.0, 1.0, 1.0]) is None, (
        "zero sigma cannot produce a z — that would be division by nothing")


def test_the_recorder_passes_no_verdict():
    """It records; source_trust judges. One truth, one judge."""
    src = (REPO / "experiments" / "grounding" / "divergence_ledger.py").read_text(
        encoding="utf-8")
    assert "recorder only: no thresholds, no alerts, no verdicts" in src


# ── 2. def_hash ────────────────────────────────────────────────────────────

def test_def_hash_is_present_and_over_sensitive():
    a = dl._def_hash("x = 1")
    b = dl._def_hash("x = 1  # a comment")
    assert a and b and a != b, (
        "the fingerprint must flip on a comment — over-sensitive on purpose, so "
        "it errs toward 'not comparable' and never toward 'comparable' wrongly")


def test_history_is_taken_only_from_rows_with_the_same_def_hash():
    recs = [{"def_hash": "AAA", "axes": {"X": {"divergence": 1.0}}},
            {"def_hash": "BBB", "axes": {"X": {"divergence": 99.0}}},
            {"def_hash": "AAA", "axes": {"X": {"divergence": 1.2}}}]
    hist = dl._past(recs, "AAA")
    assert hist["X"] == [1.0, 1.2], (
        "a row produced by different definitions is not comparable to this one")


# ── 3. too little history still writes ─────────────────────────────────────

def test_below_min_history_the_row_is_written_with_a_flag_and_no_z():
    row = dl._score({"divergence": 2.0}, history=[1.0], min_history=5)
    assert row["insufficient_history"] is True
    assert row.get("divergence_z") is None
    assert row["divergence"] == 2.0, (
        "the raw number is kept — silence would be data loss, and data loss is "
        "not caution")


def test_with_enough_history_the_z_appears_and_the_flag_does_not():
    row = dl._score({"divergence": 2.0}, history=[1.0, 1.1, 0.9, 1.0, 1.05],
                    min_history=5)
    assert row.get("insufficient_history") is not True
    assert row["divergence_z"] is not None


# ── 4. the tamper check must check content ─────────────────────────────────

def test_verify_catches_a_rewritten_body_not_only_a_broken_order(tmp_path):
    led = tmp_path / "grounding_ledger.jsonl"
    body = {"ts": "2026-08-28T00:00:00+00:00", "axes": {}, "def_hash": "AAA",
            "prev_hash": "0" * 64}
    h = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                       .encode("utf-8")).hexdigest()
    led.write_text(json.dumps({**body, "hash": h}) + "\n", encoding="utf-8")
    assert dl.verify(led)["intact"] is True

    # Rewrite the BODY and leave the stored hash untouched — the exact attack the
    # old chain reported as "intact: True".
    tampered = {**body, "axes": {"X": {"divergence": 999}}, "hash": h}
    led.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    out = dl.verify(led)
    assert out["intact"] is False, "a chain that guards order and not content is theatre"
    assert "content" in out["why"].lower()


def test_verify_still_catches_a_broken_order(tmp_path):
    led = tmp_path / "grounding_ledger.jsonl"
    rows = []
    prev = "0" * 64
    for i in range(2):
        body = {"ts": f"2026-08-2{i}T00:00:00+00:00", "axes": {}, "def_hash": "A",
                "prev_hash": prev}
        h = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                           .encode("utf-8")).hexdigest()
        rows.append({**body, "hash": h})
        prev = h
    # Break the ORDER and REHASH, so content verifies and only the order is
    # wrong. Without the rehash the content check fires first and this would not
    # be testing what it claims — prev_hash is part of the hashed body, so any
    # naive reorder is ALSO a content mismatch. The attack worth catching is the
    # one where somebody reorders and recomputes.
    rows[1]["prev_hash"] = "f" * 64
    body = {k: v for k, v in rows[1].items() if k != "hash"}
    rows[1]["hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    led.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    out = dl.verify(led)
    assert out["intact"] is False
    assert "order" in out["why"].lower()


# ── the two found while reading ────────────────────────────────────────────

def test_daily_is_read_out_of_the_slot_dict_not_used_as_a_scalar():
    """composers' `daily` is {id, value, unit, ...}. A dict is truthy whenever a
    slot exists at all, so counting it counted slots, not live values."""
    assert dl._slot_value({"id": "x", "value": 42.0}) == 42.0
    assert dl._slot_value({"id": "x", "value": None}) is None
    assert dl._slot_value(None) is None
    assert dl._slot_value({}) is None, "an empty slot is not a live daily value"


def test_no_daily_source_is_distinguishable_from_a_refused_subtraction():
    """The two must not look alike. THE CONTRACT IS THE ONE 53 RECORDS ALREADY
    USE, read off memory/grounding_ledger.jsonl rather than chosen here:
    divergence_blocked is a SENTENCE and is null when nothing blocked, while
    "no daily source at all" is legible from daily_source being None."""
    no_source = dl._score({"divergence": None, "daily": None, "daily_source": None},
                          history=[], min_history=1)
    assert no_source["divergence_blocked"] is None
    assert no_source["daily_source"] is None, (
        "absence of a source is carried by daily_source, not by a blocked reason")

    mismatch = dl._score({"divergence": None, "daily": 4330.0,
                          "anchor_unit": "pct_population",
                          "daily_unit": "cubic_feet_per_second"},
                         history=[], min_history=1)
    assert mismatch["divergence_blocked"], "a category error must be named"
    assert "category error" in mismatch["divergence_blocked"]
    assert "pct_population" in mismatch["divergence_blocked"]
    assert "cubic_feet_per_second" in mismatch["divergence_blocked"], (
        "the sentence must name BOTH units — a blind spot masquerading as a "
        "missing measurement is the defect")


def test_an_undeclared_daily_unit_is_still_a_category_error():
    """Live records carry 'vs daily unit undeclared'. A missing unit is not a
    matching unit."""
    row = dl._score({"divergence": None, "daily": 32.0,
                     "anchor_unit": "millions_persons", "daily_unit": None},
                    history=[], min_history=1)
    assert "undeclared" in (row["divergence_blocked"] or "")


def test_the_row_uses_the_field_names_already_on_disk():
    """n_history, not history_n. insufficient_history always present as a bool.
    A second convention in one file is how a ledger stops being comparable to
    itself."""
    row = dl._score({"divergence": 2.0}, history=[1.0], min_history=5)
    assert "n_history" in row and "history_n" not in row
    assert isinstance(row["insufficient_history"], bool)
    assert "divergence_blocked" in row, "present as null, not absent"


def test_the_record_carries_the_four_header_keys_the_live_ledger_has():
    src = (REPO / "experiments" / "grounding" / "divergence_ledger.py").read_text(
        encoding="utf-8")
    for key in ('"schema"', '"judged_by"', '"def_files"', '"min_history"'):
        assert key in src, f"the record header must carry {key}"
    assert dl.SCHEMA == "grounding/2"
    assert dl.JUDGED_BY == "core.source_trust.grounding_verdict + core.notary"


def test_def_files_names_what_the_fingerprint_covers():
    files = dl._def_files()
    assert set(files) == set(dl.DEF_FILES)
    assert all(isinstance(v, str) and v for v in files.values()), (
        "a hash nobody can attribute is a number, not evidence")


def test_the_live_ledger_verifies_content_and_order():
    """53 records written before this rewrite must still verify — otherwise the
    hashing convention changed and the chain is broken by the fix itself."""
    out = dl.verify()
    assert out["intact"] is True, out["why"]
    assert out["records"] > 0
