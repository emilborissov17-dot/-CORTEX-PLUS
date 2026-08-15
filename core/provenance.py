#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/provenance.py — ПРОИЗХОДЪТ НА ЧИСЛОТО (15 август 2026)

Kimi, след като Емил попита „защо точно 20 източника" и се оказа, че седем от тях
са един хост:

  „Подходът е сгрешен в основата: фетишизираш „твърдите числа" като ground truth,
   а те са просто API отговори СЪС ЗАКЪСНЕНИЕ и без контекст. grounding_ledger
   валидира LLM срещу данни, но не валидира ДАННИТЕ СРЕЩУ РЕАЛНОСТТА — няма
   мета-валидатор... Оси без числа не са „неизмервани" — те са ИЗМЕРЕНИ ОТ LLM БЕЗ
   КОНТРОЛ, което е по-опасно от призната невежда... Не ви трябват повече хостове,
   а СТРУКТУРИРАНА НЕСИГУРНОСТ."

Той поиска доверие-интервал. Възразих му и държа на възражението: интервал върху
число с НЕИЗВЕСТНА ДАВНОСТ е по-опасен от липсата на интервал, защото придава вид
на строгост. Затова редът тук е: първо ПРОИЗХОД, после несигурност — и несигурността
е изведена от произхода по обявена формула, не налучкана.

КАКВО ЗАВАРИХ (преброено, не предположено)
------------------------------------------
  • 13 от 20 секции нямат НИКАКВА дата на наблюдение.
  • displaced е от 2022, nuclear от 2024 — влизат в „днешните" числа наравно с CO2,
    измерен преди 13 дни.
  • energy е ПРАЗЕН обект и въпреки това се брои сред „20 източника".
  • _wb_world() иска последните 5 години (mrv=5), взима първата непразна стойност
    и ИЗХВЪРЛЯ годината. Продължителност на живота, грамотност, достъп до вода —
    всичките влизаха в композита без никой да знае от коя година са.

ЧЕТИРИТЕ РОДА ЧИСЛА
-------------------
Не всяко число е „измерване", и това е половината от истината за произхода:

  MEASURED  — наблюдение с дата, по-ново от прага (CO2 от миналата седмица)
  ANNUAL    — годишна агрегация; най-доброто, което съществува, но е на година
  CONSTANT  — вписана стойност, която не се извлича (SIPRI 2024)
  UNKNOWN   — числото е тук, датата му я няма. НЕ значи прясно.

ЧЕСТНО ЗА ОБХВАТА: този модул НЕ съди дали числото е вярно. Той съди откъде е,
кога е наблюдавано и колко закъснява. Източник, който лъже последователно, ще носи
отличен произход. Това е работа на мета-валидатора и не бива да се бърка — точно
както нотариусът не съди качеството, а режима.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SNAP = BASE / "snapshots" / "master" / "global_indicators_latest.json"
OUT = BASE / "memory" / "provenance_latest.json"

MEASURED, ANNUAL, CONSTANT, UNKNOWN = "measured", "annual", "constant", "unknown"

# Откъде идва всяка секция — един хост, изписан явно. Това е и отговорът на
# въпроса на Емил: секциите са 20, хостовете са по-малко.
HOSTS = {
    "co2": "gml.noaa.gov", "temperature": "data.giss.nasa.gov",
    "sea_level": "sealevel.colorado.edu", "biodiversity": "api.gbif.org",
    "food": "api.worldbank.org", "waste": "api.worldbank.org",
    "world_bank": "api.worldbank.org", "economy": "api.worldbank.org",
    "cities": "api.worldbank.org", "governance": "api.worldbank.org",
    "tech_infra": "api.worldbank.org", "displaced": "api.unhcr.org",
    "conflicts": "ucdp.uu.se", "nuclear": "(вписана стойност — SIPRI)",
    "energy": "api.eia.gov", "media": "api.gdeltproject.org",
    "ai_activity": "export.arxiv.org + api.github.com",
    "exoplanets": "exoplanetarchive.ipac.caltech.edu",
    "satellites": "celestrak.org", "neo": "ssd-api.jpl.nasa.gov",
}

# Кое поле в коя секция носи ДАТАТА НА НАБЛЮДЕНИЕТО (не на изтеглянето).
# Имената са различни във всяка секция, защото са писани по различно време —
# затова се събират тук веднъж, вместо всеки консуматор да ги отгатва.
OBSERVED_FIELD = {
    "co2": "co2_date", "temperature": "temp_anomaly_year",
    "sea_level": "sea_level_year_fraction", "displaced": "unhcr_year",
    "conflicts": "ucdp_year", "nuclear": "source_year",
}

