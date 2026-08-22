#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_embed_index.py — TOP-K THAT IS EXACT, AND A DATABASE THAT STAYS SHUT.

Vectors are L2-normalised at build time, so cosine IS the dot product and the
whole search is one matrix multiply. Most of what is held below is the arithmetic
being right at the edges — a zero vector, a wrong dimension, k larger than the
corpus — because those are the inputs that turn a nearest-neighbour search into
a silently wrong one rather than an erroring one.

chromadb IS INSTALLED IN THIS VENV. That is exactly why "no chromadb at runtime"
has to be a test and not a comment: it would import perfectly if anyone reached
for it.

    venv\\Scripts\\python.exe -m pytest test/test_embed_index.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import embed_index as ei  # noqa: E402


@pytest.fixture
def built(tmp_path):
    """Four unit-ish vectors with a known nearest-neighbour order."""
    cache = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.9, 0.1, 0.0],
        "c": [0.0, 1.0, 0.0],
        "d": [0.0, 0.0, 1.0],
    }
    ei.build(cache=cache, out_dir=tmp_path)
    return ei.Index(tmp_path)


# ---------------------------------------------------------------------------
# No database
# ---------------------------------------------------------------------------

def test_chromadb_is_installed_which_is_why_this_test_exists():
    import importlib.util
    assert importlib.util.find_spec("chromadb") is not None, (
        "chromadb is gone from the venv; this guard is now trivially true and "
        "the test below is worth less than it was")


def test_importing_and_searching_loads_no_chromadb(tmp_path):
    cache = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    (tmp_path / "c.json").write_text(json.dumps(cache), encoding="utf-8")
    code = (
        "import sys, json; sys.path.insert(0, r'{repo}');"
        "from core import embed_index as ei;"
        "ei.build(cache_path=r'{cache}', out_dir=r'{out}');"
        "ei.Index(r'{out}').search([1.0, 0.0], k=1);"
        "print([m for m in sys.modules if 'chroma' in m.lower()])"
    ).format(repo=REPO, cache=tmp_path / "c.json", out=tmp_path / "idx")
    out = subprocess.run([str(REPO / "venv" / "Scripts" / "python.exe"), "-c", code],
                         cwd=str(REPO), capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]", (
        f"a search pulled in {out.stdout.strip()}; the point of this module is "
        f"that no database process has to be alive")


def test_the_module_never_imports_chromadb_anywhere():
    """AST, not a substring scan: the docstring and the selftest's availability
    line both mention the name legitimately. What must not exist is an import."""
    import ast
    tree = ast.parse((REPO / "core" / "embed_index.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "chromadb" not in imported, (
        "embed_index imports chromadb somewhere; the point of this module is that "
        "no database process has to be alive")


def test_the_runtime_path_does_not_mention_chromadb_at_all():
    """Everything above _selftest is the path a caller actually executes."""
    src = (REPO / "core" / "embed_index.py").read_text(encoding="utf-8")
    runtime = src.split('"""', 2)[-1].split("def _selftest")[0]
    assert "chromadb" not in runtime


# ---------------------------------------------------------------------------
# Top-k sanity
# ---------------------------------------------------------------------------

def test_a_vector_is_its_own_nearest_neighbour(built):
    hits = built.search([1.0, 0.0, 0.0], k=1)
    assert hits[0]["key"] == "a"
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-5)


def test_neighbours_come_back_in_descending_similarity(built):
    hits = built.search([1.0, 0.0, 0.0], k=4)
    assert [h["key"] for h in hits][:2] == ["a", "b"]
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_an_orthogonal_query_scores_about_zero(built):
    hits = {h["key"]: h["score"] for h in built.search([0.0, 0.0, 1.0], k=4)}
    assert hits["d"] == pytest.approx(1.0, abs=1e-5)
    assert hits["a"] == pytest.approx(0.0, abs=1e-5)


def test_k_larger_than_the_corpus_returns_everything_once(built):
    hits = built.search([1.0, 0.0, 0.0], k=99)
    assert len(hits) == 4
    assert len({h["key"] for h in hits}) == 4


def test_k_of_zero_returns_nothing(built):
    assert built.search([1.0, 0.0, 0.0], k=0) == []


def test_a_query_of_the_wrong_dimension_returns_nothing(built):
    assert built.search([1.0, 0.0], k=2) == [], (
        "a wrong-dimension query must not be broadcast into an answer")


def test_a_zero_query_returns_nothing(built):
    assert built.search([0.0, 0.0, 0.0], k=2) == [], (
        "a zero vector has no direction, so it has no nearest anything")


def test_an_unbuilt_index_answers_nothing_rather_than_raising(tmp_path):
    idx = ei.Index(tmp_path / "never_built")
    assert idx.ready is False
    assert idx.search([1.0], k=1) == []


def test_an_empty_cache_builds_an_empty_index(tmp_path):
    meta = ei.build(cache={}, out_dir=tmp_path)
    assert meta["count"] == 0
    assert ei.Index(tmp_path).ready is False


def test_the_module_level_search_helper_works(built, tmp_path):
    hits = ei.search([1.0, 0.0, 0.0], k=1, out_dir=tmp_path)
    assert hits[0]["key"] == "a"


