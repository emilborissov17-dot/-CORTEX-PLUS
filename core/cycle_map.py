#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/cycle_map.py — ТАБЛИЦАТА НА ЦИКЪЛА (15 август 2026)

Досега редът на стъпките живееше единствено като поредица от редове в
fast_cycle_runner.py. Никой — нито мозъкът, нито човекът — не можеше да попита
"какво произвежда тази стъпка и кой го чака после?", защото отговорът беше скрит
в императивния код.

Тук същата поредица е ОБЯВЕНА: име, за какво служи, какви файлове произвежда, от
какво зависи, и може ли изобщо да бъде пропусната. Две неща стават възможни:

  1. ОТЧЕТНОСТ — cycle_report.py проверява за всяка стъпка дали ОБЕЩАНИЯТ ѝ файл
     наистина се е обновил в този цикъл. Стъпка, която пише "-> OK" и не пипва
     нищо, вече не може да се скрие.
  2. ПРАВО НА МОЗЪКА ДА ПОДРЕЖДА — пропускането спира да е мнение срещу мнение:
     мозъкът решава, а таблицата казва механично дали някой по-надолу ще остане
     гладен. Границата пази ДЕЙСТВИЕТО (закон, т.4), не мисълта.

ЧЕСТНО: колоната `produces` е попълнена там, където е ПРОВЕРЕНА срещу живата
машина. Където още не е — стои празен списък и това значи "не знаем", а не
"нищо не произвежда". Празните са работа, не украса.
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

