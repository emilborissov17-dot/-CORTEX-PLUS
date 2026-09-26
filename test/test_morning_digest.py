"""
test/test_morning_digest.py — the morning digest (C2c, 26 Sep 2026).

A refusal looks like: an unknown dirty state or a mislabelled proof is NOT a clean
night, and the streak resets with the reason. The forbidden fallbacks: counting a
night twice, counting an unknown as clean, and any other message class slipping
through quiet hours.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import supervisor as sup
from tools import morning_digest as md

CID = "2026-09-26T03:04:01.484682+03:00"


def _night(exit_codes=(0, 0, 0), dirty=None, field=True):
    start = {"event": "start", "cycle_id": CID, "role": "spine", "ts": "2026-09-26T00:04:05Z"}
    if field:
        start["dirty_code"] = dirty or []
    rows = [{"event": "start", "cycle_id": "2026-09-26T02:04:01+03:00#collectors", "role": "collectors",
             "ts": "2026-09-25T23:04:05Z"},
            {"event": "exit", "cycle_id": "2026-09-26T02:04:01+03:00#collectors", "exit_code": exit_codes[0],
             "wall_seconds": 493.9},
            start,
            {"event": "exit", "cycle_id": CID, "exit_code": exit_codes[1], "wall_seconds": 3147.6},
            {"event": "start", "cycle_id": CID + "#edges", "role": "edges", "ts": "2026-09-26T00:59:05Z"},
            {"event": "exit", "cycle_id": CID + "#edges", "exit_code": exit_codes[2], "wall_seconds": 571.2}]
    return md.last_night(rows)


def test_a_clean_night_needs_all_three_exits_the_right_label_and_no_dirt():
    ok, why = md.verdict(_night(), {"label": "2026-09-26"})
    assert ok is True and why == []
    assert "proof labelled 2026-09-25" in md.verdict(_night(), {"label": "2026-09-25"})[1][0]
    assert any("edges: exit 3" in r for r in md.verdict(_night((0, 0, 3)), {"label": "2026-09-26"})[1])
    assert any("DIRTY: a.py" in r for r in md.verdict(_night(dirty=["a.py"]), {"label": "2026-09-26"})[1])
    assert any("UNKNOWN" in r for r in md.verdict(_night(field=False), {"label": "2026-09-26"})[1]), \
        "a start row without dirty_code must not count as clean"


def test_the_streak_moves_once_per_night_and_resets_with_reasons(tmp_path):
    p = tmp_path / "clean.json"
    assert md.update_streak("2026-09-26", True, [], p)["count"] == 1
    assert md.update_streak("2026-09-26", True, [], p)["count"] == 1, "counted twice"
    assert md.update_streak("2026-09-27", True, [], p)["count"] == 2
    d = md.update_streak("2026-09-28", False, ["spine: exit 3"], p)
    assert d["count"] == 0 and d["history"][-1] == {"night": "2026-09-28", "clean": False,
                                                    "reasons": ["spine: exit 3"]}


def test_the_token_warning_under_30_days():
    now = datetime(2026, 9, 26, tzinfo=timezone.utc)
    assert md.token_days("2027-09-24 21:00:00 UTC", now) == 363
    text = md.compose(_night(), {"token_expiration": "2026-10-10 21:00:00 UTC", "label": "2026-09-26"},
                      {"count": 1}, True, [], [], True, 5)
    assert "UNDER 30" in text and "pipeline healthy 1/7" in text


def test_only_the_morning_digest_class_passes_quiet_hours(tmp_path, monkeypatch):
    import requests
    ch = tmp_path / "n.json"
    ch.write_text(json.dumps({"channel": "telegram", "token": "t", "chat_id": "1"}), encoding="utf-8")
    monkeypatch.setattr(sup, "NOTIFY_CHANNEL", ch)
    monkeypatch.setattr(sup, "ALARM_STAMP", tmp_path / "s.json")
    monkeypatch.setattr(sup, "note_night_event", lambda *a, **k: None)
    monkeypatch.setattr(sup, "_quiet_now", lambda: True)

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    assert sup.alarm_human("s", "d", dedup_key="a", cls="morning_digest") == "delivered"
    # C4 E: a files-only class is refused before the quiet window, never "deferred"
    assert sup.alarm_human("s", "d", dedup_key="b", cls="phase_debrief").startswith("refused")
    assert sup.alarm_human("s", "d", dedup_key="c").startswith("refused")
    assert sup.alarm_human("s", "d", dedup_key="e", cls="alarm") == "deferred"
    assert sup.QUIET_HOURS_ALLOWED_CLASSES == ("morning_digest",)


def test_the_retry_sends_only_if_nothing_was_delivered_today(tmp_path):
    log = tmp_path / "log.jsonl"
    assert md.delivered_today("2026-09-26", log) is False
    log.write_text(json.dumps({"day": "2026-09-26", "status": "failed: HTTP 500"}) + "\n", encoding="utf-8")
    assert md.delivered_today("2026-09-26", log) is False
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"day": "2026-09-26", "status": "delivered"}) + "\n")
    assert md.delivered_today("2026-09-26", log) is True


def test_the_proof_is_the_newest_daily_index_commit_not_any_commit():
    commits = [{"sha": "f784", "commit": {"message": "institution0: register forward row F-003 (root 42eb)", "author": {"date": "x"}}},
               {"sha": "72bf", "commit": {"message": "[2026-09-25] Daily index", "author": {"date": "y"}}},
               {"sha": "0ca2", "commit": {"message": "[2026-09-25] WATER_REVIEW update", "author": {"date": "z"}}}]
    assert md.daily_index_commit(commits)["sha"] == "72bf"
    assert md.daily_index_commit(commits[:1]) is None
