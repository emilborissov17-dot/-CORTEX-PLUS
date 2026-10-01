# Taxonomy implementation — 1 Oct 2026

This command replaces the earlier "D1-W draft / STEP_STATUS" command. That command had **already finished** before this one arrived, so there was nothing to stop. It left the following on disk:

- `claude/reports/STEP_STATUS_2026-10-01.md` — committed and pushed as `1677820`.
- `experiments/track_w/` (PREREG_W.md, prereg_w.json, release_dates.json, build_prereg_inputs.py) — committed and pushed as `27ec63f`.
- `claude/reports/D1W_DRAFT_2026-10-01.md` — **untracked** (it was not in either named commit).
- `data/external/views/wiki_Available-datasets.md` — a gitignored download.
- **No uncommitted code.**

## What does not work (read first)

1. **The world is barely seen: SEEN 2/105.** The two are C1.1 (greenhouse-gas concentrations) and C5.1 (geophysical hazards).
   - 67 of the 105 world subcategories have **no live key at all**.
   - Of the 38 that do have keys, 36 fail CHANGE, usually because the key has no registered observation date or carries only a year.
   - 25 of those 36 also fail SOURCE: every one of their sources is `self_reported` or `unknown`.
   - Domain E: 0/18.
2. **E1 (the body) can never be SEEN today. Two reasons:**
   - `memory/somatic_history.jsonl` rows carry only `ts`. `config/field_names.json` registers `ts` as a processing time, not an observation date, so every E1 key reads date MISSING.
   - The history itself stopped on 26 Sep (3e). It is written only while the cockpit server runs, and the server is not running.
3. **C5.1 is SEEN by the rule as written, but through different keys.**
   - CHANGE comes from `quakes.quake_m45_count` (dated via `last_date`, class `unknown`).
   - SOURCE comes from the undated USGS composed series.
   - No single key is both fresh and independent. Whether the three conditions must hold on one key is a rule decision for Emil, not mine.
4. **Two judgement calls in the key map (rule `GOV` in `tools/build_taxonomy_key_map.py`):**
   - `governance_rights_score_global` and `governance_institutions_score_global` both map to **B2.1 Rule of law**.
   - Both are CORTEX composites built only from WGI RL/CC(/GE) and V-Dem corr/rule (`wellbeing_country.py`).
   - **The "rights" axis contains no rights indicator at all.**
   - `test_every_axis_with_a_primary_metric_resolves_to_a_subcategory` required a mapping. Mapping to rule of law is the defensible single choice; it is not a measurement of rights.
5. **A new registered spelling.** `last_date` (sections `quakes` and `markets` of `snapshots/master/global_indicators_latest.json`, written by `core/global_indicators.py`) was added to `config/field_names.json`. Without it, the USGS daily count read as undated. It was found on disk, not invented. Note that `tools/ask.py observation-date` now reports it too.
6. **Many `unknown` classes are spelling mismatches, not judgements.**
   - `metric_details.source_id` uses `WORLD_BANK`, but the confirmed table has `org:World Bank`. Under the rule "unknown stays unknown" these read `unknown`.
   - Sections with no composer spec have no declared org at all (e.g. `economy.labour_force_participation_pct`, `cities.roads_paved_pct`).
7. **`folder_for()` returns a path string only.** No `atoms/` directory exists (`python -m core.taxonomy --selftest` reports it INERT).
8. **`config/domains_tree.json` was not deleted**, as instructed. Its one direct reader is `agents/core/domain_gateway.py` (`load_domains_tree`). It is a CLI that nothing imports and that no scheduled task or launcher runs; only stale data files mention it. That reader is therefore DEAD.
9. **I added a scheduler step.** `tools/prophecy_morning.bat` gained one `:step "taxonomy_coverage"` line before `daily_board`. Without it the board row would turn stale every morning. **UNVERIFIED in a real morning run** until tomorrow 09:00 UTC. Check with: `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe -c "import json;print(json.load(open('memory/taxonomy_coverage_latest.json'))['generated_utc'])"` after 09:30 UTC on 2 Oct.
10. **The daily board was not rewritten** (`tools/daily_board.py --write` was not run). The new row was verified through `build_rows()` against this repo:
    `SEEN 2/123 overall (count over all 123) · world 2/105 · E 0/18 separate, never in the world total`, correction `no`.
    Its yesterday column will read "absent from the 2026-09-30 board" on the first morning.

