#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fast_cycle_runner.py
Бърз цикъл — пуска се всеки час.
"""
from __future__ import annotations
import subprocess, sys, pathlib, json, time, gc
from datetime import datetime, timezone, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── A HARD CRASH MUST LEAVE A TRACEBACK ─────────────────────────────────────
# Four cycles have now died leaving a log that ends mid-step with no error, no
# traceback and no last words. A Python exception would have been printed; a
# fault below Python — SIGSEGV or SIGABRT inside a C extension, and this process
# loads several (requests/OpenSSL, chromadb/sqlite, ollama clients) — prints
# nothing at all. The interpreter dies before it can say why.
#
# faulthandler installs OS-level signal handlers that dump the Python stack of
# every thread at the moment of the fault. It writes to sys.stderr, which the
# supervisor points at the cycle log (stderr=STDOUT, stdout=the log file), so a
# fatal fault now lands in the same log as the step that provoked it.
#
# Cost: one signal handler per fatal signal, nothing at runtime.
#
# WHAT THIS DOES NOT CATCH: a HANG. faulthandler.enable() fires on a fault, not
# on a process that is alive and waiting forever — which is what the evidence
# points to for the 17:59 death (STEP_STUCK, four times, heartbeat frozen mid
# beat()). faulthandler.dump_traceback_later() is the tool for that case and is
# deliberately NOT enabled here: it would need a chosen interval and a decision
# about repeat/exit, which is a behaviour change rather than a diagnostic.
import faulthandler
faulthandler.enable(all_threads=True)

BASE = pathlib.Path(__file__).resolve().parent
import os
os.environ["CORTEX_BASE"] = str(BASE)

# Proof of life for the supervisor's watchdog. beat() is called at EVERY step
# boundary below — not just inside _run() — because ~a dozen steps use inline
# try/except and bypass _run entirely. If those steps did not beat, the cycle
# would look frozen during exactly the slowest legitimate work (global_indicators
# hits 20 live APIs; web_intelligence can run the better part of an hour) and the
# watchdog would kill healthy cycles. test/test_heartbeat_coverage.py enforces
# that every step boundary is instrumented, so this cannot silently rot.
from memory.heartbeat import beat, clear as _clear_heartbeat

LOCK_PATH = BASE / "memory" / "cycle.lock"

def _utc_now():
    return datetime.now(timezone.utc).isoformat()


LAST_CYCLE_ID = BASE / "memory" / "last_cycle_id.txt"        # последен ЗАПЕЧАТАН
LAST_ATTEMPT = BASE / "memory" / "last_attempted_cycle_id.txt"  # последен ОПИТАН
CYCLE_ORIGIN = BASE / "memory" / "cycle_origin.json"


def _pid_alive(pid) -> bool:
    """Жив ли е този процес. psutil, ако го има (Windows не поддържа signal 0)."""
    try:
        pid = int(pid)
    except Exception:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        pass
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _classify_cycle_id(env_id):
    """A / B / C по консенсуса с Kimi (15 авг 2026, стъпка 1).

    A: env е СТРОГО ПО-НОВ от последния запечатан цикъл -> нормално (supervisor).
    B: env липсва -> ръчно пускане; нов id, origin=manual, за да НЕ го чака
       супервайзорът като свой.
    C: env е по-стар/равен на последния запечатан, ИЛИ е нечетим -> stale/повреден:
       цикълът спира ВЕДНАГА, вместо да лъже, че е жив.
    """
    from datetime import datetime as _dt
    now = _dt.now(timezone.utc)

    def _parse(x):
        try:
            d = _dt.fromisoformat(str(x).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    # ВЕРИФИКАЦИЯ НА KIMI (15 авг, стъпка 1): „last се пише само в края;
    # прекъснат цикъл (стъпка 35) остава НЕВИДИМ за проверката" — тоест stale env
    # от цикъл, умрял ПРЕДИ запечатване, минаваше като случай A. Дупка в кода, не
    # в идеята. Затова се сравнява с ПО-КЪСНОТО от двете: последния запечатан и
    # последния ОПИТАН (записва се при всеки boot, независимо дали цикълът стига
    # до края). Супервайзорът дава ново cycle_id при всяко пускане (now.isoformat()),
    # значи законен рестарт никога не е равен на предишен опит.
    last = None
    for f in (LAST_CYCLE_ID, LAST_ATTEMPT):
        try:
            v = _parse(f.read_text(encoding="utf-8").strip())
            if v and (last is None or v > last):
                last = v
        except Exception:
            pass

    if env_id is None or str(env_id).strip() == "":
        cid, origin, why = now.isoformat(), "manual", "няма CORTEX_CYCLE_ID — ръчно пускане"
    else:
        parsed = _parse(env_id)
        if parsed is None:
            print(f"[FAST_CYCLE] BOOT ABORT: нечетим CORTEX_CYCLE_ID={env_id!r} — "
                  f"това е системен отказ, не ръчно пускане (случай C).")
            _note_boot_abort(f"нечетим cycle_id: {env_id!r}")
            raise SystemExit(2)
        # Kimi (стъпка 1, 3-ти рунд): „clock skew — бъдещ env_id не се отхвърля".
        # Часовник, избързал напред (NTP скок), ще произведе cycle_id от бъдещето,
        # който после трови всяко сравнение по време. 5 минути толеранс за
        # нормално разминаване между супервайзор и цикъл.
        if parsed > now + timedelta(minutes=5):
            print(f"[FAST_CYCLE] BOOT ABORT: CORTEX_CYCLE_ID={env_id} е в БЪДЕЩЕТО "
                  f"спрямо {now.isoformat()} — часовникът лъже (случай C).")
            _note_boot_abort(f"бъдещ cycle_id {env_id} > now+5min")
            raise SystemExit(2)
        if last is not None and parsed <= last:
            print(f"[FAST_CYCLE] BOOT ABORT: stale CORTEX_CYCLE_ID={env_id} "
                  f"<= последния запечатан {last.isoformat()} (случай C). "
                  f"Спирам сега, за да не изглеждам жив, докато съм мъртъв.")
            _note_boot_abort(f"stale cycle_id {env_id} <= {last.isoformat()}")
            raise SystemExit(2)
        cid, origin, why = str(env_id), "supervisor", "env по-нов от последния запечатан"

    try:
        CYCLE_ORIGIN.parent.mkdir(parents=True, exist_ok=True)
        CYCLE_ORIGIN.write_text(json.dumps(
            {"cycle_id": cid, "origin": origin, "why": why,
             "last_sealed": last.isoformat() if last else None},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    # ── СЛУЧАЙ D: вече тече друг цикъл (Kimi, 15 авг: „при manual пускане може
    # да се застъпи със supervisor цикъл"). Проверих кода: ключалката
    # memory/cycle.lock се СЪЗДАВА от супервайзора и се ОСВОБОЖДАВА от цикъла, но
    # самият цикъл никога не я проверява при старт. Значи два процеса можеха да
    # пишат едновременно в едни и същи файлове. Тук се проверява.
    try:
        if LOCK_PATH.exists():
            lk = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            other_pid, other_id = lk.get("pid"), lk.get("cycle_id")
            # Kimi: „other_id == cid не влиза в exit 3 — два живи процеса с еднакъв
            # ID могат да текат паралелно". Вярно беше. Сега блокира и това, но
            # ИЗКЛЮЧВА собствения си pid: супервайзорът пише ключалката с pid-а на
            # процеса, който току-що е родил — тоест нашия. Без това изключение
            # цикълът щеше да се самоубива при всяко нормално пускане.
            # ── ПРИНЦИПЪТ НА НОЩНИЯ ПАЗАЧ (Kimi, 16 август 2026) ─────────────
            # Този пазач уби цикъла ТРИ ПОРЕДНИ ПЪТИ в нощта на 16 август и
            # системата не работи цяло денонощие. Причината, измерена от логовете:
            #   ключалка cycle_id=03:04:02.435030  pid 59108
            #   процесът  "started at"  03:04:02.862      (0.43 сек по-късно)
            # Супервайзорът пише ключалката СЛЕД spawn, със същия cycle_id, който
            # подава на детето. Тоест цикълът четеше СВОЯТА СОБСТВЕНА ключалка.
            # Единственото, което го пазеше, беше сравнението по pid — а то не
            # работи, защото os.getpid() на процеса не съвпада с pid-а, върнат от
            # Popen (venv launcher/wrapper ражда истинския интерпретатор).
            #   Kimi: „Супервайзорът записва pid, който НЕ ПОЗНАВА. Това е вродена
            #          лъжа." И, признавайки собствената си вчерашна присъда:
            #          „Вчера настоях за строг пазач, без да помисля, че при
            #          неопределеност той ще убие системата. Това е моя грешка."
            #
            # ПРИНЦИПЪТ, който липсваше:
            #   „Ако не си сигурен дали да спреш, ПРОДЪЛЖИ с ясен запис на
            #    неопределеността. Смъртта е необратима; логът може да се поправи
            #    на сутринта. При система без надзор fail-deadly е по-лошо от
            #    fail-unsafe — пазачът трябва да е консервативен в причиняването
            #    на смърт."
            # Два цикъла върху едни файлове дават размазани данни, които ЧОВЕК
            # лови на сутринта. Нула цикъла дава ЛИПСА — а липсата не се лови, тя
            # е отсъствие.
            #
            # Оттук асиметрията:
            #   ясен чужд цикъл (ДРУГ cycle_id + жив pid) -> ABORT
            #   всичко неясно (същият cycle_id, несъвпадащ pid, нечетима ключалка)
            #                                              -> LOG и ПРОДЪЛЖИ
            _same_id = bool(other_id) and str(other_id) == str(cid)
            _mine = other_pid is not None and int(other_pid or -1) == os.getpid()

            if other_id and not _same_id and not _mine and _pid_alive(other_pid):
                print(f"[FAST_CYCLE] BOOT ABORT: вече тече ДРУГ цикъл {other_id} "
                      f"(pid {other_pid}, жив) — случай D. Два цикъла върху едни и "
                      f"същи файлове е по-лошо от нито един.")
                _note_boot_abort(f"застъпване: жив ЧУЖД цикъл {other_id} pid={other_pid}")
                raise SystemExit(3)

            if _same_id and not _mine:
                # Ключалката носи МОЯ cycle_id, но чужд pid — почти сигурно
                # обвивката, която ме е родила. Приемам я за своя и я ПРЕЗАПИСВАМ
                # с истинския си pid, за да не се бие следващият рестарт със
                # същата сянка.
                print(f"[FAST_CYCLE] boot -> ключалка със СЪВПАДАЩ cycle_id {other_id}, "
                      f"но pid {other_pid} != {os.getpid()} (wrapper?); приемам я за "
                      f"своя и обновявам pid. Неопределеност -> продължавам, не умирам.")
                _note_boot_abort(f"НЕ Е ПРЕКЪСВАНЕ: своя ключалка с чужд pid "
                                 f"{other_pid} -> презаписан с {os.getpid()}")
                try:
                    lk["pid"] = os.getpid()
                    lk["pid_rewritten_by_cycle"] = True
                    LOCK_PATH.write_text(json.dumps(lk, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
                except Exception as _e:
                    print(f"[FAST_CYCLE] boot -> не успях да обновя ключалката "
                          f"({type(_e).__name__}); продължавам въпреки това.")

            if other_id and not _same_id and not _pid_alive(other_pid):
                print(f"[FAST_CYCLE] boot -> заварена мъртва ключалка на {other_id} "
                      f"(pid {other_pid}); продължавам.")
    except SystemExit:
        raise
    except Exception as _e:
        # НЕЧЕТИМА КЛЮЧАЛКА Е НЕОПРЕДЕЛЕНОСТ, НЕ РАЗРЕШЕНИЕ — и не е повод за
        # смърт. Продължаваме, но го КАЗВАМЕ: досега този `pass` мълчеше, тоест
        # повредена ключалка беше неразличима от липсваща.
        print(f"[FAST_CYCLE] boot -> ключалката не се чете "
              f"({type(_e).__name__}: {_e}); третирам го като неопределеност и "
              f"продължавам — смъртта е необратима, логът не е.")
        _note_boot_abort(f"НЕ Е ПРЕКЪСВАНЕ: нечетима ключалка ({type(_e).__name__})")

    # ── ЦИКЪЛЪТ ПОЕМА СОБСТВЕНАТА СИ КЛЮЧАЛКА (16 август 2026) ──────────────
    # Измерено на машината, два пъти подред:
    #     Popen.pid = 85400 | child os.getpid() = 97752 -> MISMATCH
    #     chain: [(94152, 'python.exe')] — psutil НЕ намира жив родител
    # venv\Scripts\python.exe е ЛАУНЧЕР: Popen получава pid-а на стъпката, тя ражда
    # истинския интерпретатор и УМИРА. Тоест pid-ът, който супервайзорът записва,
    # е мъртъв секунди след старта.
    #
    # Това чупи ДВЕ неща, не едно:
    #   1. boot пазача (поправен по-горе с cycle_id),
    #   2. и — по-лошото — `pid_is_our_cycle()` в супервайзора, който пита
    #      tasklist за записания pid. Той връща False почти веднага, значи
    #      супервайзорът смята жив цикъл за МЪРТЪВ, рестартира го, и изчерпва
    #      бюджета. Точно това пише в scheduler_state от снощи:
    #      „pid=86528 is gone; no CYCLE_FINISHED on record".
    #
    # Затова цикълът поема ключалката САМ и записва СВОЯ истински pid. Никой друг
    # не знае кой е той — Popen не го вижда, стъпката вече е умряла. Единственият,
    # който го знае, е самият процес.
    #   Kimi: „Супервайзорът записва pid, който НЕ ПОЗНАВА. Това е вродена лъжа.
    #          Поправката е да се премахне зависимостта от Popen pid изобщо."
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.write_text(json.dumps({
            "pid": os.getpid(),
            "cycle_id": cid,
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "claimed_by": "cycle",          # НЕ от супервайзора — от самия процес
            "note": ("pid-ът тук е истинският на цикъла. Супервайзорът записва "
                     "pid-а на venv launcher-а, който умира веднага."),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[FAST_CYCLE] boot -> поех ключалката със СВОЯ pid {os.getpid()}")
    except Exception as _e:
        print(f"[FAST_CYCLE] boot -> не можах да поема ключалката "
              f"({type(_e).__name__}: {_e}); продължавам — липсата на ключалка "
              f"не е повод да умра.")

    # Kimi: „пиши LAST_ATTEMPT атомарно (tmp+rename), за да не остане половинчат
    # при срив" — половин timestamp е по-лош от липсващ: не се парсва, значи
    # утрешната проверка мълчаливо губи ориентира си.
    try:                      # ОПИТЪТ се записва СЕГА, не в края
        _tmp = LAST_ATTEMPT.with_suffix(".tmp")
        _tmp.write_text(cid, encoding="utf-8")
        os.replace(_tmp, LAST_ATTEMPT)
    except Exception:
        pass
    print(f"[FAST_CYCLE] boot -> cycle_id={cid} origin={origin} ({why})")
    return cid


def _note_boot_abort(detail: str) -> None:
    """Прекъснат старт не бива да изчезва — влиза в нощния дневник и утре
    сутрин излиза в отчета (човекът не се буди, но научава)."""
    try:
        p = BASE / "memory" / "night_events.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                                 "subject": "BOOT ABORTED (случай C)",
                                 "detail": detail}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _seal_cycle_record() -> None:
    """A cycle that finished cleanly says so, and lets go of its own lock.

    THE BUG THIS FIXES (2026-07-14)
    -------------------------------
    Nothing ever wrote CYCLE_FINISHED. The constant existed in
    memory/existence_ledger.py and summary() counted it — but no producer did, so
    total_cycles_finished was permanently 0. And because the runner never cleared
    its own lock, every CLEAN finish left a lock held by a now-dead pid, which the
    next supervisor tick dutifully cleared as stale and logged as "machine likely
    lost power mid-cycle". A successful cycle was therefore indistinguishable, in
    the system's own records, from a crashed one. The 2026-07-14 catch-up ran all
    25 steps, committed its Merkle root, and its permanent record says it never
    finished and probably lost power.

    A cycle is the only witness to its own completion: the supervisor watches from
    outside and cannot tell "exited cleanly" from "died quietly". So the witness
    must speak.

    Never raises. Sealing the record must not fail a cycle that has already done
    all of its work — the worst case of a failed seal is the old behaviour.
    """
    pid = os.getpid()
    lock = None
    cycle_id = None
    started = None

    try:
        if LOCK_PATH.exists():
            lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            cycle_id = lock.get("cycle_id")
            started = lock.get("started_utc")
    except Exception:
        lock = None

    if not cycle_id:
        # Run by hand, with no supervisor and no lock: still a cycle, still finished.
        try:
            from memory.heartbeat import read as _hb_read
            cycle_id = (_hb_read() or {}).get("cycle_id")
        except Exception:
            pass

    duration = None
    try:
        if started:
            t0 = datetime.fromisoformat(started)
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            duration = round((datetime.now(timezone.utc) - t0).total_seconds(), 1)
    except Exception:
        pass

    try:
        from memory.existence_ledger import append as _el_append, CYCLE_FINISHED
        _el_append(CYCLE_FINISHED, cycle_id=cycle_id or "unknown", pid=pid,
                   duration_sec=duration)
        print(f"[FAST_CYCLE] existence: CYCLE_FINISHED sealed (cycle_id={cycle_id}, "
              f"duration={duration}s)")
    except Exception as e:
        print(f"[FAST_CYCLE] existence: CYCLE_FINISHED -> FAILED: {type(e).__name__}: {e}")

    # Release OUR lock — and only ours. If the supervisor decided we were hung,
    # killed us, and started a replacement, the lock on disk belongs to the new
    # cycle. Deleting it would leave the live cycle unlocked and invite a second.
    try:
        if lock is not None and lock.get("pid") == pid:
            LOCK_PATH.unlink(missing_ok=True)
            print("[FAST_CYCLE] lock released")
    except Exception as e:
        print(f"[FAST_CYCLE] lock release -> FAILED: {type(e).__name__}: {e}")

# ── --resume: OFF UNLESS SOMEBODY SAYS OTHERWISE (22 авг 2026) ───────────────
# Populated once by _decide_resume() at the top of main(); read by _run(). A dict
# rather than a bare set so that "no decision was taken" and "the decision was to
# skip nothing" stay distinguishable in the log.
_RESUME = {"active": False, "skip": frozenset(), "reason": "not evaluated",
           "seal_only": False}


def _decide_resume(argv) -> dict:
    """Should this run skip work a previous cycle already completed?

    Four independent ways to say no, and all of them mean "run the whole cycle" —
    never "run some of it and hope":

      * --resume absent. The default, and the only thing a manual run gets unless
        the human types the flag.
      * no checkpoint, or one filed under a different cycle than the one we were
        told we are continuing.
      * that cycle already sealed CYCLE_FINISHED — there is nothing to resume.
      * the artifact gate (core/phase_resume) says the evidence the completed
        prefix promises is not on disk, or belongs to an older cycle. That gate
        exists because scoring will happily run on last night's snapshots and
        stamp today's date on the result.

    The set of steps actually skipped is the INTERSECTION of decide_resume's
    prefix with the steps that genuinely recorded a completion. Prefix alone is
    not enough here: only 21 of 54 steps checkpoint at all, and `body_scan`
    appears twice in the step list so an index-based prefix is ambiguous for it.
    Evidence beats arithmetic — a step is skipped only if it is on record as done.
    """
    if "--resume" not in argv:
        return {"active": False, "skip": frozenset(),
                "reason": "resume not requested (--resume is OFF by default)",
                "seal_only": False}
    try:
        from core import cycle_checkpoint as _cc
        from core.cycle_map import STEPS as _STEPS
        from memory.existence_ledger import has_finished as _has_finished

        prev = os.environ.get("CORTEX_RESUME_CYCLE_ID") or ""
        if not prev:
            return {"active": False, "skip": frozenset(), "seal_only": False,
                    "reason": "--resume given but CORTEX_RESUME_CYCLE_ID is empty; "
                              "nothing names the cycle being continued"}

        steps = [s[0] for s in _STEPS]
        decision = _cc.decide_resume(
            prev, steps, _cc.latest(),
            cycle_finished=_has_finished(prev),
            enabled=True,
            artifact_check=_artifact_veto,
        )
        if not decision.resume:
            return {"active": False, "skip": frozenset(), "seal_only": False,
                    "reason": decision.reason}

        done = set(_cc.completed_steps(prev))
        skip = frozenset(s for s in decision.skipped_steps if s in done)
        seal_only = decision.start_index >= len(steps)
        return {"active": True, "skip": skip, "seal_only": seal_only,
                "reason": decision.reason}
    except Exception as e:
        # A resume that cannot be reasoned about is a resume that does not happen.
        return {"active": False, "skip": frozenset(), "seal_only": False,
                "reason": f"resume evaluation failed ({type(e).__name__}: {e}) — "
                          f"running the full cycle"}


def _artifact_veto(step: str):
    """core/phase_resume as decide_resume's veto. Returns a refusal string or None.

    Maps the last completed STEP to the phase the cycle would resume INTO, and
    asks phase_resume whether that phase's required artifacts exist AND belong to
    this cycle. Anything it cannot answer is a refusal, not a shrug: an unknown
    phase is exactly when a wrong resume is most likely.
    """
    try:
        from core.phase_report import load_phases
        phases = load_phases()
        names = list(phases)
        here = None
        for i, ph in enumerate(names):
            if any(s.get("name") == step for s in phases[ph].get("steps", [])):
                here = i
        if here is None:
            return f"step {step!r} belongs to no declared phase"
        if here + 1 >= len(names):
            return None            # nothing after it to require anything
        nxt = names[here + 1]
        from core.phase_resume import check_requires
        cid = os.environ.get("CORTEX_RESUME_CYCLE_ID") or ""
        bad = [r for r in check_requires(nxt, cid) if not r["ok"]]
        if bad:
            return "{} of {} artifact(s) for {} missing: {}".format(
                len(bad), len(bad), nxt,
                "; ".join(f"{r['path']} ({r['reason']})" for r in bad[:3]))
        return None
    except Exception as e:
        return f"artifact gate could not run ({type(e).__name__}: {e})"


def _checkpoint_step(label: str) -> None:
    """Record that `label` finished. Called only from the success path of _run().

    The cycle_id is read from the heartbeat rather than passed down, because the
    heartbeat is already the one place that holds the SUPERVISOR's cycle_id — a
    second source for the same id is how a checkpoint ends up filed under a cycle
    that never ran.

    NEVER RAISES. A checkpoint is a convenience for the next run; a cycle that
    dies because it could not write one has traded a real night for a hypothetical
    one. The failure is printed, not swallowed silently.
    """
    try:
        from core import cycle_checkpoint as _cc
        from core.cycle_map import ALIASES as _AL
        from memory.heartbeat import read as _hb_read
        _hb = _hb_read() or {}
        _cid = _hb.get("cycle_id") or "unknown"
        _step = _AL.get(label, label)
        _cc.record_step_complete(_cid, _step, _hb.get("step_index"))
    except Exception as e:
        print(f"[FAST_CYCLE] checkpoint({label}) -> {type(e).__name__}: {e}")


def _free_ollama():
    """Release the GPU after a model-heavy step.

    22 Aug 2026 — THIS FUNCTION USED TO BE A LIE. Its whole body was `gc.collect()`,
    which frees Python objects and has no effect whatsoever on what Ollama holds in
    VRAM; twelve steps pass `free_after=True` in the belief that they are handing the
    GPU back. Measured on this box, they were handing back nothing.

    What it does now: outside the 8b window, unload the big model and pin the small
    one (keep_alive=-1) so the next step finds it already resident. Inside the window
    it deliberately does nothing — releasing 8b mid-window is the alternation this
    whole change exists to stop. Never raises; the GPU is not worth a cycle.
    """
    gc.collect()
    try:
        from core import model_window as _mw
        if not _mw.is_open():
            _mw.release_big()
            _mw.pin_small()
    except Exception as e:
        print(f"[FAST_CYCLE] _free_ollama -> {type(e).__name__}: {e}")

def _llm(prompt):
    try:
        from core.groq_backend import call_groq
        text = call_groq(prompt, max_tokens=1024)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        if "</think>" in text:
            text = text.split("</think>")[-1].strip()
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

def _write_snapshot(axis, folder, domain, data):
    out_dir = BASE / "snapshots" / domain / folder
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{folder}_snapshot_latest.json"
    data["snapshot_timestamp"] = _utc_now()
    data["axis"]               = axis
    data["source_type"]        = "LLM_FAST_CYCLE"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path

def _run(label, fn, free_after=False):
    # ── МОДЕЛЪТ СЕ СМЕНЯ ПО ПРОЗОРЕЦ, НЕ ПО СТЪПКА (22 авг 2026) ───────────
    # core/model_window.py opens the 8b window when the cycle reaches the first
    # step inside it and closes it after the last, unloading 8b and re-pinning 3b.
    # Driven from here, by the cycle's real position, because a caller that has to
    # REMEMBER to close a window is a caller that will one day forget.
    # FAIL-OPEN: a residency policy that raises must not cost a step.
    try:
        from core import model_window as _mw
        _mw.on_step(label)
    except Exception as e:
        print(f"[FAST_CYCLE] model_window.on_step({label}) -> "
              f"{type(e).__name__}: {e}")
    # 15 Aug 2026 (закон, т.1 и 3): преди да тръгне стъпка, се пита мозъкът какво
    # е казал за нея в beat(). Ако е решил "пропусни" — пропуска се и се записва
    # ЧИЯ е била преценката. Гръбнакът на одита не се пропуска по мнение
    # (core.brain.skipped_by_brain пази този списък).
    # Already done by the cycle this run is continuing? Then it is not done again.
    # Checked BEFORE the brain's opinion and before the contract opens, because a
    # step that is being skipped should not open a contract it will never finish.
    if _RESUME["active"]:
        try:
            from core.cycle_map import ALIASES as _AL
            if _AL.get(label, label) in _RESUME["skip"]:
                print(f"[FAST_CYCLE] {label} -> SKIPPED (resume: completed by "
                      f"{os.environ.get('CORTEX_RESUME_CYCLE_ID', '?')})")
                return
        except Exception as e:
            print(f"[FAST_CYCLE] resume gate for {label} -> "
                  f"{type(e).__name__}: {e} (running it)")
    try:
        from core.brain import skipped_by_brain as _skip, stance as _stance
        if _skip(label):
            print(f"[FAST_CYCLE] {label} -> SKIPPED BY BRAIN: "
                  f"{str(_stance().get('expect'))[:120]}")
            return
    except Exception:
        pass
    # ── СЪДЕНО ПО СЛЕДАТА, НЕ ПО МЪЛЧАНИЕТО (21 авг 2026) ──────────────────
    # Долният except печата един ред и продължава. Стъпка, която е глътнала
    # грешката си и не е записала нищо, изглежда в ЦЯЛАТА следа на цикъла точно
    # като стъпка, която си е свършила работата. core/step_contract.py мери
    # какво е ПИПНАЛА спрямо какво обикновено пипа: NO_EFFECT е тихият отказ.
    # Цена: две снимки на 4853 файла = ~0.8s на стъпка, ~42s на цикъл от 1h47m.
    # FAIL-OPEN: счупен контракт не бива да убива стъпка.
    _contract = None
    try:
        from core.step_contract import StepContract
        _contract = StepContract(label)
        _contract.__enter__()
    except Exception:
        _contract = None
    _completed = False
    try:
        fn()
        print(f"[FAST_CYCLE] {label} -> OK")
        _completed = True
    except Exception as e:
        # str(e) can be empty (e.g. bare MemoryError()) — always show the
        # exception type too, so a failure never renders as a blank message.
        print(f"[FAST_CYCLE] {label} -> FAILED: {type(e).__name__}: {e}")
        if _contract is not None:
            _contract.note_swallowed(f"{type(e).__name__}: {e}")
    finally:
        if _contract is not None:
            try:
                _contract.finish()
            except Exception:
                pass
    # ── ЗАВЪРШВАНЕТО СЕ ЗАПИСВА, НЕ ВЛИЗАНЕТО (22 авг 2026) ────────────────
    # Deliberately here and NOT inside beat(). beat() fires when a step is
    # ENTERED; a cycle that dies mid-step has beaten for it, and a checkpoint
    # written on entry would name that step as done and let a resume skip the
    # work it died in the middle of. Completion is the only thing worth
    # recording, and `_completed` is set on the success path only — the except
    # branch above swallows the error and carries on, so "we got here" is not
    # the same question as "it worked".
    # WRITE-ONLY TODAY. Nothing reads this to skip steps; --resume is item 3 and
    # is off by default. This exists so that tomorrow's resume has a real record
    # to stand on instead of an inferred one.
    if _completed:
        _checkpoint_step(label)
    if free_after:
        _free_ollama()
    gc.collect()  # release memory after every agent step

def _note_night(subject: str, detail: str) -> None:
    """Нощно събитие — това, което сутрешните доклади четат."""
    try:
        p = BASE / "memory" / "night_events.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _utc_now(), "subject": subject,
                                 "detail": detail[:600]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _web_intel_order():
    """Редът на осите според плана на деня — ПРИОРИТЕТ, не филтър.

    КОНСЕНСУС С KIMI, стъпка 8, т.3 (15 авг 2026). Проверих с grep: планът
    (memory/brain_cycle_plan.json) се четеше само от runner-а и от core/brain.py.
    Стъпката, която яде най-много от нощта, не знаеше какво мозъкът е поискал.
    Нарочно НЕ филтрирам: тесен фокус не бива да значи отрязани сетива. Осите,
    които мозъкът е посочил, минават НАПРЕД; всички останали ги следват. При
    изчерпан бюджет отрязаното е това, което той е сметнал за маловажно — негово
    решение, не мое.
    """
    try:
        from web_intelligence_agent import AXES
        allx = list(AXES.keys())
    except BaseException:          # виж run_web_intelligence: модулът може да sys.exit
        return None
    try:
        from core.brain import current_plan
        plan = current_plan() or {}
        if plan.get("_stale"):
            return None
        want = " ".join(str(plan.get(k, "")) for k in ("focus", "watch")).lower()
    except Exception:
        return None
    if not want.strip():
        return None
    first = [a for a in allx if any(w and w in a.lower()
                                    for w in want.replace(",", " ").split())]
    if not first:
        return None
    rest = [a for a in allx if a not in first]
    print(f"[FAST_CYCLE] web_intel ред по плана: първо {first[:5]} (+{len(rest)} след тях)")
    return first + rest


def run_web_intelligence():
    """КОНСЕНСУС С KIMI, стъпка 8 (15 авг 2026). Той подреди приоритета:
      „Първо бих направил точка 2 — SKIP да ГОРИ в night_events.jsonl."
      „Смърт от часовоя е ВИДИМА, но сляп цикъл, завършил 'успешно', е по-опасна лъжа."
      „Точка 3 е важна, но без 2 системата не знае, че е ослепяла."

    Затова тук има три неща, които преди нямаше:
      1. МЪЛЧАНИЕТО ГОРИ. ImportError вече не е тихо „SKIP" — записва се като
         нощно събитие и влиза в сутрешния доклад. Цикъл, вървял без сетива, не
         може да се отчете като нормален.
      2. СОБСТВЕН БЮДЖЕТ. Таванът стоеше само в часовоя, тоест единственият изход
         при бавност беше да бъде убит ЦЕЛИЯТ цикъл. Сега стъпката се пуска в
         отделен процес със свой срок (таванът минус запас) и при изтичане се
         прекратява САМА, запазвайки каквото вече е записала на диска. Деградация
         вместо смърт.
      3. РЕДЪТ Е ПО ПЛАНА (виж _web_intel_order) — приоритет, не филтър.
    """
    # НАМЕРЕНО ПРИ ТЕСТА, 15 авг 2026 — по-лошо от трите точки по-горе.
    # web_intelligence_agent вика sys.exit(1) при липсващ feedparser, ПРИ ИМПОРТ.
    # SystemExit НЕ Е ImportError и НЕ Е Exception — тоест старият
    #     except ImportError: ... except Exception: ...
    # не хващаше нищо, и липсата на ЕДИН незадължителен пакет убиваше ЦЕЛИЯ цикъл
    # на стъпка 1, без обяснение в пулса. Мина незабелязано само защото на машината
    # feedparser е инсталиран. Затова тук се лови BaseException.
    try:
        import web_intelligence_agent  # noqa: F401
    except BaseException as e:
        print(f"[FAST_CYCLE] web_intelligence_agent -> НЕ СЕ ЗАРЕЖДА: "
              f"{type(e).__name__}: {e}")
        _note_night("ЦИКЪЛЪТ ВЪРВЯ СЛЯП",
                    f"web_intelligence не се зареди ({type(e).__name__}: {e}); нощта "
                    f"минава без свободно търсене в мрежата. Това НЕ е нормален цикъл.")
        gc.collect()
        return

    ceiling = 3600
    try:
        ceiling = int((json.loads((BASE / "config" / "scheduler.json")
                                  .read_text(encoding="utf-8")).get("step_ceilings_sec")
                       or {}).get("web_intelligence", 3600))
    except Exception:
        pass
    budget = max(300, ceiling - 300)          # запас, за да свърши ПРЕДИ часовоя

    order = _web_intel_order()
    code = ("import sys, json; sys.path.insert(0, %r);"
            "import web_intelligence_agent as w;"
            "w.run(axes_filter=%r)" % (str(BASE), order))
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=str(BASE),
                           timeout=budget)
        took = round(time.time() - t0)
        if r.returncode == 0:
            print(f"[FAST_CYCLE] web_intelligence_agent -> OK ({took}s)")
        else:
            print(f"[FAST_CYCLE] web_intelligence_agent -> exit {r.returncode} ({took}s)")
            _note_night("web_intelligence падна",
                        f"exit={r.returncode} след {took}s; каквото е записано на "
                        f"диска остава, останалото липсва")
    except subprocess.TimeoutExpired:
        took = round(time.time() - t0)
        print(f"[FAST_CYCLE] web_intelligence_agent -> БЮДЖЕТЪТ ИЗТЕЧЕ след {took}s; "
              f"спирам сама, вместо да чакам часовоя да убие цикъла")
        _note_night("web_intelligence спряна по бюджет",
                    f"{took}s от таван {ceiling}s. Частичен резултат: каквото е "
                    f"стигнало до диска. Редът беше "
                    f"{'по плана на мозъка' if order else 'по подразбиране'}.")
    except Exception as e:
        print(f"[FAST_CYCLE] web_intelligence_agent -> FAILED: {type(e).__name__}: {e}")
        _note_night("web_intelligence се провали", f"{type(e).__name__}: {e}")
    gc.collect()

def refresh_llm_axes():
    # 21 авг 2026: GENERAL_SELF_REVIEW излезе оттук заедно с осата. Тази стъпка
    # викаше core.cortex_reasoner.self_review(), който взимаше думата на облачен
    # модел за самия CORTEX ("HIGH"/"MEDIUM"/"LOW"), превеждаше я в 85/55/25 и я
    # подаваше на continuous_learner като СКОР. Тоест системата се оценяваше сама
    # с число, което после пътуваше като измерване. Самонаблюдението вече върви
    # през core/self_mirror.py и не произвежда нито едно число за композита.
    axes = [
        {
            "axis": "GOAL_PROGRESS_REVIEW",
            "folder": "goal_progress",
            "domain": "cosmos",
            "prompt": (
                "You are CORTEX++ AGI working toward: sustainable civilization, "
                "dignity for all, AGI in transparent service of humanity. "
                "Generate JSON for GOAL_PROGRESS_REVIEW. Include: "
                "current_level (LOW/MEDIUM/HIGH), overall_progress_pct (0-100), "
                "progress_by_domain dict (HUMAN/PLANET/CIVILIZATION/COSMOS each 0-100), "
                "main_bottlenecks list, next_actions list. Return ONLY valid JSON."
            ),
        },
        {
            "axis": "LONG_TERM_FUTURE_REVIEW",
            "folder": "long_term_future",
            "domain": "cosmos",
            "prompt": (
                "Generate fresh JSON for LONG_TERM_FUTURE_REVIEW "
                "(existential risks: nuclear, AGI misalignment, biorisks, climate collapse). "
                "Include: current_level, xrisk_score (0-100, lower=safer), "
                "main_risks list, trends list. Return ONLY valid JSON."
            ),
        },
    ]
    for cfg in axes:
        print(f"[FAST_CYCLE] refreshing {cfg['axis']}...")
        if cfg.get("use_reasoner"):
            from core.cortex_reasoner import self_review
            snap = self_review()
        else:
            snap = _llm(cfg["prompt"])
        path = _write_snapshot(cfg["axis"], cfg["folder"], cfg["domain"], snap)
        print(f"[FAST_CYCLE] wrote {cfg['axis']} -> {path}")
    _free_ollama()

def run_trend_tracker():
    print("[FAST_CYCLE] running trend_tracker...")
    r = subprocess.run(
        [sys.executable, "-m", "memory.trend_tracker"],
        cwd=str(BASE), capture_output=False, timeout=120
    )
    print(f"[FAST_CYCLE] trend_tracker -> {'OK' if r.returncode == 0 else 'FAILED'}")

def update_master():
    snap_dir  = BASE / "snapshots"
    snapshots = {}
    for json_file in sorted(snap_dir.rglob("*_snapshot_latest.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            axis = data.get("axis", json_file.stem)
            if axis != "master_snapshot_latest":
                snapshots[axis] = data
        except Exception:
            pass
    out = BASE / "snapshots" / "master" / "master_snapshot_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "report_type": "MASTER_CIVILIZATION_SNAPSHOT",
        "timestamp":   _utc_now(),
        "cycle_type":  "FAST_CYCLE",
        "axes_count":  len(snapshots),
        "axes":        list(snapshots.keys()),
        "snapshots":   snapshots,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[FAST_CYCLE] master updated — {len(snapshots)} axes")


def _check_dependencies() -> bool:
    """Step 0 — проверява API ключове и Groq свързаност преди цикъла."""
    out_path = BASE / "snapshots" / "master" / "dependency_check_latest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Зарежда .env в os.environ (само ако ключът не е вече зареден).
    # 14 Aug 2026: първо се търси ~/.cortex/.env — ИЗВЪН дървото на репото, което
    # самогенерирани patch-ове могат да четат. Преместването е решение на Емил
    # (copy .env %USERPROFILE%\.cortex\.env); дотогава репо-копието продължава да работи.
    _user_env = pathlib.Path.home() / ".cortex" / ".env"
    env_path = _user_env if _user_env.exists() else (BASE / ".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip()

    checks      = {}
    critical_ok = True

    # КОНСЕНСУС С KIMI, стъпка 6: „Groq като единствен critical превръща резервната
    # верига в ДЕКОР — един срив убива нощта въпреки четири живи пътя и локален
    # мозък." И: „Ollama непроверен е СЛЕПОТА: той е fallback И законен мозък на
    # всяка стъпка, но единствен непроверен."
    # Затова критерият вече не е „този ключ го има", а „има ли поне един път до
    # мислене". Цикълът спира само когато НИЩО не мисли — и тогава спира честно,
    # защото тогава мозъкът наистина не може да се произнесе: той е падналото.
    _paths = []

    # ── Self-heal (14 Aug 2026): the ddgs search package was missing for weeks and
    # web intelligence ran blind — a dependency the system can install for itself.
    # Narrow by design: ONE hardcoded, known-safe package, own venv, logged, fail-open.
    # This is self-maintenance inside the machine, not an action on the world.
    # КОНСЕНСУС С KIMI, стъпка 6, 15 авг 2026: „pip install без надзор е ДУПКА,
    # не бордюр." Съгласен съм и махам самоинсталацията. Досега липсващ пакет се
    # доизтегляше от мрежата всяка нощ, без човек да е казал дума — тоест системата
    # изпълняваше чужд код от интернет вътре в собствения си процес. Че пакетът е
    # един и известен, не променя рода на действието; променя само вероятността.
    # Сега липсата се ЗАПИСВА като предложение за човека и се вижда в известията.
    try:
        import ddgs  # noqa: F401
        checks["pkg_ddgs"] = {"present": True, "level": "optional"}
    except ImportError:
        checks["pkg_ddgs"] = {"present": False, "level": "optional",
                              "needs_human": "pip install ddgs"}
        print("[DEP_CHECK] MISSING ddgs (optional) -> proposed to human, NOT self-installed")
        try:
            _props = BASE / "memory" / "improvement_proposals.json"
            _cur = json.loads(_props.read_text(encoding="utf-8")) if _props.exists() else []
            if isinstance(_cur, list) and not any(
                    "ddgs" in str(x.get("title", "")) for x in _cur if isinstance(x, dict)):
                _cur.append({"ts": _utc_now(), "source": "dependency_check",
                             "title": "Липсва пакет ddgs (търсене в мрежата)",
                             "detail": "Web intelligence върви сляпо без него. "
                                       "Инсталацията е ЧОВЕШКО действие: pip install ddgs",
                             "needs_human": True})
                _props.write_text(json.dumps(_cur, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        except Exception:
            pass

    # 1. Проверка на ключове
    key_levels = {
        "GROQ_API_KEY":       "thinking_path",
        "CEREBRAS_API_KEY":   "thinking_path",
        "OPENROUTER_API_KEY": "thinking_path",
        "GEMINI_API_KEY":     "thinking_path",
        "YOUTUBE_API_KEY":    "optional",
        "NASA_API_KEY":       "optional",
    }
    for key, level in key_levels.items():
        present = bool(os.environ.get(key))
        checks[key] = {"present": present, "level": level}
        if present and level == "thinking_path":
            _paths.append(key)
        print(f"[DEP_CHECK] {'OK' if present else 'MISSING':7s} {key} ({level})")

    # ЛОКАЛНИЯТ МОЗЪК — досега единственият непроверен, макар по закон да е на всяка
    # стъпка. Пита се самият Ollama кои модели държи; отговор = път до мислене.
    try:
        import requests as _rq
        from core.groq_backend import _OLLAMA_URL as _OL
        _r = _rq.get(f"{_OL}/api/tags", timeout=8)
        _models = [m.get("name") for m in (_r.json().get("models") or [])] if _r.ok else []
        checks["local_brain"] = {"ok": bool(_models), "url": _OL, "models": _models[:6]}
        if _models:
            _paths.append("local_brain")
            print(f"[DEP_CHECK] OK      local_brain ({len(_models)} model(s))")
        else:
            print(f"[DEP_CHECK] FAIL    local_brain: няма модели на {_OL}")
    except Exception as _oe:
        checks["local_brain"] = {"ok": False, "error": f"{type(_oe).__name__}: {_oe}"[:140]}
        print(f"[DEP_CHECK] FAIL    local_brain: {type(_oe).__name__}")

    # 2. Тестов call към Groq chat — директна HTTP заявка с requests.
    #    429 (rate limit) = ключът е валиден, API достъпно → третираме като OK.
    #    Не викаме call_groq() за да не задействаме 60s cooldown в главния цикъл.
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if groq_key:
        try:
            import requests as _req
            from core.groq_backend import GROQ_API_URL, GROQ_MODEL
            r = _req.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 3},
                timeout=15,
            )
            # 200 = success, 429 = rate limited but key is valid and endpoint reachable
            if r.status_code in (200, 429):
                checks["groq_chat"] = {"ok": True, "http": r.status_code}
                print(f"[DEP_CHECK] OK      groq_chat (HTTP {r.status_code})")
            else:
                checks["groq_chat"] = {"ok": False, "error": f"HTTP {r.status_code}"}
                print(f"[DEP_CHECK] FAIL    groq_chat: HTTP {r.status_code} "
                      f"(не е фатално — има други пътища)")
                if "GROQ_API_KEY" in _paths:
                    _paths.remove("GROQ_API_KEY")
        except Exception as e:
            checks["groq_chat"] = {"ok": False, "error": str(e)[:150]}
            print(f"[DEP_CHECK] FAIL    groq_chat: {e} (не е фатално)")
            if "GROQ_API_KEY" in _paths:
                _paths.remove("GROQ_API_KEY")
    else:
        checks["groq_chat"] = {"ok": False, "error": "no key"}

    # 3. Groq Whisper — same key as groq_chat; ако chat мина, Whisper ще мине също
    if checks.get("groq_chat", {}).get("ok"):
        checks["groq_whisper"] = {"ok": True, "note": "key verified via groq_chat"}
        print("[DEP_CHECK] OK      groq_whisper (key verified via groq_chat)")
    else:
        checks["groq_whisper"] = {"ok": False, "note": "skipped — groq_chat failed"}
        print("[DEP_CHECK] SKIP    groq_whisper (groq_chat failed)")

    # ЕДИНСТВЕНОТО фатално условие: нито един път до мислене.
    critical_ok = bool(_paths)
    checks["thinking_paths"] = {"alive": _paths, "count": len(_paths)}
    print(f"[DEP_CHECK] {'OK' if critical_ok else 'FATAL':7s} пътища до мислене: "
          f"{', '.join(_paths) if _paths else 'НИТО ЕДИН'}")

    report = {
        "timestamp":       _utc_now(),
        "all_critical_ok": critical_ok,
        "thinking_paths":  _paths,
        "checks":          checks,
        "note":            "" if critical_ok else (
            "ЦИКЪЛЪТ Е СПРЯН: няма НИТО ЕДИН път до мислене — нито външен доставчик, "
            "нито локалният мозък. Това е единственото условие, при което спираме."
        ),
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return critical_ok


def _strategist_to_proposals():
    snap_path     = BASE / "snapshots" / "cortex_strategist" / "cortex_strategist_snapshot_latest.json"
    proposals_path = BASE / "memory" / "improvement_proposals.json"
    if not snap_path.exists():
        print("[FAST_CYCLE] strategist_to_proposals -> no snapshot yet")
        return
    try:
        data = json.loads(snap_path.read_text(encoding="utf-8"))
        new_proposals = []
        for act in data.get("immediate_actions", []):
            new_proposals.append({
                "component":       "unknown",
                "problem":         act.get("why", "CortexStrategist action"),
                "solution":        act.get("action", ""),
                "measurable_goal": act.get("action", "")[:80],
                "root_cause":      f"CortexStrategist scan -> {act.get('file', 'unknown')}",
                "priority":        "HIGH",
                "real_world_signal": True,
                "generated_by":    "CORTEX_STRATEGIST",
                "timestamp":       _utc_now(),
            })
        for gap in data.get("critical_gaps", []):
            if gap.get("impact") == "HIGH":
                new_proposals.append({
                    "component":       "unknown",
                    "problem":         gap.get("gap", ""),
                    "solution":        gap.get("fix", ""),
                    "measurable_goal": gap.get("gap", "")[:80],
                    "root_cause":      "Critical gap -- CortexStrategist full-scan",
                    "priority":        "HIGH",
                    "real_world_signal": True,
                    "generated_by":    "CORTEX_STRATEGIST",
                    "timestamp":       _utc_now(),
                })
        if not new_proposals:
            print("[FAST_CYCLE] strategist_to_proposals -> 0 HIGH proposals")
            return
        try:
            existing = json.loads(proposals_path.read_text(encoding="utf-8"))
            existing_list = existing.get("proposals", existing) if isinstance(existing, dict) else existing
        except Exception:
            existing_list = []
        merged = new_proposals + [p for p in existing_list if p.get("generated_by") != "CORTEX_STRATEGIST"]
        proposals_path.write_text(
            json.dumps({"proposals": merged}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[FAST_CYCLE] strategist_to_proposals -> {len(new_proposals)} proposals injected")
    except Exception as e:
        print(f"[FAST_CYCLE] strategist_to_proposals -> FAILED: {e}")


def _hyperclaw_to_proposals():
    """Convert the latest HyperClaw markdown plan to improvement proposals."""
    plans_dir = BASE / "plans"
    proposals_path = BASE / "memory" / "improvement_proposals.json"
    if not plans_dir.exists():
        return
    plan_files = sorted(plans_dir.glob("plan-*.md"), key=lambda p: p.name, reverse=True)
    if not plan_files:
        print("[FAST_CYCLE] hyperclaw_to_proposals -> no plan file found")
        return
    plan_text = plan_files[0].read_text(encoding="utf-8", errors="ignore")
    new_proposals = []
    current_axis = None
    import re as _re
    _bold_re      = _re.compile(r'\*{1,2}([^*]+)\*{1,2}')
    _obj_re       = _re.compile(r'^\*{0,2}OBJECTIVE\*{0,2}\s*:', _re.IGNORECASE)
    _step_num_re  = _re.compile(r'^\d+\.\s+(.+)')
    _step_dash_re = _re.compile(r'^-\s+STEP\s+\d+\s*[:.~]?\s*(.+)', _re.IGNORECASE)

    def _clean(text: str) -> str:
        return _bold_re.sub(r'\1', text).strip()

    for line in plan_text.splitlines():
        line = line.strip()
        for marker in ("HUMAN_AXIS_FOCUS", "PLANET_AXIS_FOCUS", "CIVILIZATION_AXIS_FOCUS", "COSMOS_AXIS_FOCUS"):
            if marker in line:
                current_axis = marker.replace("_AXIS_FOCUS", "")
        if current_axis and _obj_re.match(line):
            objective = _clean(_obj_re.sub("", line, count=1))
            if objective and "<" not in objective and len(objective) > 10:
                new_proposals.append({
                    "component":         current_axis,
                    "problem":           f"{current_axis} axis needs progress",
                    "solution":          objective,
                    "measurable_goal":   objective[:80],
                    "root_cause":        f"HyperClaw plan — {plan_files[0].name}",
                    "priority":          "MEDIUM",
                    "real_world_signal": True,
                    "generated_by":      "HYPERCLAW",
                    "timestamp":         _utc_now(),
                })
        if current_axis:
            m = _step_num_re.match(line) or _step_dash_re.match(line)
            if m:
                step = _clean(m.group(1))
                if step and "<" not in step and len(step) > 10:
                    new_proposals.append({
                        "component":         current_axis,
                        "problem":           f"Action required for {current_axis}",
                        "solution":          step,
                        "measurable_goal":   step[:80],
                        "root_cause":        f"HyperClaw step — {plan_files[0].name}",
                        "priority":          "MEDIUM",
                        "real_world_signal": True,
                        "generated_by":      "HYPERCLAW",
                        "timestamp":         _utc_now(),
                    })
    if not new_proposals:
        if len(plan_text) > 500:
            print("[FAST_CYCLE] hyperclaw_to_proposals -> 0 steps from non-empty plan (parser drift?)")
        else:
            print("[FAST_CYCLE] hyperclaw_to_proposals -> 0 concrete steps extracted")
        return
    try:
        existing = json.loads(proposals_path.read_text(encoding="utf-8"))
        existing_list = existing.get("proposals", existing) if isinstance(existing, dict) else existing
    except Exception:
        existing_list = []
    merged = new_proposals + [p for p in existing_list if p.get("generated_by") != "HYPERCLAW"]
    proposals_path.write_text(
        json.dumps({"proposals": merged}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[FAST_CYCLE] hyperclaw_to_proposals -> {len(new_proposals)} proposals injected")


def _scan_needs_reanalysis() -> list[dict]:
    """
    Сканира всички snapshot JSON файлове за needs_reanalysis: true.
    Връща списък от {"axis", "file", "error"} — за логване и приоритизиране.
    Резултатът се записва в snapshots/master/needs_reanalysis_latest.json
    за да може initiative_tracker / cortex_strategist да го намерят.
    """
    # КОНСЕНСУС С KIMI, стъпка 7 (15 авг 2026), т.2: „45GB rglob е отделен грях —
    # трябва индекс, не сканиране на архива." Архивът е ИСТОРИЯ; флагът живее само
    # в живите снимки. Пропускаме архива и всичко под него.
    snap_dir = BASE / "snapshots"
    _SKIP_PARTS = {"master", "self_archive", "__pycache__"}
    flagged = []
    for path in snap_dir.rglob("*.json"):
        if _SKIP_PARTS & set(path.parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # т.1: флагът се ГАСИ със заключение, не с чистене — щом на оста е
            # сложен reanalysis_resolved_at, тя вече не чака работа.
            if isinstance(data, dict) and data.get("reanalysis_resolved_at"):
                continue
            if isinstance(data, dict) and data.get("needs_reanalysis"):
                axis = data.get("axis") or data.get("axis_name") or path.stem
                flagged.append({
                    "axis":  axis,
                    "file":  str(path.relative_to(BASE)),
                    "error": data.get("error", ""),
                })
        except Exception:
            continue

    out = BASE / "snapshots" / "master" / "needs_reanalysis_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"timestamp": _utc_now(), "count": len(flagged), "axes": flagged},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return flagged


def _resolve_reanalysis() -> int:
    """Гаси флага „чака преразглеждане" — КОНСЕНСУС С KIMI, стъпка 7, 15 авг 2026.

    Той: „Съгласен — гасенето е ЗАКЛЮЧЕНИЕ: нов успешен запис за оста трябва да
    носи reanalysis_resolved_at, иначе silent overwrite оставя флага висок."
    И: „Нов риск: ако гасенето е на стъпка, която после се пропуска, флагът остава
    висок ЗАВИНАГИ — зависимост от несигурна стъпка. Гасенето да е в update_master
    (12) или scoring_engine (12.4), които са в ГРЪБНАКА, не в пропускаеми."
    Затова живее тук и се вика от update_master — стъпка, която мозъкът няма право
    да пропусне.

    Критерият е доказателство, не изтекло време: за ос с вдигнат флаг търсим
    ПО-НОВА снимка на същата ос БЕЗ флаг. Има ли такава — старата се подпечатва
    като разрешена. Няма ли — флагът си стои, колкото и стар да е.
    """
    idx = BASE / "snapshots" / "master" / "needs_reanalysis_latest.json"
    try:
        flagged = (json.loads(idx.read_text(encoding="utf-8")) or {}).get("axes", [])
    except Exception:
        return 0
    if not flagged:
        return 0

    # най-новата ЧИСТА снимка на всяка ос
    newest_clean = {}
    _SKIP_PARTS = {"master", "self_archive", "__pycache__"}
    for path in (BASE / "snapshots").rglob("*.json"):
        if _SKIP_PARTS & set(path.parts):
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or d.get("needs_reanalysis"):
                continue
            ax = d.get("axis") or d.get("axis_name") or path.stem
            m = path.stat().st_mtime
            if m > newest_clean.get(ax, (0, None))[0]:
                newest_clean[ax] = (m, path)
        except Exception:
            continue

    n = 0
    for item in flagged:
        ax, rel = item.get("axis"), item.get("file")
        old_p = BASE / str(rel)
        try:
            old_m = old_p.stat().st_mtime
        except Exception:
            continue
        cand = newest_clean.get(ax)
        if not cand or cand[0] <= old_m:
            continue                      # няма по-нов чист запис -> флагът остава
        try:
            d = json.loads(old_p.read_text(encoding="utf-8"))
            d["reanalysis_resolved_at"] = _utc_now()
            d["reanalysis_resolved_by"] = str(cand[1].relative_to(BASE))
            old_p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
            n += 1
        except Exception:
            continue
    if n:
        print(f"[FAST_CYCLE] reanalysis: {n} ос(и) разрешени с по-нов чист запис")
    return n


def _load_directives() -> dict:
    """Read adaptive_directives.json written by body_scanner. Safe fallback to defaults."""
    p = BASE / "memory" / "adaptive_directives.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"cycle_mode": "FULL", "max_parallel_workers": 3, "llm_sleep_secs": 10}


def _send_windows_toast(title: str, body: str) -> None:
    """Send a Windows balloon notification via PowerShell NotifyIcon."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$n = New-Object System.Windows.Forms.NotifyIcon; "
        "$n.Icon = [System.Drawing.SystemIcons]::Warning; "
        "$n.BalloonTipIcon = 'Warning'; "
        "$n.BalloonTipTitle = $env:NOTIFY_TITLE; "
        "$n.BalloonTipText  = $env:NOTIFY_BODY; "
        "$n.Visible = $true; "
        "$n.ShowBalloonTip(30000); "
        "Start-Sleep -Milliseconds 500; "
        "$n.Dispose()"
    )
    env = {**os.environ, "NOTIFY_TITLE": title[:63], "NOTIFY_BODY": body[:255]}
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, timeout=15, env=env,
        )
    except Exception as e:
        print(f"[NOTIFY] toast failed: {e}")


