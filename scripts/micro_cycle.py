#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/micro_cycle.py — МАЛКИЯТ КРЪГ: 10-15 МИНУТИ, БЕЗ ОБЛАК.

ЗАЩО (21 август 2026)
----------------------
Големият цикъл трае 1 ч 47 мин до 3 часа и върви веднъж в денонощието, в 03:00.
Значи между два цикъла има ~21 часа, в които системата не поглежда към себе си
нито веднъж. Часовоят я гледа (на 5 минути), но той гледа само дали ДИША. Дали
предсказание е узряло, дали опит е получил наблюдение, дали тялото се е
променило — това чака до следващата нощ.

Малкият кръг е тази липса. Шест стъпки, всяка локална, всяка евтина:

    body_scan            какво е тялото СЕГА
    axis_feed            числата на осите, такива каквито са на диска
    resolve_predictions  запечатаните предсказания, които вече са узрели
    observe_experiments  едно наблюдение на всеки незавършен опит
    consolidate          шестте наблюдения се сгъват в един траен запис
    mirror_row           един ред в дневника на огледалото

БЕЗ ОБЛАЧЕН МОДЕЛ — И ТОВА Е МЕХАНИЗЪМ, НЕ ОБЕЩАНИЕ.
core.backend_policy.block_cloud() се вика ПЪРВО и изключва облака за целия
процес през същата врата, през която минава всяко облачно решение. Обещание,
което се пази с надежда, е обещание без механизъм.

ВСЯКА СТЪПКА ОБЯВЯВА КАКВО ПИПА, И СЕ СЪДИ ПО ТОВА.
core/step_contract.py мери следата; тук следата се сравнява с ОБЯВЕНИЯ списък.
Пипнат файл извън обявеното е НАРУШЕНИЕ и излиза поименно. Малък кръг, който
пише където му падне, е втори голям цикъл без надзор — точно каквото не искаме
да пуснем 3-4 пъти на ден.

НЕ ВЪРВИ СРЕЩУ ГОЛЕМИЯ ЦИКЪЛ. Ако memory/cycle.lock е зает от жив процес,
малкият кръг се отказва и го казва. Две неща, които пишат в едни и същи файлове
едновременно, произвеждат история, която никой не може да разчете.

    venv\\Scripts\\python.exe scripts/micro_cycle.py            # едно пускане
    venv\\Scripts\\python.exe scripts/micro_cycle.py --dry      # само проверките
    venv\\Scripts\\python.exe scripts/micro_cycle.py --selftest
    venv\\Scripts\\python.exe scripts/micro_cycle.py --install  # печата schtasks
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LOCK = REPO / "memory" / "cycle.lock"
LATEST = REPO / "memory" / "micro_cycle_latest.json"
LOG = REPO / "memory" / "micro_cycle_log.jsonl"
BASELINE = REPO / "memory" / "micro_cycle_contract_baseline.json"
REPORT = REPO / "memory" / "micro_cycle_contract_latest.json"

# Дърветата, над които се мери следата. Различно от WATCHED на големия цикъл:
# дневникът на предсказанията живее под experiments/prophecy/ и без него
# „резолвирай предсказанията" не би имало измерима следа изобщо.
WATCHED = ("memory", "snapshots", "openclaw_queue", "output",
           "experiments/prophecy")

# Прозорците, в които малкият кръг е добре дошъл. Големият цикъл тръгва в 03:00
# местно и трае до ~3 часа; часовоят бие на 5 мин, CORTEX_Prophecy в 12:00,
# CORTEX_Collector на 4 часа. Тези четири часа не се блъскат с нищо от тях.
WINDOWS_LOCAL_HOUR = (9, 13, 17, 21)

# Meaningful upper bound for one run. Not a watchdog — a promise the report can
# be held to. 15 минути е таванът, обявен в задачата.
SOFT_BUDGET_SEC = 15 * 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# ---------------------------------------------------------------------------
# The six steps and what each one is allowed to touch
# ---------------------------------------------------------------------------

def _step_body_scan() -> dict:
    from agents.body.body_scanner import run as body_run
    body = body_run()
    return {"health": body.get("health"), "capacity_pct": body.get("capacity_pct"),
            "mode": (body.get("adaptive_directives") or {}).get("cycle_mode")}


