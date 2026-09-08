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
    # PRODUCT NARROWED 8 сеп 2026, from the TREE to the FILE.
    # This row declared "snapshots/master" — the whole directory — and
    # kept_promise() takes the NEWEST file's mtime inside a tree. But
    # snapshots/master/ also holds goal_score_latest.json and
    # needs_reanalysis_latest.json, written by OTHER steps in the same cycle. So
    # update_master could fail to write its own artifact and still read ОБНОВИ,
    # on somebody else's file. A promise that another step can keep for you is
    # not a promise.
    #
    # update_master() writes exactly one file, at fast_cycle_runner.py:1416:
    # snapshots/master/master_snapshot_latest.json. That is what
    # config/cycle_phases.json already promises from D_SCORE — the same
    # disagreement between the two cards that scoring_engine had, with the phase
    # card right again.
    #
    # No logic changed: only what the table says this step leaves behind.
    ("update_master", "12", "Слива всичко в master snapshot.",
     ["snapshots/master/master_snapshot_latest.json"], True),
    ("system_hypergraph", "12.3", "Строи хиперграфа на системата.", [], False),
    # PRODUCT DECLARED 8 сеп 2026. This row carried [] — which the header of
    # this file defines as "не знаем", not "нищо не произвежда" — on the step
    # that produces THE NUMBER everything downstream rests on, and which is
    # BACKBONE (never skipped by opinion).
    #
    # config/cycle_phases.json already promised output/cortex_scores_latest.json
    # from D_SCORE, so the phase card knew and the STEP card did not: the two
    # maps disagreed about the most load-bearing artifact in the cycle.
    #
    # Written by fast_cycle_runner.py:2933 on the cycle path (the runner
    # persists what score_all_snapshots() returns). cortex_scoring_engine.
    # save_scores():1592 writes the same path, but only from that module's
    # __main__ block, which the cycle never takes.
    #
    # kept_promise() can now answer for this step at all: until now it returned
    # "НЕ ЗНАЕМ" -> UNKNOWN(0), which became the promise dimension of the NEXT
    # step. No score, threshold or scorer changed here — only what the table
    # says this step leaves behind.
    ("scoring_engine", "12.4", "Оценява всички снимки по осите.",
     ["output/cortex_scores_latest.json"], True),
    # ── ОСЕМТЕ, КОИТО РАБОТЕХА БЕЗ ДА СЪЩЕСТВУВАТ В ТАБЛИЦАТА (23 авг 2026) ──
    # Всяка от тях има собствен beat() и собствен _run() в fast_cycle_runner.py,
    # значи е пълноправна стъпка — и въпреки това я нямаше тук. Последствието
    # беше механично: чекпойнтът ѝ се записваше под име, което таблицата не
    # познава, и се изхвърляше мълчаливо. Десет имена паднаха на пода в цикъла
    # на 23 авг; осем от тях са ето тези (другите две са подстъпки — виж SUBSTEPS).
    ("alarm_bands", "12.42", "Червените линии: праг, пресечен СЕГА, звъни веднага, "
     "а не в сутрешния дайджест.",
     ["memory/alarm_bands_latest.json"], False),
    ("facade_self_check", "12.45", "Ловец на фасади: кои скорери са мъртви, но изглеждат живи.",
     [], False),
    ("auto_levels", "12.5", "Автоматични нива от реални данни.",
     ["memory/auto_levels.json"], False),
    ("level_reconcile", "12.55", "Където думата (auto_levels) и числото (goal_score) "
     "спорят и значението е заковано — числото печели. _RISK_ осите само се отбелязват.",
     [], False),
    ("goal_score_calculator", "12.6", "Композитният резултат спрямо целта (ражда `composite`).",
     ["memory/goal_score_history.json"], True),
    ("deduction", "12.65", "Дедуктивният слой R1-R7 с предпоставки за всеки извод.",
     ["memory/deductions_latest.json", "memory/deduction_rule_stats.json"], False),
    ("constancy_and_constellation", "12.66",
     "Постоянството като измерване: очакван режим на всеки показател + четене на всички заедно.",
     ["memory/constancy_latest.json", "memory/constellation_latest.json"], False),
    ("axis_feed", "12.68", "Фийдът по ос към опашката: ос без число излиза с ABSENT ред "
     "и причина, вместо да изчезне.",
     ["openclaw_queue/axis_feeds_latest.json"], False),
    ("cognitive_orchestrator", "12.7", "Когнитивна оркестрация; дава priority_axes на HyperClaw.",
     ["memory/orchestration_latest.json"], False),
    ("brain_reconsider", "12.75",
     "Точката на връщане: мозъкът решава продължава ли, или преизчислява една стъпка (макс 1/цикъл).",
     ["memory/reconsider_latest.json"], False),
    ("body_scan", "13", "Тялото СЛЕД тежките стъпки.",
     ["memory/body_scan_latest.json"], False),
    ("growth_planner", "14", "План за растеж според реалното тяло.", [], False),
    # PRODUCT DECLARED 8 сеп 2026. This row carried [] — "не знаем" — and an
    # empty produces makes cycle_map.kept_promise() return "НЕ ЗНАЕМ", which the
    # notary reads as UNKNOWN(0) for the PROMISE dimension of the NEXT step. So
    # hyperclaw_plan was stamped level_0 partly because nobody had written down
    # what its predecessor was supposed to leave behind.
    #
    # It writes plans/plan-<today>.md — agents/hyperclaw/hyperclaw_orchestrator.py
    # line 352, the only unconditional write in main(). The directory is declared
    # rather than the dated filename because the name moves every night;
    # kept_promise() takes the newest file's mtime inside a directory, which is
    # exactly the question ("did HyperClaw write a plan THIS cycle?").
    #
    # The snapshot at line 335 is deliberately NOT here: it is written only on
    # the AllBackendsFailedError path, so promising it would mark a healthy night
    # as a broken promise.
    ("hyperclaw", "15.6", "HyperClaw оркестратор.", ["plans"], False),
    ("hyperclaw_plan", "15.7", "Планът му -> предложения за подобрение.",
     ["memory/improvement_proposals.json"], False),
    ("github_publish", "15.8", "Публикува синтеза на цикъла и проверените хипотези.", [], False),
    ("action_recommendations", "16", "Разсъждение -> препоръка, записана в семантичната памет.",
     ["memory/causal_log.json"], False),
    # ATTRIBUTION CORRECTED 8 сеп 2026. This row promised
    # memory/runtime_experiences.json, and self_observer has never written it:
    # agents/core/self_observer.py writes memory/development_journal.json (542)
    # and memory/improvement_proposals.json (665), and nothing else. The only
    # writer of runtime_experiences.json is memory/runtime_telemetry._append,
    # reached through record_experience(), whose only caller is
    # agents/core/self_modifier.py — step 18, one phase later. The promise sat
    # on the wrong step, so the staleness was blamed every night on a step that
    # was never supposed to produce it.
    # PRODUCES CORRECTED AGAIN 8 сеп 2026, AND THE CONDITIONALITY IS THE POINT.
    # This row named only development_journal.json. AST guard-walk of run():
    # EVERY write in this step is conditional — save_proposals at :276 behind
    # `if dep_proposals:`, save_proposals at :409 behind `if history and not
    # escalated:`, and _save_assessment at :339/:356/:385 behind deeper guards.
    # There is no artifact this step writes on every run.
    #
    # Both are declared because both are really written, and kept_promise() then
    # reads the truth rather than half of it: ОБНОВИ when the night produced
    # both, ЧАСТИЧНО (REDUCED 2, which still clears IRREVERSIBLE_MIN) when it
    # produced one, and НЕ ПИПНА only when the step genuinely left nothing —
    # which is a real fact about the night, not a fault of the declaration.
    ("self_observer", "17", "Наблюдава собственото си поведение.",
     ["memory/improvement_proposals.json", "memory/development_journal.json"], False),
    # runtime_experiences.json is HERE because the REFUSAL is here. The gate
    # (_witness_or_refuse -> _refused) writes the refusal record before run()
    # would have been reached, so the artifact is produced whether the step acts
    # OR is refused. That is what stops this move from hiding the gap behind the
    # REFUSED exemption of commit 0ae4bb4: a night with no record is now a real
    # red, not an excused one.
    ("self_modifier", "18", "Пише пачове за самия себе си.",
     ["memory/improvement_proposals.json", "memory/runtime_experiences.json"], False),
    ("execute_patches", "19", "Изпълнява пачове през AST портата; мери before/after и качеството на измерването.",
     ["memory/development_journal.json"], False),
    ("feedback_loop", "20", "Обратна връзка по ос от реално измерени стойности.",
     ["memory/feedback_log.json"], False),
    # ДОБАВЕНА 3 сеп 2026 (пейка за калибрация, част 1). И трите карти наведнъж,
    # по урока от ITEM 7.1: fast_cycle_runner, config/cycle_phases.json и тази.
    # `produces` е СТАТУС файлът, а не resolved.json — evaluator пише resolved.json
    # само когато нещо се е разрешило, така че тиха и правилна нощ би се четяла
    # като счупена фаза. Статусът се пише винаги, затова хваща стъпка, която е
    # престанала да се изпълнява.
    ("resolve_hypotheses", "20.05", "Съди дължимите хипотези срещу trends.json; разрешаване само, никога генериране.",
     ["memory/hypothesis_resolution_latest.json"], False),
    # ДОБАВЕНА 3 сеп 2026 (C7). Изпълнява се ПРЕДИ hypothesis_intake, за да стигне
    # тазвечершната ревизия до тазвечершния генератор — иначе примката се затваря
    # за два цикъла вместо за един.
    ("belief_revision", "20.07", "Мести теглата по метод според изненадата от разрешените хипотези.",
     ["memory/belief_state.json"], False),
    # ДОБАВЕНА 3 сеп 2026 (C5+C11). ОТДЕЛНА стъпка от resolve_hypotheses: едната
    # пише pending.json, другата resolved.json, и стъпка, която прави и двете, може
    # да оцени твърдение, което току-що е измислила.
    ("hypothesis_intake", "20.06", "Пре-регистрира тазвечершните предсказания с интервал; само MEASURED оси.",
     ["memory/hypothesis_intake_latest.json"], False),
    # ДОБАВЕНА 29 авг 2026 (ITEM 7.1, поправено в ITEM 10). Стъпката беше
    # обявена в config/cycle_phases.json и НЕ тук, така че първият цикъл, който
    # наистина я изпълни, я записа като unmapped_checkpoint: тя не можеше да
    # запали нито едно квадратче в кокпита. Две карти на едни и същи стъпки —
    # ако добавяш стъпка, и двете искат ред.
    ("measurement_honesty", "20.1", "K1: измереното тегло и защо всяка ос се брои за измерена.",
     ["memory/measurement_honesty_latest.json"], False),
    # ДОБАВЕНА 29 авг 2026 (ITEM 11). И трите карти наведнъж този път —
    # fast_cycle_runner, config/cycle_phases.json и тази — защото ITEM 7.1
    # обяви стъпка само в едната и първият цикъл, който я изпълни, я записа
    # като unmapped_checkpoint.
    ("resolve_ideas", "20.2", "Съди хипотезите на пулса срещу наблюдаваната серия; приложение само, никога редакция на idea_stream.",
     ["memory/idea_resolutions.jsonl"], False),
    ("session_update", "21", "Обновява записа на сесията.", [], False),
    ("daily_analysis", "22", "Дневен анализ.", [], False),
    ("data_scout", "22.5", "Търси нови източници; последен, за да не се бие за LLM лимита.",
     ["memory/discovered_data_sources.json"], False),
    ("continuous_learning", "23", "Учи от цикъла.",
     ["memory/knowledge_base.json"], False),
    # PRODUCT DECLARED 8 сеп 2026. This row carried [] — "не знаем" per this
    # file's own header — on the step that SEALS the audit chain. So
    # kept_promise() could not answer for the artifact the whole chain rests on.
    #
    # merkle_memory.MerkleMemory.commit() writes essence.md (:190), the numbered
    # archive dir (:217/:255) and MERKLE_ROOT (:204). The root is declared and
    # the others are not, per this file's rule that produces names the
    # LOAD-BEARING artifact per step: MERKLE_ROOT.write_text() is the LAST write
    # in commit(), so its freshness is evidence the whole commit COMPLETED
    # rather than merely started. config/cycle_phases.json already promised it
    # from G_LEARN — the same two-card disagreement as scoring_engine and
    # update_master, with the phase card right again.
    ("merklememory_commit", "24", "Merkle ангажимент на паметта — одитната верига.",
     ["cortex_memory/archive/merkle_root.txt"], True),
    # ДОБАВЕНА 3 сеп 2026. verify_cycle() съществуваше от началото на архива и
    # единственият ѝ викащ беше __main__ блокът на самия merkle_memory.py: всяка
    # нощ системата пишеше хаш и нито веднъж не провери, че хашът описва цикъла.
    # backbone=True — проверката на одитната верига не се пропуска по мнение.
    ("merkle_verify", "24.1", "Проверява току-що запечатания цикъл срещу хаша му — proof-of-inclusion.",
     ["memory/merkle_verify_latest.json"], True),
    ("training_data_accumulation", "25", "Трупа тренировъчни данни от архива.", [], False),
    # РЕДЪТ Е ПО ИЗПЪЛНЕНИЕ, НЕ ПО НОМЕР. В runner-а proposal_sla (25.38) стои
    # ПРЕДИ needs_auth (25.37) — номерата са разменени спрямо реда, в който
    # цикълът наистина ги минава. Таблицата описва хода, затова следва хода;
    # индексът остава такъв, какъвто beat() го пише, за да съвпада с лога.
    ("metta_column", "25.35", "Символната колона: 5 правила върху фийдовете; несъгласията "
     "влизат в доклада на D_SCORE.",
     ["memory/metta_assessment_latest.json"], False),
    ("brain_relay", "25.36", "Релето: изнася на телефона онова, което мозъкът е казал.",
     [], False),
    ("proposal_sla", "25.38", "Часовникът на предложенията: просрочено ескалира ВЕДНЪЖ, поименно.",
     [], False),
    ("needs_auth", "25.37", "Източници, които чакат ключ — веднъж седмично, с линка "
     "и името на променливата.",
     [], False),
    ("self_experiment", "25.44",
     "Едно наблюдение на всеки незавършен предварително записан опит; рамото се "
     "проверява срещу живия файл, не се приема на доверие.",
     ["memory/self_experiments.json"], False),
    ("self_mirror", "25.45",
     "Огледалото: калибрация на съдията, дебрифи, отворени предсказания, чакащи "
     "предложения с възраст, доверени източници. НЕ влиза в никакво число.",
     ["memory/self_mirror_latest.json", "memory/self_mirror_log.jsonl"], True),
    ("read_the_mirror", "25.46", "Мозъкът получава ЦЯЛОТО огледало и казва какво вижда; "
     "цитираните числа се проверяват срещу него, не се приемат на доверие.",
     ["memory/mirror_read_latest.json"], False),
    ("brain_debrief", "25.5", "Мозъкът съди собствения си план: сбъдна ли се тестът му.",
     ["memory/brain_journal.jsonl"], True),
    ("cycle_report", "25.6", "Отчетът пред човека, написан от самата система.",
     ["output/reports"], True),
    # ДОБАВЕНА 29 авг 2026 (ITEM 34 стъпка 2). Последна: агрегира завършения
    # цикъл. Изходът ѝ не беше пипан от 13 април, защото никой не я викаше.
    ("cortex_scan", "25.7", "Пълното състояние за таблото — агрегира готовия цикъл.",
     ["memory/cortex_full_state.json"], False),
    # ДОБАВЕНА 29 авг 2026 (ITEM 14). Последна: чете каквото цикълът е написал
    # тази нощ. K2 нарочно отказва число — виж K2_NOT_WIRED_REASON.
    ("compass", "25.8", "Четирите стрелки: измереното тегло, доверието, консолидираните твърдения, интервалният резултат.",
     ["memory/compass_latest.json"], False),
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
    # ── ДВЕ ИМЕНА, КОИТО СА ПРОСТО ПРЕИМЕНУВАНИЯ (23 авг 2026) ─────────────
    # _run() ги вика така, beat() ги обявява иначе. Едно към едно, значи псевдоним.
    "session_updater": "session_update",
    "cortex_reasoner": "action_recommendations",
    # Не беше в списъка на десетте — не се появи в чекпойнтите на 23 авг, защото
    # стъпката беше ОТКАЗАНА от свидетеля и _run() изобщо не се стигна. Тоест
    # име, което щеше да падне на пода първата нощ, в която публикуването мине.
    # Намерено от scripts/verify_checkpoint_map.py, не от четене на лога.
    "github_publisher": "github_publish",
}

