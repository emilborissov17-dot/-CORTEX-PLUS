#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test/test_brain_relay.py — THE BRAIN ASKED FOR A HUMAN AND NOBODY WAS TOLD.

WHAT WENT WRONG (20 August 2026, 19:03:32)
-------------------------------------------
The brain wrote its own autopsy into memory/brain_journal.jsonl:

    "failure": true, "cause": "CLOUD_BACKEND_FAILURE",
    "transient": false, "halt_and_call_human": true

It asked for a person. The line sat in a 250-row JSONL file that nothing tails,
and the cycle stayed dead until it was found by hand hours later.

AND THE VERDICT ARRIVED TRUNCATED
----------------------------------
core/brain.py capped summary at 400 characters and put only {role, model} in
payload, so the structured verdict survived on disk as JSON cut off mid-string:

    ..."remedy": "Провери статуса на локалния qwen3:8b и опреде

salvage_fields keeps COMPLETE key/value pairs only. A half-read value is worse
than a missing one because it looks whole.

THE TWO PROOFS, both against the REAL journal:
  * test_tonights_truncated_autopsy_escalates
  * test_cold_start_does_not_fire_250_rows_of_history

    venv\\Scripts\\python.exe -m pytest test/test_brain_relay.py -v
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core import brain_relay as relay

REPO = pathlib.Path(__file__).resolve().parents[1]
LIVE_JOURNAL = REPO / "memory" / "brain_journal.jsonl"

# Verbatim from memory/brain_journal.jsonl, cut at 400 chars as it is on disk.
TRUNCATED_AUTOPSY = {
    "ts": "2026-08-20T19:03:32.000000+00:00",
    "kind": "autopsy",
    "payload": {"role": "дежурен инженер на цикъла", "model": "qwen3:8b"},
    "summary": ('{"failure": true, "cause": "CLOUD_BACKEND_FAILURE", "why": '
                '"Всички облакови LLM API са недостъпни, останал е само '
                'локалният qwen3:8b (дефектен)", "transient": false, '
                '"retry_after_sec": 0, "halt_and_call_human": true, '
                '"remedy": "Провери статуса на локалния qwen3:8b и опреде'),
}


def _journal(tmp_path, rows) -> pathlib.Path:
    p = tmp_path / "brain_journal.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def _capture():
    sent = []

    def sender(text, escalation):
        sent.append({"text": text, "escalation": escalation})
        return True
    return sent, sender


# ---------------------------------------------------------------------------
# (a) THE FIRST PROOF — tonight's truncated autopsy escalates
# ---------------------------------------------------------------------------

def test_tonights_truncated_autopsy_escalates():
    bucket, why, fields = relay.classify(TRUNCATED_AUTOPSY)

    assert bucket == relay.IMMEDIATE, (
        f"\n  THE BRAIN ASKED FOR A HUMAN AND THE RELAY FILED IT AS {bucket}.\n"
        f"  This is the literal row from 19:03:32 on 20 August, truncated\n"
        f"  exactly as it sits on disk. It carries halt_and_call_human: true.\n"
    )
    assert why == "halt_and_call_human"
    assert relay.asks_for_a_human(fields) == "halt_and_call_human"


def test_the_same_row_in_the_live_journal_escalates():
    """Not a fixture — the actual file on this machine."""
    rows = relay.read_journal(LIVE_JOURNAL)
    target = [r for r in rows if str(r.get("ts", "")).startswith("2026-08-20T19:03:32")]
    if not target:
        pytest.skip("the 19:03:32 autopsy has rotated out of the journal")

    bucket, why, fields = relay.classify(target[0])
    assert bucket == relay.IMMEDIATE
    assert why == "halt_and_call_human"
    assert fields["cause"] == "CLOUD_BACKEND_FAILURE"


def test_salvage_keeps_only_complete_pairs():
    """The last field is cut mid-string and must NOT be half-reported."""
    fields = relay.salvage_fields(TRUNCATED_AUTOPSY)

    assert fields["failure"] is True
    assert fields["transient"] is False
    assert fields["halt_and_call_human"] is True
    assert fields["cause"] == "CLOUD_BACKEND_FAILURE"
    assert "remedy" not in fields, (
        "the truncated 'remedy' value was reported as if it were whole"
    )


