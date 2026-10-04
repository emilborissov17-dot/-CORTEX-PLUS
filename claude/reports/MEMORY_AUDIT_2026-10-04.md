# MEMORY AUDIT — 4 Oct 2026 (command C-MEM-1, read-only, facts only)

## OPEN ITEMS

* **Tests and my own tools write live memory.** While every CORTEX task was Disabled, `memory/blackbox.jsonl` got rows
  at 3 Oct 18:56–19:00 UTC from pids of my C-GUARD-1 suite run (`earning_verifier`, and `fast_cycle_runner.py --from
  D_SCORE` start/exit at 19:00:48); `memory/expression_stream.jsonl` (3 Oct 18:41) and `memory/somatic_history.jsonl`
  (3 Oct 18:38) were written in the same window; `memory/night_events.jsonl` gets a `DETACHED_EXIT` row from
  tools/launch_detached.ps1's watchdog for each detached job (last: 4 Oct 01:57, this audit's own Step 2). Cause:
  those writers default to memory/ paths. Decision: none taken here (this command only reads). Action: listed for Emil.
* **The reader/writer classes are approximate where marked.** `tools/ask.py readers` matches whole path segments, so a
  read through a path variable (e.g. `d / "brain_needs.json"`) is listed as "named, read not classified"; writer counts
  are grep candidates (the file names the store AND contains a write call) united with ask.py's tagged writes — they
  over-include. "unclear" is printed instead of a guess, as ordered.

## Step 0 — before anything

HEAD `8ddf8e2` (the C-VISION-2 commit). `git status --short | wc -l` = 1168. Scheduled tasks named CORTEX*: 12, all
**Disabled** (Approvals, MorningDigest, OpenClaw, Prophecy, Pulse, ResolveForward, SignedSchedule, SuiteFullRun,
Supervisor, TriggerWatchdog, Turns, WarmCore). EXPECTED: all Disabled — OBSERVED: as expected.

## Step 1 — inventory of memory/ and atoms/

EXPECTED: statements.jsonl well over 200,000 rows; space/base.metta present; most CYCLE-HISTORY last written on or
before 2 Oct. OBSERVED: memory/ has 470 top-level entries (6,713 files recursively); `statements.jsonl` 264,183,168
bytes, not opened, **297,156 rows** by `wc -l`; `space/base.metta` present (264,540 lines); CYCLE-HISTORY data files
last written 29 Sep – 2 Oct (proposal_archive.py, 3 Oct 05:55, is a code file the name pattern matches). Group counts:
KNOWLEDGE 11 (+7 atoms/ entries), PROOF 6, BRAIN 16, CYCLE-HISTORY 8, OTHER 415.

