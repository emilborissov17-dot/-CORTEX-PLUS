# -*- coding: utf-8 -*-
"""test/test_maintenance.py — maintenance is rotation, not priority (C-NEED-1 Part 1).
The searcher and the per-source worker are injected; state and log are
under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import maintenance as mt  # noqa: E402

TREE_SUBS = [{"level": "subcategory", "id": f"A1.{i}", "domain": "A", "category": "A1", "name_en": f"Thing {i}",
              "subgoal": "X", "wanted_keys": ["alpha_pct", "beta_count"]} for i in range(1, 4)]
SOURCES = [{"id": "s1", "url": "https://s1.org"}, {"id": "s2", "url": "https://s2.org"}]
PAGE = "<p>Water stress rose in the basin.</p><p>Wells ran dry.</p>"


@pytest.fixture
def p(tmp_path, monkeypatch):
    from core import taxonomy as tx
    monkeypatch.setattr(tx, "world_subcategories", lambda tree=None: TREE_SUBS)
    return {"state": tmp_path / "state.json", "log": tmp_path / "obs.jsonl", "store": tmp_path / "s.jsonl",
            "seen": tmp_path / "seen.json", "stale": tmp_path / "stale.json"}


def _run(p, n, search=None, worker=None):
    return mt.run(n=n, search=search,
                  worker_run=worker or (lambda s: {"cards": [{}]}), state_path=p["state"], log_path=p["log"],
                  sources=SOURCES, stale_path=p["stale"])


def _log(p):
    return [json.loads(l) for l in p["log"].read_text(encoding="utf-8").splitlines()]


def test_rotation_visits_every_cell_before_repeating(p, monkeypatch):
    clock = iter(f"2026-10-01T00:00:{i:02d}Z" for i in range(60))
    monkeypatch.setattr(mt, "_now", lambda: next(clock))
    seen = []
    for _ in range(3):
        seen += [r["cell"] for r in _run(p, 2)["rows"]]
    first5 = seen[:5]
    assert sorted(first5) == sorted(["sub:A1.1", "sub:A1.2", "sub:A1.3", "src:s1", "src:s2"])
    assert seen[5] == seen[0], "the rotation did not wrap around to the oldest-worked cell"


def test_mutation_ordering_by_anything_but_age_repeats_a_cell_early(p, monkeypatch):
    clock = iter(f"2026-10-01T00:00:{i:02d}Z" for i in range(60))
    monkeypatch.setattr(mt, "_now", lambda: next(clock))
    monkeypatch.setattr(mt, "queue", lambda cells, state, due=None: sorted(cells, key=lambda c: c["cell"]))
    seen = []
    for _ in range(3):
        seen += [r["cell"] for r in _run(p, 2)["rows"]]
    assert len(set(seen[:5])) < 5


def test_queries_rotate_keys_and_are_not_repeated_until_the_rotation_completes():
    sub, st = TREE_SUBS[0], {}
    qs = [mt.query_for(sub, st) for _ in range(2)]
    for q in qs:
        st.setdefault("tried", []).append(q)
    assert qs == ["Thing 1 alpha pct", "Thing 1 beta count"]
    assert mt.query_for(sub, st) == "Thing 1 alpha pct" and st["rotations"] == 1


def test_mutation_without_the_tried_check_a_query_repeats_inside_a_rotation():
    sub, st = TREE_SUBS[0], {"tried": ["Thing 1 alpha pct"], "key_idx": 0}
    assert mt.query_for(sub, st) == "Thing 1 beta count"
    st2 = {"tried": [], "key_idx": 0}                     # the memory removed
    assert mt.query_for(sub, st2) == "Thing 1 alpha pct"


def test_without_a_searcher_a_subcategory_cell_says_so(p):
    _run(p, 5)
    row = [r for r in _log(p) if r["cell"] == "sub:A1.1"][0]
    assert row["verdict"] == "NO_SEARCHER" and row["queries"] == ["Thing 1 alpha pct"]
    assert "Python finder was removed" in row["why"]


def test_mutation_a_stand_in_searcher_would_hide_the_absence(p):
    _run(p, 5, search=lambda cell, q: {"pages": 0})
    row = [r for r in _log(p) if r["cell"] == "sub:A1.1"][0]
    assert row["verdict"] == "NOTHING_FOUND", "with any searcher the cell stops saying NO_SEARCHER"


def test_a_searcher_that_gains_text_is_changed_and_one_that_gains_none_is_unchanged(p, monkeypatch):
    results = iter([{"pages": 1, "statements_added": 4}, {"pages": 1, "statements_added": 0}])
    clock = iter(f"2026-10-0{d}T00:00:00Z" for d in range(1, 10))
    monkeypatch.setattr(mt, "_now", lambda: next(clock))
    search = lambda cell, q: next(results) if cell["cell"] == "sub:A1.1" else {"pages": 0}
    for _ in range(8):                                    # A1.1 is 3rd of 5 cells: back on pass 8
        _run(p, 1, search)
    rows = [r for r in _log(p) if r["cell"] == "sub:A1.1"]
    assert [r["verdict"] for r in rows] == ["CHANGED", "UNCHANGED"]


def test_an_unreachable_source_is_nothing_found(p):
    worker = lambda s: {"unreachable": [{"reason": "HTTP 503"}], "cards": []}
    r = _run(p, 5, worker=worker)
    src = [x for x in r["rows"] if x["cell"].startswith("src:")]
    assert src and all(x["verdict"] == "NOTHING_FOUND" and x["why"] == "HTTP 503" for x in src)


def test_source_hints_are_not_used_to_build_queries():
    import inspect
    src = inspect.getsource(mt)
    assert "source_hints_unverified" not in src.replace("source_hints_unverified are not used", "")
    assert "candidate_sources" not in src


def test_the_taxonomy_field_is_renamed_and_its_writer_stated():
    doc = json.loads((REPO / "config" / "taxonomy.json").read_text(encoding="utf-8"))
    raw = json.dumps(doc)
    assert '"candidate_sources"' not in raw
    assert "source_hints_unverified" in doc["_meta"] and "Claude" in doc["_meta"]["source_hints_unverified"]


def test_a_source_listed_twice_is_one_cell(p):
    cells = mt.cells(sources=SOURCES + [{"id": "s1", "url": "https://s1.org/again"}])
    ids = [c["cell"] for c in cells]
    assert len(ids) == len(set(ids))


def test_a_refused_source_says_so_and_is_not_fetched(p):
    worker = lambda s: {"cards": [], "refusals": [{"reason": "World Bank header, not an observation"}]}
    r = _run(p, 5, worker=worker)
    src = [x for x in r["rows"] if x["cell"].startswith("src:")]
    assert all(x["verdict"] == "LABEL_REFUSED" and "header" in x["why"] for x in src)



def test_a_stale_source_is_due_first(p, monkeypatch):
    clock = iter(f"2026-10-01T00:00:{i:02d}Z" for i in range(60))
    monkeypatch.setattr(mt, "_now", lambda: next(clock))
    for _ in range(5):
        _run(p, 1)                                         # every cell worked once
    p["stale"].write_text(json.dumps({"sources": ["s2"]}), encoding="utf-8")
    assert _run(p, 1)["rows"][0]["cell"] == "src:s2"


def test_mutation_without_the_stale_hand_off_the_oldest_comes_first(p, monkeypatch):
    clock = iter(f"2026-10-01T00:00:{i:02d}Z" for i in range(60))
    monkeypatch.setattr(mt, "_now", lambda: next(clock))
    for _ in range(5):
        _run(p, 1)
    p["stale"].write_text(json.dumps({"sources": ["s2"]}), encoding="utf-8")
    real = mt.queue
    monkeypatch.setattr(mt, "queue", lambda cells, state, due=None: real(cells, state, set()))
    assert _run(p, 1)["rows"][0]["cell"] == "src:s1"