## PART 0

- `.git/claude_stale_index_lock_2026-10-01.tmp`: already absent. It was deleted by the earlier command in this session, so there was nothing to delete now.
- `.git/index.lock`: does not exist.
- `git log -1 --format="%h %ad %s"` at the start: `27ec63f Thu Oct 1 10:58:04 2026 +0300 D1-W pre-registration DRAFT (unsealed): prereg text, frozen 56-country list, release dates`.
- `config/taxonomy.json`: 55,298 bytes, sha256 `f0307a8ad09aaa4777b96feebdac444ce85bbbd2ba805b91022572e053084997`, matching the expected hash.
  - `_meta.counts` = 5 / 25 / 123, and the counted tree = 5 / 25 / 123. No duplicate ids.
  - Sub-goals used: the five `target_config.json` names plus `SYSTEM`.

**ask.py preambles, before writing code:**
```
SEARCHED: 973 .py file(s) under ., for the whole-segment file path config/domains_tree.json
EXAMINED: 973 parsed module(s)
READERS — code that reads it (1):
  agents/core/domain_gateway.py   [20: .open('r')]
```
```
SEARCHED: 973 .py file(s) under ., for the whole-segment file path config/taxonomy.json
EXAMINED: 973 parsed module(s)
READERS — code that reads it (0):
  (none)
```

## Commits

Both were pushed to `origin/experimental/self-mod`.

| Part | Commit | Message |
|---|---|---|
| 1 | `7d479c5` | taxonomy v2: one tree (5/25/123), one loader, generated key map |
| 2 | `78d9106` | taxonomy coverage: subcategories SEEN / 123 on the daily board |

- **Commit 1:**
  - `config/taxonomy.json`, `config/taxonomy_key_map.json`;
  - `core/taxonomy.py`;
  - `tools/build_taxonomy_key_map.py`;
  - `test/test_taxonomy.py` (23 tests, all passed).
- **Commit 2:**
  - `tools/taxonomy_coverage.py`, `tools/daily_board.py` (row "Taxonomy coverage"), `tools/prophecy_morning.bat` (one step);
  - `config/field_names.json` (`last_date`);
  - `core/taxonomy.py` (a non-object JSON top level now raises `TaxonomyError` instead of crashing with `AttributeError`);
  - `test/test_taxonomy_coverage.py`, `test/test_daily_board_missing.py` (new row in `ROW_SOURCES`, plus fixture and three row tests);
  - all 134 related tests passed (`pytest -v`). The meta suites (ci_contract, no_exit_on_import, no_bare_except, llm_one_door, seed_boundary, produces_has_a_reader, …) also passed: 96.
- **Not committed:**
  - `claude/reports/TAXONOMY_COVERAGE_2026-10-01.md` and `memory/taxonomy_coverage_latest.json`, which are regenerated daily (runtime);
  - this report.

**Selftests:**
- `python -m core.taxonomy --selftest`:
  - LIVE: taxonomy (5/25/123), target_config (5 sub-goals), key map (153 keys, 131 world-facing), callers (`tools/build_taxonomy_key_map.py`).
  - INERT: `atoms/`.
- `tools/taxonomy_coverage.py --selftest`: all 10 inputs LIVE; the board reads it (LIVE); the bat runs it (LIVE); 5/5 controls hold.

## Key map (`config/taxonomy_key_map.json`)

There are 188 live keys: 153 mapped and 35 UNMAPPED. No rule names a key that is not live today.