#### all entries
| entry | group | bytes | rows (.jsonl) | last write UTC | age d |
|---|---|---|---|---|---|
| __init__.py | OTHER | 0 |  | 2026-05-01 11:26 | 155.6 |
| __pycache__/ | OTHER | 524,802 | 39 files | 2026-10-03 15:58 | 0.4 |
| _axis_map_verification.json | OTHER | 30,925 |  | 2026-08-03 13:08 | 61.5 |
| _mem_trace.jsonl | OTHER | 1,278,019 | 2836 | 2026-08-21 14:41 | 43.5 |
| _mem_trace.STOP | OTHER | 0 |  | 2026-08-21 14:41 | 43.5 |
| _sdg_resolved.json | OTHER | 3,698 |  | 2026-08-03 13:15 | 61.5 |
| _sdg_world_sweep.json | OTHER | 20,770 |  | 2026-08-03 13:13 | 61.5 |
| _source_health.json | OTHER | 22,457 |  | 2026-08-03 14:40 | 61.5 |
| _world_anchor_candidates.json | OTHER | 7,943 |  | 2026-08-03 13:17 | 61.5 |
| acled_credentials.txt | OTHER | 44 |  | 2026-09-18 13:58 | 15.5 |
| acled_token.json | OTHER | 1,654 |  | 2026-09-18 14:22 | 15.5 |
| active_canon_frame.txt | OTHER | 1,295 |  | 2026-10-02 00:04 | 2.1 |
| adaptive_directives.json | OTHER | 382 |  | 2026-10-02 00:20 | 2.1 |
| agents/ | OTHER | 10,116 | 13 files | 2026-10-01 20:19 | 2.2 |
| alarm_bands_latest.json | OTHER | 6,859 |  | 2026-10-02 00:12 | 2.1 |
| alarm_sent.json | OTHER | 17,828 |  | 2026-10-02 04:00 | 1.9 |
| alerts_log.json | OTHER | 445 |  | 2026-07-21 06:06 | 74.8 |
| approval_queue.json | OTHER | 5,855 |  | 2026-04-13 07:27 | 173.8 |
| approvals_ledger.jsonl | OTHER | 35,714 | 79 | 2026-09-26 14:58 | 7.4 |
| auto_level.py | OTHER | 11,428 |  | 2026-06-23 22:06 | 102.2 |
| auto_levels.json | OTHER | 6,874 |  | 2026-10-02 00:12 | 2.1 |
| auto_threshold.py | OTHER | 3,296 |  | 2026-05-01 11:26 | 155.6 |
| autonomic_pulse.py | OTHER | 4,883 |  | 2026-10-03 05:33 | 0.8 |
| axis_history.json | CYCLE-HISTORY | 1,060,720 |  | 2026-10-02 00:07 | 2.1 |
| axis_history_annual.json | CYCLE-HISTORY | 109,456 |  | 2026-10-02 09:00 | 1.7 |
| axis_observations.jsonl | OTHER | 94,025 | 442 | 2026-10-02 00:12 | 2.1 |
| backend_order_measured.json | OTHER | 147 |  | 2026-10-02 11:11 | 1.6 |
| backups/ | OTHER | 0 | 0 files | 2026-03-11 11:16 | 206.6 |
| battery_registry.json | OTHER | 1,722 |  | 2026-08-04 00:42 | 61.0 |
| belief_state.json | OTHER | 1,477 |  | 2026-10-02 00:29 | 2.1 |
| biodiversity_measure.json | OTHER | 67 |  | 2026-08-05 06:40 | 59.8 |
| biodiversity_measurements.json | OTHER | 487 |  | 2026-08-03 08:25 | 61.7 |
| biodiversity_observations.json | OTHER | 226 |  | 2026-08-06 07:04 | 58.8 |
| biodiversity_reserves.json | OTHER | 1,265 |  | 2026-08-06 07:04 | 58.8 |
| biodiversity_stats.json | OTHER | 124 |  | 2026-08-04 00:42 | 61.0 |
| blackbox.jsonl | PROOF | 537,818 | 3027 | 2026-10-03 19:00 | 0.3 |
| body_scan.py | OTHER | 16,484 |  | 2026-10-03 10:14 | 0.6 |
| body_scan_latest.json | OTHER | 3,039 |  | 2026-10-02 00:27 | 2.1 |
| body_sensorium/ | OTHER | 2,417,749 | 16 files | 2026-10-02 11:19 | 1.6 |
| brain_briefings.jsonl | BRAIN | 760,660 | 37 | 2026-10-02 10:28 | 1.6 |
| brain_cycle_plan.json | BRAIN | 528 |  | 2026-10-02 00:04 | 2.1 |
| brain_cycle_reviews.jsonl | BRAIN | 19,047 | 21 | 2026-10-01 00:35 | 3.0 |
| brain_journal.jsonl | BRAIN | 3,136,429 | 3441 | 2026-10-02 10:36 | 1.6 |
| brain_needs.json | BRAIN | 133,383 |  | 2026-10-02 11:19 | 1.6 |
| brain_needs_log.jsonl | BRAIN | 2,493 | 6 | 2026-10-02 10:07 | 1.7 |
| brain_needs_refused.jsonl | BRAIN | 2,704 | 4 | 2026-10-02 10:30 | 1.6 |
| brain_probe/ | BRAIN | 227,798,845 | 2 files | 2026-09-17 19:28 | 16.3 |
| brain_relay_cursor.json | BRAIN | 29,085 |  | 2026-10-02 00:30 | 2.1 |
| brain_stance.json | BRAIN | 573 |  | 2026-09-25 06:58 | 8.8 |
| brain_step_log.jsonl | BRAIN | 2,431,128 | 4310 | 2026-09-25 06:58 | 8.8 |
| browse_sources/ | OTHER | 2,054 | 6 files | 2026-10-02 00:06 | 2.1 |
| budget.json | OTHER | 29 |  | 2026-05-07 10:20 | 149.6 |
| bumblebee_population_log.json | OTHER | 15 |  | 2026-08-04 09:17 | 60.7 |
| canon_invariants.json | OTHER | 19 |  | 2026-09-12 08:21 | 21.7 |
| card_refusals.jsonl | PROOF | 28,198 | 28 | 2026-10-01 18:00 | 2.3 |
| catalog_probe.json | OTHER | 2,857 |  | 2026-08-15 16:54 | 49.4 |
| causal_log.json | OTHER | 48,915 |  | 2026-09-24 13:28 | 9.5 |
| chromadb/ | OTHER | 15,156,896 | 6 files | 2026-10-02 00:43 | 2.0 |
| civic_participation.json | OTHER | 26 |  | 2026-05-04 09:07 | 152.7 |
| civilization_monitoring.json | OTHER | 26 |  | 2026-05-04 09:18 | 152.7 |
| claude_query_proposals.json | OTHER | 2,476 |  | 2026-05-16 17:52 | 140.3 |
| clean_nights.json | OTHER | 823 |  | 2026-10-02 04:00 | 1.9 |
| climate_data.json | OTHER | 39 |  | 2026-05-04 09:18 | 152.7 |
| cockpit_forks_cache.json | OTHER | 159 |  | 2026-08-22 14:47 | 42.5 |
| cockpit_phase_seen.json | OTHER | 10,075 |  | 2026-09-24 13:37 | 9.5 |
| cockpit_terminal.log | OTHER | 892,969 |  | 2026-09-14 10:21 | 19.6 |
| collector_instrumentation.json | OTHER | 991 |  | 2026-10-02 08:58 | 1.7 |
| collector_queries.json | OTHER | 51,583 |  | 2026-10-02 00:58 | 2.0 |
| collector_rotation.json | OTHER | 3,305 |  | 2026-10-02 08:58 | 1.7 |
| collector_runs.jsonl | OTHER | 477,470 | 345 | 2026-10-02 08:58 | 1.7 |
| collector_runs.log | OTHER | 1,501,253 |  | 2026-10-02 08:58 | 1.7 |
| collector_seen.json | OTHER | 69,389 |  | 2026-10-01 18:20 | 2.3 |
| collectors/ | OTHER | 28,546 | 9 files | 2026-10-01 23:19 | 2.1 |
| compass_latest.json | OTHER | 5,972 |  | 2026-10-02 00:30 | 2.1 |
| composed_indicators.json | OTHER | 175,225 |  | 2026-10-02 00:07 | 2.1 |
| composer_needs.json | OTHER | 44,495 |  | 2026-10-02 00:07 | 2.1 |
| composer_state/ | OTHER | 248,643 | 25 files | 2026-10-02 00:07 | 2.1 |
| consolidation_latest.json | OTHER | 5,920 |  | 2026-10-01 23:10 | 2.1 |
| consolidation_queue.json | OTHER | 1,346 |  | 2026-10-01 23:10 | 2.1 |
| constancy_bands_latest.json | OTHER | 13,503 |  | 2026-10-02 00:12 | 2.1 |
| constancy_latest.json | OTHER | 20,191 |  | 2026-10-02 00:18 | 2.1 |
| constellation_latest.json | OTHER | 314 |  | 2026-10-02 00:19 | 2.1 |
| context_injector.py | OTHER | 6,536 |  | 2026-05-01 11:26 | 155.6 |
| continuous_learner.py | OTHER | 23,067 |  | 2026-08-28 19:19 | 36.3 |
| cortex_full_state.json | OTHER | 9,564 |  | 2026-10-02 00:30 | 2.1 |
| counterfactual_probe.jsonl | OTHER | 120,993 | 161 | 2026-10-02 09:58 | 1.7 |
| counterfactual_probe_by_model.json | OTHER | 881 |  | 2026-09-12 07:12 | 21.8 |
| counterfactual_probe_by_model_2026-09-11.json | OTHER | 3,297 |  | 2026-09-11 22:22 | 22.1 |
| counterfactual_probe_by_model_2026-09-12_l1b_run1.json | OTHER | 1,692 |  | 2026-09-12 07:06 | 21.8 |
| counterfactual_probe_by_model_2026-09-12_l1b_run2.json | OTHER | 881 |  | 2026-09-12 07:12 | 21.8 |
| counterfactual_probe_by_model_2026-09-12_lean.json | OTHER | 2,415 |  | 2026-09-11 22:47 | 22.1 |
| counterfactual_probe_latest.json | OTHER | 558 |  | 2026-10-02 09:58 | 1.7 |
| cycle_exit.json | OTHER | 438 |  | 2026-09-24 06:39 | 9.8 |
| cycle_exits.jsonl | OTHER | 11,902 | 30 | 2026-09-22 01:45 | 12.0 |
| cycle_graph_latest.json | OTHER | 3,368 |  | 2026-08-15 11:26 | 49.6 |
| cycle_knowledge_log.json | OTHER | 21,763 |  | 2026-10-02 00:30 | 2.1 |
| cycle_logs/ | OTHER | 2,037,228 | 39 files | 2026-10-02 00:44 | 2.0 |
| cycle_origin.json | OTHER | 259 |  | 2026-10-02 00:04 | 2.1 |
| cycle_resume.json | OTHER | 183 |  | 2026-10-02 00:30 | 2.1 |
| cycle_resume.jsonl | OTHER | 653,445 | 3766 | 2026-10-02 00:30 | 2.1 |
| cycle_trace/ | OTHER | 11,383,566 | 35 files | 2026-10-02 00:30 | 2.1 |
| daily_tier.jsonl | OTHER | 602,571 | 3568 | 2026-10-02 00:06 | 2.1 |
| data.json | OTHER | 120 |  | 2026-05-07 10:21 | 149.6 |
| declined_approvals.json | OTHER | 200 |  | 2026-08-23 16:40 | 41.4 |
| deduction_rule_stats.json | OTHER | 480 |  | 2026-10-02 00:12 | 2.1 |
| deductions_latest.json | OTHER | 1,164 |  | 2026-10-02 00:12 | 2.1 |
| development_journal.json | CYCLE-HISTORY | 139,872 |  | 2026-09-29 00:21 | 5.1 |
| diagnosis_history.jsonl | OTHER | 32,901 | 26 | 2026-09-24 06:58 | 9.8 |
| diagnosis_latest.json | OTHER | 1,237 |  | 2026-09-24 06:58 | 9.8 |
| discarded_candidates.jsonl | OTHER | 22,820 | 43 | 2026-10-01 23:19 | 2.1 |
| discovered_data_sources.json | OTHER | 28,685 |  | 2026-10-01 23:19 | 2.1 |
| discovery_leads.jsonl | OTHER | 3,823 | 11 | 2026-09-18 01:31 | 16.0 |
| disk_actuator_log.jsonl | OTHER | 58,795 | 1 | 2026-08-27 20:18 | 37.2 |
| distrust_ledger.jsonl | OTHER | 2,252 | 8 | 2026-09-13 00:25 | 21.1 |
| divergence_log.jsonl | OTHER | 4,991,612 | 4513 | 2026-10-02 00:30 | 2.1 |
| drawdown_log.json | OTHER | 138 |  | 2026-08-08 06:51 | 56.8 |
| dreaming/ | OTHER | 268 | 3 files | 2026-09-10 05:45 | 23.8 |
| dynamic_thresholds.json | OTHER | 12,822 |  | 2026-05-09 06:01 | 147.8 |
| education_literacy_progress.json | OTHER | 237 |  | 2026-07-22 00:56 | 74.0 |
| embed_index/ | OTHER | 21,586,936 | 9 files | 2026-09-17 13:06 | 16.5 |
| embed_index_t1/ | OTHER | 459,940 | 3 files | 2026-09-17 13:47 | 16.5 |
| embeddings_cache.json | OTHER | 84,488,997 |  | 2026-09-17 13:27 | 16.5 |
| energy_price_data.json | OTHER | 21 |  | 2026-08-13 07:31 | 51.8 |
| energy_price_measurements.json | OTHER | 181 |  | 2026-08-11 08:49 | 53.7 |
| energy_price_report.json | OTHER | 148 |  | 2026-08-13 07:31 | 51.8 |
| energy_review_result.json | OTHER | 34 |  | 2026-08-22 01:28 | 43.0 |
| energy_storage_plan.json | OTHER | 1,297 |  | 2026-07-30 00:42 | 66.0 |
| energy_storage_proposals.json | OTHER | 1,088 |  | 2026-07-29 06:24 | 66.8 |
| energy_storage_state.json | OTHER | 587 |  | 2026-07-21 06:06 | 74.8 |
| energy_tariff_projection.json | OTHER | 107 |  | 2026-08-14 06:54 | 50.8 |
| exemplar_audit_latest.json | OTHER | 5,252 |  | 2026-08-23 08:39 | 41.7 |
| existence_latest.json | OTHER | 1,610 |  | 2026-10-02 00:27 | 2.1 |
| existence_ledger.jsonl | PROOF | 175,160 | 421 | 2026-10-02 00:30 | 2.1 |
| existence_ledger.py | PROOF | 19,526 |  | 2026-09-24 07:36 | 9.8 |
| existence_model.py | OTHER | 8,788 |  | 2026-08-17 11:16 | 47.6 |
| expectations.jsonl | OTHER | 26,448 | 348 | 2026-10-02 10:33 | 1.6 |
| expression_quarantine/ | OTHER | 60,598 | 27 files | 2026-10-02 00:41 | 2.0 |
| expression_stream.jsonl | OTHER | 3,221,320 | 8712 | 2026-10-03 18:41 | 0.3 |
| extra_calls_log.jsonl | OTHER | 20,958 | 44 | 2026-10-02 00:30 | 2.1 |
| factcheck_config.json | OTHER | 191 |  | 2026-08-22 01:28 | 43.0 |
| factcheck_result.json | OTHER | 48 |  | 2026-08-22 01:28 | 43.0 |
| fair_civilization_agent_state.json | OTHER | 542 |  | 2026-07-21 06:06 | 74.8 |
| farm_socio.json | OTHER | 13 |  | 2026-08-13 07:31 | 51.8 |
| feature_proposals.jsonl | OTHER | 21,549 | 39 | 2026-10-02 10:36 | 1.6 |
| feature_registry.json | OTHER | 213 |  | 2026-09-12 09:13 | 21.7 |
| feedback_log.json | OTHER | 18,256 |  | 2026-10-02 00:29 | 2.1 |
| fetch_parking.json | OTHER | 10,463 |  | 2026-10-01 18:00 | 2.3 |
| filter_deployment_config.json | OTHER | 222 |  | 2026-08-22 01:28 | 43.0 |
| first_bet/ | OTHER | 48,610 | 5 files | 2026-09-07 12:18 | 26.6 |
| free_expression.jsonl | OTHER | 82,461 | 20 | 2026-09-05 21:04 | 28.2 |
| goal_alignment.py | OTHER | 870 |  | 2026-05-01 11:26 | 155.6 |
| goal_axis_history.json | OTHER | 4,715 |  | 2026-09-19 11:32 | 14.6 |
| goal_impact_inbox/ | OTHER | 17,647 | 5 files | 2026-09-03 07:44 | 30.8 |
| goal_score_history.json | CYCLE-HISTORY | 92,540 |  | 2026-10-02 00:29 | 2.1 |
| governance_institutions.json | OTHER | 39 |  | 2026-05-04 09:18 | 152.7 |
| government_processes.json | OTHER | 501 |  | 2026-05-04 12:48 | 152.5 |
| grid_current_data.json | OTHER | 13 |  | 2026-08-12 07:34 | 52.8 |
| grid_progress.json | OTHER | 49 |  | 2026-08-09 00:42 | 56.0 |
| grid_roadmap.json | OTHER | 126 |  | 2026-08-09 00:42 | 56.0 |
| grid_state.json | OTHER | 339 |  | 2026-08-09 00:42 | 56.0 |
| grid_upgrade_plan.json | OTHER | 20 |  | 2026-08-12 07:34 | 52.8 |
| grid_upgrade_roadmap.json | OTHER | 2 |  | 2026-08-15 00:54 | 50.0 |
| ground_sensors.json | OTHER | 12 |  | 2026-07-31 07:34 | 64.8 |
| grounding_ledger.jsonl | OTHER | 1,001,566 | 98 | 2026-10-02 00:07 | 2.1 |
| groundwater_monitoring.json | OTHER | 20 |  | 2026-08-09 00:43 | 56.0 |
| groundwater_quotas.json | OTHER | 20 |  | 2026-08-06 07:05 | 58.8 |
| groundwater_report.json | OTHER | 63 |  | 2026-08-09 00:43 | 56.0 |
| groundwater_sensors.json | OTHER | 512 |  | 2026-08-04 00:42 | 61.0 |
| heartbeat.py | OTHER | 17,507 |  | 2026-10-03 09:59 | 0.7 |
| homeostasis_latest.json | OTHER | 732 |  | 2026-10-02 10:38 | 1.6 |
| homeostasis_state.json | OTHER | 9,756 |  | 2026-10-02 00:30 | 2.1 |
| hook_test.log | OTHER | 104,873 |  | 2026-10-04 01:46 | 0.0 |
| human_channel_state.json | OTHER | 201 |  | 2026-10-02 00:04 | 2.1 |
| human_input_queue.db | OTHER | 12,288 |  | 2026-08-27 13:54 | 37.5 |
| hypothesis_intake_latest.json | OTHER | 1,452 |  | 2026-10-02 00:29 | 2.1 |
| hypothesis_resolution_latest.json | OTHER | 3,916 |  | 2026-10-02 00:29 | 2.1 |
| idea_resolutions.jsonl | OTHER | 439,106 | 494 | 2026-10-02 00:29 | 2.1 |
| idea_stream.jsonl | OTHER | 849,290 | 1062 | 2026-10-01 23:10 | 2.1 |
| improvement_plan_latest.json | OTHER | 1,798 |  | 2026-04-13 17:25 | 173.3 |
| improvement_proposals.json | OTHER | 30,123 |  | 2026-10-02 00:29 | 2.1 |
| improvement_proposals_archive.json | CYCLE-HISTORY | 30,619 |  | 2026-07-23 07:21 | 72.8 |
| intel.db | OTHER | 47,046,656 |  | 2026-10-02 08:35 | 1.7 |
| international_agreements.json | OTHER | 726 |  | 2026-08-12 07:34 | 52.8 |
| interval_head_curve.json | OTHER | 2,338 |  | 2026-08-28 14:51 | 36.5 |
| interval_head_runs.jsonl | OTHER | 21,541 | 8 | 2026-08-28 14:51 | 36.5 |
| interval_head_weights.npz | OTHER | 4,576,993 |  | 2026-08-28 14:51 | 36.5 |
| interval_head_weights_prev.npz | OTHER | 4,555,368 |  | 2026-08-28 14:37 | 36.5 |
| knowledge/ | KNOWLEDGE | 874,463,457 | 6 files | 2026-10-02 11:19 | 1.6 |
| knowledge_base.json | CYCLE-HISTORY | 132,115 |  | 2026-10-02 00:30 | 2.1 |
| l1_ollama_holdout.json | OTHER | 853 |  | 2026-09-11 22:13 | 22.1 |
| l1_real_prompt_blocks.json | OTHER | 4,785 |  | 2026-09-11 21:36 | 22.2 |
| language_quarantine.json | OTHER | 1,323 |  | 2026-10-02 00:30 | 2.1 |
| last_attempted_cycle_id.txt | OTHER | 32 |  | 2026-10-02 00:04 | 2.1 |
| last_cycle_id.txt | OTHER | 32 |  | 2026-10-02 00:30 | 2.1 |
| learn_world_latest.json | OTHER | 558 |  | 2026-09-20 01:31 | 14.0 |
| learner_progress.jsonl | OTHER | 3,739 | 21 | 2026-10-02 11:11 | 1.6 |
| learner_state.json | OTHER | 1,898 |  | 2026-10-02 00:30 | 2.1 |
| level_corrections.jsonl | OTHER | 287,621 | 668 | 2026-10-02 00:12 | 2.1 |
| live_monitor_latest.json | OTHER | 1,056 |  | 2026-08-30 09:17 | 34.7 |
| live_monitor_runs.jsonl | OTHER | 961 | 1 | 2026-08-30 09:17 | 34.7 |
| llm_leg_state.json | OTHER | 251 |  | 2026-10-03 05:11 | 0.9 |
| llm_provenance.jsonl | OTHER | 4,973,169 | 13152 | 2026-10-03 09:41 | 0.7 |
| llm_timeouts.json | OTHER | 841 |  | 2026-10-03 19:04 | 0.3 |
| local_brain_test.json | OTHER | 2,122 |  | 2026-08-15 08:41 | 49.7 |
| maintenance_state.json | OTHER | 2,901 |  | 2026-10-01 17:54 | 2.3 |
| measurement_honesty_latest.json | OTHER | 18,865 |  | 2026-10-02 00:29 | 2.1 |
| merkle_roots.jsonl | PROOF | 10,731 | 24 | 2026-10-02 00:30 | 2.1 |
| merkle_verify_latest.json | PROOF | 195 |  | 2026-10-02 00:30 | 2.1 |
| metta_assessment_latest.json | OTHER | 11,882 |  | 2026-10-02 00:30 | 2.1 |
| metta_bridge_check.json | OTHER | 393 |  | 2026-10-02 20:44 | 1.2 |
| metta_forward_F-001.json | OTHER | 3,178 |  | 2026-09-27 09:24 | 6.7 |
| metta_forward_F-002.json | OTHER | 3,150 |  | 2026-09-27 09:25 | 6.7 |
| metta_forward_F-003.json | OTHER | 3,178 |  | 2026-09-27 09:25 | 6.7 |
| metta_forward_F-004.json | OTHER | 3,190 |  | 2026-09-27 09:25 | 6.7 |
| micro_cycle_contract_baseline.json | OTHER | 2,686 |  | 2026-08-21 11:20 | 43.6 |
| micro_cycle_contract_latest.json | OTHER | 2,656 |  | 2026-08-21 11:20 | 43.6 |
| micro_cycle_latest.json | OTHER | 1,564 |  | 2026-08-21 11:20 | 43.6 |
| micro_cycle_log.jsonl | OTHER | 154 | 2 | 2026-08-21 11:20 | 43.6 |
| mining_licenses.json | OTHER | 16 |  | 2026-07-22 00:56 | 74.0 |
| mining_registry.json | OTHER | 339 |  | 2026-07-19 15:17 | 76.4 |
| mirror_read_latest.json | OTHER | 820 |  | 2026-10-02 00:34 | 2.0 |
| model_window.json | OTHER | 897 |  | 2026-10-02 00:30 | 2.1 |
| monitoring_result.json | OTHER | 121 |  | 2026-08-22 01:28 | 43.0 |
| morning_digest_log.jsonl | OTHER | 1,136 | 8 | 2026-10-02 04:00 | 1.9 |
| morning_digest_run.log | OTHER | 6,840 |  | 2026-10-02 06:05 | 1.8 |
| my_result.json | OTHER | 120 |  | 2026-08-14 06:54 | 50.8 |
| needs.json | BRAIN | 44,861 |  | 2026-10-01 14:56 | 2.5 |
| needs_auth_asked.json | BRAIN | 4 |  | 2026-10-02 00:30 | 2.1 |
| needs_brief.md | BRAIN | 73,489 |  | 2026-10-02 00:30 | 2.1 |
| needs_push_state.json | BRAIN | 140 |  | 2026-10-02 00:30 | 2.1 |
| night_events.jsonl | OTHER | 732,560 | 1366 | 2026-10-04 00:37 | 0.0 |
| notify_channel.json | OTHER | 119 |  | 2026-07-30 09:50 | 65.7 |
| observation_log.jsonl | OTHER | 6,135 | 25 | 2026-10-01 18:00 | 2.3 |
| observation_retractions.jsonl | OTHER | 1,244 | 4 | 2026-10-01 11:28 | 2.6 |
| openclaw_pages/ | OTHER | 26,812,439 | 231 files | 2026-10-02 11:19 | 1.6 |
| orchestration_grounded_latest.json | OTHER | 9,686 |  | 2026-10-02 00:19 | 2.1 |
| orchestration_latest.json | OTHER | 7,756 |  | 2026-10-02 00:43 | 2.0 |
| output_contracts_latest.json | OTHER | 721 |  | 2026-10-02 00:29 | 2.1 |
| p_survive_history.jsonl | OTHER | 38,988 | 59 | 2026-10-02 00:04 | 2.1 |
| pantry_fill.jsonl | OTHER | 9,247 | 19 | 2026-10-02 10:20 | 1.6 |
| pending_approvals.json | OTHER | 683 |  | 2026-10-02 00:30 | 2.1 |
| pending_expression.json | OTHER | 6,016 |  | 2026-09-14 09:56 | 19.7 |
| pending_tasks.json | OTHER | 678 |  | 2026-04-10 09:47 | 176.7 |
| penumbra/ | OTHER | 27,256 | 21 files | 2026-08-24 23:10 | 40.1 |
| phase_debriefs/ | OTHER | 1,823,099 | 416 files | 2026-10-02 00:43 | 2.0 |
| phase_reports/ | OTHER | 1,264,507 | 427 files | 2026-10-02 00:30 | 2.1 |
| plastic_collection_log.json | OTHER | 172 |  | 2026-08-08 06:51 | 56.8 |
| plastic_recycle_log.json | OTHER | 15 |  | 2026-08-09 00:42 | 56.0 |
| plastic_recycle_metric.json | OTHER | 59 |  | 2026-08-22 01:28 | 43.0 |
| plastic_recycling_projection.json | OTHER | 73 |  | 2026-08-15 00:54 | 50.0 |
| plastic_recycling_stats.json | OTHER | 352 |  | 2026-08-13 07:31 | 51.8 |
| plastic_waste_log.json | OTHER | 479 |  | 2026-08-12 07:35 | 52.8 |
| precip_forecast.json | OTHER | 15 |  | 2026-08-13 07:31 | 51.8 |
| prediction_tracker.py | OTHER | 3,826 |  | 2026-08-17 11:16 | 47.6 |
| predictions.json | OTHER | 8,035 |  | 2026-08-28 15:09 | 36.4 |
| predictor_memory.json | OTHER | 1,269 |  | 2026-05-07 10:20 | 149.6 |
| problem_solution_db.json | OTHER | 287,838 |  | 2026-10-02 00:29 | 2.1 |
| progress_metric.json | OTHER | 38 |  | 2026-07-21 06:07 | 74.8 |
| proposal_archive/ | CYCLE-HISTORY | 287,574 | 4 files | 2026-10-01 00:30 | 3.1 |
| proposal_archive.py | CYCLE-HISTORY | 17,100 |  | 2026-10-03 05:55 | 0.8 |
| proposal_execution_log.json | OTHER | 25,166 |  | 2026-04-13 17:41 | 173.3 |
| proposal_intake_refusals.jsonl | OTHER | 193,916 | 397 | 2026-10-01 00:08 | 3.1 |
| proposal_sla_escalated.json | OTHER | 13,276 |  | 2026-10-02 00:30 | 2.1 |
| proposal_sla_queue.json | OTHER | 6,458 |  | 2026-10-02 00:30 | 2.1 |
| provenance_latest.json | OTHER | 17,117 |  | 2026-10-02 00:06 | 2.1 |
| provenance_pairs.json | OTHER | 8,519 |  | 2026-08-03 14:36 | 61.5 |
| provider_catalogs/ | OTHER | 1,766,854 | 2 files | 2026-08-03 11:03 | 61.6 |
| public_campaign.json | OTHER | 351 |  | 2026-08-22 01:28 | 43.0 |
| pulse_cycle_requests.json | OTHER | 582 |  | 2026-09-19 11:39 | 14.6 |
| pulse_history.jsonl | OTHER | 11,340 | 46 | 2026-03-12 09:06 | 205.7 |
| pulse_latest.json | OTHER | 262 |  | 2026-03-12 09:06 | 205.7 |
| pulse_rate_baseline.json | OTHER | 181 |  | 2026-07-31 18:09 | 64.3 |
| pulse_runs.log | OTHER | 20,449,671 |  | 2026-10-02 11:19 | 1.6 |
| pulse_signal.json | OTHER | 197 |  | 2026-10-02 11:19 | 1.6 |
| pulse_stream.jsonl | OTHER | 15,727,727 | 16250 | 2026-10-02 11:19 | 1.6 |
| qftest2_marker.txt | OTHER | 2 |  | 2026-08-22 01:28 | 43.0 |
| quarantine_triage.json | OTHER | 49,944 |  | 2026-08-23 10:36 | 41.6 |
| reactions.jsonl | OTHER | 13,954 | 7 | 2026-08-28 10:37 | 36.6 |
| reasoning_memory.json | OTHER | 3,155 |  | 2026-03-28 10:55 | 189.6 |
| reconsider_history.jsonl | OTHER | 4,687 | 4 | 2026-08-25 01:06 | 40.0 |
| reconsider_latest.json | OTHER | 1,213 |  | 2026-08-25 01:06 | 40.0 |
| recycled_material_marketplace.json | OTHER | 226 |  | 2026-08-08 06:52 | 56.8 |
| recycling_hubs.json | OTHER | 12 |  | 2026-08-03 08:26 | 61.7 |
| recycling_stats.json | OTHER | 136 |  | 2026-08-03 08:26 | 61.7 |
| renewable_profile.json | OTHER | 15 |  | 2026-08-08 06:51 | 56.8 |
| repair_proposals.json | OTHER | 2,362 |  | 2026-09-11 01:21 | 23.0 |
| retrieval_at_k.jsonl | OTHER | 475 | 1 | 2026-09-17 13:27 | 16.5 |
| revision_ledger.jsonl | OTHER | 26,500 | 41 | 2026-10-02 00:29 | 2.1 |
| root_cause_water.json | OTHER | 85 |  | 2026-07-25 00:42 | 71.0 |
| routing_log.json | OTHER | 15 |  | 2026-08-11 08:49 | 53.7 |
| runtime_experiences.json | OTHER | 144,015 |  | 2026-10-02 00:29 | 2.1 |
| runtime_telemetry.py | OTHER | 14,608 |  | 2026-09-08 10:22 | 25.6 |
| satellite_data.json | OTHER | 12 |  | 2026-07-31 07:34 | 64.8 |
| satellite_moisture.json | OTHER | 15 |  | 2026-08-13 07:31 | 51.8 |
| satellite_observations.json | OTHER | 20 |  | 2026-07-22 00:56 | 74.0 |
| scheduler_state.json | OTHER | 2,801 |  | 2026-10-02 00:34 | 2.1 |
| self_awareness.json | OTHER | 402,907 |  | 2026-03-11 17:20 | 206.4 |
| self_awareness.py.backup2 | OTHER | 8,389 |  | 2026-03-11 15:13 | 206.4 |
| self_directed_priority.json | OTHER | 1,155 |  | 2026-09-19 11:32 | 14.6 |
| self_experiment_schedule_log.jsonl | OTHER | 5,661 | 13 | 2026-09-24 23:50 | 9.1 |
| self_experiments.json | OTHER | 31,519 |  | 2026-09-26 10:28 | 7.6 |
| self_mirror_latest.json | OTHER | 6,471 |  | 2026-10-02 00:30 | 2.1 |
| self_mirror_log.jsonl | OTHER | 20,329 | 57 | 2026-10-02 00:30 | 2.1 |
| self_modification.py | OTHER | 6,260 |  | 2026-05-01 11:26 | 155.6 |
| self_modification_final.py | OTHER | 4,559 |  | 2026-05-01 11:26 | 155.6 |
| self_narrative_latest.txt | OTHER | 301 |  | 2026-09-19 11:33 | 14.6 |
| self_profile.json | OTHER | 1,962 |  | 2026-10-02 10:38 | 1.6 |
| self_read_probe.jsonl | OTHER | 750 | 1 | 2026-09-12 08:58 | 21.7 |
| self_read_probe_latest.json | OTHER | 24,640 |  | 2026-09-12 08:58 | 21.7 |
| self_reflection_log.jsonl | OTHER | 5,040 | 6 | 2026-09-19 11:33 | 14.6 |
| selfcode_runs.jsonl | OTHER | 7,607 | 7 | 2026-08-04 09:13 | 60.7 |
| semantic_memory.py | OTHER | 5,774 |  | 2026-08-28 10:57 | 36.6 |
| sensorium/ | OTHER | 1,278,655 | 1565 files | 2026-10-02 00:06 | 2.1 |
| session_2026-03-10.json | OTHER | 602 |  | 2026-03-10 12:12 | 207.6 |
| session_2026-03-12.json | OTHER | 1,060 |  | 2026-03-12 16:19 | 205.4 |
| session_2026-03-13.json | OTHER | 660 |  | 2026-03-13 14:01 | 204.5 |
| session_2026-03-14.json | OTHER | 660 |  | 2026-03-14 07:15 | 203.8 |
| session_2026-03-21.json | OTHER | 661 |  | 2026-03-21 11:58 | 196.6 |
| session_2026-03-27.json | OTHER | 661 |  | 2026-03-27 08:15 | 190.7 |
| session_2026-03-28.json | OTHER | 661 |  | 2026-03-28 10:55 | 189.6 |
| session_2026-06-18.json | OTHER | 683 |  | 2026-06-18 20:31 | 107.2 |
| session_2026-06-19.json | OTHER | 683 |  | 2026-06-19 18:30 | 106.3 |
| session_2026-06-20.json | OTHER | 683 |  | 2026-06-20 13:00 | 105.5 |
| session_2026-06-21.json | OTHER | 683 |  | 2026-06-21 13:57 | 104.5 |
| session_2026-07-11.json | OTHER | 683 |  | 2026-07-11 08:03 | 84.7 |
| session_2026-07-13.json | OTHER | 683 |  | 2026-07-13 10:04 | 82.7 |
| session_2026-07-14.json | OTHER | 683 |  | 2026-07-14 06:10 | 81.8 |
| session_2026-07-19.json | OTHER | 683 |  | 2026-07-19 06:47 | 76.8 |
| session_2026-07-21.json | OTHER | 683 |  | 2026-07-21 06:07 | 74.8 |
| session_2026-07-22.json | OTHER | 683 |  | 2026-07-22 00:56 | 74.0 |
| session_2026-07-25.json | OTHER | 683 |  | 2026-07-25 00:42 | 71.0 |
| session_2026-07-29.json | OTHER | 684 |  | 2026-07-29 19:28 | 66.3 |
| session_2026-07-30.json | OTHER | 684 |  | 2026-07-30 00:42 | 66.0 |
| session_2026-07-31.json | OTHER | 684 |  | 2026-07-31 07:34 | 64.8 |
| session_2026-08-01.json | OTHER | 684 |  | 2026-08-01 06:03 | 63.8 |
| session_2026-08-02.json | OTHER | 684 |  | 2026-08-02 06:48 | 62.8 |
| session_2026-08-03.json | OTHER | 684 |  | 2026-08-03 08:26 | 61.7 |
| session_2026-08-04.json | OTHER | 684 |  | 2026-08-04 09:18 | 60.7 |
| session_2026-08-05.json | OTHER | 684 |  | 2026-08-05 06:41 | 59.8 |
| session_2026-08-06.json | OTHER | 684 |  | 2026-08-06 07:05 | 58.8 |
| session_2026-08-07.json | OTHER | 684 |  | 2026-08-07 00:50 | 58.0 |
| session_2026-08-08.json | OTHER | 684 |  | 2026-08-08 06:52 | 56.8 |
| session_2026-08-09.json | OTHER | 684 |  | 2026-08-09 00:43 | 56.0 |
| session_2026-08-10.json | OTHER | 684 |  | 2026-08-10 00:47 | 55.0 |
| session_2026-08-11.json | OTHER | 684 |  | 2026-08-11 08:49 | 53.7 |
| session_2026-08-12.json | OTHER | 684 |  | 2026-08-12 07:35 | 52.8 |
| session_2026-08-13.json | OTHER | 684 |  | 2026-08-13 07:31 | 51.8 |
| session_2026-08-14.json | OTHER | 684 |  | 2026-08-14 06:54 | 50.8 |
| session_2026-08-15.json | OTHER | 684 |  | 2026-08-15 00:54 | 50.0 |
| session_2026-08-16.json | OTHER | 684 |  | 2026-08-16 10:50 | 48.6 |
| session_2026-08-17.json | OTHER | 684 |  | 2026-08-17 16:21 | 47.4 |
| session_2026-08-18.json | OTHER | 684 |  | 2026-08-18 13:24 | 46.5 |
| session_2026-08-19.json | OTHER | 684 |  | 2026-08-19 02:35 | 46.0 |
| session_2026-08-20.json | OTHER | 684 |  | 2026-08-20 18:42 | 44.3 |
| session_2026-08-21.json | OTHER | 684 |  | 2026-08-21 14:06 | 43.5 |
| session_2026-08-22.json | OTHER | 684 |  | 2026-08-22 16:27 | 42.4 |
| session_2026-08-23.json | OTHER | 684 |  | 2026-08-23 18:18 | 41.3 |
| session_2026-08-24.json | OTHER | 684 |  | 2026-08-24 02:07 | 41.0 |
| session_2026-08-25.json | OTHER | 684 |  | 2026-08-25 01:23 | 40.0 |
| session_2026-08-26.json | OTHER | 684 |  | 2026-08-26 09:07 | 38.7 |
| session_2026-08-27.json | OTHER | 684 |  | 2026-08-27 01:37 | 38.0 |
| session_2026-08-28.json | OTHER | 684 |  | 2026-08-28 13:36 | 36.5 |
| session_2026-08-29.json | OTHER | 684 |  | 2026-08-29 16:39 | 35.4 |
| session_2026-08-30.json | OTHER | 684 |  | 2026-08-30 13:00 | 34.5 |
| session_2026-08-31.json | OTHER | 684 |  | 2026-08-31 12:48 | 33.5 |
| session_2026-09-01.json | OTHER | 684 |  | 2026-09-01 01:40 | 33.0 |
| session_2026-09-02.json | OTHER | 684 |  | 2026-09-02 01:33 | 32.0 |
| session_2026-09-03.json | OTHER | 684 |  | 2026-09-03 01:39 | 31.0 |
| session_2026-09-04.json | OTHER | 684 |  | 2026-09-04 01:21 | 30.0 |
| session_2026-09-05.json | OTHER | 684 |  | 2026-09-05 01:38 | 29.0 |
| session_2026-09-06.json | OTHER | 684 |  | 2026-09-06 01:48 | 28.0 |
| session_2026-09-07.json | OTHER | 684 |  | 2026-09-07 01:27 | 27.0 |
| session_2026-09-08.json | OTHER | 684 |  | 2026-09-08 01:38 | 26.0 |
| session_2026-09-09.json | OTHER | 684 |  | 2026-09-09 01:55 | 25.0 |
| session_2026-09-10.json | OTHER | 684 |  | 2026-09-10 01:21 | 24.0 |
| session_2026-09-11.json | OTHER | 684 |  | 2026-09-11 01:36 | 23.0 |
| session_2026-09-12.json | OTHER | 684 |  | 2026-09-12 01:50 | 22.0 |
| session_2026-09-13.json | OTHER | 681 |  | 2026-09-13 01:41 | 21.0 |
| session_2026-09-14.json | OTHER | 684 |  | 2026-09-14 16:36 | 19.4 |
| session_2026-09-15.json | OTHER | 684 |  | 2026-09-15 01:11 | 19.0 |
| session_2026-09-16.json | OTHER | 684 |  | 2026-09-16 01:15 | 18.0 |
| session_2026-09-17.json | OTHER | 684 |  | 2026-09-17 01:28 | 17.0 |
| session_2026-09-18.json | OTHER | 684 |  | 2026-09-18 01:13 | 16.0 |
| session_2026-09-19.json | OTHER | 684 |  | 2026-09-19 11:41 | 14.6 |
| session_2026-09-20.json | OTHER | 684 |  | 2026-09-20 01:14 | 14.0 |
| session_2026-09-21.json | OTHER | 684 |  | 2026-09-21 01:10 | 13.0 |
| session_2026-09-22.json | OTHER | 684 |  | 2026-09-22 01:11 | 12.0 |
| session_2026-09-24.json | OTHER | 684 |  | 2026-09-24 17:33 | 9.3 |
| session_2026-09-25.json | OTHER | 684 |  | 2026-09-25 06:41 | 8.8 |
| session_2026-09-26.json | OTHER | 684 |  | 2026-09-26 09:16 | 7.7 |
| session_2026-09-27.json | OTHER | 684 |  | 2026-09-27 00:25 | 7.1 |
| session_2026-09-28.json | OTHER | 684 |  | 2026-09-28 00:32 | 6.1 |
| session_2026-09-29.json | OTHER | 684 |  | 2026-09-29 00:21 | 5.1 |
| session_2026-09-30.json | OTHER | 684 |  | 2026-09-30 00:24 | 4.1 |
| session_2026-10-01.json | OTHER | 684 |  | 2026-10-01 00:31 | 3.1 |
| session_2026-10-02.json | OTHER | 684 |  | 2026-10-02 00:29 | 2.1 |
| social_cohesion_indicators.json | OTHER | 315 |  | 2026-07-30 00:42 | 66.0 |
| social_cohesion_projects.json | OTHER | 1,231 |  | 2026-07-30 00:42 | 66.0 |
| social_relations_approvals.json | OTHER | 17 |  | 2026-08-11 08:49 | 53.7 |
| social_relations_history.json | OTHER | 397 |  | 2026-08-05 06:40 | 59.8 |
| social_relations_plan.json | OTHER | 270 |  | 2026-08-14 06:54 | 50.8 |
| social_relations_progress.json | OTHER | 3,111 |  | 2026-08-04 00:42 | 61.0 |
| social_relations_projects.json | OTHER | 1,088 |  | 2026-08-04 09:17 | 60.7 |
| social_relations_result.json | OTHER | 42 |  | 2026-08-15 00:54 | 50.0 |
| social_relations_review.json | OTHER | 227 |  | 2026-07-31 07:34 | 64.8 |
| social_relations_review_metric.json | OTHER | 163 |  | 2026-08-10 00:47 | 55.0 |
| social_relations_score.json | OTHER | 14 |  | 2026-08-11 08:49 | 53.7 |
| social_relations_state.json | OTHER | 182 |  | 2026-08-06 07:04 | 58.8 |
| somatic_history.jsonl | OTHER | 816,336 | 1197 | 2026-10-03 18:38 | 0.3 |
| source_lifecycle.json | OTHER | 81,577 |  | 2026-10-01 18:00 | 2.3 |
| source_lifecycle_ledger.jsonl | OTHER | 742,185 | 2070 | 2026-10-01 18:00 | 2.3 |
| source_trust_state.json | OTHER | 3,025 |  | 2026-09-13 00:25 | 21.1 |
| space/ | KNOWLEDGE | 17,284,265 | 7 files | 2026-10-02 10:33 | 1.6 |
| state_vectors.jsonl | OTHER | 45,399 | 49 | 2026-10-02 00:30 | 2.1 |
| statements.jsonl | KNOWLEDGE | 264,183,168 | skip>200MB | 2026-10-02 11:19 | 1.6 |
| statements_ingest.jsonl | KNOWLEDGE | 48,636 | 205 | 2026-09-17 12:23 | 16.6 |
| step_callmap.json | OTHER | 52,334 |  | 2026-08-21 11:51 | 43.6 |
| step_contract_baseline.json | OTHER | 385,749 |  | 2026-10-02 00:30 | 2.1 |
| step_contract_latest.json | OTHER | 23,639 |  | 2026-10-02 00:30 | 2.1 |
| steps/ | OTHER | 904,782 | 50 files | 2026-10-02 00:04 | 2.1 |
| suite_runs.jsonl | OTHER | 251,288 | 58 | 2026-09-19 12:51 | 14.5 |
| survival_state.json | OTHER | 77 |  | 2026-09-12 18:34 | 21.3 |
| system2_latest.json | OTHER | 10,549 |  | 2026-03-11 21:27 | 206.2 |
| t1_result_full.json | OTHER | 66,983 |  | 2026-09-17 14:12 | 16.5 |
| t1_trials.jsonl | OTHER | 2,561 | 2 | 2026-09-17 14:12 | 16.5 |
| task_runs.jsonl | OTHER | 39,703 | 194 | 2026-10-01 18:00 | 2.3 |
| taxonomy_coverage_latest.json | OTHER | 139,186 |  | 2026-10-02 11:12 | 1.6 |
| telegram_approvals.json | OTHER | 17 |  | 2026-08-07 00:50 | 58.0 |
| telegram_offset.json | OTHER | 63 |  | 2026-09-26 14:58 | 7.4 |
| threshold_proposals.json | OTHER | 9,567 |  | 2026-08-21 09:51 | 43.7 |
| training_log.jsonl | OTHER | 2,564,619 | 7593 | 2026-10-02 00:30 | 2.1 |
| transcript_cache/ | OTHER | 948,370 | 824 files | 2026-10-01 09:13 | 2.7 |
| trend_analyzer.py | OTHER | 2,924 |  | 2026-07-11 17:18 | 84.4 |
| trend_tracker.py | OTHER | 18,745 |  | 2026-08-29 09:25 | 35.7 |
| trends_latest.json | OTHER | 9,895 |  | 2026-10-02 00:07 | 2.1 |
| truck_routing_log.json | OTHER | 200 |  | 2026-08-08 06:52 | 56.8 |
| turn.json | OTHER | 186 |  | 2026-10-02 21:59 | 1.2 |
| turn_result.json | OTHER | 1,105 |  | 2026-10-02 10:43 | 1.6 |
| turns/ | OTHER | 631,174 | 66 files | 2026-10-02 10:43 | 1.6 |
| turns_log.jsonl | OTHER | 37,905 | 157 | 2026-10-02 21:59 | 1.2 |
| ucdp_provenance.jsonl | OTHER | 9,904 | 44 | 2026-10-02 00:11 | 2.1 |
| ucdp_requests.json | OTHER | 338 |  | 2026-10-02 00:11 | 2.1 |
| upgrade_plan.json | OTHER | 2 |  | 2026-08-14 06:54 | 50.8 |
| verified_observations.jsonl | PROOF | 171,121 | 163 | 2026-10-01 18:00 | 2.3 |
| vertical_ledger.jsonl | BRAIN | 531,014 | 3047 | 2026-10-02 11:20 | 1.6 |
| watchdog_io.json | OTHER | 65 |  | 2026-09-14 15:29 | 19.4 |
| watchdog_runs.log | OTHER | 1,123,204 |  | 2026-10-02 11:09 | 1.6 |
| water_balance.json | OTHER | 165 |  | 2026-07-22 00:56 | 74.0 |
| water_compliance_dashboard.json | OTHER | 577 |  | 2026-08-09 00:42 | 56.0 |
| water_compliance_log.json | OTHER | 672 |  | 2026-08-09 00:42 | 56.0 |
| water_drawdown.json | OTHER | 14 |  | 2026-08-13 07:31 | 51.8 |
| water_management_status.json | OTHER | 947 |  | 2026-07-25 00:42 | 71.0 |
| water_measurement.json | OTHER | 15 |  | 2026-08-11 08:49 | 53.7 |
| water_metrics.json | OTHER | 55 |  | 2026-08-12 07:35 | 52.8 |
| water_monitor/ | OTHER | 311 | 2 files | 2026-07-21 06:06 | 74.8 |
| water_quota.json | OTHER | 88 |  | 2026-08-12 07:35 | 52.8 |
| water_quota_allocations.json | OTHER | 75 |  | 2026-08-13 07:31 | 51.8 |
| water_quota_db.json | OTHER | 916 |  | 2026-08-11 08:49 | 53.7 |
| water_quota_result.json | OTHER | 157 |  | 2026-08-14 06:54 | 50.8 |
| water_recommendations.json | OTHER | 739 |  | 2026-08-04 00:42 | 61.0 |
| water_sensor_data.json | OTHER | 16 |  | 2026-08-06 07:05 | 58.8 |
| water_sensors.json | OTHER | 347 |  | 2026-07-21 06:06 | 74.8 |
| water_stress_metric.json | OTHER | 156 |  | 2026-07-31 07:34 | 64.8 |
| water_stress_recommendations.json | OTHER | 75 |  | 2026-07-31 07:34 | 64.8 |
| water_usage.json | OTHER | 12 |  | 2026-08-12 07:35 | 52.8 |
| web_intelligence/ | OTHER | 33,544,538 | 2411 files | 2026-10-01 23:17 | 2.1 |
| witness.jsonl | PROOF | 91,685 | 196 | 2026-10-02 10:43 | 1.6 |
| youtube_adaptive_memory.json | OTHER | 49,333 |  | 2026-10-02 10:19 | 1.6 |
| youtube_cache.json | OTHER | 12,317 |  | 2026-05-04 10:51 | 152.6 |
| yt_backoff.json | OTHER | 143 |  | 2026-10-02 10:08 | 1.7 |
| atoms/.gitkeep | KNOWLEDGE | 0 |  | 2026-10-01 11:44 | 2.6 |
| atoms/_unplaced/ | KNOWLEDGE | 11,161 | 14 files | 2026-10-01 18:00 | 2.3 |
| atoms/A/ | KNOWLEDGE | 22,460 | 46 files | 2026-10-01 13:33 | 2.5 |
| atoms/B/ | KNOWLEDGE | 20,370 | 42 files | 2026-10-01 13:33 | 2.5 |
| atoms/C/ | KNOWLEDGE | 15,556 | 24 files | 2026-10-01 18:00 | 2.3 |
| atoms/D/ | KNOWLEDGE | 5,241 | 2 files | 2026-10-01 18:00 | 2.3 |
| atoms/MANIFEST.json | KNOWLEDGE | 21,953 |  | 2026-10-01 18:00 | 2.3 |

