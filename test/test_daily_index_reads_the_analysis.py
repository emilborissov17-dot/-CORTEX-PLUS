"""The published index said the system knew nothing. The page behind it said HIGH.

WHAT WAS PUBLIC (measured 17 Aug 2026)
---------------------------------------
reports/2026-08-17/index.md, live in the public repo, every row of 26:

    | [WATER_REVIEW](water_review.md) | UNKNOWN | ... |

and reports/2026-08-17/water_review.md, one click behind it:

    **Severity:** HIGH
    ## Problem
    Pollution and contamination of freshwater sources, exacerbated by climate
    change and human activities

_publish_daily_index read `data.get("severity")` and `data.get("problem")` from
the JSON ROOT. In the real files those keys live under `analysis` and the root
has neither. _format_as_markdown had solved this from the day it was written,
with a get_field() helper checking both — the index simply never used it. So the
summary page of every daily report, for months, was a table of UNKNOWN sitting
in front of pages full of findings.

The helper is now lifted to module scope and used by both, rather than a second
copy written for the index. One definition of where a field lives is the point:
a duplicate would be free to drift the same way again.

THE FIXTURES ARE THE REAL FILES
--------------------------------
Every assertion below loads memory/web_intelligence/<date>/*.json off disk. A
test that invented `{"severity": "HIGH"}` at the root would have passed against
the broken code — inventing the shape is exactly the mistake that let this
survive, so the shape is not invented here.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import github_publisher as gp

WEB_INTEL = REPO / "memory" / "web_intelligence"


def _latest_real_dir():
    if not WEB_INTEL.exists():
        pytest.skip("memory/web_intelligence absent")
    dirs = [d for d in sorted(WEB_INTEL.iterdir(), reverse=True)
            if d.is_dir() and list(d.rglob("*.json"))]
    if not dirs:
        pytest.skip("no web_intelligence run with JSON in it")
    return dirs[0]


def _axis_files(d):
    return [f for f in sorted(d.rglob("*.json")) if f.stem not in gp.SUMMARY_STEMS]


def test_the_real_files_really_do_hide_severity_under_analysis():
    """If this stops being true the bug is gone and so is the point of this file."""
    d = _latest_real_dir()
    files = _axis_files(d)
    assert files, f"no axis JSON in {d}"
    hidden = 0
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("severity") is None and (data.get("analysis") or {}).get("severity"):
            hidden += 1
    assert hidden > 0, (
        f"no file in {d.name} keeps severity under 'analysis' any more. The "
        f"writer changed shape; re-read _publish_daily_index before deleting this.")


def test_the_index_reports_the_severity_the_axis_page_reports(monkeypatch):
    """The two documents must agree, because they describe the same run."""
    d = _latest_real_dir()
    pushed = {}
    monkeypatch.setattr(gp, "_push_file",
                        lambda p, c, m: pushed.setdefault(p, c) or 200)

    gp._publish_daily_index(d.name, d)
    index = next(v for k, v in pushed.items() if k.endswith("index.md"))

    checked = 0
    for f in _axis_files(d):
        data = json.loads(f.read_text(encoding="utf-8"))
        axis = data.get("axis", f.stem)
        severity = gp.get_field(data, "severity")
        if not severity:
            continue
        checked += 1
        row = next((line for line in index.splitlines()
                    if f"[{axis}]" in line), None)
        assert row, f"{axis} is missing from the index entirely"
        assert f"| {severity} |" in row, (
            f"the index reports a different severity for {axis} than its own "
            f"page does.\n  index row: {row}\n  file says: {severity}")
    assert checked >= 5, f"only {checked} axes had a severity — too few to prove anything"

    # NOT "no UNKNOWN rows anywhere". Measured on the real 2026-08-17 run, one
    # axis (GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL) carries the literal string
    # severity: 'UNKNOWN' and no `problem` key at all — the model said UNKNOWN.
    # That row is HONEST and the index must be free to print it. What must not
    # happen is the index inventing UNKNOWN for axes whose files say otherwise,
    # which is what the assertion loop above checks.
    honest_unknown = sum(
        1 for f in _axis_files(d)
        if (gp.get_field(json.loads(f.read_text(encoding="utf-8")), "severity")
            or "UNKNOWN") == "UNKNOWN")
    printed_unknown = sum(1 for l in index.splitlines()
                          if l.startswith("| [") and "| UNKNOWN |" in l)
    assert printed_unknown == honest_unknown, (
        f"the index prints {printed_unknown} UNKNOWN rows but only "
        f"{honest_unknown} source files actually say UNKNOWN")


def test_the_old_root_only_read_would_have_said_unknown_for_everything(monkeypatch):
    """POSITIVE CONTROL: reproduce the shipped bug and prove this file catches it.

    A test that only asserts the fixed behaviour cannot tell you it is testing
    the right thing. This re-implements the exact line that was public —
    data.get("severity") off the root — over the same real files, and shows it
    yields UNKNOWN for effectively everything.
    """
    d = _latest_real_dir()
    files = _axis_files(d)

    old = [json.loads(f.read_text(encoding="utf-8")).get("severity", "UNKNOWN")
           for f in files]
    new = [gp.get_field(json.loads(f.read_text(encoding="utf-8")), "severity")
           or "UNKNOWN" for f in files]

    assert all(s in (None, "UNKNOWN") for s in old), (
        "the root-only read no longer produces UNKNOWN for every axis — the bug "
        "cannot be reproduced, so this file has stopped guarding anything")
    old_real = [s for s in old if s and s != "UNKNOWN"]
    new_real = [s for s in new if s != "UNKNOWN"]
    assert not old_real, "the root-only read recovered a severity it never could"
    # Measured on the 2026-08-17 run: 19 of 25 axes carry a real severity under
    # `analysis`; the remaining 6 say UNKNOWN in the source itself. The claim is
    # therefore "a majority, and strictly more than the zero the old read got" —
    # not an invented near-total, which would go red the next time the model
    # declines to rate a few axes.
    assert len(new_real) > len(old_real), \
        "the fix recovers no more severities than the bug did"
    assert len(new_real) >= len(files) // 2, (
        f"the fixed read recovers only {len(new_real)} of {len(files)}; that is "
        f"not a majority, so something else is now wrong with the lookup")


def test_one_definition_of_where_a_field_lives():
    """POSITIVE CONTROL against a second helper being written later.

    The bug was two readers disagreeing about where severity lives. A future
    copy-paste would re-create it silently, so: the index must call the shared
    helper, and the module must not grow a second inner get_field.
    """
    src = (REPO / "github_publisher.py").read_text(encoding="utf-8")
    idx = src.index("def _publish_daily_index")
    body = src[idx:idx + 2000]
    assert "get_field(data," in body, \
        "_publish_daily_index no longer uses the shared helper"
    assert 'data.get("severity"' not in body and 'data.get("problem"' not in body, \
        "_publish_daily_index is reading the root directly again"
    assert src.count("def get_field") == 1, \
        "a second get_field exists — one definition, or the index drifts again"


# ---------------------------------------------------------------------------
# master_web_intel is a summary, not an axis
# ---------------------------------------------------------------------------

def test_the_summary_file_is_not_listed_as_an_axis(monkeypatch):
    d = _latest_real_dir()
    if not (d / "master_web_intel.json").exists():
        pytest.skip("this run has no master_web_intel.json")
    pushed = {}
    monkeypatch.setattr(gp, "_push_file",
                        lambda p, c, m: pushed.setdefault(p, c) or 200)
    gp._publish_daily_index(d.name, d)
    index = next(v for k, v in pushed.items() if k.endswith("index.md"))

    rows = [l for l in index.splitlines() if l.startswith("| [")]
    assert not any("[master_web_intel]" in r for r in rows), (
        "the run summary is still listed as an axis; it has no severity or "
        "problem and produced a permanent UNKNOWN row")

    master = json.loads((d / "master_web_intel.json").read_text(encoding="utf-8"))
    assert len(rows) == master.get("axes_covered"), (
        f"the table has {len(rows)} rows but the run covered "
        f"{master.get('axes_covered')} axes — the count the README states")

    # ...and it is not thrown away: its numbers open the index, and its own page
    # is still linked, because 33 published report folders contain that link.
    assert "master_web_intel.md" in index, \
        "the summary page was dropped from the index entirely; its link is public history"
    assert str(master.get("total_sources")) in index, \
        "the summary's numbers were discarded rather than moved"
