# K1b TRAINING CORPUS — 4 September 2026

Repo `CORTEX++_MERGED`, branch `feature/lidaction-guard`. Built with `venv/Scripts/python.exe`.

## THE FINDING IN ONE LINE

`merkle_to_training.py:183` read a decision's text with `d.get("action", "")`. Across all 57 archived cycles, **`action` appears in 3 of 1326 decision records (0.2%)** while **`solution` appears in 1323 (99.8%)**. Because the default was `""` and not an error, every mismatched record was written to disk as a valid-looking training pair with an empty target. **46 of 46 records in `training_data.jsonl` are empty.** The file accumulated from 11 July to 4 September and contains no supervision signal. Nothing consumed it, so nothing complained.

## PHASE 0 — AUDIT (read-only, every record iterated, nothing sampled)

### Sources `merkle_to_training.py` reads

| path | opened at | role |
|---|---|---|
| `cortex_memory/archive/cycle_*/signals.json` | `build_pair()` | input: signals |
| `cortex_memory/archive/cycle_*/decisions.json` | `build_pair()` | **target: decisions** |
| `cortex_memory/archive/cycle_*/results.json` | `build_pair()` | input: goal_score |
| `cortex_memory/abstractions/essence.md` | `_essence_excerpt()` | input: essence |
| `cortex_memory/training/training_data.jsonl` | `_already_processed()` | output + idempotency |

### `cortex_memory/archive/cycle_*/decisions.json` — list key `decisions`

- files present: **57 of 57**
- records: **1326**
- distinct key-set signatures: **9**

| key | records carrying it | % |
|---|---:|---:|
| `priority` | 1326 | 100.0% |
| `problem` | 1323 | 99.8% |
| `solution` | 1323 | 99.8% |
| `measurable_goal` | 1323 | 99.8% |
| `real_world_signal` | 1323 | 99.8% |
| `timestamp` | 1323 | 99.8% |
| `component` | 1311 | 98.9% |
| `root_cause` | 1305 | 98.4% |
| `generated_by` | 841 | 63.4% |
| `approved` | 488 | 36.8% |
| `rejected` | 488 | 36.8% |
| `agi_characteristic` | 482 | 36.3% |
| `source` | 482 | 36.3% |
| `downstream_impact` | 470 | 35.4% |
| `authored_by` | 49 | 3.7% |
| `moral_check` | 31 | 2.3% |
| `experiment_id` | 18 | 1.4% |
| `accepted_by` | 18 | 1.4% |
| `passes_measurable_gate` | 13 | 1.0% |
| `why` | 13 | 1.0% |
| `gate_signals` | 13 | 1.0% |
| `feedback_note` | 8 | 0.6% |
| `action` | 3 | 0.2% |

#### Key-set signatures, with one redacted example each

**SIG 1 — 786 records** · `solution` present: YES · `action` present: NO

keys: `component, generated_by, measurable_goal, priority, problem, real_world_signal, root_cause, solution, timestamp`

from `cycle_000004`:

```json
{
 "component": "unknown",
 "problem": "To enable full system functionality",
 "solution": "Update fast_cycle_runner.py to include missing agents",
 "measurable_goal": "Update fast_cycle_runner.py to include missing agents",
 "root_cause": "OpenClaw scan → fast_cycle_runner.py",
 "priority": "HIGH",
 "real_world_signal": true,
 "generated_by": "OPENCLAW",
 "timestamp": "2026-06-20T07:36:27.744791+00:00"
}
```

**SIG 2 — 470 records** · `solution` present: YES · `action` present: NO

keys: `agi_characteristic, approved, component, downstream_impact, measurable_goal, priority, problem, real_world_signal, rejected, root_cause, solution, source, timestamp`

from `cycle_000012`:

```json
{
 "problem": "Без пълната верига система не може да изпълни ключови прегледи по воде…",
 "component": "water_resource_monitoring_agent",
 "root_cause": "Недостатъчен сбор и интеграция на реални данни за водните ресурси",
 "solution": "Създайте и изпълните таск по сбор и интеграция на водни ресурси от раз…",
 "measurable_goal": "Увеличение на 20% в броя на водните мониторингове за година",
 "agi_characteristic": "AUTONOMOUS_LEARNING|COMMON_SENSE",
 "priority": "HIGH",
 "real_world_signal": true,
 "source": "self_observer_problem_solution",
 "downstream_impact": {
  "queried_node": "water_resource_monitoring_agent",
  "degree": 0,
  "upstream_agents": [],
  "downstream_agents": [],
  "is_isol
```

**SIG 3 — 18 records** · `solution` present: YES · `action` present: NO

keys: `authored_by, component, experiment_id, generated_by, measurable_goal, priority, problem, real_world_signal, solution, timestamp`

from `cycle_000012`:

```json
{
 "component": "config/scheduler.json",
 "problem": "experiment exp-001-daily-analysis-ceiling cannot observe arm 900 — con…",
 "solution": "experiment exp-001-daily-analysis-ceiling: set step_ceilings_sec.daily…",
 "measurable_goal": "4 cycles observed at step_ceilings_sec.daily_analysis=900, then core/s…",
 "priority": "MEDIUM",
 "generated_by": "core/self_experiment.py",
 "authored_by": "core/self_experiment.py",
 "experiment_id": "exp-001-daily-analysis-ceiling",
 "real_world_signal": false,
 "timestamp": "2026-08-28T15:27:30.255088+00:00"
}
```

**SIG 4 — 18 records** · `solution` present: YES · `action` present: NO

keys: `accepted_by, authored_by, component, generated_by, measurable_goal, moral_check, priority, problem, real_world_signal, root_cause, solution, timestamp`

from `cycle_000022`:

```json
{
 "component": "SOCIAL_RELATIONS_REVIEW",
 "problem": "furthest from the goal: SOCIAL_RELATIONS_REVIEW (weighted gap 7.728)",
 "solution": "Social Relations Review score increases by 10% within 3 years",
 "measurable_goal": "Social Relations Review score increases by 10% within 3 years",
 "root_cause": "human-accepted via Telegram approval",
 "priority": "HIGH",
 "real_world_signal": true,
 "generated_by": "human_telegram_approval",
 "accepted_by": "7348567964",
 "authored_by": "local:qwen2.5:3b",
 "moral_check": "passed",
 "timestamp": "2026-07-30T10:45:28.901405+00:00"
}
```

**SIG 5 — 13 records** · `solution` present: YES · `action` present: NO

keys: `authored_by, component, gate_signals, generated_by, measurable_goal, moral_check, passes_measurable_gate, priority, problem, real_world_signal, root_cause, solution, timestamp, why`

from `cycle_000020`:

```json
{
 "component": "SOCIAL_RELATIONS_REVIEW",
 "problem": "SOCIAL_RELATIONS_REVIEW is furthest from the civilization goal",
 "solution": "Implement community-building programs and encourage local leaders to f…",
 "measurable_goal": "Social relations review score increases by 10% in the next two years",
 "root_cause": "goal_prophecy autonomous deliberation (own local brain)",
 "priority": "HIGH",
 "real_world_signal": true,
 "generated_by": "GOAL_PROPHECY_SELF_DIRECT",
 "authored_by": "local:qwen2.5:3b",
 "passes_measurable_gate": true,
 "moral_check": "passed",
 "why": "This solution focuses on improving human connections within communitie…",
 "gate_signals": {
  "percent": true,
  "year": fals
```

**SIG 6 — 8 records** · `solution` present: YES · `action` present: NO

keys: `agi_characteristic, approved, feedback_note, measurable_goal, priority, problem, real_world_signal, rejected, root_cause, solution, source, timestamp`

from `cycle_000004`:

```json
{
 "problem": "Недостатък в правителствената гъвкавост и устойчивост на държавата във…",
 "root_cause": "Отсутствие на ефективни механизми за обществен контрол и участие",
 "solution": "Разработване на платформа за гражданско участие и онлайнPETИЦИИ, интег…",
 "measurable_goal": "10 000 потписа на петицията за увеличаване на прозрачността на правите…",
 "agi_characteristic": "REASONING",
 "priority": "MEDIUM",
 "real_world_signal": true,
 "source": "self_observer_problem_solution",
 "approved": true,
 "rejected": false,
 "timestamp": "2026-05-07T10:20:08.774529+00:00",
 "feedback_note": "Повишен — подобрение"
}
```

**SIG 7 — 6 records** · `solution` present: YES · `action` present: NO

keys: `approved, component, generated_by, measurable_goal, priority, problem, real_world_signal, rejected, root_cause, solution, timestamp`

from `cycle_000041`:

```json
{
 "component": "DEPENDENCY_CHECK",
 "problem": "groq_chat тест неуспешен: HTTP 404",
 "solution": "Проверете GROQ_API_KEY на https://console.groq.com. Ако ключът е валид…",
 "measurable_goal": "dependency_check_latest.json checks.groq_chat.ok == true",
 "root_cause": "DEPENDENCY_CHECK / network or invalid key",
 "priority": "HIGH",
 "real_world_signal": true,
 "generated_by": "SELF_OBSERVER",
 "approved": true,
 "rejected": false,
 "timestamp": "2026-08-17T16:16:38.179429+00:00"
}
```

**SIG 8 — 4 records** · `solution` present: YES · `action` present: NO

keys: `agi_characteristic, approved, measurable_goal, priority, problem, real_world_signal, rejected, root_cause, solution, source, timestamp`

from `cycle_000004`:

```json
{
 "problem": "Повишено ниво на непрекъснато движение и неразрешен проблем със стари …",
 "root_cause": "Недостатъчен бюджет за инфраструктурни проекти и липса на ефективно уп…",
 "solution": "Създаване на интегрирана система за управление на инфраструктурни прое…",
 "measurable_goal": "25% намаление на броя на несъответствията на пътищата за 12 месеца",
 "agi_characteristic": "GENERALIZATION",
 "priority": "HIGH",
 "real_world_signal": true,
 "source": "self_observer_problem_solution",
 "approved": true,
 "rejected": false,
 "timestamp": "2026-05-07T10:20:08.774654+00:00"
}
```

**SIG 9 — 3 records** · `solution` present: NO · `action` present: YES

keys: `action, priority`

from `cycle_000001`:

```json
{
 "action": "monitor",
 "priority": "HIGH"
}
```

### `cortex_memory/archive/cycle_*/results.json` — list key `results`

- files present: **57 of 57**
- records: **190**
- distinct key-set signatures: **6**

| key | records carrying it | % |
|---|---:|---:|
| `timestamp` | 141 | 74.2% |
| `patch` | 101 | 53.2% |
| `success` | 101 | 53.2% |
| `stdout` | 101 | 53.2% |
| `stderr` | 101 | 53.2% |
| `score_before` | 101 | 53.2% |
| `score_after` | 101 | 53.2% |
| `delta` | 101 | 53.2% |
| `verdict` | 101 | 53.2% |
| `changed_axes` | 101 | 53.2% |
| `type` | 86 | 45.3% |
| `ledger_head_hash` | 46 | 24.2% |
| `ledger_events` | 46 | 24.2% |
| `ledger_chain_valid` | 46 | 24.2% |
| `existence` | 46 | 24.2% |
| `original_filename` | 40 | 21.1% |
| `quarantined_path` | 40 | 21.1% |
| `deny_reason` | 40 | 21.1% |
| `verdict_gate` | 40 | 21.1% |
| `verdict_stage` | 40 | 21.1% |
| `source_proposal_component` | 40 | 21.1% |
| `measured` | 30 | 15.8% |
| `measurement_quality` | 21 | 11.1% |
| `measurement_why` | 21 | 11.1% |
| `improvement_score` | 3 | 1.6% |

### `cortex_memory/archive/cycle_*/signals.json` — list key `signals`

- files present: **57 of 57**
- records: **2373**
- distinct key-set signatures: **2**

