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
            _mine = other_pid is not None and int(other_pid or -1) == os.getpid()
            if other_id and not _mine and _pid_alive(other_pid):
                print(f"[FAST_CYCLE] BOOT ABORT: вече тече цикъл {other_id} "
                      f"(pid {other_pid}, жив) — случай D. Два цикъла върху едни и "
                      f"същи файлове е по-лошо от нито един.")
                _note_boot_abort(f"застъпване: жив цикъл {other_id} pid={other_pid}")
                raise SystemExit(3)
            if other_id and not _pid_alive(other_pid):
                print(f"[FAST_CYCLE] boot -> заварена мъртва ключалка на {other_id} "
                      f"(pid {other_pid}); продължавам.")
    except SystemExit:
        raise
    except Exception:
        pass

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

def _free_ollama():
    gc.collect()

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
    # 15 Aug 2026 (закон, т.1 и 3): преди да тръгне стъпка, се пита мозъкът какво
    # е казал за нея в beat(). Ако е решил "пропусни" — пропуска се и се записва
    # ЧИЯ е била преценката. Гръбнакът на одита не се пропуска по мнение
    # (core.brain.skipped_by_brain пази този списък).
    try:
        from core.brain import skipped_by_brain as _skip, stance as _stance
        if _skip(label):
            print(f"[FAST_CYCLE] {label} -> SKIPPED BY BRAIN: "
                  f"{str(_stance().get('expect'))[:120]}")
            return
    except Exception:
        pass
    try:
        fn()
        print(f"[FAST_CYCLE] {label} -> OK")
    except Exception as e:
        # str(e) can be empty (e.g. bare MemoryError()) — always show the
        # exception type too, so a failure never renders as a blank message.
        print(f"[FAST_CYCLE] {label} -> FAILED: {type(e).__name__}: {e}")
    if free_after:
        _free_ollama()
    gc.collect()  # release memory after every agent step

def run_web_intelligence():
    try:
        sys.path.insert(0, str(BASE))
        from web_intelligence_agent import run as _wi_run
        _wi_run()
        print("[FAST_CYCLE] web_intelligence_agent -> OK")
    except ImportError:
        print("[FAST_CYCLE] web_intelligence_agent -> SKIP")
    except Exception as e:
        print(f"[FAST_CYCLE] web_intelligence_agent -> FAILED: {e}")
    gc.collect()