#### 30 largest
| entry | group | bytes | rows (.jsonl) | last write UTC | age d |
|---|---|---|---|---|---|
| knowledge/ | KNOWLEDGE | 874,463,457 | 6 files | 2026-10-02 11:19 | 1.6 |
| statements.jsonl | KNOWLEDGE | 264,183,168 | skip>200MB | 2026-10-02 11:19 | 1.6 |
| brain_probe/ | BRAIN | 227,798,845 | 2 files | 2026-09-17 19:28 | 16.3 |
| embeddings_cache.json | OTHER | 84,488,997 |  | 2026-09-17 13:27 | 16.5 |
| intel.db | OTHER | 47,046,656 |  | 2026-10-02 08:35 | 1.7 |
| web_intelligence/ | OTHER | 33,544,538 | 2411 files | 2026-10-01 23:17 | 2.1 |
| openclaw_pages/ | OTHER | 26,812,439 | 231 files | 2026-10-02 11:19 | 1.6 |
| embed_index/ | OTHER | 21,586,936 | 9 files | 2026-09-17 13:06 | 16.5 |
| pulse_runs.log | OTHER | 20,449,671 |  | 2026-10-02 11:19 | 1.6 |
| space/ | KNOWLEDGE | 17,284,265 | 7 files | 2026-10-02 10:33 | 1.6 |
| pulse_stream.jsonl | OTHER | 15,727,727 | 16250 | 2026-10-02 11:19 | 1.6 |
| chromadb/ | OTHER | 15,156,896 | 6 files | 2026-10-02 00:43 | 2.0 |
| cycle_trace/ | OTHER | 11,383,566 | 35 files | 2026-10-02 00:30 | 2.1 |
| divergence_log.jsonl | OTHER | 4,991,612 | 4513 | 2026-10-02 00:30 | 2.1 |
| llm_provenance.jsonl | OTHER | 4,973,169 | 13152 | 2026-10-03 09:41 | 0.7 |
| interval_head_weights.npz | OTHER | 4,576,993 |  | 2026-08-28 14:51 | 36.5 |
| interval_head_weights_prev.npz | OTHER | 4,555,368 |  | 2026-08-28 14:37 | 36.5 |
| expression_stream.jsonl | OTHER | 3,221,320 | 8712 | 2026-10-03 18:41 | 0.3 |
| brain_journal.jsonl | BRAIN | 3,136,429 | 3441 | 2026-10-02 10:36 | 1.6 |
| training_log.jsonl | OTHER | 2,564,619 | 7593 | 2026-10-02 00:30 | 2.1 |
| brain_step_log.jsonl | BRAIN | 2,431,128 | 4310 | 2026-09-25 06:58 | 8.8 |
| body_sensorium/ | OTHER | 2,417,749 | 16 files | 2026-10-02 11:19 | 1.6 |
| cycle_logs/ | OTHER | 2,037,228 | 39 files | 2026-10-02 00:44 | 2.0 |
| phase_debriefs/ | OTHER | 1,823,099 | 416 files | 2026-10-02 00:43 | 2.0 |
| provider_catalogs/ | OTHER | 1,766,854 | 2 files | 2026-08-03 11:03 | 61.6 |
| collector_runs.log | OTHER | 1,501,253 |  | 2026-10-02 08:58 | 1.7 |
| sensorium/ | OTHER | 1,278,655 | 1565 files | 2026-10-02 00:06 | 2.1 |
| _mem_trace.jsonl | OTHER | 1,278,019 | 2836 | 2026-08-21 14:41 | 43.5 |
| phase_reports/ | OTHER | 1,264,507 | 427 files | 2026-10-02 00:30 | 2.1 |
| watchdog_runs.log | OTHER | 1,123,204 |  | 2026-10-02 11:09 | 1.6 |

