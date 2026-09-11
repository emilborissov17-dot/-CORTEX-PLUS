# AGI — 14 точки, като числа

_2026-09-11T17:04:09Z · chain_valid=True_

LIVE = числото е там и бие контрола; PARTIAL = числото е там, не бие или е малко; SEED = има зародиш, не стъпка; — = няма число.

| т. | точка | число днес | откъде | присъда |
|---:|---|---|---|---|
| 1 | Генералност и трансфер | static world: v2x_rule from energy, kNN MAE 0.1392 vs mean 0.2797 (61/79 closer); moving world: weights learned on A beat persistence on B in 1/12 pairs; all-lags ridge beats own-lags on 0/4 targets | COUNTRY_BENCH.md (by hand); CROSS_SERIES_BENCH.json (morning step, E1) | **SEED** |
| 2 | Учи от опит — в параметрите | world_next scored 5, learner err 0.0522 vs baseline 0.075; 5 fitted parameter(s) in learner_state | prophecy ledger + memory/learner_state.json | **PARTIAL** |
| 3 | Учи от малко примери | learning curve (ridge on all lags vs persistence): k=10: 0/4, k=20: 0/4, k=40: 0/4, k=80: 0/4 | CROSS_SERIES_BENCH.json few_examples (morning step, E1) | **SEED** |
| 4 | Нови понятия | E2 concepts on the daily world: found 2, surviving out of sample 1; constancy classes: {'MOVING': 9, 'POSITIVE_CONSTANT': 0, 'NEGATIVE_CONSTANT': 0, 'NEGATIVE_TREND': 1, 'UNCLASSIFIED': 6} | CROSS_SERIES_BENCH.json (E2, morning step); memory/constancy_bands_latest.json | **PARTIAL** |
| 5 | Активно търси информация | verified sensor cards accepted 6, refused 2; daily tier 60 indicators | memory/verified_observations.jsonl, card_refusals.jsonl, daily_tier.jsonl | **PARTIAL** |
| 6 | Планиране + заслуга | cycle reviews on file 0, failed streak 0; sandbox T6 FAIL / T6A PASS | memory/brain_cycle_reviews.jsonl; SANDBOX_BENCH.json | **PARTIAL** |
| 7 | Калибрирана несигурност | Brier self_failure 0.2444 vs 0.5388 (54 scored); self_survive scored 0; world 80% intervals covered 0.857 | prophecy ledger; CROSS_SERIES_BENCH.json (E4) | **LIVE** |
| 8 | Световен модел | daily tier 60 indicators, 4 moving; axis_next degenerate 620/748 | memory/daily_tier.jsonl; prophecy ledger | **PARTIAL** |
| 9 | Тренировъчен контур | 5 indicators with a fitted parameter; weekly comparison: no comparison yet; corpus 199 rows (no LLM training run) | memory/learner_progress.jsonl (snapshot each morning), learner_state.json, verified_corpus.manifest.json | **SEED** |
| 10 | Самомодел | self_failure 54 scored, learner beats control=True; reviews 0; canon invariants 1 | prophecy ledger; brain_cycle_reviews.jsonl; canon_invariants.json | **PARTIAL** |
| 11 | Цели — държи, разлага, ревизира | targets grounded 0.0 / ungrounded 17.0; signed indicator bands: {'OK': 2, 'ALARM': 0, 'RECORD_ONLY': 1, 'NO_VALUE': 0, 'CONFIG_ERROR': 0}; initiatives active 25 (in progress 0) | TARGET_GROUNDING.md; alarm_bands_latest.json; data/initiatives | **PARTIAL** |
| 12 | Действие → последствие | sandbox T12 PASS; cards accepted 6; self_survive scored 0 | SANDBOX_BENCH.json; verified_observations.jsonl; ledger | **PARTIAL** |
| 13 | Разбиране срещу симулация | counterfactual probe 2026-09-11: 9 cases, TRACKS 9, INSENSITIVE 0, NOISE_DRIVEN 0, WRONG 0, SILENT 0; tracks_rate 1.0 | memory/counterfactual_probe_latest.json (core/counterfactual_probe.py, morning step) | **SEED** |
| 14 | Съзнание | — | open; no test | **—** |

**LIVE 1 · PARTIAL 8 · SEED 4 · — 1**

Правило: тази страница се пренаписва всяка сутрин от tools/prophecy_morning.bat. Число, което не може да се прочете от файл, е „—“ с причина. Присъдите са механични (scripts/agi_scoreboard.py) — грешни по проверим начин.