def _get_pending_patches() -> list[str]:
    """Scan agents/core/*_patch.py for sensitive patches; return list of flagged filenames."""
    import re as _re
    _RULES = [
        (_re.compile(r"execute_patches"),                              "пипа execute_patches.py"),
        (_re.compile(r"self_modifier"),                                "пипа self_modifier.py"),
        (_re.compile(r"""["']git[\s"']"""),                            "git операция"),
        (_re.compile(r'subprocess[^\n]*"git'),                         "git subprocess"),
        (_re.compile(r"(?i)(password|secret)\s*=\s*[\"'][^\"']{4,}"), "credentials"),
        (_re.compile(r"open\s*\([^)]*\.env"),                          "пише в .env"),
    ]
    _DEL = _re.compile(r"(os\.remove|\.unlink\b|shutil\.rmtree|shutil\.rmdir)")

    pending = []
    for patch in sorted((BASE / "agents" / "core").glob("*_patch.py")):
        try:
            content = patch.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pending.append(patch.name)
            continue
        for line in content.splitlines():
            if line.strip().startswith("#"):
                continue
            hit = next((msg for rx, msg in _RULES if rx.search(line)), "")
            if not hit and _DEL.search(line) and "patch" not in line.lower():
                hit = "изтрива файл"
            if hit:
                pending.append(patch.name)
                break
    return pending


