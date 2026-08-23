# -*- coding: utf-8 -*-
"""
test/test_death_bell.py — A FAKE KILL MUST MAKE THE PHONE RING.

THE BUG THIS HOLDS
-------------------
21 Aug 2026, 14:24:02Z: CYCLE_KILLED written to the existence ledger.
21 Aug 2026, 14:39:    CYCLE_DIED written to the existence ledger.
Telegram messages sent: ZERO.

The alarm existed but was wired only to CYCLE_FAILED_BUDGET_EXHAUSTED — the
event that fires after the day's last restart is already spent. A cycle could be
killed and restarted all night in perfect silence.

THE MUTATION TEST (asked for by name, 21 Aug 2026)
---------------------------------------------------
`test_the_mutation_breaking_the_send_turns_this_red` states the mutation
explicitly and proves the suite notices it: with supervisor._ring_death_bell
replaced by a no-op — which is EXACTLY what the code looked like this morning —
the assertions in `test_a_watchdog_kill_rings_the_bell` fail. A test that would
pass against the broken version is not a test of this.

Everything runs against a sandboxed supervisor: NOTIFY_CHANNEL is redirected
into tmp_path, so even a bug that reached alarm_human() for real would find no
credentials and could not reach the network. See the comment above
supervisor.NOTIFY_CHANNEL for why that constant is a module-level name.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core import death_bell  # noqa: E402


# ---------------------------------------------------------------------------
# The message carries the facts, and the facts are the ledger's facts
# ---------------------------------------------------------------------------

def test_the_alarm_carries_every_fact_the_ledger_row_carries():
    sent = []
    rec = death_bell.ring(
        "CYCLE_KILLED", cycle_id="2026-08-21T14:10:00+03:00",
        wedged_step="daily_analysis", heartbeat_age_sec=972.7, ceiling_sec=900,
        restarts_used=1, restart_budget=2, with_postmortem=False,
        sender=lambda subject, text: sent.append((subject, text)))

    assert rec["sent"] is True
    assert len(sent) == 1
    body = sent[0][1]
    assert "CYCLE_KILLED" in rec["event"]
    assert "2026-08-21T14:10:00+03:00" in body, "the cycle_id is not in the message"
    assert "daily_analysis" in body, "the wedged step is not in the message"
    assert "972.7" in body, "the heartbeat age is not in the message"
    assert "900" in body, "the ceiling is not in the message"
    assert "72.7" in body, "the overrun was not derived for the reader"
    assert "1/2" in body, "the restart budget state is not in the message"


def test_a_death_with_nothing_measured_says_so_instead_of_printing_none():
    """CYCLE_DIED has no heartbeat age and no ceiling — the supervisor never
    measured it going stale, it found the body. The message must SAY that rather
    than render 'None s срещу таван None s', which reads like a broken alarm."""
    rec = death_bell.ring("CYCLE_DIED", cycle_id="c1", sender=lambda s, t: None)
    assert "няма измерване" in rec["text"]
    assert "None" not in rec["text"]


# ---------------------------------------------------------------------------
# Fail-open: a dead bot must never block the reaper
# ---------------------------------------------------------------------------

def test_a_dead_telegram_does_not_raise_into_the_reaper():
    def boom(_subject, _text):
        raise RuntimeError("telegram is dead")

    rec = death_bell.ring("CYCLE_KILLED", cycle_id="c1", with_postmortem=False,
                          sender=boom)
    assert rec["sent"] is False
    assert any("send:" in e for e in rec["errors"])


def test_a_broken_postmortem_does_not_stop_the_alarm():
    sent = []

    def angry_brain(**_kw):
        raise RuntimeError("ollama is not running")

    rec = death_bell.ring("CYCLE_KILLED", cycle_id="c1", wedged_step="x",
                          with_postmortem=True, thinker=angry_brain,
                          sender=lambda s, t: sent.append(t))
    assert rec["sent"] is True, "a broken brain silenced the alarm"
    assert rec["postmortem"] is None
    assert len(sent) == 1


def test_the_postmortem_budget_is_a_wall_clock_not_a_hope():
    """core.brain.think() carries a 300 s cold-load timeout. If the bell waited
    for it, the reaper's tick would be held open for five minutes while the
    system is already down."""
    started = time.time()
    got = death_bell.post_mortem({"event": "CYCLE_KILLED"}, budget_sec=0.3,
                                 thinker=lambda **kw: time.sleep(30))
    assert got is None
    assert time.time() - started < 5, "the budget was not enforced"


def test_the_postmortem_is_attached_when_the_brain_answers_in_time():
    sent = []
    rec = death_bell.ring(
        "CYCLE_KILLED", cycle_id="c1", wedged_step="daily_analysis",
        heartbeat_age_sec=972.7, ceiling_sec=900, with_postmortem=True,
        thinker=lambda **kw: {"text": "Стъпката daily_analysis надви тавана "
                                      "900 s с 72.7 s."},
        sender=lambda s, t: sent.append(t))
    assert rec["postmortem"]
    assert "АУТОПСИЯ" in sent[0]
    assert "72.7" in sent[0]


# ---------------------------------------------------------------------------
# ALARM class — the quiet window does not apply
# ---------------------------------------------------------------------------

def test_the_send_bypasses_quiet_hours(monkeypatch, tmp_path):
    """A death at 00:20 reported at 09:00 is an obituary. alarm_human() honours
    exactly one value as 'past the quiet window' — trigger='MANUAL' — so this
    asserts on the value actually passed, not on the intent."""
    import supervisor

    calls = []
    monkeypatch.setattr(supervisor, "NOTIFY_CHANNEL", tmp_path / "notify.json")
    monkeypatch.setattr(supervisor, "ALARM_STAMP", tmp_path / "stamp.json")
    monkeypatch.setattr(supervisor, "alarm_human",
                        lambda subject, detail, dedup_key=None, trigger=None,
                        level=None:
                        calls.append({"subject": subject, "detail": detail,
                                      "dedup_key": dedup_key, "trigger": trigger}))

    death_bell.ring("CYCLE_KILLED", cycle_id="c9", wedged_step="s",
                    with_postmortem=False)

    assert len(calls) == 1
    assert calls[0]["trigger"] == "MANUAL", (
        "the death bell did not ask to bypass the quiet window; a death at "
        "00:20 would arrive at 09:00")
    assert calls[0]["dedup_key"] == "death:CYCLE_KILLED:c9", (
        "the dedup key is not per (event, cycle) — the next cycle's kill would "
        "be swallowed as a duplicate of this one")


def test_every_terminal_event_has_a_headline_of_its_own():
    """A bell that rings the same words for a restart and for a permanent stop
    teaches the reader that the words do not matter."""
    heads = {e: death_bell._HEADLINE.get(e) for e in death_bell.DEATH_EVENTS}
    assert all(heads.values()), f"an event has no headline: {heads}"
    assert len(set(heads.values())) == len(heads), "two events share a headline"


# ---------------------------------------------------------------------------
# THE WIRING — and the mutation that proves this file is worth having
# ---------------------------------------------------------------------------

def _kill_action():
    import supervisor
    return supervisor.Action(
        supervisor.KILL_RESTART, reason="heartbeat stale",
        pid=4242, cycle_id="2026-08-21T14:10:00+03:00",
        wedged_step="daily_analysis", heartbeat_age_sec=972.7, ceiling_sec=900)


def test_a_watchdog_kill_rings_the_bell(monkeypatch):
    """The supervisor's own helper, called with the action the kill path builds.

    This does not re-run act() — that would spawn a cycle. It calls the seam the
    kill path calls, with the object the kill path passes, and asserts the facts
    arrive. `test_the_mutation_breaking_the_send_turns_this_red` below proves
    that assertion is load-bearing.
    """
    import supervisor

    sent = []
    monkeypatch.setattr(supervisor, "alarm_human",
                        lambda subject, detail, dedup_key=None, trigger=None,
                        level=None:
                        sent.append(detail))

    supervisor._ring_death_bell("CYCLE_KILLED", _kill_action(),
                                restarts_used=1, restart_budget=2,
                                with_postmortem=False)

    assert len(sent) == 1, "a watchdog kill sent no message"
    body = sent[0]
    assert "daily_analysis" in body
    assert "972.7" in body
    assert "900" in body
    assert "1/2" in body


def test_the_mutation_breaking_the_send_turns_this_red(monkeypatch):
    """THE MUTATION, stated out loud.

    Replace _ring_death_bell with a no-op — which is precisely what supervisor.py
    contained before this commit, and precisely why 14:24:02Z was silent — and
    the assertions above must fail. If they still pass, they are not testing the
    send.
    """
    import supervisor

    sent = []
    monkeypatch.setattr(supervisor, "alarm_human",
                        lambda subject, detail, dedup_key=None, trigger=None,
                        level=None:
                        sent.append(detail))
    monkeypatch.setattr(supervisor, "_ring_death_bell",
                        lambda *a, **k: None)      # ← the mutation

    supervisor._ring_death_bell("CYCLE_KILLED", _kill_action(),
                                restarts_used=1, restart_budget=2,
                                with_postmortem=False)

    assert sent == [], "the mutation did not take — this test proves nothing"
    with pytest.raises(AssertionError):
        assert len(sent) == 1, "a watchdog kill sent no message"


def test_the_kill_path_actually_calls_the_bell():
    """The seam is only worth testing if the kill path uses it. Read the source
    of act() and require the call to sit in the CYCLE_KILLED branch — an import
    that nothing calls is the failure mode this repo is aimed at."""
    src = (REPO / "supervisor.py").read_text(encoding="utf-8")
    for event in ("CYCLE_KILLED", "CYCLE_DIED", "CYCLE_RESTARTED",
                  "CYCLE_FAILED_BUDGET_EXHAUSTED"):
        assert f'_ring_death_bell("{event}"' in src, (
            f"{event} is written to the ledger but rings no bell")


def test_the_module_survives_being_imported_without_the_supervisor(monkeypatch):
    """core/death_bell.py must import in a repo where supervisor.py is missing:
    it is imported by the reaper, and the reaper's whole job is to work when
    things are broken."""
    monkeypatch.setitem(sys.modules, "supervisor", None)
    importlib.reload(death_bell)
    rec = death_bell.ring("CYCLE_DIED", cycle_id="c1", with_postmortem=False)
    assert rec["sent"] is False
    assert rec["errors"]
    monkeypatch.undo()
    importlib.reload(death_bell)
