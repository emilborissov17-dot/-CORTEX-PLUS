#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/self_mirror.py — ОГЛЕДАЛОТО. САМОНАБЛЮДЕНИЕТО Е СЕТИВО, НЕ ОС.

ЗАЩО СЪЩЕСТВУВА (21 август 2026)
---------------------------------
До днес самонаблюдението на системата се водеше `GENERAL_SELF_REVIEW` — ос в
дървото на ЦЕЛТА, с тегло 6 от 173. Това е категорийна грешка. Целта е за
СВЕТА: устойчиви ресурси, здрави среди, стабилна цивилизация, знание,
безопасност. Колко добре машината се вижда сама не е състояние на света — то е
качеството на нейното СЕТИВО. Ос, която мери сетивото, вкарва наблюдателя в
наблюдаваното: система с влошени сензори може да вдигне композита си, като се
самооцени по-високо.

Затова осата излиза от дървото (тегло 173 -> 167) и самонаблюдението се мести
ТУК. Правилото, което този модул не нарушава никога:

    НИЩО ОТ ОГЛЕДАЛОТО НЕ ВЛИЗА В КОМПОЗИТА.

Огледалото само ОПИСВА. То не произвежда скор, не пише в никой файл, който
goal_score_calculator чете, и това се пази от test/test_self_mirror.py.

КАЛИБРАЦИЯТА Е СЪРЦЕТО
-----------------------
Останалото е събиране на числа, които вече съществуват. Новото е това: мозъкът
съди всяка стъпка (`prev_ok` в memory/brain_step_log.jsonl), а
core/step_contract.py независимо мери СЛЕДАТА на същата стъпка. Двете се
сблъскват тук:

    мозък казва „падна"  + следата казва РАБОТИ   -> ФАЛШИВА ТРЕВОГА
    мозък казва „падна"  + следата казва ПАДНА    -> ОПРАВДАНО СЪМНЕНИЕ
    мозък казва „мина"   + следата казва ПАДНА    -> ПРОПУСНАТ ПРОВАЛ
    мозък казва „мина"   + следата казва РАБОТИ   -> ПОТВЪРДЕНО
    следата не казва нищо                        -> НЕРЕШИМО (не се брои)

Измерено на цикъла от 21 август 2026: седем присъди „падна" за стъпки, всяка от
които е пипнала между 2 и 9 файла и не е хвърлила нищо. Това не е предпазливост,
а шум — и без този брояч шумът минаваше за бдителност.

FAIL-OPEN НАВСЯКЪДЕ. Огледало, което не може да се сглоби, не бива да вали
цикъла, който се опитва да свърши.

    venv\\Scripts\\python.exe core/self_mirror.py --selftest
    venv\\Scripts\\python.exe -m core.self_mirror            # сглоби и запиши
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

BASE = pathlib.Path(__file__).resolve().parents[1]

STEP_LOG = BASE / "memory" / "brain_step_log.jsonl"
CONTRACT = BASE / "memory" / "step_contract_latest.json"
BODY = BASE / "memory" / "body_scan_latest.json"
DEBRIEF_DIR = BASE / "memory" / "phase_debriefs"
CORRECTIONS = BASE / "memory" / "level_corrections.jsonl"
LATEST = BASE / "memory" / "self_mirror_latest.json"
LOG = BASE / "memory" / "self_mirror_log.jsonl"

# ── калибрационните етикети ────────────────────────────────────────────────
FALSE_ALARM = "FALSE_ALARM"
JUSTIFIED_DOUBT = "JUSTIFIED_DOUBT"
MISSED_FAILURE = "MISSED_FAILURE"
CONFIRMED = "CONFIRMED"
UNDECIDABLE = "UNDECIDABLE"

WORKED, FAILED = "WORKED", "FAILED"

# Присъди на контракта, които са ДОКАЗАТЕЛСТВО ЗА ПРОВАЛ.
_FAILED_VERDICTS = ("RAISED", "NO_EFFECT", "MISSING")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: pathlib.Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: pathlib.Path) -> list:
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Следата: какво казва core/step_contract.py
# ---------------------------------------------------------------------------

def contract_records(path: pathlib.Path | None = None) -> list:
    blob = _read_json(path or CONTRACT, {})
    rows = blob.get("steps") if isinstance(blob, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("step")]