def _witness_or_refuse(step: str, prev_step: str) -> bool:
    """Има ли символен свидетел за тази необратима стъпка.

    КОНСЕНСУС С KIMI, 15 авг 2026. Той:
      „Не стига — обявяваш отсъствие, но продължаваш. Това е монолог, не диалог."
    Прав беше. Дотогава липсата на MeTTa се записваше в дневника и нищо повече —
    тоест струваше точно нула. Сега струва: трите стъпки, които пипат СВЕТА
    (github_publish) и СЕБЕ СИ (self_modifier, execute_patches), не тръгват без
    свидетел. Всичко останало — сетива, оценяване, дедукция, отчет — върви.
    Границата пак е на ДЕЙСТВИЕТО, не на мисълта (закон, т.4)."""
    # ВТОРИЯТ СВИДЕТЕЛ Е ЧОВЕКЪТ (консенсус с Kimi, стъпка 4, 15 авг 2026):
    # „Приложи същата логика като при MeTTa: отказ на външен свидетел = freeze на
    # необратимите, не спиране на цикъла." Мъртъв канал значи, че снощната ЗАБРАНА
    # може да не е стигнала дотук — значи не се действа необратимо. Празен inbox
    # (200 OK) НЕ е отказ, и ненастроен канал НЕ е отказ.
    _why_human = ""
    try:
        from experiments.needs.approve_reader import channel_alive
        _ok_human, _why_human = channel_alive()
        if not _ok_human:
            print(f"[FAST_CYCLE] {step} -> ОТКАЗАНА: човешкият канал е мъртъв "
                  f"({_why_human}). Снощната забрана може да не е стигнала дотук.")
            return False
    except Exception:
        pass
    # ── ПОРТАТА ЧЕТЕ ПЕЧАТИТЕ (Kimi, 15 авг 2026) ──────────────────────────
    # „Стъпка 18 може да има твърда порта, но ако входът ѝ е роден на стъпка 5 при
    #  channel_alive=false, портата е СЛЯПА."
    # Дотук тази функция гледаше само СЕГАШНОТО състояние (жив ли е свидетелят,
    # жив ли е каналът). Сега пита нотариуса, който носи и ПРОИЗХОДА на входовете:
    # наследено най-лошо, освен ако по пътя е имало независима верификация.
    try:
        from core.notary import may_act
        ok, why = may_act(step, prev_step)
        if ok:
            return True
        print(f"[FAST_CYCLE] {step} -> ОТКАЗАНА: {why}")
        try:
            from memory.heartbeat import BASE as _B
            import json as _j
            from datetime import datetime as _dt, timezone as _tz
            with open(_B / "memory" / "night_events.jsonl", "a", encoding="utf-8") as fh:
                fh.write(_j.dumps({"ts": _dt.now(_tz.utc).isoformat(),
                                   "subject": f"{step} ОТКАЗАНА от нотариуса",
                                   "detail": why}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"[FAST_CYCLE] {step} -> нотариусът е недостъпен: {type(e).__name__}: {e}")

    try:
        from core.metta_check import witness_present
        if witness_present():
            return True
    except Exception as e:
        print(f"[FAST_CYCLE] {step} -> witness check failed: {type(e).__name__}: {e}")
    print(f"[FAST_CYCLE] {step} -> ОТКАЗАНА: няма символен свидетел (MeTTa не е на "
          f"линия). Необратимо действие без проверка не се прави.")
    try:
        from memory.heartbeat import BASE as _B
        import json as _j
        from datetime import datetime as _dt, timezone as _tz
        with open(_B / "memory" / "night_events.jsonl", "a", encoding="utf-8") as fh:
            fh.write(_j.dumps({"ts": _dt.now(_tz.utc).isoformat(),
                               "subject": f"{step} ОТКАЗАНА",
                               "detail": "няма символен свидетел (MeTTa); необратимите "
                                         "стъпки спират, останалите вървят"},
                              ensure_ascii=False) + "\n")
    except Exception:
        pass
    return False


def _notify_patches_and_initiatives() -> None:
    """Run initiative tracker then send a single Windows notification combining
    pending code patches and PROPOSED/IN_PROGRESS initiatives."""
    # 1. Pending code patches
    pending_patches = _get_pending_patches()
    if pending_patches:
        print(f"[NOTIFY] {len(pending_patches)} patch(es) чакат одобрение: "
              f"{', '.join(pending_patches[:4])}" +
              (f" +{len(pending_patches)-4}" if len(pending_patches) > 4 else ""))
    else:
        print("[NOTIFY] няма patches чакащи одобрение")

    # 2. Run initiative tracker → creates data/initiatives/*.json
    active_initiatives: list[dict] = []
    try:
        from initiative_tracker import run as _it_run
        active_initiatives = _it_run()
    except Exception as e:
        print(f"[NOTIFY] initiative_tracker FAILED: {e}")

    if active_initiatives:
        prop  = sum(1 for i in active_initiatives if i.get("status") == "PROPOSED")
        prog  = sum(1 for i in active_initiatives if i.get("status") == "IN_PROGRESS")
        print(f"[NOTIFY] initiatives — PROPOSED={prop} IN_PROGRESS={prog}")
        for init in active_initiatives[:3]:
            print(f"[NOTIFY]   [{init['status']:11s}] {init['milestone'][:60]}  → {init['target_date']}")

    # 3. Build combined notification
    if not pending_patches and not active_initiatives:
        return

    body_parts: list[str] = []

    if pending_patches:
        patch_list = ", ".join(pending_patches[:5])
        if len(pending_patches) > 5:
            patch_list += f" +{len(pending_patches)-5}"
        body_parts.append(f"Patches({len(pending_patches)}): {patch_list}")

    if active_initiatives:
        prop  = sum(1 for i in active_initiatives if i.get("status") == "PROPOSED")
        prog  = sum(1 for i in active_initiatives if i.get("status") == "IN_PROGRESS")
        counts = []
        if prop: counts.append(f"{prop} PROPOSED")
        if prog: counts.append(f"{prog} IN_PROGRESS")
        # append first initiative milestone for context
        first = active_initiatives[0]
        body_parts.append(
            f"Initiatives({', '.join(counts)}): {first['milestone'][:50]}"
        )

    if pending_patches and active_initiatives:
        title = f"CORTEX++ — {len(pending_patches)} patch(es) + {len(active_initiatives)} initiatives"
    elif pending_patches:
        title = f"CORTEX++ — {len(pending_patches)} patch(es) чакат одобрение"
    else:
        title = f"CORTEX++ — {len(active_initiatives)} active initiatives"

    body = " | ".join(body_parts)
    print(f"[NOTIFY] {title}")
    _send_windows_toast(title, body)


def main():
    print("=" * 50)
    print(f"[FAST_CYCLE] started at {_utc_now()}")
    print("=" * 50)

    # Proof of life BEFORE the first real step. _notify_patches_and_initiatives()
    # below runs initiative_tracker + a PowerShell toast and can take minutes; a
    # death there left NO heartbeat at all, so the supervisor recorded
    # last_step="unknown". We stamp the heartbeat with the SUPERVISOR's cycle_id
    # (passed in via the CORTEX_CYCLE_ID env it sets at spawn) so that
    # supervisor._last_step_of() attributes the death to THIS cycle instead of
    # discarding the step on a cycle_id mismatch. Every later beat() preserves this
    # cycle_id, so attribution now works for deaths at any step, not only early ones.
    # ── КОНСЕНСУС С KIMI, 15 авг 2026 (стъпка 1 от 52) ─────────────────────
    # Той намери режима на отказ, който е по-лош от грешна атрибуция:
    #   „heartbeat.json се пише с ГРЕШЕН cycle_id (stale CORTEX_CYCLE_ID от env на
    #    предишен цикъл). Супервайзорът търси cycle_id=X, намира last_step=boot,
    #    мисли че цикълът тече, а реално е мъртъв на стъпка 35. НЕ РЕСТАРТИРА."
    # Тоест не срив, а ФАЛШИВО СПОКОЙСТВИЕ — най-опасното за система без надзор.
    # Той поиска твърда проверка „env строго по-нов от последния"; аз възразих, че
    # това убива ръчното пускане (там env изобщо липсва). Стигнахме до три случая,
    # плюс неговото последно уточнение: НЕЧЕТИМ env е системен отказ, не ръчно
    # пускане, значи се третира като C.
    _cycle_id = _classify_cycle_id(os.environ.get("CORTEX_CYCLE_ID"))

    # ── A CYCLE STARTED BY HAND MUST ALSO LEAVE A LOG (21 Aug 2026) ─────────
    # supervisor.spawn_cycle() redirects this process's stdout into
    # memory/cycle_logs/cycle_<stamp>.log. A cycle started by hand — which is
    # step 3 of the alarm the supervisor sends when it gives up,
    # `venv\Scripts\python.exe fast_cycle_runner.py` — had no such redirect,
    # and since 17 Aug the child runs with DETACHED_PROCESS, i.e. with no
    # console at all. So the run a human started BECAUSE the automatic one
    # failed was the one that left nothing to read.
    #
    # IDEMPOTENT BY EVIDENCE, NOT BY A FLAG: the supervisor opens that exact
    # path with mode "w" before spawning us, so core.cycle_log.tee_stdio()
    # refuses when the file already exists. An env var would be one wrapper away
    # from being lost; the file either is there or is not.
    try:
        from core.cycle_log import tee_stdio as _tee
        _tee_rec = _tee(_cycle_id)
        print(f"[FAST_CYCLE] cycle log: {_tee_rec['path']} "
              f"(teeing={_tee_rec['teeing']}; {_tee_rec['why']})")
    except Exception as _e:
        print(f"[FAST_CYCLE] cycle log tee unavailable: {type(_e).__name__}: {_e}")

    beat("boot", "-1", cycle_id=_cycle_id)

    # ── РЕШЕНИЕТО ЗА ПРОДЪЛЖАВАНЕ СЕ ВЗИМА ВЕДНЪЖ, ТУК (22 авг 2026) ───────
    # Taken once, at the top, so that the reason is in the log ABOVE the first
    # step it affects — a skip line explained two hundred lines later is not an
    # explanation. Default is off; only a supervisor RESTART passes --resume.
    global _RESUME
    _RESUME = _decide_resume(sys.argv)
    if _RESUME["active"]:
        print(f"[FAST_CYCLE] RESUME ACTIVE: {_RESUME['reason']}")
        print(f"[FAST_CYCLE] resume will skip {len(_RESUME['skip'])} step(s) "
              f"already recorded complete: "
              f"{', '.join(sorted(_RESUME['skip'])) or '(none)'}")
        if _RESUME["seal_only"]:
            print("[FAST_CYCLE] RESUME: every step completed but the cycle never "
                  "sealed — this run exists to seal it")
    else:
        print(f"[FAST_CYCLE] resume OFF: {_RESUME['reason']}")

    # A new cycle walks the step list from the top. The window's cursor is what
    # tells a repeated step name (body_scan appears at index 1 AND index 35) which
    # occurrence it is at; carried over from a previous run it would resolve every
    # early step to a late position and open the 8b window at boot.
    try:
        from core import model_window as _mw
        _mw.reset_cursor()
    except Exception as e:
        print(f"[FAST_CYCLE] model_window.reset_cursor -> {type(e).__name__}: {e}")

    # ── 0. Body scan → adaptive directives (runs FIRST, before everything) ──
    beat("body_scan", "0")
    print("[FAST_CYCLE] Step 0: body scan + dependency check...")
    try:
        from agents.body.body_scanner import run as _body_run
        _body_run()
    except Exception as e:
        print(f"[FAST_CYCLE] body_scan -> FAILED: {e}")

    directives = _load_directives()
    cycle_mode = directives.get("cycle_mode", "FULL")
    llm_sleep  = directives.get("llm_sleep_secs", 2)
    workers    = directives.get("max_parallel_workers", 3)
    print(f"[FAST_CYCLE] adaptive mode={cycle_mode} | workers={workers} | llm_sleep={llm_sleep}s")

    # ── Homeostatic assessment — самопознание преди старт ──
    try:
        from core.homeostasis import assess as _homeo_assess, as_prompt_block as _homeo_block
        homeo = _homeo_assess(verbose=True)
        if not homeo.get("can_start"):
            print(f"[FAST_CYCLE] СПРЯН — {homeo.get('abort_reason')}")
            print(f"[FAST_CYCLE] Нужди: {homeo.get('resource_needs')}")
            return
        # Override cycle_mode if homeostasis is more conservative
        h_mode = homeo.get("cycle_mode", "FULL")
        if h_mode == "MINIMAL" and cycle_mode != "MINIMAL":
            cycle_mode = "MINIMAL"
            workers    = 1
            llm_sleep  = 15
            print(f"[FAST_CYCLE] homeostasis overrides to MINIMAL mode")
        # Apply skip directives
        _skip_steps = set(homeo.get("skip_steps", []))
    except Exception as e:
        print(f"[FAST_CYCLE] homeostasis -> FAILED: {e}")
        _skip_steps = set()

    # Apply LLM sleep directive to groq_backend globally
    try:
        import core.groq_backend as _gb
        _gb._SLEEP_SECS = llm_sleep
    except Exception:
        pass

    # ══ КОНСЕНСУС С KIMI, 15 авг 2026 — СТЪПКА 2 от 53 ═════════════════════
    # Дотук планът на деня се пишеше ВТОРИ, веднага след boot — тоест сляп за
    # тялото и за човешката дума. Моята позиция: няма причина за това. Kimi се
    # съгласи и добави довода, който липсваше в моята:
    #   „Няма причина планът да е преди тялото — план при OOM или thermal throttle
    #    е фикция."
    #   „human_approvals преди плана е констрейнт, не опция; иначе планът пише
    #    желания, които човекът вече е забранил."
    # Затова новият ред е: pulse -> body_scan (+ хомеостаза) -> човешките одобрения
    # -> известията -> ПЛАНЪТ. Мозъкът вече планира с отворени очи: знае колко
    # памет има, знае какво човекът е разрешил и забранил.
    # Четвъртото му искане — „body_scan трябва да може да СПРЕ цикъла директно" —
    # е вече изпълнено по-горе и го проверих, вместо да го добавям втори път:
    # homeostasis.assess().can_start връща цикъла преди този ред.

    # ── 0.05. Canon — the ALWAYS-LOADED conceptual center (core/canon.py).
    # СТЪПКА 3, 15 авг 2026. Дефект, който САМО ПРЕМЕСТВАНЕТО НА СТЪПКА 2 роди:
    # канонът се зареждаше на 0.3, а планът на деня се пише на 0.2. Мозъкът чете
    # канона през memory/active_canon_frame.txt (core/brain.py::_spirit), тоест
    # щеше да напише днешния план, гледайки ВЧЕРАШНИЯ си концептуален център — а
    # канонът е човешки защитен файл, който Емил може да е сменил снощи.
    # Хомеостазата е физическото „аз"; канонът е концептуалното. И двете трябва да
    # са налице, преди да се пише план. Затова канонът минава преди плана.
    beat("canon_load", "0.05")
    try:
        from core.canon import as_frame as _canon_frame, load_canon as _load_canon
        _cf = _canon_frame()
        _cc = _load_canon()
        (BASE / "memory").mkdir(parents=True, exist_ok=True)
        (BASE / "memory" / "active_canon_frame.txt").write_text(_cf, encoding="utf-8")
        print(f"[FAST_CYCLE] canon loaded -> {len(_cc.get('invariants', []))} invariant(s), "
              f"{len(_cc.get('dimensions', []))} goal-dimensions; center stamped for this cycle")
    except Exception as e:
        print(f"[FAST_CYCLE] canon load -> FAILED (fallback center in effect): {type(e).__name__}: {e}")

    # ── Telegram approvals: apply any "OK <id>" replies BEFORE the cycle runs, so
    #    a source you approved is live for this cycle's scoring. Sensing-source
    #    promotions + accepted goals only — never a world-action, and only from the
    #    configured chat_id. FAIL-OPEN: a failure here never blocks the cycle.
    beat("telegram_approvals", "0.1")
    try:
        from experiments.needs.approve_reader import run as _approve_run
        _n_appr = _approve_run()
        if _n_appr:
            print(f"[FAST_CYCLE] telegram approvals -> applied {_n_appr}")
    except Exception as e:
        print(f"[FAST_CYCLE] telegram approvals -> FAILED: {type(e).__name__}: {e}")

    # ── МОЗЪКЪТ ОТВАРЯ ЦИКЪЛА (закон, т.3 — Емил, 15 авг 2026) ──────────────
    # Системата пита СЕБЕ СИ какво иска от този цикъл: фокус, подозрение към самата
    # себе си, и тест за успех, който сама си задава. Планът се пише в
    # memory/brain_cycle_plan.json и всяка стъпка може да го чете
    # (core.brain.current_plan()). FAIL-OPEN: мълчащ мозък не спира цикъла.
    beat("brain_briefing", "0.2")
    try:
        from core.brain import brief_cycle as _brief
        _plan = _brief()
        if _plan:
            print(f"[FAST_CYCLE] brain plan -> focus={_plan.get('focus')!r} "
                  f"watch={_plan.get('watch')} test={str(_plan.get('success_test'))[:90]!r}")
        else:
            print("[FAST_CYCLE] brain plan -> brain silent (cycle runs unplanned)")
    except Exception as e:
        print(f"[FAST_CYCLE] brain plan -> FAILED: {type(e).__name__}: {e}")

    # ── Известията — СЛЕД плана (консенсус с Kimi, стъпка 5, 15 авг 2026).
    # Стояха преди плана. Kimi: „Стъпка 5 трябва да е СЛЕД плана — иначе планът
    # ражда нужди, които излизат едва утре; човекът отговаря на вчерашни въпроси,
    # докато днешните не са стигнали до него."
    # Тоест забавката не беше една нощ, а две: нужда, родена от днешния план,
    # изчакваше следващото известяване, преди изобщо да бъде показана.
    beat("notify_patches_and_initiatives", "0.25")
    _notify_patches_and_initiatives()

    # ── 0.5. Dependency check ──
    beat("dependency_check", "0.5")
    if not _check_dependencies():
        print("\n[FAST_CYCLE] СПРЯН — няма нито един път до мислене.")
        print("[FAST_CYCLE] Отчет: snapshots/master/dependency_check_latest.json")
        return

    # ── КОНСЕНСУС С KIMI, стъпка 6, т.4 (15 авг 2026) ───────────────────────
    # „Убиването преди мозъка е допустимо само ако НИКОЙ не може да мисли —
    #  иначе МОЗЪКЪТ трябва да реши дали да продължи с локален модел."
    # Горното спиране остава (там наистина няма кой да прецени — падналото Е
    # преценяващият). Но случаят „всички външни са мъртви, локалният е жив" не е
    # авария, а ИЗБОР: цикъл с 3B модел върху 25 оси е друг цикъл, не същият
    # по-бавен. Затова изборът е негов, не мой и не на хардкоднат праг.
    try:
        _dep = json.loads((BASE / "snapshots" / "master" /
                           "dependency_check_latest.json").read_text(encoding="utf-8"))
        _alive = _dep.get("thinking_paths") or []
        if _alive == ["local_brain"]:
            print("[FAST_CYCLE] само локалният мозък е жив — питам него, не себе си")
            from core import brain as _brain
            _d = _brain.think(
                role="стопанин на цикъла, останал без външни доставчици",
                question=("Всички външни доставчици са мъртви. Жив си само ти — локален "
                          "модел на 4GB VRAM. Пред теб са 25 оси и 217 държави.\n"
                          "Въпросът е твой: този цикъл струва ли си сега, или е по-честно "
                          "да не се прави, отколкото да се напълни паметта с плитки "
                          "преценки, които утре ще се четат като истина?\n"
                          "Ако продължиш — кажи какво СЪКРАЩАВАШ, за да остане каквото "
                          "правиш смислено. Ако спреш — това не е провал, а преценка."),
                evidence=json.dumps(_dep, ensure_ascii=False)[:2000],
                kind="degraded_mode")
            _ans = str((_d or {}).get("action", "")).strip().lower()
            _why = str((_d or {}).get("why", ""))[:300]
            if _d and _ans.startswith(("спри", "не", "откаж")):
                print(f"[FAST_CYCLE] СПРЯН по преценка на мозъка: {_why}")
                try:
                    with open(BASE / "memory" / "night_events.jsonl", "a",
                              encoding="utf-8") as _fh:
                        _fh.write(json.dumps(
                            {"ts": _utc_now(), "subject": "цикълът спрян ОТ МОЗЪКА",
                             "detail": f"само локален модел; неговата причина: {_why}"},
                            ensure_ascii=False) + "\n")
                except Exception:
                    pass
                return
            print(f"[FAST_CYCLE] мозъкът продължава на локален модел: {_why}")
    except Exception as _de:
        print(f"[FAST_CYCLE] degraded-mode decision skipped: {type(_de).__name__}: {_de}")

    # Skip web intel if offline
    if directives.get("skip_web_intel"):
        print("[FAST_CYCLE] OFFLINE — skipping web intelligence")
    else:
        pass  # falls through to Step 1 below

    # ── 0.7. needs_reanalysis scan — find axes that failed all LLM backends ──
    beat("needs_reanalysis_scan", "0.7")
    try:
        flagged = _scan_needs_reanalysis()
        if flagged:
            axes_str = ", ".join(f["axis"] for f in flagged)
            print(f"[FAST_CYCLE] needs_reanalysis: {len(flagged)} axes flagged — {axes_str}")
        else:
            print("[FAST_CYCLE] needs_reanalysis: no flagged axes")
    except Exception as e:
        print(f"[FAST_CYCLE] needs_reanalysis scan -> FAILED: {e}")

    # ── 1. Web Intelligence ──
    beat("web_intelligence", "1")
    if not directives.get("skip_web_intel"):
        run_web_intelligence()
    else:
        print("[FAST_CYCLE] Step 1: web_intelligence SKIPPED (offline)")

    # ── 2. LLM self-review оси ──
    # 15 авг 2026 — ПРЕМЕСТЕНА (възражение на Kimi, проверено в кода):
    # „llm_self_review_axes е ОЦЕНКА, не сетиво, и тича преди суровите данни
    #  (2.5–2.55). Преглежда оси с ВЧЕРАШНИ стойности; мястото ѝ е след 2.7."
    # Беше стъпка 2 — тоест всяка нощ LLM произнасяше LOW/MEDIUM/HIGH върху
    # вчерашните числа, днешните пристигаха след него, и скорингът на 12.4
    # работеше върху друга реалност. Два прочита на един ден, върху различни
    # данни. Сега е на 2.75: след като всички сетива са внесли своето.
    # ── 2.5. Global indicators — реални данни от 7 источника ──
    beat("global_indicators", "2.5")
    try:
        from core.global_indicators import fetch_all as _gi_fetch
        gi_path = BASE / "snapshots" / "master" / "global_indicators_latest.json"
        # THE PREVIOUS SNAPSHOT GOES IN. Without it this write was a wholesale overwrite,
        # so one slow minute at the World Bank blanked eleven metrics and killed 26
        # composer sources across 9 axes — none of which had anything to do with the
        # world changing. A metric that fails this cycle now keeps its last good value,
        # marked and dated under _carried, and can never pass as a fresh reading.
        try:
            _gi_prev = json.loads(gi_path.read_text(encoding="utf-8"))
        except Exception:
            _gi_prev = None
        gi_data = _gi_fetch(previous=_gi_prev)

        # ── КРИПТАТА (консенсус с Kimi, 15 авг 2026) ───────────────────────
        # Число, което е физически невъзможно или идва от карантиниран източник,
        # НЕ влиза в снимката като число. На мястото му остава null плюс препратка
        # към attestation/quarantine_attestations.jsonl, където стои какво точно е
        # било отхвърлено и защо.
        # Kimi: „А е епистемично самоубийство — без запис на отхвърленото не можеш
        # да провериш дали карантината е била права, а 'липса' се чете като 'никога
        # не сме имали'. Неизбежен етикет: value е null, отхвърленото живее само в
        # rejected масив. Консуматор, който не чете етикета, получава безопасен
        # null, НЕ ЛЪЖА."
        try:
            from core.source_trust import filter_snapshot as _filter
            _before = json.dumps(gi_data, ensure_ascii=False)
            gi_data = _filter(gi_data)
            _rej = gi_data.get("_rejected") or []
            if _rej:
                print(f"[FAST_CYCLE] source_trust -> ОТХВЪРЛЕНИ {len(_rej)} числа: "
                      + ", ".join(f"{r['section']}.{r['metric']}" for r in _rej[:5]))
                _note_night("отхвърлени числа",
                            f"{len(_rej)} стойности не влязоха в снимката: "
                            + ", ".join(f"{r['section']}.{r['metric']}({r['crypt_ref']})"
                                        for r in _rej[:8]))
        except Exception as _se:
            print(f"[FAST_CYCLE] source_trust -> FAILED: {type(_se).__name__}: {_se}")

        gi_path.parent.mkdir(parents=True, exist_ok=True)
        gi_path.write_text(json.dumps(gi_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # BATCH COMMIT в проверената Merkle верига (Kimi, 15 авг 2026): една секция =
        # един лист. Дотук твърдите числа стояха ИЗВЪН всякаква одитна верига, докато
        # сензорните капки имаха дърво. Не хиляди листа — двайсет.
        try:
            from core.source_trust import commit_sections as _commit
            _c = _commit(gi_data)
            print(f"[FAST_CYCLE] merkle -> {_c.get('committed', 0)} секции ангажирани "
                  f"в проверената верига")
        except Exception as _ce:
            print(f"[FAST_CYCLE] merkle commit -> FAILED: {type(_ce).__name__}: {_ce}")
        co2  = gi_data.get("co2", {}).get("co2_ppm", "?")
        temp = gi_data.get("temperature", {}).get("temp_anomaly_c", "?")
        conf = gi_data.get("conflicts", {}).get("active_armed_conflicts", "?")
        # ── ПРОИЗХОДЪТ НА ЧИСЛАТА (Kimi, 15 авг 2026) ─────────────────────
        # „Твърдите числа са просто API отговори СЪС ЗАКЪСНЕНИЕ и без контекст."
        # Мерено върху вчерашната снимка: средно доверие 0.36; едно число прясно
        # (CO2, 11 дни); бежанците със закъснение 1321 дни; две секции ПРАЗНИ, но
        # броени за източници. Оттук нататък това се смята всеки цикъл и се пише,
        # за да не може закъснението пак да се скрие зад думата „източник".
        try:
            from core.provenance import run as _prov_run
            _prov_run()
        except Exception as _pe:
            print(f"[FAST_CYCLE] provenance -> FAILED: {type(_pe).__name__}: {_pe}")
        _h = gi_data.get("_health") or {}
        print(f"[FAST_CYCLE] global_indicators -> CO2={co2}ppm | +{temp}°C | conflicts={conf}"
              f" | {_h.get('fresh_this_cycle')} fresh, {_h.get('carried_from_a_previous_cycle')}"
              f" carried, {_h.get('missing_everywhere')} missing")
    except Exception as e:
        import traceback as _tb
        print(f"[FAST_CYCLE] global_indicators -> FAILED: {e}")
        _tb.print_exc()

    # ── 2.54. Sensorium ingest — the LIGHT half of the sensing/thinking split. The
    #    independent per-axis collectors (browser agents) deposit verified, Merkle-committed
    #    drops out-of-band; here the cycle only routes the newest ready drop per axis to the
    #    composer (numeric) / brain inbox (semantic). No browser, no search, no heavy model.
    #    FAIL-OPEN. (claude/SENSORY_COLLECTORS_ARCHITECTURE_30JUL.md)
    beat("sensorium_ingest", "2.54")
    try:
        from experiments.sensorium.sensorium import ingest as _sens_ingest, verify as _sens_verify
        _si = _sens_ingest()
        _sv = _sens_verify()
        # verify() reports the two chains separately (#55): the verified sensory chain and
        # the penumbra shadow. Each must scream on its own — a healthy shadow must never
        # mask a corrupted sense, or the reverse.
        _v, _p = _sv.get("verified", {}), _sv.get("penumbra", {})
        print(f"[FAST_CYCLE] sensorium -> ingested {_si.get('ingested', 0)} drop(s); "
              f"merkle intact={_v.get('ok')} ({_v.get('n')} leaves) | "
              f"penumbra intact={_p.get('ok')} ({_p.get('n')} leaves)")
        if not _v.get("ok"):
            print(f"[FAST_CYCLE] sensorium -> TAMPER/GAP (verified): {_v.get('mismatches')}")
        if not _p.get("ok"):
            print(f"[FAST_CYCLE] sensorium -> TAMPER/GAP (penumbra): {_p.get('mismatches')}")
    except Exception as e:
        print(f"[FAST_CYCLE] sensorium ingest -> FAILED: {type(e).__name__}: {e}")

    # ── 2.55. Browser-scout — autonomously turn HTML pages into neutral JSON for the
    #    DYNAMIC axes (deterministic extraction, traceable to page text). Writes
    #    memory/browse_sources/<key>.json, which the composer reads via its "file" kind.
    #    Runs BEFORE composers so the fresh value is available this cycle. FAIL-OPEN.
    beat("browser_scout", "2.55")
    try:
        from experiments.browser_scout.scout import run_all as _scout_all
        _scout_all()
    except Exception as e:
        print(f"[FAST_CYCLE] browser_scout -> FAILED: {type(e).__name__}: {e}")

    # ── 2.6. Composers — daily multi-source portfolio per axis = the MOVING signal.
    #    Fetches each spec'd axis's live sources, composes the indicator, appends the
    #    value to memory/composer_state/<AXIS>.json (last 30, timestamped) and refreshes
    #    composer_needs.json. THIS is the daily signal E1 (learner) / E8 (reward arena)
    #    / K1b learn from — without it those verdicts stay "insufficient data".
    #    FAIL-OPEN: a source/network failure lowers confidence and emits a NEED, it
    #    never breaks the cycle. (Task #3 — the keystone.)
    beat("composers", "2.6")
    try:
        from experiments.composers.composer import (
            compose as _compose, _load as _cload, SPEC_FILE as _CSPEC)
        _specs = _cload(_CSPEC, {})
        _c_axes = [a for a in _specs if a != "_meta"]
        _c_ok = 0
        for _ax in _c_axes:
            try:
                _r = _compose(_ax)
                if isinstance(_r, dict) and "error" in _r:
                    print(f"[FAST_CYCLE] composer {_ax} -> {_r['error']}")
                    continue
                _cmp = (_r or {}).get("composed", {})
                _c_ok += 1
                print(f"[FAST_CYCLE] composer {_ax} -> anchor={_cmp.get('anchor')} "
                      f"daily={_cmp.get('daily')} divergence={_cmp.get('divergence')} "
                      f"confidence={_r.get('confidence')} needs={len(_r.get('needs', []))}")
            except Exception as _ce:
                print(f"[FAST_CYCLE] composer {_ax} -> FAILED: {type(_ce).__name__}: {_ce}")
        print(f"[FAST_CYCLE] composers -> {_c_ok}/{len(_c_axes)} composed (moving signal recorded)")
    except Exception as e:
        print(f"[FAST_CYCLE] composers -> FAILED: {type(e).__name__}: {e}")

    # ── 2.7. Grounding ledger (E2) — anchor vs daily proxy, recorded tamper-evidently.
    #    TWO SEPARATE ACTS, on purpose (Kimi, 15 Aug 2026): the ledger only RECORDS —
    #    raw numbers, each axis's own sigma, and `insufficient_history` where the axis
    #    has fewer than `grounding_min_history` observations. It holds no threshold and
    #    raises no alert. The VERDICT is passed by source_trust, with the same sigma
    #    that judges everything else, and the distrust point lands on the DAILY SOURCE,
    #    not on the axis. One truth, one judge. FAIL-OPEN both times.
    beat("grounding_ledger", "2.7")
    try:
        from experiments.grounding.divergence_ledger import record as _ground_record
        _grec = _ground_record()
    except Exception as e:
        _grec = None
        print(f"[FAST_CYCLE] grounding_ledger -> FAILED: {type(e).__name__}: {e}")
    if _grec:
        try:
            from core import source_trust as _st
            _verdicts = _st.judge_grounding(_grec)
            _diverged = [v for v in _verdicts if v.get("verdict") == "РАЗМИНАВАНЕ"]
            _unknown = [v for v in _verdicts if v.get("verdict") == "НЕИЗВЕСТНО"]
            print(f"[FAST_CYCLE] grounding_verdicts -> {len(_verdicts)} axes judged | "
                  f"divergent {len(_diverged)} | not yet judgeable {len(_unknown)}")
            for _v in _diverged:
                print(f"  DIVERGENCE {_v['axis']}: {_v.get('z')} sigma over n={_v.get('n')}"
                      f"{' -> distrust point on ' + str(_v['distrust'].get('source', '?')) if _v.get('distrust') else ' (daily source unknown — charged to no one)'}")
        except Exception as e:
            print(f"[FAST_CYCLE] grounding_verdicts -> FAILED: {type(e).__name__}: {e}")

    beat("llm_self_review_axes", "2.75")
    refresh_llm_axes()
    update_master()

    # ── 3. Trend tracker ──
    beat("trend_tracker", "3")
    run_trend_tracker()

    # ── 3.5. CortexStrategist — MUST run early before token budget is depleted by snapshots ──
    beat("cortexstrategist", "3.5")
    # Groq free tier: 100K tokens/day. Steps 4-11 consume ~90K tokens.
    # CortexStrategist needs ~7K tokens — running it here ensures budget is available.
    _run("cortex_strategist_agent", lambda: __import__(
        "agents.cortex_strategist.cortex_strategist_agent", fromlist=["run"]).run(), free_after=True)
    _strategist_to_proposals()

    # ── 4. Internet intelligence ──
    beat("internet_intelligence", "4")
    _run("internet_agent", lambda: __import__(
        "agents.internet.internet_agent", fromlist=["run"]).run(), free_after=True)

    # ── 5. Civilization snapshots ──
    beat("civilization_snapshots", "5")
    _run("civilization_snapshots_agent", lambda: __import__(
        "agents.civilization.civilization_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 6. Planet snapshots ──
    beat("planet_snapshots", "6")
    _run("planet_snapshots_agent", lambda: __import__(
        "agents.planet.planet_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 7. Human snapshots ──
    beat("human_snapshots", "7")
    _run("human_snapshots_agent", lambda: __import__(
        "agents.human.human_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 8. Cosmos snapshots ──
    beat("cosmos_snapshots", "8")
    _run("cosmos_snapshots_agent", lambda: __import__(
        "agents.cosmos.cosmos_snapshots_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 9. Planetary potential ──
    beat("planetary_potential", "9")
    _run("planetary_potential_agent", lambda: __import__(
        "agents.planet.planetary_potential_review_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 10. Energy review ──
    beat("energy_review", "10")
    _run("energy_review_agent", lambda: __import__(
        "agents.energy.energy_review_agent_qwen", fromlist=["main"]).main(), free_after=True)

    # ── 11. Self awareness ──
    beat("self_awareness", "11")
    def _self_awareness():
        from agents.self.self_awareness_agent import SelfAwarenessAgent
        SelfAwarenessAgent().run()
    _run("self_awareness_agent", _self_awareness, free_after=True)

    # ── 12. Update master след всички snapshots ──
    beat("update_master", "12")
    update_master()
    # Гасенето на „чака преразглеждане" живее ТУК, в гръбнака (Kimi, стъпка 7, т.4):
    # ако беше на пропускаема стъпка, един пропуск оставяше флага висок завинаги.
    try:
        _resolve_reanalysis()
    except Exception as _re:
        print(f"[FAST_CYCLE] reanalysis resolve -> FAILED: {type(_re).__name__}: {_re}")

    # ── 12.3. System hypergraph — rebuild so cortex_strategist/self_observer can query it ──
    beat("system_hypergraph", "12.3")
    try:
        from system_hypergraph import build_hypergraph
        hg = build_hypergraph()
        print(f"[FAST_CYCLE] system_hypergraph -> {hg['triples_count']} triples | {len(hg['isolated_nodes'])} isolated")
    except Exception as e:
        print(f"[FAST_CYCLE] system_hypergraph -> FAILED: {e}")

    # ── 12.4. Scoring engine — освежи cortex_scores_latest.json ──
    beat("scoring_engine", "12.4")
    try:
        from cortex_scoring_engine import score_all_snapshots as _score_all, AXIS_SCORERS as _AXIS_SCORERS
        import datetime as _dt
        _scores = _score_all()
        _out = BASE / "output" / "cortex_scores_latest.json"
        _out.parent.mkdir(parents=True, exist_ok=True)
        _out.write_text(
            json.dumps(
                {
                    "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    "scorer_version": "1.1",
                    "total_axes": len(_scores),
                    "scores": {
                        ax: {
                            "score": r.score,
                            "level": r.level,
                            "signals": r.signals,
                            "metrics_used": r.metrics_used,
                            "verification": r.verification,
                        }
                        for ax, r in _scores.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _real = sum(1 for ax in _scores if ax in _AXIS_SCORERS)
        print(f"[FAST_CYCLE] scoring_engine -> {len(_scores)} axes | {_real} real scorers | output/cortex_scores_latest.json")
    except Exception as e:
        print(f"[FAST_CYCLE] scoring_engine -> FAILED: {e}")

    # ── 12.45. Facade self-check — did each real scorer consume real data, or
    #           default to a constant? Fails LOUD instead of silent. FAIL-OPEN. ──
    # ── 12.42. ЧЕРВЕНИТЕ ЛИНИИ ────────────────────────────────────────────
    # Веднага след скоринга, защото аларма, която чака сутрешния дайджест, е
    # доклад, а не аларма. Пресичане ЗВЪНИ веднага и минава през тихите часове.
    # Днес всичките 25 прага са null — нищо не звъни, а броячът
    # AWAITING_HUMAN_VALUES стои в доклада като открит въпрос към Емил.
    beat("alarm_bands", "12.42")
    def _alarm_bands():
        from core.alarm_bands import run as _sweep
        _sweep()
    _run("alarm_bands", _alarm_bands)

    beat("facade_self_check", "12.45")
    try:
        from core.scorer_self_check import run_from_snapshots as _facade_check, format_report as _facade_fmt
        import datetime as _dt2
        _report = _facade_check()
        _freport = BASE / "output" / "facade_audit_latest.json"
        _freport.parent.mkdir(parents=True, exist_ok=True)
        _report_out = dict(_report)
        _report_out["generated_at"] = _dt2.datetime.now(_dt2.timezone.utc).isoformat()
        _freport.write_text(json.dumps(_report_out, ensure_ascii=False, indent=2), encoding="utf-8")
        for _line in _facade_fmt(_report):
            print(f"[FACADE] {_line}")
        if _report["dead"]:
            print(f"[FAST_CYCLE] facade_self_check -> {len(_report['dead'])} DEAD scorer(s): "
                  f"{', '.join(_report['dead'])} — see output/facade_audit_latest.json")
        else:
            print("[FAST_CYCLE] facade_self_check -> OK (no dead scorers)")
    except Exception as e:
        print(f"[FAST_CYCLE] facade_self_check -> FAILED: {e}")

    # ── 12.5. Auto levels — СЛЕД snapshot агентите, не преди! ──
    beat("auto_levels", "12.5")
    # Тук auto_level чете реални данни от обновения master snapshot.
    # execute_patches ще вика auto_level отново за before/after measurement.
    levels = {}  # initialized here so MerkleMemory commit can read it at step 24
    try:
        from memory.auto_level import run as compute_levels
        levels, corrections, alerts = compute_levels()
        print(f"[FAST_CYCLE] auto_levels -> {len(levels)} оси | {len(corrections)} корекции | {len(alerts)} alerts")
    except Exception as e:
        print(f"[FAST_CYCLE] auto_levels -> FAILED: {e}")

    # ── 12.55. ДУМАТА СЛЕДВА ЧИСЛОТО ──────────────────────────────────────
    # auto_levels пише дума по свои прагове; goal_score пише число от измерена
    # стойност спрямо цел и посока. Никой не ги сравняваше и се разминаха: на
    # 21 авг SOCIAL_RELATIONS стоеше MEDIUM при 3.4/100. Където двете спорят и
    # значението на резултата е ЗАКОВАНО, числото печели. Двете _RISK_ оси са
    # нарочно незаковани — там LOW може да значи „нисък РИСК", обратната
    # полярност — и се само ОТБЕЛЯЗВАТ, никога не се поправят.
    beat("level_reconcile", "12.55")
    def _level_reconcile():
        from core.level_reconciler import run as _reconcile
        _reconcile()
    _run("level_reconcile", _level_reconcile)

    # ── 12.6. Goal score calculator ──
    beat("goal_score_calculator", "12.6")
    composite = 0.0  # initialized here so MerkleMemory commit can read it at step 24
    def _goal_score_calculator():
        nonlocal composite
        from goal_score_calculator import compute_goal_score, format_headline
        gs_result = compute_goal_score()
        composite  = gs_result["composite_score"]
        # КОНСЕНСУС С KIMI, 15 авг 2026: числото НИКОГА не излиза само.
        # „Число без семантика е театър (или «тъмна цифра» — едно и също).
        #  Консуматор, който иска само числото, получава пакета или нищо."
        # Пакетът се сглобява на ЕДНО място — format_headline — а
        # test/test_goal_score_package.py чупи билда, ако някой го заобиколи.
        print(f"[FAST_CYCLE] goal_score_calculator -> {format_headline(gs_result)}")
        _sens = gs_result.get("sensors_ok")
        _goal = gs_result.get("goal_covered")
        # ДВА флага, защото един е мъртъв: goal_covered е False по построение,
        # докато семантичните оси нямат мярка; sensors_ok мига всеки ден и затова
        # е този, който носи новина.
        if not _sens:
            print(f"[FAST_CYCLE] СЕТИВАТА КУЦАТ: покритие на измеримото "
                  f"{gs_result.get('coverage_of_measurable', 0):.0%} — "
                  f"{len(gs_result.get('unmeasured_axes') or [])} измерими оси без число днес")
            try:
                _note_night("СЕТИВАТА КУЦАТ",
                            "; ".join(f"{a}: {v['why']}" for a, v in
                                      (gs_result.get("unmeasured_reasons") or {}).items()))
            except Exception:
                pass
        if not _goal:
            print(f"[FAST_CYCLE] ЦЕЛТА НЕ Е ПОКРИТА: {gs_result.get('insufficient_data')}")
            _unassessed = gs_result.get("semantic_unassessed") or []
            if _unassessed:
                print(f"[FAST_CYCLE] семантични оси БЕЗ никаква оценка ({len(_unassessed)}): "
                      f"{', '.join(_unassessed[:6])}"
                      f"{'...' if len(_unassessed) > 6 else ''}")
        # Persist through the ONE writer (goal_score_calculator.persist), so the
        # cycle and core.reconsider cannot drift into two different snapshots.
        from goal_score_calculator import persist as _persist_goal
        _persist_goal(gs_result)
    _run("goal_score_calculator", _goal_score_calculator)

    # ── 12.7. Cognitive Orchestrator — Attentional Meta Protocol ──
    # ── 12.65. Deduction layer v1 (14 Aug 2026) — symbolic conclusions with premises
    #    from auto_levels + trends + measured scores. Read by daily_analysis (human),
    #    needs_report (Telegram) and available to the orchestrator. FAIL-OPEN.
    beat("deduction", "12.65")
    try:
        from core.deduction import run as _deduction_run
        _deduction_run()
    except Exception as e:
        print(f"[FAST_CYCLE] deduction -> FAILED: {type(e).__name__}: {e}")

    # ── 12.66. ПОСТОЯНСТВОТО КАТО ИЗМЕРВАНЕ (Емил, 15 авг 2026) ────────────
    # Досега системата гонеше само промяната; плоската серия минаваше за нищо.
    # Но кислородът в атмосферата е постоянен ЗАЩОТО е здрав — там движението е
    # алармата. Мозъкът казва в какъв режим ОЧАКВА да е всеки показател и дали
    # видяното е здраве или симптом; после чете всички ЗАЕДНО и търси връзки,
    # които нито един поотделно не показва. FAIL-OPEN.
    beat("constancy_and_constellation", "12.66")
    try:
        from core.constancy import run as _const_run
        _cres = _const_run()
        _cc = _cres["constancy"]["counts"]
        print(f"[FAST_CYCLE] constancy -> {_cc['total']} показателя, "
              f"{_cc['still']} неподвижни, {_cc['alarm']} тревожни")
        _cj = _cres.get("constellation") or {}
        if _cj.get("most_telling"):
            print(f"[FAST_CYCLE] constellation -> {str(_cj['most_telling'])[:160]}")
    except Exception as e:
        print(f"[FAST_CYCLE] constancy -> FAILED: {type(e).__name__}: {e}")

    # ── 12.68. AXIS FEEDS — ЧИСЛОТО, КОЕТО ПРЕСИЧА ГРАНИЦАТА ───────────────
    # Един агент на ос, и всеки може да изнесе САМО число, вързано за (ос, ключ).
    # Не изречение, не дума за ниво, не обобщение на модел. Точно това е DMZ
    # договорът от docs/OPENCLAW_INTEGRATION_DESIGN.md, приложен към данните:
    # каквото излиза, се ограничава по ТИП, а не по добро намерение.
    # Ос без число не изчезва — излиза с ABSENT ред и причина, защото „липсваща
    # ос" и „ос, която никой не е погледнал" не бива да изглеждат еднакво.
    beat("axis_feed", "12.68")
    try:
        _axis_feed = __import__("agents.axis.axis_feed", fromlist=["run"])
        _axis_feed.run()
    except Exception as e:
        print(f"[FAST_CYCLE] axis_feed -> FAILED: {type(e).__name__}: {e}")

    beat("cognitive_orchestrator", "12.7")
    # Runs BEFORE HyperClaw so it can use its priority_axes assessment.
    # (CortexStrategist was moved to step 3.5 to run before token budget is depleted.)
    #
    # ── РЕДЪТ Е АРИТМЕТИКА, ПРОЗАТА Е БЕЛЕЖКА (20 авг 2026) ────────────────
    # Приоритетът вече се смята ПРЕДИ моделът да е попитан за каквото и да е:
    # need = weight x penalty, от target_config и goal_score_latest — нито едно
    # от двете не е мнение. core/orchestrator_grounded.py го пише, после
    # cortex_orchestrator чете ТОВА като свой вход. Моделът може да ДОПИШЕ
    # бележка към ред; не може да пренареди, да смени кофата или да измисли
    # действие извън затворения речник. Разликата е между коментар и
    # непроверено решение.
    def _grounded_first():
        from core.orchestrator_grounded import run as _grounded
        _grounded()
    _run("orchestrator_grounded", _grounded_first)

    def _cortex_orchestrator():
        from core.cortex_orchestrator import run as _orchestrate
        _orchestrate()
    _run("cortex_orchestrator", _cortex_orchestrator)

    # ── 12.75. ТОЧКАТА НА ВРЪЩАНЕ (консенсус с Kimi, 15 авг 2026) ──────────
    # „Планът се ражда на стъпка 2 от слепота и умира на стъпка 51, без да е
    #  променян от нищо видяно по средата." Тук цикълът спира за миг и мозъкът
    #  решава: продължавам ли, или се връщам. Мястото е негово предложение —
    #  след оркестратора (има цялостна картина), но ПРЕДИ каквото и да е
    #  необратимо (публикуване, патчове). Най-много ЕДНО връщане на цикъл;
    #  цената в минути му се казва предварително. FAIL-OPEN.
    beat("brain_reconsider", "12.75")
    try:
        from core.reconsider import run as _reconsider
        _rc = _reconsider()
        if _rc.get("action") == "връщане":
            print(f"[FAST_CYCLE] reconsider -> ВЪРНА {_rc.get('replayed')} "
                  f"({_rc.get('seconds')}s, ok={_rc.get('ok')}) | {str(_rc.get('why'))[:120]}")
        else:
            print(f"[FAST_CYCLE] reconsider -> напред | {str(_rc.get('why'))[:120]}"
                  + (f" | ОТКАЗАНО: {_rc['refused']}" if _rc.get("refused") else ""))
    except Exception as e:
        print(f"[FAST_CYCLE] reconsider -> FAILED: {type(e).__name__}: {e}")

    # ── 13. Body scan ──
    beat("body_scan", "13")
    _run("body_scanner", lambda: __import__(
        "agents.body.body_scanner", fromlist=["run"]).run())

    # ── 14. Growth planner ──
    beat("growth_planner", "14")
    _run("growth_planner", lambda: __import__(
        "agents.body.growth_planner", fromlist=["run"]).run())

    # ── 15.6. HyperClaw — multi-axis 24-72h plan ──
    beat("hyperclaw", "15.6")
    _run("hyperclaw_orchestrator", lambda: __import__(
        "agents.hyperclaw.hyperclaw_orchestrator", fromlist=["main"]).main(), free_after=True)

    # ── 15.7. HyperClaw plan → improvement proposals ──
    beat("hyperclaw_plan", "15.7")
    _hyperclaw_to_proposals()

    # ── 15.8. GitHub publish — cycle synthesis + verified hypotheses ──
    beat("github_publish", "15.8")
    # Предшественикът идва от РЕДА НА beat() в този файл, не от лога: brain
    # ._prev_step_output() чете последния [STEP] ред, а beat() го пише ПРЕДИ да
    # повика мозъка, тоест връща самата стъпка. Тук се подава истинският.
    if not _witness_or_refuse("github_publish", "hyperclaw_plan"):
        pass
    else:
        def _github_publisher():
            from github_publisher import publish_synthesis as _gh_publish
            _gh_publish()
        _run("github_publisher", _github_publisher)

    # ── 16. Action recommendations ──
    beat("action_recommendations", "16")
    def _cortex_reasoner():
        from core.cortex_reasoner import reason
        from memory.semantic_memory import remember
        rec = reason(
            "Какви са най-важните действия сега базирани на "
            "последните данни, тенденции и web intelligence?"
        )
        remember(rec[:500], axis="ACTION_RECOMMENDATIONS", source="fast_cycle")
        print("[FAST_CYCLE] Препоръка записана в паметта.")
        try:
            from memory.context_injector import record_causal
            record_causal(
                action="fast_cycle_groq_reasoning",
                effect=rec[:200],
                why="Groq reasoning върху последни данни, тенденции и snapshots",
                axis="ACTION_RECOMMENDATIONS",
            )
        except Exception as e:
            print(f"[FAST_CYCLE] record_causal грешка: {e}")
    _run("cortex_reasoner", _cortex_reasoner)

    # ── 17. Self observer ──
    beat("self_observer", "17")
    _run("self_observer", lambda: __import__(
        "agents.core.self_observer", fromlist=["run"]).run(), free_after=True)

    # ── 18. Self modifier ──
    beat("self_modifier", "18")
    if _witness_or_refuse("self_modifier", "self_observer"):
        _run("self_modifier", lambda: __import__(
            "agents.core.self_modifier", fromlist=["run"]).run(), free_after=True)

    # ── 19. Execute patches — вика auto_level вътрешно за реален before/after ──
    beat("execute_patches", "19")
    if _witness_or_refuse("execute_patches", "self_modifier"):
        _run("execute_patches", lambda: __import__(
            "execute_patches", fromlist=["run"]).run())
        # Тук системата току-що е пренаписала СОБСТВЕНИЯ си код, значи изведените
        # requires може вече да са други. Kimi, 15 авг: „графът е построен преди
        # стъпка 1 и не знае за новото." Затова се престроява от нула.
        try:
            from core.metta_check import invalidate as _mc_invalidate
            _mc_invalidate("след execute_patches — кодът се промени, requires също")
        except Exception:
            pass

    # ── 20. Feedback loop ──
    beat("feedback_loop", "20")
    _run("feedback_loop", lambda: __import__(
        "agents.core.feedback_loop", fromlist=["run"]).run())

    # ── 21. Session update ──
    beat("session_update", "21")
    def _session_updater():
        from core.session_updater import update as _update
        _update()
    _run("session_updater", _session_updater)

    # ── 22. Daily analysis ──
    beat("daily_analysis", "22")
    _run("daily_analysis", lambda: __import__(
        "agents.core.daily_analysis_agent", fromlist=["main"]).main())

    # ── 22.5. Data Scout — автономно търсене на нови реални данни ──
    beat("data_scout", "22.5")
    # Пуска се ПОСЛЕДНО — не се бие с основния цикъл за LLM rate limit.
    # Кешира предложенията; пита LLM само когато ги няма или са >7 дни.
    def _data_scout():
        from core.data_scout import run as _scout_run
        scout_summary = _scout_run(max_axes=2)
        print(
            f"[FAST_CYCLE] data_scout -> "
            f"scanned={scout_summary.get('scanned',0)} | "
            f"validated={scout_summary.get('validated',0)} new sources"
        )
    _run("data_scout", _data_scout)

    # ── 23. Continuous learning ──
    beat("continuous_learning", "23")
    try:
        from memory.continuous_learner import learn_from_cycle
        result = learn_from_cycle({"source": "fast_cycle_runner", "timestamp": _utc_now()})
        if isinstance(result, dict):
            print(f"[FAST_CYCLE] Continuous learning: {result.get('axes_updated', '?')} оси, {result.get('total_in_kb', '?')} KB")
        else:
            print("[FAST_CYCLE] Continuous learning -> OK")
    except Exception as e:
        print(f"[FAST_CYCLE] Continuous learning грешка: {e}")

    # ── 24. MerkleMemory commit ──
    beat("merklememory_commit", "24")
    try:
        import asyncio
        import re as _re
        from merkle_memory import MerkleMemory

        # signals — parse from auto_levels details: "metric=value → LEVEL"
        _signals = []
        for _axis, _info in levels.items():
            if not isinstance(_info, dict):
                continue
            for _detail in _info.get("details", []):
                _m = _re.match(r"([\w]+)=([-\d.]+)", _detail)
                if _m:
                    _signals.append({
                        "metric":   _m.group(1),
                        "value":    float(_m.group(2)),
                        "domain":   _axis,
                        "source":   _info.get("source", "auto_level"),
                        "category": "CIVILIZATION",
                    })

        # decisions — improvement_proposals.json (written by cortex_strategist/hyperclaw, steps 15.5/15.7)
        _decisions = []
        try:
            _raw = json.loads((BASE / "memory" / "improvement_proposals.json").read_text(encoding="utf-8"))
            _decisions = (_raw.get("proposals", _raw) if isinstance(_raw, dict) else _raw)[:30]
        except Exception:
            pass

        # results — today's patch executions + quarantine events from development_journal.json
        # (patch_executions written by execute_patches, step 19; quarantine_events written by
        # safety/quarantine.py whenever the AST gate or PatchGuardian rolls back a dynamic patch)
        _patch_results = []
        _quarantine_events = []
        try:
            _journal = json.loads((BASE / "memory" / "development_journal.json").read_text(encoding="utf-8"))
            _today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            _patch_results = _journal.get(_today, {}).get("patch_executions", [])
            _quarantine_events = _journal.get(_today, {}).get("quarantine_events", [])
        except Exception:
            pass

        # ── Existence ledger anchoring ──────────────────────────────────────
        # The supervisor's scheduler events (starts, kills, restarts, missed runs)
        # live in their own hash-chained ledger. They are NOT committed as cycles —
        # doing that would inflate total_cycles and push goal_score=0.0 into the
        # trend vectors, poisoning the self-model with the system's own supervision.
        #
        # Instead we anchor: the ledger's HEAD HASH rides into results[], which is
        # already a list of arbitrary event dicts. It therefore lands inside
        # archive/cycle_NNNNNN/ and is sealed into the Merkle root — so any later
        # edit to the ledger's history breaks its chain against a hash already in
        # the tree.
        #
        # Events from a KILLED cycle are anchored by the NEXT successful cycle:
        # the dead cannot seal their own record. That is exactly why the ledger is
        # independently hash-chained as well.
        _existence_anchor = []
        try:
            from memory.existence_ledger import verify as _el_verify, summary as _el_summary
            _v = _el_verify()
            _existence_anchor = [{
                "type":              "existence_ledger_anchor",
                "ledger_head_hash":  _v.get("head_hash"),
                "ledger_events":     _v.get("events", 0),
                "ledger_chain_valid": _v.get("valid"),
                "existence":         _el_summary(),
            }]
            if not _v.get("valid"):
                print(f"[FAST_CYCLE] ⚠️  EXISTENCE LEDGER CHAIN BROKEN at seq={_v.get('broken_at')} "
                      f"— the system's own history has been edited")
        except Exception as e:
            print(f"[FAST_CYCLE] existence_ledger anchor -> FAILED: {type(e).__name__}: {e}")

        asyncio.run(MerkleMemory().commit(
            cycle_id  = _utc_now(),
            signals   = _signals,
            decisions = _decisions,
            results   = _patch_results + _quarantine_events + _existence_anchor,
            goal_score = float(composite),
        ))
        print(f"[FAST_CYCLE] MerkleMemory -> committed | signals={len(_signals)} decisions={len(_decisions)} "
              f"results={len(_patch_results)} quarantined={len(_quarantine_events)} goal={composite:.4f}")
        if _existence_anchor:
            print(f"[FAST_CYCLE] existence anchored | head={_existence_anchor[0]['ledger_head_hash'][:12]}... "
                  f"| events={_existence_anchor[0]['ledger_events']}")
    except Exception as e:
        print(f"[FAST_CYCLE] MerkleMemory -> FAILED: {e}")

    # ── 25. Training data accumulation ──
    beat("training_data_accumulation", "25")
    # Runs AFTER MerkleMemory commit (step 24) so the archive entry exists.
    try:
        from merkle_to_training import append_latest_cycle as _append_training
        if _append_training():
            print("[FAST_CYCLE] merkle_to_training -> appended latest cycle")
        else:
            print("[FAST_CYCLE] merkle_to_training -> already processed or no archive")
    except Exception as e:
        print(f"[FAST_CYCLE] merkle_to_training -> FAILED: {e}")

    # ── ЗАЗЕМЕНИТЕ ЦЕЛИ (21 авг 2026) ──────────────────────────────────────
    # Част от стъпка 25, не отделна стъпка: няма собствен beat(), затова и няма
    # номер в заглавието — test_heartbeat_coverage чете точно тези заглавия и
    # един номер тук би обявил стъпка, която пулсът никога не удря.
    # merkle_to_training трупа двойки за ДООБУЧАВАНЕ НА ЕЗИКОВ МОДЕЛ — вход
    # текст, изход текст. core/training_log.py трупа нещо друго: числа за
    # НАДЗИРАВАНО обучение, всяко със записан произход. Разликата е в това кое
    # може да влезе: тук се пуска само MEASURED, а всичко останало се брои и
    # остава отвън, за да се вижда какво е отказано.
    try:
        from core.training_log import harvest as _harvest_targets
        _harvest_targets()
    except Exception as e:
        print(f"[FAST_CYCLE] training_log -> FAILED: {type(e).__name__}: {e}")

    # ── МОЗЪКЪТ ЗАТВАРЯ ЦИКЪЛА (закон, т.3) ────────────────────────────────
    # Той сам съди сбъднал ли се е ТЕСТЪТ, който сам си зададе сутринта, и какво
    # да носи напред. Това затваря кръга ум→действие→памет: следващият план се
    # пише върху тази присъда, не върху чиста дъска. FAIL-OPEN.
    # ── 25.4. СИМВОЛНАТА КОЛОНА И РЕЛЕТО ──────────────────────────────────
    # metta_parallel гледа фийдовете с 5 правила и записва несъгласията, които
    # влизат в доклада на D_SCORE. brain_relay изнася на телефона онова, което
    # мозъкът е казал — на 20 авг той поиска човек и никой не разбра.
    beat("metta_column", "25.35")
    def _metta_column():
        from core.metta_parallel import run as _metta
        _metta()
    _run("metta_column", _metta_column)

    beat("brain_relay", "25.36")
    def _brain_relay():
        from core.brain_relay import run as _relay
        _relay()
    _run("brain_relay", _brain_relay)

    # ── 25.37. ИЗТОЧНИЦИ, КОИТО ЧАКАТ КЛЮЧ ────────────────────────────────
    # Тихото прескачане е правилно (липсващ ключ не бива да вали цикъла) и
    # точно затова е невидимо: EIA стои от 15 авг, а energy секцията беше
    # празна и въпреки това броена сред „20 източника". Веднъж СЕДМИЧНО, с
    # линка и името на променливата. Ключът тръгва сам — нула код.
    # ── 25.38. ЧАСОВНИКЪТ НА ПРЕДЛОЖЕНИЯТА ────────────────────────────────
    # Обещание за отговор до 24 часа е механизъм, не намерение. Просрочено
    # предложение ескалира ВЕДНЪЖ, поименно; после натискът се носи от брояча
    # в доклада. Всяка нощ по едно и също нещо е начинът човек да спре да чете.
    beat("proposal_sla", "25.38")
    def _proposal_sla():
        from core.proposal_sla import run as _sla_run
        _sla_run()
    _run("proposal_sla", _proposal_sla)

    beat("needs_auth", "25.37")
    def _needs_auth():
        from core.needs_auth import run as _ask
        _ask()
    _run("needs_auth", _needs_auth)

    # ── 25.44. ПРЕДВАРИТЕЛНО ЗАПИСАНИТЕ ОПИТИ ──────────────────────────────
    # Едно наблюдение на цикъл, за всеки незавършен опит. Рамото се определя от
    # поредния номер на цикъла в летописа и се ПРОВЕРЯВА срещу живия файл: ако
    # настройката не е била в сила, наблюдението се записва и НЕ СЕ БРОИ.
    beat("self_experiment", "25.44")
    def _self_experiment():
        from core.self_experiment import observe_all as _obs
        _obs()
    _run("self_experiment", _self_experiment)

    # ── 25.45. ОГЛЕДАЛОТО ──────────────────────────────────────────────────
    # Самонаблюдението вече не е ос от целта (GENERAL_SELF_REVIEW се пенсионира
    # на 21 авг 2026). Стои тук, ПРЕДИ отчета, защото отчетът чете каквото то
    # запише. Пише САМО собствените си два файла и не докосва никакво число.
    beat("self_mirror", "25.45")
    def _self_mirror():
        from core.self_mirror import run as _mirror_run
        _mirror_run(source="cycle")
    _run("self_mirror", _self_mirror)

    # ── ЕДИН СЪЗНАТЕЛЕН ПРОЧИТ НА ОГЛЕДАЛОТО (21 август 2026) ──────────────
    # Петте реда на core/interoception.py влизат във ВСЯКО повикване — това е
    # усет, а не четене: присъстват, независимо дали някой им обръща внимание.
    # Веднъж на цикъл мозъкът получава ЦЯЛОТО огледало и казва какво вижда.
    # Числата, които наистина е цитирал, се проверяват срещу огледалото (не се
    # приемат на доверие) и влизат в менюто на G_LEARN, а дебрифът на фазата е
    # длъжен да цитира поне две от тях.
    # Стои СЛЕД self_mirror, защото чете каквото то току-що е написало.
    beat("read_the_mirror", "25.46")
    def _read_the_mirror():
        from core.interoception import read_the_mirror as _rtm
        rec = _rtm()
        print(f"[FAST_CYCLE] read_the_mirror -> цитирани {rec.get('cited_count', 0)} "
              f"от {rec.get('mirror_numbers_available', 0)} числа "
              f"(квота {rec.get('quota')}, изпълнена={rec.get('met_quota')})")
        if rec.get("said"):
            print(f"[FAST_CYCLE] огледалото каза -> {str(rec['said'].get('saw'))[:200]}")
    _run("read_the_mirror", _read_the_mirror)

    beat("brain_debrief", "25.5")
    try:
        from core.brain import debrief_cycle as _debrief
        _rev = _debrief()
        if _rev:
            print(f"[FAST_CYCLE] brain review -> success={_rev.get('success')} "
                  f"| {str(_rev.get('verdict'))[:120]}")
            print(f"[FAST_CYCLE] brain blind spot -> {str(_rev.get('blind_spot'))[:120]}")
        else:
            print("[FAST_CYCLE] brain review -> no plan to judge / brain silent")
    except Exception as e:
        print(f"[FAST_CYCLE] brain review -> FAILED: {type(e).__name__}: {e}")

    # ── ОТЧЕТЪТ ПРЕД ЧОВЕКА, НАПИСАН ОТ САМАТА СИСТЕМА (Емил, 15 авг 2026) ──
    # Стъпка по стъпка: за какво служи, какво каза самата тя, удържа ли обещания
    # си файл (механична проверка по core/cycle_map.py) и какво е видял мозъкът.
    # Уводът и заключението са негови думи, не мои. FAIL-OPEN.
    beat("cycle_report", "25.6")
    try:
        from core.cycle_report import build as _rep_build, to_markdown as _rep_md, \
            telegram_text as _rep_tg
        from pathlib import Path as _P
        _rep = _rep_build()
        _dir = BASE / "output" / "reports"
        _dir.mkdir(parents=True, exist_ok=True)
        _day = str(_rep.get("ts", ""))[:10]
        (_dir / f"CYCLE_REPORT_{_day}.md").write_text(_rep_md(_rep), encoding="utf-8")
        print(f"[FAST_CYCLE] cycle_report -> output/reports/CYCLE_REPORT_{_day}.md "
              f"(кухи: {len(_rep.get('broken', []))}, паднали: {len(_rep.get('failed', []))})")
        try:                    # кратката версия отива на телефона
            from experiments.needs.needs_report import _notify as _tg_notify
            _tg_notify(_rep_tg(_rep))
        except Exception:
            pass
    except Exception as e:
        print(f"[FAST_CYCLE] cycle_report -> FAILED: {type(e).__name__}: {e}")

    # ── ПОСЛЕДНАТА ФАЗА СЕ ЗАТВАРЯ ОТ КРАЯ НА ЦИКЪЛА (21 авг 2026) ──────────
    # phase_tracker затваря фаза, когато пулсът влезе в СЛЕДВАЩАТА. За G_LEARN
    # следваща няма — цикълът свършва в нея. Затова тя не се затваряше НИКОГА:
    # на 21 август шест фази получиха дебриф, а G_LEARN нямаше дори отхвърлен
    # запис. Стъпката, в която живеят обучението, паметта и отчетът, беше
    # единствената, за която системата не казваше нищо.
    #
    # close_last() съществува от 20 авг с нула викащи. Ето го викащия. Стои
    # ПРЕДИ запечатването, за да е дебрифът вътре в цикъла, който описва.
    # FAIL-OPEN: фаза, която не може да се затвори, не проваля цикъл, който е
    # стигнал дотук.
    try:
        from core.phase_tracker import close_last as _close_last
        _close_last()
    except Exception as e:
        print(f"[FAST_CYCLE] close_last -> FAILED: {type(e).__name__}: {e}")

    # ── ПРОЗОРЕЦЪТ НА 8b СЕ ЗАТВАРЯ ОТ КРАЯ НА ЦИКЪЛА (22 авг 2026) ─────────
    # Same shape as close_last above, and for the same reason: the window opens
    # at `brain_reconsider` and its closing step would be the one AFTER
    # `cycle_report` — and there is none. Measured by walking the real step list:
    # without this call the window ends the night open, leaving qwen3:8b pinned in
    # VRAM with nothing to serve, so the next cycle's first 3b call pays a reload
    # that this whole module exists to avoid.
    try:
        from core import model_window as _mw
        _closed = _mw.close_window()
        print(f"[FAST_CYCLE] model_window closed: {_closed}")
    except Exception as e:
        print(f"[FAST_CYCLE] model_window close -> FAILED: {type(e).__name__}: {e}")

    # Cycle finished cleanly → seal the record, release the lock, drop the
    # heartbeat. Order matters: _seal_cycle_record() reads the heartbeat for the
    # cycle_id, so it must run BEFORE the heartbeat is cleared.
    _seal_cycle_record()
    try:                      # основата на проверката A/B/C за следващия цикъл
        from memory.heartbeat import read as _hb_read
        _done = (_hb_read() or {}).get("cycle_id")
        if _done:
            LAST_CYCLE_ID.write_text(str(_done), encoding="utf-8")
    except Exception:
        pass
    _clear_heartbeat()

    # Cycle finished → the organism speaks its needs in one voice: for each hunger
    # a proposal, and any candidate it found itself, written to memory/needs_brief.md
    # for the human. Runs LAST, after every memory file this cycle wrote (homeostasis,
    # composer_needs, self_directed_priority). Advisory only — nothing here acts.
    # FAIL-OPEN: a failure here never breaks a completed cycle.
    try:
        from experiments.needs.needs_report import (
            build as _needs_build, _brief as _needs_brief, _notify as _needs_notify,
        )
        _rep = _needs_build()
        _needs_notify(_needs_brief(_rep))
        _s = _rep["summary"]
        print(f"[FAST_CYCLE] needs -> {_s['total']} needs ({_s['high']} high) "
              f"-> memory/needs_brief.md")
        # Optional phone push: fires only if memory/notify_channel.json exists
        # (gitignored, holds the channel + secret). No config -> silent no-op.
        try:
            from experiments.needs.needs_report import push as _needs_push
            _pushed = _needs_push(_rep)
            if _pushed:
                print(f"[FAST_CYCLE] needs -> pushed via {_pushed}")
        except Exception as _pe:
            print(f"[FAST_CYCLE] needs push -> FAILED: {type(_pe).__name__}: {_pe}")
    except Exception as e:
        print(f"[FAST_CYCLE] needs -> FAILED: {type(e).__name__}: {e}")

    # ── RATIONALE в Telegram (14 Aug 2026, поръчано от Емил): машината, не облакът,
    # му казва какво направи и ЗАЩО — с изводите и предпоставките им. FAIL-OPEN.
    try:
        from experiments.needs.needs_report import push_rationale as _rat
        print(f"[FAST_CYCLE] rationale -> {_rat()}")
    except Exception as e:
        print(f"[FAST_CYCLE] rationale -> FAILED: {type(e).__name__}: {e}")

    print("=" * 50)
    print(f"[FAST_CYCLE] done at {_utc_now()}")
    print("=" * 50)


def _phase_cli(argv: list) -> None:
    """--only <PHASE> / --from <PHASE>: the resume gate.

    --from asserts that every phase before it already ran THIS cycle. That claim
    is checked against the artifacts on disk before anything starts, and a
    missing or stale one refuses the run by name. See core/phase_resume.py.

    HONEST LIMIT, 20 Aug 2026: this gate decides WHETHER a resume may start. It
    does not yet skip the earlier steps, because main() is one linear 900-line
    function and 30 of its 53 step bodies are inline rather than wrapped in
    _run() — the only place a skip hook exists today. Gating on _run() alone
    would silently execute those 30 while claiming to skip them, which is the
    exact class of defect the phase reports were built to expose. So --only and
    --from currently REFUSE OR PERMIT, print the phases they would run, and
    stop. Decomposing main() into per-phase callables is the follow-up that
    makes them execute; it is deliberately not being done underneath a live
    cycle.
    """
    from datetime import datetime, timezone

    from core.phase_resume import (FROM, ONLY, ResumeRefused, phase_names,
                                   verify_or_refuse)

    mode = ONLY if "--only" in argv else FROM
    flag = "--only" if mode == ONLY else "--from"
    try:
        phase = argv[argv.index(flag) + 1]
    except IndexError:
        print(f"[PHASE] {flag} needs a phase name. Have: {', '.join(phase_names())}")
        raise SystemExit(2)

    # NOT _classify_cycle_id(): that function CLAIMS memory/cycle.lock as a side
    # effect. Calling it here overwrote the lock of a cycle that was still on
    # disk — a gate that seizes the lock in order to announce it will not run is
    # worse than no gate. Everything below is read-only.
    cycle_id = os.environ.get("CORTEX_CYCLE_ID") or ""
    started = None
    lock = BASE / "memory" / "cycle.lock"
    if lock.exists():
        try:
            held = json.loads(lock.read_text(encoding="utf-8"))
            cycle_id = cycle_id or str(held.get("cycle_id") or "")
            started = datetime.fromisoformat(held["started_utc"])
        except Exception:
            started = None
    if not cycle_id:
        print("[PHASE] no cycle_id: neither CORTEX_CYCLE_ID nor a readable "
              "memory/cycle.lock. There is no cycle to resume into.")
        raise SystemExit(2)
    if started is None:
        started = datetime.now(timezone.utc)

    try:
        phases = verify_or_refuse(mode, phase, cycle_id, started)
    except ResumeRefused as exc:
        print(f"[PHASE] {exc}")
        raise SystemExit(2)

    print(f"[PHASE] {flag} {phase} — requires satisfied for cycle {cycle_id}")
    print(f"[PHASE] would run: {', '.join(phases)}")
    print("[PHASE] step-level skipping is not wired yet — see _phase_cli.__doc__. "
          "Nothing was run.")
    raise SystemExit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and ("--only" in sys.argv or "--from" in sys.argv):
        _phase_cli(sys.argv)

    if len(sys.argv) > 1 and sys.argv[1] == "--pulse":
        try:
            from memory.autonomic_pulse import start as _ps, read as _pr, stop as _pstop
        except ImportError:
            print("autonomic_pulse not available")
            sys.exit(1)
        _ps()
        print("\nPulse monitor active. Press Ctrl+C to stop.\n")
        try:
            while True:
                stats = _pr()
                print(f"CPU: {stats['cpu_pct']}% | RAM: {stats['ram_pct']}% | Free: {stats['ram_free_gb']}GB")
                time.sleep(2)
        except KeyboardInterrupt:
            print("\nStopping pulse monitor...")
            _pstop()
    else:
        # Keep the machine awake for the full cycle. Diagnosis (21 Jul 2026):
        # the cycle died mid-run ~4 of 7 mornings with no traceback -- the laptop
        # slept before the ~60-min cycle finished. The request is bound to THIS
        # process; Windows clears it on exit/death. FAIL-OPEN: if the keepalive
        # module is missing or errors, the cycle runs exactly as before.
        try:
            from experiments.keepalive.keep_awake import keep_awake as _keep_awake
        except Exception:
            from contextlib import contextmanager as _cm
            @_cm
            def _keep_awake(*a, **k):
                yield False
        # keep_awake blocks *idle* sleep but not a lid-close power action; on this
        # laptop "Lid close action" is Sleep, which kills the cycle when the lid
        # shuts mid-run. lidaction_guard sets it to "Do nothing" for the life of
        # the cycle and restores the original on exit/death (finally + atexit +
        # sidecar breadcrumb). Same FAIL-OPEN contract: missing/erroring module
        # or an unreadable setting -> the cycle runs exactly as before.
        try:
            from experiments.keepalive.lidaction_guard import lidaction_guard as _lidaction_guard
        except Exception:
            from contextlib import contextmanager as _cm
            @_cm
            def _lidaction_guard(*a, **k):
                yield False
        # ── WHO MAY ERASE THE PULSE (Kimi, 16 Aug 2026) ─────────────────────────
        #   „Heartbeat се чисти само при KeyboardInterrupt и при CYCLE_FINISHED.
        #    При всяко друго прекъсване — включително SIGTERM от watchdog — се
        #    оставя."
        # Three endings, three different truths:
        #   • CLEAN FINISH  -> main() clears it itself, after sealing the record.
        #   • HUMAN Ctrl+C  -> a decision, not a failure. Clear it, or tomorrow's
        #                      autopsy reads the frozen step as a death. (Measured:
        #                      the 16 Aug manual stop left `step: boot` behind and
        #                      it looked exactly like a boot-time death. It wasn't —
        #                      attend() was 4 seconds from returning.)
        #   • CRASH / KILL  -> LEAVE IT. It is the only record of where the cycle
        #                      was, and the only thing feeding deaths_by_step.
        try:
            _sig = __import__("signal")

            def _on_term(signum, _frame):
                # Best-effort self-report. taskkill /F cannot be caught on Windows,
                # so the supervisor's own WATCHDOG KILL log line is the real
                # fallback; this only helps when a graceful signal does arrive.
                try:
                    from memory.heartbeat import retire as _hb_retire
                    _hb_retire(f"signal {signum}", by="cycle:signal",
                               dying_by_signal=int(signum))
                except Exception:
                    pass
                raise SystemExit(128 + int(signum))

            _sig.signal(_sig.SIGTERM, _on_term)
        except Exception:
            pass  # FAIL-OPEN: no signal handling is worse than no cycle

        with _keep_awake():
            with _lidaction_guard():
                try:
                    main()
                except KeyboardInterrupt:
                    _clear_heartbeat()
                    _note_boot_abort("прекъснат от човек (Ctrl+C) — пулсът е изчистен, "
                                     "това НЕ е смърт и не бива да влиза в deaths_by_step")
                    print("[FAST_CYCLE] прекъснат от човек — пулсът е изчистен.")
                    raise SystemExit(130)
                # Any other exception propagates untouched, WITH the heartbeat
                # still on disk. That is deliberate: see the note above.