#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_no_exit_on_import.py — ЗАБРАНАТА, пазена от машина (15 август 2026)

КОНСЕНСУС С KIMI, след стъпка 8:
  „sys.exit() при импорт е противопехотна мина в система без надзор. BaseException
   е бинт, не лек: лови и KeyboardInterrupt, а по-важното — крие болестта.
   Истинската поправка е ЗАБРАНА: нито един модул не бива да убива процеса при
   липса на незадължителен пакет; трябва да хвърля ImportError или да си мълчи.
   Нощният запис е късно — ако гръмне на стъпка 1, остават 51 слепи стъпки."

Поводът беше истински: web_intelligence_agent.py викаше sys.exit(1), ако липсва
feedparser. SystemExit не е ImportError и не е Exception, тоест try/except в
извикващия не хващаше нищо — липсата на ЕДИН незадължителен пакет убиваше цялата
нощ. Мина незабелязано само защото на машината пакетът е инсталиран.

Затова тук не се поправя случай, а се затваря РОД: този тест минава по цялото дърво
и пада, ако нечие тяло на модул може да убие процеса при импорт. Кодът под
`if __name__ == "__main__":` е разрешен — той е програма, не библиотека.

  venv\\Scripts\\python.exe test\\test_no_exit_on_import.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SKIP_PARTS = {"__pycache__", ".git", "venv", "venv312_metta", "snapshots",
              "node_modules", "site-packages"}


def _is_exit(node: ast.AST) -> bool:
    if isinstance(node, ast.Raise):
        e = node.exc
        n = e.func if isinstance(e, ast.Call) else e
        return isinstance(n, ast.Name) and n.id == "SystemExit"
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        f = node.value.func
        if isinstance(f, ast.Attribute) and f.attr == "exit":
            return isinstance(f.value, ast.Name) and f.value.id == "sys"
        if isinstance(f, ast.Name) and f.id in ("exit", "quit"):
            return True
    return False


def _is_main_guard(node: ast.AST) -> bool:
    """if __name__ == "__main__": — програма, не библиотека."""
    if not isinstance(node, ast.If):
        return False
    t = node.test
    return (isinstance(t, ast.Compare)
            and isinstance(t.left, ast.Name) and t.left.id == "__name__")


def offenders(path: Path) -> list[int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    found: list[int] = []

    def walk(body):
        for n in body:
            # функции и класове не се изпълняват при импорт
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if _is_main_guard(n):
                continue
            if _is_exit(n):
                found.append(n.lineno)
            for attr in ("body", "orelse", "finalbody"):
                if hasattr(n, attr):
                    walk(getattr(n, attr))
            for h in getattr(n, "handlers", []):
                walk(h.body)

    walk(tree.body)
    return found


def main() -> int:
    bad = []
    for p in sorted(BASE.rglob("*.py")):
        if SKIP_PARTS & set(p.parts):
            continue
        for line in offenders(p):
            bad.append(f"{p.relative_to(BASE)}:{line}")
    if bad:
        print("FAIL: модул(и) убиват процеса ПРИ ИМПОРТ — забранено:")
        for b in bad:
            print(f"  {b}")
        print("Поправка: вдигни ImportError или деградирай с флаг "
              "(виж HAS_FEEDPARSER в web_intelligence_agent.py).")
        return 1
    print("OK: нито един модул не убива процеса при импорт")
    return 0


if __name__ == "__main__":
    sys.exit(main())
