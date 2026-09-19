# Test triage — the 42 known-failing tests, 2026-09-19

> ## STATUS: THE BUCKETS AND THE "LETS THROUGH" COLUMN ARE UNVERIFIED HYPOTHESES
>
> **Added 19 Sep 2026, later the same day, at Emil's instruction.**
>
> This report was produced in **12m51s for 42 tests — about 18 seconds each**. That
> is enough to read a failure message. It is not enough to verify what a defect
> lets through, or whether a test still means anything. The "lets through" column
> in particular was written from the tests' own docstrings, which the sweep of
> that same day measured as **~12% wrong** (4 false in 33 hand-verified sentences).
>
> **Every entry below is a HYPOTHESIS until it carries a VERIFIED mark.**
>
> **The rate so far: of the five entries examined closely since, THREE did not
> hold.**
>
> | entry | claimed | verification showed |
> |---|---|---|
> | `test_heartbeat_coverage` (REAL_DEFECT #1) | the watchdog's ceiling is keyed on the beat id, so steps are killed early | **FALSE.** `supervisor.ceiling_for()` keys on the step NAME; `step_ceilings_sec` has 17 keys, all names, zero ids. Nothing was ever killed by this. The real defect was six misplaced boundary comments. |
> | `test_todays_coverage_is_still_thirteen` (OBSOLETE) | asserts a count we moved past; delete it | **BUCKET WRONG.** Its own docstring designates it a tripwire to be read and updated. Constant moved 13 → 14 (MATERIALS_WASTE_REVIEW became gradeable); test kept. |
> | `test_the_cli_refuses_without_claiming_the_cycle_lock` (OBSOLETE) | asserts prose for a refusal that was reworded; delete it | **BUCKET WRONG.** Five assertions, four of them behavioural (lock untouched, no trace, no boot block, exit 2). Only the fifth checked prose. Prose assertion deleted; the test kept. |
> | `test_consult_free_only` ×2 (REAL_DEFECT #2) | a paid model is not refused; doubled prefix | **HELD**, and was worse: the NVIDIA path added 11 Sep sits ABOVE both guarded paths and had no guard at all. |
> | `test_the_patch_is_applied_outside...` (ENVIRONMENT) | a stale worktree makes it red | **HELD.** `git worktree prune` turned it green with no product change. |
>
> Two of the three OBSOLETE calls were wrong in the same direction: I read a
> failing assertion and inferred the whole test was stale, when in each case the
> test was doing its job and one line inside it had rotted. Treat every remaining
> UNVERIFIED bucket with that in mind.

Read-only. Nothing was fixed and no test or module was edited **in the command that
produced this file**; later commits, marked per entry below, changed that.

**Source of the 42 node ids:** `memory/suite_runs.jsonl` — the `failed` list of the
last VALID run (ts `2026-09-19T12:51:30Z`). `tools/suite_gate.py` keeps no baseline
file of its own; the baseline IS the previous VALID record in that ledger.

**How they were run:** exactly those 42 node ids, `-q -rA --tb=short`, not the full
suite. Result: **40 failed, 2 passed in 186.88s**. The two that passed are the
finding in section FLAKY.

**None of the 42 carries `@pytest.mark.live_state`** — `pytest <42> -m live_state`
deselects all 42. That is by construction: the gate runs `-m "not live_state"`, so a
marked test can never enter this list. The LIVE_STATE bucket below is therefore
assigned by BEHAVIOUR, and every row in it is a test that moves with the world while
carrying no marker. That is the bucket's whole point.

**Born red vs rotted**, over 49 recorded full-suite runs (2026-08-29 … 2026-09-19):
**18 have never been green**, **24 have been green at least once**. The rotted ones
cluster hard: 6 last green on 2026-09-03 and 18 on 2026-09-08.

## Disposition after the 19 Sep sweep — VERIFIED or UNVERIFIED, per entry

Added at Emil's instruction. A bucket is **VERIFIED** only where this sweep read
the code and settled it. Where the action taken did not require settling the
bucket, it says **UNVERIFIED** and stays that way. Nothing here is tidied into
confidence.

### VERIFIED — the sweep read the code and settled it (11)

| entry | triage said | verification showed | action |
|---|---|---|---|
| `test_heartbeat_coverage::test_each_beat_reports_the_step_it_is_actually_in` | REAL_DEFECT #1 — beats are killed early because the ceiling keys on the id | **"lets through" FALSE.** `supervisor.ceiling_for()` keys on the step NAME; `step_ceilings_sec` has 17 keys, all names. Nothing was killed by this. The defect was real but different: six boundary comments did not sit above their own beat, which also let `test_every_step_boundary_beats` pass falsely for two headings with no beat. | fixed, `a57ea77` |
| `test_consult_free_only::…paid_model…` | REAL_DEFECT #2 — a paid model is not refused | **HELD, and worse.** `_ask_nvidia_kimi`, added 11 Sep, sits ABOVE both guarded paths, is tried first, and had no guard at all. | fixed, `131ef66` |
| `test_consult_free_only::…free_model…` | REAL_DEFECT — doubled provider prefix | **HELD**, and it is a label defect only: `backend` is branched on twice, both `!= "local"`. | fixed, `131ef66` |
| `test_axis_history::test_todays_coverage_is_still_thirteen` | OBSOLETE — delete it | **BUCKET WRONG.** Its own docstring designates it a tripwire: "read it, then update the constant." It fired correctly; coverage moved 13 → 14 (`MATERIALS_WASTE_REVIEW` became gradeable). | constant updated, test KEPT |
| `test_phase_resume::test_the_cli_refuses_without_claiming_the_cycle_lock` | OBSOLETE — delete it | **BUCKET WRONG.** Five assertions; four are behavioural (lock byte-identical, no trace written, no boot block, exit 2). Only the fifth checked prose. | prose assertion deleted, test KEPT |
| `test_script_suite::…[experiments/dreams/test_dream.py]` | OBSOLETE | **HELD.** The assertion demanded a delta from a prior record with no `config_fingerprint`; that behaviour was removed on purpose 15 Aug (`dream.py:293-307`). The fixture predates the rule. | obsolete assertion replaced by the refusal that replaced it |
| `test_self_improve_pipeline::test_the_patch_is_applied…nothing_survives` | ENVIRONMENT | **HELD.** One PRUNABLE leftover worktree from an earlier session. `git worktree prune` turned it green with no product change. | test hardened to assert its OWN sandbox, not a global worktree count |
| `test_self_improve_pipeline::test_the_ceiling_does_not_decide_the_merits` | ENVIRONMENT — "circular, the suite has reds" | **HELD, WRONG CAUSE.** Measured: `test_self_improve_requirer.py` is 104-green in the working tree and 2-red in a pristine `git worktree add --detach HEAD`. A worktree carries only TRACKED files. Not ordering — `pytest_randomly` is not installed and `-p no:randomly` changes nothing. | explicit `skipif` naming the two tests and the reason |
| `test_durable_writes` ×2 | FLAKY | **HELD, and the cause is not a polluter.** `durable._pending` is a module-global set — correct in production, one process one buffer, flushed at every `beat()`. The test asserted on the GLOBAL, so it measured the suite's residue. | buffer isolated per test; proven by seeding residue |
| `test_script_suite::…[test/test_no_exit_on_import.py]` | BROKEN_TEST | **HELD.** Every failure was `Broker-bot/_ARCHIVE/**` — a separate vendored project that `pytest.ini` excludes by name; this script walks the tree itself and did not inherit it. | `SKIP_PARTS` now matches `pytest.ini` |
| `test_p_survive` ×2 | BROKEN_TEST | **HELD.** Offenders were `claude/reports/*.md`, `docs/*.md` and `config/attention_map.json` — records, not prompts. Verified before narrowing: nothing under `core/` or `agents/` reads those trees into a prompt. Two genuine consumers surfaced (`experiments/prophecy/self_forecast.py` and its test) which seal the metric into the prophecy LEDGER. | scan scoped to prompts; consumers added to `ALLOWED` |
| `test_cycle_seals_its_own_completion::test_sealing_a_cycle_here…` | BROKEN_TEST | **HELD.** It asserted `memory/extra_calls_log.jsonl` does not exist "and no real cycle has run". A real cycle runs nightly; the file is 13841 bytes, written 15:11 on 19 Sep by the manual cycle. | replaced with a before/after fingerprint of the real files |

### UNVERIFIED — action taken did not require settling the bucket (15)

The fifteen LIVE_STATE entries were bucketed from the failure message alone, in
the ~18 seconds per test this report was produced at. This sweep gave each the
`@pytest.mark.live_state` marker, which removes them from a code gate — and that
action is safe whether or not the bucket is exactly right, because `pytest.ini`
already rules that a test whose outcome varies with live state is an operational
monitor rather than a correctness gate, and `tools/live_monitor.py` runs exactly
this complement.

**It does not verify them.** None was re-read against the code in this sweep.
Each remains an unverified hypothesis about WHY it moves with the world:

`test_belief_revision::test_the_two_june_hypotheses_are_skipped_rather_than_mislearned` ·
`test_corrections_27::test_the_annotation_comes_after_what_it_annotates` ·
`test_corrections_27::test_the_five_test_rows_are_still_there` ·
`test_level_reconciler::test_climate_global_risk_is_corrected_to_high_under_the_ruling` ·
`test_level_reconciler::test_social_relations_is_corrected_to_low_on_live_data` ·
`test_metta_parallel::test_the_disagreement_states_both_readings` ·
`test_metta_parallel::test_the_live_climate_fact_is_what_we_think_it_is` ·
`test_needs_auth::test_the_live_registry_shows_ucdp_active_and_eia_waiting` ·
`test_needs_auth::test_the_waiting_sources_reach_the_cycle_report` ·
`test_phase_evidence_swap::test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test` ·
`test_phase_evidence_swap::test_the_replay_script_reports_the_same_number` ·
`test_proposal_sla::test_there_are_no_patches_from_13_july` ·
`test_self_experiment::test_a_guarded_arm_counts_from_the_file_even_when_the_ordinal_disagrees` ·
`test_self_experiment::test_a_guarded_file_holding_neither_arm_still_refuses` ·
`test_self_experiment::test_the_other_ordinal_reads_the_same_guarded_arm`

A marker is a routing decision, not a finding. If any of these is in fact a real
defect wearing live-state clothes, the marker hides it, and only reading the code
will say. That is an open debt.

### UNVERIFIED — the remaining REAL_DEFECT entries (11 of 13)

Two of the thirteen have been verified (`test_heartbeat_coverage`,
`test_consult_free_only` ×2 count as one entry each). The other eleven carry
UNVERIFIED buckets and UNVERIFIED "lets through" claims, and Half B settles them
one at a time. Given the rate above — three of the first five examined did not
hold — expect roughly a third of what follows to change on contact.

## Counts

| bucket | tests |
|---|---|
| REAL_DEFECT | **16** |
| OBSOLETE | **3** |
| LIVE_STATE | **15** |
| BROKEN_TEST | **4** |
| ENVIRONMENT | **2** |
| FLAKY | **2** |
| total | 42 |

## Every test, one row

| # | node id | bucket | exception | assertion line | file last changed | ever green |
|---|---|---|---|---|---|---|
| 1 | `test/test_heartbeat_coverage.py::test_each_beat_reports_the_step_it_is_actually_in` | **REAL_DEFECT** | AssertionError | — | 2026-08-21 (09163bc) | never (49 runs) |
| 2 | `test/test_consult_free_only.py::PaidSubstitutionIsRefused::test_a_paid_model_serving_the_request_is_not_an_answer` | **REAL_DEFECT** | AssertionError | — | 2026-09-11 (2f3ec8e) | yes, last 2026-09-08 |
| 3 | `test/test_cycle_reaper.py::test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk` | **REAL_DEFECT** | KeyError | — | 2026-08-27 (cb70d0b) | never (49 runs) |
| 4 | `test/test_script_suite.py::test_script_style_suite[test/test_goal_score_package.py]` | **REAL_DEFECT** | unknown | — | 2026-08-15 (3bc920e) | never (49 runs) |
| 5 | `test/test_produces_has_a_reader.py::test_every_promised_path_has_an_entry` | **REAL_DEFECT** | AssertionError | — | 2026-09-08 (68aacb6) | yes, last 2026-09-08 |
| 6 | `test/test_verifier_inputs.py::test_every_verifier_declares_what_it_reads` | **REAL_DEFECT** | AssertionError | — | 2026-09-08 (163b114) | yes, last 2026-09-03 |
| 7 | `test/test_cadence_gate.py::test_how_many_of_the_thirteen_are_usable_tonight` | **REAL_DEFECT** | core.cadence.CadenceError | — | 2026-09-06 (9560e23) | yes, last 2026-09-08 |
| 8 | `test/test_cadence_gate.py::test_the_prompt_shows_both_tiers_with_next_expected_on_slow_lines` | **REAL_DEFECT** | AssertionError | — | 2026-09-06 (9560e23) | yes, last 2026-09-08 |
| 9 | `test/test_cadence_gate.py::test_every_source_in_the_real_specs_declares_a_cadence` | **REAL_DEFECT** | AssertionError | — | 2026-09-06 (9560e23) | yes, last 2026-09-03 |
| 10 | `test/test_direction_last.py::test_the_sealed_record_shows_direction_as_the_last_generated_field` | **REAL_DEFECT** | AssertionError | — | 2026-09-07 (f5de1c8) | yes, last 2026-09-08 |
| 11 | `test/test_quarantine_triage.py::test_the_scanner_does_not_read_itself` | **REAL_DEFECT** | AssertionError | — | 2026-08-15 (3bc920e) | yes, last 2026-09-08 |
| 12 | `test/test_gate_producers_declare.py::test_the_known_blind_list_has_not_gone_stale` | **REAL_DEFECT** | AssertionError | — | 2026-09-08 (8836a57) | yes, last 2026-09-08 |
| 13 | `test/test_consult_free_only.py::PaidSubstitutionIsRefused::test_a_free_model_serving_the_request_is_an_answer` | **REAL_DEFECT** | AssertionError | — | 2026-09-11 (2f3ec8e) | yes, last 2026-09-08 |
| 14 | `test/test_ci_contract.py::test_the_test_job_uses_the_network_flag` | **REAL_DEFECT** | AssertionError | — | 2026-08-22 (cc72683) | yes, last 2026-09-03 |
| 15 | `test/test_ci_contract.py::test_no_hardcoded_drive_letters_in_code` | **REAL_DEFECT** | AssertionError | — | 2026-08-22 (cc72683) | never (49 runs) |
| 16 | `test/test_script_suite.py::test_script_style_suite[test/test_needs_approvals.py]` | **REAL_DEFECT** | unknown | — | 2026-08-15 (3bc920e) | never (49 runs) |
| 17 | `test/test_axis_history.py::test_todays_coverage_is_still_thirteen` | **OBSOLETE** | AssertionError | — | 2026-09-06 (9560e23) | yes, last 2026-09-08 |
| 18 | `test/test_phase_resume.py::test_the_cli_refuses_without_claiming_the_cycle_lock` | **OBSOLETE** | AssertionError | — | 2026-09-13 (fd5151c) | never (49 runs) |
| 19 | `test/test_script_suite.py::test_script_style_suite[experiments/dreams/test_dream.py]` | **OBSOLETE** | unknown | — | 2026-08-15 (3bc920e) | never (49 runs) |
| 20 | `test/test_belief_revision.py::test_the_two_june_hypotheses_are_skipped_rather_than_mislearned` | **LIVE_STATE** | unknown | — | 2026-09-04 (30ea472) | yes, last 2026-09-08 |
| 21 | `test/test_corrections_27.py::test_the_annotation_comes_after_what_it_annotates` | **LIVE_STATE** | unknown | — | 2026-08-23 (82a457b) | never (49 runs) |
| 22 | `test/test_corrections_27.py::test_the_five_test_rows_are_still_there` | **LIVE_STATE** | AssertionError | — | 2026-08-23 (82a457b) | never (49 runs) |
| 23 | `test/test_level_reconciler.py::test_climate_global_risk_is_corrected_to_high_under_the_ruling` | **LIVE_STATE** | AssertionError | — | 2026-09-18 (a4befb8) | never (49 runs) |
| 24 | `test/test_level_reconciler.py::test_social_relations_is_corrected_to_low_on_live_data` | **LIVE_STATE** | AssertionError | — | 2026-09-18 (a4befb8) | never (49 runs) |
| 25 | `test/test_metta_parallel.py::test_the_disagreement_states_both_readings` | **LIVE_STATE** | KeyError | — | 2026-08-30 (5ba9112) | never (49 runs) |
| 26 | `test/test_metta_parallel.py::test_the_live_climate_fact_is_what_we_think_it_is` | **LIVE_STATE** | AssertionError | — | 2026-08-30 (5ba9112) | never (49 runs) |
| 27 | `test/test_needs_auth.py::test_the_live_registry_shows_ucdp_active_and_eia_waiting` | **LIVE_STATE** | KeyError | — | 2026-08-21 (64ed73a) | never (49 runs) |
| 28 | `test/test_needs_auth.py::test_the_waiting_sources_reach_the_cycle_report` | **LIVE_STATE** | unknown | — | 2026-08-21 (64ed73a) | never (49 runs) |
| 29 | `test/test_phase_evidence_swap.py::test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test` | **LIVE_STATE** | AssertionError | — | 2026-08-21 (070463b) | never (49 runs) |
| 30 | `test/test_phase_evidence_swap.py::test_the_replay_script_reports_the_same_number` | **LIVE_STATE** | AssertionError | — | 2026-08-21 (070463b) | never (49 runs) |
| 31 | `test/test_proposal_sla.py::test_there_are_no_patches_from_13_july` | **LIVE_STATE** | AssertionError | — | 2026-08-22 (cc72683) | yes, last 2026-09-03 |
| 32 | `test/test_self_experiment.py::test_a_guarded_arm_counts_from_the_file_even_when_the_ordinal_disagrees` | **LIVE_STATE** | AssertionError | — | 2026-09-11 (6c55bb4) | yes, last 2026-09-08 |
| 33 | `test/test_self_experiment.py::test_a_guarded_file_holding_neither_arm_still_refuses` | **LIVE_STATE** | AssertionError | — | 2026-09-11 (6c55bb4) | yes, last 2026-09-08 |
| 34 | `test/test_self_experiment.py::test_the_other_ordinal_reads_the_same_guarded_arm` | **LIVE_STATE** | AssertionError | — | 2026-09-11 (6c55bb4) | yes, last 2026-09-08 |
| 35 | `test/test_cycle_seals_its_own_completion.py::test_sealing_a_cycle_here_leaves_the_real_ledgers_alone` | **BROKEN_TEST** | AssertionError | — | 2026-08-28 (724ee79) | never (49 runs) |
| 36 | `test/test_p_survive.py::test_nothing_outside_the_allowed_files_mentions_it_in_code` | **BROKEN_TEST** | AssertionError | — | 2026-08-23 (70e1f8b) | yes, last 2026-09-03 |
| 37 | `test/test_p_survive.py::test_the_recorded_line_is_not_written_where_a_prompt_reads` | **BROKEN_TEST** | AssertionError | — | 2026-08-23 (70e1f8b) | yes, last 2026-09-08 |
| 38 | `test/test_script_suite.py::test_script_style_suite[test/test_no_exit_on_import.py]` | **BROKEN_TEST** | ImportError | — | 2026-08-15 (3bc920e) | yes, last 2026-09-03 |
| 39 | `test/test_self_improve_pipeline.py::test_the_ceiling_does_not_decide_the_merits` | **ENVIRONMENT** | AssertionError | — | 2026-09-08 (5b6043c) | yes, last 2026-09-08 |
| 40 | `test/test_self_improve_pipeline.py::test_the_patch_is_applied_outside_the_repository_and_nothing_survives` | **ENVIRONMENT** | AssertionError | — | 2026-09-08 (5b6043c) | yes, last 2026-09-08 |
| 41 | `test/test_durable_writes.py::test_a_batched_append_is_only_guaranteed_after_the_barrier` | **FLAKY** | PASSED in isolation | — | 2026-08-23 (130555b) | yes, last 2026-09-08 |
| 42 | `test/test_durable_writes.py::test_the_barrier_uses_a_writable_handle` | **FLAKY** | PASSED in isolation | — | 2026-08-23 (130555b) | yes, last 2026-09-08 |

## Evidence, per test

### REAL_DEFECT — 16

**`test/test_heartbeat_coverage.py::test_each_beat_reports_the_step_it_is_actually_in`**

> AssertionError: These beats report a different step id than their boundary:

- **Module / config at fault:** `core/../fast_cycle_runner beat ids`
- Six beats report a step id that is not their boundary: step 2 beats as '2.5', 12.45 as '12.42', 12.6 as '12.56', 12.7 as '12.65', 25.4 as '25.35', 25.37 as '25.38'. Static read of the runner, no live state.

**`test/test_consult_free_only.py::PaidSubstitutionIsRefused::test_a_paid_model_serving_the_request_is_not_an_answer`**

> AssertionError: True is not false : отговор от платен модел беше приет — пазачът го няма

- **Module / config at fault:** `core consult/free-only guard`
- 'a paid model answer was accepted - the guard is not there'. The refusal this class exists to enforce does not fire.

**`test/test_cycle_reaper.py::test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk`**

> KeyError: 'exit_code'

- **Module / config at fault:** `cycle reaper`
- KeyError: 'exit_code' - the reaper does not leave the spawned cycle's exit code on disk, so how a cycle died is unrecorded.

**`test/test_script_suite.py::test_script_style_suite[test/test_goal_score_package.py]`**

> Failed: test/test_goal_score_package.py exited 1

- **Module / config at fault:** `core/phase_evidence.py:333, scripts/migrate_pin_score_meaning.py:93`
- 2 of 12397 files read composite_score WITHOUT its coverage package, which the 15 Aug rule forbids: a bare composite is a dark number.

**`test/test_produces_has_a_reader.py::test_every_promised_path_has_an_entry`**

> AssertionError: these paths are promised by config/cycle_phases.json and have NO entry in config/produces_readers.json. Name a reader, or stop producing them:

- **Module / config at fault:** `config/produces_readers.json`
- memory/backend_order_measured.json, memory/daily_tier.jsonl, memory/learn_world_latest.json are promised by config/cycle_phases.json with no entry. All three DO have readers in code, so it is a declaration gap.

**`test/test_verifier_inputs.py::test_every_verifier_declares_what_it_reads`**

> AssertionError: these steps are in core.notary.VERIFIERS with NO declared inputs in config/step_inputs.json:

- **Module / config at fault:** `config/step_inputs.json`
- steps in core.notary.VERIFIERS have no declared inputs, so a verifier can read anything and nothing checks it.

**`test/test_cadence_gate.py::test_how_many_of_the_thirteen_are_usable_tonight`**

> core.cadence.CadenceError: indicator 'MATERIALS_WASTE_REVIEW' has no declared cadence in indicator_cadence.json

- **Module / config at fault:** `config/indicator_cadence.json`
- core.cadence.CadenceError: indicator 'MATERIALS_WASTE_REVIEW' has no declared cadence. RAISES rather than asserts.

**`test/test_cadence_gate.py::test_the_prompt_shows_both_tiers_with_next_expected_on_slow_lines`**

> AssertionError:   MATERIALS_WASTE_REVIEW: 9.6359  [unit: percent of GNI; means: adjusted net savings pct; GOOD_DIRECTION: up]  (cadence UNDECLARED - any deadline will be refused)

- **Module / config at fault:** `config/indicator_cadence.json`
- MATERIALS_WASTE_REVIEW reaches the prompt tagged 'cadence UNDECLARED'. Same root as the above.

**`test/test_cadence_gate.py::test_every_source_in_the_real_specs_declares_a_cadence`**

> AssertionError: 1 of 82 sources declare no cadence: WATER_REVIEW/anchor_annual/promoted_27965

- **Module / config at fault:** `config/composer_specs.json`
- 1 of 82 sources declares no cadence: WATER_REVIEW/anchor_annual/promoted_27965 - a promoted source that skipped the declaration.

**`test/test_direction_last.py::test_the_sealed_record_shows_direction_as_the_last_generated_field`**

> AssertionError: assert None == 'DOWN'

- **Module / config at fault:** `the sealing path under test`
- assert None == 'DOWN' - sealed_direction is absent. Fully hermetic (tmp_path fixture), so this is code, not world.

**`test/test_quarantine_triage.py::test_the_scanner_does_not_read_itself`**

> AssertionError: the tool's own documentation must not count as a loader

- **Module / config at fault:** `triage_quarantine.py`
- A pure unit call, T._wiring('P = "registry.json"', 'probe.py'), still counts the tool's own documentation as a loader, so an orphan artifact looks read.

**`test/test_gate_producers_declare.py::test_the_known_blind_list_has_not_gone_stale`**

> AssertionError: these are in KNOWN_BLIND but are no longer blind: ['self_observer']. Remove them from KNOWN_BLIND in the commit that declared them.

- **Module / config at fault:** `KNOWN_BLIND list`
- 'self_observer' is in KNOWN_BLIND but is no longer blind - the exemption outlived the reason for it.

**`test/test_consult_free_only.py::PaidSubstitutionIsRefused::test_a_free_model_serving_the_request_is_an_answer`**

> AssertionError: 'nvidia:nvidia/nemotron-3-super-120b-a12b:free' != 'nvidia/nemotron-3-super-120b-a12b:free'

- **Module / config at fault:** `model id normalisation`
- 'nvidia:nvidia/nemotron-3-super-120b-a12b:free' != 'nvidia/nemotron-3-super-120b-a12b:free' - the provider prefix is applied twice.

**`test/test_ci_contract.py::test_the_test_job_uses_the_network_flag`**

> AssertionError: the pipeline does not use the marker this file exists to protect

- **Module / config at fault:** `CI workflow`
- 'the pipeline does not use the marker this file exists to protect' - the network marker is registered and CI no longer selects on it, so the flag is decoration.

**`test/test_ci_contract.py::test_no_hardcoded_drive_letters_in_code`**

> AssertionError: hardcoded drive letters make a path mean different things on different platforms:

- **Module / config at fault:** `core/receptors.py:695`
- One production hit: a hardcoded C:\Windows\System32 firewall log path. The other 7 hits are sample strings inside test files, which is noise the test does not separate.

**`test/test_script_suite.py::test_script_style_suite[test/test_needs_approvals.py]`**

> Failed: test/test_needs_approvals.py exited 1

- **Module / config at fault:** `needs/approvals brief`
- 'the inline hint stays in the brief (extras are an addition, not a move)' - the hint was moved out instead of kept alongside.


### OBSOLETE — 3

**`test/test_axis_history.py::test_todays_coverage_is_still_thirteen`**

> AssertionError: measured_axes() now returns 14, was 13 on 6 Sep

- measured_axes() returns 14, was 13 on 6 Sep. The count rose because axes were repaired on purpose; the tripwire pins a number we deliberately moved past.

**`test/test_phase_resume.py::test_the_cli_refuses_without_claiming_the_cycle_lock`**

> AssertionError: assert 'REFUSING --from' in '[PHASE] no cycle_id: neither CORTEX_CYCLE_ID nor a readable memory/cycle.lock. There is no cycle to resume into.\n'

- Asserts the literal string 'REFUSING --from'. The CLI does refuse, with reworded text: 'no cycle_id: neither CORTEX_CYCLE_ID nor a readable memory/cycle.lock. There is no cycle to resume'. The behaviour holds; the prose moved.

**`test/test_script_suite.py::test_script_style_suite[experiments/dreams/test_dream.py]`**

> Failed: experiments/dreams/test_dream.py exited 1

- '[FAIL] delta computed = None'. dream.py refuses a delta when the prior record carries no config_fingerprint (the 15 Aug rule). The fixture writes {'date':..., 'composite_score':0.52} with no fingerprint, so the refusal is correct and the fixture predates it.


### LIVE_STATE — 15

**`test/test_belief_revision.py::test_the_two_june_hypotheses_are_skipped_rather_than_mislearned`**

> assert 11 == 0

- assert 11 == 0 - counts hypotheses in the live store, which has grown since June.

**`test/test_corrections_27.py::test_the_annotation_comes_after_what_it_annotates`**

> assert None == 'ANNOTATION'

- assert None == 'ANNOTATION' - ordering assertion over the same live history file.

**`test/test_corrections_27.py::test_the_five_test_rows_are_still_there`**

> AssertionError: a history line was deleted: 41

- Pins memory/p_survive_history.jsonl to exactly 5 non-ANNOTATION rows; the live append-only file now holds 41. The message says 'a history line was deleted' and prints the count, which reads backwards.

**`test/test_level_reconciler.py::test_climate_global_risk_is_corrected_to_high_under_the_ruling`**

> AssertionError:

- Asserts a correction over today's scored levels. Same file carries @pytest.mark.live_state on a sibling at line 122; this one does not.

**`test/test_level_reconciler.py::test_social_relations_is_corrected_to_low_on_live_data`**

> AssertionError:

- Name says it: 'on_live_data'. Unmarked while siblings in the same file are marked.

**`test/test_metta_parallel.py::test_the_disagreement_states_both_readings`**

> KeyError: 'level'

- KeyError: 'level' - reads today's level output, which no longer carries the key for that axis.

**`test/test_metta_parallel.py::test_the_live_climate_fact_is_what_we_think_it_is`**

> AssertionError: auto_levels no longer says LOW: HIGH

- 'auto_levels no longer says LOW: HIGH' - asserts today's computed level. Three siblings in this file carry the marker; this one does not.

**`test/test_needs_auth.py::test_the_live_registry_shows_ucdp_active_and_eia_waiting`**

> KeyError: 'eia_api'

- KeyError: 'eia_api' - asserts the contents of the live source registry, which changed when the source set changed.

**`test/test_needs_auth.py::test_the_waiting_sources_reach_the_cycle_report`**

> assert False

- assert False over the same live registry.

**`test/test_phase_evidence_swap.py::test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test`**

> AssertionError: survived=['B_SENSE'] rejected=['A_ORIENT', 'C_SNAPSHOT', 'D_SCORE', 'E_PROPOSE', 'F_SELF'] — expected D_SCORE alone

- survived=['B_SENSE'] rejected=[...] - expected D_SCORE alone. Which phase survives depends on the night's debriefs.

**`test/test_phase_evidence_swap.py::test_the_replay_script_reports_the_same_number`**

> AssertionError: assert 'B_SENSE' == 'D_SCORE'

- assert 'B_SENSE' == 'D_SCORE' - same live dependency as its sibling.

**`test/test_proposal_sla.py::test_there_are_no_patches_from_13_july`**

> AssertionError: oldest is 52.3 days

- 'oldest is 52.3 days'. An SLA tripwire measuring a human's unanswered queue; the number grows every day with no code change.

**`test/test_self_experiment.py::test_a_guarded_arm_counts_from_the_file_even_when_the_ordinal_disagrees`**

> AssertionError: but the guarded arm is whatever the file holds

- 'but the guarded arm is whatever the file holds' - reads the live guarded file.

**`test/test_self_experiment.py::test_a_guarded_file_holding_neither_arm_still_refuses`**

> AssertionError: assert 'neither arm' in 'config/scheduler.json was edited at 2026-09-18T23:50:01, after this cycle ended at 2026-09-02T00:00:00 — what was in force then cannot be established from the file'

- The failure names it outright: 'config/scheduler.json was edited at 2026-09-18T23:50:01, after this cycle ended at 2026-09-02T00:00:00'. The assertion depends on when a live config was last touched.

**`test/test_self_experiment.py::test_the_other_ordinal_reads_the_same_guarded_arm`**

> AssertionError: assert (None == 'b')

- assert (None == 'b') - same live guarded file.


### BROKEN_TEST — 4

**`test/test_cycle_seals_its_own_completion.py::test_sealing_a_cycle_here_leaves_the_real_ledgers_alone`**

> AssertionError: memory/extra_calls_log.jsonl exists, and no real cycle has run: a test wrote it

- Asserts memory/extra_calls_log.jsonl does not exist 'and no real cycle has run: a test wrote it'. A real cycle DID run (13841 bytes, 15:11 today, and the run logged 'extra calls: 0 attempt(s)'). The premise is false on the machine that runs the system.

**`test/test_p_survive.py::test_nothing_outside_the_allowed_files_mentions_it_in_code`**

> AssertionError: ['claude/reports/HANDOFF_5SEP_0115.md', 'claude/reports/TRACE_2026-09-17.md', 'config/attention_map.json', 'docs/HANDOVER_2026-09-10.md', 'docs/QUEUE.md', 'experiments/prophecy/self_forecast.py', ...]

- Every hit is documentation, not code: claude/reports/HANDOFF_5SEP_0115.md, claude/reports/TRACE_2026-09-17.md, config/attention_map.json, docs/HANDOVER_2026-09-10.md. The rule is about what reaches a model; it is scanning prose.

**`test/test_p_survive.py::test_the_recorded_line_is_not_written_where_a_prompt_reads`**

> AssertionError: ['claude/reports/SUITE_2026-09-12.log', 'claude/reports/SUITE_2026-09-13_1622.log', 'claude/reports/TRACE_2026-09-17.md', 'config/attention_map.json']

- Same shape: hits are claude/reports/SUITE_*.log and TRACE_*.md - a log that RECORDS the guard firing is counted as a leak of it.

**`test/test_script_suite.py::test_script_style_suite[test/test_no_exit_on_import.py]`**

> Failed: test/test_no_exit_on_import.py exited 1

- Fails only on Broker-bot/_ARCHIVE/* files. pytest.ini excludes Broker-bot and _ARCHIVE by norecursedirs precisely because it is a separate vendored project; this script walks the tree itself and does not honour that.


### ENVIRONMENT — 2

**`test/test_self_improve_pipeline.py::test_the_ceiling_does_not_decide_the_merits`**

> AssertionError: a patch that applies, stays in scope, keeps the tests green and has a recomputable metric did not pass on merits: failed on tests_pass: tests_pass: pytest exited 1 on ['test/test_self_improve_requirer.py'

- 'did not pass on merits: failed on tests_pass'. The merit check runs pytest inside itself, and this suite currently has 42 reds, so it can never report green here. Circular on this machine.

**`test/test_self_improve_pipeline.py::test_the_patch_is_applied_outside_the_repository_and_nothing_survives`**

> AssertionError: a sandbox worktree survived: ['C:/Users/emilb/Desktop/AGI/CORTEX++_MERGED                      00c269e [experimental/self-mod]', 'C:/Users/emilb/AppData/Local/Temp/selfmod_sandbox_wpfl8y3r/tree 8cf7b69 (d

- 'a sandbox worktree survived'. git worktree list shows a stale PRUNABLE leftover, C:/Users/.../Temp/selfmod_sandbox_wpfl8y3r/tree, from an earlier session. This run's own sandbox was cleaned (the preceding assert passed). Clears with git worktree prune.


### FLAKY — 2

**`test/test_durable_writes.py::test_a_batched_append_is_only_guaranteed_after_the_barrier`**

- PASSES alone 3/3 and 13/13 with its own file; fails only inside the full suite. Order-dependent, not a code defect.

**`test/test_durable_writes.py::test_the_barrier_uses_a_writable_handle`**

- PASSES alone 3/3 and 13/13 with its own file; fails only inside the full suite. Order-dependent.


## REAL_DEFECT, ordered by what each one would let through

| rank | node id | what it would let through |
|---|---|---|
| 1 | `test/test_heartbeat_coverage.py::test_each_beat_reports_the_step_it_is_actually_in` | A slow step killed early and a log pointing at the wrong step. The watchdog's per-step ceiling is keyed on the beat id, so six steps are timed against another step's budget. This is the mechanism that decides WHERE a night stopped. |
| 2 | `test/test_consult_free_only.py::PaidSubstitutionIsRefused::test_a_paid_model_serving_the_request_is_not_an_answer` | A paid model answering a request that must be free-only, silently. The whole point of the class is that this cannot happen. |
| 3 | `test/test_cycle_reaper.py::test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk` | A cycle dying with no exit code on disk — the cause of death unrecorded, which is the question asked after every kill. |
| 4 | `test/test_script_suite.py::test_script_style_suite[test/test_goal_score_package.py]` | A composite score reaching a consumer without its coverage package: a bare number read as truth. Exactly the defect that killed the cycle at step 35 today. |
| 5 | `test/test_produces_has_a_reader.py::test_every_promised_path_has_an_entry` | An indicator with no declared cadence entering the night, so 'fresh' and 'stale' cannot be told apart for it. |
| 6 | `test/test_verifier_inputs.py::test_every_verifier_declares_what_it_reads` | The same undeclared indicator reaching the model prompt tagged UNDECLARED. |
| 7 | `test/test_cadence_gate.py::test_how_many_of_the_thirteen_are_usable_tonight` | A promoted source that skipped its cadence declaration — the promotion path does not enforce what the manual path does. |
| 8 | `test/test_cadence_gate.py::test_the_prompt_shows_both_tiers_with_next_expected_on_slow_lines` | A file the cycle writes that nobody has claimed to read. Three such paths right now. |
| 9 | `test/test_cadence_gate.py::test_every_source_in_the_real_specs_declares_a_cadence` | A verifier that reads whatever it likes with no declared inputs, so its evidence cannot be checked. |
| 10 | `test/test_direction_last.py::test_the_sealed_record_shows_direction_as_the_last_generated_field` | A sealed record with no direction field — the round exists to prove direction came last, and it is absent. |
| 11 | `test/test_quarantine_triage.py::test_the_scanner_does_not_read_itself` | An orphan artifact looking read because the scanner counts its own documentation as a loader. This is the tool that decides what is dead weight. |
| 12 | `test/test_gate_producers_declare.py::test_the_known_blind_list_has_not_gone_stale` | A stale exemption: a step listed as blind that is no longer blind, so the blind list stops meaning anything. |
| 13 | `test/test_consult_free_only.py::PaidSubstitutionIsRefused::test_a_free_model_serving_the_request_is_an_answer` | A doubled provider prefix in a model id — the request goes to a name that does not exist. |
| 14 | `test/test_ci_contract.py::test_the_test_job_uses_the_network_flag` | CI running without the network marker it registered, so `-m 'not network'` selects nothing and the flag is decoration. |
| 15 | `test/test_ci_contract.py::test_no_hardcoded_drive_letters_in_code` | A hardcoded Windows path in production code (`core/receptors.py:695`), which means something different on the Linux CI leg. |
| 16 | `test/test_script_suite.py::test_script_style_suite[test/test_needs_approvals.py]` | An inline hint moved out of the brief instead of kept beside it — the human reads the brief without the hint. |

The first four are the ones I would act on. Ranks 5–9 are all one shape — a
declaration that was never made — and they are cheap: they need a config entry, not
a code change.

## What is NOT a code defect

**15 LIVE_STATE tests are sitting in a code gate.** Every one asserts something that
moves with the world — a count in an append-only ledger, today's computed level, the
age of a human's unanswered queue, when `config/scheduler.json` was last edited. None
carries the marker that exists for exactly this, so each one is a permanent red that
no commit can clear. `pytest.ini` already states the rule: *'A gating test must be
deterministic; any test whose outcome varies with live state is an operational
monitor, not a correctness gate.'*

**2 FLAKY.** `test_durable_writes` passes 3/3 alone and 13/13 with its own file, and
fails only inside the full suite — order-dependent, proven by rerun, not a defect in
the code it tests.

**2 ENVIRONMENT.** One clears with `git worktree prune`; the other runs pytest inside
itself and so cannot go green while the suite has any red at all.

**4 BROKEN_TEST.** Two scan documentation and count a report that RECORDS a guard
firing as a leak of it; one asserts no real cycle has ever run on a machine that runs
one nightly; one walks a vendored project `pytest.ini` deliberately excludes.

