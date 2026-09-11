# -*- coding: utf-8 -*-
"""
test/test_notify_awaits_a_decision.py — the notification asks the tracker what
needs a human, instead of counting statuses itself. (11 September 2026.)

THE DEFECT, in both directions at once. _notify_patches_and_initiatives() did its
own arithmetic over initiative_tracker.run()'s return value:

    prop = sum(... if i["status"] == "PROPOSED")
    prog = sum(... if i["status"] == "IN_PROGRESS")

So it counted IN_PROGRESS — which waits on nobody — into a notification whose
whole purpose is "something needs you", and it never counted OVERDUE at all. An
initiative whose target date has passed is the single case most likely to need a
person, and it was the one case the notification could not mention.

initiative_tracker.awaiting_decision() is the module's own answer: PROPOSED +
OVERDUE, highest priority first. One definition, where the statuses live.

WHAT SILENCE MEANS, and it is the point rather than an edge case: a night whose
initiatives are all IN_PROGRESS has nothing to ask, so nothing is sent. A channel
that rings when there is nothing to decide is a channel people stop reading — the
same reason the deno need is MEDIUM and the repeated-failure alert needs two
nights.
"""
from __future__ import annotations

import pathlib
import re
import sys

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

SRC = (BASE / "fast_cycle_runner.py").read_text(encoding="utf-8-sig")
FN = SRC[SRC.index("def _notify_patches_and_initiatives"):
         SRC.index("def main():")]


def test_the_notifier_asks_the_tracker_not_itself():
    assert "awaiting_decision" in FN, (
        "the notifier no longer calls initiative_tracker.awaiting_decision()")


def test_in_progress_is_never_counted_as_waiting():
    """IN_PROGRESS may be PRINTED as context, but it must not decide whether a
    notification is sent or appear in the body's counts."""
    gate = re.search(r"if not pending_patches and not (\w+):", FN)
    assert gate, "the send gate was restructured — check it by hand"
    assert gate.group(1) == "waiting", (
        f"the send gate is driven by {gate.group(1)!r}; it must be the "
        f"awaiting-a-decision list, or IN_PROGRESS work will ring the channel")


def test_overdue_reaches_the_body():
    """The case the old arithmetic could not express at all."""
    assert "OVERDUE" in FN, "OVERDUE is still invisible to the notification"


def test_the_tracker_still_runs_because_it_is_what_writes_the_files():
    """awaiting_decision() only READS. Dropping the run() call would leave the
    notification describing a state nothing had refreshed."""
    assert "_it_run()" in FN, "initiative_tracker.run() is no longer called"
    assert FN.index("_it_run()") < FN.index("awaiting_decision"), (
        "the tracker must run BEFORE its output is asked for")


# --------------------------------------------------------------------------- #
# behaviour, against the real function
# --------------------------------------------------------------------------- #

def _drive(monkeypatch, patches, active, waiting):
    """Run the real notifier with its four outside edges stubbed, and capture
    what it would have sent."""
    import fast_cycle_runner as R
    import initiative_tracker as IT
    sent = {}
    monkeypatch.setattr(R, "_get_pending_patches", lambda: patches)
    monkeypatch.setattr(IT, "run", lambda: active)
    monkeypatch.setattr(IT, "awaiting_decision", lambda *a, **k: waiting)
    monkeypatch.setattr(R, "_send_windows_toast",
                        lambda title, body: sent.update(title=title, body=body))
    R._notify_patches_and_initiatives()
    return sent


def _init(status, milestone="M", pri="HIGH", date="2026-09-01"):
    return {"id": "i1", "status": status, "milestone": milestone,
            "priority": pri, "target_date": date}


def test_all_in_progress_sends_nothing(monkeypatch):
    """THE SILENCE CASE. Work is under way, nothing is owed a decision."""
    sent = _drive(monkeypatch, [], [_init("IN_PROGRESS")], [])
    assert sent == {}, f"the channel rang with nothing to decide: {sent}"


def test_an_overdue_initiative_rings_and_says_so(monkeypatch):
    sent = _drive(monkeypatch, [], [_init("OVERDUE")], [_init("OVERDUE")])
    assert sent, "an OVERDUE initiative sent nothing"
    assert "OVERDUE" in sent["body"]
    assert "чакат решение" in sent["title"]


def test_a_proposed_initiative_rings(monkeypatch):
    sent = _drive(monkeypatch, [], [_init("PROPOSED")], [_init("PROPOSED")])
    assert sent and "PROPOSED" in sent["body"]


def test_patches_alone_still_ring(monkeypatch):
    """Negative control: the change must not have made patches depend on
    initiatives."""
    sent = _drive(monkeypatch, ["p1", "p2"], [], [])
    assert sent and "patch" in sent["title"]


def test_the_first_line_of_the_body_is_the_highest_priority_one(monkeypatch):
    """awaiting_decision() returns them ranked; the body must take the first
    rather than re-sorting or picking active_initiatives[0] as before."""
    waiting = [_init("OVERDUE", milestone="THE URGENT ONE"),
               _init("PROPOSED", milestone="the other one")]
    sent = _drive(monkeypatch, [], waiting, waiting)
    assert "THE URGENT ONE" in sent["body"]


def test_a_broken_tracker_does_not_stop_the_patch_notification(monkeypatch):
    """FAIL-OPEN, like every other builder in this path."""
    import fast_cycle_runner as R
    import initiative_tracker as IT
    sent = {}
    monkeypatch.setattr(R, "_get_pending_patches", lambda: ["p1"])
    monkeypatch.setattr(IT, "run", lambda: [])

    def boom(*a, **k):
        raise RuntimeError("tracker exploded")
    monkeypatch.setattr(IT, "awaiting_decision", boom)
    monkeypatch.setattr(R, "_send_windows_toast",
                        lambda t, b: sent.update(title=t, body=b))
    R._notify_patches_and_initiatives()
    assert sent and "patch" in sent["title"]
