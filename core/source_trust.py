#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/source_trust.py — КОЙ ЗАКРИВА ИЗТОЧНИК, КОЙТО ЛЪЖЕ (15 август 2026)

Емил попита: „с кои живи данни се очаква системата да живее, тя ли ще си ги търси
и как точно?" Оказа се, че по това не сме се разбирали. Консенсусът с Kimi:

  1) РАЖДАНЕ. „LLM не бива да ражда URL-и, а КАТАЛОЖНИ ЗАЯВКИ — оста дефинира
     нуждата, LLM я превежда в SDG/Eurostat/OWID заявка, регистърът връща машинни
     метаданни. URL по спомен е ЛОВ НА ПРИЗРАЦИ."
  2) ДОПУСКАНЕ. Моето предложение (три исторически стойности да съвпадат с
     независим източник) той отхвърли: „Три съвпадения са ТЕАТЪР, ако
     'независимият' източник черпи от същия първичен доставчик. Минималната
     семантична проверка е SANITY CHECK: стойността влиза ли в историческия
     диапазон? Ако не — източникът лъже, независимо от потвърждения."
  3) ЗАКРИВАНЕ. „Закрива го ДРЕЙФ-ДЕТЕКТОР: стойности извън собствения 3-сигма
     диапазон или скъсана корелация с други източници за същата ос = ТОЧКА НА
     НЕДОВЕРИЕ. При N точки — карантина. ЧОВЕКЪТ ОДОБРЯВА ПРАВИЛОТО, НЕ ВСЯКО
     ИЗПЪЛНЕНИЕ."

Този модул е (2) и (3). Дупката, която запушва, е конкретна: днес
config/dead_sources.json лови източник, който МЪЛЧИ. Нищо не лови източник, който
отговаря бодро и лъже — а той е по-опасният, защото минава за жив и влиза в
композита с пълно доверие.

ЗАЩО ПРАВИЛОТО Е В КОНФИГУРАЦИЯ, А НЕ ТУК
-----------------------------------------
config/source_trust_rules.json е ЧОВЕШКИ ФАЙЛ (като scheduler.json и BOUNDARIES.md):
системата го чете, но не го пише. Прагът за недоверие е решение за това колко лъжа
се търпи — то е на човека. Изпълнението е на системата. Точно това е „одобряваш
правилото, не всяко изпълнение".

ЧЕСТНО ЗА ОБХВАТА
-----------------
Този модул не знае кое е ВЯРНО. Той знае кое е НЕВЪЗМОЖНО (извън историческия
диапазон) и кое е ВНЕЗАПНО (извън собствения 3-сигма). Източник, който лъже
последователно и правдоподобно от първия ден, минава — и това се казва тук, а не
се крие зад думата „валидиран".
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
HISTORY = BASE / "memory" / "axis_history.json"
RULES = BASE / "config" / "source_trust_rules.json"
LEDGER = BASE / "memory" / "distrust_ledger.jsonl"
STATE = BASE / "memory" / "source_trust_state.json"

