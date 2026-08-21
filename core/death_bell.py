#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/death_bell.py — WHEN THE CYCLE DIES, THE PHONE RINGS.

THE SCAR
---------
21 August 2026. Two rows landed in memory/existence_ledger.jsonl:

    14:24:02Z  CYCLE_KILLED  wedged_step=daily_analysis
    14:39      CYCLE_DIED

Zero Telegram messages were sent. The ledger is append-only, hash-chained and
fsynced — and read by nobody until a human opens it hours later. The reaper had
a perfect memory and no voice.

The alarm that DID exist fired only on CYCLE_FAILED_BUDGET_EXHAUSTED, i.e. after
the last restart of the day was spent. Every kill and every restart before that
was silent by construction: the system could die, be reborn, die again and be
reborn again, and the only trace was a file.

WHAT RINGS
-----------
Four events, each written by the supervisor's own reaper path:

    CYCLE_KILLED                      the watchdog measured a stale heartbeat
                                      and killed the cycle
    CYCLE_DIED                        the cycle vanished; the supervisor found
                                      the body
    CYCLE_RESTARTED                   a replacement was spawned
    CYCLE_FAILED_BUDGET_EXHAUSTED     nothing will be spawned; the system is down

Each carries the same facts the ledger row carries, and nothing invented:
event, cycle_id, wedged step, heartbeat age against its ceiling, restart budget.

ALARM CLASS — QUIET HOURS DO NOT APPLY
---------------------------------------
supervisor.QUIET_HOURS (22:00-09:00) exists so a NIGHTLY cycle that heals itself
does not wake anybody. A death is not that. "ДА НЕ МЕ БУДЯТ" was about routine;
the system being dead is not routine, and a message that arrives at 09:00 about a
death at 00:20 is an obituary, not an alarm. The send therefore passes
trigger="MANUAL", which is the one value alarm_human() honours as "past the
quiet window".

FAIL-OPEN, ABSOLUTELY
----------------------
A dead bot must never block the reaper. Every path here is wrapped; ring()
returns a record saying what happened and RAISES NOTHING. If Telegram is down,
if the token file is missing, if the local brain is not installed — the kill
still lands, the restart still happens, and the record says which parts failed.

THE DEATH DEBRIEF
------------------
After a kill the local brain (never the cloud — a dead machine cannot reach it,
and core.backend_policy.SELF_DIRECTED already forbids it for purpose "autopsy")
is given the autopsy numbers and asked for three sentences. It gets 60 seconds
of wall clock, enforced by a daemon thread that the caller abandons on timeout.
If it says nothing, the alarm goes out without it. The alarm is the point; the
post-mortem is a courtesy.

    venv\\Scripts\\python.exe core/death_bell.py --selftest
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

# The four events that mean "the cycle is not running any more". Kept as a
# frozenset rather than four scattered call sites so that a fifth terminal event
# added to memory/existence_ledger.py is one line here, not a hunt through
# supervisor.py.
DEATH_EVENTS = frozenset({
    "CYCLE_KILLED",
    "CYCLE_DIED",
    "CYCLE_RESTARTED",
    "CYCLE_FAILED_BUDGET_EXHAUSTED",
})

# Wall clock the local brain gets for its three sentences. Measured 21 Aug 2026:
# qwen3:8b writes a four-field debrief in 124.5 s, so 60 s is deliberately NOT
# enough for the big model on a cold load — the post-mortem is best-effort and
# the alarm must not wait for it.
POSTMORTEM_BUDGET_SEC = 60

PURPOSE = "autopsy"          # core/backend_policy.SELF_DIRECTED

