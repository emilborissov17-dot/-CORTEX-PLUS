# -*- coding: utf-8 -*-
"""test/test_engine_guard.py — the guard around the symbolic engine (C-GUARD-1, Kimi round 74 K1).

Decided: hyperon stays 0.2.10. Before the engine runs, atoms are counted per shape (head + arity)
in the exact program it receives; a shape at or over the sealed threshold refuses the run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import space as sp  # noqa: E402


def _obs(n, head="obs"):
    return "\n".join(f'({head} "a-{i}" "C1" "k{i}" "WLD" "2023" {i}.0 "n" "src")' for i in range(n)) + "\n"


def _paths(tmp_path, base, threshold=400):
    d = tmp_path / "space"
    d.mkdir(exist_ok=True)
    (d / "base.metta").write_text(base, encoding="utf-8")
    (tmp_path / "rules.metta").write_text("!(match &self (stale $a) (stale $a))\n", encoding="utf-8")
    cfg = tmp_path / "engine_guard.json"
    cfg.write_text(json.dumps({"threshold": threshold}), encoding="utf-8")
    return {"dir": d, "rules": tmp_path / "rules.metta", "proposed": tmp_path / "none.metta"}, cfg


def _derive(tmp_path, base, threshold=400, engine=None):
    paths, cfg = _paths(tmp_path, base, threshold)
    return sp.derive(paths, engine=engine or (lambda prog: []), guard_config=cfg)


# ── 2. the count per shape ──────────────────────────────────────────────────
def test_shape_is_head_and_arity_and_commands_are_not_atoms():
    prog = _obs(3) + '(obs "x" 1)\n(subcategory "s" "c")\n; (obs "comment" 1)\n!(match &self (obs $a $b) $a)\n'
    assert sp.shape_counts(prog) == {"obs/8": 3, "obs/2": 1, "subcategory/2": 1}


def test_a_nested_expression_is_one_atom_of_its_outer_shape():
    assert sp.shape_counts('(proposed "id" "m" (says "a (b)" "c"))\n') == {"proposed/3": 1}


def test_399_is_allowed_and_the_largest_shapes_are_reported(tmp_path):
    r = _derive(tmp_path, _obs(399))
    assert r["shapes"][0] == ["obs/8", 399]
    log = [json.loads(l) for l in (tmp_path / "space" / "guard_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[-1]["shapes"][0] == ["obs/8", 399]


@pytest.mark.parametrize("n", [400, 401])
def test_a_shape_at_or_over_the_threshold_refuses_the_run(tmp_path, n):
    ran = []
    with pytest.raises(sp.SpaceEngineFailed, match=f"obs/8 has {n} atoms") as exc:
        _derive(tmp_path, _obs(n), engine=lambda prog: ran.append(1) or [])
    assert exc.value.cause == "ENGINE_THRESHOLD"
    assert ran == [], "the engine saw a program the guard refused"
    assert not (tmp_path / "space" / "derived.metta").exists()


def test_a_shape_of_another_arity_counts_apart(tmp_path):
    base = _obs(300) + "\n".join(f'(obs "b-{i}" "C1" "k" "WLD" "2023" 1.0 "n" "src" "extra")'
                                  for i in range(300)) + "\n"
    r = _derive(tmp_path, base)
    assert dict(map(tuple, r["shapes"])) == {"obs/8": 300, "obs/9": 300}


def test_the_threshold_comes_from_the_config_and_a_missing_key_raises(tmp_path):
    cfg = tmp_path / "g.json"
    cfg.write_text("{}", encoding="utf-8")
    with pytest.raises(KeyError):
        sp.guard_threshold(cfg)
    real = json.loads((REPO / "config" / "engine_guard.json").read_text(encoding="utf-8"))
    assert real["threshold"] == 400 and "Kimi round 74 K1" in real["_threshold_why"]


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_threshold_off_by_one_would_let_400_through():
    assert sp.shapes_over({"obs/8": 400}, 400) == ["obs/8"]
    off_by_one = [s for s, c in {"obs/8": 400}.items() if c > 400]
    assert off_by_one == [], "the strict comparison passes 400 — the guard must not be written that way"
