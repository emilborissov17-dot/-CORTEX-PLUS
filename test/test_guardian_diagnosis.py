"""A rejected patch must record WHY it was rejected.

The guardian truncated a failing patch's stderr to its first 300 characters. A Python
traceback opens with boilerplate and a frame list and names the fault on its LAST line,
so head-truncation kept the least useful part and dropped the verdict. The real
quarantine record for ecosystems_biodiversity_review_patch (2026-08-04) ends mid-path at
"...ecosystems_biodiversity_revie"; the actual cause, KeyError: 'name', appears nowhere
in the file. A self-improvement loop that cannot see why its own code failed cannot
learn from it.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

from patch_guardian import _diagnosis  # noqa: E402

REAL_TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "C:\\Users\\emilb\\Desktop\\AGI\\CORTEX++_MERGED\\agents\\core\\'
    'ecosystems_biodiversity_review_patch.py", line 107, in <module>\n'
    "    _example_setup()\n"
    "    ~~~~~~~~~~~~~~^^\n"
    '  File "C:\\Users\\emilb\\Desktop\\AGI\\CORTEX++_MERGED\\agents\\core\\'
    'ecosystems_biodiversity_review_patch.py", line 89, in _example_setup\n'
    '    reserves = _add_reserve(reserves, "Green Corridor Alpha", "Midwest USA", 150)\n'
    '  File "C:\\Users\\emilb\\Desktop\\AGI\\CORTEX++_MERGED\\agents\\core\\'
    'ecosystems_biodiversity_review_patch.py", line 45, in _add_reserve\n'
    '    if r["name"] == name:\n'
    "       ~^^^^^^^^\n"
    "KeyError: 'name'"
)


def test_the_cause_survives_truncation():
    """The last line is the diagnosis — it may never be the part that gets cut."""
    assert len(REAL_TRACEBACK) > 600, "fixture too short to exercise truncation"
    assert "KeyError: 'name'" not in REAL_TRACEBACK[:300], "old behaviour kept the cause"
    assert "KeyError: 'name'" in _diagnosis(REAL_TRACEBACK)


def test_a_leading_warning_cannot_eat_the_budget():
    """One DeprecationWarning ahead of the traceback used to consume all 300 chars."""
    noisy = ("patch.py:29: DeprecationWarning: datetime.datetime.utcnow() is deprecated "
             "and scheduled for removal in a future version. Use timezone-aware objects "
             "to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).\n"
             '  "run"\n') + REAL_TRACEBACK
    assert "KeyError" in _diagnosis(noisy)


def test_short_stderr_is_returned_whole():
    assert _diagnosis("ValueError: bad input") == "ValueError: bad input"
    assert _diagnosis("") == ""
    assert _diagnosis(None) == ""


def test_output_stays_bounded():
    out = _diagnosis("x" * 50_000)
    assert len(out) <= 700, "a runaway stderr must not be written to disk in full"