def _step_axis_feed() -> dict:
    from agents.axis import axis_feed
    batch = axis_feed.run()
    return {"present": batch.get("present"), "absent": batch.get("absent"),
            "rejected": batch.get("rejected")}


def _step_resolve_predictions() -> dict:
    """Само детерминирани оценители. Нито един не пита модел."""
    out = {}
    sys.path.insert(0, str(REPO / "experiments" / "prophecy"))
    try:
        import prophecy  # noqa: PLC0415
        prophecy.cmd_score()
        out["self_failure"] = "scored"
    except Exception as exc:  # noqa: BLE001
        out["self_failure"] = f"{type(exc).__name__}: {exc}"
    try:
        import prophecy as _p  # noqa: PLC0415
        _p.cmd_score_axes()
        out["axis_next"] = "scored"
    except Exception as exc:  # noqa: BLE001
        out["axis_next"] = f"{type(exc).__name__}: {exc}"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "score_prophecies", REPO / "scripts" / "score_prophecies.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out["composer_series"] = mod.score_matured()
    except Exception as exc:  # noqa: BLE001
        out["composer_series"] = f"{type(exc).__name__}: {exc}"
    try:
        from core.self_mirror import open_predictions
        out["still_open"] = open_predictions().get("open")
    except Exception:
        pass
    return out


def _step_observe_experiments() -> dict:
    from core import self_experiment as sx
    rows = sx.observe_all()
    return {"observed": len(rows),
            "counted": sum(1 for r in rows if r.get("counts")),
            "running": len(sx.running())}


def _step_consolidate(state: dict) -> dict:
    """Сгъва наблюденията на този кръг в един траен запис.

    Консолидация тук значи точно това и нищо повече: наблюденията ПРЕДИ нея
    стават ЕДИН запис, който следващият кръг може да сравни със себе си. Тя НЕ
    повишава инварианти в канона и не пипа паметта на големия цикъл — малък
    кръг, който променя канона 4 пъти на ден, е самомодификация под друго име.

    ЗАПИСЪТ ПОКРИВА ЧЕТИРИТЕ НАБЛЮДАТЕЛНИ СТЪПКИ, НЕ ШЕСТТЕ. Стъпка се записва
    в state СЛЕД като приключи, значи консолидацията физически не може да види
    нито себе си, нито огледалния ред след нея. Второ записване накрая би било
    писане ИЗВЪН контракта на която и да е стъпка — тоест точно следата, която
    този кръг твърди, че няма. Затова следите на всичките шест живеят там,
    където им е мястото: memory/micro_cycle_contract_latest.json.
    """
    prev = _read_json(LATEST, {})
    record = {
        "ts": _now(),
        "previous_ts": prev.get("ts"),
        "folded_steps": sorted(state.get("steps", {})),
        "steps": state.get("steps", {}),
        "violations": state.get("violations", []),
        "seconds": state.get("seconds"),
        "all_six_footprints": str(REPORT.relative_to(REPO)),
    }
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    LATEST.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": record["ts"], "seconds": record["seconds"],
                             "violations": len(record["violations"])},
                            ensure_ascii=False) + "\n")
    return {"written": str(LATEST.relative_to(REPO))}


def _step_mirror_row() -> dict:
    from core import self_mirror
    m = self_mirror.build()
    m["source"] = "micro_cycle"
    self_mirror.write(m)
    cal = m.get("calibration") or {}
    return {"false_alarms": cal.get("false_alarms"),
            "missed_failures": cal.get("missed_failures"),
            "confirmed": cal.get("confirmed")}


# (label, fn, declared outputs — prefixes, repo-relative, forward slashes)
STEPS = (
    ("body_scan", _step_body_scan,
     ("snapshots/body/body_snapshot_latest.json",
      "memory/adaptive_directives.json",
      "memory/body_capacity_history.json")),
    ("axis_feed", _step_axis_feed,
     ("openclaw_queue/axis_feeds.jsonl",
      "openclaw_queue/axis_feeds_latest.json")),
    ("resolve_predictions", _step_resolve_predictions,
     ("experiments/prophecy/prophecy_ledger.jsonl",
      "memory/composer_state/")),
    ("observe_experiments", _step_observe_experiments,
     ("memory/self_experiments.json",
      "memory/improvement_proposals.json")),
    ("consolidate", None,
     ("memory/micro_cycle_latest.json",
      "memory/micro_cycle_log.jsonl")),
    ("mirror_row", _step_mirror_row,
     ("memory/self_mirror_latest.json",
      "memory/self_mirror_log.jsonl")),
)