def test_a_row_can_be_fetched_back_by_key(built):
    v = built.vector_for("a")
    assert v is not None and v.shape == (3,)
    assert built.vector_for("nope") is None


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def test_rows_are_unit_length_after_build(built):
    norms = np.linalg.norm(np.asarray(built.vectors), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_magnitude_does_not_change_the_ranking(tmp_path):
    """Cosine is about direction. A vector scaled by 1000 is the same neighbour."""
    ei.build(cache={"small": [1.0, 0.0], "big": [1000.0, 0.0], "other": [0.0, 1.0]},
             out_dir=tmp_path)
    hits = ei.Index(tmp_path).search([2.0, 0.0], k=2)
    assert {h["key"] for h in hits} == {"small", "big"}
    assert hits[0]["score"] == pytest.approx(hits[1]["score"], abs=1e-5)


def test_a_zero_vector_does_not_become_nan(tmp_path):
    """NaN propagates through argpartition and gives a silently wrong top-k."""
    ei.build(cache={"zero": [0.0, 0.0], "real": [1.0, 0.0]}, out_dir=tmp_path)
    idx = ei.Index(tmp_path)
    assert not np.isnan(np.asarray(idx.vectors)).any()
    hits = idx.search([1.0, 0.0], k=2)
    assert hits[0]["key"] == "real"


def test_normalise_leaves_a_zero_row_at_zero():
    out = ei.normalise(np.array([[0.0, 0.0], [3.0, 4.0]]))
    assert np.allclose(out[0], [0.0, 0.0])
    assert np.allclose(out[1], [0.6, 0.8])


# ---------------------------------------------------------------------------
# Build hygiene
# ---------------------------------------------------------------------------

def test_a_wrong_dimension_row_is_dropped_not_padded(tmp_path):
    meta = ei.build(cache={"a": [1.0, 0.0], "wrong": [1.0, 0.0, 0.0]},
                    out_dir=tmp_path)
    assert meta["count"] == 1
    assert meta["dropped_count"] == 1
    assert "dimension" in meta["dropped"][0]["why"], (
        "padding would put a vector from a different model into the same space "
        "and let it be returned as a neighbour")


def test_junk_rows_are_dropped_with_a_reason(tmp_path):
    meta = ei.build(cache={"a": [1.0, 0.0], "s": "not a vector",
                           "e": [], "n": None}, out_dir=tmp_path)
    assert meta["count"] == 1
    assert meta["dropped_count"] == 3
    assert all(d["why"] for d in meta["dropped"])


def test_the_meta_records_dimension_count_and_backend(tmp_path):
    meta = ei.build(cache={"a": [1.0, 0.0, 0.0]}, out_dir=tmp_path)
    assert meta["dim"] == 3 and meta["count"] == 1
    assert meta["normalised"] is True
    assert meta["backend_available"] in ("numpy", "hnswlib")


def test_the_index_is_memory_mapped_not_read(built):
    assert isinstance(built.vectors, np.memmap), (
        "np.load without mmap_mode reads the whole file into a process that "
        "already died once at 99% RAM")


def test_rebuilding_replaces_rather_than_appends(tmp_path):
    ei.build(cache={"a": [1.0, 0.0], "b": [0.0, 1.0]}, out_dir=tmp_path)
    ei.build(cache={"c": [1.0, 0.0]}, out_dir=tmp_path)
    idx = ei.Index(tmp_path)
    assert idx.count == 1 and idx.keys == ["c"]


# ---------------------------------------------------------------------------
# The real cache
# ---------------------------------------------------------------------------

def test_the_real_embeddings_cache_builds_and_searches(tmp_path):
    if not ei.CACHE.exists():
        pytest.skip("no embeddings cache on this machine")
    meta = ei.build(out_dir=tmp_path)
    idx = ei.Index(tmp_path)
    if meta["count"] == 0:
        pytest.skip("the cache is empty")
    probe = np.asarray(idx.vectors[0])
    hits = idx.search(probe, k=min(3, idx.count))
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-3), (
        "a real vector is not its own nearest neighbour")
    assert idx.dim > 0


def test_the_corpus_is_far_below_the_exhaustive_ceiling():
    cache = ei.load_cache()
    if not cache:
        pytest.skip("no cache")
    assert len(cache) < ei.EXHAUSTIVE_CEILING, (
        f"{len(cache)} vectors is at or past the {ei.EXHAUSTIVE_CEILING} ceiling "
        f"where an approximate index starts earning its build cost — the numpy "
        f"backend choice should be revisited")


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------

def test_the_backend_is_reported_honestly():
    assert ei.backend() in ("numpy", "hnswlib")
    import importlib.util
    expected = "hnswlib" if importlib.util.find_spec("hnswlib") else "numpy"
    assert ei.backend() == expected


def test_forcing_the_numpy_path_gives_the_same_answer(built):
    a = built.search([1.0, 0.0, 0.0], k=3, use_hnsw=False)
    b = built.search([1.0, 0.0, 0.0], k=3)
    assert [h["key"] for h in a] == [h["key"] for h in b]


def test_the_selftest_says_NOT_WIRED(capsys):
    ei._selftest()
    assert "NOT WIRED" in capsys.readouterr().out