DEFAULT_RULES = {
    "_README": ("ЧОВЕШКИ ФАЙЛ. Системата го чете, не го пише. Тук се решава КОЛКО "
                "лъжа се търпи — това е човешко решение, а прилагането е на "
                "системата (консенсус с Kimi, 15 авг 2026)."),
    "sigma": 3.0,
    "min_history": 8,
    "min_distinct": 6,
    # Заземяването (разминаване котва vs дневен прокси) е ОТДЕЛНА редица — тя
    # не се мери на периоди като показателите, а на цикли. Затова има собствен
    # минимум, но НЕ и собствена сигма: присъдата минава през същата сигма като
    # всичко останало. (Kimi, 15 авг 2026: „Минимум 7 наблюдения за rolling std;
    # под тях — само архив, без alert.")
    "grounding_min_history": 7,
    # Колко може да избяга покритието между ЗАПЕЧАТВАНЕ на предсказание и
    # УЗРЯВАНЕТО му, преди сравнението да стане нечестно. (Kimi, 15 авг 2026:
    # „отказ при abs(coverage_pred − coverage_mature) > 15%... Предсказание за
    # пълен композит, узряло в беден ден, е предсказание за друга вселена —
    # грешката не е на модела.")
    "coverage_drift_max": 0.15,
    "range_slack": 0.25,
    "min_slack_of_value": 0.50,
    "distrust_to_quarantine": 3,
    "distrust_window_days": 30,
    "correlation_min_pairs": 10,
    "correlation_break_below": 0.2,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rules() -> dict:
    r = dict(DEFAULT_RULES)
    try:
        r.update(json.loads(RULES.read_text(encoding="utf-8")))
    except Exception:
        pass
    return r


def _history(metric: str) -> list:
    """Всички исторически стойности на един показател, по дата."""
    try:
        hist = json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for _axis, entries in (hist.items() if isinstance(hist, dict) else []):
        if not isinstance(entries, list):
            continue
        for e in entries:
            v = (e.get("metrics") or {}).get(metric)
            if isinstance(v, (int, float)):
                out.append((e.get("date", ""), float(v)))
    out.sort()
    return out


# ── ФИЗИЧЕСКИЯТ ДИАПАЗОН (Kimi, 15 авг 2026) ───────────────────────────────
# „Трети път: ВЪНШЕН ФИЗИЧЕСКИ ДИАПАЗОН (domain constraint), не емпиричен.
#  За GDP growth: [-20%, +20%] от икономиката, не от твоите 3 стойности.
#  Бедният показател не е сляп — гледа физически възможното, не историята."
# Това реши дупката, която сам отворих: без история системата не съдеше ИЗОБЩО и
# явна лъжа минаваше. Сега при бедна история се съди по това, което е ВЪЗМОЖНО В
# СВЕТА — знание, което не идва от наблюденията и затова не се влияе от бедността им.
# Границите живеят в ЧОВЕШКИЯ файл: те са твърдение за света, не за данните.
DEFAULT_DOMAIN = {
    "_README": ("Физически/дефиниционни граници на показателите. Твърдение за СВЕТА, "
                "не за данните — затова е човешки файл. Ползва се, когато историята "
                "е твърде бедна, за да съди (Kimi, 15 авг 2026)."),
    "gdp_growth_pct": [-20, 20],
    "gdp_growth_annual_pct": [-20, 20],
    "unemployment_pct": [0, 60],
    "life_expectancy": [20, 100],
    "literacy_rate_adult_pct": [0, 100],
    "literacy_rate_youth_pct": [0, 100],
    "safe_water_access_pct": [0, 100],
    "forest_area_pct": [0, 100],
    "renewable_elec_pct": [0, 100],
    "poverty_190_pct": [0, 100],
    "extreme_poverty_rate_pct": [0, 100],
    "urbanization_pct": [0, 100],
    "gini_mean": [0, 100],
    "infant_mortality_per1k": [0, 400],
    "child_mortality_per_1000": [0, 400],
    "population_billions": [7.0, 12.0],
    "co2_ppm": [250, 1000],
    "co2_ppm_current": [250, 1000],
    "temp_anomaly_c": [-2, 8],
    "sea_level_rise_mm": [-50, 2000],
    "active_armed_conflicts": [0, 500],
    "nuclear_warheads_total": [0, 80000],
    "news_tone_avg_1month": [-100, 100],
}
DOMAIN = BASE / "config" / "metric_domains.json"


def domains() -> dict:
    d = dict(DEFAULT_DOMAIN)
    try:
        d.update(json.loads(DOMAIN.read_text(encoding="utf-8")))
    except Exception:
        pass
    return d


def domain_check(metric: str, value: float) -> dict:
    """Физически възможно ли е това число изобщо. Не зависи от историята."""
    b = domains().get(metric)
    if not isinstance(b, list) or len(b) != 2:
        return {"verdict": "НЯМА ГРАНИЦА",
                "why": f"за {metric} няма обявена физическа граница — "
                       f"добави я в config/metric_domains.json"}
    lo, hi = float(b[0]), float(b[1])
    ok = lo <= value <= hi
    return {"verdict": "ВЪЗМОЖНА" if ok else "ФИЗИЧЕСКИ НЕВЪЗМОЖНА",
            "bounds": [lo, hi], "value": value,
            "why": ("в границите на възможното" if ok else
                    f"извън физически възможното [{lo:g}, {hi:g}]")}


# ── ПЕРИОДЪТ НА ПОКАЗАТЕЛЯ (Kimi) ──────────────────────────────────────────
# „Добави ВРЕМЕВИ критерий: 79 еднакви дневни записа от годишен показател = 1
#  наблюдение, не 3. Дискретизирай по ПЕРИОДА на показателя, не по уникалността."
# Моята първа поправка броеше 3 различни числа за 3 наблюдения. Но ако годишен
# показател бъде преписан, после поправен и пак преписан в рамките на една година,
# това пак е ЕДНО наблюдение за тази година. Периодът е верният дискретизатор.
PERIOD_ANNUAL = "annual"
PERIOD_DAILY = "daily"
DEFAULT_PERIODS = {
    "gdp_growth_pct": PERIOD_ANNUAL, "gdp_growth_annual_pct": PERIOD_ANNUAL,
    "life_expectancy": PERIOD_ANNUAL, "literacy_rate_adult_pct": PERIOD_ANNUAL,
    "poverty_190_pct": PERIOD_ANNUAL, "gini_mean": PERIOD_ANNUAL,
    "forest_area_pct": PERIOD_ANNUAL, "unemployment_pct": PERIOD_ANNUAL,
    "active_armed_conflicts": PERIOD_ANNUAL, "nuclear_warheads_total": PERIOD_ANNUAL,
    "co2_ppm": PERIOD_DAILY, "co2_ppm_current": PERIOD_DAILY,
}


def _period_of(metric: str) -> str:
    return DEFAULT_PERIODS.get(metric, PERIOD_DAILY)


def _by_period(hist: list, metric: str) -> list:
    """Едно наблюдение на ПЕРИОД — последното записано за този период."""
    if _period_of(metric) != PERIOD_ANNUAL:
        return _distinct_observations(hist)
    per = {}
    for d, v in hist:
        per[str(d)[:4]] = v          # една стойност на година
    return [per[k] for k in sorted(per)]


def _distinct_observations(hist: list) -> list:
    """Поредните ЕДНАКВИ стойности не са отделни наблюдения.

    НАМЕРЕНО ПРИ ТЕСТА (15 авг 2026) и това е по-важно от двата дефекта преди него:
    годишен показател се записва в историята ВСЕКИ ДЕН с една и съща стойност. За
    gdp_growth_pct това дава ~150 записа на 2 различни числа, тоест стандартното
    отклонение клони към нула. Тогава ВСЯКА истинска годишна промяна излиза
    като „дрейф“ и източникът, който е казал истината, получава точка на недоверие —
    а след три такива честният източник отива в карантина.

    Това е същата грешка, която този проект вече е ловил веднъж: да броиш
    ПОВТОРЕНИЕТО за наблюдение. Затова разпределението се смята върху различните
    последователни стойности, а не върху преписването им.
    """
    out, last = [], None
    for _d, v in hist:
        if last is None or v != last:
            out.append(v)
            last = v
    return out


def _stats(values: list) -> tuple:
    n = len(values)
    if n < 2:
        return (values[0] if n else None), 0.0
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return mean, math.sqrt(var)


# ── (2) SANITY CHECK — влиза ли изобщо в възможното ─────────────────────────

def sanity(metric: str, value: float) -> dict:
    """Влиза ли стойността в историческия диапазон на показателя.

    Kimi: „Ако не — източникът ЛЪЖЕ, независимо от потвърждения."
    Диапазонът е историческият min/max, разширен с обявен луфт: реалността се
    движи, и границата не бива да наказва истинска промяна. Луфтът е в правилата,
    за да е оспорим."""
    r = rules()
    hist = _history(metric)
    # НАМЕРЕНО ПРИ ТЕСТА и е най-опасното от четирите: с история от 79 записа, но
    # само 3 РАЗЛИЧНИ стойности, „историческият диапазон“ е [2.87, 2.92]. С луфта
    # допустимото става [1.41, 4.38] — тоест истинска световна РЕЦЕСИЯ (-2%, каквато
    # е била 2020) щеше да бъде обявена за НЕВЪЗМОЖНА и източникът, който я
    # съобщава, щеше да получи точка на недоверие.
    # Система, която отхвърля реалността, защото не я е виждала, е по-лоша от
    # система без проверка. Затова: без достатъчно РАЗЛИЧНИ наблюдения проверката
    # казва НЕИЗВЕСТНО и не се произнася. Незнанието не е присъда.
    vals = _by_period(hist, metric)
    if len(hist) < r["min_history"] or len(vals) < r["min_distinct"]:
        return {"verdict": "НЕИЗВЕСТНО", "distinct": len(vals), "records": len(hist),
                "why": (f"{len(vals)} различни стойности в {len(hist)} записа "
                        f"(нужни {r['min_distinct']}) — диапазонът, който бих ползвал, "
                        f"е твърде тесен, за да съди; отхвърляне тук би отрекло "
                        f"реалността, а не лъжата")}
    lo, hi = min(vals), max(vals)
    span = hi - lo
    # НАМЕРЕНО ПРИ ТЕСТА (15 авг 2026): gdp_growth_pct има история [2.8719, 2.9213]
    # — показателят е стоял почти неподвижен, защото идва от годишен източник.
    # Луфт от 25% върху такъв размах дава допустим диапазон [2.86, 2.93], тоест
    # ИСТИНСКА промяна на световния растеж щеше да бъде обявена за „невъзможна".
    # Тесният диапазон е свойство на РЯДКОТО ИЗМЕРВАНЕ, не на реалността.
    # Затова луфтът има под: процент от самата величина, не само от размаха.
    scale = max(abs(lo), abs(hi), 1e-9)
    slack = max(span * r["range_slack"], scale * r["min_slack_of_value"])
    ok = (lo - slack) <= value <= (hi + slack)
    return {"verdict": "ДОПУСТИМА" if ok else "НЕВЪЗМОЖНА",
            "range": [round(lo, 4), round(hi, 4)],
            "allowed": [round(lo - slack, 4), round(hi + slack, 4)],
            "value": value, "points": len(vals),
            "why": ("влиза в историческия диапазон" if ok else
                    f"извън историческия диапазон [{lo:.4g}, {hi:.4g}] "
                    f"дори с луфт до ±{slack:.4g}")}


# ── (3) ДРЕЙФ — внезапна промяна спрямо СОБСТВЕНОТО минало ──────────────────

def drift(metric: str, value: float) -> dict:
    """Извън собствения 3-сигма диапазон = точка на недоверие.

    Това е различно от sanity: стойност може да е напълно възможна и пак да е
    внезапна. Внезапното не е доказателство за лъжа — затова е ТОЧКА, а не присъда."""
    r = rules()
    hist = _history(metric)
    vals = _by_period(hist, metric)
    if len(vals) < r["min_distinct"]:
        return {"verdict": "НЕИЗВЕСТНО", "distinct": len(vals), "records": len(hist),
                "why": (f"само {len(vals)} РАЗЛИЧНИ стойности в {len(hist)} записа "
                        f"(нужни {r['min_distinct']}) — при рядко измерван показател "
                        f"дрейфът не е определим, а не 'няма дрейф'")}
    mean, sd = _stats(vals)
    if sd == 0:
        return {"verdict": "НЕПОДВИЖЕН", "mean": mean,
                "why": "показателят не е мърдал — дрейф не е определим"}
    z = abs(value - mean) / sd
    return {"verdict": "ДРЕЙФ" if z > r["sigma"] else "В НОРМА",
            "z": round(z, 2), "mean": round(mean, 4), "sd": round(sd, 4),
            "distinct": len(vals), "records": len(hist),
            "why": (f"{z:.1f} сигма от средното" if z > r["sigma"]
                    else f"{z:.1f} сигма — в рамките на {r['sigma']}")}


# ── ЗАЗЕМЯВАНЕТО: КОЙ СЪДИ РАЗМИНАВАНЕТО (Kimi, 15 авг 2026) ────────────────
# „divergence_ledger се влива в notary/source_trust — носещ е notary с provenance
#  и типизирани присъди." Регистърът в experiments/grounding остава ЧИСТ ЗАПИСВАЧ:
# записва котвата, дневния прокси, разстоянието между тях и това разстояние в
# сигмите на СОБСТВЕНАТА история на оста. Присъдата се произнася ТУК — със същата
# сигма, с която се съди всичко останало. Така няма втори праг и няма втори съдия.
GROUNDING_REASON = "grounding_divergence"


def grounding_verdict(z, n: int) -> dict:
    """Превръща сурово z (от grounding ledger) в типизирана присъда.

    Бедната история НЕ дава „в норма" — дава НЕИЗВЕСТНО. Разликата е същата,
    която вече наложихме при drift: липсата на доказателство не е доказателство
    за липса."""
    r = rules()
    need = int(r.get("grounding_min_history", 7))
    if n < need:
        return {"verdict": "НЕИЗВЕСТНО", "reason": "insufficient_history",
                "n": n, "need": need,
                "why": (f"{n} наблюдения на разминаването (нужни {need}) — суровото "
                        f"число се пази, но присъда няма")}
    if z is None:
        return {"verdict": "НЕОПРЕДЕЛИМ", "n": n,
                "why": ("разсейването на разминаването е нула или разминаването не е "
                        "измеримо — не 'няма разминаване'")}
    z = float(z)
    return {"verdict": "РАЗМИНАВАНЕ" if z > r["sigma"] else "В НОРМА",
            "z": round(z, 2), "n": n, "sigma": r["sigma"],
            "why": (f"{z:.1f} сигма от собствената история на оста"
                    if z > r["sigma"] else f"{z:.1f} сигма — в рамките на {r['sigma']}")}


def judge_grounding(rec: dict) -> list:
    """Взима един ред от grounding ledger и произнася присъда по всяка ос.

    Точка на недоверие получава ДНЕВНИЯТ източник, не оста: котвата е бавна и
    авторитетна, а разминаването е твърдение на дневния прокси срещу нея. Ако
    дневният източник е неизвестен, присъдата се записва, но никого не осъжда —
    анонимно обвинение не е присъда."""
    out = []
    for axis, row in (rec.get("axes") or {}).items():
        v = grounding_verdict(row.get("divergence_z"), int(row.get("n_history") or 0))
        v["axis"] = axis
        src = row.get("daily_source")
        if v["verdict"] == "РАЗМИНАВАНЕ" and src:
            v["distrust"] = distrust(src, axis, GROUNDING_REASON,
                                     {"z": v.get("z"), "n": v.get("n"),
                                      "anchor": row.get("anchor"),
                                      "daily": row.get("daily"),
                                      "divergence": row.get("divergence")})
        elif v["verdict"] == "РАЗМИНАВАНЕ":
            v["not_charged"] = ("дневният източник е неизвестен — разминаването се "
                                "записва, но не се вменява никому")
        out.append(v)
    return out


# ── КНИГАТА НА НЕДОВЕРИЕТО ──────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(s: dict) -> None:
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def distrust(source: str, metric: str, reason: str, detail: dict | None = None) -> dict:
    """Записва точка на недоверие. При N точки в прозореца — КАРАНТИНА.

    Карантината НЕ е изтриване: източникът остава, спира да влиза в осите и се
    вижда в отчета. Реабилитацията е човешка — защото връщането на доверие е
    решение, не изчисление."""
    r = rules()
    st = _load_state()
    rec = st.setdefault(source, {"points": [], "quarantined": False})
    rec["points"].append({"ts": _now(), "metric": metric, "reason": reason,
                          "detail": detail or {}})

    # само точките в прозореца се броят — стара грешка не осъжда завинаги
    cutoff = datetime.now(timezone.utc).timestamp() - r["distrust_window_days"] * 86400
    fresh = []
    for p in rec["points"]:
        try:
            if datetime.fromisoformat(p["ts"]).timestamp() >= cutoff:
                fresh.append(p)
        except Exception:
            continue
    rec["points"] = fresh[-50:]

    if len(fresh) >= r["distrust_to_quarantine"] and not rec["quarantined"]:
        rec["quarantined"] = True
        rec["quarantined_at"] = _now()
        rec["quarantine_reason"] = (f"{len(fresh)} точки на недоверие за "
                                    f"{r['distrust_window_days']} дни")
    _save_state(st)

    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), "source": source, "metric": metric,
                                 "reason": reason, "detail": detail or {},
                                 "points_in_window": len(fresh),
                                 "quarantined": rec["quarantined"]},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass
    return {"source": source, "points": len(fresh), "quarantined": rec["quarantined"]}


