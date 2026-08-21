#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_experiment.py — ПРЕДВАРИТЕЛНО ЗАПИСАН ОПИТ ВЪРХУ СЕБЕ СИ.

ЗАЩО (21 август 2026)
----------------------
Системата мени собствените си настройки от месеци — тавани, редове на бекенди,
модели за дебриф — и нито една промяна не е измерена. Настройка се сменя, нещо
се случва, и после разказът за причината се пише НАЗАД. Точно това е разликата,
която целият проект съществува да улавя: твърдение срещу реалност. Прилагана
навън, а не върху себе си, тя е половин уред.

Затова: A/B опит, ЗАПИСАН ПРЕДИ да тръгне. Хипотезата, копчето, двете стойности,
метриката и колко наблюдения на рамо — всичко се фиксира при регистрацията.
Присъдата после е АРИТМЕТИКА: две средни и сравнение. Никой модел не съди
собствения си опит.

ЧЕТИРИ ПРАВИЛА, ВГРАДЕНИ В ТИПА
--------------------------------
1. САМО ОТ ALLOWED_KNOBS. Копчетата са в КОД, не в конфигурация — данните са
   точно това, което един патч най-лесно пренаписва (същият довод като в
   safety/protected_paths.py). Копче извън списъка -> Rejected.

2. ПАЗЕНИТЕ ФАЙЛОВЕ НЕ СЕ ПИПАТ. Никога. Ако копчето живее в пазен файл
   (config/, safety/, canon), опитът се регистрира, но НЕ ПИША НИЩО: рамото се
   НАБЛЮДАВА срещу това, което файлът вече казва, а другото рамо става
   ПРЕДЛОЖЕНИЕ до човека в опашката на SLA. Система, която може да си вдигне
   собствения таван, няма таван.

3. РАВНИ РАМЕНА -> Rejected. Опит, чиито две стойности съвпадат, не може да
   различи нищо. Той не е опит, а ритуал с име.

4. МЕТРИКАТА СЕ РЕШАВА ОТ МАШИНА. Всяка метрика тук се чете от файл, който
   системата вече води (existence_ledger, step_contract). Метрика, за която
   трябва да се пита модел, е мнение, преоблечено като резултат.

РАМЕНАТА СЕ РЕДУВАТ ДЕТЕРМИНИРАНО по поредния номер на цикъла: чет -> A,
нечет -> B. Без случайност — при n=4 на рамо случайният избор може да даде 7:1
и опитът да свърши без да е сравнил нищо.

    venv\\Scripts\\python.exe core/self_experiment.py --selftest
    venv\\Scripts\\python.exe -m core.self_experiment --register-first
    venv\\Scripts\\python.exe -m core.self_experiment --observe
    venv\\Scripts\\python.exe -m core.self_experiment --report
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

STORE = BASE / "memory" / "self_experiments.json"
OVERLAY = BASE / "memory" / "self_experiment_overlay.json"
LEDGER = BASE / "memory" / "existence_ledger.jsonl"
CONTRACT_BASELINE = BASE / "memory" / "step_contract_baseline.json"
IMPROVEMENTS = BASE / "memory" / "improvement_proposals.json"

# ── състояния ───────────────────────────────────────────────────────────────
REGISTERED = "REGISTERED"
BLOCKED_ON_HUMAN = "BLOCKED_ON_HUMAN"
RESOLVED = "RESOLVED"
REJECTED = "REJECTED"

LOWER_BETTER, HIGHER_BETTER = "lower_better", "higher_better"

MIN_N, MAX_N = 3, 15


# ---------------------------------------------------------------------------
# THE KNOBS — in code, on purpose
# ---------------------------------------------------------------------------
#
# Всяко копче казва: КОЙ файл го носи, кой ключ, какъв е допустимият диапазон и
# ПАЗЕН ЛИ Е файлът. Диапазонът също е в кода: и да се подправи наслойката,
# прочитането се реже до него.

