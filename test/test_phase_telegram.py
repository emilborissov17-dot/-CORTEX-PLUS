#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_phase_telegram.py — FOUR PHASES, FOUR MESSAGES, NO DUPLICATES.

WHAT WENT WRONG
----------------
alarm_human() deduplicated on date + subject:

    key = f"{today}:{subject[:40]}"

The first guess about this was wrong and the mutation test caught it: because
the subject is "фаза <PHASE>", date+subject IS unique per phase, so one cycle's
four phases do send four messages. The defect is one level up — it is unique
per phase PER DAY, not per cycle.

Six cycles started on 20 August 2026:

    00:04:02 START   02:39:01 RESTART  04:39:01 RESTART
    14:05:14 MANUAL  14:59:34 MANUAL   17:12:54 MANUAL

Under date+subject, the first cycle reports its phases and cycles two through
six report NOTHING — every phase is a same-day duplicate of the one before.
That is precisely a day like today: a cycle dies, you fix something, you run it
again, and the run you are actually watching is the silent one.

The second defect is the quiet window. "ДА НЕ МЕ БУДЯТ" is about the NIGHTLY
cycle, which runs at 03:00 while he sleeps. A cycle started BY HAND is one he
is sitting in front of, waiting for; a phase report delivered tomorrow morning
is useless. Tonight's runs were all manual, all inside quiet hours.

SUPERSEDED 26 Sep 2026 (C4 E, Emil): phase reports are FILES ONLY. Only four
classes reach Telegram (morning_digest, sign_request, new_risks, alarm) and a
phase report is none of them. The tests below now pin that: every phase is
recorded in the night log with cls="phase_report", and nothing is sent — not in
the day, not for a manual run, not for a second cycle.

Nothing here reaches Telegram: requests.post is captured, and NOTIFY_CHANNEL /
ALARM_STAMP / NIGHT_LOG are redirected into tmp_path. That redirection is why
those are module-level constants — see the note above them in supervisor.py.

    venv\\Scripts\\python.exe -m pytest test/test_phase_telegram.py -v