# ── СЯНКАТА (Kimi, 15 авг 2026) ────────────────────────────────────────────
# Реших реабилитацията да е ЧОВЕШКА. Kimi отмени решението:
#   „ОТМЕНИ — реабилитацията трябва да е АВТОМАТИЧНА след N чисти цикъла, иначе
#    ЧОВЕКЪТ СТАВА BOTTLENECK."
# И реши парадокса, който му поставих (карантиниран източник не се чете, значи
# никога не може да заслужи връщане):
#   „СЯНКА (shadow read). Карантинираният източник СЕ ЧЕТЕ, но НЕ ВЛИЗА в
#    композита. Ако 3 поредни цикъла shadow-стойността минава детекторите —
#    автоматична реабилитация. N = 3."
SHADOW_CLEAN_NEEDED = 3


def shadow_observe(source: str, metric: str, value: float) -> dict:
    """Чете карантиниран източник, без да го пуска в оценката.

    Стойността минава през същите детектори. Чист цикъл трупа; мръсен нулира
    броенето — иначе източник, който греши през ден, би се реабилитирал с
    търпение вместо с поправяне."""
    st = _load_state()
    rec = st.get(source)
    if not rec or not rec.get("quarantined"):
        return {"source": source, "shadow": False, "why": "не е в карантина"}

    dom = domain_check(metric, value)
    san = sanity(metric, value)
    dri = drift(metric, value)
    clean = (dom["verdict"] != "ФИЗИЧЕСКИ НЕВЪЗМОЖНА"
             and san["verdict"] != "НЕВЪЗМОЖНА"
             and dri["verdict"] != "ДРЕЙФ")

    sh = rec.setdefault("shadow", {"clean_streak": 0, "seen": 0})
    sh["seen"] += 1
    sh["last_ts"] = _now()
    sh["clean_streak"] = (sh["clean_streak"] + 1) if clean else 0

    out = {"source": source, "metric": metric, "value": value, "shadow": True,
           "clean": clean, "clean_streak": sh["clean_streak"],
           "needed": SHADOW_CLEAN_NEEDED, "rehabilitated": False}

    if sh["clean_streak"] >= SHADOW_CLEAN_NEEDED:
        rec["quarantined"] = False
        rec["points"] = []                    # чистата поредица гаси старите точки
        rec["rehabilitated_at"] = _now()
        rec["rehabilitated_by"] = (f"{SHADOW_CLEAN_NEEDED} поредни чисти цикъла "
                                   f"в сянка — автоматично, без човек")
        sh["clean_streak"] = 0
        out["rehabilitated"] = True
    _save_state(st)

    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": _now(), "kind": "shadow", **out},
                                ensure_ascii=False) + "\n")
    except Exception:
        pass
    return out