def resolve_label(beat_name: str, labels) -> str | None:
    """Името на пулса и етикетът на контракта не винаги съвпадат.

    Измерено: пулсът бие `session_update`, а _run() увива същата стъпка като
    `session_updater`. Затова: точно съвпадение, иначе ЕДНОЗНАЧНО съвпадение по
    представка. Две кандидатури -> None; гадаенето би произвело калибрация
    срещу чужда стъпка, което е по-лошо от липсваща калибрация.
    """
    labels = set(labels)
    if beat_name in labels:
        return beat_name
    cands = [l for l in labels
             if l.startswith(beat_name) or beat_name.startswith(l)]
    return cands[0] if len(cands) == 1 else None


def footprint_verdict(record: dict) -> str:
    """WORKED | FAILED | UNDECIDABLE — какво ДОКАЗВА следата на една стъпка."""
    if not isinstance(record, dict):
        return UNDECIDABLE
    if record.get("error"):
        return FAILED
    verdict = str(record.get("verdict") or "")
    if verdict in _FAILED_VERDICTS:
        return FAILED
    if verdict == "OK":
        return WORKED
    # UNKNOWN = контрактът още се загрява. Няма базова линия, по която да съди —
    # но следата пак е доказателство: стъпка, която е пипнала файлове и не е
    # хвърлила, Е РАБОТИЛА. Нула пипнати без базова линия остава НЕРЕШИМО,
    # защото не знаем дали изобщо е трябвало да пише.
    if verdict == "UNKNOWN":
        return WORKED if (record.get("touched_count") or 0) > 0 else UNDECIDABLE
    return UNDECIDABLE


# ---------------------------------------------------------------------------
# Калибрацията
# ---------------------------------------------------------------------------

def classify(prev_ok, evidence: str) -> str:
    if evidence == UNDECIDABLE or prev_ok is None:
        return UNDECIDABLE
    if prev_ok is False:
        return FALSE_ALARM if evidence == WORKED else JUSTIFIED_DOUBT
    return CONFIRMED if evidence == WORKED else MISSED_FAILURE


