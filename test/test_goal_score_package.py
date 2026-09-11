#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_goal_score_package.py — the composite may never travel alone.

Kimi, 15 August 2026 (step 14 of 53):
  "Семантичната колона може да бъде прочетена като «мнение» и игнорирана, докато
   числото се чете като «истина». Ако публикуваш само числото при
   composite_valid=True, семантичната колона става гроб. Трябва ЗАДЪЛЖИТЕЛНО да
   излизат заедно — число без семантика е театър (или «тъмна цифра» — едно и също)."

An agreement that lives only in a comment is an agreement that dies the first time
someone is in a hurry. So it lives here instead: this test walks every module in the
repository, finds every scope that reads `composite_score`, and fails the build if
that same scope does not also carry the package — the two coverages, the two flags,
or the single blessed formatter `format_headline()`.

Same shape as test/test_no_exit_on_import.py: a structural ban, enforced by the AST,
not by anyone's memory.

  venv\\Scripts\\python.exe -m test.test_goal_score_package
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Четенето на числото е позволено САМО в компанията на поне едно от тези.
PACKAGE_MARKERS = (
    "format_headline",
    "coverage_of_goal",
    "coverage_of_measurable",
    "sensors_ok",
    "goal_covered",
    "semantic_axes",
    "coverage",              # старият договор, все още валиден
    "insufficient_data",
)

# Файлове, на които четенето е РАБОТАТА, а не отчет пред човек.
EXEMPT = {
    "goal_score_calculator.py",          # тук числото се ражда
    "test_goal_score_package.py",        # този тест
}

SKIP_DIRS = {".git", "venv", "venv312_metta", "__pycache__", "node_modules",
             "snapshots", "memory", "data", "logs", "output", "cortex_memory",
             # Гробището. Мъртъв код, който нищо живо не импортва — пазач, който
             # вика за него, се обезсилва сам.
             "LEGACY", "OLD"}


def _scopes(tree: ast.AST):
    """Всеки самостоятелен обхват: модулът и всяка функция в него."""
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _reads_composite(node: ast.AST) -> bool:
    """Има ли в ТОЗИ обхват четене на ключа composite_score?"""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Subscript):
            k = sub.slice
            if isinstance(k, ast.Constant) and k.value == "composite_score":
                return True
        # .get("composite_score")
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                and sub.func.attr == "get" and sub.args:
            a0 = sub.args[0]
            if isinstance(a0, ast.Constant) and a0.value == "composite_score":
                return True
    return False


def _has_package(node: ast.AST, src: str) -> bool:
    seg = ast.get_source_segment(src, node) or ""
    return any(m in seg for m in PACKAGE_MARKERS)


def check_file(path: Path) -> tuple:
    """(нарушения, слепи_петна). Двете НЕ се смесват: нарушение е видяна лъжа,
    сляпо петно е файл, който изобщо не е бил прочетен. Второто беше докладвано
    като първото и това правеше списъка нечетим."""
    try:
        src = path.read_text(encoding="utf-8-sig", errors="strict")
        tree = ast.parse(src)
    except Exception as e:
        return [], [f"{path.name}: {type(e).__name__}: {e}"]
    faults = []
    for scope in _scopes(tree):
        if not _reads_composite(scope):
            continue
        # модулът като цяло се проверява само ако нарушението не е вътре в функция
        if isinstance(scope, ast.Module):
            inner = [n for n in ast.walk(scope)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and _reads_composite(n)]
            if inner:
                continue
        if _has_package(scope, src):
            continue
        name = getattr(scope, "name", "<module>")
        line = getattr(scope, "lineno", 1)
        faults.append(
            f"{path.relative_to(REPO)}:{line} в {name}() чете composite_score БЕЗ "
            f"покритието. Числото само по себе си е тъмна цифра — вземи и "
            f"coverage_of_goal/coverage_of_measurable, или ползвай "
            f"goal_score_calculator.format_headline().")
    return faults, []


def main() -> int:
    faults, blind, checked = [], [], 0
    for p in REPO.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in EXEMPT:
            continue
        checked += 1
        f, b = check_file(p)
        faults.extend(f)
        blind.extend(b)
    if blind:
        print(f"FAIL: {len(blind)} file(s) the guard could NOT read — blind spots, "
              f"not clean files:")
        for b in blind:
            print("  ? " + b)
        print("  (BOM -> save as UTF-8 without BOM; dead code -> LEGACY/ or OLD/)")
    if faults:
        print(f"FAIL: {len(faults)} place(s) read the composite without its package "
              f"({checked} files checked)")
        for f in faults:
            print("  - " + f)
    if faults or blind:
        return 1
    print(f"OK: the composite never travels alone, and every file was actually "
          f"read ({checked} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