#### 30 least recently written
| entry | group | bytes | rows (.jsonl) | last write UTC | age d |
|---|---|---|---|---|---|
| session_2026-03-10.json | OTHER | 602 |  | 2026-03-10 12:12 | 207.6 |
| backups/ | OTHER | 0 | 0 files | 2026-03-11 11:16 | 206.6 |
| self_awareness.py.backup2 | OTHER | 8,389 |  | 2026-03-11 15:13 | 206.4 |
| self_awareness.json | OTHER | 402,907 |  | 2026-03-11 17:20 | 206.4 |
| system2_latest.json | OTHER | 10,549 |  | 2026-03-11 21:27 | 206.2 |
| pulse_history.jsonl | OTHER | 11,340 | 46 | 2026-03-12 09:06 | 205.7 |
| pulse_latest.json | OTHER | 262 |  | 2026-03-12 09:06 | 205.7 |
| session_2026-03-12.json | OTHER | 1,060 |  | 2026-03-12 16:19 | 205.4 |
| session_2026-03-13.json | OTHER | 660 |  | 2026-03-13 14:01 | 204.5 |
| session_2026-03-14.json | OTHER | 660 |  | 2026-03-14 07:15 | 203.8 |
| session_2026-03-21.json | OTHER | 661 |  | 2026-03-21 11:58 | 196.6 |
| session_2026-03-27.json | OTHER | 661 |  | 2026-03-27 08:15 | 190.7 |
| session_2026-03-28.json | OTHER | 661 |  | 2026-03-28 10:55 | 189.6 |
| reasoning_memory.json | OTHER | 3,155 |  | 2026-03-28 10:55 | 189.6 |
| pending_tasks.json | OTHER | 678 |  | 2026-04-10 09:47 | 176.7 |
| approval_queue.json | OTHER | 5,855 |  | 2026-04-13 07:27 | 173.8 |
| improvement_plan_latest.json | OTHER | 1,798 |  | 2026-04-13 17:25 | 173.3 |
| proposal_execution_log.json | OTHER | 25,166 |  | 2026-04-13 17:41 | 173.3 |
| auto_threshold.py | OTHER | 3,296 |  | 2026-05-01 11:26 | 155.6 |
| context_injector.py | OTHER | 6,536 |  | 2026-05-01 11:26 | 155.6 |
| goal_alignment.py | OTHER | 870 |  | 2026-05-01 11:26 | 155.6 |
| self_modification.py | OTHER | 6,260 |  | 2026-05-01 11:26 | 155.6 |
| self_modification_final.py | OTHER | 4,559 |  | 2026-05-01 11:26 | 155.6 |
| __init__.py | OTHER | 0 |  | 2026-05-01 11:26 | 155.6 |
| civic_participation.json | OTHER | 26 |  | 2026-05-04 09:07 | 152.7 |
| climate_data.json | OTHER | 39 |  | 2026-05-04 09:18 | 152.7 |
| governance_institutions.json | OTHER | 39 |  | 2026-05-04 09:18 | 152.7 |
| civilization_monitoring.json | OTHER | 26 |  | 2026-05-04 09:18 | 152.7 |
| youtube_cache.json | OTHER | 12,317 |  | 2026-05-04 10:51 | 152.6 |
| government_processes.json | OTHER | 501 |  | 2026-05-04 12:48 | 152.5 |