def test_a_row_written_after_the_fix_uses_payload_fields():
    """The write side now carries the full dict. No scraping needed."""
    row = {"ts": "t", "kind": "autopsy", "summary": "cut off...",
           "payload": {"model": "m", "fields": {"failure": True,
                                                "transient": False,
                                                "remedy": "the whole sentence"}}}
    fields = relay.salvage_fields(row)
    assert fields["remedy"] == "the whole sentence"
    assert relay.asks_for_a_human(fields) == "failure=true, transient=false"


def test_the_write_side_was_actually_fixed():
    """A relay that salvages perfectly while the writer keeps truncating has
    fixed the symptom."""
    src = (REPO / "core" / "brain.py").read_text(encoding="utf-8")
    assert '"fields": fields' in src, (
        "core/brain.py still puts only {role, model} into payload"
    )


# ---------------------------------------------------------------------------
# (b) THE SECOND PROOF — cold start
# ---------------------------------------------------------------------------

def test_cold_start_does_not_fire_250_rows_of_history(tmp_path):
    rows = relay.read_journal(LIVE_JOURNAL)
    if len(rows) < 50:
        pytest.skip("the live journal is too short to make the point")

    sent, sender = _capture()
    result = relay.relay(journal_path=LIVE_JOURNAL,
                         cursor_path=tmp_path / "cursor.json", sender=sender)

    assert len(sent) <= relay.COLD_START_TAIL + 1, (
        f"\n  A COLD START SENT {len(sent)} MESSAGES.\n"
        f"  The journal holds {len(rows)} rows. A relay that has never run must\n"
        f"  not replay the archive at the operator; after the first flood the\n"
        f"  channel is muted and the next real autopsy is muted with it.\n"
    )
    assert result["cold_start"] is True
    assert result["cold_start_skipped"] == len(rows) - relay.COLD_START_TAIL


def test_the_skipped_history_is_reported_not_merely_silent(tmp_path):
    sent, sender = _capture()
    result = relay.relay(journal_path=LIVE_JOURNAL,
                         cursor_path=tmp_path / "cursor.json", sender=sender)
    assert result["cold_start_skipped"] > 0
    cur = json.loads((tmp_path / "cursor.json").read_text(encoding="utf-8"))
    assert cur["cold_start_skipped"] == result["cold_start_skipped"]


def test_the_second_run_is_not_a_cold_start(tmp_path):
    cursor = tmp_path / "cursor.json"
    sent, sender = _capture()
    relay.relay(journal_path=LIVE_JOURNAL, cursor_path=cursor, sender=sender)
    first = len(sent)

    result = relay.relay(journal_path=LIVE_JOURNAL, cursor_path=cursor,
                         sender=sender)
    assert result["cold_start"] is False
    assert len(sent) == first, "the second run re-sent what it had already sent"


# ---------------------------------------------------------------------------
# (c) Routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind", sorted(relay.IMMEDIATE_KINDS))
def test_the_immediate_kinds_go_alone(kind, tmp_path):
    sent, sender = _capture()
    relay.relay(journal_path=_journal(tmp_path, [{"ts": "t", "kind": kind,
                                                  "summary": "{}"}]),
                cursor_path=tmp_path / "c.json", sender=sender)
    assert len(sent) == 1
    assert kind in sent[0]["text"]


def test_constancy_is_digested_not_sent_one_by_one(tmp_path):
    """constancy alone is 192 of the 250 rows. One message per row would train
    the operator to ignore the channel, and the autopsy would go with it."""
    rows = [{"ts": f"t{i}", "kind": "constancy",
             "summary": json.dumps({"reading": f"r{i}"})} for i in range(30)]
    cursor = tmp_path / "c.json"
    cursor.write_text(json.dumps({"initialised": True, "sent_hashes": []}),
                      encoding="utf-8")   # not a cold start: all 30 are new
    sent, sender = _capture()
    relay.relay(journal_path=_journal(tmp_path, rows),
                cursor_path=cursor, sender=sender)

    assert len(sent) == 1, f"{len(sent)} messages for 30 digest rows"
    assert "30" in sent[0]["text"]
    assert sent[0]["escalation"] is False


