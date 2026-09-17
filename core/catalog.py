#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/catalog.py — КАТАЛОЖНАТА ЗАЯВКА ВМЕСТО URL ПО СПОМЕН (15 август 2026)

Емил: „с кои живи данни се очаква системата да живее, тя ли ще си ги търси и как
точно?" Оказа се, че по това не сме се разбирали. Консенсусът с Kimi:

  „LLM НЕ БИВА ДА РАЖДА URL-и, а КАТАЛОЖНИ ЗАЯВКИ — оста дефинира нуждата, LLM я
   превежда в SDG/Eurostat/OWID заявка, регистърът връща машинни метаданни.
   URL ПО СПОМЕН Е ЛОВ НА ПРИЗРАЦИ."

Какво прави днес core/data_scout.py: пита LLM за 3 безплатни URL-а, дърпа ги и
проверява дали връщат числа. Резултатът от този контур, преброен днес: 20 секции,
14 хоста, 7 от които през World Bank, средно доверие 0.36, две празни секции,
броени за източници. Това е добивът на „URL по спомен".

Разликата тук е в РОДА на въпроса. Не „кой URL има това число", а „кой регистър
публикува показател с това значение" — и регистърът отговаря с МЕТАДАННИ: кой е
издателят, коя е последната година, каква е периодичността, по чия дефиниция.
Тоест източникът пристига вече със своя произход, вместо да го гадаем след това.

  upstream    — кой е ПЪРВИЧНИЯТ (Kimi: „агрегатор без upstream е статистически
                косплей")
  definition  — по чий метод (Kimi: „Eurostat е смислен САМО ако записваш
                дефиниционната разлика")
  revision    — кога е ревизирано (Kimi: „печели по-скорошната РЕВИЗИЯ, не
                институцията")

СЪСТОЯНИЕ (проверено на живо на машината, 15 авг 2026)
------------------------------------------------------
Средата, в която този код е писан, няма изход към регистрите (ProxyError и за
четирите), затова схемите бяха първо предположение. Режимът `--probe` беше пуснат
на машината и трите работещи схеми са ПРЕПИСАНИ ОТ ИСТИНСКИЯ ОТГОВОР:

  worldbank  HTTP 200 — sourceOrganization назовава действителния производител на
                        всеки показател. upstream вече не е моя догадка.
  un_sdg     HTTP 200 — полето `release` е обявената РЕВИЗИЯ (напр. 2026.Q2.G.01).
  eurostat   HTTP 200 — TSV с „last update of data" + „data start/end", тоест дата
                        на ревизия и период на данните.
  owid       HTTP 404 — endpoint-ът, който предположих, не съществува. ИЗКЛЮЧЕН.
                        Не пиша втора догадка върху първата.

`search()` продължава да връща празно за регистър, който probe не е потвърдил.

  venv\\Scripts\\python.exe -m core.catalog --probe
  venv\\Scripts\\python.exe -m core.catalog "life expectancy"
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
PROBE_OUT = BASE / "memory" / "catalog_probe.json"
CACHE = BASE / "memory" / "catalog_cache.json"

TIMEOUT = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(url: str, params: dict | None = None):
    import requests
    r = requests.get(url, params=params, timeout=TIMEOUT,
                     headers={"User-Agent": "CORTEX++/catalog"})
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    return r.json() if "json" in ct else r.text


# ── РЕГИСТРИТЕ ──────────────────────────────────────────────────────────────
# Всеки адаптер връща списък от кандидати с ЕДНАКВИ полета, за да може оста да
# избира по смисъл, а не по формат на конкретния регистър.

def _wb_search(need: str, limit: int = 8) -> list:
    """World Bank WDI.

    СХЕМА, ПРОВЕРЕНА НА ЖИВО (машината на Емил, 15 авг 2026, HTTP 200):
      [{page,pages,per_page,total}, [{id,name,unit,source:{id,value},
                                      sourceNote,sourceOrganization}, ...]]
    Полето `sourceOrganization` е находка: то назовава ДЕЙСТВИТЕЛНИЯ производител
    на числото за конкретния показател — напр. „LAC Equity Lab tabulations of
    SEDLAC (CEDLAS...)". Тоест upstream не е моя догадка „НСИ", а е обявен от
    самия регистър, показател по показател. Точно това Kimi искаше с
    „агрегатор без upstream е статистически косплей".
    """
    words = [w for w in need.lower().split() if len(w) > 2]
    out, page = [], 1
    while page <= 30 and len(out) < limit:
        data = _get("https://api.worldbank.org/v2/indicator",
                    {"format": "json", "per_page": 1000, "page": page})
        if not isinstance(data, list) or len(data) < 2:
            break
        for it in (data[1] or []):
            name = str(it.get("name") or "")
            if not all(w in name.lower() for w in words):
                continue
            org = str(it.get("sourceOrganization") or "").strip()
            out.append({
                "registry": "worldbank",
                "id": it.get("id"),
                "name": name,
                "unit": it.get("unit") or "",
                "url": f"https://api.worldbank.org/v2/country/WLD/indicator/"
                       f"{it.get('id')}?format=json&mrv=1",
                # ОБЯВЕН от регистъра, не предположен от мен:
                "upstream": org[:200] or "не е обявен от WB — да се третира като неизвестен",
                "definition": (it.get("source") or {}).get("value") or "WDI",
                "publisher": "World Bank",
                "revision": None,      # WB не дава дата на ревизия в този отговор
                "note": (it.get("sourceNote") or "")[:300],
            })
            if len(out) >= limit:
                break
        meta = data[0] if isinstance(data[0], dict) else {}
        if page >= int(meta.get("pages") or 1):
            break
        page += 1
    return out


def _sdg_search(need: str, limit: int = 8) -> list:
    """ООН SDG API.

    СХЕМА, ПРОВЕРЕНА НА ЖИВО (HTTP 200, 181 KB):
      [{goal:[...], target:[...], indicator:[...], release:"2026.Q2.G.01",
        code:"DC_ODA_BDVDL", description:"...", uri:"/v1/sdg/Series/DC_ODA_BDVDL"}]
    Полето `release` е ДАТАТА НА РЕВИЗИЯТА, която Kimi поиска: „печели по-скорошната
    РЕВИЗИЯ, не институцията... записвай дата на ревизия, не само стойност."
    Тук тя идва наготово и не се налага да се гади.
    """
    data = _get("https://unstats.un.org/sdgapi/v1/sdg/Series/List")
    if not isinstance(data, list):
        return []
    words = [w for w in need.lower().split() if len(w) > 2]
    out = []
    for it in data:
        desc = str(it.get("description") or "")
        if not all(w in desc.lower() for w in words):
            continue
        code = it.get("code")
        out.append({
            "registry": "un_sdg",
            "id": code,
            "name": desc[:250],
            "unit": "",
            "url": f"https://unstats.un.org/sdgapi/v1/sdg/Series/Data"
                   f"?seriesCode={code}&areaCode=1",
            "upstream": "национални статистически институти (докладвани към ООН)",
            "definition": f"SDG рамка на ООН — индикатор {', '.join(it.get('indicator') or [])}",
            "publisher": "UNSD",
            "revision": it.get("release"),        # обявена ревизия
            "note": f"цел {', '.join(it.get('goal') or [])}",
        })
        if len(out) >= limit:
            break
    return out


def _eurostat_search(need: str, limit: int = 8) -> list:
    """Евростат.

    СХЕМА, ПРОВЕРЕНА НА ЖИВО (HTTP 200, 1.97 MB, TSV с кавички). Заглавен ред:
      "title" "code" "type" "last update of data" "last table structure change"
      "data start" "data end" "values"
    Тоест регистърът дава ДАТА НА ПОСЛЕДНО ОБНОВЯВАНЕ и ПЕРИОД НА ДАННИТЕ —
    двете неща, които днес липсват на всичките 20 секции.
    Kimi: „Eurostat отделно е смислен САМО ако записваш дефиниционната разлика."
    Затова тук definition и coverage казват изрично, че методът е ЕС-хармонизиран
    и покритието е ЕС — за да не мине за глобален показател.
    """
    data = _get("https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/txt",
                {"lang": "en"})
    if not isinstance(data, str):
        return []
    words = [w for w in need.lower().split() if len(w) > 2]
    out = []
    for line in data.splitlines():
        cells = [c.strip().strip('"').strip() for c in line.split("\t")]
        if len(cells) < 7 or cells[2] != "dataset":
            continue
        title = cells[0]
        if not all(w in title.lower() for w in words):
            continue
        out.append({
            "registry": "eurostat",
            "id": cells[1],
            "name": title[:200],
            "unit": "",
            "url": f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/"
                   f"data/{cells[1]}?format=JSON&lastTimePeriod=1",
            "upstream": "национални статистически институти (ЕС-хармонизирани)",
            "definition": "ЕС-хармонизиран метод — НЕ е сравним с национален",
            "publisher": "Eurostat",
            "revision": cells[3] or None,          # last update of data
            "coverage": f"само ЕС; данни {cells[5]}–{cells[6]}",
            "note": "",
        })
        if len(out) >= limit:
            break
    return out


def _owid_search(need: str, limit: int = 8) -> list:
    """Our World in Data — ИЗКЛЮЧЕН, докато не се намери работещ вход.

    ПРОВЕРЕНО НА ЖИВО (15 авг 2026): /v1/indicators/search връща HTTP 404 и HTML
    страница „Not Found". Тоест endpoint-ът, който предположих по документация,
    не съществува. Няма да пиша втора догадка върху първата — регистърът стои
    изключен и това се вижда, вместо да връща празно и да прилича на „няма данни".
    """
    raise RuntimeError("OWID: няма проверен каталожен endpoint (404 при probe)")


# owid е ИЗКЛЮЧЕН след probe (404). Стои извън списъка, вместо да пада всеки цикъл.
REGISTRIES = {
    "worldbank": ("https://api.worldbank.org/v2/indicator?format=json&per_page=1", _wb_search),
    "un_sdg": ("https://unstats.un.org/sdgapi/v1/sdg/Series/List", _sdg_search),
    "eurostat": ("https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/txt?lang=en",
                 _eurostat_search),
}


# ── ПРОВЕРКАТА, която се пуска НА МАШИНАТА ──────────────────────────────────

def probe() -> dict:
    """Кой регистър отговаря и как изглежда отговорът му.

    Съществува, защото средата, в която този код е писан, няма изход към нито
    един от четирите (ProxyError). Докато това не се пусне, схемите тук са
    предположение по документация — и се държат като такова."""
    rep = {"ts": _now(), "registries": {}}
    for name, (url, _fn) in REGISTRIES.items():
        rec = {"url": url}
        try:
            import requests
            r = requests.get(url, timeout=TIMEOUT,
                             headers={"User-Agent": "CORTEX++/catalog"})
            rec["http"] = r.status_code
            rec["bytes"] = len(r.content)
            rec["content_type"] = r.headers.get("content-type", "")[:60]
            rec["sample"] = r.text[:400]
            rec["ok"] = r.status_code == 200
        except Exception as e:
            rec["ok"] = False
            rec["error"] = f"{type(e).__name__}: {e}"[:200]
        rep["registries"][name] = rec
        print(f"  [CATALOG] {name:11} "
              + ("OK   " if rec.get("ok") else "ПАДНА") +
              f"  {rec.get('http', rec.get('error', ''))}")
    try:
        PROBE_OUT.parent.mkdir(parents=True, exist_ok=True)
        PROBE_OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"  [CATALOG] -> memory/catalog_probe.json")
    except Exception:
        pass
    return rep


def _probed_ok(name: str) -> bool:
    """Регистър, който НЕ е проверен на живо, не се ползва. Догадката не е източник."""
    try:
        rep = json.loads(PROBE_OUT.read_text(encoding="utf-8"))
        return bool((rep.get("registries") or {}).get(name, {}).get("ok"))
    except Exception:
        return False


def search(need: str, registries: list | None = None) -> list:
    """Кандидати за една нужда, от регистрите — с метаданни, не с догадки.

    Връща ПРАЗНО за регистър, който не е потвърден от probe(). Това е нарочно:
    непроверена схема, която мълчаливо не съвпада, ще върне празен списък и ще
    изглежда като „няма такъв показател" — а това е точно родът лъжа, който този
    проект гони."""
    out, skipped = [], []
    for name in (registries or list(REGISTRIES)):
        if not _probed_ok(name):
            skipped.append(name)
            continue
        try:
            out.extend(REGISTRIES[name][1](need))
        except Exception as e:
            skipped.append(f"{name}({type(e).__name__})")
    if skipped:
        print(f"  [CATALOG] НЕПРОВЕРЕНИ/ПАДНАЛИ регистри пропуснати: "
              f"{', '.join(skipped)} — пусни `-m core.catalog --probe`")
    return out



# ── НОРМАЛИЗАЦИЯ НА ПЪРВИЧНИЯ ИЗТОЧНИК ─────────────────────────────────────
# НАМЕРЕНО ПРИ ПЪРВОТО ЖИВО ПУСКАНЕ (машината на Емил, 15 авг 2026).
# Заявка „life expectancy" върна 16 кандидата и `distinct_upstreams: 5`. Но пет
# беше ЛЪЖА, и то в оптимистичната посока: три от петте бяха един и същ източник,
# изписан по три начина —
#   „World Population Prospects, United Nations (UN), publisher: UN Population Division;…"
#   „World Population Prospects, United Nations (UN), uri: UN Population Division;…"
#   „2022 World Population Prospects, United Nations Population Division: Retrieved…"
# Сравнявах СУРОВИ НИЗОВЕ. Разлика в препинателен знак се броеше за независим
# източник — точно родът фалшива независимост, който този слой съществува да лови,
# само че този път я произвеждах аз.
#
# Затова: суровият текст се пази (той е доказателството), а сравнението минава по
# КАНОНИЧЕН КЛЮЧ. Списъкът е явен и къс; каквото не се разпознае, се обявява за
# неразпознато и НЕ се брои за независимо.
_UPSTREAM_PATTERNS = (
    ("UN_WPP",      ("world population prospects", "un population division")),
    ("UNESCO_UIS",  ("unesco", "uis api", "institute for statistics")),
    ("NSO",         ("national statistical office", "national statistical institut",
                     "статистически институти")),
    ("EUROSTAT",    ("eurostat", "ес-хармонизиран")),
    ("WHO",         ("world health organization", "who global health")),
    ("ILO",         ("international labour", "ilostat")),
    ("IMF",         ("international monetary fund", "imf ")),
    ("OECD",        ("oecd",)),
    ("FAO",         ("food and agriculture organization", "faostat")),
    ("IEA",         ("international energy agency",)),
    ("UNHCR",       ("unhcr",)),
    ("WB_OWN",      ("world bank staff", "wb staff estimates", "world bank national accounts")),
    # НАМЕРЕНО ПРИ ТЕСТА, 15 авг 2026: търсех само „uppsala", значи низът „UCDP"
    # излизаше НЕРАЗПОЗНАТ — тоест дори не се броеше за свидетел. Kimi предвиди
    # точно това („org='Wikipedia/UCDP-ACLED' и org='UCDP' няма да се слеят"), но
    # причината се оказа по-дълбока от неговата: не че няма да се слеят, а че
    # НИТО ЕДИН от двата не се разпознава.
    ("UCDP",        ("uppsala", "ucdp")),
    ("NOAA",        ("noaa", "mauna loa")),
    ("NASA",        ("nasa", "gistemp", "jpl")),
)


def normalize_upstream(raw: str) -> str:
    """Каноничен ключ на първичния източник. Незнанието не се брои за независимост."""
    low = (raw or "").lower()
    hits = [key for key, pats in _UPSTREAM_PATTERNS if any(p in low for p in pats)]
    if not hits:
        return "НЕРАЗПОЗНАТ"
    # Няколко имена в едно поле значи ВЕРИГА (напр. WPP + NSO). Каноничният ключ е
    # цялата верига, подредена — защото два показателя с една и съща верига НЕ са
    # независими, дори да са в различни регистри.
    return "+".join(sorted(set(hits)))


def independence(candidates: list) -> dict:
    """Колко РАЗЛИЧНИ първични източника стоят зад тези кандидати.

    Kimi: „две числа потвърждават едно друго САМО ако upstream-ите им се
    различават." Тук това е измеримо ПРЕДИ да сме взели каквото и да е."""
    ups: dict = {}
    for c in candidates:
        key = normalize_upstream(c.get("upstream", ""))
        c["upstream_key"] = key                    # каноничното върви с кандидата
        ups.setdefault(key, []).append(f"{c.get('registry')}:{c.get('id')}")
    real = {k: v for k, v in ups.items() if k != "НЕРАЗПОЗНАТ"}

    # ВТОРА ПОПРАВКА, от същото живо пускане: „UN_WPP" и „NSO+UN_WPP" още се брояха
    # за два източника, макар вторият само да ИЗБРОЯВА по-подробно същата верига.
    # Веригата, която е ПОДМНОЖЕСТВО на друга, не е независима от нея — тя е същата
    # верига, описана по-скъпернически. Затова подмножествата се сливат в надмножеството.
    _sets = {k: set(k.split("+")) for k in real}
    merged: dict = {}
    for k, s in _sets.items():
        parent = next((o for o, os_ in _sets.items()
                       if o != k and s < os_), None)
        merged.setdefault(parent or k, []).extend(real[k])
    real = merged
    warn = None
    if len(real) <= 1:
        warn = ("всички разпознати кандидати идват от ЕДИН първичен източник — "
                "те НЕ се потвърждават взаимно")
    if "НЕРАЗПОЗНАТ" in ups:
        warn = ((warn + "; ") if warn else "") + (
            f"{len(ups['НЕРАЗПОЗНАТ'])} кандидата с неразпознат първичен източник — "
            f"не се броят за независими")
    return {"candidates": len(candidates),
            "distinct_upstreams": len(real),
            "by_upstream": {k: v for k, v in sorted(ups.items())},
            "warning": warn}


if __name__ == "__main__":
    import sys
    if "--probe" in sys.argv:
        probe()
    else:
        need = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "life expectancy"
        res = search(need)
        print(json.dumps({"need": need, "found": len(res),
                          "independence": independence(res),
                          "candidates": res[:5]}, ensure_ascii=False, indent=2))