| key | records carrying it | % |
|---|---:|---:|
| `source` | 2373 | 100.0% |
| `category` | 2373 | 100.0% |
| `domain` | 2373 | 100.0% |
| `metric` | 2373 | 100.0% |
| `value` | 2373 | 100.0% |
| `delta` | 21 | 0.9% |
| `timestamp` | 21 | 0.9% |
| `raw` | 21 | 0.9% |

### The existing corpus `cortex_memory/training/training_data.jsonl`

- total records: **46**
- top-level keys: `['cycle_dir', 'cycle_id', 'input', 'output']`
- records whose target (`РЕШЕНИЕ:` block) is empty after stripping `(priority=…)` markers: **46 of 46**
- records carrying real decision text: **0**

The key that SHOULD have supplied the target for every one of them is **`solution`**. The extractor asked for `action`.

| key | decision records carrying it | of | % |
|---|---:|---:|---:|
| `action` | 3 | 1326 | 0.2% |
| `solution` | 1323 | 1326 | 99.8% |
| `problem` | 1323 | 1326 | 99.8% |
| `measurable_goal` | 1323 | 1326 | 99.8% |
| `priority` | 1326 | 1326 | 100.0% |
| `root_cause` | 1305 | 1326 | 98.4% |
| `component` | 1311 | 1326 | 98.9% |

## PHASE 1 — THE KEY CONTRACT

`training/corpus_from_merkle.py` declares a frozen mapping from each observed key-set
signature to the exact key supplying the prompt and the exact key supplying the target.
**There is no `.get(key, "")` anywhere in the mapping path** — that default is what
turned a schema mismatch into two months of silent garbage, and a test asserts it
cannot come back.

- SIG 1-8 (1323 records) -> prompt `problem`, target `solution`
- SIG 9 (3 records, `{action, priority}`) -> **refused on purpose**, named in the
  contract: a bare stub with no problem statement to pair a target with. It is the
  only shape the old extractor could read.
- any signature not listed -> refused as `key_set_not_in_contract`, reported with the
  key set observed

## PHASE 3 — MANIFEST (verbatim)

```json
{
  "built_at_utc": "2026-09-04T16:55:16+00:00",
  "source": "cortex_memory/archive/cycle_*/decisions.json",
  "contract_signatures": 9,
  "total_in": 1326,
  "emitted": 1323,
  "refused_total": 3,
  "refused_by_reason": {
    "bare_action_stub_no_problem_field": 3
  },
  "train_count": 1077,
  "holdout_count": 246,
  "split": "by cycle number, last 20% of cycles held out (never random)",
  "train_cycle_range": [
    4,
    47
  ],
  "holdout_cycle_range": [
    48,
    57
  ],
  "target_len_chars": {
    "min": 21,
    "median": 144,
    "max": 341
  },
  "exact_duplicate_target_rate": 0.4376,
  "distinct_targets": 744,
  "files": {
    "train": "cortex_memory/training/corpus_train.jsonl",
    "holdout": "cortex_memory/training/corpus_holdout.jsonl"
  }
}
```

## REFUSAL TABLE

| reason | count |
|---|---:|
| `bare_action_stub_no_problem_field` | 3 |

Refused **3** of **1326**. Every refusal is a named reason, not a dropped row.

## PHASE 2/3 — PYTEST OUTPUT (verbatim)

```
$ venv/Scripts/python.exe -m pytest test/test_corpus_contract.py -q -rf
..........                                                               [100%]
10 passed in 0.86s
exit=0
```

## WHAT THIS CHANGES

| | before | after |
|---|---:|---:|
| usable experience records | **0** | **1323** |
| records on disk | 46 | 1323 |
| empty targets | 46 of 46 | 0 |
| train / holdout | none | 1077 / 246 |
| holdout split | none | by cycle 48-57, train 4-47 |

**Quality caveat, stated rather than buried:** the exact-duplicate target rate is **0.4376** — only 744 of 1323 targets are distinct. The archive repeats the same proposed solutions across cycles. That is a real limit on what can be learned from this corpus, and it is why the holdout is split by time and never at random: consecutive cycles are near-duplicates, so a random split would score memorisation.
