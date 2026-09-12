"""Keep coverage running only in the processes that are OURS.

WHY THIS IS NOT WHAT IT LOOKS LIKE. The obvious shape -- "call
coverage.process_startup() when the process is ours" -- is inert in this venv,
and was measured to be: coverage ships
venv/Lib/site-packages/a1_coverage.pth, which runs

    if os.getenv("COVERAGE_PROCESS_START"): coverage.process_startup(slug="pth")

in EVERY interpreter, and .pth files execute BEFORE sitecustomize. So by the
time this file runs, coverage has already started; a guard that only decides
whether to call process_startup() decides nothing. Proven by running child.py
with no PYTHONPATH and no sitecustomize at all: still one data file.

What is left to decide is therefore the opposite: whether to CANCEL what the
.pth already started. Not ours -> stop and erase, and the process writes no
data file. That is why the branch below stops coverage instead of starting it.

WHAT THIS DOES AND DOES NOT SAVE. It removes the tracing and the empty data
file from every foreign child -- 677 of the 679 processes on the first
whole-cycle run were yt-dlp and its kin, each writing nothing. It does NOT save
the import of coverage itself, which the .pth has already paid for. The saving
is real but partial, and calling it a fix for the memory ceiling would be a
claim this file cannot support.

OURS means one of two things, and the first is not a shortcut:
  * argv[0] == "-c" -- the runner spawns children as `python -c "..."`, and such
    a child has no script path to test. Excluding it would silently drop exactly
    the children the cycle itself creates.
  * a script under COVERAGE_ONLY_UNDER, but not inside venv or site-packages
    (yt-dlp.exe lives in the venv's Scripts directory, which is how it falls out).

With COVERAGE_ONLY_UNDER unset, a script-path process is NOT ours, so an
ordinary coverage run that forgets the variable measures the parent only and
says so loudly by measuring nothing else.
"""
import os
import sys

_root = os.environ.get("COVERAGE_ONLY_UNDER", "")


def _ours() -> bool:
    a0 = sys.argv[0] or ""
    if a0 == "-c":                      # python -c children of the runner
        return True
    if not _root:
        return False
    try:
        p = os.path.realpath(a0)
        r = os.path.realpath(_root)
        if not p.startswith(r):
            return False
        rest = p[len(r):].lower()
        return "venv" not in rest and "site-packages" not in rest
    except Exception:
        return False


if not _ours():
    try:
        import coverage

        _c = coverage.Coverage.current()
        if _c is not None:
            _c.stop()
            _c.erase()
    except Exception:
        pass