# ── ПОДСТЪПКИ: РАБОТА В СТЪПКА, НЕ СТЪПКА (23 авг 2026) ────────────────────
# Тези НЕ СА стъпки и нарочно не влизат в STEPS. Всяка е един _run() ВЪТРЕ в
# чужд beat(): cognitive_orchestrator (12.7) се състои от две — първо
# заземеният ред (аритметика), после моделът, който има право само да ДОПИШЕ
# бележка. Двете имат отделни _run() етикети, защото се провалят поотделно.
#
# Обявени изрично, вместо да падат на пода: чекпойнт, записан под такова име,
# СЕ РАЗРЕШАВА до своята стъпка и се показва като подстъпка, а не като
# непознато име. Разликата спрямо ALIASES е, че псевдонимът Е стъпката, а
# подстъпката е ЧАСТ от нея — и броят на стъпките не бива да расте от части.
SUBSTEPS = {
    "orchestrator_grounded": "cognitive_orchestrator",
    "cortex_orchestrator": "cognitive_orchestrator",
}

# Какво е това име: стъпка, псевдоним, подстъпка, или наистина непознато.
STEP, ALIAS, SUBSTEP, UNKNOWN = "step", "alias", "substep", "unknown"


def resolve(name: str) -> tuple:
    """(канонично_име, вид). Никое от четирите не е грешка — UNKNOWN е отговор.

    Това е единственото място, което знае и трите таблици. Преди го нямаше и
    всеки четец на чекпойнти пишеше свой вариант на `ALIASES.get(x, x)`, който
    мълчаливо изхвърляше всичко останало.
    """
    n = str(name or "")
    if n in BY_NAME:
        return n, STEP
    if n in ALIASES:
        return ALIASES[n], ALIAS
    if n in SUBSTEPS:
        return SUBSTEPS[n], SUBSTEP
    return n, UNKNOWN

BY_NAME = {}
for _n, _i, _p, _prod, _bb in STEPS:
    BY_NAME.setdefault(_n, {"name": _n, "index": _i, "purpose": _p,
                            "produces": _prod, "backbone": _bb})


def _canon(step: str) -> str:
    """Псевдонимите И подстъпките сочат към стъпката, на която принадлежат."""
    return ALIASES.get(step) or SUBSTEPS.get(step) or step


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
