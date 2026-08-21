#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/training_log.py — ЦЕЛИ ЗА ОБУЧЕНИЕ, ВСЯКА С ПРОИЗХОДА СИ.

ЗАЩО (21 август 2026)
----------------------
Ако някога тази система се обучи на нещо, тя ще се обучи на числата, които сама
е записала. А memory/goal_score_history.json вече показва какъв е рискът:
69 llm_level срещу 28 measured — тоест ДВЕ ТРЕТИ от историята ѝ са мнения на
модел, записани със същия шрифт като четенията от NOAA. Модел, обучен върху
тази смес, ще научи собствените си халюцинации и ще ги върне като увереност.
Това не е обучение, а препис.

Затова: всяка цел носи произхода си, и произходът се класифицира от
core/measurement_honesty.py — СЪЩИЯ модул, който съди композита. Един речник,
не два.

    MEASURED   число, произведено от уред: часовник, брояч, сензор
    CARRIED    пренесено от по-ранно истинско четене
    ASSERTED   мнение на модел
    ABSENT     няма число

FAIL-CLOSED. `rows()` връща САМО MEASURED по подразбиране. Непознат произход се
класифицира като ASSERTED и остава отвън. Ако утре някой добави източник и
забрави да го впише, обучението ще получи по-малко данни — правилната посока на
грешката. Обратната посока е модел, който вярва на себе си.

ЗАБЕЛЕЖКА ЗА ТОВА КАКВО ОЗНАЧАВА „ИЗМЕРЕНО" ТУК. Произходът е за това как е
произведено ЧИСЛОТО, не за какво е то. Времето, което един разговор с модел е
отнел, е ИЗМЕРЕНО — мерил го е часовник. Присъдата, която моделът е издал в
този разговор, е ТВЪРДЯНА. Двете идват от едно и също събитие и не са едно и
също нещо.

    venv\\Scripts\\python.exe core/training_log.py --selftest
    venv\\Scripts\\python.exe -m core.training_log --harvest
    venv\\Scripts\\python.exe -m core.training_log --stats
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timezone

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.measurement_honesty import (  # noqa: E402
    ABSENT, ASSERTED, CARRIED, MEASURED, classify,
)

BASE = pathlib.Path(__file__).resolve().parents[1]

LOG = BASE / "memory" / "training_log.jsonl"
CONTRACT_BASELINE = BASE / "memory" / "step_contract_baseline.json"
BRAIN_STEP_LOG = BASE / "memory" / "brain_step_log.jsonl"

# The one target this file harvests today. Others get their own harvester and
# their own provenance string — never a shared "misc" bucket, because a bucket
# is where an asserted number goes to lose its label.
STEP_SECONDS = "step_seconds"

_last_drop_count = 0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: pathlib.Path) -> list:
    try:
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    except Exception:
        return []



# ---------------------------------------------------------------------------
# What is impossible, according to the system's own rules
# ---------------------------------------------------------------------------

WATCHDOG_TICK_SEC = 300          # supervisor.py runs every 5 minutes


def _impossible_above() -> float:
    """The longest a step could POSSIBLY have run, read from the guarded config.

    A derived duration longer than this is not a slow step — it is a gap: the
    cycle died, or the machine slept, and the next beat belongs to a different
    run. The bound is not a taste; it is the watchdog's own promise. The largest
    declared ceiling plus one supervisor tick is the most any step can survive
    before it is killed.

    Measured on this repo the difference is not cosmetic: without the bound the
    training set contained a 44302 s "step" (12.3 hours) and three more above
    18000 s. A single row like that dominates any loss computed in seconds, and
    it would have looked exactly like a legitimately slow step.
    """
    try:
        blob = json.loads((BASE / "config" / "scheduler.json").read_text(encoding="utf-8"))
        ceilings = [v for k, v in (blob.get("step_ceilings_sec") or {}).items()
                    if isinstance(v, (int, float))]
        if ceilings:
            return float(max(ceilings)) + WATCHDOG_TICK_SEC
    except Exception:
        pass
    return 3600.0 + WATCHDOG_TICK_SEC