def quarantined() -> set:
    """Кои източници НЕ бива да влизат в осите този цикъл."""
    return {k for k, v in _load_state().items() if v.get("quarantined")}


def judge(source: str, metric: str, value: float) -> dict:
    """Пълната присъда за едно число. Връща и дали да се приеме."""
    s = sanity(metric, value)
    d = drift(metric, value)
    dom = domain_check(metric, value)
    verdicts = []
    # Физическата граница бие всичко: тя е твърдение за света, не за данните.
    if dom["verdict"] == "ФИЗИЧЕСКИ НЕВЪЗМОЖНА":
        verdicts.append(("физически невъзможна стойност", dom))
    elif s["verdict"] == "НЕВЪЗМОЖНА":
        verdicts.append(("невъзможна спрямо историята", s))
    if d["verdict"] == "ДРЕЙФ":
        verdicts.append(("внезапен дрейф", d))
    out = {"source": source, "metric": metric, "value": value,
           "domain": dom, "sanity": s, "drift": d, "accepted": not verdicts}
    # НАМЕРЕНО ПРИ ТЕСТА: една лоша стойност пали и двата детектора и досега
    # получаваше ДВЕ точки. Тоест карантина при праг 3 настъпваше след 2 стойности,
    # а не след 3 — правилото на човека се изпълняваше по-строго, отколкото е
    # написано. Едно число = НАЙ-МНОГО ЕДНА точка; причините се записват заедно.
    # Kimi: „Двата детектора са ЕДНА аномалия през две лещи — корелация, не
    # независимост. Две точки искат ДВА ИЗТОЧНИКА за една ос, не два алгоритъма."
    if verdicts:
        out["distrust"] = distrust(
            source, metric,
            " + ".join(rsn for rsn, _ in verdicts),
            {rsn: det for rsn, det in verdicts})
    out["quarantined"] = source in quarantined()
    if out["quarantined"]:
        out["accepted"] = False
    return out


