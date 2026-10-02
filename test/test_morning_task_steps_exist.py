# -*- coding: utf-8 -*-
"""test/test_morning_task_steps_exist.py — the morning task calls what exists
(C-FIX-1 Part 7, 2 Oct 2026).

tools/prophecy_morning.bat called experiments/institution/witness_reader.py, whose
poll() was retired on 18 Sep 2026 (5fb7661) and raises: the step failed every
morning since. Every `call :step` must name a file that exists and an entry point
whose main() does not call a retired function (one whose body raises a
RuntimeError saying "is retired").
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BAT = REPO / "tools" / "prophecy_morning.bat"
STEP = re.compile(r'^\s*call :step\s+"[^"]*"\s+"%PY%\s+([^\s"]+\.py)', re.M)


def steps(text: str) -> list:
    return [m.replace("\\", "/") for m in STEP.findall(text)]


def retired_functions(tree: ast.Module) -> set:
    out = set()
    for n in tree.body:
        if not isinstance(n, ast.FunctionDef):
            continue
        body = [b for b in n.body if not (isinstance(b, ast.Expr) and isinstance(getattr(b, "value", None), ast.Constant))]
        if body and isinstance(body[0], ast.Raise):
            src = ast.unparse(body[0])
            if "is retired" in src:
                out.add(n.name)
    return out


def main_calls(tree: ast.Module) -> set:
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "main":
            return {c.func.id for c in ast.walk(n) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    return set()


def problems(text: str, repo: Path = REPO) -> list:
    out = []
    for rel in steps(text):
        p = repo / rel
        if not p.exists():
            out.append(f"{rel}: the file does not exist")
            continue
        tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        bad = main_calls(tree) & retired_functions(tree)
        if bad:
            out.append(f"{rel}: main() calls the retired {sorted(bad)}")
    return out


def test_every_step_names_a_file_that_exists_and_is_not_retired():
    text = BAT.read_text(encoding="utf-8")
    assert len(steps(text)) >= 15, "the step parser found too few steps to be reading the .bat"
    assert problems(text) == []


def test_the_witness_step_calls_the_dispatcher():
    assert "experiments/institution/telegram_dispatcher.py" in steps(BAT.read_text(encoding="utf-8"))


def test_mutation_a_step_on_the_retired_witness_reader_fails():
    bad = 'call :step "institution0_witness"  "%PY% experiments\\institution\\witness_reader.py"          no\n'
    assert problems(bad) == ["experiments/institution/witness_reader.py: main() calls the retired ['poll']"]


def test_mutation_a_step_on_a_missing_file_fails():
    bad = 'call :step "fill_pantry"           "%PY% tools\\fill_pantry.py"                              no\n'
    assert problems(bad) == ["tools/fill_pantry.py: the file does not exist"]
