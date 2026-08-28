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


class Unparseable(Exception):
    """A file the guard COULD NOT READ. It is not "clean" — it is a BLIND SPOT.

    RECOVERED REQUIREMENT, NEW IMPLEMENTATION, 2026-08-28. The lost version drew
    this distinction; a `git reset --hard` destroyed it. The requirement survives
    in test/__pycache__/test_no_exit_on_import.cpython-314-pytest-9.1.1.pyc
    compiled 2026-08-20 12:13:43.

    The defect it closes: `except Exception: return []` reported an unreadable or
    unparseable file as having no offenders, which is indistinguishable from a
    file that was read and found clean. A guard that cannot read a file and says
    nothing has not checked it — it has failed quietly. Same principle as the
    counted SKIP in cockpit/glass.py: read it, or say why not, but never let
    silence pass for a pass.
    """


def offenders(path: Path) -> list[int]:
    """Line numbers of import-time process kills.

    Raises Unparseable when the file could not be read or parsed. The caller must
    not treat that as clean.
    """
    try:
        # utf-8-sig strips a BOM; strict means an encoding fault SURFACES instead
        # of being silently mangled by errors="ignore", which is how an
        # unreadable file used to look exactly like an empty one.
        text = path.read_text(encoding="utf-8-sig", errors="strict")
    except Exception as e:
        raise Unparseable(f"cannot read: {type(e).__name__}: {e}") from e
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise Unparseable(f"does not parse: {e.msg} (line {e.lineno})") from e
    except Exception as e:
        raise Unparseable(f"does not parse: {type(e).__name__}: {e}") from e

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


def _script_style() -> set:
    """The files whose module-level sys.exit() is the DOCUMENTED convention.

    test/_script_style.py calls itself "the single source of the split" and
    computes it rather than hand-listing it. A second guard that contradicts
    that split would be two truths about the same question — the schism this
    repo keeps naming. So this reads the declared split instead of re-deciding
    it. If _script_style cannot be imported, nothing is excluded: a guard that
    silently widens its own exemptions is worse than a noisy one.
    """
    try:
        sys.path.insert(0, str(BASE / "test"))
        from _script_style import SCRIPT_STYLE
        return {s.replace("\\", "/") for s in SCRIPT_STYLE}
    except Exception:
        return set()


def main() -> int:
    bad, blind = [], []
    scripted = _script_style()
    skipped = []
    for p in sorted(BASE.rglob("*.py")):
        if SKIP_PARTS & set(p.parts):
            continue
        rel = p.relative_to(BASE)
        if str(rel).replace("\\", "/") in scripted:
            # Legitimate by the repo's own declaration, and COUNTED — an
            # exemption nobody can see is an exemption nobody can challenge.
            skipped.append(str(rel).replace("\\", "/"))
            continue
        try:
            lines = offenders(p)
        except Unparseable as e:
            blind.append(f"{rel}: {e}")
            continue
        for line in lines:
            bad.append(f"{rel}:{line}")

    rc = 0
    if bad:
        print("FAIL: модул(и) убиват процеса ПРИ ИМПОРТ — забранено:")
        for b in bad:
            print(f"  {b}")
        print("Поправка: вдигни ImportError или деградирай с флаг "
              "(виж HAS_FEEDPARSER в web_intelligence_agent.py).")
        rc = 1
    if blind:
        # A BLIND SPOT IS A FAILURE, NOT A PASS. The guard did not check these,
        # and reporting nothing about them is how "clean" came to include
        # "never read".
        print("FAIL: files the guard COULD NOT READ — these are blind spots, "
              "not clean files:")
        for b in blind:
            print(f"  {b}")
        print("Fix: remove the BOM (save as UTF-8 without BOM) or fix the "
              "syntax. Dead code belongs in LEGACY/ or OLD/.")
        rc = 1
    if skipped:
        print(f"  ({len(skipped)} script-style file(s) exempt by "
              f"test/_script_style.py — module-level sys.exit is their "
              f"documented convention)")
    if rc == 0:
        print("OK: no module kills the process on import, and every file was "
              "actually read")
    return rc


if __name__ == "__main__":
    sys.exit(main())