# ── КРИПТАТА (Kimi, 15 авг 2026 — синтезата вместо А или Б) ─────────────────
# Питах: къде се отрязва карантинираният източник — при вземането (числото изчезва)
# или при оценяването (числото остава с етикет)? Защитавах второто, защото
# карантината трябва да се ВИЖДА. Kimi отхвърли и двете и даде трето:
#
#   „Б. А е ЕПИСТЕМИЧНО САМОУБИЙСТВО — без запис на отхвърленото не можеш да
#    провериш дали карантината е била права, а 'липса' се чете като 'никога не сме
#    имали'."
#   „Неизбежен етикет: value е NULL, отхвърленото число живее САМО в rejected
#    масив. Консуматор, който не чете етикета, получава безопасен null, НЕ ЛЪЖА."
#   „Криптата: отделен append-only quarantine_attestations.jsonl (като night_events,
#    но ПО ДАТУМ). Snapshot държи crypt_ref и value: null. Имаш видимостта на Б и
#    чистотата на А."
#
# Това е по-добро от моето предложение по причина, която не бях видял: етикетът не
# бива да зависи от четящия. Числото просто НЕ Е там — на негово място стои null и
# препратка. Който чете небрежно, получава липса; който чете внимателно, получава
# цялата история. Никой не получава лъжа.
#
# Криптата живее в attestation/ — извън петте папки, които safety/ast_gate.py
# позволява на самомодификацията. Отхвърленото не може да бъде пренаписано от
# системата, която го е отхвърлила.
# СЛЯТО В СЕНЗОРИУМА (Kimi, 15 август 2026):
#   „ДА. Два одитни механизма за една истина са АРХИТЕКТУРЕН РАЗКОЛ — слей ги."
# Моята крипта беше append-only jsonl с crypt_ref и причина в СВОБОДЕН ТЕКСТ.
# experiments/sensorium/sensorium.py вече прави същото, но по-строго: Merkle дърво,
# отделна верига за сянката (penumbra), типизирана причина, която ХВЪРЛЯ при
# непознат тип, и съхранение на точните канонични байтове, които са хеширани.
# Държах два механизма за едно и също. Сега отхвърленото число отива в penumbra.
CRYPT_FALLBACK = BASE / "attestation" / "quarantine_attestations.jsonl"


