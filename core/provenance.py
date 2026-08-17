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

# ── КОЙ СТОИ ЗАД АГРЕГАТОРА (Kimi, 15 авг 2026) ────────────────────────────
# Емил попита за Евростат, ООН, Световната банка и националните статистически
# институти. Като ги подредих, излезе нещо неудобно: Световната банка, Евростат и
# ООН НЕ СА независими източници — и тримата ПРЕПУБЛИКУВАТ едни и същи НСИ.
# Kimi, дословно:
#   „217 NSI-та са самоубийство на лаптоп, но АГРЕГАТОР БЕЗ UPSTREAM Е
#    СТАТИСТИЧЕСКИ КОСПЛЕЙ. Полето upstream е минималната честност."
#   „Разминаването е улика срещу агрегатора САМО АКО Е СИСТЕМНО. Печели
#    по-скорошната РЕВИЗИЯ, не институцията... записвай дата на ревизия, не само
#    стойност."
#   „Eurostat отделно е смислен САМО ако записваш дефиниционната разлика
#    (ЕС-хармонизиран vs национален метод). Иначе е фалшива независимост."
#
# Следствието за мярката, която сам предложих сутринта („14 независими хоста"):
# тя брои ЛИЦА, не ИЗТОЧНИЦИ. Седем секции през World Bank + утрешен Евростат щяха
# да се броят за независими, докато всички седят върху един и същ първичен слой.
UPSTREAM = {
    "api.worldbank.org": "национални статистически институти (препубликувани от WB)",
    "ec.europa.eu/eurostat": "национални статистически институти (ЕС-хармонизирани)",
    "unstats.un.org": "национални статистически институти (докладвани към ООН)",
    "api.unhcr.org": "правителства и полеви операции на UNHCR",
    "gml.noaa.gov": "собствено измерване (Mauna Loa)",
    "data.giss.nasa.gov": "собствен анализ на NASA върху станции и сателити",
    "sealevel.colorado.edu": "сателитна алтиметрия (собствено измерване)",
    "api.gbif.org": "музеи, институти и граждански наблюдения",
    "ucdp.uu.se": "собствено кодиране на Uppsala",
    "celestrak.org": "каталог на US Space Force (препубликуван)",
    "api.eia.gov": "собствено измерване на EIA (САЩ)",
    "api.gdeltproject.org": "новинарски издания (собствена агрегация)",
    "exoplanetarchive.ipac.caltech.edu": "рецензирани публикации (препубликувани)",
    "ssd-api.jpl.nasa.gov": "собствени наблюдения на JPL",
    "export.arxiv.org + api.github.com": "самите платформи (първичен брой)",
    "(вписана стойност — SIPRI)": "SIPRI Yearbook (вписан на ръка, не извличан)",
}

# По чий метод е числото. Различната дефиниция е причина едно число да НЕ е
# сравнимо с друго, дори когато мери същото нещо.
DEFINITION = {
    "api.worldbank.org": "WDI, глобални агрегати по методика на Световната банка",
    "ec.europa.eu/eurostat": "ЕС-хармонизиран метод (различен от националния)",
    "unstats.un.org": "SDG индикаторна рамка на ООН",
}

# Откъде идва всяка секция — един хост, изписан явно. Това е и отговорът на
# въпроса на Емил: секциите са 20, хостовете са по-малко, а ПЪРВИЧНИТЕ са още
# по-малко (виж UPSTREAM).
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


def _witness_count(sections: dict) -> dict:
    """Колко НЕЗАВИСИМИ СВИДЕТЕЛСТВА стоят зад картината — не наказание, а броене.

    ОТМЕНЕНО РЕШЕНИЕ (Kimi, 15 авг 2026). Тук стоеше „наказание за концентрация":
    доверието на всяка секция се делеше на sqrt(n) според това колко секции висят
    на един upstream. Kimi го отмени:

      „ОТМЕНИ — sqrt е ПРОИЗВОЛ. Групирай по upstream: 7 секции от един източник =
       1 НАБЛЮДЕНИЕ, не 7 с наказание."
      „Нито една. Групата НЕ РАЖДА СТОЙНОСТ — ражда само брой независими
       свидетелства = 1. Всяко остойностяване си пази собствената стойност."
      „Теглата НЕ ПАДАТ. Групирането важи само за distinct_upstream_count, не за
       композитното тегло."

    Бях смесил две неща: КОЛКО СТРУВА ЧИСЛОТО и КОЛКО СВИДЕТЕЛИ ИМА. Първото си е
    работа на самото число; второто е свойство на картината. Сега те са отделни:
    стойностите не се пипат, а свидетелите се броят.
    """
    groups: dict = {}
    for name, r in sections.items():
        groups.setdefault(r["upstream_key"], []).append(name)
    return groups


