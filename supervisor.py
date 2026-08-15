#!/usr/bin/env python3
"""
supervisor.py — the system's first autonomy rung: continuous existence.

WHAT THIS IS
------------
A SHORT-LIVED, STATELESS tick, invoked by Windows Task Scheduler every 5 minutes.
It is not a resident daemon.

  schtasks /Create /TN "CORTEX_Supervisor" /SC MINUTE /MO 5 /F ^
           /TR "<repo>\\venv\\Scripts\\python.exe <repo>\\supervisor.py --tick"

Each tick reads on-disk state (last run, heartbeat, lock), decides exactly ONE
action, performs it, records it, and exits.

WHY NOT A RESIDENT SUPERVISOR
-----------------------------
A resident supervisor is the single point of failure that has no supervisor. If
it deadlocks or dies silently at 03:00, the system stops existing and NOTHING is
there to notice or say so — self-defeating for a component whose entire purpose
is "continuous existence, auditable". A fresh process per tick cannot inherit
corruption from the last one, and the OS guarantees re-invocation.

WHY NOT TASK SCHEDULER ALONE
----------------------------
It cannot watch a heartbeat. Its only tool is a blunt "terminate if the task runs
longer than N hours", which cannot tell a cycle legitimately spending 40 minutes
in web_intelligence from one wedged on a dead socket.

So: durability from the OS, intelligence in Python.

THE AUTONOMY BOUNDARY (this is the important part)
--------------------------------------------------
The supervisor STARTS and STOPS the cycle. It does nothing else. It makes NO LLM
call. It cannot form an intention; it can only observe a clock and a file.

It may write exactly: memory/heartbeat.json (never — the cycle owns that),
memory/cycle.lock, memory/existence_ledger.jsonl, memory/scheduler_state.json,
logs/supervisor.log.

It MUST NOT — and is prevented by safety/protected_paths.py from — modifying
itself, its config, the guardian, the gates, or the action policy. It cannot
widen its own restart budget or its own ceilings: those live in
config/scheduler.json, which is protected. A system that can widen its own
restart budget has no restart budget.

Per the OpenClaw ladder its actions are level_2 (local writes, backed up,
rollback-able). It never reaches level_3.

TESTABILITY
-----------
decide() is a PURE FUNCTION of (now, state, heartbeat, lock, config) -> Action.
No clock, no processes, no OS. The entire policy is unit-testable offline, which
is what lets us assert the thing that actually matters: that a healthy 40-minute
web_intelligence step is NEVER killed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from memory import existence_ledger as ledger  # noqa: E402
from memory import heartbeat as hb             # noqa: E402

CONFIG_PATH = BASE / "config" / "scheduler.json"
# THE ALARM CLOCK IS HUMAN-OWNED.
#
# This file may be written by ONE author: approve_reader, and only after Emil has replied
# "OK <id>" in Telegram. The pulse can notice that a cycle looks warranted and it can ASK
# — it cannot write this file. An endogenous trigger that is auto-honoured is not a
# horizontal capability, it is vertical creep wearing a horizontal costume: the system
# would be setting its own alarm clock and then answering it.
#
# Read and CONSUMED on the very next tick — a request that could survive its own reading
# would fire again forever.
EXTRAORDINARY_PATH   = BASE / "memory" / "extraordinary_request.json"
EXTRAORDINARY_MAX_AGE_MIN = 10    # older than this is not a request, it is litter
EXTRAORDINARY_MIN_GAP_H   = 4     # a daily cycle must not become an hourly one
EXTRAORDINARY_AUTHOR = "approve_reader"   # the ONLY accepted author
STATE_PATH  = BASE / "memory" / "scheduler_state.json"
LOCK_PATH   = BASE / "memory" / "cycle.lock"
LOG_PATH    = BASE / "logs" / "supervisor.log"
RUNNER      = BASE / "fast_cycle_runner.py"
PYTHON      = BASE / "venv" / "Scripts" / "python.exe"

# The cycle's own stdout/stderr. Until 2026-07-14 these went to DEVNULL, so the
# only record of a 70-minute run was whatever it happened to write to disk: no
# traceback if it crashed, no LLM backend lines, no finish_reason=length warnings.
# A prediction about tomorrow's cycle was literally unfalsifiable — the evidence
# was being discarded at the moment it was produced.
CYCLE_LOG_DIR   = BASE / "memory" / "cycle_logs"
CYCLE_LOG_KEEP  = 14      # ~two weeks; a cycle log is a few hundred KB


# ---------------------------------------------------------------------------
# Actions — the complete vocabulary of what a tick may do
# ---------------------------------------------------------------------------

NOTHING          = "NOTHING"
START            = "START"
CATCHUP          = "CATCHUP"
SKIP_MISSED      = "SKIP_MISSED"
KILL_RESTART     = "KILL_RESTART"
KILL_BUDGET_DONE = "KILL_BUDGET_EXHAUSTED"
CLEAR_STALE_LOCK = "CLEAR_STALE_LOCK"
# A stale lock left by a cycle that DIED without finishing (no CYCLE_FINISHED on
# record). Distinct from CLEAR_STALE_LOCK, which is reserved for the benign race
# where a cycle finished cleanly but died before unlinking its lock. A death is
# not today's completed run: it is recorded (CYCLE_DIED) and retried, bounded by
# the SAME restart budget that bounds kill-restarts — or, once that budget is
# spent, it fails loudly like any exhausted budget.
DEAD_LOCK_RETRY       = "DEAD_LOCK_CLEARED_RETRY"
DEAD_LOCK_BUDGET_DONE = "DEAD_LOCK_BUDGET_EXHAUSTED"


@dataclass
class Action:
    kind: str
    reason: str = ""
    # populated for kill actions — the WHY, not merely the THAT
    wedged_step: Optional[str] = None
    wedged_step_index: Optional[str] = None
    heartbeat_age_sec: Optional[float] = None
    ceiling_sec: Optional[int] = None
    pid: Optional[int] = None
    cycle_id: Optional[str] = None
    scheduled_for: Optional[str] = None
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config / state
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "daily_hour": 3,
    "catchup_grace_hours": 20,
    "max_restarts_per_day": 2,
    "step_ceilings_sec": {"_default": 900},
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
        except Exception as e:
            log(f"WARNING: config unreadable ({type(e).__name__}: {e}) — using defaults")
    return cfg


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_run_date": None, "last_run_utc": None,
            "restarts": {}, "failure": None}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def ceiling_for(step: Optional[str], cfg: dict) -> int:
    ceilings = cfg.get("step_ceilings_sec", {})
    if step and step in ceilings:
        return int(ceilings[step])
    return int(ceilings.get("_default", 900))


def _autopsy(action) -> str:
    """Ask core.self_diagnosis WHY the cycle died, so the alarm carries a cause and a
    proposed fix instead of a bare symptom. Fail-open: a broken autopsy must never
    stop the alarm from reaching the human. (15 Aug 2026)"""
    try:
        sys.path.insert(0, str(BASE))
        from core.self_diagnosis import diagnose, summary_line
        return summary_line(diagnose(action.wedged_step, action.cycle_id,
                                     getattr(action, "ceiling_sec", None),
                                     getattr(action, "heartbeat_age_sec", None)))
    except Exception as e:
        return f"(автопсията не сработи: {type(e).__name__})"


NIGHT_LOG = BASE / "memory" / "night_events.jsonl"
QUIET_HOURS = (22, 9)      # 22:00-09:00 местно: човекът спи, системата се оправя сама


def _quiet_now() -> bool:
    h = datetime.now().hour
    a, b = QUIET_HOURS
    return h >= a or h < b


def note_night_event(subject: str, detail: str) -> None:
    """Емил, 15 авг 2026: „ДА НЕ МЕ БУДЯТ ... ДАЙ МУ ПЪЛНА АВТОНОМНОСТ ...
    ИСКАМ САМО ДОКЛАДИТЕ ЗА ИЗМИНАЛ ДЕН."

    Затова всичко, което системата преживее нощем, се записва ТУК, а не се
    праща на телефона. Сутрешният отчет (core/cycle_report.py) го чете и го
    разказва в раздел „какво стана през нощта без теб". Нищо не се губи —
    само не звъни в 3 през нощта."""
    try:
        NIGHT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(NIGHT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "subject": subject, "detail": detail},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass


def alarm_human(subject: str, detail: str) -> None:
    """15 Aug 2026 — THE DEAD-SYSTEM ALARM.

    ПРОМЕНЕНО (15 авг, вечер): в тихите часове НЕ буди. Записва събитието за
    сутрешния отчет и се връща. Пътят към телефона остава за деня — и за
    случаите, в които човекът сам е поискал да бъде питан.

    Between 23 and 28 July the restart budget was exhausted ELEVEN times: the system
    was down, and it "called for a human" by writing a line into supervisor.log and a
    block at the top of notes/next_actions.txt — files nobody opens while the thing is
    dead. An alarm nobody hears is not an alarm. This sends it to Telegram, the one
    channel that reaches Emil's pocket, and it does so from the MACHINE (which can
    reach the API; the cloud cannot). Fail-open, never raises, never blocks recovery.
    """
    note_night_event(subject, detail)
    if _quiet_now():
        return                      # спи човекът; сутринта ще прочете всичко
    try:
        cfg = json.loads((BASE / "memory" / "notify_channel.json").read_text(encoding="utf-8"))
        if cfg.get("channel") != "telegram" or not cfg.get("token") or not cfg.get("chat_id"):
            return
        # do not spam: one alarm per subject per day
        stamp = BASE / "memory" / "alarm_sent.json"
        try:
            sent = json.loads(stamp.read_text(encoding="utf-8"))
        except Exception:
            sent = {}
        key = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}:{subject[:40]}"
        if sent.get(key):
            return
        import requests
        requests.post(f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
                      json={"chat_id": cfg["chat_id"],
                            "text": f"🚨 CORTEX: {subject}\n{detail}"[:3500]}, timeout=20)
        sent[key] = True
        stamp.write_text(json.dumps(sent, ensure_ascii=False)[:20000], encoding="utf-8")
    except Exception:
        pass


# ── DIAGNOSED RETRY (15 Aug 2026, Emil: "защо да жертваме цял ден заради 2 сляпи
# рестарта, чиято причина не е отстранена?") ────────────────────────────────────
# The blind-restart budget stays exactly as it was: a system that retries without
# understanding must stop. But a retry that comes WITH a diagnosis of a TRANSIENT
# cause (LLM cooldowns that expire, a source/network blip) is not blind — the cause
# really has cleared by the next tick. So: after the blind budget is spent, the
# supervisor may earn up to DIAGNOSED_RETRY_MAX further attempts, and ONLY when the
# autopsy says the cause is transient. A CODE_ERROR or a full disk is never
# transient and still fails loudly at once — repeating those is the infinite loop
# the budget exists to prevent. This ceiling, like every other, is not self-raisable.
# 15 авг 2026 — пълна автономност: диагностицираните опити вече не са с таван.
# Сляпият бюджет (max_restarts_per_day) си остава за СЛЕПИТЕ рестарти; когато
# мозъкът е дал заземена причина и е преценил, че е преходно, той решава колко
# пъти си струва. Всеки такъв опит се вписва в дневника за сутрешния отчет.
DIAGNOSED_RETRY_MAX = 10**6


def diagnosed_retries_today(state: dict, today: str) -> int:
    return int((state.get("diagnosed_retries") or {}).get(today, 0))


def note_diagnosed_retry(state: dict, today: str) -> None:
    d = state.setdefault("diagnosed_retries", {})
    d[today] = int(d.get(today, 0)) + 1
    save_state(state)


def restarts_today(state: dict, today: str) -> int:
    return int((state.get("restarts") or {}).get(today, 0))


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------

def read_lock() -> Optional[dict]:
    if not LOCK_PATH.exists():
        return None
    try:
        return json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"pid": None, "corrupt": True}


def _log_refusal(why: str) -> None:
    """A refused escalation must be NAMED, not silently dropped: a request that vanishes
    without a reason is indistinguishable from one that was never made."""
    try:
        log(f"extraordinary request REFUSED: {why}")
    except Exception:
        pass


def read_extraordinary(now: Optional[datetime] = None) -> Optional[dict]:
    """The pulse's request, if there is a VALID one. A request must be fresh and must
    NAME a reason: an unnamed or stale request is litter, and litter must never start a
    multi-hour cycle. Returns None for anything malformed — the file is consumed either
    way by consume_extraordinary()."""
    if not EXTRAORDINARY_PATH.exists():
        return None
    try:
        req = json.loads(EXTRAORDINARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(req, dict) or not str(req.get("reason", "")).strip():
        return None
    # AUTHORSHIP IS THE WHOLE POINT — and a CLAIM of authorship is not authorship. The
    # authored_by/approved_by fields are a label; the SIGNATURE is the fence. Only
    # approve_reader holds the signing key, so a request the system wrote for itself
    # fails here no matter how fresh, well-reasoned or correctly-shaped it is.
    if req.get("authored_by") != EXTRAORDINARY_AUTHOR or not str(req.get("approved_by", "")).strip():
        return None
    try:
        from core.request_signing import (verify as _verify_sig,
                                          evidence_digest as _ev_digest,
                                          evidence_complete as _ev_complete)
    except Exception:
        return None                      # no verifier, no honoured request. Fail-closed.
    # THE EQUALITY IS A GUARD, NOT A TEST. Recompute the digest from the RAW evidence
    # rather than trusting the digest supplied with it, then require the signature to
    # cover both. A request whose displayed numbers were edited after approval fails at
    # the first step; one whose digest was edited to match fails at the second.
    ev = req.get("evidence")
    ok_ev, missing = _ev_complete(ev, req.get("keys", []))
    if not ok_ev:
        _log_refusal(f"incomplete evidence (missing {', '.join(missing)})")
        return None
    if _ev_digest(ev) != req.get("evidence_sha256"):
        _log_refusal("evidence digest does not match the raw evidence — displayed and "
                     "signed payloads have diverged")
        return None
    if not _verify_sig(req):
        _log_refusal("signature invalid, missing, or made with another key")
        return None
    now = now or datetime.now().astimezone()
    age_s = _age(now, req.get("ts"))
    if age_s is None or age_s > EXTRAORDINARY_MAX_AGE_MIN * 60 or age_s < -60:
        return None          # stale, undated, or dated in the future
    return req


def consume_extraordinary() -> bool:
    """Delete the request file. Called whether the request STARTED a cycle or was
    refused, and whether it was valid or litter — a request that survives its own
    reading fires again on the next tick, forever."""
    try:
        existed = EXTRAORDINARY_PATH.exists()
        EXTRAORDINARY_PATH.unlink(missing_ok=True)
        return existed
    except Exception:
        return False


def _age_hours(now: datetime, ts: Optional[str]) -> Optional[float]:
    s = _age(now, ts)
    return None if s is None else s / 3600.0


def write_lock(pid: int, cycle_id: str) -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(json.dumps({
        "pid": pid,
        "cycle_id": cycle_id,
        "started_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")


def clear_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def pid_is_our_cycle(pid: Optional[int]) -> bool:
    """True only if `pid` is alive AND is actually a python process running our
    cycle.

    Identity matters, not just liveness: after a hard power loss the OS may have
    recycled the PID onto an unrelated process. Killing whatever happens to hold
    a stale PID would be a serious bug — the supervisor must only ever kill a
    process it can prove is ours.
    """
    if not pid:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except Exception:
        return False

    if not out or "No tasks" in out or str(pid) not in out:
        return False
    # Our cycle runs under the venv python.
    return "python" in out.lower()


def kill_tree(pid: int) -> bool:
    """taskkill /T — the /T is essential.

    The cycle spawns children: yt-dlp, Playwright/Chromium, subprocess calls to
    trend_tracker. Killing only the parent orphans a Chromium that then holds the
    RAM the NEXT cycle needs.
    """
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception as e:
        log(f"kill_tree({pid}) failed: {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------------------
# THE DECISION — a pure function. No clock, no processes, no OS.
# ---------------------------------------------------------------------------

def decide(now: datetime, state: dict, heartbeat: Optional[dict],
           lock: Optional[dict], cfg: dict, lock_pid_alive: bool = False,
           lock_cycle_finished: bool = False,
           extraordinary: Optional[dict] = None) -> Action:
    """What should this tick do? Exactly one thing.

    `lock_pid_alive`, `lock_cycle_finished` and `extraordinary` are passed in rather
    than probed (from the OS, the existence ledger, and the request file respectively),
    so the whole policy stays pure and testable — the same discipline that lets us
    assert a healthy 40-minute web_intelligence step is never killed. Consuming the
    request file is tick()'s job, not this function's.
    """
    today = now.date().isoformat()

    # ── A cycle is (or claims to be) running ────────────────────────────────
    if lock is not None:
        if not lock_pid_alive:
            # A dead pid holding a lock. Now that the runner clears its own lock on
            # a clean exit, a surviving lock means the cycle ended badly — but there
            # are still TWO ways to end badly, and the ledger tells them apart.
            if lock_cycle_finished:
                # The BENIGN race: the runner sealed CYCLE_FINISHED and then died
                # before it could unlink the lock (the seal and the unlink are two
                # steps; a kill can land between them). Its work is DONE. Just clear
                # the orphaned lock — do NOT retry; today's cycle really did run.
                return Action(CLEAR_STALE_LOCK,
                              reason=f"stale lock from a cleanly-finished cycle "
                                     f"(pid={lock.get('pid')} is gone; CYCLE_FINISHED "
                                     f"is on record) — clearing, not retrying",
                              pid=lock.get("pid"), cycle_id=lock.get("cycle_id"))
            # No CYCLE_FINISHED on record: the cycle DIED mid-run — OOM, power loss,
            # an uncaught crash. A death is not a completed run, so it must not
            # satisfy the day. Record it and retry, within the restart budget.
            return _dead_cycle_action(now, state, today, cfg, lock, heartbeat)

        # It is alive. Is it making progress?
        if heartbeat is None:
            # Alive but no proof of life at all. Measure against the default
            # ceiling using the lock's own start time.
            age = _age(now, lock.get("started_utc"))
            ceil = ceiling_for(None, cfg)
            if age is not None and age > ceil:
                return _kill_or_fail(state, today, cfg,
                                     reason="cycle is alive but has never written a heartbeat",
                                     step=None, step_index=None, age=age, ceil=ceil,
                                     pid=lock.get("pid"), cycle_id=lock.get("cycle_id"))
            return Action(NOTHING, reason="cycle just started; no heartbeat yet")

        step = heartbeat.get("step")
        age  = _age(now, heartbeat.get("updated_utc"))
        ceil = ceiling_for(step, cfg)

        if age is None:
            return Action(NOTHING, reason="heartbeat present but unparseable timestamp")

        if age > ceil:
            return _kill_or_fail(state, today, cfg,
                                 reason=f"heartbeat stale: step '{step}' has not beaten for "
                                        f"{age:.0f}s (ceiling {ceil}s)",
                                 step=step, step_index=heartbeat.get("step_index"),
                                 age=age, ceil=ceil,
                                 pid=heartbeat.get("pid") or lock.get("pid"),
                                 cycle_id=heartbeat.get("cycle_id") or lock.get("cycle_id"))

        # Healthy — including a 40-minute web_intelligence step. Do NOT kill it.
        return Action(NOTHING, reason=f"cycle healthy in '{step}' ({age:.0f}s / {ceil}s)")

    # ── No cycle running. Should today's run have happened? ─────────────────
    if state.get("failure", {}) and (state.get("failure") or {}).get("date") == today:
        return Action(NOTHING,
                      reason="restart budget exhausted today — waiting for human "
                             "intervention (see daily report)")

    # ── An EXTRAORDINARY request (from the pulse) ───────────────────────────
    # Deliberately placed AFTER the lock and restart-budget checks and BEFORE the
    # "already ran today" check: a running cycle, a wedged cycle or a spent budget all
    # still veto it, but the whole point of an extraordinary run is that something
    # happened AFTER today's scheduled cycle. Rate-limited hard, because a pulse that
    # can request a cycle whenever its necessity spikes would quietly convert a daily
    # cycle into an hourly one — the budget is what keeps the request a request.
    if extraordinary:
        gap_h = float(cfg.get("extraordinary_min_gap_hours", EXTRAORDINARY_MIN_GAP_H))
        last = _age_hours(now, state.get("last_extraordinary_utc"))
        if last is not None and last < gap_h:
            return Action(NOTHING,
                          reason=f"extraordinary request REFUSED (rate limit): last one was "
                                 f"{last:.1f}h ago, minimum gap is {gap_h:.0f}h "
                                 f"— reason was: {extraordinary.get('reason')}")
        return Action(START, reason="extraordinary: " + str(extraordinary.get("reason")),
                      scheduled_for=now.isoformat(),
                      details={"extraordinary": True,
                               "requested_at": extraordinary.get("ts")})

    if state.get("last_run_date") == today:
        return Action(NOTHING, reason="today's cycle has already run")

    hour = int(cfg.get("daily_hour", 3))
    scheduled = now.replace(hour=hour, minute=0, second=0, microsecond=0)

    if now < scheduled:
        return Action(NOTHING, reason=f"before today's scheduled hour ({hour:02d}:00)")

    # The scheduled hour has passed and we have not run today.
    #
    # NOTE this is deliberately NOT "is it 03:00 right now?" — a machine asleep at
    # 03:00 would miss that forever. We ask "has today's run happened yet?", so
    # catch-up falls out of the same rule instead of being a special case.
    late_by = now - scheduled
    grace = timedelta(hours=float(cfg.get("catchup_grace_hours", 20)))

    if late_by <= timedelta(minutes=10):
        return Action(START, reason=f"scheduled run for {hour:02d}:00",
                      scheduled_for=scheduled.isoformat())

    if late_by <= grace:
        return Action(CATCHUP,
                      reason=f"missed the {hour:02d}:00 run (machine off?) — "
                             f"{late_by.total_seconds()/3600:.1f}h late, within the "
                             f"{grace.total_seconds()/3600:.0f}h grace window",
                      scheduled_for=scheduled.isoformat(),
                      details={"late_by_hours": round(late_by.total_seconds() / 3600, 2)})

    # Too late to be worth starting — a multi-hour cycle begun now collides with
    # tomorrow's. Skipping is logged as loudly as running: a day with no cycle is
    # a fact about the system's existence.
    return Action(SKIP_MISSED,
                  reason=f"missed the {hour:02d}:00 run by "
                         f"{late_by.total_seconds()/3600:.1f}h — past the "
                         f"{grace.total_seconds()/3600:.0f}h grace window; skipping to tomorrow",
                  scheduled_for=scheduled.isoformat(),
                  details={"late_by_hours": round(late_by.total_seconds() / 3600, 2)})


def _kill_or_fail(state, today, cfg, reason, step, step_index, age, ceil, pid, cycle_id) -> Action:
    """A wedged cycle. Restart it — unless we have already spent the budget."""
    used = restarts_today(state, today)
    budget = int(cfg.get("max_restarts_per_day", 2))

    kind = KILL_RESTART if used < budget else KILL_BUDGET_DONE
    if kind == KILL_BUDGET_DONE:
        # Before giving up the whole day: is the cause KNOWN and TRANSIENT?
        try:
            sys.path.insert(0, str(BASE))
            from core.self_diagnosis import diagnose
            d = diagnose(step, cycle_id, ceil, age)
        except Exception as e:
            d = {"cause": f"AUTOPSY_FAILED({type(e).__name__})", "transient": False}
        dused = diagnosed_retries_today(state, today)
        # 15 авг 2026: мозъкът вече може да каже „НЕ рестартирай — викай човека".
        # Досега такъв отговор нямаше къде да се побере и той беше сведен до
        # таймер. Ако го каже, се уважава веднага и без пазарлък.
        if d.get("halt_and_call_human"):
            log(f"BRAIN SAYS HALT: {d.get('cause')} — no restart; will be in the report")
            note_night_event("CYCLE HALTED BY ITS OWN BRAIN",
                        f"cause={d.get('cause')}\nwhy={d.get('why')}\n"
                        f"remedy={d.get('proposed_fix')}\n"
                        f"(the brain judged a restart would not help)")
            return
        if d.get("transient") and dused < DIAGNOSED_RETRY_MAX:
            note_diagnosed_retry(state, today)
            kind = KILL_RESTART
            reason = (f"{reason} — blind budget spent ({used}/{budget}), BUT the autopsy "
                      f"says the cause is TRANSIENT ({d.get('cause')}); taking diagnosed "
                      f"retry {dused + 1}/{DIAGNOSED_RETRY_MAX} instead of losing the day.")
            log(f"DIAGNOSED_RETRY {dused + 1}/{DIAGNOSED_RETRY_MAX}: {d.get('cause')} "
                f"on step '{step}' — retrying despite spent blind budget.")
        else:
            reason = (f"{reason} — and the restart budget for today is exhausted "
                      f"({used}/{budget}); autopsy: {d.get('cause')} "
                      f"({'transient but diagnosed retries also spent' if d.get('transient') else 'NOT transient'}). "
                      f"NOT restarting; failing loudly.")

    return Action(kind, reason=reason, wedged_step=step, wedged_step_index=step_index,
                  heartbeat_age_sec=age, ceiling_sec=ceil, pid=pid, cycle_id=cycle_id,
                  details={"restarts_used": used, "restart_budget": budget})


def _last_step_of(lock: Optional[dict], heartbeat: Optional[dict]) -> str:
    """The step the dead cycle was last seen in, from its heartbeat — but only if
    the heartbeat is actually ITS heartbeat. A heartbeat left over from an earlier
    cycle must not be attributed to this death, so if the cycle_ids disagree we
    admit we do not know rather than record a plausible-sounding wrong step."""
    if not heartbeat:
        return "unknown"
    hb_cid = heartbeat.get("cycle_id")
    lock_cid = (lock or {}).get("cycle_id")
    if hb_cid and lock_cid and hb_cid != lock_cid:
        return "unknown"
    return heartbeat.get("step") or "unknown"


def _dead_cycle_action(now, state, today, cfg, lock, heartbeat) -> Action:
    """A stale lock with no CYCLE_FINISHED behind it: the cycle died mid-run and
    the supervisor found the body. Record the death and retry — bounded by the
    same restart budget that bounds kill-restarts, for the same reason: a cycle
    that dies on every attempt must eventually stop and become a visible failure,
    not an invisible restart loop."""
    last_step = _last_step_of(lock, heartbeat)
    used = restarts_today(state, today)
    budget = int(cfg.get("max_restarts_per_day", 2))
    kind = DEAD_LOCK_RETRY if used < budget else DEAD_LOCK_BUDGET_DONE

    reason = (f"stale lock from a cycle that DIED without finishing "
              f"(pid={lock.get('pid')} is gone; no CYCLE_FINISHED on record; "
              f"last step '{last_step}')")
    if kind == DEAD_LOCK_BUDGET_DONE:
        reason += (f" — and today's restart budget is exhausted ({used}/{budget}); "
                   f"NOT retrying, failing loudly")

    return Action(kind, reason=reason, wedged_step=last_step,
                  wedged_step_index=(heartbeat or {}).get("step_index"),
                  pid=lock.get("pid"), cycle_id=lock.get("cycle_id"),
                  details={"restarts_used": used, "restart_budget": budget})


def _age(now: datetime, ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts)
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds()


# ---------------------------------------------------------------------------
# The effectful shell
# ---------------------------------------------------------------------------

def cycle_log_path(now: Optional[datetime] = None) -> Path:
    now = now or datetime.now().astimezone()
    return CYCLE_LOG_DIR / f"cycle_{now:%Y-%m-%d_%H%M%S}.log"


def prune_cycle_logs(keep: int = CYCLE_LOG_KEEP) -> int:
    """Keep the newest `keep` cycle logs. Returns how many were deleted.

    Unbounded logs are how an observability fix turns into a disk-full outage at
    03:00, which is precisely the hour nobody is watching.
    """
    try:
        logs = sorted(CYCLE_LOG_DIR.glob("cycle_*.log"))
    except Exception:
        return 0
    doomed = logs[:-keep] if keep > 0 else logs
    n = 0
    for p in doomed:
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


def spawn_cycle(cycle_id: str) -> Optional[int]:
    """Start fast_cycle_runner detached, with its output captured. Returns its PID.

    The handle is deliberately NOT closed here and the process is NOT waited on:
    the supervisor is a short-lived tick that exits in milliseconds while the
    cycle runs for an hour. The OS keeps the file open for the child and flushes
    it as the child writes; when this tick's process exits, its own copy of the
    descriptor is closed by the OS, and the child keeps writing to its own.

    PYTHONUNBUFFERED=1 is essential, not cosmetic. Redirected to a file (not a
    tty), the child's stdout is BLOCK-buffered: output sits in an in-process buffer
    and only reaches disk every few KB. When the cycle is killed abruptly — OOM
    under memory pressure, a hard power loss — that buffer dies with it and the log
    is 0 bytes for the one run it most needed to explain (observed 2026-07-15: a
    cycle ran ~20 min, died at 99% RAM, and left an empty log — the [FAST_CYCLE]
    and [CEREBRAS] lines it printed never reached disk). Unbuffered, output lands
    line by line, so a death cannot erase what came before it.
    """
    python = str(PYTHON) if PYTHON.exists() else sys.executable
    # PYTHONUNBUFFERED — the cycle log must survive the abrupt kill it exists to record.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
           "CORTEX_BASE": str(BASE),
           # The runner stamps its heartbeat with THIS cycle_id, so that on a death
           # _last_step_of() attributes the last step to this cycle instead of
           # discarding it on a cycle_id mismatch (which recorded last_step=
           # "unknown" for every death before 2026-07-19).
           "CORTEX_CYCLE_ID": cycle_id}

    try:
        CYCLE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        prune_cycle_logs()
        log_file = cycle_log_path()
        fh = log_file.open("w", encoding="utf-8", errors="replace")
    except Exception as e:
        # Losing the log must not cost us the cycle. Fall back to the old
        # behaviour and say so, loudly, rather than refusing to run.
        log(f"could not open cycle log ({type(e).__name__}: {e}) — running with output discarded")
        fh = subprocess.DEVNULL
        log_file = None

    try:
        proc = subprocess.Popen(
            [python, str(RUNNER)],
            cwd=str(BASE), env=env,
            stdout=fh, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as e:
        log(f"failed to spawn cycle: {type(e).__name__}: {e}")
        return None

    # Nothing below this line may raise: the cycle is ALREADY RUNNING. Returning
    # None now would tell the supervisor the spawn failed while a live cycle held
    # no lock — and the next tick would start a second one. Cosmetics must never
    # cost us the pid.
    try:
        if log_file:
            log(f"cycle output -> {log_file}")
    except Exception:
        pass
    return proc.pid


def tick(now: Optional[datetime] = None, dry_run: bool = False) -> Action:
    now = now or datetime.now().astimezone()
    cfg = load_config()
    state = load_state()
    lock = read_lock()
    beat = hb.read()

    alive = pid_is_our_cycle(lock.get("pid")) if lock else False
    # Only ask the ledger the question that matters: a dead-pid lock either came
    # from a cycle that finished cleanly (CYCLE_FINISHED sealed) or one that died
    # mid-run (no seal). A live cycle needs no such lookup.
    finished = ledger.has_finished(lock.get("cycle_id")) if (lock and not alive) else False
    extra = read_extraordinary(now)
    action = decide(now, state, beat, lock, cfg, lock_pid_alive=alive,
                    lock_cycle_finished=finished, extraordinary=extra)

    if dry_run:
        log(f"[dry-run] {action.kind}: {action.reason}")
        return action

    # CONSUME unconditionally: started, refused by the rate limit, vetoed by a running
    # cycle, or plain litter — the file goes. Doing this before acting means even a
    # crash inside spawn_cycle cannot leave a request that fires again next minute.
    if consume_extraordinary():
        log(f"extraordinary request consumed (valid={extra is not None})")

    today = now.date().isoformat()

    if action.kind == NOTHING:
        return action     # the steady state: no log, no ledger entry, no noise

    log(f"{action.kind}: {action.reason}")

    if action.kind == CLEAR_STALE_LOCK:
        clear_lock()
        hb.clear()
        ledger.append(ledger.LOCK_STALE, pid=action.pid, cycle_id=action.cycle_id,
                      detail=action.reason)
        return action

    if action.kind in (DEAD_LOCK_RETRY, DEAD_LOCK_BUDGET_DONE):
        # Record the death FIRST, off the still-present heartbeat, then clear both.
        # A cycle killed by the supervisor gets CYCLE_KILLED from the kill path; a
        # cycle that died on its own is witnessed here and only here.
        ledger.record_death(cycle_id=action.cycle_id or "unknown",
                            pid=action.pid or -1, last_step=action.wedged_step,
                            detail=action.reason)
        clear_lock()
        hb.clear()

        used = restarts_today(state, today)

        if action.kind == DEAD_LOCK_RETRY:
            state.setdefault("restarts", {})[today] = used + 1
            # THE fix: a death is not today's completed run. Un-satisfy the day so
            # the ordinary daily logic starts a replacement on the next tick —
            # within the budget just incremented, so a cycle that dies every time
            # cannot loop forever.
            state["last_run_date"] = None
            state["last_run_utc"] = None
            state["failure"] = None
            save_state(state)
            # No CYCLE_RESTARTED here on purpose: nothing has restarted yet. The
            # replacement is a real spawn on the NEXT tick's daily logic, and it
            # writes its own CYCLE_STARTED then. Claiming a restart now would be an
            # event with no cycle behind it — exactly what the ledger forbids.
            return action

        # Budget spent — stay down and visible, do not silently limp on.
        state["failure"] = {
            "date": today,
            "reason": action.reason,
            "wedged_step": action.wedged_step,
            "restarts_used": used,
        }
        save_state(state)
        ledger.append(ledger.BUDGET_EXHAUSTED, cycle_id=action.cycle_id,
                      wedged_step=action.wedged_step, restarts_used=used,
                      detail=action.reason)
        log("!!! RESTART BUDGET EXHAUSTED after a cycle death — the system is NOT "
            "running. Human intervention required. This will appear in the daily report.")
        _diag = _autopsy(action)
        alarm_human("СИСТЕМАТА НЕ РАБОТИ — рестартите за деня свършиха",
                    f"Умряла на стъпка: {action.wedged_step}\n"
                    f"{_diag}\n"
                    f"Рестарти: {used}/{int(cfg.get('max_restarts_per_day', 2))}\n"
                    f"Причина: {str(action.reason)[:300]}\n"
                    f"КАКВО ДА НАПРАВИШ:\n"
                    f"1) нищо — утре бюджетът се нулира и системата опитва пак (губиш 1 ден данни)\n"
                    f"2) ако стъпката е БАВНА, не счупена: вдигни тавана й в config/scheduler.json\n"
                    f"3) ръчен опит: venv\\Scripts\\python.exe fast_cycle_runner.py\n"
                    f"4) прати ми този текст — диагностицирам и поправям")
        return action

    if action.kind in (START, CATCHUP):
        cycle_id = now.isoformat()
        pid = spawn_cycle(cycle_id)
        if pid is None:
            return action
        write_lock(pid, cycle_id)

        state["last_run_date"] = today
        state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
        state["failure"] = None
        if (action.details or {}).get("extraordinary"):
            # stamp the rate limit from the moment it actually STARTED, not from when
            # it was requested — otherwise a burst of requests could each look "old"
            state["last_extraordinary_utc"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

        if action.kind == CATCHUP:
            ledger.append(ledger.MISSED_CATCHUP, cycle_id=cycle_id, pid=pid,
                          scheduled_for=action.scheduled_for,
                          actual_start=now.isoformat(), **action.details)
        ledger.append(ledger.CYCLE_STARTED, cycle_id=cycle_id, pid=pid,
                      trigger=action.kind)
        return action

    if action.kind == SKIP_MISSED:
        state["last_run_date"] = today   # do not retry all day
        save_state(state)
        ledger.append(ledger.MISSED_SKIPPED, scheduled_for=action.scheduled_for,
                      detail=action.reason, **action.details)
        return action

    if action.kind in (KILL_RESTART, KILL_BUDGET_DONE):
        if action.pid and pid_is_our_cycle(action.pid):
            kill_tree(action.pid)
        clear_lock()
        hb.clear()

        used = restarts_today(state, today)
        ledger.record_kill(
            cycle_id=action.cycle_id or "unknown", pid=action.pid or -1,
            step=action.wedged_step, step_index=action.wedged_step_index,
            heartbeat_age_sec=action.heartbeat_age_sec,
            ceiling_sec=action.ceiling_sec,
            restart_number=used + 1,
        )

        if action.kind == KILL_RESTART:
            state.setdefault("restarts", {})[today] = used + 1
            save_state(state)

            cycle_id = now.isoformat()
            pid = spawn_cycle(cycle_id)
            if pid:
                write_lock(pid, cycle_id)
                ledger.append(ledger.CYCLE_RESTARTED, cycle_id=cycle_id, pid=pid,
                              restart_number=used + 1,
                              after_wedged_step=action.wedged_step)
                ledger.append(ledger.CYCLE_STARTED, cycle_id=cycle_id, pid=pid,
                              trigger="RESTART")
            return action

        # Budget exhausted — fail loudly, do not restart.
        state["failure"] = {
            "date": today,
            "reason": action.reason,
            "wedged_step": action.wedged_step,
            "restarts_used": used,
        }
        save_state(state)
        ledger.append(ledger.BUDGET_EXHAUSTED, cycle_id=action.cycle_id,
                      wedged_step=action.wedged_step, restarts_used=used,
                      detail=action.reason)
        log("!!! RESTART BUDGET EXHAUSTED — the system is NOT running. "
            "Human intervention required. This will appear in the daily report.")
        _diag = _autopsy(action)
        alarm_human("СИСТЕМАТА НЕ РАБОТИ — рестартите за деня свършиха",
                    f"Заклещена на стъпка: {action.wedged_step}\n"
                    f"{_diag}\n"
                    f"Рестарти: {used}/{int(cfg.get('max_restarts_per_day', 2))}\n"
                    f"Причина: {str(action.reason)[:300]}\n"
                    f"КАКВО ДА НАПРАВИШ:\n"
                    f"1) нищо — утре бюджетът се нулира и системата опитва пак (губиш 1 ден данни)\n"
                    f"2) ако стъпката е БАВНА, не счупена: вдигни тавана й в config/scheduler.json\n"
                    f"3) ръчен опит: venv\\Scripts\\python.exe fast_cycle_runner.py\n"
                    f"4) прати ми този текст — диагностицирам и поправям")
        return action

    return action


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    cfg, state, lock, beat = load_config(), load_state(), read_lock(), hb.read()
    now = datetime.now().astimezone()

    print("=" * 62)
    print("CORTEX++ SUPERVISOR — existence report")
    print("=" * 62)
    print(f"now                 {now.isoformat()}")
    print(f"daily hour          {cfg['daily_hour']:02d}:00  (grace {cfg['catchup_grace_hours']}h)")
    print(f"last run            {state.get('last_run_date') or 'never'}")
    print(f"restarts today      {restarts_today(state, now.date().isoformat())}"
          f" / {cfg['max_restarts_per_day']}")

    if state.get("failure"):
        print(f"\n  !!! FAILURE: {state['failure']['reason']}\n")

    if lock:
        alive = pid_is_our_cycle(lock.get("pid"))
        print(f"lock                pid={lock.get('pid')} alive={alive}")
    else:
        print("lock                (none — no cycle running)")

    if beat:
        age = hb.age_seconds() or 0
        ceil = ceiling_for(beat.get("step"), cfg)
        print(f"heartbeat           step='{beat.get('step')}' age={age:.0f}s ceiling={ceil}s")
    else:
        print("heartbeat           (none)")

    print("\nnext action:")
    action = tick(dry_run=True)
    print(f"  {action.kind}: {action.reason}")

    print("\nexistence:")
    for k, v in ledger.summary().items():
        print(f"  {k:24} {v}")
    print("=" * 62)


def cmd_mark_ran_today() -> None:
    """Mark today as already-run, so the next tick does NOT fire a catch-up.

    Why this exists: if you install the scheduled task at 12:00 with no last_run
    on record, the very first tick correctly concludes that today's 03:00 run was
    missed and starts a catch-up cycle immediately. That is right by default — but
    sometimes you just want the thing installed and quiet until tomorrow morning.

    This does not fake a cycle. It writes no CYCLE_STARTED and no CYCLE_FINISHED;
    it records CATCHUP_SUPPRESSED_BY_HUMAN, so the existence history says plainly
    that this day had no cycle AND that a person decided that — never leaving a
    future agent to read a human's choice as its own.
    """
    now = datetime.now().astimezone()
    today = now.date().isoformat()

    st = load_state()
    if st.get("last_run_date") == today:
        log(f"today ({today}) is already marked as run — nothing to do")
        return

    if read_lock() and pid_is_our_cycle((read_lock() or {}).get("pid")):
        log("a cycle is RUNNING right now — refusing to mark today as run "
            "(that would let a second cycle start once this one finishes)")
        sys.exit(1)

    st["last_run_date"] = today
    st["last_run_utc"] = None          # honest: no cycle actually ran
    save_state(st)

    ledger.append(
        ledger.CATCHUP_SUPPRESSED,
        date=today,
        scheduled_for=now.replace(hour=int(load_config().get("daily_hour", 3)),
                                  minute=0, second=0, microsecond=0).isoformat(),
        detail="human marked today as already-run; no cycle was executed",
    )

    hour = int(load_config().get("daily_hour", 3))
    log(f"today ({today}) marked as run — no catch-up will fire. "
        f"Next cycle: tomorrow at {hour:02d}:00.")
    log("NOTE: no cycle actually ran today; the ledger records this as "
        "CATCHUP_SUPPRESSED_BY_HUMAN, not as a completed cycle.")


def cmd_install() -> None:
    """Print the schtasks command. Deliberately does NOT run it: registering a
    scheduled task is the moment the system starts running on its own, and that
    is a human's decision to make, explicitly."""
    python = str(PYTHON) if PYTHON.exists() else sys.executable
    cmd = (f'schtasks /Create /TN "CORTEX_Supervisor" /SC MINUTE /MO 5 /F '
           f'/TR "\\"{python}\\" \\"{BASE / "supervisor.py"}\\" --tick"')
    print("Run this to give the system continuous existence (no admin required):\n")
    print("  " + cmd + "\n")
    print("To stop it:\n\n  schtasks /Delete /TN \"CORTEX_Supervisor\" /F\n")
    print("The task runs in your user session — it fires only while you are logged in.")
    print("A machine that was off or logged out at the scheduled hour is covered by")
    print("the catch-up path, which runs the missed cycle on the next tick.")

    hour = int(load_config().get("daily_hour", 3))
    now = datetime.now().astimezone()
    st = load_state()
    if st.get("last_run_date") != now.date().isoformat() and now.hour >= hour:
        print()
        print(f"HEADS UP: it is past {hour:02d}:00 and no cycle has run today, so the FIRST")
        print("tick after you install will immediately start a catch-up cycle.")
        print("If you would rather it stay quiet until tomorrow morning, run this first:")
        print()
        print("  venv\\Scripts\\python.exe supervisor.py --mark-ran-today")


