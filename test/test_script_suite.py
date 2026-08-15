"""Runs the script-style tests under pytest, so `pytest` means all fifty.

21 of this repo's test files assert at import time and end in a module-level
`sys.exit(...)`. That is a fine way to write them — each is runnable on its own — but
pytest cannot collect them: importing one raises SystemExit and aborts the entire run
(see the root conftest.py). They are excluded from direct collection there and executed
here, one subprocess each, with the repo root on PYTHONPATH exactly as running them by
hand would give.

One pytest case per file, named after the file, so a failure points straight at it and
carries that script's own output.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _script_style import SCRIPT_STYLE     # the single source of the split  # noqa: E402


@pytest.mark.parametrize("script", SCRIPT_STYLE)
def test_script_style_suite(script):
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / script)],
                          cwd=str(REPO), env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=900)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout or "").splitlines()[-25:])
        pytest.fail(f"{script} exited {proc.returncode}\n"
                    f"--- stdout (tail) ---\n{tail}\n"
                    f"--- stderr (tail) ---\n{(proc.stderr or '')[-2000:]}")


def test_the_split_covers_every_test_file():
    """No file may fall between the two populations and go unrun."""
    all_tests = {p.resolve().relative_to(REPO).as_posix()
                 for p in (REPO / "test").glob("test_*.py")}
    scripted = set(SCRIPT_STYLE)
    assert scripted, "script-style detection found nothing — the split is broken"
    # every test/ file is either run here as a subprocess or collected by pytest itself
    assert all_tests - scripted, "nothing left for pytest to collect — split is inverted"
    assert (REPO / "test" / "test_pulse.py").exists()
    assert "test/test_pulse.py" in scripted, "a known script-style file went unclassified"