# Files that ANY step may touch, because they are the system's own bookkeeping
# and are written by the machinery rather than by the step's own work. Declared
# here explicitly so "everything is allowed" never becomes the default.
ALWAYS_ALLOWED = (
    "memory/micro_cycle_contract_baseline.json",
    "memory/micro_cycle_contract_latest.json",
    "memory/llm_provenance.jsonl",
    "memory/brain_journal.jsonl",
)


def declared_for(label: str) -> tuple:
    for name, _fn, outputs in STEPS:
        if name == label:
            return outputs
    return ()


def violations(label: str, touched) -> list:
    """Пипнати файлове извън обявеното. Префикс, за да покрие и папка."""
    allowed = tuple(declared_for(label)) + ALWAYS_ALLOWED
    return sorted(f for f in touched
                  if not any(f.startswith(a) for a in allowed))


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def big_cycle_running() -> tuple:
    """(running, why). Никога не върви успоредно с големия цикъл."""
    lock = _read_json(LOCK, None)
    if not lock:
        return False, "no cycle.lock"
    pid = lock.get("pid")
    try:
        import supervisor
        alive = supervisor.pid_is_our_cycle(pid)
    except Exception:
        # FAIL-CLOSED: не можем да проверим -> приемаме, че върви.
        return True, f"cycle.lock holds pid={pid} and liveness could not be checked"
    if alive:
        return True, (f"the big cycle is running (pid={pid}, "
                      f"cycle_id={lock.get('cycle_id')})")
    return False, f"cycle.lock is stale (pid={pid} is not our cycle)"


def in_window(hour: int | None = None) -> bool:
    h = datetime.now().hour if hour is None else hour
    return h in WINDOWS_LOCAL_HOUR


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def run(dry: bool = False, force: bool = False) -> dict:
    from core import backend_policy
    from core.step_contract import StepContract

    backend_policy.block_cloud("scripts/micro_cycle.py is local-only by design")

    busy, why = big_cycle_running()
    if busy and not force:
        print(f"[MICRO] отказ: {why}")
        return {"ran": False, "why": why}

    started = time.time()
    state = {"steps": {}, "violations": []}
    print(f"[MICRO] начало {_now()} | облакът е изключен за този процес")

    for label, fn, _declared in STEPS:
        contract = StepContract(f"micro:{label}", baseline_path=BASELINE,
                                report_path=REPORT, watched=WATCHED)
        contract.__enter__()
        result, error = None, None
        try:
            if dry:
                result = {"skipped": "dry run"}
            elif label == "consolidate":
                state["seconds"] = round(time.time() - started, 1)
                result = _step_consolidate(state)
            else:
                result = fn()
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            contract.note_swallowed(error)
        finally:
            contract.finish()

        touched = getattr(contract, "touched_files", []) or []
        bad = violations(label, touched)
        state["steps"][label] = {
            "seconds": contract.result.get("seconds"),
            "verdict": contract.result.get("verdict"),
            "touched": len(touched),
            "undeclared": bad,
            "result": result,
            "error": error,
        }
        if bad:
            state["violations"].extend(f"{label}: {f}" for f in bad)
        flag = "!!" if bad else "  "
        print(f"[MICRO] {flag} {label:<20} {contract.result.get('verdict'):<9} "
              f"{contract.result.get('seconds'):>6}s  "
              f"{len(touched)} файла, {len(bad)} извън обявеното"
              + (f"  -> {error}" if error else ""))
        for f in bad[:6]:
            print(f"[MICRO]      НЕОБЯВЕН: {f}")

    state["seconds"] = round(time.time() - started, 1)
    state["ran"] = True
    state["within_budget"] = state["seconds"] <= SOFT_BUDGET_SEC
    print(f"[MICRO] край: {state['seconds']}s "
          f"({'в рамките на' if state['within_budget'] else 'НАД'} "
          f"{SOFT_BUDGET_SEC}s), нарушения: {len(state['violations'])}")
    return state


