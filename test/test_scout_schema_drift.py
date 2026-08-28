"""A changed source is NEWS. Broken code is a DEFECT. They must not look alike.

PROVENANCE. Requirement RECOVERED, implementation NEW, dated 2026-08-28. A
`git reset --hard` over uncommitted work destroyed the version that drew this
distinction; it survives in experiments/browser_scout/__pycache__/scout
.cpython-314.pyc compiled 2026-08-17 14:16:18, which kept the class docstring
whole and named the lost class: SourceSchemaDrift.

Quoted from the recovered docstring:

    "The extraction contract no longer holds — the source has changed.
     Kimi, 15 August 2026: 'Fragility is source_schema_drift, not a step
     failure.' A separate type, so the cycle can tell 'my code broke' from 'the
     world I was reading now looks different'. The second is news, the first is
     a defect."

and the message it carries:

    "the extraction contract is invalid: the phrase 'The N conflicts in the
     following list' is gone. The page has changed — this is an event for the
     source, not an error in the code."

THE DEFECT THIS CLOSES. _extract_ongoing_conflicts raised a bare ValueError when
the page layout changed, and run_all caught bare Exception and printed FAILED.
A source that quietly restructured its page and a scout with a bug produced the
same line. One of those is a finding about the world worth acting on; the other
is a ticket. Recording them identically loses the difference — the same shape as
an empty fetch written as REAL_DATA, and as a truncated answer published as LOW.
"""
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from experiments.browser_scout import scout as sc     # noqa: E402

# A page that still parses as HTML but no longer states its tiers the old way.
CHANGED_PAGE = """<html><body>
<h2>List of ongoing armed conflicts</h2>
<p>This list now groups conflicts by region instead of by fatality tier.</p>
</body></html>"""

INTACT_PAGE = """<html><body>
<p>The 6 conflicts in the following list have caused at least 10,000 deaths.</p>
<p>The 12 conflicts in the following list have caused 1,000-9,999 deaths.</p>
</body></html>"""


def test_the_drift_type_exists_and_is_not_a_plain_error():
    assert hasattr(sc, "SourceSchemaDrift")
    assert issubclass(sc.SourceSchemaDrift, Exception)
    assert sc.SourceSchemaDrift is not ValueError, (
        "a separate TYPE is the whole point — the cycle must be able to tell "
        "'my code broke' from 'the world I was reading looks different'")


def test_a_changed_page_raises_drift_not_a_bare_error():
    with pytest.raises(sc.SourceSchemaDrift) as e:
        sc._extract_ongoing_conflicts(CHANGED_PAGE)
    msg = str(e.value)
    assert "The N conflicts in the following list" in msg, (
        "the message must name the CONTRACT that no longer holds, so a human "
        "can check the page against it")
    assert "not an error in the code" in msg


def test_an_intact_page_still_extracts():
    """The negative control: drift must not swallow the working path."""
    total, breakdown, evidence = sc._extract_ongoing_conflicts(INTACT_PAGE)
    assert total == 18
    assert len(evidence) == 2, "the counted substrings are the evidence"


def test_drift_is_reported_as_a_source_event_not_a_step_failure():
    """run_all must classify it, not flatten it into FAILED."""
    src = (REPO / "experiments" / "browser_scout" / "scout.py").read_text(
        encoding="utf-8")
    assert "source_schema_drift" in src, (
        "the event needs a name the cycle can key on")
    assert "SOURCE HAS CHANGED" in src.upper(), (
        "and a line a human reads differently from FAILED")


def test_the_record_carries_the_event_and_the_reason():
    out = sc._drift_record("social_conflicts",
                           sc.SourceSchemaDrift("contract gone"))
    assert out["ok"] is False
    assert out["event"] == "source_schema_drift"
    assert out["reason"], "a drift with no reason is unactionable"
    assert "error" not in out or out.get("event"), (
        "drift must not be filed under the same key as a code fault")


def test_a_real_code_fault_is_still_a_failure_not_drift():
    """The distinction cuts both ways, or it is not a distinction."""
    out = sc._fault_record("social_conflicts", TypeError("bad slice"))
    assert out["ok"] is False
    assert out.get("event") != "source_schema_drift"
    assert "TypeError" in out["error"]
