#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_proposal_sla.py — THE HUMAN'S DEBT, COUNTED LIKE THE MACHINE'S.

EMIL'S RULING, 21 August 2026: every proposal gets a human answer within 24
hours, approvable from Telegram. The mechanism is built now so the clock is
already running when the amendment vote makes it binding.

WHAT IT REPLACED
-----------------
The system counted what IT owed — unmeasured axes, silent sources, steps that
touched nothing — and never counted what it was OWED. So proposals piled up
where nobody looked. Measured on disk:

    38 quarantined patches      oldest 27.4 days
    18 unresolved improvements
    15 threshold suggestions
    71 open, 39 past the 24-hour promise

THE COUNTER WINS OVER ANY CITATION. The working note said "5 quarantined from
13 July"; an earlier count in this session said 17. Disk says 38, and the
earliest is 25 July — there are NO patches from 13 July at all. Tests assert
against the directory, never against a remembered number.

ONE ESCALATION PER PROPOSAL, EVER. A proposal that pings nightly for 27 days is
how a person learns to ignore the channel, and then the 24-hour promise is
worth less than no promise.

    venv\\Scripts\\python.exe -m pytest test/test_proposal_sla.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

from core import proposal_sla as sla

REPO = pathlib.Path(__file__).resolve().parents[1]
QUARANTINE = REPO / "patches" / "quarantine"