| Source | Keys | Path |
|---|---:|---|
| target_config | 17 | `config/target_config.json` |
| metric_details | 17 | `snapshots/master/goal_score_latest.json` |
| daily_tier | 70 | `memory/daily_tier.jsonl` |
| composed | 72 | `memory/composed_indicators.json` (series ids; the top-level keys are axis names and were not enumerated) |
| openclaw | 4 | `config/openclaw_sources.json` |
| somatic | 25 | `cockpit/somatic.py` `VECTOR_FIELDS` |

### UNMAPPED, in full (35)

| key | source | why |
|---|---|---|
| markets.spy_adjclose | daily_tier | an equity fund price; no subcategory measures equity markets |
| markets.gld_adjclose | daily_tier | a gold fund price; no subcategory wants it |
| markets.uup_adjclose | daily_tier | a dollar-index fund price; no subcategory wants it |
| biodiversity.species_observations_30d | daily_tier | GBIF observation count measures observer effort, not species state |
| food.food_production_index | daily_tier | an index of output; A1.1 wants a price index, not production |
| food.agriculture_pct_gdp | daily_tier | economic structure; no subcategory wants it |
| food.cereal_yield_kg_per_ha | daily_tier | productivity, not food security, land or prices |
| tech_infra.high_tech_exports_pct_manuf | daily_tier | trade composition; B3.4 wants balance and dependency |
| exoplanets.confirmed_exoplanets | daily_tier | no subcategory measures astronomy discovery |
| media.news_tone_avg_1month | daily_tier | GDELT tone of coverage is not press freedom, ownership, censorship or disinformation |
| media.news_tone_latest | daily_tier | same |
| media.news_tone_min | daily_tier | same |
| media.news_tone_max | daily_tier | same |
| promoted_11883 | composed | discharge of one US river gauge measures no global subcategory |
| promoted_35258 | composed | evapotranspiration over one point in the US corn belt |
| gi_cereal_yield_kg_per_ha | composed | productivity, not food security, land or prices |
| gi_food_production_index | composed | an index of output, not a price index |
| promoted_34826 | composed | solar radiation over one point in Germany |
| promoted_40232 | composed | a COUNT of WHO GHE indicator codes in a catalogue, not a health measurement |
| promoted_61568 | composed | a COUNT of WHO HIV indicator codes in a catalogue |
| promoted_84957 | composed | a row count of an OWID vaccination file, not a vaccination rate |
| promoted_78396 | composed | a metadata count from the Nobel API, not a measurement of rights |
| fred_dgs10 | composed | a sovereign bond yield; B3.3 wants public debt and debt distress |
| ecb_eurusd | composed | an exchange rate; no subcategory wants it |
| eonet_sealakeice | composed | a count of sea/lake ice EVENTS is not sea-ice extent |
| gi_species_observations | composed | GBIF observation count measures observer effort |
| gi_confirmed_exoplanets | composed | no subcategory measures astronomy discovery |
| gi_self_fresh_metrics | composed | the system's own refresh count; E2.1 wants subcategories_seen |
| gi_self_carried_metrics | composed | the system's own carry count; E2.1 wants subcategories_seen |
| surface_temp_c_sofia | openclaw | weather at one city measures no global subcategory |
| this_path_does_not_exist | openclaw | a deliberately broken seed source |
| uptime_hours | somatic | machine uptime fits no E1 subcategory by name |
| open_handles | somatic | OS handle count fits no E1 subcategory by name |
| idle_seconds | somatic | Periphery is not defined precisely enough to claim it |
| brightness_pct | somatic | 'Optic' is not defined precisely enough to claim it |

## SEEN n/123 (`tools/taxonomy_coverage.py --write`, 2026-10-01T09:24Z)

**The rule.** A subcategory is SEEN when all three conditions hold:
- **STATE:** at least one key with a finite numeric value;
- **CHANGE:** at least one key whose newest *registered* observation date is a calendar day (iso_date/iso_datetime) at most 45 days old. A year, a year fraction or a missing date never counts, and mtime is never used;
- **SOURCE:** at least one key of class independent or adversarial, using only the `confirmed` entries of `config/reporter_independence.json`, looked up through `experiments/composers/provenance.reporter_class`.