def main() -> None:
    ap = argparse.ArgumentParser(description="CORTEX++ supervisor")
    ap.add_argument("--tick", action="store_true", help="one supervision tick (what Task Scheduler calls)")
    ap.add_argument("--dry-run", action="store_true", help="decide, print, change nothing")
    ap.add_argument("--run-now", action="store_true", help="force a cycle now")
    ap.add_argument("--status", action="store_true", help="human-readable existence report")
    ap.add_argument("--verify-ledger", action="store_true", help="verify the existence hash chain")
    ap.add_argument("--install", action="store_true", help="print the schtasks registration command")
    ap.add_argument("--mark-ran-today", action="store_true",
                    help="treat today as already-run so no catch-up fires (no cycle is executed)")
    args = ap.parse_args()

    if args.mark_ran_today:
        cmd_mark_ran_today()
    elif args.status:
        cmd_status()
    elif args.verify_ledger:
        print(json.dumps(ledger.verify(), indent=2))
    elif args.install:
        cmd_install()
    elif args.run_now:
        if read_lock() and pid_is_our_cycle((read_lock() or {}).get("pid")):
            log("a cycle is already running — refusing to start a second one")
            sys.exit(1)
        cycle_id = datetime.now().astimezone().isoformat()
        pid = spawn_cycle(cycle_id)
        if pid:
            write_lock(pid, cycle_id)
            st = load_state()
            st["last_run_date"] = datetime.now().astimezone().date().isoformat()
            save_state(st)
            ledger.append(ledger.CYCLE_STARTED, cycle_id=cycle_id, pid=pid, trigger="MANUAL")
            log(f"cycle started manually (pid={pid})")
    elif args.tick or args.dry_run:
        tick(dry_run=args.dry_run)
    else:
        cmd_status()


if __name__ == "__main__":
    main()