def test_an_escalation_inside_a_digest_kind_still_goes_immediately(tmp_path):
    """The flag outranks the kind. A constancy row that asks for a human is not
    a digest item."""
    rows = [{"ts": "t", "kind": "constancy",
             "summary": json.dumps({"reading": "x", "halt_and_call_human": True})}]
    sent, sender = _capture()
    result = relay.relay(journal_path=_journal(tmp_path, rows),
                         cursor_path=tmp_path / "c.json", sender=sender)

    assert result["immediate"] == 1
    assert result["digest_rows"] == 0
    assert sent[0]["escalation"] is True


def test_failure_true_with_transient_false_escalates(tmp_path):
    rows = [{"ts": "t", "kind": "constellation",
             "summary": json.dumps({"failure": True, "transient": False})}]
    sent, sender = _capture()
    result = relay.relay(journal_path=_journal(tmp_path, rows),
                         cursor_path=tmp_path / "c.json", sender=sender)
    assert result["immediate"] == 1
    assert sent[0]["escalation"] is True


def test_a_transient_failure_does_not_escalate(tmp_path):
    """It will clear by itself. Waking someone for it is how alarms get muted."""
    rows = [{"ts": "t", "kind": "constancy",
             "summary": json.dumps({"failure": True, "transient": True})}]
    sent, sender = _capture()
    result = relay.relay(journal_path=_journal(tmp_path, rows),
                         cursor_path=tmp_path / "c.json", sender=sender)
    assert result["immediate"] == 0
    assert sent[0]["escalation"] is False


def test_escalations_bypass_quiet_hours():
    """The bypass is carried by trigger=MANUAL into supervisor.alarm_human,
    which is the only path to the phone."""
    import inspect
    src = inspect.getsource(relay._default_sender)
    assert 'trigger="MANUAL" if escalation else None' in src


# ---------------------------------------------------------------------------
# (d) The cursor
# ---------------------------------------------------------------------------

def test_the_cursor_does_not_advance_when_the_send_fails(tmp_path):
    """Otherwise a Telegram outage silently eats the autopsy it was carrying."""
    rows = [{"ts": "t", "kind": "autopsy", "summary": json.dumps({"cause": "X"})}]
    journal = _journal(tmp_path, rows)
    cursor = tmp_path / "c.json"

    result = relay.relay(journal_path=journal, cursor_path=cursor,
                         sender=lambda text, esc: False)
    assert result["failed"], "a failed send was not recorded"
    assert json.loads(cursor.read_text(encoding="utf-8")).get("sent_hashes") == []

    sent, sender = _capture()
    relay.relay(journal_path=journal, cursor_path=cursor, sender=sender)
    assert len(sent) == 1, "the row lost after a failed send was never retried"


def test_the_same_row_is_not_sent_twice(tmp_path):
    rows = [{"ts": "t", "kind": "autopsy", "summary": json.dumps({"cause": "X"})}]
    journal = _journal(tmp_path, rows)
    cursor = tmp_path / "c.json"
    sent, sender = _capture()

    relay.relay(journal_path=journal, cursor_path=cursor, sender=sender)
    relay.relay(journal_path=journal, cursor_path=cursor, sender=sender)
    assert len(sent) == 1


def test_dedup_is_by_content_not_by_line_number(tmp_path):
    """The journal is appended to by several writers; a row can be re-emitted."""
    row = {"ts": "t", "kind": "autopsy", "summary": json.dumps({"cause": "X"})}
    cursor = tmp_path / "c.json"
    sent, sender = _capture()

    relay.relay(journal_path=_journal(tmp_path, [row]), cursor_path=cursor,
                sender=sender)
    relay.relay(journal_path=_journal(tmp_path, [{"ts": "later", **{
        k: v for k, v in row.items() if k != "ts"}}]),
        cursor_path=cursor, sender=sender)
    assert len(sent) == 1, "the same verdict was relayed twice under a new ts"