| domain | SEEN | of |
|---|---:|---:|
| A — the person | 0 | 26 |
| B — society and civilization | 0 | 41 |
| C — the planet | **2** (C1.1, C5.1) | 25 |
| D — the long future and the cosmos | 0 | 13 |
| **World total (A–D)** | **2** | **105** |
| E — the system itself (separate, never in the world total) | 0 | 18 |
| Overall, a plain count over all 123 | 2 | 123 |

### NOT SEEN reasons, counted

A subcategory can fail several conditions.

**World:**

| reason | subcategories |
|---|---:|
| no live key is mapped to it | 67 |
| CHANGE: no key with a day-resolution observation ≤ 45 d old | 36 |
| SOURCE: no independent or adversarial source | 25 |
| STATE: no key with a value | 0 |

Combinations, world:

| combination | subcategories |
|---|---:|
| no key | 67 |
| CHANGE + SOURCE | 25 |
| CHANGE only | 11 |
| SEEN | 2 |

The CHANGE-only subcategories have an independent source but no fresh day-dated key. Examples:
- B1.1: UCDP, year-dated;
- B1.4: SIPRI 2024;
- C1.3: NASA, year;
- C1.4: NOAA-CU, year fraction;
- C5.2 / C5.3: EONET counts with no registered date;
- D1.5: NEO counts with no date.

**Domain E:**

| reason | subcategories |
|---|---:|
| no key | 10 |
| CHANGE | 8 |
| SOURCE | 8 |
| STATE | 1 |

## 3a — Card schema today, and where the new fields would enter

**The card.**
- `scripts/openclaw_axis_worker.card_from_row` builds a card from `CARD_FIELDS = (axis, key, value, unit, url, quote, data_date)`, adding `data_date_missing` when the date is None. It returns None when the row has no quote.
- `core/card_intake.judge_inbox` judges each card with `core.quote_gate.judge`, whose `REQUIRED = (axis, key, value, unit, url, quote)`.
- It stores `{card_key, judged_utc, source_file, verdict, gate, page_sha256, record}`. `card_key` is the sha256 of the card's canonical JSON.
- **There is no subcategory, place, period, group or actor field anywhere in the card path.**

**Where each would enter:**
- **subcategory**
  - Either at `fetch_one` (the feed row is built from the source dict, so a `subcategory` on each `config/openclaw_sources.json` entry would flow through), or at `card_from_row` by looking up `key` in `core.taxonomy.load_key_map()`. That works only for keys the map holds; today the two openclaw keys it maps are `quakes_m45_last_24h` and `objects_launched_last_30d`.
  - It must be added to `CARD_FIELDS`.
  - **Adding any field to a card changes `card_key`.** Cards already judged would then be re-judged as new.
- **place / period**
  - A second, richer path already exists. `core/observation_record.extract` (with `RECORD_FIELDS`: entity, period, period_granularity, value, unit, span, url, selector_path, published_at, retrieved_at) and `core.quote_gate.judge_record` (with `RECORD_REQUIRED`) carry entity (≈ place) and period.
  - **Both have no live caller.** `tools/ask.py callers` for each:
    ```
    SEARCHED: 978 .py file(s) under ., for calls named 'extract' (AST call nodes, not text)
    EXAMINED: 978 parsed module(s), 2 matching call site(s)
    NO live caller outside test/.
    ```
    ```
    SEARCHED: 978 .py file(s) under ., for calls named 'judge_record' (AST call nodes, not text)
    EXAMINED: 978 parsed module(s), 4 matching call site(s)
    NO live caller outside test/.
    ```
  - place/period enter the system by wiring `fetch_one` → `observation_record.extract` → `judge_record` → `card_intake`, not by widening the card.
