# AGI — 14 точки, като числа

_2026-09-11T11:50:15Z · chain_valid=True_

LIVE = числото е там и бие контрола; PARTIAL = числото е там, не бие или е малко; SEED = има зародиш, не стъпка; — = няма число.

| т. | точка | число днес | откъде | присъда |
|---:|---|---|---|---|
| 1 | Генералност и трансфер | V-Dem rule of law from energy, 3 targets; v2x_rule kNN MAE 0.1392 vs mean 0.2797 (61/79 closer) | claude/reports/COUNTRY_BENCH.md (leave-one-country-out; run by hand, not a step) | **SEED** |
| 2 | Учи от опит — в параметрите | world_next scored 5, learner err 0.0522 vs baseline 0.075; 5 fitted parameter(s) in learner_state | prophecy ledger + memory/learner_state.json | **PARTIAL** |
| 3 | Учи от малко примери | — | no step, no bench | **—** |
| 4 | Нови понятия | — | memory/constancy_bands_latest.json (the seed: constellation/constancy) | **—** |
| 5 | Активно търси информация | verified sensor cards accepted 6, refused 2; daily tier 60 indicators | memory/verified_observations.jsonl, card_refusals.jsonl, daily_tier.jsonl | **PARTIAL** |
| 6 | Планиране + заслуга | cycle reviews on file 0, failed streak 0; sandbox T6 FAIL / T6A PASS | memory/brain_cycle_reviews.jsonl; SANDBOX_BENCH.json | **PARTIAL** |
| 7 | Калибрирана несигурност | Brier self_failure 0.2444 vs 0.5388 (54 scored); self_survive scored 0 | prophecy ledger | **LIVE** |
| 8 | Световен модел | daily tier 60 indicators, 4 moving; axis_next degenerate 620/748 | memory/daily_tier.jsonl; prophecy ledger | **PARTIAL** |
| 9 | Тренировъчен контур | verified corpus 199 rows {'sensor_card': 7, 'predict:self_failure': 54, 'predict:axis_next': 128, 'predict:composer_series': 2, 'predict:world_next': 5, 'predict:self_duration': 1, 'predict:self_degraded': 1, 'predict:self_step_fail': 1} | training/verified_corpus.manifest.json (no training run yet) | **SEED** |
| 10 | Самомодел | self_failure 54 scored, learner beats control=True; reviews 0; canon invariants 1 | prophecy ledger; brain_cycle_reviews.jsonl; canon_invariants.json | **PARTIAL** |
| 11 | Цели — държи, разлага, ревизира | targets grounded 0.0 / ungrounded 17.0; signed indicator bands: {'OK': 2, 'ALARM': 0, 'RECORD_ONLY': 1, 'NO_VALUE': 0, 'CONFIG_ERROR': 0}; initiatives active 133 (in progress 0) | TARGET_GROUNDING.md; alarm_bands_latest.json; data/initiatives | **PARTIAL** |
| 12 | Действие → последствие | sandbox T12 PASS; cards accepted 6; self_survive scored 0 | SANDBOX_BENCH.json; verified_observations.jsonl; ledger | **PARTIAL** |
| 13 | Разбиране срещу симулация | — | memory/counterfactual_probe.jsonl (not built yet) | **—** |
| 14 | Съзнание | — | open; no test | **—** |

**LIVE 1 · PARTIAL 7 · SEED 2 · — 4**

Правило: тази страница се пренаписва всяка сутрин от tools/prophecy_morning.bat. Число, което не може да се прочете от файл, е „—“ с причина. Присъдите са механични (scripts/agi_scoreboard.py) — грешни по проверим начин.
