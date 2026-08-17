#!/usr/bin/env python3
"""
memory/heartbeat.py — the cycle's proof of life.

WHY A FILE, NOT STDOUT
----------------------
The 2026-07-11 lesson: PowerShell buffers a child process's stdout, so "no
output for 15 minutes" is indistinguishable from "hung". A watchdog reading
stdout would kill healthy cycles. A file write is observable immediately by an
unrelated process, with no buffering in between.

WHY EVERY STEP MUST BEAT
------------------------
fast_cycle_runner has two kinds of step: those that go through _run(label, fn),
and roughly a dozen that use inline try/except (body_scan, homeostasis,
global_indicators, web_intelligence_agent, scoring_engine, auto_levels,
goal_score_calculator, the Merkle commit, ...). If only _run() beat, the cycle
would look FROZEN during exactly the steps that legitimately take longest —
global_indicators hits 20 live HTTP APIs, web_intelligence can run for the best
part of an hour — and the watchdog would kill perfectly healthy cycles.

So beat() is called explicitly at every step boundary, and
test_heartbeat_coverage.py asserts that no step is left uninstrumented. That
test is the thing that keeps this true as the cycle grows.

WRITES ARE ATOMIC
-----------------
temp file + os.replace(). The supervisor reads this file from another process at
any moment; a half-written heartbeat that failed to parse would look like a dead
cycle and trigger a kill.

This module is deliberately dependency-free and cheap: a beat is a few hundred
bytes and happens ~25 times per cycle.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent.parent
HEARTBEAT_PATH = BASE / "memory" / "heartbeat.json"
CYCLE_LOG_DIR = BASE / "memory" / "cycle_logs"

# ── КОЯ Е БИЛА ПРЕДИШНАТА СТЪПКА (17 авг 2026) ─────────────────────────────
# core/brain.py::_prev_step_output() четеше ПОСЛЕДНИЯ [STEP] ред от лога, за да
# намери предишната стъпка. Но beat() пише този ред ПРЕДИ да повика мозъка, значи
# „последният" е СЕГАШНАТА стъпка. Затова prev_step == step във всичките 53 реда
# от 17 авг, а нотариусът сравняваше стъпка със самата себе си.
#
# Поправката НЕ Е да се премести print-ът след мозъка. Маркерът съществува точно
# за да може аутопсията да намери КЪДЕ е започнала заклещената стъпка (виж
# коментара в beat()); ако се пише след повикване към мозъка с таван 60 секунди,
# то при смърт ПО ВРЕМЕ на това повикване маркерът никога не се написва и
# аутопсията губи границата на стъпката — точно когато най-много ѝ трябва.
# core/cycle_report.py реже изхода МЕЖДУ два маркера; преместен маркер би
# приписал думите на мозъка на предишната стъпка.
#
# Затова: стойността се ХВАЩА преди новия ред да бъде написан, и се помни.
# Никакво повторно четене — четенето е това, което не може да различи двете.
_PREV_STEP: Optional[str] = None


def _last_step_in_log() -> Optional[str]:
    """The [STEP] name currently last in the cycle log.

    Called BEFORE this beat writes its own line, so what it finds is the step that
    actually ran before this one.
    """
    try:
        logs = sorted(CYCLE_LOG_DIR.glob("cycle_*.log"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            return None
        lines = logs[0].read_text(encoding="utf-8", errors="ignore").splitlines()[-400:]
        for line in reversed(lines):
            if line.lstrip().startswith("[STEP] "):
                return line.split("[STEP] ", 1)[1].strip() or None
    except Exception:
        return None
    return None


def previous_step() -> Optional[str]:
    """The step that ran before the one currently running, or None if this is the
    first beat of the cycle. Captured, never re-read."""
    return _PREV_STEP


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def beat(step: str, step_index: Optional[int] = None, cycle_id: Optional[str] = None) -> None:
    """Record that the cycle is alive and has entered `step`.

    Never raises: a failure to write the heartbeat must not kill the cycle. The
    worst case of a failed write is that the supervisor eventually sees a stale
    heartbeat and restarts us — which is the correct conservative behaviour, and
    far better than crashing a healthy cycle over a transient file lock.
    """
    # 15 Aug 2026: also stamp the step INTO THE CYCLE LOG. Until today the step
    # name lived only in heartbeat.json, so when a cycle died the autopsy
    # (core/self_diagnosis) could not find where in a 180k-line log the wedged
    # step began — it could name the step but never show its last words.
    # CAPTURE FIRST, THEN ANNOUNCE. The order of these two statements is the whole
    # fix: once the new line is written, nothing can tell it from the old one.
    global _PREV_STEP
    _PREV_STEP = _last_step_in_log()
    try:
        print(f"[STEP] {step}", flush=True)
    except Exception:
        pass
    try:
        prev = read() or {}
        # Preserve the cycle_id across beats; only the first beat sets it.
        cid = cycle_id or prev.get("cycle_id") or _utc_now()

        now = _utc_now()
        payload = {
            "pid":              os.getpid(),
            "cycle_id":         cid,
            "step":             step,
            "step_index":       step_index,
            "step_started_utc": now,
            "updated_utc":      now,
        }
        _write_atomic(payload)
    except Exception:
        pass  # never let the heartbeat kill the cycle

    # ── МОЗЪКЪТ Е НА ВСЯКА СТЪПКА (Емил, 15 авг 2026 — закон, т.1) ──────────
    # beat() е ЕДИНСТВЕНИЯТ общ проход на всичките ~50 стъпки (виж горе: точно
    # затова съществува). Затова мозъкът се закача тук — нито една стъпка не може
    # да мине покрай него, и не се налага 48 отделни закърпвания.
    # Редът е нарочен: пулсът се записва ПЪРВО (той пази живота на цикъла), чак
    # после мисли мозъкът. FAIL-OPEN: мълчащ или бавен мозък не убива цикъл.
    try:
        from core.brain import attend as _attend
        _said = _attend(step)
    except Exception:
        _said = None

    # ── ВТОРОТО МНЕНИЕ: MeTTa на всяка стъпка (Емил, 15 авг 2026) ───────────
    # „имаме ли МеТТа и Хиперон връзка на всяка стъпка (като допълнително мнение
    # и точка за съпоставка)?" — дотогава НЕ, MeTTa стоеше само в графа за
    # пропускането. Сега стои до мозъка на всяка стъпка, но НЕ като втори мозък:
    # мозъкът казва какво МИСЛИ, MeTTa казва какво СЛЕДВА ОТ ФАКТИТЕ, и когато
    # се разминат — разминаването се записва. Мозък, който твърди „предишната
    # мина добре", докато обещаният ѝ файл не е пипнат, вече не минава невидим.
    # Цена: ~0.06s за целия цикъл, нула LLM повиквания. FAIL-OPEN.
    try:
        from core.metta_check import compare as _mcompare
        _mcompare(step, (_said or {}).get("prev_step"), _said)
    except Exception:
        pass

    # ── ТРЕТИЯТ РОД ЗНАНИЕ: ПРОИЗХОДЪТ (Kimi, 15 авг 2026) ─────────────────
    # „Третият слой не е оркестратор — той е НОТАРИУС НА АВТОНОМИЯТА: на всяка
    #  стъпка подпечатва продукта с текущото ниво на доверие. Без тази верига на
    #  атестация, портата одобрява необратимо действие върху данни с неизвестен
    #  произход — архитектурна лъжа."
    # Мозъкът казва какво МИСЛИ, MeTTa какво СЛЕДВА ОТ ФАКТИТЕ, нотариусът — ПОД
    # КАКЪВ РЕЖИМ е произведено това. Лек, детерминистичен, нула LLM. FAIL-OPEN.
    try:
        from core.notary import attest as _attest
        _attest(step, (_said or {}).get("prev_step"))
    except Exception:
        pass


def _write_atomic(payload: dict) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(HEARTBEAT_PATH.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, HEARTBEAT_PATH)   # atomic on Windows and POSIX
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def read() -> Optional[dict]:
    """The current heartbeat, or None if absent/unreadable.

    A torn or missing heartbeat returns None. The supervisor treats None as "no
    proof of life", which is the safe reading.
    """
    if not HEARTBEAT_PATH.exists():
        return None
    try:
        return json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def age_seconds(now: Optional[datetime] = None) -> Optional[float]:
    """Seconds since the last beat, or None if there is no readable heartbeat."""
    hb = read()
    if not hb or not hb.get("updated_utc"):
        return None
    try:
        updated = datetime.fromisoformat(hb["updated_utc"])
    except Exception:
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - updated).total_seconds()


def clear() -> None:
    """Remove the heartbeat.

    WHO MAY CALL THIS — the rule, not a suggestion (Kimi, 16 Aug 2026):

        „Heartbeat се чисти само при KeyboardInterrupt и при CYCLE_FINISHED.
         При всяко друго прекъсване — включително SIGTERM от watchdog — се оставя."

    Exactly two callers are legitimate:
      1. the cycle itself, after a CLEAN finish (the record is already sealed);
      2. the cycle itself, on KeyboardInterrupt — a human stop is a human
         decision, not a system failure, and a frozen heartbeat left behind by a
         Ctrl+C would be read next morning as a death at that step.

    Everything else must call retire() instead. A crash, an OOM, a taskkill —
    in every one of those the heartbeat is the ONLY record of WHERE the cycle
    was when it ended, and it is what feeds deaths_by_step and the autopsy.

    This is not theory. Until 16 Aug 2026 the supervisor called clear() on every
    phantom death, which erased the proof that the "dead" cycle was in fact
    alive and working — and that is why nine of twelve deaths in the ledger read
    `last_step=unknown`: the heartbeat had been deleted by the previous tick.
    Deleting evidence to tidy up is how a system goes blind to its own errors.
    """
    try:
        HEARTBEAT_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def retire(reason: str, by: str = "supervisor", **fields) -> bool:
    """End the heartbeat WITHOUT destroying it. Returns True if one was there.

    The retired heartbeat keeps every field it had — pid, cycle_id, step,
    step_index, updated_utc — and gains `retired_utc`, `retired_by` and
    `retired_reason`. So the morning autopsy can still answer "where was it and
    who ended it", which a deleted file cannot.

    Readers must treat a retired heartbeat as NOT proof of life: it says where
    the cycle stopped, not that it is running. supervisor.decide() enforces that.
    """
    hb = read()
    if hb is None:
        return False
    hb["retired_utc"] = _utc_now()
    hb["retired_by"] = str(by)[:80]
    hb["retired_reason"] = str(reason)[:400]
    for k, v in fields.items():
        if v is not None:
            hb[k] = v
    try:
        _write_atomic(hb)
    except Exception:
        pass
    return True