- **group / actor:** no field exists in either the card or the record. `config/taxonomy.json` `_meta.atom_fields` names them, along with place, period, source_class and quote_hash. That is the only place they are defined.

## 3b — Spine steps that called a model last night (cycle 2026-10-01T03:04:02)

Sources:
- **Calls:** rows of `memory/llm_provenance.jsonl` with ts in the cycle window (00:04:06–00:31:56Z), by their `step` field. This includes the `brain:*` callers (core/brain.py goes through `llm_door`).
- **Seconds:** the `stepb:` span in `memory/cycle_trace/2026-10-01T03_04_02.154470_03_00.jsonl`.
- **Files:** the trace's write events inside the step span, excluding per-step infrastructure (attestation, heartbeat, step_contract, cycle_resume, homeostasis, divergence_log, llm_provenance, brain_step_log).
- **Readers:** `ask.readers()`, non-test, direct plus indirect.

| step | s | calls (backend: outcome) | file written → readers |
|---|---:|---|---|
| constancy_and_constellation | 396.9 | 25 × local cortex-l1b-3b ok (`brain:interpreter of an indicator`, `brain:reader of the whole picture`) | `memory/constancy_latest.json` → core/constancy, core/cycle_report, core/reconsider, edges_runner · `memory/constellation_latest.json` → core/cycle_report, edges_runner · `memory/brain_journal.jsonl` → 8 (cockpit/timeline, core/brain, core/language_gate, core/self_read_probe, tools/morning_digest, …) |
| self_observer | 267.4 | 15: Groq ok 13, OpenRouter ok 1 / error 1 | `memory/improvement_proposals.json` → 18 readers · `memory/body_scan_latest.json` → 8 · `memory/existence_latest.json` → experiments/pulse/pulse_daemon · `memory/proposal_archive/2026-10.md` → **0** · `phase_reports/…/E_PROPOSE.json` → 0 * |
| hyperclaw | 84.9 | 4: Groq error, NVIDIA error, Gemini error (400), local cortex-l1b-3b ok (DEGRADED) | `plans/plan-2026-10-01.md` → **0** (dir read by glob, invisible to ask.py) · `memory/llm_leg_state.json` → core/groq_backend, core/llm_door |
| cosmos_snapshots | 47.3 | 3 × Groq ok | 5 × `snapshots/cosmos/*/…_snapshot_latest.json` → **0** each (globbed) · `C_SNAPSHOT.json` * |
| cortexstrategist | 39.4 | 1 × Groq ok | `snapshots/cortex_strategist/cortex_strategist_snapshot_latest.json` → _diag, cortex_scanner, fast_cycle_runner · `memory/improvement_proposals.json` → 18 · `memory/proposal_intake_refusals.jsonl` → core/gate_contract, core/proposal_intake, fast_cycle_runner · `B_SENSE.json` * |
| brain_briefing | 35.2 | 1 × local ok (`brain:owner of this cycle`) | `memory/brain_cycle_plan.json` → core/brain, core/cycle_report, edges_runner · `memory/brain_journal.jsonl` → 8 |
| brain_reconsider | 30.2 | 1 × local ok (`brain:owner of the cycle, halfway through`) | `memory/brain_journal.jsonl` → 8 · `memory/night_events.jsonl` → core/cycle_report, edges_runner, scripts/morning_check, tools/read_the_refusals · `D_SCORE.json` * |
| planet_snapshots | 132.1 | 1 × Groq ok | 7 × `snapshots/planet/*/…_snapshot_latest.json` → **0** each (globbed) |
| growth_planner | 19.0 | 1 × Groq ok | `snapshots/body/growth_plan_latest.json` → fast_cycle_runner · `memory/improvement_proposals.json` → 18 |
| dependency_check | 3.7 | 1 × Groq error (`dependency_check:groq_ping`) | `snapshots/master/dependency_check_latest.json` → _diag, agents/core/self_observer, core/notary, fast_cycle_runner |

