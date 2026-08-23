#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_language_purity.py — THE RATIO ALARMS ONCE, ON ENOUGH EVIDENCE.

The drift ran for six days in plain sight. Every verdict was on disk and
readable, and nobody read them, because reading a journal is something you do
once you are already suspicious. A ratio changes on its own.

Nothing here touches the live journal, the live quarantine file, or Telegram:
every path is a tmp_path and the sender is injected.

    venv/Scripts/python.exe -m pytest test/test_language_purity.py -v
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import language_gate as lg  # noqa: E402

RU = ("Показателята оставя без изменений за 48 дней подряд, что указывает на "
      "возможную замръзнала сензор.")
EN = ("The indicator has not moved for 48 days, which suggests a frozen sensor "
      "rather than a stable quantity.")

NOW = datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


def _journal(tmp_path, rows, name="j.jsonl"):
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    return path


def _mix(clean, dirty, kind="constancy", age_hours=1):
    ts = (NOW - timedelta(hours=age_hours)).isoformat()
    return ([{"ts": ts, "kind": kind, "summary": EN} for _ in range(clean)]
            + [{"ts": ts, "kind": kind, "summary": RU} for _ in range(dirty)])


class _Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, subject, detail):
        self.calls.append((subject, detail))


# ── the ratio itself ────────────────────────────────────────────────────────

def test_the_ratio_is_clean_over_total(tmp_path):
    path = _journal(tmp_path, _mix(30, 10))
    ratio, total = lg.purity_ratio(24, path, now=NOW)
    assert total == 40
    assert ratio == pytest.approx(0.75)


def test_rows_outside_the_window_are_not_counted(tmp_path):
    path = _journal(tmp_path, _mix(10, 0, age_hours=1) + _mix(0, 90, age_hours=48))
    ratio, total = lg.purity_ratio(24, path, now=NOW)
    assert total == 10 and ratio == 1.0


def test_an_empty_window_is_not_a_ratio_of_zero(tmp_path):
    path = _journal(tmp_path, _mix(5, 5, age_hours=100))
    ratio, total = lg.purity_ratio(24, path, now=NOW)
    assert ratio is None and total == 0, (
        "an idle night must not read as a total language failure")


def test_rows_without_a_lang_field_are_judged_at_read_time(tmp_path):
    """So the window is comparable across the day the gate shipped."""
    path = _journal(tmp_path, _mix(5, 5))
    assert lg.purity_ratio(24, path, now=NOW)[0] == pytest.approx(0.5)


def test_a_stored_verdict_is_used_when_present(tmp_path):
    ts = (NOW - timedelta(hours=1)).isoformat()
    path = _journal(tmp_path, [
        {"ts": ts, "kind": "k", "summary": EN, "lang": {"ok": False}},
        {"ts": ts, "kind": "k", "summary": EN, "lang": {"ok": True}},
    ])
    assert lg.purity_ratio(24, path, now=NOW)[0] == pytest.approx(0.5)


def test_the_breakdown_names_the_call_site_to_look_at(tmp_path):
    path = _journal(tmp_path, _mix(0, 24, kind="constancy")
                    + _mix(10, 0, kind="cycle_plan"))
    by = lg.purity_by_kind(24, path, now=NOW)
    assert by["constancy"] == {"clean": 0, "total": 24, "ratio": 0.0}
    assert by["cycle_plan"]["ratio"] == 1.0


# ── the two cases the brief names ───────────────────────────────────────────

def test_ratio_half_with_forty_entries_writes_once_and_alarms_once(tmp_path):
    path = _journal(tmp_path, _mix(20, 20))
    q = tmp_path / "language_quarantine.json"
    sender = _Sender()

    res = lg.check_purity(24, path, q, sender=sender, now=NOW)

    assert res["verdict"] == "BELOW_FLOOR"
    assert res["ratio"] == pytest.approx(0.5)
    assert res["n_total"] == 40
    assert res["written"] is True and q.exists()
    assert res["alarmed"] is True
    assert len(sender.calls) == 1

    blob = json.loads(q.read_text(encoding="utf-8"))
    assert blob["ratio"] == pytest.approx(0.5)
    assert blob["window_hours"] == 24
    assert blob["n_total"] == 40
    assert blob["by_kind"]["constancy"]["total"] == 40


def test_ratio_half_with_ten_entries_writes_nothing_and_alarms_not(tmp_path):
    path = _journal(tmp_path, _mix(5, 5))
    q = tmp_path / "language_quarantine.json"
    sender = _Sender()

    res = lg.check_purity(24, path, q, sender=sender, now=NOW)

    assert res["verdict"] == "INSUFFICIENT_SAMPLE"
    assert res["n_total"] == 10
    assert res["written"] is False
    assert res["alarmed"] is False
    assert sender.calls == []
    assert not q.exists(), "a quarantine file was written on an anecdote"