# (име, индекс, за какво служи, произвежда, гръбнак?)
# гръбнак=True => не се пропуска по мнение: одитната верига не се къса.
STEPS = [
    ("boot", "-1", "Първо доказателство за живот; печата cycle_id от супервайзора.",
     ["memory/heartbeat.json"], True),
    # ── Стъпка 2, консенсус с Kimi, 15 авг 2026 ────────────────────────────
    # Планът беше втори — преди тялото и преди човешката дума. Kimi: „план при OOM
    # или thermal throttle е фикция"; „human_approvals преди плана е констрейнт,
    # не опция; иначе планът пише желания, които човекът вече е забранил."
    # Нов ред: тяло -> човешката дума -> известия -> план.
    ("body_scan", "0", "CPU/RAM/VRAM/диск/модели -> адаптивни директиви. Може да СПРЕ "
     "цикъла през хомеостазата (can_start=false).",
     ["memory/body_scan_latest.json", "memory/adaptive_directives.json"], True),
    ("canon_load", "0.05", "Зарежда канона и го сверява с хардкоднат SHA-256. ПРЕДИ плана: "
     "мозъкът чете канона през memory/active_canon_frame.txt.",
     ["memory/active_canon_frame.txt"], True),
    ("telegram_approvals", "0.1", "Прилага човешките отговори OK/NO преди плана.",
     ["memory/approvals_ledger.jsonl", "memory/telegram_offset.json"], False),
    ("brain_briefing", "0.2", "Мозъкът пише плана на деня — вече знаейки тялото и "
     "човешката дума: фокус, подозрение, свой тест за успех.",
     ["memory/brain_cycle_plan.json"], True),
    ("notify_patches_and_initiatives", "0.25", "Известява какво чака одобрение — СЛЕД "
     "плана, за да излязат и нуждите, които самият план е родил.",
     ["memory/pending_approvals.json"], False),
    ("dependency_check", "0.5", "Има ли с какво да работи. Единствената стъпка, която спира цикъла.",
     [], True),
    ("needs_reanalysis_scan", "0.7", "Кои оси са маркирани за преразглеждане. Флагът се "
     "гаси в update_master (12) с ПО-НОВ чист запис, не с изтекло време.",
     ["snapshots/master/needs_reanalysis_latest.json"], False),
    ("web_intelligence", "1", "Свободно търсене в мрежата по осите (най-дългата). Свой "
     "бюджет (таван-300s) в отделен процес: спира сама с частичен резултат, вместо "
     "часовоят да убие цикъла. Редът на осите е по плана на мозъка.",
     ["memory/web_intelligence"], False),
    ("global_indicators", "2.5", "20 секции от 14 независими хоста (7 от тях през един "
     "— World Bank). Всяко число получава произход: откъде, КОГА Е НАБЛЮДАВАНО, "
     "закъснение и доверие по обявена формула.",
     ["snapshots/master/global_indicators_latest.json",
      "memory/provenance_latest.json"], False),
    ("sensorium_ingest", "2.54", "Поглъща сензорни капки; проверява истинската верига и сянката поотделно.",
     ["memory/sensorium"], False),
    ("browser_scout", "2.55", "Ходи по страници за смислови заключения, не само за числа.",
     ["memory/browse_sources"], False),
    ("composers", "2.6", "Дневното портфолио на ос — движещият се сигнал.",
     ["memory/composed_indicators.json", "memory/composer_needs.json"], False),
    # Описанието беше "разминаването LLM срещу данни" — това не е вярно и никога не е
    # било: модулът сравнява БАВНАТА КОТВА срещу ДНЕВНИЯ ПРОКСИ, две данни, без LLM в
    # средата. Картата на самата система лъжеше за самата система — точно класът дефект,
    # който metta_check.observe() лови. (15 авг 2026)
    ("grounding_ledger", "2.7", "Записва котва срещу дневен прокси. Само записва — присъдата е на source_trust.",
     ["memory/grounding_ledger.jsonl"], False),
    ("llm_self_review_axes", "2.75", "LLM преглед по ос СЛЕД сетивата: ниво + разсъждение върху ДНЕШНИТЕ данни.",
     [], False),
    ("trend_tracker", "3", "Посоката на всяка ос през времето.",
     ["memory/trends_latest.json"], False),
    ("cortexstrategist", "3.5", "Стратегическа преценка ПРЕДИ снимките да изядат дневния токен бюджет.",
     [], False),
    ("internet_intelligence", "4", "Интернет агент.", [], False),
    ("civilization_snapshots", "5", "7-те оси на Цивилизация -> снимки.",
     ["snapshots/civilization"], False),
    ("planet_snapshots", "6", "7-те оси на Планета -> снимки.",
     ["snapshots/planet"], False),
    ("human_snapshots", "7", "5-те оси на Човек -> снимки.",
     ["snapshots/human"], False),
    ("cosmos_snapshots", "8", "6-те оси на Космос -> снимки.",
     ["snapshots/cosmos"], False),
    ("planetary_potential", "9", "Преглед на планетарния потенциал.", [], False),
    ("energy_review", "10", "Енергиен преглед.", [], False),
    ("self_awareness", "11", "Агент за самоосъзнаване.",
     ["memory/self_profile.json", "memory/self_narrative_latest.txt"], False),
    ("update_master", "12", "Слива всичко в master snapshot.",
     ["snapshots/master"], True),
    ("system_hypergraph", "12.3", "Строи хиперграфа на системата.", [], False),
    ("scoring_engine", "12.4", "Оценява всички снимки по осите.", [], True),
    ("facade_self_check", "12.45", "Ловец на фасади: кои скорери са мъртви, но изглеждат живи.",
     [], False),
    ("auto_levels", "12.5", "Автоматични нива от реални данни.",
     ["memory/auto_levels.json"], False),
    ("goal_score_calculator", "12.6", "Композитният резултат спрямо целта (ражда `composite`).",
     ["memory/goal_score_history.json"], True),
    ("deduction", "12.65", "Дедуктивният слой R1-R7 с предпоставки за всеки извод.",
     ["memory/deductions_latest.json", "memory/deduction_rule_stats.json"], False),
    ("constancy_and_constellation", "12.66",
     "Постоянството като измерване: очакван режим на всеки показател + четене на всички заедно.",
     ["memory/constancy_latest.json", "memory/constellation_latest.json"], False),
    ("cognitive_orchestrator", "12.7", "Когнитивна оркестрация; дава priority_axes на HyperClaw.",
     ["memory/orchestration_latest.json"], False),
    ("brain_reconsider", "12.75",
     "Точката на връщане: мозъкът решава продължава ли, или преизчислява една стъпка (макс 1/цикъл).",
     ["memory/reconsider_latest.json"], False),
    ("body_scan", "13", "Тялото СЛЕД тежките стъпки.",
     ["memory/body_scan_latest.json"], False),
    ("growth_planner", "14", "План за растеж според реалното тяло.", [], False),
    ("hyperclaw", "15.6", "HyperClaw оркестратор.", [], False),
    ("hyperclaw_plan", "15.7", "Планът му -> предложения за подобрение.",
     ["memory/improvement_proposals.json"], False),
    ("github_publish", "15.8", "Публикува синтеза на цикъла и проверените хипотези.", [], False),
    ("action_recommendations", "16", "Разсъждение -> препоръка, записана в семантичната памет.",
     ["memory/causal_log.json"], False),
    ("self_observer", "17", "Наблюдава собственото си поведение.",
     ["memory/runtime_experiences.json"], False),
    ("self_modifier", "18", "Пише пачове за самия себе си.",
     ["memory/improvement_proposals.json"], False),
    ("execute_patches", "19", "Изпълнява пачове през AST портата; мери before/after и качеството на измерването.",
     ["memory/development_journal.json"], False),
    ("feedback_loop", "20", "Обратна връзка по ос от реално измерени стойности.",
     ["memory/feedback_log.json"], False),
    ("session_update", "21", "Обновява записа на сесията.", [], False),
    ("daily_analysis", "22", "Дневен анализ.", [], False),
    ("data_scout", "22.5", "Търси нови източници; последен, за да не се бие за LLM лимита.",
     ["memory/discovered_data_sources.json"], False),
    ("continuous_learning", "23", "Учи от цикъла.",
     ["memory/knowledge_base.json"], False),
    ("merklememory_commit", "24", "Merkle ангажимент на паметта — одитната верига.",
     [], True),
    ("training_data_accumulation", "25", "Трупа тренировъчни данни от архива.", [], False),
    ("self_experiment", "25.44",
     "Едно наблюдение на всеки незавършен предварително записан опит; рамото се "
     "проверява срещу живия файл, не се приема на доверие.",
     ["memory/self_experiments.json"], False),
    ("self_mirror", "25.45",
     "Огледалото: калибрация на съдията, дебрифи, отворени предсказания, чакащи "
     "предложения с възраст, доверени източници. НЕ влиза в никакво число.",
     ["memory/self_mirror_latest.json", "memory/self_mirror_log.jsonl"], True),
    ("brain_debrief", "25.5", "Мозъкът съди собствения си план: сбъдна ли се тестът му.",
     ["memory/brain_journal.jsonl"], True),
    ("cycle_report", "25.6", "Отчетът пред човека, написан от самата система.",
     ["output/reports"], True),
]