def calibration(step_log_path: pathlib.Path | None = None,
                contract_path: pathlib.Path | None = None,
                since: str | None = None,
                until: str | None = None) -> dict:
    """Присъдите на мозъка, сблъскани със следата, стъпка по стъпка.

    Двойката се прави ТОЧНО: за всяка присъда се търси записът на контракта за
    СЪЩАТА предишна стъпка с най-голямо време, което е ПРЕДИ присъдата. Така
    няма прозорец, който да се сбърка, и няма сравнение с бъдещето.
    """
    records = contract_records(contract_path)
    labels = {r["step"] for r in records}
    judgements = _read_jsonl(step_log_path or STEP_LOG)

    if since is None and records:
        since = min(str(r.get("ts") or "") for r in records)

    rows = []
    for s in judgements:
        ts = str(s.get("ts") or "")
        if since and ts < since:
            continue
        if until and ts > until:
            continue
        prev = s.get("prev_step")
        if not prev:
            continue
        label = resolve_label(str(prev), labels)
        earlier = [r for r in records
                   if r["step"] == label and str(r.get("ts") or "") <= ts] \
            if label else []
        record = max(earlier, key=lambda r: str(r.get("ts") or "")) if earlier else None
        evidence = footprint_verdict(record) if record else UNDECIDABLE
        verdict = classify(s.get("prev_ok"), evidence)
        rows.append({
            "ts": ts,
            "judged_at_step": s.get("step"),
            "about_step": prev,
            "contract_label": label,
            "brain_said_ok": s.get("prev_ok"),
            "brain_note": str(s.get("prev_note") or "")[:160],
            "footprint": evidence,
            "contract_verdict": (record or {}).get("verdict"),
            "touched_count": (record or {}).get("touched_count"),
            "verdict": verdict,
            "model": s.get("model"),
        })

    counts = {FALSE_ALARM: 0, JUSTIFIED_DOUBT: 0, MISSED_FAILURE: 0,
              CONFIRMED: 0, UNDECIDABLE: 0}
    for r in rows:
        counts[r["verdict"]] += 1

    judged = sum(counts[k] for k in (FALSE_ALARM, JUSTIFIED_DOUBT,
                                     MISSED_FAILURE, CONFIRMED))
    return {
        "window_since": since,
        "window_until": until,
        "judgements_paired": judged,
        "false_alarms": counts[FALSE_ALARM],
        "justified_doubts": counts[JUSTIFIED_DOUBT],
        "missed_failures": counts[MISSED_FAILURE],
        "confirmed": counts[CONFIRMED],
        "undecidable": counts[UNDECIDABLE],
        "false_alarm_rate": (round(counts[FALSE_ALARM] / judged, 3)
                             if judged else None),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Останалите огледални повърхности
# ---------------------------------------------------------------------------

def body() -> dict:
    bs = _read_json(BODY, {})
    hw = bs.get("hardware") or {}
    sw = bs.get("software") or {}
    return {
        "ts": bs.get("ts") or bs.get("timestamp"),
        "cpu_percent": hw.get("cpu_percent"),
        "ram_percent": hw.get("ram_percent"),
        "disk_free_gb": hw.get("disk_free_gb"),
        "vram_gb": hw.get("vram_gb"),
        "ollama_status": sw.get("ollama_status"),
        "local_models": sw.get("ollama_models") or [],
    }


def stances(since: str | None = None, path: pathlib.Path | None = None) -> dict:
    rows = _read_jsonl(path or STEP_LOG)
    if since:
        rows = [r for r in rows if str(r.get("ts") or "") >= since]
    by_stance = {}
    silent = 0
    for r in rows:
        if r.get("silent"):
            silent += 1
            continue
        key = str(r.get("stance") or "?")
        by_stance[key] = by_stance.get(key, 0) + 1
    return {"total": len(rows), "silent": silent, "by_stance": by_stance,
            "models": sorted({str(r.get("model")) for r in rows if r.get("model")})}


def _current_cycle_dir(root: pathlib.Path):
    """Папката на ТЕКУЩИЯ цикъл, не „последната по азбучен ред".

    Измерено на 21 август 2026: тестовият пакет вика heartbeat.beat() с измислени
    cycle_id-та ("dead-1", "manual-run-1") срещу ЖИВАТА памет, което кара
    phase_tracker да напише истински дебрифи в тези папки. Подредба по име или
    по mtime тогава връща тестов боклук вместо цикъла. Затова първо се пита
    системата кой е цикълът ѝ, и чак ако тя мълчи — най-скорошната папка.
    """
    for src in (BASE / "memory" / "cycle.lock", BASE / "memory" / "heartbeat.json"):
        blob = _read_json(src, {})
        cid = blob.get("cycle_id") if isinstance(blob, dict) else None
        if cid:
            try:
                from core.phase_report import safe_cycle_dir
                d = root / safe_cycle_dir(str(cid))
                if d.is_dir():
                    return d
            except Exception:
                pass
    try:
        cid = (BASE / "memory" / "last_cycle_id.txt").read_text(encoding="utf-8").strip()
        from core.phase_report import safe_cycle_dir
        d = root / safe_cycle_dir(cid)
        if d.is_dir():
            return d
    except Exception:
        pass
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()]
        return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None
    except Exception:
        return None


def debriefs(cycle_dir: pathlib.Path | None = None) -> dict:
    """ПРИЕТИ И ОТХВЪРЛЕНИ. Отхвърленият дебриф е измерване на съдията, не боклук."""
    root = cycle_dir or DEBRIEF_DIR
    empty = {"cycle": None, "accepted": [], "rejected": [], "phases_missing": []}
    latest = _current_cycle_dir(root)
    if latest is None:
        return empty

    accepted, rejected = [], []
    for f in sorted(latest.glob("*.json")):
        rec = _read_json(f, {})
        entry = {"phase": rec.get("phase") or f.stem.split(".")[0],
                 "verdict": (rec.get("debrief") or {}).get("verdict"),
                 "model": (rec.get("debrief") or {}).get("_model") or rec.get("model"),
                 "attempts": rec.get("attempts"),
                 "why": (rec.get("rejected_because") or [])[:3]}
        (accepted if rec.get("accepted") else rejected).append(entry)

    seen = {e["phase"] for e in accepted + rejected}
    try:
        from core.phase_report import load_phases
        all_phases = list(load_phases().keys())
    except Exception:
        all_phases = []
    return {"cycle": latest.name, "accepted": accepted, "rejected": rejected,
            "phases_missing": [p for p in all_phases if p not in seen]}


