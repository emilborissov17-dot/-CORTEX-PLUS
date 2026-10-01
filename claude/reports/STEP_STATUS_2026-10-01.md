# STEP STATUS — cycle 2026-10-01T03:04:02+03:00

Generated 2026-10-01T07:54:58+00:00 by a read-only script (no code changed). One row per entry of `core/cycle_map.STEPS` (**66 entries**; `body_scan` appears twice, at 0 and 13).

## How each column was measured

- **Cycle window**: trace `2026-10-01T03_04_02.154470_03_00.jsonl` head `t0` = 2026-10-01T00:04:06+00:00 to `recorder_stop` (t = 1669.4 s) = 2026-10-01T00:31:55.420000+00:00.
- **_run()**: static AST scan of `fast_cycle_runner.py` — every `_run("label", …)` call is assigned to the nearest preceding `beat(name, index)`. Labels in parentheses. Cross-checked against the trace: a `_run` call produces a `step:<label>` span nested in the `stepb:<name>` span; disagreements are flagged.
- **step_inputs.json**: the step name or a `cycle_map.ALIASES` alias is a key of `steps`.
- **Ceiling**: `config/scheduler.json` `step_ceilings_sec` (keyed on step NAME, `_default` otherwise). This is the configured value; `core.step_budget.effective_ceiling` may only tighten it (survival mode p50); the effective value was not computed.
- **Seconds**: `ms` of the `stepb:<name>` span with matching index in the trace.
- **Artifacts**: every path in the step's `produces` list. `IN` = current mtime inside the cycle window; `AFTER` = rewritten since (by a later task), so mtime alone cannot say whether the cycle wrote it — the trace's own write events (`open-w/a`, `os.replace/rename`, in-process only; a subprocess's writes are invisible to the audit hook) are given beside it.
- **Readers**: `tools/ask.py readers` (called in-process as `ask.readers()`), on the FIRST path in `produces`; count = distinct non-test files that read it directly or indirectly; test readers in parentheses. Each call searched 973 .py files. A path reached only through a config file is invisible to it (ask.py's own caveat).
- **Tests**: number of `test/**/*.py` files with a non-docstring string literal containing the step name (or an alias) as a whole token, or an identifier equal to it. Generic names (`boot`, `compass`, `deduction`) may over-count.

| # | index | name | goes through _run() | in step_inputs.json | ceiling s | s last night | promised artifacts: mtime vs cycle; trace write | readers of main output | tests naming it |
|---|---|---|---|---|---|---|---|---|---|
| 0 | -1 | `boot` | no | no | 900 (default) | 2.2 | `memory/heartbeat.json` — MISSING; trace: written by this step | 8 (+6 test) | 19 |
| 1 | 0 | `body_scan` | no | no | 900 (default) | 3.7 | `memory/body_scan_latest.json` — mtime 10-01 00:30Z IN; trace: written by self_observer@17<br>`memory/adaptive_directives.json` — mtime 10-01 00:23Z IN; trace: written by this step | 8 (+2 test) | 13 |
| 2 | 0.05 | `canon_load` | no | no | 900 (default) | 0.5 | `memory/active_canon_frame.txt` — mtime 10-01 00:04Z IN; trace: written by this step | 4 (+3 test) | 3 |
| 3 | 0.1 | `telegram_approvals` | no | no | 900 (default) | 1.1 | `memory/approvals_ledger.jsonl` — mtime 09-26 14:58Z BEFORE; trace: no write<br>`memory/telegram_offset.json` — mtime 09-26 14:58Z BEFORE; trace: no write | 0 | 0 |
| 4 | 0.2 | `brain_briefing` | no | no | 900 (default) | 35.2 | `memory/brain_cycle_plan.json` — mtime 10-01 00:04Z IN; trace: written by this step | 3 (+1 test) | 2 |
| 5 | 0.25 | `notify_patches_and_initiatives` | no | no | 900 (default) | 1.7 | `memory/pending_approvals.json` — mtime 10-01 00:31Z IN; trace: written by compass@25.8 | 0 | 2 |
| 6 | 0.5 | `dependency_check` | no | no | 900 (default) | 3.7 | — (empty `produces`: not verified) | n/a (promises nothing) | 2 |
| 7 | 0.7 | `needs_reanalysis_scan` | no | no | 900 (default) | 0.9 | `snapshots/master/needs_reanalysis_latest.json` — mtime 10-01 00:04Z IN; trace: written by this step | 1 | 1 |
| 8 | 1 | `web_intelligence` | no | yes | 3600 | 0.9 | `memory/web_intelligence` — mtime 09-30 23:17Z BEFORE; trace: no write | 5 | 27 |
| 9 | 2.5 | `global_indicators` | no | yes | 1200 | 137.7 | `snapshots/master/global_indicators_latest.json` — mtime 10-01 00:07Z IN; trace: written by this step<br>`memory/provenance_latest.json` — mtime 10-01 00:07Z IN; trace: written by this step | 13 (+6 test) | 9 |
| 10 | 2.52 | `daily_tier` | yes (daily_tier) | yes | 900 (default) | 2.8 | `memory/daily_tier.jsonl` — mtime 10-01 00:07Z IN; trace: written by this step | 5 (+4 test) | 10 |
| 11 | 2.54 | `sensorium_ingest` | no | yes | 900 (default) | 1.0 | `memory/sensorium` — mtime 10-01 00:07Z IN; trace: written by this step | 2 (+3 test) | 9 |
| 12 | 2.55 | `browser_scout` | no | yes | 900 (default) | 1.5 | `memory/browse_sources` — mtime 10-01 00:07Z IN; trace: written by this step | 1 | 14 |
| 13 | 2.6 | `composers` | no | no | 900 (default) | 49.8 | `memory/composed_indicators.json` — mtime 10-01 00:08Z IN; trace: written by this step<br>`memory/composer_needs.json` — mtime 10-01 00:08Z IN; trace: written by this step | 3 (+2 test) | 12 |
| 14 | 2.7 | `grounding_ledger` | no | no | 900 (default) | 0.4 | `memory/grounding_ledger.jsonl` — mtime 10-01 00:08Z IN; trace: written by this step | 1 | 1 |
| 15 | 3 | `trend_tracker` | no | no | 900 (default) | 0.5 | `memory/trends_latest.json` — mtime 10-01 00:08Z IN; trace: no write | 4 (+2 test) | 9 |
| 16 | 3.5 | `cortexstrategist` | yes (cortex_strategist_agent) | no | 1200 | 39.4 | — (empty `produces`: not verified) | n/a (promises nothing) | 3 |
| 17 | 5 | `civilization_snapshots` | yes (civilization_snapshots_agent) | no | 1800 | 205.1 | `snapshots/civilization` — mtime 10-01 00:12Z IN; trace: written by this step | 1 | 2 |
| 18 | 6 | `planet_snapshots` | yes (planet_snapshots_agent) | no | 1800 | 132.1 | `snapshots/planet` — mtime 10-01 00:14Z IN; trace: written by this step | 0 | 3 |
| 19 | 7 | `human_snapshots` | yes (human_snapshots_agent) | no | 1800 | 53.7 | `snapshots/human` — mtime 10-01 00:15Z IN; trace: written by this step | 1 | 1 |
| 20 | 8 | `cosmos_snapshots` | yes (cosmos_snapshots_agent) | no | 1800 | 47.3 | `snapshots/cosmos` — mtime 10-01 00:16Z IN; trace: written by this step | 0 | 3 |
| 21 | 12 | `update_master` | no | no | 900 (default) | 0.6 | `snapshots/master` — mtime 10-01 00:16Z IN; trace: written by this step | 29 (+8 test) | 0 |
| 22 | 12.3 | `system_hypergraph` | no | no | 900 (default) | 0.5 | — (empty `produces`: not verified) | n/a (promises nothing) | 0 |
| 23 | 12.4 | `scoring_engine` | no | no | 900 (default) | 0.5 | — (empty `produces`: not verified) | n/a (promises nothing) | 14 |
| 24 | 12.42 | `alarm_bands` | yes (alarm_bands) | no | 900 (default) | 2.4 | `memory/alarm_bands_latest.json` — mtime 10-01 00:16Z IN; trace: written by this step | 2 (+3 test) | 5 |
| 25 | 12.45 | `facade_self_check` | no | no | 900 (default) | 0.6 | — (empty `produces`: not verified) | n/a (promises nothing) | 1 |
| 26 | 12.5 | `auto_levels` | no | yes | 900 (default) | 0.4 | `memory/auto_levels.json` — mtime 10-01 00:16Z IN; trace: written by this step | 10 (+2 test) | 5 |
| 27 | 12.55 | `level_reconcile` | yes (level_reconcile) | no | 900 (default) | 2.2 | — (empty `produces`: not verified) | n/a (promises nothing) | 1 |
| 28 | 12.56 | `axis_history` | yes (axis_history) | no | 900 (default) | 2.4 | `memory/axis_observations.jsonl` — mtime 10-01 00:16Z IN; trace: written by this step | 2 (+2 test) | 9 |
| 29 | 12.6 | `goal_score_calculator` | yes (goal_score_calculator) | no | 900 (default) | 2.4 | `memory/goal_score_history.json` — mtime 10-01 00:30Z IN; trace: written by feedback_loop@20 | 9 (+1 test) | 13 |
| 30 | 12.65 | `deduction` | no | no | 900 (default) | 0.4 | `memory/deductions_latest.json` — mtime 10-01 00:16Z IN; trace: written by this step<br>`memory/deduction_rule_stats.json` — mtime 10-01 00:16Z IN; trace: written by this step | 2 | 3 |
| 31 | 12.66 | `constancy_and_constellation` | no | no | 900 (default) | 396.9 | `memory/constancy_latest.json` — mtime 10-01 00:22Z IN; trace: written by this step<br>`memory/constellation_latest.json` — mtime 10-01 00:22Z IN; trace: written by this step | 4 | 1 |
| 32 | 12.68 | `axis_feed` | no | no | 900 (default) | 0.4 | `openclaw_queue/axis_feeds_latest.json` — mtime 10-01 00:22Z IN; trace: written by this step | 0 | 2 |
| 33 | 12.7 | `cognitive_orchestrator` | yes (orchestrator_grounded) | no | 900 (default) | 2.5 | `memory/orchestration_latest.json` — mtime 10-01 00:43Z AFTER; trace: no write | 3 (+1 test) | 1 |
| 34 | 12.75 | `brain_reconsider` | no | no | 900 (default) | 30.2 | `memory/reconsider_latest.json` — mtime 08-25 01:06Z BEFORE; trace: no write | 0 | 2 |
| 35 | 13 | `body_scan` | yes (body_scanner) | no | 900 (default) | 8.4 | `memory/body_scan_latest.json` — mtime 10-01 00:30Z IN; trace: written by self_observer@17 | 8 (+2 test) | 13 |
| 36 | 14 | `growth_planner` | yes (growth_planner) | no | 900 (default) | 19.0 | — (empty `produces`: not verified) | n/a (promises nothing) | 2 |
| 37 | 15.6 | `hyperclaw` | yes (hyperclaw_orchestrator) | no | 1200 | 84.9 | `plans` — mtime 10-01 00:25Z IN; trace: written by this step | 0 (+1 test) | 3 |
| 38 | 15.7 | `hyperclaw_plan` | yes (hyperclaw_plan) | yes | 900 (default) | 2.3 | `memory/improvement_proposals.json` — mtime 10-01 00:30Z IN; trace: written by cortexstrategist@3.5, growth_planner@14, self_observer@17 | 18 (+5 test) | 4 |
| 39 | 15.8 | `github_publish` | yes (github_publisher) | yes | 900 (default) | 52.0 | — (empty `produces`: not verified) | n/a (promises nothing) | 18 |
| 40 | 17 | `self_observer` | yes (self_observer) | yes | 1200 | 267.4 | `memory/improvement_proposals.json` — mtime 10-01 00:30Z IN; trace: written by this step<br>`memory/development_journal.json` — mtime 09-29 00:21Z BEFORE; trace: no write | 18 (+5 test) | 16 |
| 41 | 18 | `self_modifier` | yes (self_modifier) [trace disagrees: no step: span] | yes | 900 (default) | 0.8 | `memory/improvement_proposals.json` — mtime 10-01 00:30Z IN; trace: written by cortexstrategist@3.5, growth_planner@14, self_observer@17<br>`memory/runtime_experiences.json` — mtime 10-01 00:30Z IN; trace: written by this step | 18 (+5 test) | 24 |
| 42 | 19 | `execute_patches` | yes (execute_patches) [trace disagrees: no step: span] | yes | 900 (default) | 0.7 | `memory/development_journal.json` — mtime 09-29 00:21Z BEFORE; trace: no write | 10 (+2 test) | 14 |
| 43 | 20 | `feedback_loop` | yes (feedback_loop) | no | 900 (default) | 3.1 | `memory/feedback_log.json` — mtime 10-01 00:30Z IN; trace: written by this step | 1 | 5 |
| 44 | 20.05 | `resolve_hypotheses` | yes (resolve_hypotheses) | yes | 900 (default) | 2.6 | `memory/hypothesis_resolution_latest.json` — mtime 10-01 00:30Z IN; trace: written by this step | 0 | 3 |
| 45 | 20.07 | `belief_revision` | yes (belief_revision) | no | 900 (default) | 2.4 | `memory/belief_state.json` — mtime 10-01 00:30Z IN; trace: written by this step | 0 | 1 |
| 46 | 20.06 | `hypothesis_intake` | yes (hypothesis_intake) | no | 900 (default) | 2.5 | `memory/hypothesis_intake_latest.json` — mtime 10-01 00:30Z IN; trace: written by this step | 0 | 2 |
| 47 | 20.08 | `output_contracts` | yes (output_contracts) | no | 900 (default) | 2.4 | `memory/output_contracts_latest.json` — mtime 10-01 00:30Z IN; trace: written by this step | 0 | 1 |
| 48 | 20.1 | `measurement_honesty` | yes (measurement_honesty) | no | 900 (default) | 2.4 | `memory/measurement_honesty_latest.json` — mtime 10-01 00:31Z IN; trace: written by this step | 1 | 6 |
| 49 | 20.2 | `resolve_ideas` | yes (resolve_ideas) | no | 900 (default) | 2.6 | `memory/idea_resolutions.jsonl` — mtime 10-01 00:31Z IN; trace: written by this step | 1 (+2 test) | 2 |
| 50 | 21 | `session_update` | yes (session_updater) | no | 900 (default) | 4.2 | — (empty `produces`: not verified) | n/a (promises nothing) | 3 |
| 51 | 22.5 | `data_scout` | yes (data_scout) | no | 1200 | 2.3 | `memory/discovered_data_sources.json` — mtime 09-30 23:17Z BEFORE; trace: no write | 5 (+2 test) | 18 |
| 52 | 23 | `continuous_learning` | no | no | 1200 | 6.8 | `memory/knowledge_base.json` — mtime 10-01 00:31Z IN; trace: written by this step | 2 (+2 test) | 1 |
| 53 | 24 | `merklememory_commit` | no | no | 900 (default) | 0.8 | — (empty `produces`: not verified) | n/a (promises nothing) | 3 |
| 54 | 24.1 | `merkle_verify` | yes (merkle_verify) | no | 900 (default) | 2.4 | `memory/merkle_verify_latest.json` — mtime 10-01 00:31Z IN; trace: written by this step | 1 (+1 test) | 2 |
| 55 | 25 | `training_data_accumulation` | no | no | 900 (default) | 1.4 | — (empty `produces`: not verified) | n/a (promises nothing) | 1 |
| 56 | 25.35 | `metta_column` | yes (metta_column) | no | 900 (default) | 2.7 | `memory/metta_assessment_latest.json` — mtime 10-01 00:31Z IN; trace: written by this step | 3 | 2 |
| 57 | 25.36 | `brain_relay` | yes (brain_relay) | no | 900 (default) | 2.7 | — (empty `produces`: not verified) | n/a (promises nothing) | 2 |
| 58 | 25.38 | `proposal_sla` | yes (proposal_sla) | no | 900 (default) | 2.5 | — (empty `produces`: not verified) | n/a (promises nothing) | 2 |
| 59 | 25.37 | `needs_auth` | yes (needs_auth) | no | 900 (default) | 2.4 | — (empty `produces`: not verified) | n/a (promises nothing) | 2 |
| 60 | 25.43 | `learn_world` | yes (learn_world) | yes | 900 (default) | 4.5 | `memory/backend_order_measured.json` — mtime 10-01 00:31Z IN; trace: written by this step | 0 | 1 |
| 61 | 25.44 | `self_experiment` | yes (self_experiment) | no | 900 (default) | 2.4 | `memory/self_experiments.json` — mtime 09-26 10:28Z BEFORE; trace: no write | 1 (+1 test) | 1 |
| 62 | 25.45 | `self_mirror` | yes (self_mirror) | no | 900 (default) | 2.5 | `memory/self_mirror_latest.json` — mtime 10-01 00:31Z IN; trace: written by this step<br>`memory/self_mirror_log.jsonl` — mtime 10-01 00:31Z IN; trace: written by this step | 1 (+2 test) | 1 |
| 63 | 25.6 | `cycle_report` | no | no | 900 (default) | 1.1 | `output/reports` — mtime 10-01 00:43Z AFTER; trace: written by this step | 0 | 13 |
| 64 | 25.7 | `cortex_scan` | yes (cortex_scan) | no | 900 (default) | 6.6 | `memory/cortex_full_state.json` — mtime 10-01 00:31Z IN; trace: written by this step | 0 (+1 test) | 2 |
| 65 | 25.8 | `compass` | yes (compass) | no | 900 (default) | 6.3 | `memory/compass_latest.json` — mtime 10-01 00:31Z IN; trace: written by this step | 0 | 1 |

## (1) Steps whose promised artifact was NOT written last night

Criterion: mtime not inside the cycle window AND no write event for that path anywhere in the trace.

- #3 `telegram_approvals` (0.1): `memory/approvals_ledger.jsonl` (mtime 09-26 14:58Z BEFORE); `memory/telegram_offset.json` (mtime 09-26 14:58Z BEFORE)
- #8 `web_intelligence` (1): `memory/web_intelligence` (mtime 09-30 23:17Z BEFORE)
- #33 `cognitive_orchestrator` (12.7): `memory/orchestration_latest.json` (mtime 10-01 00:43Z AFTER)
- #34 `brain_reconsider` (12.75): `memory/reconsider_latest.json` (mtime 08-25 01:06Z BEFORE)
- #40 `self_observer` (17): `memory/development_journal.json` (mtime 09-29 00:21Z BEFORE)
- #42 `execute_patches` (19): `memory/development_journal.json` (mtime 09-29 00:21Z BEFORE)
- #51 `data_scout` (22.5): `memory/discovered_data_sources.json` (mtime 09-30 23:17Z BEFORE)
- #61 `self_experiment` (25.44): `memory/self_experiments.json` (mtime 09-26 10:28Z BEFORE)

Steps with an empty `produces` list cannot appear here — for them nothing is promised, which `cycle_map` itself says means 'not known', not 'produces nothing'.

## (2) Steps whose main output has zero (non-test) readers

**This list is `tools/ask.py readers` output and is NOT verified. It contains at least one KNOWN FALSE NEGATIVE:** `memory/backend_order_measured.json` (learn_world) IS read, by `core/groq_backend.py:474` `json.loads((path or MEASURED_ORDER).read_text(...))` - ask.py does not follow a path through an `or` expression. Directory outputs (`snapshots/planet`, `snapshots/cosmos`, `plans`, `output/reports`) are usually read by globbing a variable, which ask.py cannot see either. Treat every entry as 'no reader found by ask.py', not 'no reader'.

- #3 `telegram_approvals` (0.1): `memory/approvals_ledger.jsonl`
- #5 `notify_patches_and_initiatives` (0.25): `memory/pending_approvals.json`
- #18 `planet_snapshots` (6): `snapshots/planet`
- #20 `cosmos_snapshots` (8): `snapshots/cosmos`
- #32 `axis_feed` (12.68): `openclaw_queue/axis_feeds_latest.json`
- #34 `brain_reconsider` (12.75): `memory/reconsider_latest.json`
- #37 `hyperclaw` (15.6): `plans` — read only by tests: test/test_parse_plan_steps.py
- #44 `resolve_hypotheses` (20.05): `memory/hypothesis_resolution_latest.json`
- #45 `belief_revision` (20.07): `memory/belief_state.json`
- #46 `hypothesis_intake` (20.06): `memory/hypothesis_intake_latest.json`
- #47 `output_contracts` (20.08): `memory/output_contracts_latest.json`
- #60 `learn_world` (25.43): `memory/backend_order_measured.json`
- #63 `cycle_report` (25.6): `output/reports`
- #64 `cortex_scan` (25.7): `memory/cortex_full_state.json` — read only by tests: test/test_scanner_never_invents_a_score.py
- #65 `compass` (25.8): `memory/compass_latest.json`

## (3) Retire-list steps that still run, with readers named

- `auto_levels` (12.5) — ran last night, 0.4 s, status OK. Main output: `memory/auto_levels.json`.
  - readers (non-test): `agents/core/cortex_core_agent.py`, `agents/core/goal_planner.py`, `agents/core/self_modifier.py`, `core/deduction.py`, `core/level_reconciler.py`, `memory/auto_level.py`, `memory/body_scan.py`, `memory/continuous_learner.py`, `memory/existence_model.py`, `memory/semantic_memory.py`
  - test readers: `test/test_composer_matches_target.py`, `test/test_level_reconciler.py`
- `growth_planner` (14) — ran last night, 19.0 s, status OK. Main output: none promised.
  - written in its span last night (trace): `8`, `attestation/attest.jsonl`, `attestation/chain.head`, `attestation/chain.tmp`, `memory/cycle_resume.json`, `memory/cycle_resume.json.tmp`, `memory/cycle_resume.jsonl`, `memory/divergence_log.jsonl`, `memory/heartbeat.json`, `memory/homeostasis_state.json`, `memory/homeostasis_state.json.tmp`, `memory/improvement_proposals.json`, `memory/llm_provenance.jsonl`, `memory/step_contract_baseline.json`, `memory/step_contract_latest.json`, `snapshots/body/growth_plan_latest.json`
    - `attestation/attest.jsonl` readers (non-test): `core/notary.py`
    - `attestation/chain.head` readers (non-test): `core/notary.py`
    - `memory/cycle_resume.json` readers (non-test): **none**
    - `memory/cycle_resume.jsonl` readers (non-test): `scripts/verify_checkpoint_map.py`; test: test/test_cycle_checkpoint_resume.py
    - `memory/divergence_log.jsonl` readers (non-test): `core/cycle_report.py`, `edges_runner.py`
    - `memory/homeostasis_state.json` readers (non-test): `cockpit/entropy.py`, `core/homeostasis.py`, `core/survival_gate.py`
    - `memory/improvement_proposals.json` readers (non-test): `_check_proposals.py`, `_clean_proposals.py`, `_diag.py`, `agents/core/feedback_loop.py`, `agents/core/self_modifier.py`, `agents/core/self_observer.py`, `agents/core/self_observer_backup.py`, `core/extra_calls_ledger.py`, `core/proposal_gate.py`, `core/proposal_intake.py`, `core/self_experiment.py`, `cortex_approval_server.py`, `cortex_proposal_executor.py`, `experiments/prophecy/goal_prophecy.py`, `fast_cycle_runner.py`, `initiative_tracker.py`, `memory/proposal_archive.py`, `predictor.py`; test: test/test_initiative_hygiene.py, test/test_proposal_archive.py, test/test_proposal_required_fields.py, test/test_self_experiment.py, test/test_stagnation_priority.py
    - `memory/llm_provenance.jsonl` readers (non-test): `core/llm_door.py`, `core/phase_report.py`, `tools/daily_board.py`; test: test/test_consult_paid_refusal_is_named.py, test/test_gemini_budget_and_usage.py, test/test_provenance_model_id.py
    - `memory/step_contract_baseline.json` readers (non-test): `core/step_budget.py`, `tools/step_audit.py`
    - `memory/step_contract_latest.json` readers (non-test): `core/flow_score.py`, `core/step_contract.py`, `supervisor.py`, `tools/cycle_step_audit.py`, `tools/cycle_watch.py`, `tools/step_contracts.py`; test: test/test_flow_score.py, test/test_kill_policy_wiring.py, test/test_needle_is_integrity.py, test/test_step_contracts.py, test/test_step_window.py
    - `snapshots/body/growth_plan_latest.json` readers (non-test): `fast_cycle_runner.py`
- `session_update` (21) — ran last night, 4.2 s, status OK. Main output: none promised.
  - written in its span last night (trace): `8`, `attestation/attest.jsonl`, `attestation/chain.head`, `attestation/chain.tmp`, `memory/cycle_resume.json`, `memory/cycle_resume.json.tmp`, `memory/cycle_resume.jsonl`, `memory/divergence_log.jsonl`, `memory/heartbeat.json`, `memory/homeostasis_state.json`, `memory/homeostasis_state.json.tmp`, `memory/session_2026-10-01.json`, `memory/step_contract_baseline.json`, `memory/step_contract_latest.json`
    - `attestation/attest.jsonl` readers (non-test): `core/notary.py`
    - `attestation/chain.head` readers (non-test): `core/notary.py`
    - `memory/cycle_resume.json` readers (non-test): **none**
    - `memory/cycle_resume.jsonl` readers (non-test): `scripts/verify_checkpoint_map.py`; test: test/test_cycle_checkpoint_resume.py
    - `memory/divergence_log.jsonl` readers (non-test): `core/cycle_report.py`, `edges_runner.py`
    - `memory/homeostasis_state.json` readers (non-test): `cockpit/entropy.py`, `core/homeostasis.py`, `core/survival_gate.py`
    - `memory/session_2026-10-01.json` readers (non-test): **none**
    - `memory/step_contract_baseline.json` readers (non-test): `core/step_budget.py`, `tools/step_audit.py`
    - `memory/step_contract_latest.json` readers (non-test): `core/flow_score.py`, `core/step_contract.py`, `supervisor.py`, `tools/cycle_step_audit.py`, `tools/cycle_watch.py`, `tools/step_contracts.py`; test: test/test_flow_score.py, test/test_kill_policy_wiring.py, test/test_needle_is_integrity.py, test/test_step_contracts.py, test/test_step_window.py
- `cortex_scan` (25.7) — ran last night, 6.6 s, status OK. Main output: `memory/cortex_full_state.json`.
  - readers (non-test): **none**
  - test readers: `test/test_scanner_never_invents_a_score.py`

Note on (3): the "written in its span" lists include writes every step makes through the runner's own
wrappers (attestation/*, memory/heartbeat.json, memory/step_contract_*, memory/cycle_resume*,
memory/homeostasis_state.json, memory/divergence_log.jsonl, memory/llm_provenance.jsonl). The step's OWN
outputs are: growth_planner -> `snapshots/body/growth_plan_latest.json` (reader: `fast_cycle_runner.py`) and
`memory/improvement_proposals.json` (many readers); session_update -> `memory/session_2026-10-01.json`
(no reader found by ask.py). The path `8` is a relative write recorded by the trace as-is (cwd-relative
file named "8"), not investigated.