def refresh_llm_axes():
    axes = [
        {
            "axis": "GENERAL_SELF_REVIEW",
            "folder": "general_self_review",
            "domain": "cosmos",
            "use_reasoner": True,
        },
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

    # ── Self-heal (14 Aug 2026): the ddgs search package was missing for weeks and
    # web intelligence ran blind — a dependency the system can install for itself.
    # Narrow by design: ONE hardcoded, known-safe package, own venv, logged, fail-open.
    # This is self-maintenance inside the machine, not an action on the world.
    try:
        import ddgs  # noqa: F401
        checks["pkg_ddgs"] = {"present": True, "level": "optional"}
    except ImportError:
        try:
            import subprocess as _sp
            r = _sp.run([sys.executable, "-m", "pip", "install", "ddgs"],
                        capture_output=True, text=True, timeout=180)
            ok = r.returncode == 0
            checks["pkg_ddgs"] = {"present": ok, "level": "optional",
                                  "self_installed": ok,
                                  "note": (r.stdout or r.stderr)[-160:]}
            print(f"[DEP_CHECK] {'SELF-INSTALLED' if ok else 'INSTALL FAILED':14s} ddgs (optional)")
        except Exception as _ie:
            checks["pkg_ddgs"] = {"present": False, "level": "optional",
                                  "error": f"{type(_ie).__name__}: {_ie}"[:120]}
            print(f"[DEP_CHECK] INSTALL ERROR ddgs: {type(_ie).__name__}")

    # 1. Проверка на ключове
    key_levels = {
        "GROQ_API_KEY":    "critical",
        "GEMINI_API_KEY":  "important",
        "YOUTUBE_API_KEY": "optional",
        "NASA_API_KEY":    "optional",
    }
    for key, level in key_levels.items():
        present = bool(os.environ.get(key))
        checks[key] = {"present": present, "level": level}
        if not present and level == "critical":
            critical_ok = False
        print(f"[DEP_CHECK] {'OK' if present else 'MISSING':7s} {key} ({level})")

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
                print(f"[DEP_CHECK] FAIL    groq_chat: HTTP {r.status_code}")
                critical_ok = False
        except Exception as e:
            checks["groq_chat"] = {"ok": False, "error": str(e)[:150]}
            print(f"[DEP_CHECK] FAIL    groq_chat: {e}")
            critical_ok = False
    else:
        checks["groq_chat"] = {"ok": False, "error": "no key"}

    # 3. Groq Whisper — same key as groq_chat; ако chat мина, Whisper ще мине също
    if checks.get("groq_chat", {}).get("ok"):
        checks["groq_whisper"] = {"ok": True, "note": "key verified via groq_chat"}
        print("[DEP_CHECK] OK      groq_whisper (key verified via groq_chat)")
    else:
        checks["groq_whisper"] = {"ok": False, "note": "skipped — groq_chat failed"}
        print("[DEP_CHECK] SKIP    groq_whisper (groq_chat failed)")

    report = {
        "timestamp":       _utc_now(),
        "all_critical_ok": critical_ok,
        "checks":          checks,
        "note":            "" if critical_ok else (
            "ЦИКЪЛЪТ Е СПРЯН. Провери горните грешки и рестартирай fast_cycle_runner.py."
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
    snap_dir = BASE / "snapshots"
    flagged = []
    for path in snap_dir.rglob("*.json"):
        if "master" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
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


def _witness_or_refuse(step: str) -> bool:
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
    beat("boot", "-1", cycle_id=_cycle_id)

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
        print("\n[FAST_CYCLE] СПРЯН — dependency check failed.")
        print("[FAST_CYCLE] Отчет: snapshots/master/dependency_check_latest.json")
        return

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
        gi_path.parent.mkdir(parents=True, exist_ok=True)
        gi_path.write_text(json.dumps(gi_data, ensure_ascii=False, indent=2), encoding="utf-8")
        co2  = gi_data.get("co2", {}).get("co2_ppm", "?")
        temp = gi_data.get("temperature", {}).get("temp_anomaly_c", "?")
        conf = gi_data.get("conflicts", {}).get("active_armed_conflicts", "?")
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

    # ── 2.7. Grounding ledger (E2) — record per-axis anchor-vs-daily divergence and
    #    proxy agreement, tamper-evidently. Reads composed_indicators, appends to its
    #    own ledger — NEVER touches scoring. Inert (no alerts) until daily sources are
    #    live, then it surfaces contradictions the human can act on. FAIL-OPEN.
    beat("grounding_ledger", "2.7")
    try:
        from experiments.grounding.divergence_ledger import record as _ground_record
        _ground_record()
    except Exception as e:
        print(f"[FAST_CYCLE] grounding_ledger -> FAILED: {type(e).__name__}: {e}")

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

    # ── 12.6. Goal score calculator ──
    beat("goal_score_calculator", "12.6")
    composite = 0.0  # initialized here so MerkleMemory commit can read it at step 24
    def _goal_score_calculator():
        nonlocal composite
        from goal_score_calculator import compute_goal_score
        gs_result = compute_goal_score()
        composite  = gs_result["composite_score"]
        print(f"[FAST_CYCLE] goal_score_calculator -> composite={composite:.4f}")
        # Persist result as snapshot so master + MerkleMemory can read it
        gs_snap = BASE / "snapshots" / "master" / "goal_score_latest.json"
        gs_snap.parent.mkdir(parents=True, exist_ok=True)
        gs_snap.write_text(
            json.dumps({**gs_result, "axis": "GOAL_SCORE", "source_type": "CALCULATED"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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

    beat("cognitive_orchestrator", "12.7")
    # Runs BEFORE HyperClaw so it can use its priority_axes assessment.
    # (CortexStrategist was moved to step 3.5 to run before token budget is depleted.)
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
    if not _witness_or_refuse("github_publish"):
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
    if _witness_or_refuse("self_modifier"):
        _run("self_modifier", lambda: __import__(
            "agents.core.self_modifier", fromlist=["run"]).run(), free_after=True)

    # ── 19. Execute patches — вика auto_level вътрешно за реален before/after ──
    beat("execute_patches", "19")
    if _witness_or_refuse("execute_patches"):
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

    # ── МОЗЪКЪТ ЗАТВАРЯ ЦИКЪЛА (закон, т.3) ────────────────────────────────
    # Той сам съди сбъднал ли се е ТЕСТЪТ, който сам си зададе сутринта, и какво
    # да носи напред. Това затваря кръга ум→действие→памет: следващият план се
    # пише върху тази присъда, не върху чиста дъска. FAIL-OPEN.
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


if __name__ == "__main__":
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
        with _keep_awake():
            with _lidaction_guard():
                main()