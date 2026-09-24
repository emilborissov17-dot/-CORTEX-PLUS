"""
test/test_restart_on_knowledge.py — no restart budget; a restart is gated on knowledge.

Emil's ruling, 24 Sep 2026: the cycle must not die silently, and there is no
restart budget. The rule in supervisor.py:
  * a dead cycle with an EXIT ROW in the witness log (tools/cycle_witness.ps1) is an
    explained death -> restart, with no daily cap, never more than one restart per
    RESTART_MIN_GAP_SEC;
  * a dead cycle with NO exit row -> no restart, CYCLE_DEATH_UNEXPLAINED in the
    ledger with the last blackbox step, and the alarm through alarm_human.

Failure shapes these tests exist to catch, before the happy path:
  * an unexplained death that restarts anyway (the 23-24 Sep loop);
  * a restart counted against a cap nobody set any more (the old budget back);
  * two restarts inside ten minutes;
  * a witness row from ANOTHER cycle, sharing only a recycled pid, explaining this
    death;
  * the unexplained path writing no ledger row, or not calling the alarm.

Everything with an effect (ledger, alarm, lock, heartbeat, state, model release,
spawn) is replaced; nothing here touches memory/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import supervisor as sup  # noqa: E402

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)


def _cfg():
    c = dict(sup.load_config())
    c["max_restarts_per_day"] = None
    return c


def _lock():
    return {"pid": 111, "cycle_id": "c-dead", "started_utc": (NOW - timedelta(hours=1)).isoformat()}


def _stale_heartbeat():
    return {"pid": 222, "cycle_id": "c-dead", "step": "boot", "step_index": "-1",
            "updated_utc": (NOW - timedelta(minutes=40)).isoformat()}


EXIT_ROW = {"event": "exit", "cycle_id": "c-dead", "cycle_pid": 222, "exit_code": 1,
            "exit_code_hex": "0x00000001", "meaning": "killed (taskkill /F or TerminateProcess: "
            "exit code 1 and no traceback at the end of the log)"}


def _decide(state=None, witness_exit=None, cfg=None):
    return sup.decide(NOW, state or {}, _stale_heartbeat(), _lock(), cfg or _cfg(),
                      lock_pid_alive=False, lock_cycle_finished=False,
                      lock_cycle_refused=False, heartbeat_pid_alive=False,
                      witness_exit=witness_exit)


# --------------------------------------------------------------- the pure rule

def test_an_unexplained_death_is_not_restarted():
    a = _decide(witness_exit=None)
    assert a.kind == sup.DEATH_UNEXPLAINED, a
    assert a.kind not in (sup.DEAD_LOCK_RETRY, sup.START, sup.CATCHUP, sup.KILL_RESTART)
    assert "NO exit row" in a.reason


def test_an_explained_death_is_restarted_and_says_how_it_died():
    a = _decide(witness_exit=EXIT_ROW)
    assert a.kind == sup.DEAD_LOCK_RETRY, a
    assert "exit 1" in a.reason and "killed" in a.reason
    assert a.details["witness_exit"] == EXIT_ROW


def test_there_is_no_daily_cap():
    state = {"restarts": {NOW.date().isoformat(): 50}}
    assert _decide(state=state, witness_exit=EXIT_ROW).kind == sup.DEAD_LOCK_RETRY
    for gone in ("restart_cap", "restarts_today", "_cap_text"):
        assert not hasattr(sup, gone), f"the per-day count is back: supervisor.{gone}"


def test_a_number_in_max_restarts_per_day_is_not_read():
    """24 Sep 2026: no per-day count, not even one a human writes into the config."""
    cfg = _cfg(); cfg["max_restarts_per_day"] = 2
    state = {"restarts": {NOW.date().isoformat(): 5}}
    assert _decide(state=state, witness_exit=EXIT_ROW, cfg=cfg).kind == sup.DEAD_LOCK_RETRY
    assert _decide(state=state, witness_exit=EXIT_ROW, cfg=sup.load_config()).kind == sup.DEAD_LOCK_RETRY


def test_never_more_than_one_restart_per_ten_minutes():
    recent = {"last_restart_utc": (NOW - timedelta(minutes=5)).isoformat()}
    held = _decide(state=recent, witness_exit=EXIT_ROW)
    assert held.kind == sup.NOTHING and "minimum gap" in held.reason
    old = {"last_restart_utc": (NOW - timedelta(minutes=11)).isoformat()}
    assert _decide(state=old, witness_exit=EXIT_ROW).kind == sup.DEAD_LOCK_RETRY


def test_the_kill_path_has_no_cap_and_respects_the_gap():
    args = dict(reason="stale", step="x", step_index="1", age=2000, ceil=900, pid=5, cycle_id="k")
    many = {"restarts": {NOW.date().isoformat(): 30}}
    assert sup._kill_or_fail(many, NOW.date().isoformat(), _cfg(), now=NOW, **args).kind == sup.KILL_RESTART
    recent = {"last_restart_utc": (NOW - timedelta(minutes=3)).isoformat()}
    assert sup._kill_or_fail(recent, NOW.date().isoformat(), _cfg(), now=NOW, **args).kind == sup.NOTHING


# --------------------------------------------------------- matching the row

def test_only_a_row_for_the_same_cycle_id_explains_a_death(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    other = {**EXIT_ROW, "cycle_id": "some-other-cycle"}          # same pid, other cycle
    (tmp_path / "witness.jsonl").write_text(json.dumps(other) + "\n", encoding="utf-8")
    assert sup.witness_exit_for("c-dead") is None, "a recycled pid must not explain a death"
    with (tmp_path / "witness.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(EXIT_ROW) + "\n")
    assert sup.witness_exit_for("c-dead") == EXIT_ROW


# ------------------------------------------------ the unexplained-death effects

@pytest.fixture
def effects(tmp_path, monkeypatch):
    rec = {"ledger": [], "deaths": [], "alarms": [], "spawned": [], "state": None, "base": tmp_path}
    monkeypatch.setattr(sup, "CYCLE_LOG_DIR", tmp_path / "cycle_logs")
    monkeypatch.setattr(sup, "SURVIVAL_BASE", tmp_path)
    monkeypatch.setattr(sup.ledger, "append", lambda ev, **kw: rec["ledger"].append((ev, kw)) or {})
    monkeypatch.setattr(sup.ledger, "record_death", lambda **kw: rec["deaths"].append(kw) or {})
    monkeypatch.setattr(sup, "alarm_human", lambda subject, detail, **kw: rec["alarms"].append((subject, detail, kw)))
    monkeypatch.setattr(sup, "spawn_cycle", lambda *a, **k: rec["spawned"].append(a) or 9999)
    monkeypatch.setattr(sup, "clear_lock", lambda: None)
    monkeypatch.setattr(sup.hb, "retire", lambda *a, **k: None)
    monkeypatch.setattr(sup, "save_state", lambda s: rec.__setitem__("state", dict(s)))
    monkeypatch.setattr(sup, "_release_after_death", lambda cid: None)
    monkeypatch.setattr(sup, "log", lambda m: None)
    (tmp_path / "blackbox.jsonl").write_text(
        json.dumps({"utc": "2026-09-25T08:59:05Z", "pid": 222, "step": "cycle", "phase": "start"}) + "\n"
        + json.dumps({"utc": "2026-09-25T08:59:06Z", "pid": 999, "step": "other", "phase": "begin"}) + "\n",
        encoding="utf-8")
    return rec


def test_the_unexplained_path_writes_the_ledger_row_and_raises_the_alarm(effects):
    a = _decide(witness_exit=None)
    out = sup._handle_unexplained_death(a, {}, NOW.date().isoformat(), _cfg())
    assert out is a
    events = [e for e, _ in effects["ledger"]]
    assert sup.ledger.CYCLE_DEATH_UNEXPLAINED in events, effects["ledger"]
    kw = dict(effects["ledger"])[sup.ledger.CYCLE_DEATH_UNEXPLAINED]
    assert kw["cycle_id"] == "c-dead" and kw["last_step"] == "boot"
    assert kw["last_blackbox_step"].startswith("cycle start"), kw
    assert effects["deaths"] and effects["deaths"][0]["cycle_id"] == "c-dead"
    assert len(effects["alarms"]) == 1 and "NO EXPLANATION" in effects["alarms"][0][0]
    assert effects["spawned"] == [], "an unexplained death must not start anything"
    assert effects["state"]["failure"]["kind"] == "death unexplained"
    assert effects["state"]["failure"]["witness_era"] is True
    assert (effects["base"] / "memory" / "survival_state.json").exists(),         "an unexplained death must latch survival mode"


def test_tick_consults_the_witness(tmp_path, monkeypatch, effects):
    """Wiring: tick() must hand the witness row to decide(). Dry run, sandboxed."""
    monkeypatch.setattr(sup, "load_state", lambda: {})
    monkeypatch.setattr(sup, "_clear_stale_failure", lambda s: False)
    monkeypatch.setattr(sup, "read_lock", _lock)
    monkeypatch.setattr(sup.hb, "read", _stale_heartbeat)
    monkeypatch.setattr(sup, "pid_is_our_cycle", lambda pid: False)
    monkeypatch.setattr(sup.ledger, "has_finished", lambda cid: False)
    monkeypatch.setattr(sup.ledger, "was_refused", lambda cid: False)
    monkeypatch.setattr(sup, "read_extraordinary", lambda now: None)
    assert sup.tick(now=NOW, dry_run=True).kind == sup.DEATH_UNEXPLAINED
    (tmp_path / "witness.jsonl").write_text(json.dumps(EXIT_ROW) + "\n", encoding="utf-8")
    assert sup.tick(now=NOW, dry_run=True).kind == sup.DEAD_LOCK_RETRY
