#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test/test_bootstrap_expires.py — entered trust must run out.

PLAN point 2. Measured 13 Sep 2026: 18 of 20 TRUSTED sources carry clean_streak 0
and cv 0.000 — they never passed the gate, they were written in. Only four
sources in the register have ever accumulated a streak.

The grant is not deleted. Deleting it leaves twenty candidates and no criterion
for any of them. It becomes a contract with an end date, and the end date does the
work, because the finding of this week is that nobody reads: six machines recorded
their own failure honestly and not one sentence was read. A review flag needs a
reader. An expiry needs nobody, and the default outcome of being ignored is losing
the privilege — the only safe direction when the reader is absent.

Every test fails if the thing it names is removed.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import source_lifecycle as sl          # noqa: E402


def _entered(**kw):
    """A record that is TRUSTED without having earned it — the 18."""
    r = {"source_id": "s", "state": sl.TRUSTED, "clean_streak": 0,
         "contradictions": 0, "observations": 0, "refusals": 0,
         "recent_values": [], "cv": 0.0}
    r.update(kw)
    return r


def _earned(**kw):
    return _entered(clean_streak=sl.PROMOTE_AFTER, **kw)


def test_ninety_days_is_pinned():
    assert sl.BOOTSTRAP_DAYS == 90


def test_earned_means_the_streak_and_nothing_else():
    assert sl.earned(_earned()) is True
    assert sl.earned(_entered()) is False
    assert sl.earned(_entered(clean_streak=sl.PROMOTE_AFTER - 1)) is False


def test_a_grant_records_who_when_why_and_until():
    rec = sl.grant_bootstrap(_entered(), "emil", "seeded before the gate existed")
    b = rec["bootstrap"]
    assert b["granted_by"] == "emil" and "seeded" in b["because"]
    granted = sl._parse_ts(b["granted_at"])
    until = sl._parse_ts(b["valid_until"])
    assert (until - granted).days == sl.BOOTSTRAP_DAYS


def test_a_grant_inside_its_term_has_not_expired():
    rec = sl.grant_bootstrap(_entered(), "emil", "why")
    assert sl.bootstrap_expired(rec) is False


def test_a_grant_past_its_term_has_expired():
    rec = sl.grant_bootstrap(_entered(), "emil", "why", days=1)
    later = datetime.now(timezone.utc) + timedelta(days=2)
    assert sl.bootstrap_expired(rec, now=later) is True


def test_no_grant_is_not_expiry():
    """A source that earned its place has no grant, and must not be swept."""
    assert sl.bootstrap_expired(_earned()) is False
    assert sl.bootstrap_expired({}) is False


def test_a_grant_without_an_end_date_counts_as_expired():
    """An open-ended grant is not a contract; treating it as valid forever would
    reintroduce exactly what this replaces."""
    rec = _entered(bootstrap={"granted_at": "2026-01-01T00:00:00+00:00",
                              "granted_by": "x", "because": "y"})
    assert sl.bootstrap_expired(rec) is True


def test_an_expired_grant_lapses_to_candidate_and_says_why(tmp_path):
    st = {"s": sl.grant_bootstrap(_entered(), "emil", "seeded", days=1)}
    later = datetime.now(timezone.utc) + timedelta(days=2)
    moved = sl.expire_bootstraps(state=st, now=later,
                                 ledger=tmp_path / "ledger.jsonl")
    assert st["s"]["state"] == sl.CANDIDATE
    assert len(moved) == 1 and moved[0]["was"] == sl.TRUSTED
    assert "expired" in moved[0]["why"] and "unrenewed" in moved[0]["why"]
    assert st["s"].get("bootstrap_lapsed_at")


def test_a_source_that_earned_its_streak_keeps_trust_and_loses_the_grant(tmp_path):
    """The grant was a loan against evidence. When the evidence arrives, the loan
    is simply closed — demoting here would punish the source for improving."""
    st = {"s": sl.grant_bootstrap(_earned(), "emil", "seeded", days=1)}
    later = datetime.now(timezone.utc) + timedelta(days=2)
    moved = sl.expire_bootstraps(state=st, now=later,
                                 ledger=tmp_path / "ledger.jsonl")
    assert st["s"]["state"] == sl.TRUSTED
    assert "bootstrap" not in st["s"]
    assert moved and "earned in the meantime" in moved[0]["why"]


def test_activity_alone_does_not_renew(tmp_path):
    """THE FORBIDDEN FALLBACK. 326 of 435 ledger events are refusals from sources
    that answered something; answering is not trustworthiness."""
    rec = sl.grant_bootstrap(_entered(), "emil", "seeded", days=1)
    st = {"s": rec}
    sl.observe("s", axis="AX", ok=True, value=1.0, state=st,
               ledger=tmp_path / "obs.jsonl")
    later = datetime.now(timezone.utc) + timedelta(days=2)
    sl.expire_bootstraps(state=st, now=later, ledger=tmp_path / "ledger.jsonl")
    assert st["s"]["state"] == sl.CANDIDATE, (
        "an observation renewed the grant; only a named act may renew it")


def test_backfill_marks_only_the_entered_and_records_the_evidence():
    st = {"entered": _entered(), "earned": _earned(),
          "candidate": {"state": sl.CANDIDATE, "clean_streak": 0}}
    done = sl.backfill_bootstraps(state=st)
    assert [d["source_id"] for d in done] == ["entered"]
    assert "bootstrap" not in st["earned"] and "bootstrap" not in st["candidate"]
    because = st["entered"]["bootstrap"]["because"]
    assert "clean_streak=0" in because and "did not pass the gate" in because
    assert st["entered"]["bootstrap"]["granted_by"] == "unknown", (
        "the register carries no author for these rows; inventing one would be "
        "the same fiction as the entered trust itself")


def test_backfill_is_idempotent():
    st = {"entered": _entered()}
    assert len(sl.backfill_bootstraps(state=st)) == 1
    assert len(sl.backfill_bootstraps(state=st)) == 0


def test_the_live_register_has_the_entered_trust_this_is_about():
    """Against the real file: if this stops being true the guard is describing a
    problem that no longer exists, and should be re-read rather than kept."""
    st = sl.load()
    trusted = [r for r in st.values()
               if isinstance(r, dict) and r.get("state") == sl.TRUSTED]
    entered = [r for r in trusted if not sl.earned(r)]
    assert trusted, "no TRUSTED sources at all — the register moved"
    assert entered, "no entered trust left; this guard has done its job"