def open_predictions() -> dict:
    """Запечатани предсказания, които още не са оценени."""
    try:
        p = str(BASE / "experiments" / "prophecy")
        if p not in sys.path:
            sys.path.insert(0, p)
        import prophecy_ledger as pl  # noqa: PLC0415
        events = pl.read_all()
    except Exception as exc:  # noqa: BLE001
        return {"open": None, "why": f"{type(exc).__name__}: {exc}"}
    scored = {e.get("ref_hash") for e in events if e.get("event") == "OUTCOME_SCORED"}
    sealed = [e for e in events if e.get("event") == "PREDICTION_SEALED"]
    still_open = [e for e in sealed if e.get("hash") not in scored]
    by_kind = {}
    for e in still_open:
        k = str(e.get("target_kind") or "?")
        by_kind[k] = by_kind.get(k, 0) + 1
    oldest = min((str(e.get("ts") or "") for e in still_open), default=None)
    return {"sealed_total": len(sealed), "open": len(still_open),
            "by_kind": by_kind, "oldest_ts": oldest}


def pending_proposals() -> dict:
    """Предложенията, които чакат човек — С ВЪЗРАСТ. Дългът на човека е част
    от огледалото точно колкото дългът на машината."""
    try:
        from core import proposal_sla
        rows = proposal_sla.all_open()
        s = proposal_sla.summary(rows)
    except Exception as exc:  # noqa: BLE001
        return {"open": None, "why": f"{type(exc).__name__}: {exc}"}
    s["oldest_five"] = [{"id": r["id"], "kind": r["kind"],
                         "age_days": round((r.get("age_hours") or 0) / 24, 1),
                         "title": str(r.get("title"))[:70]} for r in rows[:5]]
    return s


def trusted_sources() -> dict:
    try:
        from core import source_lifecycle
        return source_lifecycle.summary()
    except Exception as exc:  # noqa: BLE001
        return {"why": f"{type(exc).__name__}: {exc}"}


def level_corrections(path: pathlib.Path | None = None) -> dict:
    rows = _read_jsonl(path or CORRECTIONS)
    return {"total": len(rows),
            "recent": [{"ts": r.get("ts"), "axis": r.get("axis"),
                        "from": r.get("was") or r.get("from"),
                        "to": r.get("now") or r.get("to")} for r in rows[-5:]]}


# ---------------------------------------------------------------------------
# Сглобяване
# ---------------------------------------------------------------------------

def build(since: str | None = None) -> dict:
    cal = calibration(since=since)
    window = since or cal.get("window_since")
    return {
        "ts": _now(),
        "note": ("самонаблюдение: сетиво, не ос. НИЩО оттук не влиза в композита — "
                 "config/target_config.json вече не съдържа GENERAL_SELF_REVIEW."),
        "window_since": window,
        "body": body(),
        "stances": stances(since=window),
        "debriefs": debriefs(),
        "predictions": open_predictions(),
        "proposals": pending_proposals(),
        "sources": trusted_sources(),
        "levels": level_corrections(),
        "calibration": cal,
    }


def row(mirror: dict) -> dict:
    """Един ред: това, което може да се сравнява между пускания. Микроциклите
    добавят точно по един такъв ред."""
    cal = mirror.get("calibration") or {}
    db = mirror.get("debriefs") or {}
    return {
        "ts": mirror.get("ts"),
        "source": mirror.get("source", "cycle"),
        "false_alarms": cal.get("false_alarms"),
        "justified_doubts": cal.get("justified_doubts"),
        "missed_failures": cal.get("missed_failures"),
        "confirmed": cal.get("confirmed"),
        "undecidable": cal.get("undecidable"),
        "false_alarm_rate": cal.get("false_alarm_rate"),
        "debriefs_accepted": len(db.get("accepted") or []),
        "debriefs_rejected": len(db.get("rejected") or []),
        "open_predictions": (mirror.get("predictions") or {}).get("open"),
        "proposals_open": (mirror.get("proposals") or {}).get("open"),
        "proposals_overdue": (mirror.get("proposals") or {}).get("overdue"),
        "trusted_sources": (mirror.get("sources") or {}).get("TRUSTED"),
        "level_corrections": (mirror.get("levels") or {}).get("total"),
    }