"""
from __future__ import annotations

import json

import pytest

import supervisor

PHASES = ["A_ORIENT", "B_SENSE", "C_SNAPSHOT", "D_SCORE"]
CYCLE = "2026-08-20T20:12:54.766727+03:00"
OTHER_CYCLE = "2026-08-21T03:00:00.000000+03:00"


@pytest.fixture
def phone(monkeypatch, tmp_path):
    """Capture what would have been sent. Redirect every file it writes."""
    sent: list[dict] = []

    monkeypatch.setattr(supervisor, "NOTIFY_CHANNEL", tmp_path / "notify_channel.json")
    monkeypatch.setattr(supervisor, "ALARM_STAMP", tmp_path / "alarm_sent.json")
    monkeypatch.setattr(supervisor, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    supervisor.NOTIFY_CHANNEL.write_text(json.dumps({
        "channel": "telegram", "token": "test-token", "chat_id": "test-chat",
    }), encoding="utf-8")

    class _FakeRequests:
        @staticmethod
        def post(url, json=None, timeout=None, **kw):
            sent.append({"url": url, "json": json})
            class _R:
                status_code = 200

                @staticmethod
                def json():
                    # Telegram's success body; since 25 Sep 2026 alarm_human stamps
                    # a message as sent only on 200 AND ok=true (task #9b).
                    return {"ok": True}
            return _R()

    import sys
    monkeypatch.setitem(sys.modules, "requests", _FakeRequests)
    return sent


@pytest.fixture
def daytime(monkeypatch):
    monkeypatch.setattr(supervisor, "_quiet_now", lambda: False)


@pytest.fixture
def quiet(monkeypatch):
    monkeypatch.setattr(supervisor, "_quiet_now", lambda: True)


def _run_phases(cycle: str, phases=PHASES, trigger: str | None = "MANUAL"):
    return [supervisor.send_phase_debrief(p, cycle, f"CORTEX++ · фаза {p} · OK",
                                          trigger=trigger)
            for p in phases]


# ---------------------------------------------------------------------------
# (a) THE PROOF
# ---------------------------------------------------------------------------

def _night_rows():
    return [json.loads(l) for l in
            supervisor.NIGHT_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_a_cycle_reaching_four_phases_sends_nothing_and_records_four(phone, daytime):
    _run_phases(CYCLE)
    assert len(phone) == 0, f"phase reports reached Telegram: {len(phone)}"
    rows = _night_rows()
    assert len(rows) == 4 and all(r["cls"] == "phase_report" for r in rows)
    for phase in PHASES:
        assert any(phase in r["subject"] for r in rows), f"{phase} never recorded"


def test_every_key_is_refused_not_just_a_duplicate(phone, daytime):
    keys = _run_phases(CYCLE) + _run_phases(OTHER_CYCLE)
    assert len(set(keys)) == 8
    assert len(phone) == 0


def test_the_dedup_key_is_cycle_plus_phase():
    key = f"{CYCLE}:D_SCORE"
    assert supervisor.send_phase_debrief.__doc__
    import inspect
    src = inspect.getsource(supervisor.send_phase_debrief)
    assert 'f"{cycle_id}:{phase}"' in src, src


# ---------------------------------------------------------------------------
# (b) Quiet hours
# ---------------------------------------------------------------------------

def test_a_manual_run_does_not_reopen_the_phone(phone, quiet):
    """MANUAL used to bypass the quiet window for phase reports. A files-only class
    is refused before that check, so a manual run sends nothing either."""
    _run_phases(CYCLE, trigger="MANUAL")
    assert len(phone) == 0


def test_quiet_hours_still_silence_the_nightly_cycle(phone, quiet):
    """NEGATIVE CONTROL for the bypass — it must not silence-break everything.
    Remove the trigger check and this fails."""
    _run_phases(CYCLE, trigger="SCHEDULED")

    assert len(phone) == 0, (
        f"the 03:00 scheduled cycle sent {len(phone)} messages during quiet "
        f"hours — this is the thing Emil explicitly asked not to happen"
    )


def test_the_night_log_records_it_even_when_the_phone_is_silent(phone, quiet):
    """Nothing is lost — it is just not delivered now. The morning report reads
    the night log."""
    _run_phases(CYCLE, trigger="SCHEDULED")
    assert len(phone) == 0

    lines = [json.loads(l) for l in
             supervisor.NIGHT_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 4, f"night log has {len(lines)} of 4 phase events"
    assert all("фаза" in l["subject"] for l in lines)


# ---------------------------------------------------------------------------
# (c) It stays fail-open
# ---------------------------------------------------------------------------

def test_no_channel_configured_is_silent_not_fatal(phone, daytime, monkeypatch,
                                                   tmp_path):
    monkeypatch.setattr(supervisor, "NOTIFY_CHANNEL", tmp_path / "absent.json")
    _run_phases(CYCLE)          # must not raise
    assert len(phone) == 0


def test_a_dead_telegram_api_does_not_take_the_cycle_down(phone, daytime,
                                                          monkeypatch):
    import sys

    class _Boom:
        @staticmethod
        def post(*a, **kw):
            raise RuntimeError("telegram unreachable")

    monkeypatch.setitem(sys.modules, "requests", _Boom)
    _run_phases(CYCLE)          # must not raise


def test_the_record_carries_the_phase_and_the_verdict(phone, daytime):
    supervisor.send_phase_debrief(
        "D_SCORE", CYCLE, "CORTEX++ · фаза D_SCORE · DEGRADED\nКакво: 0 от 173",
        trigger="MANUAL")
    row = _night_rows()[-1]
    text = row["subject"] + "\n" + row["detail"]
    assert "D_SCORE" in text and "DEGRADED" in text and "173" in text
