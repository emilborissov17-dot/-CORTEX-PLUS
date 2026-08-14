"""Root conftest — makes a bare `pytest` actually run this repo's suite.

21 of the 50 files in `test/` are standalone scripts that assert at import time and end
with a module-level `sys.exit(...)`. pytest imports a module in order to collect it, so
that call raised SystemExit during COLLECTION: pytest reported INTERNALERROR and "no
tests ran", and not one test out of fifty executed. A `pytest` run that looks green
because it ran nothing is worse than a red one.

Those files are NOT rewritten — the style is deliberate here and each is runnable on its
own (`venv/Scripts/python.exe test/test_pulse.py`). They are excluded from direct
collection below and executed as subprocesses by test/test_script_suite.py, so `pytest`
still runs all fifty and a failure in any of them fails the run.

test/_script_style.py owns the split; it is loaded by path because `test/` is not a
package and `conftest` alone resolves to test/conftest.py from inside the suite.
"""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "_cortex_script_style", REPO / "test" / "_script_style.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SCRIPT_STYLE = _mod.SCRIPT_STYLE
collect_ignore = list(SCRIPT_STYLE)
