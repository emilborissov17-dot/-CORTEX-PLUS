#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_alarm_levels.py — THE SIREN IS FOR WHAT NEEDS A HUMAN NOW.

Every message out of supervisor.alarm_human() carried "🚨 CORTEX:". Seven
phases of a nightly cycle closing normally arrived as seven sirens, and so did
"EIA still needs a key". A siren that fires for a phase that went fine is a
siren nobody reads by the second week, and then the one that matters arrives
looking exactly like the six that did not.

    ALARM   halt_and_call_human · a red-line threshold · a death · the restart
            budget exhausted
    NOTICE  everything else. The morning is enough.

No network is reachable from these tests: NOTIFY_CHANNEL is repointed into
tmp_path, and alarm_human returns before `import requests` when there are no
credentials there. One test asserts exactly that, since it is the property the
whole file leans on.

    venv/Scripts/python.exe -m pytest test/test_alarm_levels.py -v
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import supervisor as sup  # noqa: E402


@pytest.fixture
def phone(tmp_path, monkeypatch):
    """Credentials that exist, and a requests module that records instead of posting."""
    channel = tmp_path / "notify_channel.json"
    channel.write_text(json.dumps({"channel": "telegram", "token": "t",
                                   "chat_id": "c"}), encoding="utf-8")
    monkeypatch.setattr(sup, "NOTIFY_CHANNEL", channel)
    monkeypatch.setattr(sup, "ALARM_STAMP", tmp_path / "alarm_sent.json")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    monkeypatch.setattr(sup, "_quiet_now", lambda: False)

    posted = []

    class _Requests:
        @staticmethod
        def post(url, json=None, timeout=None):
            posted.append(json or {})

            class _R:
                status_code = 200
            return _R()

    monkeypatch.setitem(sys.modules, "requests", _Requests)
    return posted


def test_an_alarm_keeps_the_siren(phone):
    sup.alarm_human("умря", "cycle died", dedup_key="k1", level=sup.ALARM)
    assert phone[0]["text"].startswith("🚨 CORTEX: ")


def test_a_notice_does_not(phone):
    sup.alarm_human("фаза A_ORIENT", "OK", dedup_key="k2", level=sup.NOTICE)
    assert not phone[0]["text"].startswith("🚨")
    assert phone[0]["text"].startswith("CORTEX · ")


def test_the_default_is_the_loud_one(phone):
    """A caller that forgets must be too loud, never silently quiet."""
    sup.alarm_human("something", "detail", dedup_key="k3")
    assert phone[0]["text"].startswith("🚨 CORTEX: ")


def test_a_phase_debrief_is_always_a_notice(phone):
    sup.send_phase_debrief("A_ORIENT", "cycle-1", "the phase closed OK")
    assert phone[0]["text"].startswith("CORTEX · ")
    assert "🚨" not in phone[0]["text"]


def test_a_notice_is_still_held_through_the_quiet_window(phone, monkeypatch):
    monkeypatch.setattr(sup, "_quiet_now", lambda: True)
    sup.send_phase_debrief("A_ORIENT", "cycle-1", "the phase closed OK")
    assert not phone, "a phase that went fine woke the human at 3am"


def test_every_caller_states_its_level():
    """A siren added by omission is the failure this file exists to stop.

    supervisor.py's own two budget-exhausted calls are the documented ALARM
    default and are allowed to omit it; everything under core/ must say which
    it is, out loud, at the call site.
    """
    missing = []
    for path in sorted((REPO / "core").glob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"supervisor\.alarm_human\((.*?)\)\n",
                                 src, re.S):
            if "level=" not in match.group(1):
                missing.append("{}:{}".format(
                    path.name, src[:match.start()].count("\n") + 1))
    assert not missing, (
        "these calls fall back to the ALARM default without saying so: {}"
        .format(", ".join(missing)))


def test_the_phase_trigger_is_read_and_not_asserted():
    """trigger='MANUAL' was hardcoded, and MANUAL is what bypasses quiet hours."""
    src = (REPO / "core" / "phase_tracker.py").read_text(encoding="utf-8")
    # Comments may quote the old literal — that is the record of why. Only a
    # real call site counts, so the scan drops comment lines first.
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert 'trigger="MANUAL"' not in code, (
        "every phase of every nightly cycle claims to be hand-started again")
    assert "_trigger()" in code


def test_the_trigger_says_manual_only_for_a_hand_started_cycle(tmp_path,
                                                               monkeypatch):
    from core import phase_tracker as pt
    monkeypatch.setattr(pt, "BASE", tmp_path)
    (tmp_path / "memory").mkdir()
    origin = tmp_path / "memory" / "cycle_origin.json"

    origin.write_text(json.dumps({"origin": "supervisor"}), encoding="utf-8")
    assert pt._trigger() is None

    origin.write_text(json.dumps({"origin": "manual"}), encoding="utf-8")
    assert pt._trigger() == "MANUAL"

    origin.write_text("not json", encoding="utf-8")
    assert pt._trigger() is None, "an unreadable origin must fail towards quiet"


def test_no_credentials_means_no_network(tmp_path, monkeypatch):
    """The property every other test here leans on."""
    monkeypatch.setattr(sup, "NOTIFY_CHANNEL", tmp_path / "absent.json")
    monkeypatch.setattr(sup, "NIGHT_LOG", tmp_path / "night_events.jsonl")
    monkeypatch.setattr(sup, "_quiet_now", lambda: False)

    class _Boom:
        @staticmethod
        def post(*a, **k):
            raise AssertionError("a test reached the network")

    monkeypatch.setitem(sys.modules, "requests", _Boom)
    sup.alarm_human("subject", "detail", dedup_key="k", level=sup.ALARM)