# One line per event, in Bulgarian: this arrives on Emil's phone.
_HEADLINE = {
    "CYCLE_KILLED":                  "ЦИКЪЛЪТ Е УБИТ от пазача",
    "CYCLE_DIED":                    "ЦИКЪЛЪТ Е УМРЯЛ (намерен мъртъв)",
    "CYCLE_RESTARTED":               "ЦИКЪЛЪТ Е РЕСТАРТИРАН",
    "CYCLE_FAILED_BUDGET_EXHAUSTED": "СИСТЕМАТА НЕ РАБОТИ — рестартите свършиха",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# The facts
# ---------------------------------------------------------------------------

def facts(event: str, cycle_id=None, wedged_step=None,
          heartbeat_age_sec=None, ceiling_sec=None,
          restarts_used=None, restart_budget=None, detail=None) -> dict:
    """Exactly what the ledger row carries — no more, and nothing invented.

    `exceeded_by_sec` is derived, not asserted: it is the one number that says
    whether the ceiling was crossed by a second or by ten minutes, and doing
    that subtraction on a phone at 03:00 is how a real alarm gets skimmed.
    """
    over = None
    if heartbeat_age_sec is not None and ceiling_sec is not None:
        try:
            over = round(float(heartbeat_age_sec) - float(ceiling_sec), 1)
        except (TypeError, ValueError):
            over = None
    return {
        "event":             event,
        "cycle_id":          cycle_id or "unknown",
        "wedged_step":       wedged_step or "unknown",
        "heartbeat_age_sec": (round(float(heartbeat_age_sec), 1)
                              if heartbeat_age_sec is not None else None),
        "ceiling_sec":       ceiling_sec,
        "exceeded_by_sec":   over,
        "restarts_used":     restarts_used,
        "restart_budget":    restart_budget,
        "detail":            (str(detail)[:300] if detail else None),
        "ts":                _now(),
    }


def render(f: dict, postmortem=None) -> str:
    """The message body. Positional lines, one fact each, no prose padding."""
    head = _HEADLINE.get(f["event"], f["event"])
    age = f["heartbeat_age_sec"]
    ceil_ = f["ceiling_sec"]
    if age is None and ceil_ is None:
        beat = "пулс: няма измерване (цикълът изчезна, не беше измерен)"
    else:
        beat = (f"пулс: {age if age is not None else '?'} s срещу таван "
                f"{ceil_ if ceil_ is not None else '?'} s")
        if f["exceeded_by_sec"] is not None:
            beat += f" (превишение {f['exceeded_by_sec']} s)"
    used, budget = f["restarts_used"], f["restart_budget"]
    if used is None and budget is None:
        bank = "рестарти: неизвестно"
    else:
        left = (budget - used) if (used is not None and budget is not None) else None
        bank = (f"рестарти: {used if used is not None else '?'}/"
                f"{budget if budget is not None else '?'}"
                + (f" — остават {max(left, 0)}" if left is not None else ""))
    lines = [
        head,
        f"цикъл: {f['cycle_id']}",
        f"заклещена стъпка: {f['wedged_step']}",
        beat,
        bank,
    ]
    if f.get("detail"):
        lines.append(f"причина: {f['detail']}")
    if postmortem:
        lines.append("")
        lines.append("АУТОПСИЯ (локален мозък):\n" + str(postmortem).strip()[:900])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The post-mortem — local brain, hard 60 s wall clock
# ---------------------------------------------------------------------------

POSTMORTEM_PROMPT = """Цикълът на CORTEX++ току-що завърши със събитие {event}.

ЧИСЛАТА ОТ АУТОПСИЯТА:
{numbers}

Напиши ТОЧНО три изречения — какво се е случило, защо вероятно, какво следва.
Всяко твърдение да стъпва на число от горните. Ако числата не стигат за извод,
кажи го вместо да съчиняваш. Български или английски, без йероглифи."""


def post_mortem(f: dict, budget_sec: float = POSTMORTEM_BUDGET_SEC,
                thinker=None):
    """Three sentences from the LOCAL brain, or None. Never raises, never waits
    past `budget_sec`.

    core.brain.think() carries a 300 s cold-load timeout of its own, which is
    five times this budget: waiting for it would hold the reaper's tick open
    while the system is already down. So the call runs on a daemon thread and
    the result is collected only if it arrives in time. The abandoned thread
    costs nothing — a supervisor tick is a short-lived process.
    """
    box: dict = {}

    def _work() -> None:
        try:
            from core import backend_policy
            backend_policy.block_cloud(
                "core/death_bell.py post-mortem is local-only by design")
        except Exception:
            pass                       # a missing policy module must not stop it
        try:
            from core.brain import think
            said = (thinker or think)(
                role="патоанатом на собствения си цикъл",
                question=POSTMORTEM_PROMPT.format(
                    event=f.get("event"),
                    numbers=json.dumps(f, ensure_ascii=False, indent=2)),
                kind=PURPOSE,
                temperature=0.1,
            )
            if isinstance(said, dict):
                box["text"] = str(said.get("text") or "").strip() or None
            elif isinstance(said, str):
                box["text"] = said.strip() or None
        except Exception as exc:       # noqa: BLE001
            box["error"] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=_work, daemon=True, name="death-bell-postmortem")
    t.start()
    t.join(budget_sec)
    if t.is_alive():
        return None                    # past budget: ring without it
    return box.get("text")


