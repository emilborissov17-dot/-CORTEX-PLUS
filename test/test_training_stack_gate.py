# -*- coding: utf-8 -*-
"""test/test_training_stack_gate.py — a red leaves the gate only by a named marker (C-GATE-1, 3 Oct 2026).

Decided: the tests of test/test_eval_harness.py that build the real BitsAndBytesConfig need
venv_train (bitsandbytes). They carry @pytest.mark.training_stack; the gate deselects that marker
and names it with its count in the summary; tools/run_training_stack_tests.ps1 runs them under
venv_train. A skip that hides a red is refused: the file has no importorskip.
"""
from __future__ import annotations

import ast
import configparser
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "test"))
import conftest  # noqa: E402

GATE = "not live_state and not training_stack"


def test_the_marker_is_registered():
    ini = configparser.ConfigParser(interpolation=None)
    ini.read(REPO / "pytest.ini", encoding="utf-8")
    assert any(l.strip().startswith("training_stack:") for l in ini["pytest"]["markers"].splitlines())


def test_both_gate_commands_deselect_it():
    assert f'"-m", "{GATE}"' in (REPO / "tools" / "suite_gate.py").read_text(encoding="utf-8")
    assert f'-m "{GATE}"' in (REPO / "tools" / "full_suite_detached.ps1").read_text(encoding="utf-8")


def _marked(tree) -> list[str]:
    out = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef):
            for d in n.decorator_list:
                if isinstance(d, ast.Attribute) and d.attr == "training_stack":
                    out.append(n.name)
    return out


def test_exactly_the_bitsandbytes_tests_carry_it():
    tree = ast.parse((REPO / "test" / "test_eval_harness.py").read_text(encoding="utf-8"))
    assert sorted(_marked(tree)) == sorted([
        "test_main_skips_blank_targets_before_the_model_is_touched",
        "test_exit_2_when_the_adapter_is_missing", "test_exit_0_only_when_an_UNSEEN_stratum_IMPROVED",
        "test_exit_1_when_the_adapter_did_nothing", "test_exit_1_when_the_adapter_made_it_WORSE",
        "test_exit_1_when_the_UNSEEN_bucket_is_too_small_to_grade",
        "test_improvement_on_SEEN_alone_does_not_earn_exit_0"])


def test_no_importorskip_hides_a_missing_stack():
    tree = ast.parse((REPO / "test" / "test_eval_harness.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", getattr(n.func, "id", "")) == "importorskip"]
    assert calls == []


class _Item:
    def __init__(self, *markers):
        self._m = set(markers)

    def get_closest_marker(self, name):
        return name if name in self._m else None


def test_the_summary_names_each_marker_with_its_count(monkeypatch):
    monkeypatch.setattr(conftest, "_DESELECTED_BY_MARKER", {})
    conftest.pytest_deselected([_Item("live_state"), _Item("training_stack"), _Item("training_stack"), _Item()])
    assert conftest.deselected_line(conftest._DESELECTED_BY_MARKER) == \
        "deselected by marker: live_state 1, training_stack 2"


# ── mutations ───────────────────────────────────────────────────────────────
def test_mutation_a_marker_dropped_from_one_test_is_seen():
    src = (REPO / "test" / "test_eval_harness.py").read_text(encoding="utf-8")
    src = src.replace("@pytest.mark.training_stack\ndef test_exit_1_when_the_adapter_did_nothing(",
                      "def test_exit_1_when_the_adapter_did_nothing(", 1)
    assert "test_exit_1_when_the_adapter_did_nothing" not in _marked(ast.parse(src))


def test_mutation_an_importorskip_would_be_seen():
    tree = ast.parse('torch = pytest.importorskip("torch")\n')
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", "") == "importorskip"]