## Step 2 — writers and readers

Command: `venv\Scripts\python.exe tools/ask.py readers <store>` for each store; writers additionally by grep over
tracked non-test *.py: the file names the store's file name AND contains `.write_text(`, `.write_bytes(`, `.write(`,
`open(…'a'/'w')`, `json.dump(`, `os.replace(` or `shutil.copy/move`. CLASS rules: BRAIN-READ = a live reader is
core/knowledge.py, core/brain.py, core/brain_needs.py or scripts/turn_brain.py; CYCLE-READ = fast_cycle_runner.py
itself reads it; REPORT-ONLY = every live reader is a report or dashboard (tools/daily_board.py, cockpit/*,
tools/*step_audit*, tools/cycle_watch.py, tools/morning_digest.py, scripts/morning_check.py, scripts/agi_scoreboard.py,
...); NO-READER = nothing reads it; otherwise "unclear".

| store | group | rows | last write UTC | writers (count) | readers, live (count; +tests) | CLASS |
|---|---|---|---|---|---|---|
| atoms/MANIFEST.json | KNOWLEDGE |  | 2026-10-01 18:00 | core/atoms.py (1) | - (0; +1) | NO-READER |
| cortex_memory/abstractions/essence.md | - |  |  | merkle_memory.py, merkle_to_training.py (2) | merkle_memory.py, merkle_to_training.py (2; +0) | unclear (live reader; cycle path not traced) |
| cortex_memory/abstractions/hashes.json | - |  |  | merkle_memory.py, wellbeing_globe.py (2) | wellbeing_globe.py (1; +1) | unclear (live reader; cycle path not traced) |
| cortex_memory/abstractions/self_profile.json | - |  |  | agents/core/self_modifier.py, core/homeostasis.py, experiments/needs/needs_report.py, experiments/prophecy/goal_prophecy.py … (5) | experiments/prophecy/goal_prophecy.py, search_logic.py (2; +0) | unclear (live reader; cycle path not traced) |
| cortex_memory/abstractions/trends.json | - |  |  | citation_verifier.py, evaluator.py, experiments/prophecy/goal_prophecy.py, goal_score_calculator.py … (8) | core/gdelt_daily.py, core/hypothesis_intake.py, core/market_daily.py, core/usgs_quakes.py, evaluator.py, experiments/prophecy/goal_prophecy.py … (8; +3) | unclear (live reader; cycle path not traced) |
| cortex_memory/hypotheses/causal_pending.json | - |  |  | hypothesis_generator.py (1) | hypothesis_generator.py (1; +0) | unclear (live reader; cycle path not traced) |
| cortex_memory/hypotheses/pending.json | - |  |  | citation_verifier.py, core/consolidation.py, core/hypothesis_intake.py, core/hypothesis_resolution.py … (7) | core/hypothesis_intake.py, core/hypothesis_resolution.py, evaluator.py, github_publisher.py, hypothesis_generator.py (5; +3) | unclear (live reader; cycle path not traced) |
| cortex_memory/hypotheses/resolved.json | - |  |  | core/belief_revision.py, core/hypothesis_intake.py, core/hypothesis_resolution.py, core/self_improve/requirer.py … (6) | core/hypothesis_resolution.py, evaluator.py (2; +1) | unclear (live reader; cycle path not traced) |
| cortex_memory/middle | - |  |  | core/hypothesis_search.py, core/model_window.py, fast_cycle_runner.py, memory/runtime_telemetry.py … (6) | - (0; +0) | NO-READER |
| cortex_memory/state.json | - |  |  | agents/core/daily_analysis_agent.py, cockpit/server.py, core/belief_revision.py, core/brain.py … (23) | experiments/institution/register_forward_row.py (1; +0) | unclear (live reader; cycle path not traced) |
| memory/_mem_trace.jsonl | OTHER | 2836 | 2026-08-21 14:41 | none found (0) | - (0; +0) | NO-READER + NO-WRITER |
| memory/axis_history.json | CYCLE-HISTORY |  | 2026-10-02 00:07 | cockpit/server.py, core/alarm_bands.py, core/axis_backfill.py, core/constancy.py … (17) | core/constancy.py, core/source_trust.py, cortex_scanner.py, experiments/prophecy/prophecy.py, experiments/prophecy/world_forecast.py, memory/auto_threshold.py … (9; +6) | unclear (live reader; cycle path not traced) |
| memory/blackbox.jsonl | PROOF | 3027 | 2026-10-03 19:00 | agents/core/self_modifier.py, core/blackbox.py, core/earning.py, core/provenance.py … (9) | tools/cycle_step_audit.py, tools/cycle_watch.py, tools/step_audit.py (3; +0) | REPORT-ONLY |
| memory/brain_journal.jsonl | BRAIN | 3441 | 2026-10-02 10:36 | core/brain.py, core/brain_relay.py, core/language_gate.py, core/metta_check.py … (8) | cockpit/timeline.py, core/brain.py, core/language_gate.py, core/self_read_probe.py, scripts/audit_exemplars.py, scripts/prompt_census.py … (8; +10) | BRAIN-READ |
| memory/brain_needs.json | BRAIN |  | 2026-10-02 11:19 | core/brain_needs.py, core/space.py (2) | - (0; +0) | unclear (named, read not classified) |
| memory/brain_step_log.jsonl | BRAIN | 4310 | 2026-09-25 06:58 | core/brain.py, core/cycle_report.py, core/self_mirror.py, core/training_log.py (4) | cockpit/timeline.py, core/cycle_report.py, experiments/audit/watch_cycle.py, scripts/morning_check.py (4; +0) | unclear (live reader; cycle path not traced) |
| memory/consolidation_latest.json | OTHER |  | 2026-10-01 23:10 | core/consolidation.py, core/output_contracts.py (2) | core/output_contracts.py (1; +1) | unclear (live reader; cycle path not traced) |
| memory/consolidation_queue.json | OTHER |  | 2026-10-01 23:10 | core/consolidation.py, core/hypothesis_intake.py, core/output_contracts.py, tools/step_audit.py (4) | core/hypothesis_intake.py, core/output_contracts.py (2; +1) | unclear (live reader; cycle path not traced) |
| memory/cycle_resume.jsonl | OTHER | 3766 | 2026-10-02 00:30 | cockpit/server.py, core/cycle_checkpoint.py (2) | scripts/verify_checkpoint_map.py (1; +1) | unclear (live reader; cycle path not traced) |
| memory/daily_tier.jsonl | OTHER | 3568 | 2026-10-02 00:06 | core/consolidation.py, core/daily_tier.py, core/output_contracts.py, fast_cycle_runner.py … (8) | core/daily_tier.py, core/output_contracts.py, experiments/prophecy/world_forecast.py, scripts/agi_scoreboard.py, tools/daily_board.py (5; +5) | unclear (live reader; cycle path not traced) |
| memory/development_journal.json | CYCLE-HISTORY |  | 2026-09-29 00:21 | agents/action_gate.py, agents/core/feedback_loop.py, agents/core/goal_planner.py, agents/core/self_modifier.py … (16) | agents/core/feedback_loop.py, agents/core/self_modifier.py, agents/core/self_observer.py, agents/core/self_observer_backup.py, cortex_scanner.py, execute_patches.py … (10; +2) | CYCLE-READ |
| memory/divergence_log.jsonl | OTHER | 4513 | 2026-10-02 00:30 | core/cycle_report.py, core/metta_check.py (2) | core/cycle_report.py, edges_runner.py (2; +0) | unclear (live reader; cycle path not traced) |
| memory/existence_ledger.jsonl | PROOF | 421 | 2026-10-02 00:30 | cockpit/server.py, core/interoception.py, core/self_experiment.py, experiments/dreams/dream.py … (12) | cockpit/entropy.py, cockpit/timeline.py, core/cycle_vector.py, core/halt.py, core/interoception.py, core/p_survive.py … (22; +12) | unclear (live reader; cycle path not traced) |
| memory/expression_stream.jsonl | OTHER | 8712 | 2026-10-03 18:41 | cockpit/phase_voice.py, cockpit/server.py, scripts/cockpit_answer.py (3) | cockpit/timeline.py (1; +0) | REPORT-ONLY |
| memory/goal_score_history.json | CYCLE-HISTORY |  | 2026-10-02 00:29 | agents/core/feedback_loop.py, agents/core/goal_planner.py, agents/core/self_modifier.py, cockpit/server.py … (18) | agents/core/feedback_loop.py, agents/core/goal_planner.py, core/cycle_report.py, core/deduction.py, core/measurement_honesty.py, core/training_log.py … (9; +1) | unclear (live reader; cycle path not traced) |
| memory/hypothesis_intake_latest.json | OTHER |  | 2026-10-02 00:29 | core/hypothesis_intake.py (1) | - (0; +0) | unclear (named, read not classified) |
| memory/hypothesis_resolution_latest.json | OTHER |  | 2026-10-02 00:29 | core/hypothesis_resolution.py (1) | - (0; +0) | unclear (named, read not classified) |
| memory/idea_stream.jsonl | OTHER | 1062 | 2026-10-01 23:10 | cockpit/server.py, experiments/pulse/pulse_continuum.py, fast_cycle_runner.py, tools/resolve_ideas.py (4) | tools/resolve_ideas.py (1; +2) | unclear (live reader; cycle path not traced) |
| memory/improvement_proposals_archive.json | CYCLE-HISTORY |  | 2026-07-23 07:21 | memory/proposal_archive.py (1) | - (0; +0) | NO-READER |
| memory/knowledge_base.json | CYCLE-HISTORY |  | 2026-10-02 00:30 | agents/core/self_observer.py, core/hypothesis_search.py, memory/continuous_learner.py, tools/attention_ratio.py (4) | core/hypothesis_search.py, memory/continuous_learner.py (2; +2) | unclear (live reader; cycle path not traced) |
| memory/llm_provenance.jsonl | OTHER | 13152 | 2026-10-03 09:41 | core/brain.py, core/durable.py, core/llm_door.py, core/phase_report.py … (7) | core/phase_report.py, tools/daily_board.py (2; +2) | unclear (live reader; cycle path not traced) |
| memory/merkle_roots.jsonl | PROOF | 24 | 2026-10-02 00:30 | experiments/institution/forward_rows.py, experiments/institution/register_forward_row.py, experiments/institution/resolve_forward_rows.py, experiments/institution/revisions.py … (5) | core/prereg_gate.py, experiments/institution/forward_rows.py, experiments/institution/register_forward_row.py, experiments/institution/resolve_forward_rows.py, experiments/institution/revisions.py, merkle_memory.py (6; +1) | unclear (live reader; cycle path not traced) |
| memory/night_events.jsonl | OTHER | 1366 | 2026-10-04 00:37 | core/cycle_report.py, core/durable.py, core/metta_check.py, core/reconsider.py … (8) | core/cycle_report.py, edges_runner.py, scripts/morning_check.py, tools/read_the_refusals.py (4; +3) | unclear (live reader; cycle path not traced) |
| memory/proposal_archive | CYCLE-HISTORY | 4 files | 2026-10-01 00:30 | agents/core/self_observer.py, memory/proposal_archive.py (2) | - (0; +0) | NO-READER |
| memory/pulse_stream.jsonl | OTHER | 16250 | 2026-10-02 11:19 | experiments/needs/needs_report.py, experiments/pulse/pulse_continuum.py, tools/attention_ratio.py, tools/suite_gate.py (4) | cockpit/timeline.py, experiments/needs/needs_report.py (2; +3) | unclear (live reader; cycle path not traced) |
| memory/revision_ledger.jsonl | OTHER | 41 | 2026-10-02 00:29 | core/belief_revision.py (1) | core/belief_revision.py (1; +2) | unclear (live reader; cycle path not traced) |
| memory/somatic_history.jsonl | OTHER | 1197 | 2026-10-03 18:38 | cockpit/norms.py, cockpit/phase_voice.py, cockpit/server.py, tools/taxonomy_coverage.py (4) | cockpit/norms.py, tools/taxonomy_coverage.py (2; +0) | unclear (live reader; cycle path not traced) |
| memory/source_lifecycle_ledger.jsonl | OTHER | 2070 | 2026-10-01 18:00 | core/source_lifecycle.py, tools/compass.py (2) | - (0; +0) | unclear (named, read not classified) |
| memory/space/base.metta | - |  |  | core/space.py, tools/daily_board.py (2) | core/brain_needs.py, core/space.py, experiments/engine_bridge/real_rules_two_versions.py, scripts/turn_brain.py, tools/daily_board.py (5; +4) | BRAIN-READ |
| memory/space/derived.metta | - |  |  | core/space.py, tools/daily_board.py (2) | tools/daily_board.py (1; +1) | REPORT-ONLY |
| memory/space/proposed.metta | - |  |  | core/space.py, core/symbols.py, tools/daily_board.py (3) | tools/daily_board.py (1; +0) | REPORT-ONLY |
| memory/statements.jsonl | KNOWLEDGE | skip>200MB | 2026-10-02 11:19 | core/knowledge.py, core/space.py, core/statements.py (3) | core/brain_needs.py, core/knowledge.py, scripts/openclaw_search.py (3; +4) | BRAIN-READ |
| memory/training_log.jsonl | OTHER | 7593 | 2026-10-02 00:30 | core/interval_head.py, core/training_log.py, tools/brain_scan.py (3) | - (0; +0) | unclear (named, read not classified) |
| memory/verified_observations.jsonl | PROOF | 163 | 2026-10-01 18:00 | core/alarm_bands.py, core/card_intake.py, scripts/agi_scoreboard.py, scripts/data_feed_reader.py … (6) | core/alarm_bands.py, core/card_intake.py, scripts/agi_scoreboard.py, training/verified_corpus.py (4; +4) | unclear (live reader; cycle path not traced) |
| memory/vertical_ledger.jsonl | BRAIN | 3047 | 2026-10-02 11:20 | core/brain_needs.py, core/symbols.py, scripts/turn_agents.py, tools/daily_board.py (4) | scripts/turn_agents.py, tools/daily_board.py (2; +5) | unclear (live reader; cycle path not traced) |
| memory/witness.jsonl | PROOF | 196 | 2026-10-02 10:43 | core/turn.py, experiments/institution/telegram_dispatcher.py, experiments/institution/witness_reader.py, scripts/turns_loop.py … (6) | tools/morning_digest.py (1; +1) | REPORT-ONLY |

## Step 3 — the old tiered structure (cortex_memory/)

EXPECTED: archive and roots written by the nightly cycle; essence.md read by something. OBSERVED: as expected.

* `state.json` mtime 2026-10-02 00:30; keys: `merkle_root`, `last_cycle` ("2026-10-02T00:30:01Z"), `last_updated`,
  `total_cycles` (88), `essence_summary` (515 chars), `_total_cycles_reconciled` (242 chars).
* `abstractions/essence.md` exists, 1,172 bytes, mtime 2026-10-02 00:30; `trends.json`, `self_profile.json`,
  `hashes.json` mtime 2026-10-02 00:30.
* `middle/`: 0 `week_*.json` (the folder is empty; mtime 2026-06-14).
* `archive/`: 88 cycle directories; newest `cycle_000088`, 2026-10-02 00:30, **has seal.json**; `merkle_root.txt` 00:30.
* MerkleMemory call sites (non-test): `fast_cycle_runner.py:3416` `MerkleMemory().commit(...)` (step 24) and `:3450`;
  `agents/core/self_observer.py:128` and `agents/hyperclaw/hyperclaw_orchestrator.py:58` `MerkleMemory().load_fast()`
  (FAST = essence.md); `merkle_memory.py:32`, `:722` (its own commit helpers). No `load_medium()` caller found.
* essence into a prompt: `agents/core/self_observer.py:430` puts up to 600 chars of `load_fast()` into the model prompt
  ("МИНАЛ ОПИТ (Merkle Memory)"); self_observer.run() is cycle step 17 (config/step_inputs.json, fast_cycle_runner.py:3249).
  No live caller of hyperclaw_orchestrator was found.

## Step 4 — consolidation and dreams

* core/consolidation.py docstring (head): "THE SYSTEM READS ITS OWN MEMORY (3 Sep 2026) ... reads the archive as a TIME
  SERIES ... NO MODEL ... emits dated, falsifiable hypotheses to memory/consolidation_queue.json". Public functions:
  read_cycles, read_daily_tier, build_series, long_record, local_run_not_drift, slope_smaller_than_its_own_error,
  horizon_longer_than_the_record, impossible_at_the_horizon, run, summary_line, module_imports, imported_forbidden.
* Callers of `core.consolidation.run()` (`tools/ask.py callers`): `experiments/pulse/pulse_continuum.py:767-768`
  (`from core.consolidation import run as _run`, gated by `consolidation_due`) and its own `__main__` (:603, :615);
  tests. fast_cycle_runner.py 3226-3230, verbatim: "there is no consolidation step: core/consolidation.run() is called
  only by experiments/pulse/pulse_continuum.py, and the cycle merely CONSUMES what the pulse left, at 20.06 above."
* `memory/consolidation_latest.json`: ts 2026-10-01T23:10:29Z, window 30 days, date_range 2026-09-01..2026-10-01,
  cycles_read 65, series_considered 118, emitted 2, rejected (10 reasons), uses_model false; keys: ts, made_on,
  window_days, cycles_read, date_range, series_considered, emitted, truncated, rejected, long_record, refused, axes,
  uses_model, queue.
* `memory/consolidation_queue.json`: made_on 2026-10-01; 2 hypotheses (no status field), both made_on 2026-10-01,
  due_on 2026-10-08: `markets.uup_adjclose` up, `biodiversity.species_observations_30d` down. Readers of the queue:
  core/hypothesis_intake.py (cycle step 20.06) and core/output_contracts.py.
* experiments/dreams/dream.py: no caller in any .py/.ps1/.bat/.json outside its folder (named only in
  cockpit/timeline.py:409, config/network_allowlist.json:94, core/p_survive.py:354, docs/MODULE_MAP.json).
  `memory/dreaming/`: deep 1 file, light 1 file, rem 1 file.
* `DREAMS.md` (repo root): 5 lines; nothing in *.py/*.ps1/*.json reads it.

## Step 5 — reading evidence in the logs, 18 Sep – 1 Oct 2026

EXPECTED: the brain's evidence is text assembled by core/knowledge.read; the older stores are not named. OBSERVED: no
log row in the window names any Step-2 store (searched in the whole JSON text of each row):

| log | rows | in window | rows naming a store | fields used |
|---|---|---|---|---|
| brain_journal.jsonl | 3,441 | 693 | 0 | kind, lang, payload, summary, ts |
| llm_provenance.jsonl | 13,152 | 3,572 | 0 | backend, caller, prompt_head, prompt_sha, step, ts, ... (29 fields) |
| brain_step_log.jsonl | 4,310 | 789 | 0 | expect, model, prev_note, step, stance, why, ts, ... (16 fields) |

brain_journal kinds in the window: constancy 384, phase_debrief 167, skip_decision 34, cycle_report 16, cycle_plan 15,
constellation 14, reconsider 14, mirror_read 14, cycle_review 14, feature_proposal 10. llm_provenance callers: brain
1,292, threading 1,109, (none) 978, reflex 94, source_registration 30, consult 25, internet_agent 20, ladder 12. No
provenance row names core/knowledge as caller. That the brain's evidence comes from core/knowledge.read is therefore
NOT visible in these logs; it is visible only in the code (Step 2: statements.jsonl is read by core/knowledge.py and
core/brain_needs.py).

## Step 6 — the table of the whole

| store | group | rows | last write UTC | writers (count) | readers (live; +tests) | CLASS |
|---|---|---|---|---|---|---|
| atoms/MANIFEST.json | KNOWLEDGE |  | 2026-10-01 18:00 | 1 | 0; +1 | NO-READER |
| cortex_memory/abstractions/essence.md | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:30 | 2 | 2; +0 | unclear (live reader; cycle path not traced) |
| cortex_memory/abstractions/hashes.json | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:30 | 2 | 1; +1 | unclear (live reader; cycle path not traced) |
| cortex_memory/abstractions/self_profile.json | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:30 | 5 | 2; +0 | unclear (live reader; cycle path not traced) |
| cortex_memory/abstractions/trends.json | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:30 | 8 | 8; +3 | unclear (live reader; cycle path not traced) |
| cortex_memory/hypotheses/causal_pending.json | CORTEX-MEMORY (old tiers) |  | 2026-07-04 18:26 | 1 | 1; +0 | unclear (live reader; cycle path not traced) |
| cortex_memory/hypotheses/pending.json | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:29 | 7 | 5; +3 | unclear (live reader; cycle path not traced) |
| cortex_memory/hypotheses/resolved.json | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:29 | 6 | 2; +1 | unclear (live reader; cycle path not traced) |
| cortex_memory/middle | CORTEX-MEMORY (old tiers) | 0 files | 2026-06-14 07:24 | 6 | 0; +0 | NO-READER |
| cortex_memory/state.json | CORTEX-MEMORY (old tiers) |  | 2026-10-02 00:30 | 23 | 1; +0 | unclear (live reader; cycle path not traced) |
| memory/_mem_trace.jsonl | OTHER | 2836 | 2026-08-21 14:41 | 1 | 0; +0 | NO-READER |
| memory/axis_history.json | CYCLE-HISTORY |  | 2026-10-02 00:07 | 17 | 9; +6 | unclear (live reader; cycle path not traced) |
| memory/blackbox.jsonl | PROOF | 3027 | 2026-10-03 19:00 | 9 | 3; +0 | REPORT-ONLY |
| memory/brain_journal.jsonl | BRAIN | 3441 | 2026-10-02 10:36 | 8 | 8; +10 | BRAIN-READ |
| memory/brain_needs.json | BRAIN |  | 2026-10-02 11:19 | 2 | 0; +0 | unclear (named, read not classified) |
| memory/brain_step_log.jsonl | BRAIN | 4310 | 2026-09-25 06:58 | 4 | 4; +0 | unclear (live reader; cycle path not traced) |
| memory/consolidation_latest.json | OTHER |  | 2026-10-01 23:10 | 2 | 1; +1 | unclear (live reader; cycle path not traced) |
| memory/consolidation_queue.json | OTHER |  | 2026-10-01 23:10 | 4 | 2; +1 | unclear (live reader; cycle path not traced) |
| memory/cycle_resume.jsonl | OTHER | 3766 | 2026-10-02 00:30 | 2 | 1; +1 | unclear (live reader; cycle path not traced) |
| memory/daily_tier.jsonl | OTHER | 3568 | 2026-10-02 00:06 | 8 | 5; +5 | unclear (live reader; cycle path not traced) |
| memory/development_journal.json | CYCLE-HISTORY |  | 2026-09-29 00:21 | 16 | 10; +2 | CYCLE-READ |
| memory/divergence_log.jsonl | OTHER | 4513 | 2026-10-02 00:30 | 2 | 2; +0 | unclear (live reader; cycle path not traced) |
| memory/existence_ledger.jsonl | PROOF | 421 | 2026-10-02 00:30 | 14 | 22; +12 | unclear (live reader; cycle path not traced) |
| memory/expression_stream.jsonl | OTHER | 8712 | 2026-10-03 18:41 | 3 | 1; +0 | REPORT-ONLY |
| memory/goal_score_history.json | CYCLE-HISTORY |  | 2026-10-02 00:29 | 19 | 9; +1 | unclear (live reader; cycle path not traced) |
| memory/hypothesis_intake_latest.json | OTHER |  | 2026-10-02 00:29 | 1 | 0; +0 | unclear (named, read not classified) |
| memory/hypothesis_resolution_latest.json | OTHER |  | 2026-10-02 00:29 | 1 | 0; +0 | unclear (named, read not classified) |
| memory/idea_stream.jsonl | OTHER | 1062 | 2026-10-01 23:10 | 4 | 1; +2 | unclear (live reader; cycle path not traced) |
| memory/improvement_proposals_archive.json | CYCLE-HISTORY |  | 2026-07-23 07:21 | 1 | 0; +0 | NO-READER |
| memory/knowledge_base.json | CYCLE-HISTORY |  | 2026-10-02 00:30 | 4 | 2; +2 | unclear (live reader; cycle path not traced) |
| memory/llm_provenance.jsonl | OTHER | 13152 | 2026-10-03 09:41 | 7 | 2; +2 | unclear (live reader; cycle path not traced) |
| memory/merkle_roots.jsonl | PROOF | 24 | 2026-10-02 00:30 | 5 | 6; +1 | unclear (live reader; cycle path not traced) |
| memory/night_events.jsonl | OTHER | 1367 | 2026-10-04 01:57 | 8 | 4; +3 | unclear (live reader; cycle path not traced) |
| memory/proposal_archive | CYCLE-HISTORY | 4 files | 2026-10-01 00:30 | 2 | 0; +0 | NO-READER |
| memory/pulse_stream.jsonl | OTHER | 16250 | 2026-10-02 11:19 | 4 | 2; +3 | unclear (live reader; cycle path not traced) |
| memory/revision_ledger.jsonl | OTHER | 41 | 2026-10-02 00:29 | 1 | 1; +2 | unclear (live reader; cycle path not traced) |
| memory/somatic_history.jsonl | OTHER | 1197 | 2026-10-03 18:38 | 4 | 2; +0 | unclear (live reader; cycle path not traced) |
| memory/source_lifecycle_ledger.jsonl | OTHER | 2070 | 2026-10-01 18:00 | 2 | 0; +0 | unclear (named, read not classified) |
| memory/space/base.metta | KNOWLEDGE | 264540 | 2026-10-02 10:28 | 2 | 5; +4 | BRAIN-READ |
| memory/space/derived.metta | KNOWLEDGE | 286 | 2026-10-02 10:28 | 2 | 1; +1 | REPORT-ONLY |
| memory/space/proposed.metta | KNOWLEDGE | 200 | 2026-10-02 10:32 | 3 | 1; +0 | REPORT-ONLY |
| memory/statements.jsonl | KNOWLEDGE | skip>200MB (wc -l 297,156) | 2026-10-02 11:19 | 3 | 3; +4 | BRAIN-READ |
| memory/training_log.jsonl | OTHER | 7593 | 2026-10-02 00:30 | 3 | 0; +0 | unclear (named, read not classified) |
| memory/verified_observations.jsonl | PROOF | 163 | 2026-10-01 18:00 | 6 | 4; +4 | unclear (live reader; cycle path not traced) |
| memory/vertical_ledger.jsonl | BRAIN | 3047 | 2026-10-02 11:20 | 4 | 2; +5 | unclear (live reader; cycle path not traced) |
| memory/witness.jsonl | PROOF | 196 | 2026-10-02 10:43 | 6 | 1; +1 | REPORT-ONLY |

**NO-READER:** atoms/MANIFEST.json, cortex_memory/middle, memory/_mem_trace.jsonl, memory/improvement_proposals_archive.json, memory/proposal_archive

**NO-WRITER:** none

**Last write older than 7 days:** cortex_memory/hypotheses/causal_pending.json (2026-07-04 18:26), cortex_memory/middle (2026-06-14 07:24), memory/_mem_trace.jsonl (2026-08-21 14:41), memory/brain_step_log.jsonl (2026-09-25 06:58), memory/improvement_proposals_archive.json (2026-07-23 07:21)

(essence.md: the class above comes from its readers' list; Step 3 traced by hand that cycle step 17 puts it into a
model prompt.)

**The two layers side by side (facts from Steps 1-5).** The nightly cycle's last run ended 2 Oct 00:30 UTC
(cortex_memory/state.json `last_cycle`, archive `cycle_000088` sealed). At 00:07–00:30 it wrote the old layer:
cortex_memory/state.json, abstractions/essence.md, trends.json, self_profile.json, hashes.json, the archive and
merkle_roots.jsonl; and memory/knowledge_base.json, goal_score_history.json, axis_history.json. The newer layer was
written later the same day by the brain's turns, not at 00:30: statements.jsonl 11:19, space/base.metta 10:28,
proposed.metta 10:32, vertical_ledger.jsonl 11:20, brain_needs.json 11:19; atoms/ last 1 Oct 18:00. The brain's last
turn in brain_journal is 2 Oct 10:32–10:36 (kinds symbols, feature_proposal) and its last model call in llm_provenance
2 Oct 11:10 (`brain:probe: read two numbers`). No log row from 18 Sep – 1 Oct names a store as evidence. By code (not
logs): the brain turn reads statements.jsonl (core/knowledge.py, core/brain_needs.py) and space/base.metta
(core/brain_needs.py, scripts/turn_brain.py); the cycle reads essence.md into the step-17 prompt; cortex_memory/middle/
is empty and nothing reads it.