def _epoch(days_ago: float) -> int:
    return int((datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp())


@pytest.fixture
def queue(tmp_path):
    """A small world: one fresh proposal, one long overdue."""
    imp = tmp_path / "improvements.json"
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    imp.write_text(json.dumps({"proposals": [
        {"problem": "fresh one", "timestamp": fresh},
        {"problem": "old one", "timestamp": old},
        {"problem": "already handled", "timestamp": old, "approved": True},
    ]}), encoding="utf-8")

    q = tmp_path / "quarantine"
    q.mkdir()
    (q / f"a_patch.{_epoch(10)}.py").write_text("x", encoding="utf-8")

    thr = tmp_path / "thresholds.json"
    thr.write_text(json.dumps({"ts": old, "proposals": [
        {"axis": "A", "suggested": 1.0, "basis": "rationale"},
        {"axis": "B", "suggested": None, "basis": "none"},
    ]}), encoding="utf-8")

    return dict(improvements_path=imp, quarantine_dir=q, thresholds_path=thr)


def _capture():
    sent = []
    return sent, lambda pid, text: sent.append({"id": pid, "text": text})


# ---------------------------------------------------------------------------
# (a) THE PROOF — 25h escalates ONCE, not every cycle
# ---------------------------------------------------------------------------

def test_a_proposal_aged_25h_escalates(tmp_path):
    imp = tmp_path / "i.json"
    when = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    imp.write_text(json.dumps({"proposals": [
        {"problem": "waited a day and an hour", "timestamp": when}]}),
        encoding="utf-8")
    empty = tmp_path / "q"; empty.mkdir()
    thr = tmp_path / "t.json"; thr.write_text("{}", encoding="utf-8")

    sent, sender = _capture()
    result = sla.run(improvements_path=imp, quarantine_dir=empty,
                     thresholds_path=thr, stamp_path=tmp_path / "s.json",
                     sender=sender, queue_path=tmp_path / "queue.json")

    assert len(sent) == 1, f"{len(sent)} messages for one overdue proposal"
    assert "25" in sent[0]["text"] or "1.0 дни" in sent[0]["text"]
    assert result["summary"]["overdue"] == 1


def test_the_same_proposal_does_not_escalate_every_cycle(tmp_path, queue):
    """THE NEGATIVE CONTROL. Remove the stamp check and a 27-day-old patch
    pings every night until the channel is muted."""
    stamp = tmp_path / "s.json"
    sent, sender = _capture()

    qf = tmp_path / "queue.json"
    sla.run(**queue, stamp_path=stamp, sender=sender, queue_path=qf)
    first = len(sent)
    assert first >= 1

    for _ in range(3):
        sla.run(**queue, stamp_path=stamp, sender=sender, queue_path=qf)

    assert len(sent) == first, (
        f"\n  THE SAME PROPOSALS ESCALATED {len(sent)} TIMES ACROSS 4 CYCLES.\n"
        f"  A proposal that pings nightly for 27 days teaches the operator to\n"
        f"  ignore the channel, and then the 24-hour promise is worth less\n"
        f"  than no promise at all.\n"
    )


def test_a_fresh_proposal_does_not_escalate(tmp_path, queue):
    """POSITIVE CONTROL — inside the SLA there is nothing to answer for yet."""
    sent, sender = _capture()
    result = sla.run(**queue, stamp_path=tmp_path / "s.json", sender=sender,
                     queue_path=tmp_path / "queue.json")

    assert not any("fresh one" in s["text"] for s in sent)
    fresh = [r for r in result["rows"] if "fresh" in r["title"]]
    assert fresh and fresh[0]["age_hours"] < sla.SLA_HOURS


# ---------------------------------------------------------------------------
# (b) THE SECOND PROOF — the quarantine, at its true age
# ---------------------------------------------------------------------------

def test_every_quarantined_patch_is_counted_at_its_own_age():
    """Disk truth, not a remembered number."""
    on_disk = sorted(QUARANTINE.glob("*_patch.*.py"))
    rows = sla.quarantined()

    assert len(rows) == len(on_disk), (
        f"counter says {len(rows)}, disk holds {len(on_disk)}"
    )
    assert len(rows) >= 30, (
        "the working note said 5 and an earlier count said 17; the counter "
        "wins, and it is far larger than either"
    )
    for r in rows:
        assert r["age_hours"] and r["age_hours"] > 0
        assert r["age_basis"] in ("timestamp in filename", "file mtime")


def test_the_age_comes_from_the_patch_own_timestamp_not_mtime(tmp_path):
    """A file copy resets mtime. The epoch in the name is the patch's own
    record of when it was written."""
    q = tmp_path / "q"; q.mkdir()
    f = q / f"x_patch.{_epoch(30)}.py"
    f.write_text("x", encoding="utf-8")     # mtime is NOW; the name says 30 days

    row = sla.quarantined(q)[0]
    assert 29 < (row["age_hours"] / 24) < 31, f"{row['age_hours'] / 24} days"
    assert row["age_basis"] == "timestamp in filename"


def test_there_are_no_patches_from_13_july():
    """The citation named 13 July. The earliest on disk is later, and saying so
    is the point of counting rather than quoting."""
    rows = sla.quarantined()
    oldest = max(r["age_hours"] for r in rows) / 24
    earliest = min(datetime.fromisoformat(r["entered"]) for r in rows)

    assert earliest.date() > datetime(2026, 7, 20, tzinfo=timezone.utc).date(), (
        f"earliest quarantined patch is {earliest.date()}"
    )
    assert 20 < oldest < 40, f"oldest is {oldest:.1f} days"


# ---------------------------------------------------------------------------
# (c) What counts as unresolved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", list(sla.DECIDED_FLAGS))
def test_a_decided_proposal_is_not_counted(tmp_path, flag):
    imp = tmp_path / "i.json"
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    imp.write_text(json.dumps({"proposals": [
        {"problem": "handled", "timestamp": old, flag: True}]}), encoding="utf-8")
    assert sla.improvements(imp) == []


def test_a_threshold_with_no_suggestion_is_not_a_proposal(queue):
    """10 of the 25 axes had nothing to suggest. Counting them would inflate
    the human's debt with rows nobody can answer."""
    rows = sla.thresholds(queue["thresholds_path"])
    assert [r["id"] for r in rows] == ["thr:A"]


def test_all_three_queues_are_counted(queue):
    rows = sla.all_open(**queue)
    kinds = {r["kind"] for r in rows}
    assert kinds == {"improvement", "quarantined_patch", "alarm_threshold"}


def test_the_rows_are_ordered_oldest_first(queue):
    rows = sla.all_open(**queue)
    ages = [r["age_hours"] or 0 for r in rows]
    assert ages == sorted(ages, reverse=True)


# ---------------------------------------------------------------------------
# (d) The standing counter
# ---------------------------------------------------------------------------

def test_the_report_line_names_the_count_and_the_oldest():
    line = sla.report_line()
    assert "предложения без отговор" in line
    assert "най-старото" in line
    assert "просрочени" in line


def test_the_counter_reaches_the_cycle_report():
    from core.cycle_report import to_markdown
    md = to_markdown({"ts": "2026-08-21T00:00:00+00:00", "rows": [], "broken": [],
                      "failed": [], "plan": {}, "brain": {}, "log": "",
                      "cycle_start": None})

    assert "## Дългът на човека" in md, (
        "the human's debt has no line in the report — the system lists its own "
        "debts and not yours, which is not modesty, it is an incomplete ledger"
    )
    assert "предложения без отговор" in md


def test_the_live_counter_is_the_disk_truth():
    s = sla.summary()
    assert s["open"] == sum(s["by_kind"].values())
    assert s["by_kind"]["quarantined_patch"] == len(
        sorted(QUARANTINE.glob("*_patch.*.py")))
    assert s["oldest_days"] > 20


def test_the_sla_is_twenty_four_hours():
    """The ruling's number, pinned so it cannot drift."""
    assert sla.SLA_HOURS == 24


def test_the_runner_calls_it():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    assert "core.proposal_sla" in src
    assert '"proposal_sla", "25.38"' in src


def test_the_message_offers_the_telegram_reply_form():
    """approve_reader already turns 'OK <id>' into the action."""
    row = {"id": "imp:3", "kind": "improvement", "title": "x", "age_hours": 30}
    text = sla.message(row)
    assert "OK imp:3" in text
    assert "24 часа" in text


# ---------------------------------------------------------------------------
# (f) ONE MESSAGE PER DELIVERY RUN — the 28-in-two-minutes defect
# ---------------------------------------------------------------------------
# On 22 Aug 2026 the first run to meet a real backlog sent 28 separate Telegram
# messages inside two minutes. Every one of them obeyed "escalate once per
# proposal"; together they were exactly the muted channel that rule exists to
# prevent. The queue now speaks once per run.

def _thirty(tmp_path, n=30):
    """A fake backlog of n proposals, all long overdue, oldest first by age."""
    imp = tmp_path / "i.json"
    imp.write_text(json.dumps({"proposals": [
        {"problem": f"proposal number {i}",
         "timestamp": (datetime.now(timezone.utc)
                       - timedelta(days=2 + i)).isoformat()}
        for i in range(n)]}), encoding="utf-8")
    q = tmp_path / "q"; q.mkdir()
    thr = tmp_path / "t.json"; thr.write_text("{}", encoding="utf-8")
    return dict(improvements_path=imp, quarantine_dir=q, thresholds_path=thr)


def test_thirty_overdue_proposals_send_exactly_one_message(tmp_path):
    sent, sender = _capture()
    result = sla.run(**_thirty(tmp_path), stamp_path=tmp_path / "s.json",
                     sender=sender, queue_path=tmp_path / "queue.json")

    assert result["summary"]["overdue"] == 30
    assert len(sent) == 1, (
        f"\n  {len(sent)} TELEGRAM MESSAGES FOR ONE DELIVERY RUN.\n"
        f"  This is the 22 Aug defect exactly: 28 notifications in two minutes\n"
        f"  is not 28x the pressure of one, it is a muted channel — and the\n"
        f"  24-hour promise dies with the channel.\n")
    assert len(result["escalated"]) == 30, "all 30 must still be marked escalated"


def test_the_digest_carries_the_count_the_five_oldest_and_the_reply_form(tmp_path):
    sent, sender = _capture()
    sla.run(**_thirty(tmp_path), stamp_path=tmp_path / "s.json", sender=sender,
            queue_path=tmp_path / "queue.json")
    text = sent[0]["text"]

    assert "30" in text, "the count is the actual news and it is missing"
    # oldest first: proposal 29 is 31 days old, 25 is 27 days old
    for i in (29, 28, 27, 26, 25):
        assert f"imp:{i}" in text, f"imp:{i} is among the five oldest and is absent"
    assert "imp:0" not in text, "the newest proposal is in the top five"
    assert text.count("imp:") <= sla.DIGEST_TOP + 1, "more than five were listed"
    assert "OK <id>" in text, (
        "a digest that names problems but not the handle to grab them by makes "
        "the human open a laptop")
    assert "още 25" in text, "the 25 not listed are not accounted for"


def test_the_full_list_goes_to_the_file_the_cockpit_reads(tmp_path):
    sent, sender = _capture()
    qf = tmp_path / "queue.json"
    result = sla.run(**_thirty(tmp_path), stamp_path=tmp_path / "s.json",
                     sender=sender, queue_path=qf)

    assert qf.exists(), "the phone got a headline and nothing got the table"
    blob = json.loads(qf.read_text(encoding="utf-8"))
    assert len(blob["rows"]) == 30
    assert blob["summary"]["overdue"] == 30
    assert all(r["overdue"] for r in blob["rows"])
    assert blob["rows"][0]["age_days"] > blob["rows"][-1]["age_days"]
    assert str(qf) in sent[0]["text"], "the message does not say where the rest is"
    assert result["queue_file"] == str(qf)


def test_the_queue_file_is_written_even_when_nothing_escalates(tmp_path, queue):
    """A cockpit that only sees the queue on escalation nights sees it wrong."""
    qf = tmp_path / "queue.json"
    stamp = tmp_path / "s.json"
    sent, sender = _capture()
    sla.run(**queue, stamp_path=stamp, sender=sender, queue_path=qf)
    qf.unlink()
    sla.run(**queue, stamp_path=stamp, sender=sender, queue_path=qf)   # nothing new
    assert len(sent) == 1
    assert qf.exists(), "the second run sent nothing and also recorded nothing"


def test_a_second_run_with_the_same_backlog_is_silent(tmp_path):
    q = _thirty(tmp_path)
    stamp = tmp_path / "s.json"
    sent, sender = _capture()
    sla.run(**q, stamp_path=stamp, sender=sender, queue_path=tmp_path / "qu.json")
    for _ in range(3):
        sla.run(**q, stamp_path=stamp, sender=sender, queue_path=tmp_path / "qu.json")
    assert len(sent) == 1, f"{len(sent)} digests across four runs of one backlog"


def test_a_single_overdue_proposal_keeps_the_per_proposal_message(tmp_path):
    """A digest of one is a worse message than the proposal itself."""
    sent, sender = _capture()
    sla.run(**_thirty(tmp_path, n=1), stamp_path=tmp_path / "s.json",
            sender=sender, queue_path=tmp_path / "queue.json")
    assert len(sent) == 1
    assert "OK imp:0" in sent[0]["text"], "the reply form lost the id"
    assert "най-старите" not in sent[0]["text"]


def test_the_batch_key_changes_when_the_backlog_does(tmp_path):
    a = sla.digest_key(["imp:1", "imp:2"])
    assert a == sla.digest_key(["imp:2", "imp:1"]), "order must not matter"
    assert a != sla.digest_key(["imp:1", "imp:2", "imp:3"]), (
        "a grown backlog reuses the old dedup key and is swallowed as a repeat")
    assert len(sla.digest_key([f"imp:{i}" for i in range(30)])) < 40, (
        "the key is stored in a 20k-char stamp file; 30 ids in a key would "
        "evict the day's dedup memory")


def test_dry_run_writes_nothing_and_sends_nothing(tmp_path):
    qf = tmp_path / "queue.json"
    stamp = tmp_path / "s.json"
    result = sla.run(**_thirty(tmp_path), stamp_path=stamp, dry_run=True,
                     queue_path=qf)
    assert not qf.exists() and not stamp.exists(), (
        "a dry run touched disk")
    # escalated on a dry run is a PREVIEW of what a real run would say — the
    # pre-existing contract, kept: it is what makes --dry-run readable.
    assert len(result["escalated"]) == 30
    assert result["messages_sent"] == 0


# ---------------------------------------------------------------------------
# (g) ALARM-CLASS EVENTS ARE NOT BATCHED
# ---------------------------------------------------------------------------

def test_the_alarm_path_still_sends_one_message_per_event(monkeypatch, tmp_path):
    """An alarm is a thing that just happened; a queue is a standing debt whose
    whole content is its size. Batching the first would be a defect."""
    import supervisor

    posts = []
    monkeypatch.setattr(supervisor, "NOTIFY_CHANNEL", tmp_path / "ch.json")
    (tmp_path / "ch.json").write_text(json.dumps(
        {"channel": "telegram", "token": "t", "chat_id": "1"}), encoding="utf-8")
    monkeypatch.setattr(supervisor, "ALARM_STAMP", tmp_path / "stamp.json")
    monkeypatch.setattr(supervisor, "note_night_event", lambda *a, **k: None)
    monkeypatch.setattr(supervisor, "_quiet_now", lambda: False)

    class _Req:
        @staticmethod
        def post(url, json=None, timeout=None):
            posts.append(json)

    monkeypatch.setitem(sys.modules, "requests", _Req)

    supervisor.alarm_human("wedged step", "daily_analysis is hung",
                           dedup_key="a:1", trigger="AUTO")
    supervisor.alarm_human("disk full", "3% left", dedup_key="a:2", trigger="AUTO")
    assert len(posts) == 2, (
        "two separate alarms arrived as one message; the SLA digest leaked into "
        "the channel every event shares")


def test_only_this_module_batches():
    src = (REPO / "core" / "proposal_sla.py").read_text(encoding="utf-8")
    assert "digest" in src
    sup = (REPO / "supervisor.py").read_text(encoding="utf-8")
    assert "proposal_sla" not in sup, (
        "the supervisor imported the queue's batching; alarms would inherit it")
