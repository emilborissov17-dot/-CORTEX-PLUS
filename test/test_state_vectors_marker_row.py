# -*- coding: utf-8 -*-
"""test/test_state_vectors_marker_row.py — the phase voice died on a schema marker (11 Sep 2026).

memory/state_vectors.jsonl holds one row per cycle end (25-dim body vector) AND,
since 27 Aug, one {"schema_change": true} marker row with no "vector". The night
the lexicon went warm, cockpit.vector.usable_matrix did r["vector"] on the marker
and every phase of every cycle printed
    [PHASE] X: no expression line (producer RAISED: KeyError: 'vector')
This pins: markers are skipped, vectors are kept, the matrix builds, and the
mutation (a loader that keeps everything) reproduces the crash.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from cockpit import vector as vec  # noqa: E402

FIELDS = [f"f{i}" for i in range(25)]


def _store(tmp_path, n=22, with_marker=True):
    p = tmp_path / "state_vectors.jsonl"
    rows = []
    for i in range(n):
        rows.append({"ts": f"2026-08-{(i % 28) + 1:02d}T00:00:00+00:00", "version": "v1", "fields": FIELDS,
                     "vector": [float(i + j) for j in range(25)], "dims": 25, "measured": 25, "cycle": {}})
        if with_marker and i == 6:
            rows.append({"ts": "2026-08-27T00:00:00+00:00", "schema_change": True, "commit": "9edc238",
                         "why": "flow_score -> integrity_ratio"})
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_marker_rows_are_not_vectors(tmp_path):
    p = _store(tmp_path)
    rows = vec.load(p)
    assert len(rows) == 22 and all(isinstance(r["vector"], list) for r in rows)


def test_the_matrix_builds_over_a_store_with_a_marker(tmp_path):
    p = _store(tmp_path)
    matrix, keep = vec.usable_matrix(vec.load(p))
    assert len(matrix) == 22 and len(keep) == 25


def test_usable_matrix_tolerates_a_marker_handed_to_it_directly():
    rows = [{"vector": [1.0] * 25}, {"schema_change": True}, {"vector": [2.0] * 25}]
    matrix, keep = vec.usable_matrix(rows)
    assert len(matrix) == 2


def test_mutation_a_loader_that_keeps_markers_reproduces_the_crash(tmp_path, monkeypatch):
    p = _store(tmp_path)
    raw = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert any("vector" not in r for r in raw)
    # the shipped behaviour: rows straight into r["vector"]
    with pytest.raises(KeyError):
        [len(r["vector"]) for r in raw]


def test_the_live_store_loads_and_builds():
    live = REPO / "memory" / "state_vectors.jsonl"
    if not live.exists():
        pytest.skip("no live store here")
    rows = vec.load(live)
    assert rows and all(isinstance(r["vector"], list) for r in rows)
    matrix, keep = vec.usable_matrix(rows)
    assert len(matrix) == len(rows) and keep