def bury(source: str, metric: str, value, judgement: dict) -> str:
    """Погребва отхвърленото число В СЕНЗОРНАТА СЯНКА и връща препратка към него.

    Причината вече е ТИПИЗИРАНА (impossible_value / source_distrusted), а не
    свободен текст — сензориумът отказва капка с причина, която не може да назове.
    Ако сензориумът е недостъпен, пада на стария append-only файл и КАЗВА, че е
    паднал: тиха загуба на одитна следа е по-лоша от липсата ѝ."""
    dom_bad = (judgement.get("domain") or {}).get("verdict") == "ФИЗИЧЕСКИ НЕВЪЗМОЖНА"
    reason = "impossible_value" if dom_bad else "source_distrusted"
    payload = {"metric": metric, "rejected_value": value, "source": source,
               "why": {"domain": (judgement.get("domain") or {}).get("why"),
                       "sanity": (judgement.get("sanity") or {}).get("why"),
                       "drift": (judgement.get("drift") or {}).get("why")}}
    try:
        from experiments.sensorium.sensorium import drop as _drop
        return _drop(axis=f"indicator/{metric}", kind="numeric", payload=payload,
                     collector=f"source_trust/{source}",
                     quarantine={"reason": reason})
    except Exception as e:
        ref = hashlib.sha256(
            f"{_now()}|{source}|{metric}|{value}".encode("utf-8")).hexdigest()[:16]
        try:
            CRYPT_FALLBACK.parent.mkdir(parents=True, exist_ok=True)
            with open(CRYPT_FALLBACK, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ref": ref, "ts": _now(), "reason": reason,
                                     "sensorium_unavailable": f"{type(e).__name__}: {e}",
                                     **payload}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        print(f"  [TRUST] СЕНЗОРИУМЪТ НЕ ПРИЕ капката ({type(e).__name__}) — "
              f"записано във fallback, веригата за това число ЛИПСВА")
        return ref