def write(mirror: dict, latest: pathlib.Path | None = None,
          log: pathlib.Path | None = None) -> dict:
    """Един пълен файл + един ред в дневника."""
    out = {}
    try:
        p = latest or LATEST
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(mirror, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
        out["latest"] = str(p)
    except Exception as exc:  # noqa: BLE001
        out["latest"] = f"{type(exc).__name__}: {exc}"
    try:
        p = log or LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row(mirror), ensure_ascii=False) + "\n")
        out["log"] = str(p)
    except Exception as exc:  # noqa: BLE001
        out["log"] = f"{type(exc).__name__}: {exc}"
    return out


def _pct(x) -> str:
    return "—" if x is None else f"{x:.0%}"


def to_markdown(mirror: dict) -> str:
    """Секцията „Огледало" за CYCLE_REPORT. На български — човекът чете това."""
    cal = mirror.get("calibration") or {}
    db = mirror.get("debriefs") or {}
    pr = mirror.get("proposals") or {}
    pd = mirror.get("predictions") or {}
    src = mirror.get("sources") or {}
    bd = mirror.get("body") or {}
    st = mirror.get("stances") or {}

    out = ["## Огледало", "",
           "_Самонаблюдение. НЕ е ос от целта и НЕ влиза в композита._", ""]

    judged = cal.get("judgements_paired") or 0
    out += ["**Калибрация на съдията** — присъда на мозъка срещу следата на стъпката:", ""]
    if judged:
        out += [f"- фалшиви тревоги: **{cal.get('false_alarms')}** от {judged} сверени "
                f"({_pct(cal.get('false_alarm_rate'))})",
                f"- оправдани съмнения: {cal.get('justified_doubts')}",
                f"- пропуснати провала: {cal.get('missed_failures')}",
                f"- потвърдени: {cal.get('confirmed')}",
                f"- нерешими (следата мълчи): {cal.get('undecidable')}", ""]
        bad = [r for r in cal.get("rows") or [] if r.get("verdict") == FALSE_ALARM]
        if bad:
            out += ["Стъпки, обявени за паднали, които всъщност са писали на диска:", ""]
            for r in bad[:10]:
                out.append(f"- `{r['about_step']}` — контрактът: {r['contract_verdict']}, "
                           f"{r['touched_count']} пипнати файла; мозъкът е казал: "
                           f"„{r['brain_note'][:90]}“")
            out.append("")
    else:
        out += ["- няма нито една сверена присъда в този прозорец", ""]

    missing = db.get("phases_missing") or []
    out += ["**Дебрифи:** "
            f"приети {len(db.get('accepted') or [])}, "
            f"отхвърлени {len(db.get('rejected') or [])}"
            + (f"; фази без дебриф: {', '.join(missing)}" if missing else ""), ""]

    out += [f"**Отворени предсказания:** {pd.get('open')} от {pd.get('sealed_total')} запечатани"
            + (f" (най-старото {str(pd.get('oldest_ts'))[:10]})"
               if pd.get("oldest_ts") else ""), ""]

    out += [f"**Предложения без отговор:** {pr.get('open')} "
            f"(просрочени {pr.get('overdue')}; най-старото {pr.get('oldest_days')} дни)", ""]
    for r in (pr.get("oldest_five") or [])[:5]:
        out.append(f"- {r['age_days']} дни · {r['kind']} · {r['title']}")
    if pr.get("oldest_five"):
        out.append("")

    out += [f"**Източници:** доверени {src.get('TRUSTED')}, кандидати {src.get('CANDIDATE')}, "
            f"понижени {src.get('DEMOTED')}", ""]
    out += [f"**Корекции на нива:** {(mirror.get('levels') or {}).get('total')}", ""]
    by = ", ".join(f"{k}:{v}" for k, v in sorted((st.get("by_stance") or {}).items()))
    out += [f"**Стойки на мозъка:** {st.get('total')} ({st.get('silent')} мълчания) — {by}", ""]
    out += [f"**Тяло:** CPU {bd.get('cpu_percent')}%, RAM {bd.get('ram_percent')}%, "
            f"Ollama {bd.get('ollama_status')}, "
            f"модели {', '.join(bd.get('local_models') or [])}", ""]
    return "\n".join(out)