\* Phase-report files (`memory/phase_reports/<cycle>/<PHASE>.json`) fall into whichever step span is open when the phase debrief writes them. They are not that step's own output.

**Steps that connected to the local model port (localhost:11434) without a provenance row:** civilization_snapshots, human_snapshots, cortex_scan, body_scan, plus one extra connection in each of the snapshot steps. **UNVERIFIED** whether these were generations that bypassed `llm_door`, or `core/model_window.py`'s own Ollama traffic. That module calls `/api/ps` for status and an empty-message `/api/chat` to load or unload a model; neither writes a provenance row. To verify, run the next cycle with `CORTEX_TRACE_CALLS=1` (`core/flight_recorder.py` channel C, per-call tracing) and read the `call` events inside those spans. I did not run that here, because running a cycle is forbidden in this command.

## 3c — Root files: readers and callers

**Method.** For each file:
- `ask.readers("<file>.py")`. Preamble each time: `SEARCHED: 978 .py file(s) under ., for the whole-segment file path <file>.py`.
- `ask.callers("<module>.<fn>")` for **every** top-level function. Preamble, e.g. `SEARCHED: 978 .py file(s) for calls named 'main'; 1 matching call site(s)`.
- An AST import scan of all repo `.py` files (not under venv*, .git, Broker-bot, _ARCHIVE).
- A scan of every `.bat/.ps1/.vbs/.cmd` and all 226 Task Scheduler actions for the file name.

Totals examined: 20 files, 104 functions, 978 modules per query.

| file | defs | readers (non-test) | live callers outside test/ | imported by | launchers / tasks | verdict |
|---|---:|---|---|---|---|---|
| _check_proposals.py | 0 | — | — | — | — | **DEAD** |
| _check_ram.py | 0 | — | — | — | — | **DEAD** |
| _clean_proposals.py | 0 | — | — | — | — | **DEAD** |
| _diag.py | 0 | — | — | — | — | **DEAD** |
| _divergence_pilot.py | 4 | — | — (7 calls inside itself) | — | — | **DEAD** |
| _refresh_three_axes.py | 2 | — (named, not read, by core/answered_by.py) | — | — | — | **DEAD** |
| _test_zone_logic.py | 2 | — | — | — | — | **DEAD** |
| test_llm.py | 1 | — | — (its own `main()` only) | — | — | **DEAD** |
| manual_pre_llm_backup.py | 5 | — | — | — | — | **DEAD** (it imports `agents.actions.hypercortex_actions_agent`) |
| qwen_repl.py | 1 | — | — | — | — | **DEAD** |
| qwen_planetary_repl.py | 2 | — | — | — | — | **DEAD** |
| qwen_cortex_agent.py | 4 | — | — | — | — | **DEAD** |
| qwen_civilization_daily_review_agent.py | 8 | — | — | — | — | **DEAD** |
| civilization_state_review_agent_qwen.py | 3 | — | — | — | — | **DEAD** |
| energy_review_patch.py | 2 | — | — | — | — | **DEAD** |
| merkle_to_training.py | 10 | — | — | test/test_corpus_contract_one_reader.py only | — | **DEAD** (test-only) |
| cortex_approval_server.py | 12 | test files only | — | test/test_dashboard_freshness.py only | — | **DEAD** (test-only) |
| hypercortex_runner.py | 9 | — (named by run_daily.py, patch_guardian.py, agents/actions/hypercortex_actions_agent.py) | — | — | `run_daily.bat`; no task | **DEAD** — see below |
| cortex_planning_agent.py | 21 | — | — | — | — | **DEAD** |
| cortex_proposal_executor.py | 8 | — | — | — | — | **DEAD** |

**Why `hypercortex_runner.py` is DEAD despite three mentions.**
- `run_daily.py` runs it via `subprocess.run([... BASE / "hypercortex_runner.py"])`. `ask.py` lists that as a name-only mention, because the path is built at runtime. Nothing live references `run_daily.py`, and no task runs it.
- `run_daily.bat` does `cd /d …\CORTEX++_QWEN`, the archived system, so it runs QWEN's copy, not this one. No scheduled task runs the .bat.
- `hypercortex_actions_agent.py` only whitelists the name. It is imported solely by `manual_pre_llm_backup.py`, which is itself DEAD.

