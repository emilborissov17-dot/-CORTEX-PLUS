# CYCLE LIVE — 2026-09-19 (manual run)

One line per step as it happens, from `memory/blackbox.jsonl` (fsync'd begin/end)
enriched with `core/step_contract.py` verdicts. Append-only, fsync per line: an
IN PROGRESS line is never rewritten, so if the cycle dies the last line names the
step it died in.

## THE COST OF RUNNING THIS BY HAND — recorded up front, not discovered later

Emil's decision, 19 Sep 2026, option 3: run the cycle manually now for a per-step
audit, and record what that costs.

A cycle was already sealed for 2026-09-19 (`state.json` → `last_cycle
2026-09-19T01:37:17Z`, `total_cycles 73`, 73 archive directories). A second seal
does **not** corrupt the Merkle chain or the existence ledger — both are
append-only, `cycle_000073` is untouched, and the new run becomes
`cycle_000074`.

What it does consume is the prophecy record. **Five predictions** were sealed at
`09:00:03Z` today against anchor `next_cycle_after::2026-09-19T01:52:01Z` and are
still unresolved:

| kind | step |
|---|---|
| `self_failure` | — |
| `self_duration` | — |
| `self_degraded` | — |
| `self_step_fail` | `cortex_reasoner` |
| `self_step_fail` | `cycle_report` |

`experiments/prophecy/self_forecast.py:407` resolves them against *the first
`CYCLE_FINISHED` after the anchor*, and applies **no origin filter** — the code
is aware manual runs exist (line 303 mentions "a scheduled run after a manual
one") but does not exclude them. So this hand-run daytime cycle becomes the night
those five predictions were about.

**No flag avoids it.** The runner's complete flag set is `--from --full --help
--only --pulse --resume --survival`; `--only/--from/--pulse/--help` are in
`_INSPECTION_ARGV` and never run a cycle at all. There is no `--no-seal` and no
`--dry-run`.

**`self_duration` is the worst affected, and there is precedent.** It has **n=7**
scored to date (not 4). Six were resolved against a scheduled `03:04` cycle. The
one prior off-schedule resolution — 2026-09-13, scored against a `20:39` cycle —
produced `actual = 3344.3s` against a nightly range of 6171–8504s, and is the
largest error in the entire series for **both** predictors:

| date | actual (s) | baseline err | learner err |
|---|---|---|---|
| 2026-09-11 | 7646.6 | 1316.2 | 194.6 |
| 2026-09-12 | 8503.9 | 857.3 | 857.3 |
| **2026-09-13** | **3344.3** | **5159.6** | **4940.7** |
| 2026-09-16 | 6826.0 | 397.2 | 397.2 |
| 2026-09-17 | 7430.7 | 604.7 | 604.7 |
| 2026-09-18 | 6171.5 | 1259.2 | 654.5 |
| 2026-09-19 | 6477.1 | 305.6 | 48.3 |

Every scheduled night sits between 305 and 1316. The single off-schedule night is
4–16× worse. Expect this run's row to be distorted the same way, and read the
`self_duration` scoreboard for 2026-09-19→20 as **one manual run in a series of
seven**, not as a normal night.

## Known blind spot in the numbering

`core/cycle_map.py` maps **75** steps. Only **44** reach the flight recorder; the
other **31** bypass `_run()` and emit no begin/end at all. They are listed in the
close-out as NOT INSTRUMENTED, which is a different statement from SKIPPED. The
recorder's names also differ from the map's (`body_scanner` vs `body_scan`), so
every name goes through `cycle_map.resolve()` before it is numbered.

## Steps

```

[cycle_watch] no new blackbox rows for 900s — stopping the follow. Steps still open: none
```

## Close-out

- steps that ENDED: **0**
- began and never ended: none
- mapped in core/cycle_map.py but NOT INSTRUMENTED (they bypass _run(), so the flight recorder never sees them — this is a blind spot, NOT a claim that they were skipped): **75**
    - boot
    - body_scan
    - canon_load
    - telegram_approvals
    - brain_briefing
    - notify_patches_and_initiatives
    - dependency_check
    - needs_reanalysis_scan
    - web_intelligence
    - global_indicators
    - daily_tier
    - sensorium_ingest
    - browser_scout
    - composers
    - grounding_ledger
    - llm_self_review_axes
    - trend_tracker
    - cortexstrategist
    - internet_intelligence
    - civilization_snapshots
    - planet_snapshots
    - human_snapshots
    - cosmos_snapshots
    - planetary_potential
    - energy_review
    - self_awareness
    - update_master
    - system_hypergraph
    - scoring_engine
    - alarm_bands
    - facade_self_check
    - auto_levels
    - level_reconcile
    - axis_history
    - goal_score_calculator
    - deduction
    - constancy_and_constellation
    - axis_feed
    - cognitive_orchestrator
    - brain_reconsider
    - body_scan
    - growth_planner
    - hyperclaw
    - hyperclaw_plan
    - github_publish
    - action_recommendations
    - self_observer
    - self_modifier
    - execute_patches
    - feedback_loop
    - resolve_hypotheses
    - belief_revision
    - hypothesis_intake
    - output_contracts
    - measurement_honesty
    - resolve_ideas
    - session_update
    - daily_analysis
    - data_scout
    - continuous_learning
    - merklememory_commit
    - merkle_verify
    - training_data_accumulation
    - metta_column
    - brain_relay
    - proposal_sla
    - needs_auth
    - learn_world
    - self_experiment
    - self_mirror
    - read_the_mirror
    - brain_debrief
    - cycle_report
    - cortex_scan
    - compass

---

## CORRECTION — the close-out above is WRONG, and it is my bug

At **13:39:34** the watcher stopped itself and wrote the close-out above. Read
literally it says the cycle ended having run nothing, with all 75 steps NOT
INSTRUMENTED. That is false. The cycle was alive and working the whole time
(worker pid 16996), inside `web_intelligence`, step 9 of 75.

**Cause.** I launched the watcher with `--idle-stop 900`, meaning "close the
report after 15 minutes of silence from `memory/blackbox.jsonl`". I chose that to
make the watcher close itself once the cycle finished. But 31 of the 75 steps
emit no begin/end at all, and this run spent its first **15 minutes** entirely
inside that uninstrumented prefix — `boot` through `web_intelligence`. So the
blackbox was legitimately silent for longer than the idle timer, and the timer
fired mid-cycle.

**An idle blackbox is not a finished cycle.** Silence means "inside an
uninstrumented step" at least as often as it means "over". Inferring liveness
from the absence of writes is the same class of error this repo keeps finding:
a missing signal read as a definite answer.

**Nothing was lost.** At the moment it stopped, `memory/blackbox.jsonl` held
exactly one row for this run — `cycle start` — so no step record was missed.

**Fixed, and the fix is why the report continues below.**

- `--idle-stop` is now gated on process liveness via `--watch-pid`: while the
  cycle process is alive the idle timer is continuously reset, so it can only
  fire after the cycle is genuinely gone.
- A restarted watcher no longer resumes from end-of-file. It seeks to the last
  `cycle/start` row, so it picks up everything this run has recorded rather than
  only what happens after the restart.

The step lines below come from the restarted watcher and cover the whole run.

## Steps (continued)

```
       earning_verifier             | LIFT_REVOKED | core/earning.py is in ALWAYS_FORBIDDEN (core/earning.py) — a patch that edits the verifier, the poli
[11/75] daily_tier                   |    1.07s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_030401.log, memory/cycle_trace/2026-09-19T03_04_01.664980_03_00.jsonl, memory/daily_tier.jsonl | contract yes
[19/75] internet_intelligence        |    0.77s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_030401.log | contract yes
```

---

## CORRECTION 2 — the three lines above carried the WRONG NIGHT'S NUMBERS

The lines emitted between 13:52 and 13:57 are withdrawn. Two defects in this
tool, both mine, both found by checking a number against its source instead of
trusting the column.

**(a) The seconds belonged to the 03:04 cycle.** The watcher enriched each step
from the newest `memory/steps/<cycle_id>_steps.jsonl`. But that per-cycle file is
written with the PREVIOUS run's contents at the START of a run — the file dated
`2026-09-19T03_04_01` was rewritten at 13:24:40 by this run's own boot. So
"newest by mtime" was last night's cycle all along. It reported
`[11/75] daily_tier | 1.07s`; this run's own blackbox span says **0.1s**, and
this run's contract row says **0.94s**. The file paths in those lines
(`cycle_2026-09-19_030401.log`) name the 03:04 cycle, which is what gave it away.

Fixed: contract rows now come from `memory/step_contract_latest.json`, which
carries a `cycle_id` and is rewritten as the run proceeds, and the SECONDS come
from this run's own `elapsed_s` span in the blackbox in preference to any
contract row.

**(b) A restarted watcher seeked to the wrong cycle.** `_offset_of_current_cycle`
counted offsets with `bytes.splitlines()`, which also splits on a bare carriage
return — and one blackbox row, `earning_verifier`'s revocation message, contains
one. `_iter_json` splits on newline only. The two disagreed by a row, so the
follower resumed inside a cycle that had ended hours earlier and replayed three
foreign `cycle/start` rows before reaching this one. That is why `cortexstrategist`
never got a line: its records were consumed while the follower was still
mis-aligned.

Fixed: both now split on newline only. Verified before restart — the corrected
offset yields 11 records, all from pid 16996, and nothing from any other run.

**No step record was lost.** `memory/blackbox.jsonl` is append-only and every row
this cycle has written is still on disk; the restarted watcher re-reads the run
from its own `cycle/start`. The lines below supersede the three above.

## Steps (restarted, corrected)

```
[11/75] daily_tier                   | IN PROGRESS
[11/75] daily_tier                   |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/daily_tier.jsonl | contract yes
[18/75] cortexstrategist             | IN PROGRESS  (recorded as cortex_strategist_agent)
[18/75] cortexstrategist             |    93.6s | OK       | memory/blackbox.jsonl, memory/chromadb/chroma.sqlite3, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, snapshots/cortex_strategist/cortex_strategist_snapshot_latest.json | contract yes
[19/75] internet_intelligence        | IN PROGRESS  (recorded as internet_agent)
[19/75] internet_intelligence        |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[20/75] civilization_snapshots       | IN PROGRESS  (recorded as civilization_snapshots_agent)
[20/75] civilization_snapshots       |    13.7s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, snapshots/civilization/economy_work/economy_work_snapshot_latest.json, snapshots/civilization/education_culture/education_culture_snapshot_latest.json, snapshots/civilization/governance_institutions/governance_institutions_snapshot_latest.json | contract yes
[21/75] planet_snapshots             | IN PROGRESS  (recorded as planet_snapshots_agent)
[21/75] planet_snapshots             |    62.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, snapshots/planet/climate_global_risk/climate_global_risk_snapshot_latest.json, snapshots/planet/ecosystems_biodiversity/ecosystems_biodiversity_snapshot_latest.json | contract yes
[22/75] human_snapshots              | IN PROGRESS  (recorded as human_snapshots_agent)
[22/75] human_snapshots              |    10.4s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/night_events.jsonl, snapshots/human/cognition_learning/cognition_learning_snapshot_latest.json, snapshots/human/culture_media/culture_media_snapshot_latest.json | contract yes
[26/75] self_awareness               |  2535.8s | OK       | - | contract no
```

---

## CORRECTION 3 — a one-byte offset drift was EATING step records

Symptom, visible in the block above: steps 23, 24 and 25 produced no line at
all, and `self_awareness` came out as **2535.8s** for a step the blackbox shows
took 2 seconds.

**Cause.** `_iter_json` walked `data.split(newline)` and counted the empty
element after a trailing newline as one consumed byte. Every poll of a file that
ends in a newline — which an append-only JSONL always does — therefore advanced
the offset ONE BYTE TOO FAR. The next read began one byte inside a line, that
line failed `json.loads`, and the bare `except` swallowed it. One record lost per
poll, silently, with the drift landing on whichever row happened to be next.

The 2535.8s is the same bug seen from the other end: `self_awareness`'s `begin`
row was the one eaten, so with no span start recorded the duration fell through
to the process's ABSOLUTE `elapsed_s` instead of the step's span. A number that
looks like a reading and is actually a clock.

**Fix.** The reader now consumes only up to the last newline: it finds
`data.rfind(newline)`, parses that prefix, and leaves any partial trailing line
for the next poll. Offsets can no longer drift.

**Proved before restarting, not after.** Feeding the same file to the parser in
many small incremental polls now returns exactly the same 21 records as a single
whole-file read — `IDENTICAL: True` — with every step's `begin` and `end` present
and in order.

**Nothing is unrecoverable.** `memory/blackbox.jsonl` is append-only and fsync'd,
so every row this cycle wrote is still on disk. The restarted watcher re-reads
the run from its own `cycle/start` and the block below is the complete, correct
sequence. Everything above this line is superseded.

## Steps (complete re-read)

```
[11/75] daily_tier                   | IN PROGRESS
[11/75] daily_tier                   |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/daily_tier.jsonl | contract yes
[18/75] cortexstrategist             | IN PROGRESS  (recorded as cortex_strategist_agent)
[18/75] cortexstrategist             |    93.6s | OK       | memory/blackbox.jsonl, memory/chromadb/chroma.sqlite3, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, snapshots/cortex_strategist/cortex_strategist_snapshot_latest.json | contract yes
[19/75] internet_intelligence        | IN PROGRESS  (recorded as internet_agent)
[19/75] internet_intelligence        |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[20/75] civilization_snapshots       | IN PROGRESS  (recorded as civilization_snapshots_agent)
[20/75] civilization_snapshots       |    13.7s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, snapshots/civilization/economy_work/economy_work_snapshot_latest.json, snapshots/civilization/education_culture/education_culture_snapshot_latest.json, snapshots/civilization/governance_institutions/governance_institutions_snapshot_latest.json | contract yes
[21/75] planet_snapshots             | IN PROGRESS  (recorded as planet_snapshots_agent)
[21/75] planet_snapshots             |    62.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, snapshots/planet/climate_global_risk/climate_global_risk_snapshot_latest.json, snapshots/planet/ecosystems_biodiversity/ecosystems_biodiversity_snapshot_latest.json | contract yes
[22/75] human_snapshots              | IN PROGRESS  (recorded as human_snapshots_agent)
[22/75] human_snapshots              |    10.4s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/night_events.jsonl, snapshots/human/cognition_learning/cognition_learning_snapshot_latest.json, snapshots/human/culture_media/culture_media_snapshot_latest.json | contract yes
[23/75] cosmos_snapshots             | IN PROGRESS  (recorded as cosmos_snapshots_agent)
[23/75] cosmos_snapshots             |   111.7s | DEGRADED | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, snapshots/cosmos/cosmic_resources/cosmic_resources_snapshot_latest.json, snapshots/cosmos/deep_time_risks/deep_time_risks_snapshot_latest.json | contract yes  <- answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned at its slice of B=148
[24/75] planetary_potential          | IN PROGRESS  (recorded as planetary_potential_agent)
[24/75] planetary_potential          |    92.7s | DEGRADED | memory/blackbox.jsonl, memory/body_sensorium/2026-09-19.jsonl, memory/body_sensorium/_last.json, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl | contract yes  <- answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned at its slice of B=94s
[25/75] energy_review                | IN PROGRESS  (recorded as energy_review_agent)
[25/75] energy_review                |    30.1s | DEGRADED | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl | contract yes  <- no tier answered within B=30s (no tier produced a result within B=30s (cloud=TIMEOUT, loca
[26/75] self_awareness               | IN PROGRESS  (recorded as self_awareness_agent)
[26/75] self_awareness               |     1.5s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, snapshots/self/self_snapshot_20260919_140630.json | contract yes
[30/75] alarm_bands                  | IN PROGRESS
[30/75] alarm_bands                  |     0.1s | OK       | memory/alarm_bands_latest.json | contract no
[33/75] level_reconcile              | IN PROGRESS
[33/75] level_reconcile              |     0.1s | OK       | memory/auto_levels.json, memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/level_corrections.jsonl | contract yes
[34/75] axis_history                 | IN PROGRESS
[34/75] axis_history                 |     0.0s | OK       | memory/axis_observations.jsonl, memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[35/75] goal_score_calculator        | IN PROGRESS
       goal_score_calculator        | ERROR | 
[39/75] cognitive_orchestrator       | IN PROGRESS  (recorded as orchestrator_grounded)
[39/75] cognitive_orchestrator       |     0.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/orchestration_grounded_latest.json | contract yes
[39/75] cognitive_orchestrator       |    31.7s | OK       | memory/blackbox.jsonl, memory/chromadb/chroma.sqlite3, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, memory/orchestration_latest.json | contract yes
[41/75] body_scan                    | IN PROGRESS  (recorded as body_scanner)
[41/75] body_scan                    |     2.5s | OK       | memory/adaptive_directives.json, memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, snapshots/body/body_snapshot_latest.json | contract yes
[42/75] growth_planner               | IN PROGRESS
[42/75] growth_planner               |    61.7s | OK       | - | contract no
[43/75] hyperclaw                    | IN PROGRESS  (recorded as hyperclaw_orchestrator)
[43/75] hyperclaw                    |   118.7s | DEGRADED | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, plans/plan-2026-09-19.md | contract yes  <- answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned at its slice of B=172
[44/75] hyperclaw_plan               | IN PROGRESS
[44/75] hyperclaw_plan               |     0.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[45/75] github_publish               | IN PROGRESS  (recorded as github_publisher)
[45/75] github_publish               |    51.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl, memory/night_events.jsonl | contract yes
[46/75] action_recommendations       | IN PROGRESS  (recorded as cortex_reasoner)
[46/75] action_recommendations       |    37.7s | OK       | memory/blackbox.jsonl, memory/causal_log.json, memory/chromadb/chroma.sqlite3, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/knowledge_base.json | contract yes
[47/75] self_observer                | IN PROGRESS
[47/75] self_observer                |   288.8s | DEGRADED | memory/blackbox.jsonl, memory/body_scan_latest.json, memory/body_sensorium/2026-09-19.jsonl, memory/body_sensorium/_last.json, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl | contract yes  <- answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned at its slice of B=689
[50/75] feedback_loop                | IN PROGRESS
[50/75] feedback_loop                |     0.3s | OK       | memory/blackbox.jsonl, memory/chromadb/chroma.sqlite3, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/feedback_log.json, memory/goal_score_history.json | contract yes
[51/75] resolve_hypotheses           | IN PROGRESS
[51/75] resolve_hypotheses           |     0.0s | OK       | memory/hypothesis_resolution_latest.json | contract no
[52/75] belief_revision              | IN PROGRESS
[52/75] belief_revision              |     0.0s | OK       | memory/belief_state.json, memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[53/75] hypothesis_intake            | IN PROGRESS
[53/75] hypothesis_intake            |     0.2s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/hypothesis_intake_latest.json | contract yes
[54/75] output_contracts             | IN PROGRESS
[54/75] output_contracts             |     0.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/output_contracts_latest.json | contract yes
[55/75] measurement_honesty          | IN PROGRESS
[55/75] measurement_honesty          |     0.0s | OK       | memory/measurement_honesty_latest.json | contract no
[56/75] resolve_ideas                | IN PROGRESS
[56/75] resolve_ideas                |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[57/75] session_update               | IN PROGRESS  (recorded as session_updater)
[57/75] session_update               |     1.9s | OK       | memory/blackbox.jsonl, memory/chromadb/chroma.sqlite3, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/session_2026-09-19.json | contract yes
[58/75] daily_analysis               | IN PROGRESS
[58/75] daily_analysis               |   897.7s | DEGRADED | daily/2026-09-19_analysis.json, memory/blackbox.jsonl, memory/body_sensorium/2026-09-19.jsonl, memory/body_sensorium/_last.json, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl | contract yes  <- answered by local_3b (qwen2.5:3b) after the cloud tier was abandoned at its slice of B=805
[59/75] data_scout                   | IN PROGRESS
[59/75] data_scout                   |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/discovered_data_sources.json | contract yes
[62/75] merkle_verify                | IN PROGRESS
[62/75] merkle_verify                |     0.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/merkle_verify_latest.json | contract yes
[64/75] metta_column                 | IN PROGRESS
[64/75] metta_column                 |     0.4s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/metta_assessment_latest.json | contract yes
[65/75] brain_relay                  | IN PROGRESS
[65/75] brain_relay                  |    22.2s | DEGRADED | memory/alarm_sent.json, memory/blackbox.jsonl, memory/brain_relay_cursor.json, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/llm_provenance.jsonl | contract yes  <- 23s against a learned p95 of 3s (x3)
[66/75] proposal_sla                 | IN PROGRESS
[66/75] proposal_sla                 |     0.0s | OK       | - | contract no
[67/75] needs_auth                   | IN PROGRESS
[67/75] needs_auth                   |     0.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/needs_auth_asked.json | contract yes
[68/75] learn_world                  | IN PROGRESS
[68/75] learn_world                  |     0.8s | OK       | memory/backend_order_measured.json, memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl, memory/learn_world_latest.json, memory/learner_state.json | contract yes
[69/75] self_experiment              | IN PROGRESS
[69/75] self_experiment              |     0.0s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/improvement_proposals.json, memory/self_experiments.json | contract yes
[70/75] self_mirror                  | IN PROGRESS
[70/75] self_mirror                  |     0.1s | OK       | memory/blackbox.jsonl, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/self_mirror_latest.json, memory/self_mirror_log.jsonl | contract yes
[71/75] read_the_mirror              | IN PROGRESS
[71/75] read_the_mirror              |   164.7s | OK       | memory/mirror_read_latest.json | contract no
[74/75] cortex_scan                  | IN PROGRESS
[74/75] cortex_scan                  |     0.1s | OK       | memory/blackbox.jsonl, memory/cortex_full_state.json, memory/cycle_logs/cycle_2026-09-19_102415.log | contract yes
[75/75] compass                      | IN PROGRESS
[75/75] compass                      |     0.7s | OK       | memory/blackbox.jsonl, memory/compass_latest.json, memory/cycle_logs/cycle_2026-09-19_102415.log, memory/cycle_trace/2026-09-19T10_24_15.804727_00_00.jsonl | contract yes
```

---

## CORRECTION 4 — the follower would not stop, because "alive" was measured wrong

The cycle worker exited at 15:11:38 and wrote its last blackbox row there. With
`--idle-stop 600` the follower should have closed this file at 15:21:38. At 15:23
it was still running.

**Cause.** `--idle-stop` is held off while the cycle process is alive — correct,
since silence means an uninstrumented step at least as often as it means "over".
But `_alive()` asked the wrong question: it called `OpenProcess` and treated a
handle as proof of life. Measured at 15:23:

    Get-Process 16996      -> GONE
    OpenProcess 16996      -> handle 312
    GetExitCodeProcess     -> 0        (259 = STILL_ACTIVE)

The process had exited twelve minutes earlier and another process was still
holding a handle to the corpse, so the PID remained openable. A PID that can be
named is not a process that is running.

**Fix.** `_alive()` now calls `GetExitCodeProcess` and returns True only for
STILL_ACTIVE (259). Verified: `_alive(16996) -> False`, `_alive(own pid) -> True`.

**Also fixed: a promise in this tool's own docstring.** The USAGE block advertised
`--summary` to close the file off. There was no such flag. It exists now, and the
close-out below was written with it.

## Close-out
```

## Close-out

- steps that ENDED: **42**
- **began and never ended: goal_score_calculator** — this is where it stopped.
- mapped in core/cycle_map.py but NOT INSTRUMENTED (they bypass _run(), so the flight recorder never sees them — this is a blind spot, NOT a claim that they were skipped): **31**
    - boot
    - canon_load
    - telegram_approvals
    - brain_briefing
    - notify_patches_and_initiatives
    - dependency_check
    - needs_reanalysis_scan
    - web_intelligence
    - global_indicators
    - sensorium_ingest
    - browser_scout
    - composers
    - grounding_ledger
    - llm_self_review_axes
