"""Five orthogonal scalars in the learning trace — confounding is not a feature.

core/cycle_vector.py wrote flow_score into the vector: a completeness ratio
MULTIPLIED BY a speed. A lexicon fitted on that trace could not separate "did
less work" from "took longer", because the two arrive as one number and no
amount of clustering can pull them apart afterwards. That is not a limitation of
the clustering; it is information destroyed before it was ever stored.

The seven rows written before the change are NOT rewritten. A learning trace
that can be revised to match today's understanding is not evidence of anything.
A schema-change marker row says where the boundary is.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

STORE = REPO / "memory" / "state_vectors.jsonl"


def _rows():
    return [json.loads(l) for l in STORE.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def test_the_vector_carries_five_independent_scalars():
    from core.cycle_vector import cycle_metrics
    m = cycle_metrics(cycle_id="probe")
    for k in ("integrity_ratio", "degraded_ratio", "failed_ratio",
              "cloud_success_ratio", "pace_median_s"):
        assert k in m, f"the vector no longer carries {k}"


def test_no_composite_enters_the_vector():
    from core.cycle_vector import cycle_metrics
    from cockpit import vector as v
    m = cycle_metrics(cycle_id="probe")
    for banned in ("flow_score", "fs", "score", "band"):
        assert banned not in m, (
            f"cycle_metrics still emits {banned!r} — a product of two facts "
            f"cannot be un-multiplied by whatever reads it later")
        assert banned not in v.CYCLE_FIELDS


def test_the_speed_is_its_own_dimension_not_folded_into_a_quality():
    from cockpit import vector as v
    assert "pace_median_s" in v.CYCLE_FIELDS
    assert "integrity_ratio" in v.CYCLE_FIELDS, (
        "the two must both be present AND separate; that is the whole change")


def test_passing_a_flow_score_is_refused_not_silently_dropped():
    """An old caller must fail loudly rather than have its number vanish."""
    from core.cycle_vector import cycle_metrics
    with pytest.raises(ValueError) as e:
        cycle_metrics(cycle_id="probe", flow_score=2.5272)
    assert "composite" in str(e.value) or "multiplied" in str(e.value)


# ── the boundary in the trace ───────────────────────────────────────────────

def test_the_schema_change_is_marked_and_the_old_rows_are_intact():
    rows = _rows()
    markers = [r for r in rows if r.get("schema_change")]
    assert len(markers) == 1, (
        f"expected exactly one schema-change marker, found {len(markers)}")
    m = markers[0]
    assert "flow_score" in m["from"]
    assert "integrity_ratio" in m["to"] and "pace_median_s" in m["to"]
    assert m["commit"] and m["date"] == "2026-08-27"
    assert m["rows_before"] == 7

    before = rows[:m["rows_before"]]
    assert len(before) == 7
    for r in before:
        assert "cycle" in r, "an old row lost its cycle block"
        assert "flow_score" in (r["cycle"] or {}), (
            "an old row was REWRITTEN to the new schema — the trace must not "
            "be revised to match today's understanding")


def test_the_marker_says_why_not_just_what():
    m = [r for r in _rows() if r.get("schema_change")][0]
    assert len(m.get("why", "")) > 120, (
        "the marker records a schema change with no account of why; a future "
        "reader hitting the boundary would have only a diff")
    assert "MULTIPLIED" in m["why"] or "multiplied" in m["why"]


def test_a_reader_can_tell_which_side_of_the_boundary_a_row_is_on():
    """The point of the marker: rows either side are not comparable."""
    rows = _rows()
    idx = next(i for i, r in enumerate(rows) if r.get("schema_change"))
    old_side = [r for r in rows[:idx] if "cycle" in r]
    assert old_side, "no rows before the marker"
    assert all("flow_score" in (r["cycle"] or {}) for r in old_side)
    assert all("integrity_ratio" not in (r["cycle"] or {}) for r in old_side), (
        "a row before the marker already carries the new field, so the marker "
        "does not mark anything")