# ---------------------------------------------------------------------------
# One row
# ---------------------------------------------------------------------------

def make_row(target: str, key: str, value, source: str, how: str,
             ts: str | None = None, **features) -> dict:
    """A target with its provenance attached, classified at birth.

    `source` goes through measurement_honesty.classify(), so the whitelist that
    decides what counts as measured for the composite decides it here too.
    `how` is free text saying WHICH instrument produced the number — a reader
    who does not believe the label must be able to go and check.
    """
    kind = classify(source) if value is not None else ABSENT
    return {
        "ts": ts or _now(),
        "target": target,
        "key": key,
        "value": (float(value) if isinstance(value, (int, float)) else None),
        "provenance": {"source": source, "how": how, "kind": kind},
        "features": features,
    }


def is_trainable(row: dict) -> bool:
    """MEASURED only, by default and by rule.

    CARRIED is excluded too: a value carried forward is a real reading repeated,
    and repeating it would weight one observation as if it were several.
    """
    return (isinstance(row, dict)
            and row.get("value") is not None
            and ((row.get("provenance") or {}).get("kind") == MEASURED))


def append(rows, path: pathlib.Path | None = None) -> int:
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(p, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def rows(target: str | None = None, include_asserted: bool = False,
         path: pathlib.Path | None = None) -> list:
    out = _read_jsonl(path or LOG)
    if target:
        out = [r for r in out if r.get("target") == target]
    if include_asserted:
        return out
    return [r for r in out if is_trainable(r)]


def stats(path: pathlib.Path | None = None) -> dict:
    all_rows = _read_jsonl(path or LOG)
    by_kind = {MEASURED: 0, CARRIED: 0, ASSERTED: 0, ABSENT: 0}
    by_target = {}
    for r in all_rows:
        k = (r.get("provenance") or {}).get("kind", ABSENT)
        by_kind[k] = by_kind.get(k, 0) + 1
        t = r.get("target", "?")
        by_target[t] = by_target.get(t, 0) + 1
    trainable = sum(1 for r in all_rows if is_trainable(r))
    return {"total": len(all_rows), "trainable": trainable,
            "excluded": len(all_rows) - trainable,
            "by_kind": by_kind, "by_target": by_target}


# ---------------------------------------------------------------------------
# Harvesters — each names its instrument
# ---------------------------------------------------------------------------

def harvest_step_seconds(baseline: pathlib.Path | None = None,
                         brain_log: pathlib.Path | None = None) -> list:
    """How long each step took. Two instruments, both clocks, both MEASURED.

    1. memory/step_contract_baseline.json — time.time() taken around _run() in
       core/step_contract.py. The step's true wall-clock length.
    2. memory/brain_step_log.jsonl — consecutive beats. Each row carries the
       moment the brain's judgement for that step FINISHED plus how long that
       judgement took, so the previous step's length is
           ts(next) - sec(next) - ts(this)
       This is arithmetic on two clock readings, not an estimate.

    Rows whose arithmetic gives a negative or absurd length are dropped, and the
    count of drops is returned rather than hidden: a silently discarded row is
    indistinguishable from a row that never existed.
    """
    out = []
    global _last_drop_count
    dropped = 0

    blob = {}
    try:
        blob = json.loads((baseline or CONTRACT_BASELINE).read_text(encoding="utf-8"))
    except Exception:
        blob = {}
    for step, record in (blob or {}).items():
        for run in (record or {}).get("runs", []):
            secs = run.get("seconds")
            if not isinstance(secs, (int, float)):
                continue
            out.append(make_row(
                STEP_SECONDS, str(step), float(secs),
                source="measured",
                how="time.time() around _run(), core/step_contract.py",
                ts=run.get("ts"),
                instrument="step_contract",
                touched=len(run.get("touched") or []),
            ))

    beats = _read_jsonl(brain_log or BRAIN_STEP_LOG)
    for i in range(len(beats) - 1):
        cur, nxt = beats[i], beats[i + 1]
        # A pair that spans a cycle boundary is not a step duration, it is the
        # machine being asleep. `boot` is the first beat of every cycle, so the
        # gap before it is the gap BETWEEN cycles. Measured on this repo: 4 such
        # pairs, the largest 66621 s — 18.5 hours, recorded as if one step had
        # taken it. A single row like that dominates any loss computed in
        # seconds and would have been invisible as "just a slow step".
        if str(nxt.get("step")) == "boot":
            continue
        try:
            t0 = datetime.fromisoformat(str(cur["ts"]))
            t1 = datetime.fromisoformat(str(nxt["ts"]))
        except Exception:
            continue
        # the next beat's timestamp is written AFTER its own judgement finished
        secs = (t1 - t0).total_seconds() - float(nxt.get("sec") or 0.0)
        if not (0.0 < secs <= _impossible_above()):
            dropped += 1
            continue
        out.append(make_row(
            STEP_SECONDS, str(cur.get("step")), round(secs, 2),
            source="measured",
            how="clock difference between consecutive beats, minus the next "
                "beat's own judgement time (memory/brain_step_log.jsonl)",
            ts=cur.get("ts"),
            instrument="heartbeat",
            stance=cur.get("stance"),
            model=cur.get("model"),
        ))
    _last_drop_count = dropped
    if dropped:
        # NO SILENT CAPS. A row removed without a count is indistinguishable
        # from a row that never existed.
        print(f"[TRAINING_LOG] dropped {dropped} derived duration(s) above "
              f"{_impossible_above():.0f}s — cycle gaps, not steps")
    return out


def harvest_asserted_levels(history: pathlib.Path | None = None) -> list:
    """The counter-example, recorded ON PURPOSE.

    memory/goal_score_history.json holds axis scores whose score_source is
    `llm_level` — a model's word. They are written into the log as ASSERTED so
    that the exclusion is VISIBLE and countable, instead of the rows quietly
    not existing. A training set that cannot show what it refused cannot be
    audited for what it accepted.
    """
    path = history or (BASE / "memory" / "goal_score_history.json")
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    records = blob if isinstance(blob, list) else blob.get("history") or []
    out = []
    for rec in records[-40:]:
        if not isinstance(rec, dict):
            continue
        ts = rec.get("timestamp") or rec.get("ts")
        sources = rec.get("score_sources") or {}
        for axis, value in (rec.get("scores") or {}).items():
            # No entry in score_sources means nobody said where the number came
            # from, and an unlabelled number is ASSERTED by rule, not by guess.
            out.append(make_row("axis_score", str(axis), value,
                                source=str(sources.get(axis) or "unlabelled"),
                                how=f"read from {path.name}", ts=ts,
                                instrument="goal_score_history"))
    return out


HARVESTERS = {
    "step_seconds": harvest_step_seconds,
    "asserted_levels": harvest_asserted_levels,
}


def _seen_keys(path: pathlib.Path | None = None) -> set:
    return {(r.get("ts"), r.get("target"), r.get("key"),
             (r.get("features") or {}).get("instrument"))
            for r in _read_jsonl(path or LOG)}


def harvest(path: pathlib.Path | None = None) -> dict:
    """Append every new grounded row. Idempotent on (ts, target, key, instrument)."""
    seen = _seen_keys(path)
    fresh, skipped = [], 0
    for name, fn in HARVESTERS.items():
        for row in fn():
            k = (row.get("ts"), row.get("target"), row.get("key"),
                 (row.get("features") or {}).get("instrument"))
            if k in seen:
                skipped += 1
                continue
            seen.add(k)
            fresh.append(row)
    n = append(fresh, path)
    s = stats(path)
    print(f"[TRAINING_LOG] +{n} rows ({skipped} already present) | "
          f"total {s['total']}, trainable {s['trainable']}, "
          f"excluded {s['excluded']} "
          f"(asserted {s['by_kind'].get(ASSERTED, 0)}, "
          f"carried {s['by_kind'].get(CARRIED, 0)}, "
          f"absent {s['by_kind'].get(ABSENT, 0)})")
    return {"appended": n, "skipped": skipped, "stats": s}


def run() -> dict:
    return harvest()


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _selftest() -> int:
    import tempfile
    print("core/training_log.py --selftest")
    ok = True
    checks = []

    m = make_row("t", "k", 1.0, source="measured", how="a clock")
    a = make_row("t", "k", 1.0, source="llm_level", how="a model said so")
    u = make_row("t", "k", 1.0, source="satellite_v2_nobody_whitelisted",
                 how="unknown")
    c = make_row("t", "k", 1.0, source="carried", how="carried forward")
    n = make_row("t", "k", None, source="measured", how="a clock with no reading")

    checks += [
        ("a clock reading is MEASURED", m["provenance"]["kind"] == MEASURED),
        ("a model's level is ASSERTED", a["provenance"]["kind"] == ASSERTED),
        (f"an UNKNOWN source is ASSERTED, not measured "
         f"({u['provenance']['kind']})", u["provenance"]["kind"] == ASSERTED),
        ("a carried value is CARRIED", c["provenance"]["kind"] == CARRIED),
        ("no number is ABSENT", n["provenance"]["kind"] == ABSENT),
        ("only MEASURED is trainable", is_trainable(m) is True),
        ("ASSERTED is NOT trainable", is_trainable(a) is False),
        ("an unknown source is NOT trainable — fail-closed",
         is_trainable(u) is False),
        ("CARRIED is NOT trainable (it would double-count one reading)",
         is_trainable(c) is False),
        ("a row with no value is NOT trainable", is_trainable(n) is False),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "log.jsonl"
        append([m, a, u, c, n], p)
        kept = rows(path=p)
        every = rows(include_asserted=True, path=p)
        s = stats(p)
        checks += [
            (f"rows() returns only the measured one ({len(kept)}/5)",
             len(kept) == 1),
            ("include_asserted=True returns all five", len(every) == 5),
            ("the excluded rows are COUNTED, not invisible",
             s["excluded"] == 4 and s["by_kind"][ASSERTED] == 2),
        ]

    # Live harvest against THIS repo, written nowhere.
    harvested = harvest_step_seconds()
    trainable = [r for r in harvested if is_trainable(r)]
    print(f"\n  live harvest: {len(harvested)} step_seconds rows, "
          f"{len(trainable)} trainable")
    by_instrument = {}
    for r in trainable:
        i = (r.get("features") or {}).get("instrument")
        by_instrument[i] = by_instrument.get(i, 0) + 1
    print(f"  by instrument: {by_instrument}")
    checks.append((f"the live harvest finds real rows ({len(trainable)})",
                   len(trainable) > 50))

    asserted = harvest_asserted_levels()
    print(f"  asserted counter-example: {len(asserted)} rows, "
          f"{sum(1 for r in asserted if is_trainable(r))} trainable")
    checks.append(("not one asserted axis level is trainable",
                   all(not is_trainable(r) for r in asserted
                       if (r['provenance']['kind'] == ASSERTED))))

    print("\n  интеграции:")
    for name, alive in (
            ("memory/step_contract_baseline.json", CONTRACT_BASELINE.exists()),
            ("memory/brain_step_log.jsonl", BRAIN_STEP_LOG.exists()),
            ("memory/goal_score_history.json",
             (BASE / "memory" / "goal_score_history.json").exists()),
            ("core.measurement_honesty (the shared taxonomy)", True)):
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
    if "--stats" in sys.argv:
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
        sys.exit(0)
    harvest()