# ── ОТМЕНЕНАТА ФОРМУЛА (Kimi, 15 авг 2026) ─────────────────────────────────
# Тук стоеше _confidence(): таван по род (измерено 1.0 / годишно 0.8 / вписано 0.5 /
# неизвестно 0.3), умножен по спад с давността до 0.2 при три години. Числата бяха
# МОИ. Kimi ги отмени с довод, който сам ми беше дал по-рано за доверие-интервала:
#
#   „ОТМЕНИ — числата са НАЛУЧКАНИ. Таваните са ЕВРИСТИКА, МАСКИРАНА КАТО ФОРМУЛА;
#    няма principled derivation."
#   „Вариант А сега, със seed за Б. Публикувай СУРОВИТЕ ФАКТИ (род, давност,
#    upstream-и). НЕ ИЗМИСЛЯЙ ЧИСЛО. Но започни да трупаш историята в криптата —
#    след месеци Вариант Б ще има ДАННИ, НЕ МНЕНИЕ."
#
# Затова тук няма число. Секцията носи какво Е: род, давност в дни, кой е първичният
# източник, колко независими свидетели има. Който съди — съди по тях.
#
# ВАРИАНТ Б (доверие, ИЗМЕРЕНО от миналата точност на източника) не е изоставен —
# той е отложен, защото днес няма история. Семето му е криптата
# (attestation/quarantine_attestations.jsonl): всяко отхвърлено число се записва от
# днес, и след месеци доверието ще може да се смята от „колко пъти този източник е
# бил отхвърлян", вместо от моята преценка.


def _section(name: str, body: dict, fetched: datetime) -> dict:
    n_values = sum(1 for k, v in body.items()
                   if not k.startswith("_") and isinstance(v, (int, float)))
    host = HOSTS.get(name, "?")
    rec = {"host": host, "values": n_values,
           "fetched_at": fetched.isoformat(),
           "upstream": UPSTREAM.get(host, "неизвестен първичен източник"),
           "definition": DEFINITION.get(host),
           # Ревизията е ДРУГО нещо от наблюдението: число за 2023 може да бъде
           # преработено през 2026. Днес го нямаме от нито един fetcher — казва се
           # тук, а не се подразбира (Kimi: „записвай дата на ревизия").
           "revision_date": body.get("_revision_date")}

    if n_values == 0:
        rec.update({"kind": UNKNOWN, "observed_at": None, "lag_days": None,
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
                "lag_days": lag})
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

    # каноничният ключ идва от каталога — един и същ навсякъде
    try:
        from core.catalog import normalize_upstream
    except Exception:
        def normalize_upstream(x): return x or "НЕРАЗПОЗНАТ"
    hosts, ups = {}, {}
    for name, r in sections.items():
        r["upstream_key"] = normalize_upstream(r.get("upstream", ""))
        hosts.setdefault(r["host"], []).append(name)
        ups.setdefault(r["upstream"], []).append(name)
    witnesses = _witness_count(sections)
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
            # ЧЕСТНАТА мярка: колко РАЗЛИЧНИ ПЪРВИЧНИ източника стоят зад всичко.
            # Хостовете са лица; upstream-ите са източници.
            "independent_upstreams": len(ups),
            "upstream_map": {k: sorted(v) for k, v in sorted(ups.items())},
            "unknown_upstream": [n for n, r in sections.items()
                                 if r["upstream"].startswith("неизвестен")],
            "no_revision_date": [n for n, r in sections.items()
                                 if not r.get("revision_date")],
            "by_kind": by_kind,
            "empty_sections": [n for n, r in sections.items() if r["values"] == 0],
            "unknown_provenance": [n for n, r in sections.items() if r["kind"] == UNKNOWN],
            "largest_host": {"host": concentration[0], "sections": concentration[1],
                             "share": round(concentration[1] / max(1, len(sections)), 2)},
            # Вместо „средно доверие" — какво ИМА, преброено:
            "by_kind_counts": by_kind,
            "median_lag_days": (sorted(
                [r["lag_days"] for r in sections.values() if r.get("lag_days") is not None]
            ) or [None])[len([r for r in sections.values()
                              if r.get("lag_days") is not None]) // 2],
            "witnesses": {k: sorted(v) for k, v in sorted(witnesses.items())},
            "independent_witnesses": len([k for k in witnesses if k != "НЕРАЗПОЗНАТ"]),
            "largest_upstream": max(
                ((u, len(v)) for u, v in ups.items()), key=lambda x: x[1],
                default=("?", 0))[0],
        },
        "rule": ("ТУК НЯМА ЧИСЛО ЗА ДОВЕРИЕ. Формулата, която стоеше на това място, беше "
                 "евристика, маскирана като формула (Kimi, 15 авг 2026). Публикуват се "
                 "суровите факти: род на числото, давност в дни, кой е първичният "
                 "източник и колко НЕЗАВИСИМИ свидетели стоят зад картината. Доверие, "
                 "ИЗМЕРЕНО от миналата точност на всеки източник, ще стане възможно, "
                 "когато криптата натрупа история — не по-рано."),
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
              f"({s['largest_host']['share']:.0%}) | родове {s['by_kind_counts']} "
              f"| медианна давност {s['median_lag_days']} дни")
        if s["unknown_provenance"]:
            print(f"[PROVENANCE] БЕЗ ДАТА НА НАБЛЮДЕНИЕ: {', '.join(s['unknown_provenance'])}")
        if s["empty_sections"]:
            print(f"[PROVENANCE] ПРАЗНИ, но броени за източник: {', '.join(s['empty_sections'])}")
    return rep


if __name__ == "__main__":
    r = run()
    print()
    for n, s in sorted(r.get("sections", {}).items(),
                       key=lambda kv: (kv[1].get("lag_days") is None,
                                       kv[1].get("lag_days") or 0)):
        print(f"  {n:14s} {s['kind']:9s} lag={s['lag_days']} "
              f"upstream={s['upstream_key']} host={s['host']}")