# Секции, чиито числа са вписани, а не извличани.
DECLARED_CONSTANT = {"nuclear"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_observed(v) -> datetime | None:
    """Приема '2026-08-02', 2025, 2026.101 — връща дата или None. Не гадае."""
    if v is None:
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
        except Exception:
            return None
    m = re.match(r"^(\d{4})\.(\d+)$", s)          # година с дроб (2026.101)
    if m:
        try:
            y = int(m[1])
            frac = float("0." + m[2])
            return datetime(y, 1, 1, tzinfo=timezone.utc) + \
                (datetime(y + 1, 1, 1, tzinfo=timezone.utc) -
                 datetime(y, 1, 1, tzinfo=timezone.utc)) * frac
        except Exception:
            return None
    if re.match(r"^\d{4}$", s):                   # само година -> КРАЯ на годината,
        try:                                      # защото годишната стойност покрива
            return datetime(int(s), 12, 31, tzinfo=timezone.utc)   # цялата година
        except Exception:
            return None
    return None


def _confidence(kind: str, lag_days: float | None) -> float:
    """Обявена формула, не налучкване. Смисълът: доверието пада с давността, а
    видът на числото слага таван.

    Таваните: measured 1.00, annual 0.80, constant 0.50, unknown 0.30.
    Спадът: 1.0 до 2 дни, после линейно надолу до 0.2 при 3 години.
    Числото се публикува ЗАЕДНО с формулата, за да може да се оспори."""
    cap = {MEASURED: 1.0, ANNUAL: 0.8, CONSTANT: 0.5, UNKNOWN: 0.3}.get(kind, 0.3)
    if lag_days is None:
        return round(min(cap, 0.3), 2)
    if lag_days <= 2:
        decay = 1.0
    else:
        decay = max(0.2, 1.0 - (lag_days - 2) / (365 * 3 - 2) * 0.8)
    return round(cap * decay, 2)


def _section(name: str, body: dict, fetched: datetime) -> dict:
    n_values = sum(1 for k, v in body.items()
                   if not k.startswith("_") and isinstance(v, (int, float)))
    rec = {"host": HOSTS.get(name, "?"), "values": n_values,
           "fetched_at": fetched.isoformat()}

    if n_values == 0:
        rec.update({"kind": UNKNOWN, "observed_at": None, "lag_days": None,
                    "confidence": 0.0,
                    "note": "секцията е ПРАЗНА — брои се като източник, а няма число"})
        return rec

    field = OBSERVED_FIELD.get(name)
    obs = _parse_observed(body.get(field)) if field else None

    # World Bank: годината вече се пази ПО ПОКАЗАТЕЛ (виж _wb_world). Взима се
    # най-СТАРАТА, защото секцията е толкова прясна, колкото най-старото ѝ число.
    years = body.get("_observed_years") or {}
    if years:
        parsed = [d for d in (_parse_observed(y) for y in years.values()) if d]
        if parsed:
            obs = min(parsed)
            rec["oldest_metric"] = min(
                ((k, v) for k, v in years.items() if v),
                key=lambda kv: str(kv[1]), default=(None, None))[0]

    if name in DECLARED_CONSTANT:
        kind = CONSTANT
    elif obs is None:
        kind = UNKNOWN
    elif field and re.match(r"^\d{4}$", str(body.get(field, ""))) or years:
        kind = ANNUAL
    else:
        kind = MEASURED

    lag = round((fetched - obs).total_seconds() / 86400.0, 1) if obs else None
    rec.update({"kind": kind, "observed_at": obs.isoformat()[:10] if obs else None,
                "lag_days": lag, "confidence": _confidence(kind, lag)})
    if obs is None:
        rec["note"] = ("числото е тук, датата му я няма — това НЕ значи прясно, "
                       "а че произходът е неизвестен")
    return rec


def build(snapshot: dict | None = None) -> dict:
    if snapshot is None:
        try:
            snapshot = json.loads(SNAP.read_text(encoding="utf-8"))
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    try:
        fetched = datetime.fromisoformat(str(snapshot.get("timestamp")))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
    except Exception:
        fetched = _now()

    sections = {}
    for name, body in snapshot.items():
        if name.startswith("_") or name in ("sources", "timestamp") or not isinstance(body, dict):
            continue
        sections[name] = _section(name, body, fetched)

    hosts = {}
    for name, r in sections.items():
        hosts.setdefault(r["host"], []).append(name)
    by_kind = {}
    for r in sections.values():
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1

    concentration = max(((h, len(v)) for h, v in hosts.items()),
                        key=lambda x: x[1], default=("?", 0))
    return {
        "ts": _now().isoformat(),
        "sections": sections,
        "summary": {
            "sections_total": len(sections),
            "independent_hosts": len(hosts),
            "by_kind": by_kind,
            "empty_sections": [n for n, r in sections.items() if r["values"] == 0],
            "unknown_provenance": [n for n, r in sections.items() if r["kind"] == UNKNOWN],
            "largest_host": {"host": concentration[0], "sections": concentration[1],
                             "share": round(concentration[1] / max(1, len(sections)), 2)},
            "mean_confidence": round(
                sum(r["confidence"] for r in sections.values()) / max(1, len(sections)), 2),
        },
        "rule": ("доверието = таван по род (measured 1.0 / annual 0.8 / constant 0.5 / "
                 "unknown 0.3), умножен по спад с давността (пълно до 2 дни, до 0.2 при "
                 "3 години). Формулата се публикува, за да може да се оспори."),
    }


def run() -> dict:
    rep = build()
    try:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    s = rep.get("summary", {})
    if s:
        print(f"[PROVENANCE] {s['sections_total']} секции | {s['independent_hosts']} "
              f"независими хоста | най-голям: {s['largest_host']['host']} "
              f"({s['largest_host']['share']:.0%}) | средно доверие {s['mean_confidence']}")
        if s["unknown_provenance"]:
            print(f"[PROVENANCE] БЕЗ ДАТА НА НАБЛЮДЕНИЕ: {', '.join(s['unknown_provenance'])}")
        if s["empty_sections"]:
            print(f"[PROVENANCE] ПРАЗНИ, но броени за източник: {', '.join(s['empty_sections'])}")
    return rep


if __name__ == "__main__":
    r = run()
    print()
    for n, s in sorted(r.get("sections", {}).items(),
                       key=lambda kv: kv[1]["confidence"]):
        print(f"  {s['confidence']:.2f}  {n:14s} {s['kind']:9s} "
              f"lag={s['lag_days']} host={s['host']}")
