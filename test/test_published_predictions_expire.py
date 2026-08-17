"""An expired prediction must never be published as a current one.

WHAT WAS PUBLIC (measured 17 Aug 2026)
---------------------------------------
Every night, reports/{today}/verified_hypotheses.md went out to the public repo
emilborissov17-dot/cortex-civilization-watch reading:

    # Verified Hypotheses — 2026-08-17
    | co2_ppm | ... ще остане стабилен на 432.4 ppm до 2026-07-20 | 432.44 |
      2026-07-20 | FLAGGED | 0.4 |

`prediction_date` was 2026-07-20 — four weeks past due, never resolved — and the
document was titled with the current date. The store was not lying; the formatter
was. It re-stamped an expired claim as today's, every night, for four weeks.

WHY IT WAS NEVER SCORED
-----------------------
Not because the scorer is broken. `scripts/score_prophecies.py` runs every cycle
through core/cortex_orchestrator.py:321 and succeeds — it scores a DIFFERENT
store (the prophecy ledger). The resolver for cortex_memory/hypotheses/pending.json
is `evaluator.check_due_hypotheses`, and its only caller in the whole repo is
hypothesis_generator.py:521, inside `if __name__ == "__main__"` behind `--check`.
Nothing on the cycle calls it. That is the root cause and it is NOT fixed here;
these tests pin the publication guard, which holds whether or not a resolver ever
runs.

THE FIXTURES ARE THE REAL STORE
--------------------------------
Every record used below is loaded from the live
cortex_memory/hypotheses/pending.json, not from a shape invented for the test. A
guard written against a hand-made record proves only that the guard matches the
imagination of whoever wrote it — which is how the root-key/analysis-key mismatch
in the daily index survived for months.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import github_publisher as gp

STORE = REPO / "cortex_memory" / "hypotheses" / "pending.json"


def _real_records():
    if not STORE.exists():
        pytest.skip(f"{STORE} absent — nothing real to test against")
    recs = json.loads(STORE.read_text(encoding="utf-8"))
    if not isinstance(recs, list) or not recs:
        pytest.skip("pending.json holds no records")
    return recs


def _real_expired(published_only: bool = False):
    """A record from the live store that is genuinely past due and unresolved.

    `published_only` matters and is not a detail. publish_verified_hypotheses
    only emits records with a truthy `verification_status`, so the store's other
    expired record (kp_index_20260617_183543, due 2026-07-17, status null) is
    past due, unresolved AND invisible — it is never published at all. The
    end-to-end test has to pick from what actually goes out, or it asserts
    against a document that record was never in.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for r in _real_records():
        if published_only and not r.get("verification_status"):
            continue
        if gp._resolution_state(r, today)[0] == gp.EXPIRED:
            return r
    pytest.skip("no past-due unresolved record in the live store today")


def test_the_live_store_is_the_shape_this_guard_assumes():
    """If the store stops looking like this, these tests are measuring nothing."""
    recs = _real_records()
    r = recs[0]
    for field in ("id", "axis", "prediction_date", "hypothesis_text"):
        assert field in r, (
            f"pending.json records no longer carry {field!r} (got {sorted(r)}). "
            f"The publisher reads these; update it and this file together.")


def test_a_past_due_unresolved_prediction_is_EXPIRED(_=None):
    """The record that was actually being published as current."""
    r = _real_expired()
    state, detail = gp._resolution_state(r)
    assert state == gp.EXPIRED, (
        f"{r.get('id')} is due {r.get('prediction_date')} and unresolved, but "
        f"reads as {state}")
    assert "overdue" in detail and str(r.get("prediction_date")) in detail, (
        f"the detail must carry the ORIGINAL date and how late it is: {detail!r}")


def test_the_published_page_never_presents_an_expired_prediction_as_current(tmp_path, monkeypatch):
    """End to end, on the real store: what would go out to the public repo.

    Captures the markdown at the _push_file boundary instead of pushing it, so
    this test exercises the whole formatter without touching the network.
    """
    pushed = {}

    def _capture(path, content, message):
        pushed[path] = content
        return 200

    monkeypatch.setattr(gp, "_push_file", _capture)
    r = _real_expired(published_only=True)

    n = gp.publish_verified_hypotheses()
    assert n >= 1, "nothing was published — the guard is untested"
    (path, md), = [(k, v) for k, v in pushed.items() if "hypotheses" in k]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert f"# Verified Hypotheses — {today}" not in md, (
        "the page still titles an expired prediction with today's date, which "
        "is the public claim this commit exists to stop")
    assert gp.EXPIRED in md, f"no EXPIRED label anywhere in the published page:\n{md[:600]}"
    assert str(r.get("prediction_date")) in md, (
        "the ORIGINAL prediction date is not visible — 'never silently re-dated' "
        "means the reader can see the date it was actually made for")
    assert "PAST DUE" in md and "UNRESOLVED" in md, \
        "a reader has to reach the table to learn the claims are stale"


def test_a_future_prediction_is_pending_not_expired():
    """POSITIVE CONTROL.

    A guard that stamped EXPIRED on everything would pass every assertion above
    while destroying the file's meaning. Take the real record and move only its
    date forward: the verdict must change.
    """
    r = dict(_real_records()[0])
    r["prediction_date"] = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
    for f in gp._RESOLUTION_FIELDS:
        r.pop(f, None)
    state, detail = gp._resolution_state(r)
    assert state == gp.PENDING, f"a prediction due in 30 days reads as {state}: {detail}"


def test_a_resolved_prediction_is_scored_not_expired():
    """Second positive control: resolution must beat the calendar.

    A record whose date has passed AND which was scored is not expired — it is
    answered. If this returned EXPIRED, the guard would be a clock, not a check.
    """
    r = dict(_real_expired())
    r["actual_value"] = 431.9
    state, _ = gp._resolution_state(r)
    assert state == gp.SCORED, \
        f"a resolved past-due prediction reads as {state} — resolution is being ignored"


def test_an_undatable_prediction_fails_closed():
    """No date means no way to check it and no way to expire it. It must not
    read as current."""
    r = dict(_real_records()[0])
    r["prediction_date"] = ""
    for f in gp._RESOLUTION_FIELDS:
        r.pop(f, None)
    state, detail = gp._resolution_state(r)
    assert state == gp.EXPIRED, f"an undatable claim reads as {state}"
    assert "no usable prediction_date" in detail


def test_the_stray_backtick_is_gone():
    """`- **Prediction date:** 2026-07-20\\`` shipped publicly for weeks."""
    src = (REPO / "github_publisher.py").read_text(encoding="utf-8")
    assert "{h.get('prediction_date', '?')}`" not in src, \
        "the unbalanced backtick after prediction_date is still there"
