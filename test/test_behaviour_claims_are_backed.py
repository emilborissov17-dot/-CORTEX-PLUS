# -*- coding: utf-8 -*-
"""test/test_behaviour_claims_are_backed.py — prose that asserts behaviour is not evidence.

THE INCIDENT, 19 September 2026. test_heartbeat_coverage's docstring said:

    "the watchdog's per-step ceiling is keyed on that id, so a slow step
     reporting a fast step's number gets killed early"

Every identifier in it was real. The RELATION was invented. supervisor
.ceiling_for() keys on beat["step"] — the NAME — and config/scheduler.json
carries seventeen ceiling keys, all names and zero fractional ids. The sentence
was lifted into a triage report as rank-1 evidence and a whole command was
planned against it before anyone read ceiling_for.

WHAT THIS FILE IS, AND WHAT IT IS NOT.

It is a POPULATION net, the same shape as test/known_failures.txt: the inventory
of behaviour-asserting sentences is frozen in test/behaviour_claims.txt, and any
NEW one is named. That stops the population growing in silence.

It is NOT a truth check, and recording it as one would repeat the original sin.
The watchdog sentence would have passed any existence check — everything it named
existed. Measured the same day: an automated attempt to falsify the 188
foreign-module claims produced 17 flags of which essentially all were false
positives, while the four genuinely false sentences were found only by reading
the code. A scanner is not verification.

KNOWN GAP, stated rather than papered over: the 612 sentences already in the
baseline are UNVERIFIED. Thirty-three were hand-checked on 19 Sep and four were
false. The rest carry no assertion and no audit.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import claim_scan   # noqa: E402

BASELINE = REPO / "test" / "behaviour_claims.txt"


def _accepted() -> dict:
    out = {}
    if not BASELINE.exists():
        return out
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, why = line.partition("#")
        key = key.strip()
        if key:
            out[key] = why.strip()
    return out


# ── the net ─────────────────────────────────────────────────────────────────

def test_no_new_behaviour_claim_without_a_test_or_a_line_in_the_baseline():
    """THE ONE THAT MATTERS.

    A new sentence asserting how the code behaves must either have an assertion
    behind it — in which case it does not need to be here — or be accepted
    explicitly by adding a line to test/behaviour_claims.txt in the same commit.
    What it may not do is appear quietly.
    """
    accepted = _accepted()
    found = claim_scan.scan(REPO)
    new = [h for h in found if h["fp"] not in accepted]
    assert not new, (
        "%d behaviour-asserting sentence(s) are not in %s.\n"
        "Either point at the assertion that fails when each stops being true, or "
        "DELETE the sentence — CLAUDE.md forbids softening it into a vaguer claim. "
        "If the debt is deliberate, run tools/claim_scan.py --write-baseline and "
        "say so in the commit.\n  "
        % (len(new), BASELINE.name)
        + "\n  ".join("%s:%d  %s" % (h["file"], h["line"], h["sentence"][:110])
                      for h in new[:12]))


def test_the_baseline_only_shrinks_unless_a_commit_says_otherwise():
    """A count, so growth is visible even when the fingerprints churn.

    612 on 19 Sep 2026, the day the rule landed. This number moves DOWN as
    sentences get tests or get deleted; it moves up only in a commit that says
    why, exactly like test/known_failures.txt.

    625 on 20 Sep 2026, and the thirteen added are a different kind of entry:
    each NAMES the assertion that goes red when its sentence stops being true.
    The scanner cannot tell a backed sentence from an unbacked one - it finds
    sentences, not proofs - so the two are counted separately below. THE DEBT is
    the unbacked count, and that one still only shrinks.
    """
    accepted = _accepted()
    unbacked = {k: why for k, why in accepted.items()
                if not why.startswith("BACKED:")}
    assert len(unbacked) <= 612, (
        "the UNBACKED claim count grew to %d. A sentence with no assertion "
        "behind it is the debt this file holds; more of them is the population "
        "growing in silence, which is what the net exists to stop."
        % len(unbacked))
    # 630 on 20 Sep, later the same day: the baseline reconciliation added five
    # more, all backed, while the UNBACKED count above did not move at all.
    # 631 on 20 Sep: the OpenClaw wire added one more, backed by the test its
    # docstring belongs to. The UNBACKED count above is still the debt.
    # 635 on 20 Sep: the fetch/judge chain added four, all backed. The
    # UNBACKED count above has not moved all day.
    # 641 on 21 Sep: the observation-record shape added six, all backed.
    # The UNBACKED count above has still not moved.
    assert len(accepted) <= 641, (
        "the accepted-claims baseline grew to %d. Prose that asserts behaviour "
        "is not evidence; a bigger number here means more of it." % len(accepted))


def test_every_baseline_line_is_a_real_fingerprint():
    bad = [k for k in _accepted() if not re.match(r"^[\w./-]+\.py [0-9a-f]{12}$", k)]
    assert not bad, "malformed baseline entries: %r" % bad[:5]


def test_the_scanner_still_recognises_a_behaviour_claim():
    """Mutation guard. If the patterns ever stop matching, the net would pass by
    finding nothing at all — the quietest possible failure."""
    hits = claim_scan.scan(REPO)
    assert len(hits) > 400, (
        "the scanner found only %d claims; it used to find 612, so it has "
        "probably stopped matching rather than the repo having been cleaned"
        % len(hits))


def test_a_rule_or_a_decision_is_not_counted_as_a_behaviour_claim():
    """CLAUDE.md allows decisions and rules freely. If the scanner counted them
    the baseline would be noise and nobody would read it."""
    from claim_scan import NORM, PAST, ENTITY, VERB
    # NOTE on an example this test originally got wrong: "We decided that
    # supervisor.ceiling_for keys on the name" is NOT a decision, it is a
    # behaviour claim wearing one. Prefixing an assertion with "we decided"
    # changes who is speaking, not what is being asserted, and the scanner is
    # right to count it. A real decision says what MUST hold, not what does.
    for allowed in ("A beat must report the id of the boundary it is inside.",
                    "Ceilings must be keyed on the step name, never on the id.",
                    "core/brain.py never writes memory/heartbeat.json — that is the rule."):
        assert NORM.search(allowed) or PAST.search(allowed), (
            "a decision/rule would be counted as a behaviour claim: %r" % allowed)
    claim = "supervisor.ceiling_for reads beat['step'] and returns the ceiling."
    assert ENTITY.search(claim) and VERB.search(claim)
    assert not (NORM.search(claim) or PAST.search(claim))


# ── the two claims whose substance was true, now actually backed ────────────

def test_the_supervisor_staleness_check_reads_step_and_updated_utc():
    """Backs a sentence in test_prev_step_is_not_the_current_step.py whose
    LINE CITATION was false: it said supervisor.py:642-643, which is
    read_extraordinary. The behaviour is real, at 936-937, and now has this."""
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    assert 'heartbeat.get("step")' in src, (
        "the supervisor no longer reads heartbeat['step'] — the staleness check "
        "moved, and the sentence in test_prev_step_is_not_the_current_step is "
        "now describing something that does not happen")
    assert 'heartbeat.get("updated_utc")' in src, (
        "the supervisor no longer reads heartbeat['updated_utc']")


def test_the_runner_calls_proposal_intake_admit():
    """Backs a sentence in test_first_bet.py that cited fast_cycle_runner.py:1600
    — an env-key check. The call is real; the line number was not."""
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "proposal_intake" in src, (
        "the runner no longer reaches proposal_intake, so test_first_bet's "
        "description of the chain is stale")
    assert re.search(r"_pi\.admit|proposal_intake\.admit|\.admit\(", src), (
        "nothing in the runner calls admit()")


def test_the_dashboard_generator_really_is_gone():
    """Backs the DELETION of three sentences in test_dashboard_freshness.py that
    described cortex_dashboard_generator.py in the present tense. It was removed
    on 2026-08-21 in 208e2cf. If it ever comes back, the deletions should be
    revisited rather than left as a silent hole."""
    assert not (REPO / "cortex_dashboard_generator.py").exists(), (
        "cortex_dashboard_generator.py exists again — the sentences deleted from "
        "test_dashboard_freshness.py on 19 Sep 2026 described it, and their "
        "removal should be reconsidered together with whatever brought it back")
