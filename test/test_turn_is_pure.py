# -*- coding: utf-8 -*-
"""test/test_turn_is_pure.py — the baton module reaches nothing (C-FIX-1, 2 Oct 2026).

Every network reader checks the baton (no fetch in the brain's turn) through
core.turn. When core.turn carried its own live defaults (supervisor's alarm and
witness, model_window, micro_cycle, homeostasis), every reader statically reached
core.llm_door through it, and core.notary reached the model door past llm_parse
(test/test_llm_text.py). THE RULE: core.turn holds the baton and nothing live; the
live checks are in core/turn_live.py and are passed in by scripts/turns_loop.py.
A REFUSAL: hand_over / blocked called without them raise TurnNotWired by name -
never a silent default.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import turn  # noqa: E402

LIVE = ("supervisor", "core.model_window", "core.homeostasis", "scripts.micro_cycle", "core.turn_live")


def imports_of(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out |= {n.module} | {f"{n.module}.{a.name}" for a in n.names}
    return out


def test_core_turn_imports_nothing_live():
    assert not imports_of(REPO / "core" / "turn.py") & set(LIVE)


def test_mutation_an_import_of_supervisor_is_seen(tmp_path):
    f = tmp_path / "turn.py"
    f.write_text((REPO / "core" / "turn.py").read_text(encoding="utf-8") + "\ndef _x():\n    import supervisor\n",
                 encoding="utf-8")
    assert "supervisor" in imports_of(f)


def test_hand_over_without_a_witness_refuses_by_name(tmp_path):
    with pytest.raises(turn.TurnNotWired):
        turn.hand_over("AGENTS", "s", "T1", path=tmp_path / "t.json", log_path=tmp_path / "l.jsonl",
                       alarm=lambda *a: "sent")
    with pytest.raises(turn.TurnNotWired):
        turn.hand_over("AGENTS", "s", "T1", path=tmp_path / "t.json", log_path=tmp_path / "l.jsonl",
                       witness=lambda c: None)


def test_blocked_without_its_checks_refuses_by_name(tmp_path):
    with pytest.raises(turn.TurnNotWired):
        turn.blocked(log_path=tmp_path / "l.jsonl")


def test_the_loop_passes_the_live_checks(tmp_path, monkeypatch):
    from core import turn_live
    from scripts import turns_loop as tl
    seen = {}

    def blocked(**k):
        seen["blocked"] = k
        return None

    def hand(*a, **k):
        seen["hand"] = k
        return {"handed": True}
    monkeypatch.setattr(turn, "blocked", blocked)
    monkeypatch.setattr(turn, "hand_over", hand)
    tl.loop(max_turns=1, run_turn=lambda h, c: 0, turn_path=tmp_path / "t.json", result_path=tmp_path / "r.json",
            stop_path=tmp_path / "stop", log_path=tmp_path / "l.jsonl")
    assert seen["blocked"]["cycle"] is turn_live.cycle and seen["blocked"]["body"] is turn_live.body
    assert seen["hand"]["witness"] is turn_live.witness and seen["hand"]["alarm"] is turn_live.alarm