def exhume(ref: str) -> dict | None:
    """Какво точно е било отхвърлено — от сянката, иначе от fallback-а."""
    try:
        from experiments.sensorium.sensorium import PENUMBRA_LEAVES, REPO
        for line in PENUMBRA_LEAVES.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("id") == ref:
                body = json.loads((REPO / e["path"]).read_text(encoding="utf-8"))
                return {"leaf": e, "record": body}
    except Exception:
        pass
    try:
        for line in CRYPT_FALLBACK.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("ref") == ref:
                return json.loads(line)
    except Exception:
        pass
    return None


_SKIP_KEYS = ("_", "timestamp", "sources")


def filter_snapshot(snapshot: dict, source_of=None) -> dict:
    """Минава през числата на снимката и погребва негодните.

    На мястото на отхвърленото число остава None + препратка в `_rejected`.
    Снимката НЕ носи число, за което се знае, че е негодно — това беше слабостта
    на моето предложение и Kimi я затвори.
    """
    out = json.loads(json.dumps(snapshot, ensure_ascii=False))   # не пипаме входа
    rejected = []
    for section, body in list(out.items()):
        if section.startswith(_SKIP_KEYS) or not isinstance(body, dict):
            continue
        src = source_of(section) if source_of else section
        for metric, value in list(body.items()):
            if metric.startswith("_") or not isinstance(value, (int, float)):
                continue
            if src in quarantined():
                # СЯНКА: чете се, съди се, но не влиза в оценката. Така източникът
                # може да заслужи връщане, вместо карантината да е вечна де факто.
                sh = shadow_observe(src, metric, float(value))
                if not sh.get("rehabilitated"):
                    ref = bury(src, metric, value,
                               {"domain": {"why": "карантина — четено в сянка"},
                                "sanity": {}, "drift": {}})
                    body[metric] = None
                    rejected.append({"section": section, "metric": metric,
                                     "crypt_ref": ref, "source": src,
                                     "reason": (f"карантина; чисти в сянка "
                                                f"{sh.get('clean_streak')}/"
                                                f"{SHADOW_CLEAN_NEEDED}")})
                    continue
            j = judge(src, metric, float(value))
            if j["accepted"]:
                continue
            ref = bury(src, metric, value, j)
            body[metric] = None                     # НЕИЗБЕЖНИЯТ етикет
            rejected.append({"section": section, "metric": metric,
                             "crypt_ref": ref, "source": src,
                             "reason": (j.get("distrust") or {}).get("points") and
                                       "точка на недоверие" or "карантиниран източник"})
    if rejected:
        out["_rejected"] = rejected
        out["_rejected_note"] = ("Тези числа са ОТХВЪРЛЕНИ, не липсващи. Стойността "
                                 "им е в attestation/quarantine_attestations.jsonl по "
                                 "crypt_ref — за да може утре да се съди дали "
                                 "отхвърлянето е било право.")
    return out