Nothing was deleted.

**Caveat.** `ask.py` is code-only. A file started by hand, or by a launcher outside this repo, is invisible to it. The `.bat/.ps1/.vbs` scan and the Task Scheduler scan cover what this machine can show.

## 3d — `cockpit.somatic --probe`, headless

- **It runs headless.** `venv\Scripts\python.exe -m cockpit.somatic --probe` exited 0 with no cockpit server running.
- **Microphone and camera stayed off.** `config_expression.yaml` has `mic_enabled: false` and `camera_enabled: false`, which `probe()` reads fresh. The output shows `mic_rms DISABLED`, `camera_lux DISABLED`, `motion_mse DISABLED`.
- **Duration:** `probe()` measured in-process at **3.60 s** (import 0.06 s).
- **Result:** "31 of 42 sensors available", and **"state vector v1 — 25/25 dims measured"**. All 25 `VECTOR_FIELDS` were available.

The 11 that are not available are all outside the 25-dim vector. 8 are NOT AVAILABLE, each with the probe's own reason:

| sensor | reason |
|---|---|
| battery_secsleft | unlimited while plugged in |
| discharge_rate | needs two samples over time; a single probe cannot measure a rate |
| cpu_temp_c | `psutil.sensors_temperatures()` is not implemented on Windows; needs a vendor driver (LibreHardwareMonitor) |
| fan_rpm | `psutil.sensors_fans()` is not implemented on Windows |
| smart_health | SMART needs elevated rights and smartctl, neither present |
| wifi_rssi_dbm | netsh reports a percentage, not dBm; dBm needs the WLAN API |
| bluetooth_scan | no bluetooth stack binding installed (bleak/winrt absent) |
| ambient_light | no ambient light sensor exposed by this machine |

The other 3 are DISABLED by toggle: mic_rms, camera_lux, motion_mse.

**Note:** the probe printed `uptime_hours 3.76` and `active_window` text. The machine booted at 08:45 local today.

## 3e — Why `memory/somatic_history.jsonl` stopped on 2026-09-26

- **The writer.** The only live writer is `cockpit/server.py`, in the `/api/somatic` handler (`api_somatic`), which calls `cockpit.norms.record(r, HISTORY_PATH)`. `tools/ask.py callers cockpit.norms.record`:
  ```
  SEARCHED: 978 .py file(s) under ., for calls named 'record' (AST call nodes, not text)
  EXAMINED: 978 parsed module(s), 17 matching call site(s)
    [LIVE] cockpit/norms.py:427   record(...)      <- inside norms' own selftest (temp file)
    [LIVE] cockpit/norms.py:457   record(...)      <- inside norms' own selftest
    [LIVE] cockpit/server.py:938   nm.record(...)
  ```
- **When it writes.** One row per HTTP request to `/api/somatic`, which the cockpit page polls (every 15 s per the handler's own comment) while the Flask server runs on port 5055.
- **State now:**
  - nothing listens on 5055 (`netstat -ano` shows no `:5055`);
  - no `python` process has `cockpit` in its command line;
  - no scheduled task's action mentions cockpit.
- **The file's last row:** `2026-09-26T14:20:07Z` (1,162 rows, mtime 26 Sep 17:20 local).
- **Conclusion.** The history stopped because the cockpit server stopped serving `/api/somatic` on 26 Sep, and nothing restarts it. **UNVERIFIED** why it stopped then (a closed window, a reboot, or a crash). To verify that rows resume, start `venv\Scripts\python.exe cockpit/server.py`, open the page, and run `tail -1 memory/somatic_history.jsonl`.
- **Consequence for the taxonomy:** see "does not work" item 2.