def run(source: str = "cycle") -> dict:
    m = build()
    m["source"] = source
    where = write(m)
    cal = m["calibration"]
    print(f"[MIRROR] калибрация: фалшиви тревоги {cal['false_alarms']}, "
          f"оправдани съмнения {cal['justified_doubts']}, "
          f"пропуснати провала {cal['missed_failures']}, "
          f"потвърдени {cal['confirmed']}, нерешими {cal['undecidable']}")
    print(f"[MIRROR] -> {where.get('latest')}")
    return m


# ---------------------------------------------------------------------------
# Selftest — казва кои интеграции са ЖИВИ и кои са ИНЕРТНИ В ТОЗИ репозиторий
# ---------------------------------------------------------------------------

def _selftest() -> int:
    print("core/self_mirror.py --selftest")
    ok = True
    checks = []

    # 1. Класификаторът, на синтетика с обявени етикети.
    cases = [
        ("падна + следа РАБОТИ  -> фалшива тревога", False, WORKED, FALSE_ALARM),
        ("падна + следа ПАДНА   -> оправдано съмнение", False, FAILED, JUSTIFIED_DOUBT),
        ("мина  + следа ПАДНА   -> пропуснат провал", True, FAILED, MISSED_FAILURE),
        ("мина  + следа РАБОТИ  -> потвърдено", True, WORKED, CONFIRMED),
        ("следата мълчи         -> нерешимо", False, UNDECIDABLE, UNDECIDABLE),
        ("мозъкът мълчи         -> нерешимо", None, WORKED, UNDECIDABLE),
    ]
    for name, said, evidence, expected in cases:
        got = classify(said, evidence)
        checks.append((f"{name} (got {got})", got == expected))

    # 2. Следата: какво е доказателство и какво не е.
    checks += [
        ("OK е доказателство за работа",
         footprint_verdict({"verdict": "OK", "touched_count": 3}) == WORKED),
        ("NO_EFFECT е доказателство за провал",
         footprint_verdict({"verdict": "NO_EFFECT", "touched_count": 0}) == FAILED),
        ("грешката бие присъдата",
         footprint_verdict({"verdict": "OK", "error": "boom"}) == FAILED),
        ("UNKNOWN с пипнати файлове е работа",
         footprint_verdict({"verdict": "UNKNOWN", "touched_count": 5}) == WORKED),
        ("UNKNOWN без следа е НЕРЕШИМО, не провал",
         footprint_verdict({"verdict": "UNKNOWN", "touched_count": 0}) == UNDECIDABLE),
    ]

    # 3. Разрешаването на етикети — включително измерения случай.
    labels = {"session_updater", "daily_analysis", "data_scout"}
    checks += [
        ("session_update -> session_updater",
         resolve_label("session_update", labels) == "session_updater"),
        ("точното име печели",
         resolve_label("data_scout", labels) == "data_scout"),
        ("непознато име няма етикет",
         resolve_label("no_such_step", labels) is None),
        ("двусмислената представка се отказва",
         resolve_label("data", {"data_scout", "data_load"}) is None),
    ]

    # 4. Интеграциите в ТОЗИ репозиторий: ЖИВИ или ИНЕРТНИ.
    print("\n  интеграции:")
    live = {
        "memory/brain_step_log.jsonl": STEP_LOG.exists(),
        "memory/step_contract_latest.json": CONTRACT.exists(),
        "memory/body_scan_latest.json": BODY.exists(),
        "memory/phase_debriefs/": DEBRIEF_DIR.exists(),
        "prophecy ledger": open_predictions().get("open") is not None,
        "core.proposal_sla": pending_proposals().get("open") is not None,
        "core.source_lifecycle": "TRUSTED" in trusted_sources(),
        "memory/level_corrections.jsonl": CORRECTIONS.exists(),
    }
    for name, alive in live.items():
        print(f"    {'LIVE  ' if alive else 'INERT '} {name}")

    # 5. Огледалото се сглобява на живо и НЕ пише нищо. Проверката е истинска:
    # mtime на изходния файл преди и след build(). Проверка, която не може да
    # падне, е ритуал.
    before = LATEST.stat().st_mtime if LATEST.exists() else None
    m = build()
    after = LATEST.stat().st_mtime if LATEST.exists() else None
    checks.append(("build() връща калибрация", isinstance(m.get("calibration"), dict)))
    checks.append((f"build() не пише на диска (mtime {before} -> {after})",
                   before == after))

    print()
    for name, passed in checks:
        print(f"  {'OK  ' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print(f"  RESULT: {'OK' if ok else 'BROKEN'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    run()
