"""The one place that decides which test files pytest may import.

This repo's tests come in two populations. Most are ordinary pytest modules. The rest
are standalone scripts, meant to be run one at a time
(`venv/Scripts/python.exe test/test_pulse.py`), and pytest cannot collect those — it has
to IMPORT a module to collect it, and importing these does something fatal.

Two shapes, each breaking collection its own way:

  * a module-level `sys.exit(...)` at column 0. Raised during collection, this aborted
    the entire run: `pytest` reported INTERNALERROR and "no tests ran" — none of the
    fifty test files executed. A run that looks green because it ran nothing is worse
    than a red one. (21 files in test/.)
  * a `main()` behind an `if __name__ == "__main__":` guard, whose `test_*` functions
    take real arguments instead of fixtures. pytest collects them and then errors with
    "fixture 'src' not found". (experiments/dreams/test_dream.py.)

The split is COMPUTED, never hand-listed, so a new script-style test is picked up the
day it is written instead of quietly dropping out of the suite. No pytest-style file in
this repo matches either signal, so computing it is safe.

The root conftest.py excludes these from collection; test/test_script_suite.py runs each
as a subprocess, so `pytest` still means every test.
"""
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO = TEST_DIR.parent
SCAN_DIRS = (TEST_DIR, REPO / "experiments")


def is_script_style(path: Path) -> bool:
    """True if pytest cannot import-and-collect this file the ordinary way."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    if any(ln.startswith("sys.exit(") for ln in lines):
        return True
    has_guard = any(ln.startswith('if __name__ == "__main__":') for ln in lines)
    has_main = any(ln.startswith("def main(") for ln in lines)
    return has_guard and has_main


def script_style_paths() -> list:
    """Repo-relative POSIX paths, so conftest and the runner speak the same language."""
    out = set()
    for root in SCAN_DIRS:
        if not root.exists():
            continue
        for p in sorted(root.rglob("test_*.py")):
            if is_script_style(p):
                out.add(p.resolve().relative_to(REPO).as_posix())
    return sorted(out)


SCRIPT_STYLE = script_style_paths()