# ---------------------------------------------------------------------------
# The bell
# ---------------------------------------------------------------------------

def ring(event: str, cycle_id=None, wedged_step=None,
         heartbeat_age_sec=None, ceiling_sec=None,
         restarts_used=None, restart_budget=None,
         detail=None, with_postmortem=None, sender=None, thinker=None) -> dict:
    """Send the alarm. Returns a record of what happened; raises NOTHING.

    `with_postmortem` defaults to True for CYCLE_KILLED and False for everything
    else: a kill is the event whose numbers actually support a diagnosis (there
    is a wedged step and a measured heartbeat age). A death has neither, and a
    restart is news that does not need 60 seconds of local inference.

    `sender` is the seam the tests hold. The default is supervisor.alarm_human
    with trigger="MANUAL", which is the ONLY value that bypasses the quiet
    window.
    """
    record: dict = {"ts": _now(), "event": event, "sent": False, "errors": []}
    try:
        f = facts(event, cycle_id, wedged_step, heartbeat_age_sec, ceiling_sec,
                  restarts_used, restart_budget, detail)
        record["facts"] = f
    except Exception as exc:           # noqa: BLE001
        record["errors"].append(f"facts: {type(exc).__name__}: {exc}")
        return record

    if with_postmortem is None:
        with_postmortem = (event == "CYCLE_KILLED")

    pm = None
    if with_postmortem:
        try:
            pm = post_mortem(f, thinker=thinker)
        except Exception as exc:       # noqa: BLE001
            record["errors"].append(f"post_mortem: {type(exc).__name__}: {exc}")
    record["postmortem"] = pm

    try:
        record["text"] = render(f, pm)
    except Exception as exc:           # noqa: BLE001
        record["errors"].append(f"render: {type(exc).__name__}: {exc}")
        return record

    try:
        if sender is not None:
            sender(_HEADLINE.get(event, event), record["text"])
        else:
            import supervisor
            supervisor.alarm_human(
                _HEADLINE.get(event, event), record["text"],
                # One bell per (event, cycle). A second kill of the SAME cycle
                # cannot happen; a kill of the NEXT cycle carries a different
                # cycle_id and must ring again.
                dedup_key=f"death:{event}:{f['cycle_id']}",
                trigger="MANUAL")      # ALARM class: past the quiet window
        record["sent"] = True
    except Exception as exc:           # noqa: BLE001
        record["errors"].append(f"send: {type(exc).__name__}: {exc}")
    return record


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import time as _time
    print("core/death_bell.py --selftest")
    ok = True

    def check(name: str, cond) -> None:
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {name}")

    # INTEGRATIONS — LIVE or INERT in the repo this file finds itself in.
    for name, mod in (("supervisor.alarm_human", "supervisor"),
                      ("core.brain.think", "core.brain"),
                      ("core.backend_policy", "core.backend_policy")):
        try:
            __import__(mod)
            print(f"  LIVE    {name}")
        except Exception as exc:       # noqa: BLE001
            print(f"  INERT   {name} ({type(exc).__name__})")

    sent: list = []
    rec = ring("CYCLE_KILLED", cycle_id="selftest-1", wedged_step="daily_analysis",
               heartbeat_age_sec=972.7, ceiling_sec=900, restarts_used=1,
               restart_budget=2, with_postmortem=False,
               sender=lambda s, t: sent.append((s, t)))
    check("a kill rings the bell", rec["sent"] and len(sent) == 1)
    body = sent[0][1] if sent else ""
    check("the message names the wedged step", "daily_analysis" in body)
    check("...the heartbeat age", "972.7" in body)
    check("...the ceiling", "900" in body)
    check("...the overrun, derived", "72.7" in body)
    check("...the restart budget", "1/2" in body)

    def _boom(_s, _t):
        raise RuntimeError("telegram is dead")

    rec2 = ring("CYCLE_DIED", cycle_id="selftest-2", sender=_boom)
    check("a dead bot does not raise", rec2["sent"] is False and bool(rec2["errors"]))

    rec3 = ring("CYCLE_DIED", cycle_id="selftest-3", sender=lambda s, t: None)
    check("a death with no measurement says so",
          "няма измерване" in (rec3.get("text") or ""))

    slow = post_mortem({"event": "X"}, budget_sec=0.2,
                       thinker=lambda **kw: _time.sleep(5))
    check("the post-mortem budget is enforced", slow is None)

    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(_selftest())