# ── the rate limit ──────────────────────────────────────────────────────────

def test_a_second_cycle_the_same_night_does_not_ring_again(tmp_path):
    path = _journal(tmp_path, _mix(20, 20))
    q = tmp_path / "language_quarantine.json"
    sender = _Sender()

    lg.check_purity(24, path, q, sender=sender, now=NOW)
    later = lg.check_purity(24, path, q, sender=sender,
                            now=NOW + timedelta(hours=3))

    assert len(sender.calls) == 1, "the same fact rang twice in one night"
    assert later["alarmed"] is False
    assert "rate-limited" in later["why"]
    assert later["written"] is True, (
        "the file must keep being refreshed even while the alarm is held")


def test_after_twenty_four_hours_it_rings_again(tmp_path):
    q = tmp_path / "language_quarantine.json"
    sender = _Sender()

    lg.check_purity(24, _journal(tmp_path, _mix(20, 20)), q,
                    sender=sender, now=NOW)
    # A DAY LATER NEEDS A DAY'S FRESH EVIDENCE. Reusing the first fixture put
    # every row 26 hours in the past, outside the window, so the second call
    # read INSUFFICIENT_SAMPLE and the test was asserting against a fixture
    # artefact rather than against the rate limit.
    later = NOW + timedelta(hours=25)
    fresh = [{"ts": (later - timedelta(hours=1)).isoformat(),
              "kind": "constancy", "summary": (EN if i % 2 else RU)}
             for i in range(40)]
    lg.check_purity(24, _journal(tmp_path, fresh, "j2.jsonl"), q,
                    sender=sender, now=later)
    assert len(sender.calls) == 2


def test_the_stamp_is_read_before_it_is_overwritten(tmp_path):
    """The bug this guards: writing the file first resets the rate limit."""
    path = _journal(tmp_path, _mix(20, 20))
    q = tmp_path / "language_quarantine.json"
    sender = _Sender()
    lg.check_purity(24, path, q, sender=sender, now=NOW)
    first = json.loads(q.read_text(encoding="utf-8"))["last_alarm_at"]
    lg.check_purity(24, path, q, sender=sender, now=NOW + timedelta(hours=1))
    assert json.loads(q.read_text(encoding="utf-8"))["last_alarm_at"] == first


# ── it must never cost a cycle ──────────────────────────────────────────────

def test_a_clean_window_says_ok_and_does_nothing(tmp_path):
    path = _journal(tmp_path, _mix(40, 0))
    q = tmp_path / "language_quarantine.json"
    sender = _Sender()
    res = lg.check_purity(24, path, q, sender=sender, now=NOW)
    assert res["verdict"] == "OK" and not sender.calls and not q.exists()


def test_one_dirty_in_forty_is_still_below_the_floor(tmp_path):
    """2.5% is over the 2% the floor allows. The 17 Aug transition would have
    crossed it inside one cycle."""
    path = _journal(tmp_path, _mix(39, 1))
    res = lg.check_purity(24, path, tmp_path / "q.json",
                          sender=_Sender(), now=NOW)
    assert res["verdict"] == "BELOW_FLOOR"


def test_a_sender_that_raises_does_not_kill_the_check(tmp_path):
    def _boom(subject, detail):
        raise RuntimeError("telegram is down")
    res = lg.check_purity(24, _journal(tmp_path, _mix(20, 20)),
                          tmp_path / "q.json", sender=_boom, now=NOW)
    assert res["verdict"] == "BELOW_FLOOR"
    assert res["alarmed"] is False
    assert "alarm failed" in res["why"]


def test_an_unreadable_journal_does_not_raise(tmp_path):
    res = lg.check_purity(24, tmp_path / "absent.jsonl", tmp_path / "q.json",
                          sender=_Sender(), now=NOW)
    assert res["verdict"] == "INSUFFICIENT_SAMPLE"


# ── wiring ──────────────────────────────────────────────────────────────────

def test_the_runner_calls_it_at_the_cycle_report():
    src = (REPO / "fast_cycle_runner.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "check_purity" in code, "the ratio is computed by nobody"
    report_at = code.index('beat("cycle_report"')
    assert code.index("check_purity", report_at) > report_at


def test_it_uses_the_one_existing_path_to_the_phone():
    """Not a second notification channel — the one COMMAND 23 reserved."""
    src = (REPO / "core" / "language_gate.py").read_text(encoding="utf-8")
    assert "supervisor.alarm_human" in src
    assert "level=supervisor.ALARM" in src
    assert "sendMessage" not in src and "requests.post" not in src