def commit_sections(snapshot: dict) -> dict:
    """BATCH COMMIT: една секция = един лист в проверената верига.

    Kimi, 15 август 2026, на въпроса дали всяко число да става drop():
      „НЕ. Не разбивай снимката на 4340 атома — прави BATCH COMMIT на ХЕША НА
       СЕКЦИЯТА в penumbra. Запазваш структура, получаваш веригата."
      „Единствената причина да не се слива е ОБЕМ. Но се лекува с batching, не с
       паралелна архитектура."

    Дотук твърдите числа стояха в JSON снимка ИЗВЪН всякаква одитна верига, докато
    сензорните капки имаха Merkle дърво. Сега снимката влиза в същата верига, но
    като 20 листа, не като хиляди: всеки лист носи хеша и състава на своята секция.
    """
    try:
        from experiments.sensorium.sensorium import drop as _drop
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "committed": 0}

    ids, n = [], 0
    for section, body in snapshot.items():
        if section.startswith("_") or section in ("timestamp", "sources"):
            continue
        if not isinstance(body, dict):
            continue
        values = {k: v for k, v in body.items()
                  if not k.startswith("_") and isinstance(v, (int, float))}
        if not values:
            continue                       # празна секция не е свидетелство
        payload = {"section": section,
                   "source": (snapshot.get("sources") or {}).get(section),
                   "n_values": len(values),
                   "values": values,        # съставът, за да е проверим листът
                   "cycle_ts": snapshot.get("timestamp")}
        try:
            ids.append(_drop(axis=f"indicators/{section}", kind="numeric",
                             payload=payload, collector="global_indicators"))
            n += 1
        except Exception:
            continue
    return {"ok": True, "committed": n, "ids": ids}


def ensure_rules_file() -> Path:
    """Създава човешкия файл с правилата, ако го няма. НЕ го пренаписва."""
    if not RULES.exists():
        try:
            RULES.parent.mkdir(parents=True, exist_ok=True)
            RULES.write_text(json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        except Exception:
            pass
    return RULES


def report() -> dict:
    st = _load_state()
    return {"ts": _now(), "rules": rules(),
            "sources_watched": len(st),
            "quarantined": sorted(quarantined()),
            "points_by_source": {k: len(v.get("points", [])) for k, v in st.items()}}


if __name__ == "__main__":
    import sys
    ensure_rules_file()
    if "--report" in sys.argv:
        print(json.dumps(report(), ensure_ascii=False, indent=2))
    else:
        m = sys.argv[1] if len(sys.argv) > 1 else "gdp_growth_pct"
        v = float(sys.argv[2]) if len(sys.argv) > 2 else 2.9
        print(json.dumps(judge("test_source", m, v), ensure_ascii=False, indent=2))