def install_text() -> str:
    py = REPO / "venv" / "Scripts" / "python.exe"
    lines = [
        "The micro-cycle is NOT registered by this script. Registering a task",
        "that runs unattended is a human act — the same rule supervisor.py --install",
        "follows. Run these four commands yourself if you want it live:",
        "",
    ]
    for h in WINDOWS_LOCAL_HOUR:
        lines.append(
            f'schtasks /create /tn CORTEX_Micro_{h:02d} /tr '
            f'"\\"{py}\\" \\"{REPO / "scripts" / "micro_cycle.py"}\\"" '
            f'/sc daily /st {h:02d}:00 /f')
    lines += [
        "",
        f"Windows chosen at {', '.join(f'{h:02d}:00' for h in WINDOWS_LOCAL_HOUR)} local.",
        "Why those: the big cycle starts 03:00 and runs up to ~3 h; CORTEX_Prophecy",
        "fires at 12:00; CORTEX_Collector every 4 h; the supervisor every 5 min.",
        "None of the four collide, and the run refuses anyway while cycle.lock is held.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("scripts/micro_cycle.py --selftest")
    ok = True
    checks = []

    # (1) Всяка стъпка има обявени изходи, и те не са празни.
    for label, _fn, outputs in STEPS:
        checks.append((f"{label} declares outputs", bool(outputs)))

    # (2) Нарушението се вижда.
    checks.append(("an undeclared file is a violation",
                   violations("mirror_row", ["memory/goal_score_history.json"])
                   == ["memory/goal_score_history.json"]))
    checks.append(("a declared file is not a violation",
                   violations("mirror_row", ["memory/self_mirror_log.jsonl"]) == []))
    checks.append(("a declared FOLDER covers its children",
                   violations("resolve_predictions",
                              ["memory/composer_state/gi_noaa_co2.json"]) == []))
    # NEGATIVE CONTROL: another step's declaration must not cover this one.
    checks.append(("one step cannot borrow another's declaration",
                   violations("mirror_row", ["memory/self_experiments.json"])
                   == ["memory/self_experiments.json"]))

    # (3) Прозорците не се блъскат с големия цикъл (03:00 + до 3 часа).
    checks.append((f"windows {WINDOWS_LOCAL_HOUR} avoid the 03:00-06:00 cycle",
                   all(h < 3 or h > 6 for h in WINDOWS_LOCAL_HOUR)))
    checks.append(("3-4 windows a day", 3 <= len(WINDOWS_LOCAL_HOUR) <= 4))
    checks.append(("in_window is true at a declared hour",
                   in_window(WINDOWS_LOCAL_HOUR[0]) is True))
    checks.append(("in_window is false at 04:00", in_window(4) is False))

    # (4) Облакът наистина се изключва през общата врата.
    from core import backend_policy
    backend_policy.reset_for_tests()
    before = backend_policy.cloud_allowed("ordinary")[0]
    backend_policy.block_cloud("selftest")
    after = backend_policy.cloud_allowed("ordinary")[0]
    backend_policy.reset_for_tests()
    checks.append((f"cloud allowed before block ({before})", before is True))
    checks.append((f"cloud refused after block ({after})", after is False))

    # (5) Отказът при зает голям цикъл — проверява се на живо.
    busy, why = big_cycle_running()
    print(f"\n  live lock check: busy={busy} — {why}")

    # (6) Интеграциите в ТОЗИ репозиторий.
    print("  интеграции:")
    live = {}
    for name, mod in (("agents.body.body_scanner", "agents.body.body_scanner"),
                      ("agents.axis.axis_feed", "agents.axis.axis_feed"),
                      ("core.self_experiment", "core.self_experiment"),
                      ("core.self_mirror", "core.self_mirror"),
                      ("core.step_contract", "core.step_contract")):
        try:
            __import__(mod)
            live[name] = True
        except Exception:
            live[name] = False
    live["experiments/prophecy/prophecy.py"] = \
        (REPO / "experiments" / "prophecy" / "prophecy.py").exists()
    live["scripts/score_prophecies.py"] = \
        (REPO / "scripts" / "score_prophecies.py").exists()
    for name, alive in live.items():
        print(f"    {'LIVE  ' if alive else 'INERT '} {name}")
        ok = ok and alive

    print()
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--install" in sys.argv:
        print(install_text())
        sys.exit(0)
    state = run(dry="--dry" in sys.argv, force="--force" in sys.argv)
    sys.exit(0 if state.get("ran") else 1)