# Логовете отпреди [STEP] маркерите носят етикетите на _run(), които не съвпадат
# с имената на стъпките. За да важи отчетът и за миналото:
ALIASES = {
    "web_intelligence_agent": "web_intelligence",
    "internet_agent": "internet_intelligence",
    "civilization_snapshots_agent": "civilization_snapshots",
    "planet_snapshots_agent": "planet_snapshots",
    "human_snapshots_agent": "human_snapshots",
    "cosmos_snapshots_agent": "cosmos_snapshots",
    "planetary_potential_agent": "planetary_potential",
    "energy_review_agent": "energy_review",
    "cortex_strategist_agent": "cortexstrategist",
    "body_scanner": "body_scan",
    "sensorium": "sensorium_ingest",
    "hyperclaw_orchestrator": "hyperclaw",
    "self_awareness_agent": "self_awareness",
}

BY_NAME = {}
for _n, _i, _p, _prod, _bb in STEPS:
    BY_NAME.setdefault(_n, {"name": _n, "index": _i, "purpose": _p,
                            "produces": _prod, "backbone": _bb})


def _canon(step: str) -> str:
    return ALIASES.get(step, step)


def purpose(step: str) -> str:
    return BY_NAME.get(_canon(step), {}).get("purpose", "")


def produces(step: str) -> list:
    return BY_NAME.get(_canon(step), {}).get("produces", [])


def is_backbone(step: str) -> bool:
    return bool(BY_NAME.get(_canon(step), {}).get("backbone"))


def kept_promise(step: str, since_ts: float) -> tuple:
    """Обеща ли и удържа ли? Връща (verdict, детайли).
    verdict: 'ОБНОВИ' / 'НЕ ПИПНА' / 'НЕ ЗНАЕМ' — механична проверка на mtime
    срещу началото на цикъла. Това е антидотът на '-> OK' без нищо зад него."""
    decl = produces(step)
    if not decl:
        return "НЕ ЗНАЕМ", "стъпката няма обявени продукти в таблицата"
    touched, stale = [], []
    for rel in decl:
        p = BASE / rel
        try:
            if p.is_dir():
                m = max((c.stat().st_mtime for c in p.rglob("*") if c.is_file()),
                        default=0)
            else:
                m = p.stat().st_mtime
        except Exception:
            stale.append(f"{rel} (липсва)")
            continue
        (touched if m >= since_ts else stale).append(rel)
    if touched and not stale:
        return "ОБНОВИ", ", ".join(touched)
    if touched:
        return "ЧАСТИЧНО", f"обнови {', '.join(touched)}; не пипна {', '.join(stale)}"
    return "НЕ ПИПНА", ", ".join(stale)