ALLOWED_KNOBS = {
    "step_ceiling": {
        "file": "config/scheduler.json",
        "key": "step_ceilings_sec.<step>",
        "kind": "int",
        "band": (300, 1800),
        "guarded": True,
        "why": ("Таванът решава кога часовоят убива цикъла. Пазен файл: система, "
                "която може да си вдигне тавана, няма таван. Наблюдава се, не се "
                "пише — другото рамо е предложение до човека."),
    },
    "debrief_model": {
        "file": "memory/self_experiment_overlay.json",
        "key": "debrief_model",
        "kind": "choice",
        "choices": ("qwen2.5:3b", "qwen3:8b", "qwen2.5:7b"),
        "guarded": False,
        "why": "Кой локален модел пише дебрифите. Собствен избор, собствена памет.",
    },
    "debrief_prompt": {
        "file": "memory/self_experiment_overlay.json",
        "key": "debrief_prompt",
        "kind": "choice",
        "choices": ("base", "sharpened"),
        "guarded": False,
        "why": "Кой промпт се дава на съдията на фазата.",
    },
    "backend_order": {
        "file": "memory/self_experiment_overlay.json",
        "key": "backend_order",
        "kind": "choice",
        "choices": ("groq_first", "cerebras_first", "openrouter_first"),
        "guarded": False,
        "why": "Редът, в който се пробват облачните бекенди.",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _dig(blob, dotted: str):
    cur = blob
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


# ---------------------------------------------------------------------------
# Validation — the whole point is that this refuses things
# ---------------------------------------------------------------------------

def is_guarded(rel_path: str) -> bool:
    """Пазен ли е файлът? Пита се СЪЩИЯТ модул, който пази и патчовете, за да
    няма втори, разминаващ се списък."""
    try:
        from safety.protected_paths import is_protected
        return bool(is_protected(rel_path))
    except Exception:
        return True          # fail-closed: не знаем -> пазен


def validate(spec: dict) -> tuple:
    """(ok, reasons). Никога не хвърля — отказът е резултат, не авария."""
    reasons = []

    if not isinstance(spec, dict):
        return False, [f"not an object: {type(spec).__name__}"]

    for field in ("id", "hypothesis", "knob", "metric", "n_per_arm"):
        if not spec.get(field):
            reasons.append(f"missing field {field!r}")

    knob = spec.get("knob") or {}
    name = knob.get("name")
    if name not in ALLOWED_KNOBS:
        reasons.append(
            f"knob {name!r} is not in ALLOWED_KNOBS "
            f"({', '.join(sorted(ALLOWED_KNOBS))}) — a knob nobody declared is a "
            f"self-modification, not an experiment")
    else:
        declared = ALLOWED_KNOBS[name]
        # Файлът, посочен в заявката, трябва да е ТОЧНО декларираният.
        if knob.get("file") and knob["file"] != declared["file"]:
            reasons.append(
                f"knob {name!r} is declared on {declared['file']}, the request "
                f"names {knob['file']!r}")
        a, b = knob.get("a"), knob.get("b")
        if a == b:
            reasons.append(
                f"arm a and arm b are both {a!r} — an experiment whose arms are "
                f"equal cannot distinguish anything")
        if declared["kind"] == "int":
            lo, hi = declared["band"]
            for label, v in (("a", a), ("b", b)):
                if not isinstance(v, int) or isinstance(v, bool):
                    reasons.append(f"arm {label} is {v!r}, not an int")
                elif not (lo <= v <= hi):
                    reasons.append(
                        f"arm {label}={v} is outside the declared band [{lo}, {hi}]")
        elif declared["kind"] == "choice":
            for label, v in (("a", a), ("b", b)):
                if v not in declared["choices"]:
                    reasons.append(
                        f"arm {label}={v!r} is not one of {declared['choices']}")

    # Пазените файлове никога не се пишат — това е проверка на ЦЕЛТА, отделно
    # от списъка с копчета, точно както safety/protected_paths е отделен от
    # ast_gate. Копче, добавено един ден в ALLOWED_KNOBS с пазен файл, пак не
    # може да бъде записано.
    if knob.get("name") in ALLOWED_KNOBS:
        target = ALLOWED_KNOBS[knob["name"]]["file"]
        if is_guarded(target) and not ALLOWED_KNOBS[knob["name"]]["guarded"]:
            reasons.append(
                f"{target} is a protected path but the knob does not declare "
                f"guarded=True — the registry and the guard disagree")

    n = spec.get("n_per_arm")
    if not isinstance(n, int) or isinstance(n, bool) or not (MIN_N <= n <= MAX_N):
        reasons.append(f"n_per_arm must be an int in [{MIN_N}, {MAX_N}], got {n!r}")

    metric = spec.get("metric") or {}
    if metric.get("direction") not in (LOWER_BETTER, HIGHER_BETTER):
        reasons.append(f"metric direction {metric.get('direction')!r} is not one of "
                       f"{LOWER_BETTER}/{HIGHER_BETTER}")
    if metric.get("resolver") not in RESOLVERS:
        reasons.append(
            f"metric resolver {metric.get('resolver')!r} is not machine-resolvable "
            f"(known: {', '.join(sorted(RESOLVERS))})")

    return (not reasons), reasons


# ---------------------------------------------------------------------------
# Machine-resolvable metrics
# ---------------------------------------------------------------------------

def _kills_for_step(step: str, since: str, until: str,
                    ledger: pathlib.Path | None = None) -> int:
    """Колко пъти часовоят е убил цикъл, заклещен на ТАЗИ стъпка, в прозореца."""
    path = ledger or LEDGER
    n = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("event") != "CYCLE_KILLED":
                continue
            ts = str(e.get("ts") or "")
            if not (since <= ts <= until):
                continue
            if (e.get("reason") or {}).get("wedged_step") == step:
                n += 1
    except Exception:
        return 0
    return n


def _seconds_for_step(step: str, since: str, until: str,
                      baseline: pathlib.Path | None = None):
    """Продължителността на стъпката в прозореца, от собствения ѝ контракт."""
    blob = _read_json(baseline or CONTRACT_BASELINE, {})
    runs = ((blob.get(step) or {}).get("runs") or [])
    inside = [r for r in runs if since <= str(r.get("ts") or "") <= until]
    if not inside:
        return None
    return round(sum(float(r.get("seconds") or 0) for r in inside) / len(inside), 2)


def resolve_watchdog_and_seconds(spec: dict, since: str, until: str, **paths) -> dict:
    step = (spec.get("metric") or {}).get("step")
    return {
        "watchdog_kills": _kills_for_step(step, since, until,
                                          ledger=paths.get("ledger")),
        "step_seconds": _seconds_for_step(step, since, until,
                                          baseline=paths.get("baseline")),
    }


RESOLVERS = {"watchdog_kills+step_seconds": resolve_watchdog_and_seconds}


# ---------------------------------------------------------------------------
# The live value of a knob — read, never assumed
# ---------------------------------------------------------------------------

def live_value(knob_name: str, step: str | None = None):
    """Какво казва файлът ДНЕС. Рамото не се обявява — то се ПРОЧИТА."""
    declared = ALLOWED_KNOBS.get(knob_name)
    if declared is None:
        return None
    if knob_name == "step_ceiling":
        blob = _read_json(BASE / "config" / "scheduler.json", {})
        ceilings = blob.get("step_ceilings_sec") or {}
        return ceilings.get(step, ceilings.get("_default"))
    return _read_json(OVERLAY, {}).get(declared["key"])


def overlay_set(knob_name: str, value) -> dict:
    """Запиши НЕПАЗЕНО копче в наслойката, срязано до декларирания диапазон.

    Наслойката живее в memory/ — собствената памет на машината, където ѝ е
    позволено да действа върху себе си. Срязването е в КОДА, така че дори
    подправена наслойка не може да изнесе стойност извън обявеното.
    """
    declared = ALLOWED_KNOBS[knob_name]
    if declared["guarded"]:
        raise PermissionError(
            f"{knob_name} lives in {declared['file']}, a protected path — "
            f"an experiment never writes it")
    if declared["kind"] == "choice" and value not in declared["choices"]:
        raise ValueError(f"{value!r} is not one of {declared['choices']}")
    if declared["kind"] == "int":
        lo, hi = declared["band"]
        value = max(lo, min(hi, int(value)))
    blob = _read_json(OVERLAY, {})
    blob[declared["key"]] = value
    blob["_written_by"] = "core/self_experiment.py"
    blob["_ts"] = _now()
    _write_json(OVERLAY, blob)
    return blob


def knob(name: str, default=None):
    """Единствената врата, през която ЖИВИЯТ код чете наслойката.

    Срязването е тук, а не при писането, защото този модул не е единственото
    нещо, което може да пипне memory/.
    """
    declared = ALLOWED_KNOBS.get(name)
    if declared is None or declared["guarded"]:
        return default
    value = _read_json(OVERLAY, {}).get(declared["key"], default)
    if declared["kind"] == "choice" and value not in declared["choices"]:
        return default
    if declared["kind"] == "int":
        try:
            lo, hi = declared["band"]
            return max(lo, min(hi, int(value)))
        except Exception:
            return default
    return value


# ---------------------------------------------------------------------------
# Register / observe / resolve
# ---------------------------------------------------------------------------

def load() -> dict:
    return _read_json(STORE, {"experiments": []})


def save(blob: dict) -> None:
    _write_json(STORE, blob)


def arm_for_cycle(ordinal: int) -> str:
    """Детерминирано редуване. Чет -> a, нечет -> b."""
    return "a" if int(ordinal) % 2 == 0 else "b"


def register(spec: dict, store: pathlib.Path | None = None) -> dict:
    """Записва опита ПРЕДИ да е започнал, или отказва с причини."""
    ok, reasons = validate(spec)
    record = {
        "id": spec.get("id"),
        "registered_utc": _now(),
        "hypothesis": spec.get("hypothesis"),
        "knob": spec.get("knob"),
        "metric": spec.get("metric"),
        "n_per_arm": spec.get("n_per_arm"),
        "accepted": ok,
        "rejected_because": reasons,
        "state": REGISTERED if ok else REJECTED,
        "observations": [],
    }
    # Присъдата се смята ВЕДНАГА, дори празна: "a=0/4, b=0/4" е състояние, а
    # None е липса на състояние, и двете не изглеждат еднакво в отчета.
    record["verdict"] = verdict(record) if ok else None

    if ok:
        name = record["knob"]["name"]
        declared = ALLOWED_KNOBS[name]
        record["knob_is_guarded"] = declared["guarded"]
        record["knob_file"] = declared["file"]
        step = (record["metric"] or {}).get("step")
        current = live_value(name, step=step)
        record["live_value_at_registration"] = current
        if declared["guarded"]:
            # Рамото, което ФАЙЛЪТ вече носи, е наблюдаемо веднага. Другото
            # изисква човешка ръка и затова става предложение, не действие.
            arms = {"a": record["knob"]["a"], "b": record["knob"]["b"]}
            observable = [k for k, v in arms.items() if v == current]
            record["arms_observable_now"] = observable
            record["state"] = REGISTERED if observable else BLOCKED_ON_HUMAN
            record["blocked_note"] = (
                f"{declared['file']} is human-only. Arm(s) {observable or 'none'} "
                f"are observable because the file already reads {current!r}; the "
                f"other arm needs one human edit. A proposal was filed.")

    blob = _read_json(store or STORE, {"experiments": []})
    blob["experiments"] = [e for e in blob.get("experiments", [])
                           if e.get("id") != record["id"]] + [record]
    _write_json(store or STORE, blob)

    if ok and record.get("knob_is_guarded"):
        propose_human_arm(record)
    return record


def propose_human_arm(record: dict, improvements: pathlib.Path | None = None) -> bool:
    """Едно предложение, поименно, в същата опашка, която core/proposal_sla брои.

    ADOPTION И БЛОКИРАНО РАМО МИНАВАТ ПРЕЗ ЕДНА И СЪЩА ВРАТА. Няма втори канал,
    по който настройка да влезе в пазен файл.
    """
    knob = record["knob"]
    step = (record.get("metric") or {}).get("step")
    other = [v for k, v in (("a", knob["a"]), ("b", knob["b"]))
             if k not in (record.get("arms_observable_now") or [])]
    want = other[0] if other else knob["b"]
    key = ALLOWED_KNOBS[knob["name"]]["key"].replace("<step>", str(step))
    text = (f"experiment {record['id']}: set {key} = {want} in "
            f"{record['knob_file']} for {record['n_per_arm']} cycles")
    path = improvements or IMPROVEMENTS
    blob = _read_json(path, {"proposals": []})
    rows = blob.get("proposals")
    if not isinstance(rows, list):
        return False
    if any(isinstance(r, dict) and r.get("experiment_id") == record["id"] for r in rows):
        return False           # едно предложение на опит, никога второ
    rows.append({
        "component": record["knob_file"],
        "problem": (f"experiment {record['id']} cannot observe arm "
                    f"{want} — {record['knob_file']} is a protected path and only "
                    f"a human may change it"),
        "solution": text,
        "measurable_goal": (
            f"{record['n_per_arm']} cycles observed at {key}={want}, then "
            f"core/self_experiment.py --report gives an arithmetic verdict"),
        "priority": "MEDIUM",
        "generated_by": "core/self_experiment.py",
        "authored_by": "core/self_experiment.py",
        "experiment_id": record["id"],
        "real_world_signal": False,
        "timestamp": _now(),
    })
    blob["proposals"] = rows
    _write_json(path, blob)
    return True


def observe(exp_id: str, cycle_id: str, ordinal: int, since: str, until: str,
            store: pathlib.Path | None = None, **paths) -> dict:
    """Едно наблюдение. Рамото се ОБЯВЯВА по поредния номер и се ПРОВЕРЯВА срещу
    това, което файлът наистина е носел. Разминат ли се — наблюдението се
    записва, но НЕ СЕ БРОИ. Опит, който вярва на намерението си вместо на
    файла, мери разказ."""
    blob = _read_json(store or STORE, {"experiments": []})
    exps = blob.get("experiments", [])
    exp = next((e for e in exps if e.get("id") == exp_id), None)
    if exp is None:
        return {"error": f"no experiment {exp_id!r}"}
    if not exp.get("accepted"):
        return {"error": f"{exp_id} was rejected: {exp.get('rejected_because')}"}

    arm = arm_for_cycle(ordinal)
    expected = exp["knob"][arm]
    step = (exp.get("metric") or {}).get("step")
    in_force = live_value(exp["knob"]["name"], step=step)
    counts = (in_force == expected)

    resolver = RESOLVERS[exp["metric"]["resolver"]]
    metric = resolver(exp, since, until, **paths)

    row = {
        "ts": _now(), "cycle_id": cycle_id, "cycle_ordinal": ordinal,
        "arm_expected": arm, "value_expected": expected,
        "value_in_force": in_force, "counts": counts,
        "why_not": None if counts else
                   (f"the file read {in_force!r}, the alternation asked for "
                    f"{expected!r} — arm not applied"),
        "window": [since, until],
        "metric": metric,
    }
    exp["observations"] = [o for o in exp.get("observations", [])
                           if o.get("cycle_id") != cycle_id] + [row]
    exp["verdict"] = verdict(exp)
    if exp["verdict"].get("decided"):
        exp["state"] = RESOLVED
    _write_json(store or STORE, blob)
    return row


def _arm_rows(exp: dict, arm: str) -> list:
    return [o for o in exp.get("observations", [])
            if o.get("counts") and o.get("arm_expected") == arm]


def _mean(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 3) if vals else None


def verdict(exp: dict) -> dict:
    """АРИТМЕТИКА. Основната метрика решава; при равенство решава втората.
    Пълно равенство е ОТКАЗ ОТ ПРИСЪДА, не победа за статуквото."""
    n = exp.get("n_per_arm") or MIN_N
    a, b = _arm_rows(exp, "a"), _arm_rows(exp, "b")
    out = {
        "n_a": len(a), "n_b": len(b), "n_per_arm": n,
        "kills_a": _mean([r["metric"].get("watchdog_kills") for r in a]),
        "kills_b": _mean([r["metric"].get("watchdog_kills") for r in b]),
        "seconds_a": _mean([r["metric"].get("step_seconds") for r in a]),
        "seconds_b": _mean([r["metric"].get("step_seconds") for r in b]),
        "decided": False, "winner": None, "why": None,
    }
    if len(a) < n or len(b) < n:
        out["why"] = (f"not enough counted observations: a={len(a)}/{n}, "
                      f"b={len(b)}/{n}")
        return out

    ka, kb = out["kills_a"], out["kills_b"]
    if ka is not None and kb is not None and ka != kb:
        out.update(decided=True, winner=("a" if ka < kb else "b"),
                   why=f"watchdog kills {ka} vs {kb} (lower wins)")
        return out
    sa, sb = out["seconds_a"], out["seconds_b"]
    if sa is not None and sb is not None and sa != sb:
        out.update(decided=True, winner=("a" if sa < sb else "b"),
                   why=f"kills tied at {ka}; step seconds {sa} vs {sb} (lower wins)")
        return out
    out["why"] = "both metrics tied — no winner; the knob did not matter"
    out["decided"] = True
    return out


def adopt(exp: dict, improvements: pathlib.Path | None = None) -> dict:
    """Победителят НЕ се прилага сам. Той става предложение в опашката на SLA.

    Това е границата: опитът е свободен да НАБЛЮДАВА себе си, но да ЗАКРЕПИ
    промяна в постоянна настройка е решение с последствия, и то минава през
    човек — същият канал като всяко друго предложение, със същия часовник.
    """
    v = exp.get("verdict") or {}
    if not v.get("decided") or not v.get("winner"):
        return {"proposed": False, "why": "no winner to adopt"}
    win = exp["knob"][v["winner"]]
    step = (exp.get("metric") or {}).get("step")
    key = ALLOWED_KNOBS[exp["knob"]["name"]]["key"].replace("<step>", str(step))
    path = improvements or IMPROVEMENTS
    blob = _read_json(path, {"proposals": []})
    rows = blob.get("proposals")
    if not isinstance(rows, list):
        return {"proposed": False, "why": "improvement_proposals.json is not a list"}
    marker = f"{exp['id']}:adopt"
    if any(isinstance(r, dict) and r.get("experiment_id") == marker for r in rows):
        return {"proposed": False, "why": "already proposed"}
    rows.append({
        "component": exp.get("knob_file"),
        "problem": f"experiment {exp['id']} resolved: {v.get('why')}",
        "solution": f"adopt {key} = {win}",
        "measurable_goal": v.get("why"),
        "priority": "MEDIUM",
        "generated_by": "core/self_experiment.py",
        "authored_by": "core/self_experiment.py",
        "experiment_id": marker,
        "real_world_signal": False,
        "timestamp": _now(),
    })
    blob["proposals"] = rows
    _write_json(path, blob)
    return {"proposed": True, "adopt": f"{key}={win}"}


# ---------------------------------------------------------------------------
# The first experiment
# ---------------------------------------------------------------------------

FIRST = {
    "id": "exp-001-daily-analysis-ceiling",
    "hypothesis": (
        "daily_analysis е убивана от часовоя на 900 s таван (измерено: "
        "CYCLE_KILLED, wedged_step=daily_analysis, heartbeat_age 972.7 s, "
        "20 авг 2026). Ако таванът ѝ стане 1500 s, стъпката ще довърши и "
        "убийствата ще паднат, без средното ѝ време да порасне — защото 764 s "
        "е реалната ѝ дължина, а не таванът."),
    "knob": {"name": "step_ceiling", "file": "config/scheduler.json",
             "step": "daily_analysis", "a": 900, "b": 1500},
    "metric": {"resolver": "watchdog_kills+step_seconds",
               "step": "daily_analysis", "direction": LOWER_BETTER},
    "n_per_arm": 4,
}


def register_first() -> dict:
    return register(FIRST)


def report() -> str:
    blob = load()
    lines = []
    for e in blob.get("experiments", []):
        v = e.get("verdict") or {}
        lines.append(f"{e['id']}  [{e.get('state')}]")
        lines.append(f"  hypothesis: {str(e.get('hypothesis'))[:110]}")
        lines.append(f"  knob: {e.get('knob', {}).get('name')} "
                     f"{e.get('knob_file')} a={e.get('knob', {}).get('a')} "
                     f"b={e.get('knob', {}).get('b')} guarded={e.get('knob_is_guarded')}")
        if not e.get("accepted"):
            lines.append(f"  REJECTED: {'; '.join(e.get('rejected_because') or [])}")
            continue
        lines.append(f"  observations: a={v.get('n_a')}/{e.get('n_per_arm')} "
                     f"b={v.get('n_b')}/{e.get('n_per_arm')}")
        lines.append(f"  kills a={v.get('kills_a')} b={v.get('kills_b')} | "
                     f"seconds a={v.get('seconds_a')} b={v.get('seconds_b')}")
        lines.append(f"  verdict: {v.get('why')}")
        if e.get("blocked_note"):
            lines.append(f"  blocked: {e['blocked_note']}")
    return "\n".join(lines) or "(no experiments registered)"


def running() -> list:
    """За микроцикъла: опитите, които още не са решени."""
    return [e for e in load().get("experiments", [])
            if e.get("accepted") and e.get("state") in (REGISTERED, BLOCKED_ON_HUMAN)]


# ---------------------------------------------------------------------------
# Observing from inside a live cycle
# ---------------------------------------------------------------------------

def current_cycle_id() -> str | None:
    for src in (BASE / "memory" / "cycle.lock", BASE / "memory" / "heartbeat.json"):
        blob = _read_json(src, {})
        if isinstance(blob, dict) and blob.get("cycle_id"):
            return str(blob["cycle_id"])
    return None


def cycle_ordinal(ledger: pathlib.Path | None = None,
                  current: str | None = None) -> int:
    """КОЛКО ЦИКЪЛА СА БИЛИ ПРЕДИ ТОЗИ — броени по различни cycle_id в летописа.

    Броячът е чужд: memory/existence_ledger.jsonl е ПАЗЕН файл и е верижно
    подписан. Опитът не може да си избере рамото, като пренапише брояча.

    ── ЗАЩО НЕ CYCLE_STARTED (поправено на 21 август 2026, по време на първия
       наблюдаван цикъл) ─────────────────────────────────────────────────────
    CYCLE_STARTED се пише от supervisor.py, не от бегача. Значи ръчно пуснат
    цикъл НЕ мърда този брояч изобщо: два ръчни цикъла подред получаваха ЕДНО И
    СЪЩО рамо, а редуването — цялата причина за детерминирания избор — просто
    спираше. Обратното също беше вярно и по-лошо: при supervisor-ски цикъл
    неговият собствен CYCLE_STARTED вече стои в летописа по време на пробега, а
    при ръчен не стои, тоест двата вида пробег броят различно СЕБЕ СИ.

    Броенето по различни cycle_id, с изваден ТЕКУЩИЯ, няма нито единия проблем:
    еднакво е за всеки начин на пускане и не зависи от това дали цикълът е
    успял да обяви началото си.
    """
    path = ledger or LEDGER
    mine = current if current is not None else current_cycle_id()
    seen = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            cid = json.loads(line).get("cycle_id")
            if cid:
                seen.add(str(cid))
    except Exception:
        return 0
    seen.discard(mine)
    return len(seen)


# Събития, които приключват цикъл. КЪМ КОЕТО И ДА Е ОТ ТЯХ — цикълът вече не
# тече и прозорецът му е затворен.
TERMINAL_EVENTS = ("CYCLE_FINISHED", "CYCLE_KILLED", "CYCLE_DIED",
                   "CYCLE_FAILED_BUDGET_EXHAUSTED")


def last_closed_cycle(ledger: pathlib.Path | None = None) -> tuple:
    """(cycle_id, since, until, ordinal) на последния ЗАВЪРШИЛ цикъл.

    ── ЗАЩО НЕ ТЕКУЩИЯ (научено на живо, 21 август 2026) ───────────────────
    Първият цикъл с този наблюдател беше УБИТ от часовоя на `daily_analysis`,
    982 s срещу таван 900 s — точно провалът, за който exp-001 е записан. И
    точно затова наблюдението не се случи: наблюдателят стои на стъпка 25.44, а
    цикълът умря на стъпка 22.

    Опит за стъпка, която сваля цикъла, НИКОГА не може да бъде наблюдаван от
    наблюдател, който върви в края на същия цикъл. Това не е нещастно съвпадение
    — това е системна слепота точно към най-интересния случай: колкото по-вярна
    е хипотезата, толкова по-сигурно наблюдението не се записва.

    Затова цикълът се съди СЛЕД като е свършил, от летописа, който помни и
    убийството. Днешният цикъл записва вчерашния. Метриката така или иначе се
    чете от летописа и от контракта, не от жива памет, така че нищо не се губи
    от изчакването — а всичко се губи от това да не изчакаш.
    """
    path = ledger or LEDGER
    try:
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    except Exception:
        return (None, None, None, 0)

    closed = None
    for e in rows:
        if e.get("event") in TERMINAL_EVENTS and e.get("cycle_id"):
            closed = e.get("cycle_id")
    if closed is None:
        return (None, None, None, 0)

    mine = [e for e in rows if e.get("cycle_id") == closed]
    since = min(str(e.get("ts") or "") for e in mine)
    until = max(str(e.get("ts") or "") for e in mine)

    # A cycle_id IS its start time, and it is the only start a manually launched
    # cycle has — supervisor.py writes CYCLE_STARTED, the runner does not. Without
    # this the window of a manual run collapses to the instant of its own death:
    # measured on the 21 Aug kill, since == until == 14:24:02. The kill still fell
    # inside it, so the count came out right — by the luck of an inclusive bound,
    # which is not a thing to build on.
    try:
        started = datetime.fromisoformat(str(closed).replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        iso = started.astimezone(timezone.utc).isoformat()
        since = min(since, iso)
    except Exception:
        pass

    # Поредният номер Е НА НАБЛЮДАВАНИЯ ЦИКЪЛ, не на текущия: рамото, което се
    # съди, е онова, което е било в сила ТОГАВА.
    seen, ordinal = set(), 0
    for e in rows:
        cid = e.get("cycle_id")
        if not cid or cid in seen:
            continue
        if cid == closed:
            ordinal = len(seen)
            break
        seen.add(str(cid))
    return (closed, since, until, ordinal)


def last_cycle_window(ledger: pathlib.Path | None = None) -> tuple:
    """(cycle_id, since, until) на последния ЗАВЪРШИЛ цикъл — без поредния номер."""
    cid, since, until, _ = last_closed_cycle(ledger)
    return (cid, since, until)


def observe_all(store: pathlib.Path | None = None) -> list:
    """Наблюдава ВСЕКИ незавършен опит за последния ЗАВЪРШИЛ цикъл. FAIL-OPEN.

    Повторно наблюдение на същия цикъл е безобидно: observe() заменя реда по
    cycle_id, така че един цикъл дава точно едно наблюдение колкото пъти и да
    бъде извикано.
    """
    cid, since, until, ordinal = last_closed_cycle()
    if not cid:
        print("[EXPERIMENT] няма завършил цикъл в летописа — няма какво да се наблюдава")
        return []
    out = []
    for exp in running():
        row = observe(exp["id"], cid, ordinal, since, until, store=store)
        out.append(row)
        if row.get("error"):
            print(f"[EXPERIMENT] {exp['id']}: {row['error']}")
            continue
        print(f"[EXPERIMENT] {exp['id']} cycle #{ordinal} arm {row['arm_expected']} "
              f"({row['value_expected']}) — "
              + ("counted" if row["counts"] else f"NOT counted: {row['why_not']}")
              + f" | {row['metric']}")
    # решените се предлагат за осиновяване веднъж
    for exp in load().get("experiments", []):
        if (exp.get("verdict") or {}).get("decided") and (exp["verdict"].get("winner")):
            res = adopt(exp)
            if res.get("proposed"):
                print(f"[EXPERIMENT] {exp['id']} -> предложение: {res['adopt']}")
    return out


def run() -> list:
    return observe_all()


# ---------------------------------------------------------------------------
# Selftest — the negative controls are the deliverable
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import copy
    import tempfile
    print("core/self_experiment.py --selftest")
    ok = True
    checks = []

    # (1) NEGATIVE CONTROL: canon.py as a knob -> Rejected.
    canon_spec = copy.deepcopy(FIRST)
    canon_spec["id"] = "neg-canon"
    canon_spec["knob"] = {"name": "canon", "file": "core/canon.py",
                          "a": "old", "b": "new"}
    accepted, reasons = validate(canon_spec)
    checks.append((f"canon.py as knob is Rejected ({reasons[0][:60] if reasons else ''})",
                   accepted is False))
    checks.append(("core/canon.py is recognised as a protected path",
                   is_guarded("core/canon.py") is True))

    # (2) NEGATIVE CONTROL: equal arms -> Rejected.
    equal = copy.deepcopy(FIRST)
    equal["id"] = "neg-equal"
    equal["knob"] = {**FIRST["knob"], "a": 900, "b": 900}
    accepted, reasons = validate(equal)
    checks.append((f"equal a/b is Rejected ({reasons[0][:60] if reasons else ''})",
                   accepted is False and
                   any("equal" in r for r in reasons)))

    # (3) The first experiment itself validates.
    accepted, reasons = validate(FIRST)
    checks.append((f"the first experiment validates ({reasons})", accepted is True))

    # (4) Out-of-band arm -> Rejected.
    wide = copy.deepcopy(FIRST)
    wide["id"] = "neg-band"
    wide["knob"] = {**FIRST["knob"], "b": 99999}
    accepted, _ = validate(wide)
    checks.append(("an arm outside the declared band is Rejected", accepted is False))

    # (5) n outside [3, 15] -> Rejected.
    for bad_n in (1, 2, 16, 100):
        accepted, _ = validate({**FIRST, "id": "n", "n_per_arm": bad_n})
        checks.append((f"n_per_arm={bad_n} is Rejected", accepted is False))

    # (6) A metric no machine can resolve -> Rejected.
    vague = copy.deepcopy(FIRST)
    vague["metric"] = {**FIRST["metric"], "resolver": "the model decides"}
    accepted, _ = validate(vague)
    checks.append(("a metric that is not machine-resolvable is Rejected",
                   accepted is False))

    # (7) A guarded knob refuses to be written, loudly.
    try:
        overlay_set("step_ceiling", 1500)
        wrote = True
    except PermissionError:
        wrote = False
    checks.append(("overlay_set refuses a guarded knob", wrote is False))

    # (8) Deterministic alternation.
    arms = [arm_for_cycle(i) for i in range(6)]
    checks.append((f"alternation is deterministic ({arms})",
                   arms == ["a", "b", "a", "b", "a", "b"]))

    # (9) Verdict arithmetic, on synthetic observations with declared labels.
    with tempfile.TemporaryDirectory() as tmp:
        exp = {"id": "t", "n_per_arm": 2, "knob": {"name": "step_ceiling",
               "a": 900, "b": 1500}, "metric": {"step": "s"}, "observations": []}
        def obs(arm, kills, secs, counts=True):
            return {"cycle_id": f"{arm}{kills}{secs}{counts}", "counts": counts,
                    "arm_expected": arm,
                    "metric": {"watchdog_kills": kills, "step_seconds": secs}}
        exp["observations"] = [obs("a", 1, 800), obs("a", 1, 820),
                               obs("b", 0, 900), obs("b", 0, 910)]
        v = verdict(exp)
        checks.append((f"fewer kills wins ({v.get('winner')}, {v.get('why')})",
                       v["decided"] and v["winner"] == "b"))

        exp["observations"] = [obs("a", 0, 800), obs("a", 0, 800),
                               obs("b", 0, 800), obs("b", 0, 800)]
        v = verdict(exp)
        checks.append((f"a dead heat decides nothing ({v.get('why')})",
                       v["decided"] and v["winner"] is None))

        exp["observations"] = [obs("a", 0, 800, counts=False),
                               obs("a", 0, 800), obs("b", 0, 900), obs("b", 0, 900)]
        v = verdict(exp)
        checks.append((f"an unapplied arm does not count ({v.get('why')})",
                       v["decided"] is False and v["n_a"] == 1))

    # (10) Integrations, in THIS repo.
    print("\n  интеграции:")
    live = {
        "memory/existence_ledger.jsonl (watchdog kills)": LEDGER.exists(),
        "memory/step_contract_baseline.json (step seconds)": CONTRACT_BASELINE.exists(),
        "config/scheduler.json (the guarded ceiling)":
            (BASE / "config" / "scheduler.json").exists(),
        "memory/improvement_proposals.json (the SLA queue)": IMPROVEMENTS.exists(),
        "safety.protected_paths": is_guarded("core/canon.py") is True,
    }
    for name, alive in live.items():
        print(f"    {'LIVE  ' if alive else 'INERT '} {name}")

    print()
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--register-first" in sys.argv:
        rec = register_first()
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        sys.exit(0)
    if "--observe" in sys.argv:
        observe_all()
        print()
    print(report())
