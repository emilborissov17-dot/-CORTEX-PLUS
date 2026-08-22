# Quarantine triage — 38 patches, 22 August 2026

Read-only. Nothing was applied, nothing was rejected. Every patch in
`patches/quarantine/` that `scripts/review_quarantine.py` lists was opened and read
in full; the summaries below are from the source, not from the sidecar.

## The finding that decides most of the table

Three checks, run against this repo, apply to **all 38** without exception:

1. **Every target file is absent.** `agents/core/general_patch.py`,
   `agents/core/water_review_patch.py` and the nine other targets do not exist.
   Approving a patch therefore *creates* a new module rather than changing one.
2. **Nothing would import it.** No file in `core/`, `agents/`, `experiments/`,
   `scripts/`, `fast_cycle_runner.py` or `supervisor.py` imports any `*_patch`
   module. The created file would sit there, executed by nobody.
3. **Nothing reads what they write.** `battery_registry.json`,
   `biodiversity_reserves.json`, `water_sensors.json`, `grid_upgrade_plan.json`,
   `agents_registry.json` — zero readers outside `patches/`.

So the question "does this patch work" is the wrong one. The right one is "does it
do anything real", and the answer is in the verdict column.

The shared shape, seen 34 times: the patch invents a domain the system has no
contact with — EV battery registries, bumblebee reserves, plastic sorting trucks,
farm water quotas — types its own inputs into `__main__`, computes a percentage
from those literals, and prints it as a measurement. Six separate patches build
the same battery registry; five build the same biodiversity registry. The residue
is already on disk: `memory/battery_registry.json` holds "BAT001 / ManufacturerA",
`memory/water_sensors.json` holds "SENSOR-01", from earlier runs of these files.

**Verdict rule.** JUNK = invents a domain with no producer and no consumer in this
repo, or is a no-op / crashes on its own demo. REVIEW = acts on real CORTEX
machinery (a real module, the real runner, a real config path), so a human should
look even if the answer turns out to be reject.

## The table

| # | id | age | target | verdict |
|---|----|-----|--------|---------|
| 1 | `general_patch.1784940113.py` | 27d | `agents/core/general_patch.py` | **JUNK** |
| 2 | `general_patch.1785306175.py` | 23d | `agents/core/general_patch.py` | **REVIEW** |
| 3 | `general_patch.1785353275.py` | 23d | `agents/core/general_patch.py` | **JUNK** |
| 4 | `general_patch.1785353287.py` | 23d | `agents/core/general_patch.py` | **REVIEW** |
| 5 | `general_patch.1785353298.py` | 23d | `agents/core/general_patch.py` | **REVIEW** |
| 6 | `social_relations_review_patch.1785353303.py` | 23d | `agents/core/social_relations_review_patch.py` | **JUNK** |
| 7 | `social_patch.1785372158.py` | 22d | `agents/core/social_patch.py` | **JUNK** |
| 8 | `water_review_patch.1785372131.py` | 22d | `agents/core/water_review_patch.py` | **JUNK** |
| 9 | `energy_review_patch.1785483242.py` | 21d | `agents/core/energy_review_patch.py` | **JUNK** |
| 10 | `social_relations_review_patch.1785564191.py` | 20d | `agents/core/social_relations_review_patch.py` | **JUNK** |
| 11 | `general_patch.1785653292.py` | 19d | `agents/core/general_patch.py` | **JUNK** |
| 12 | `social_relations_review_patch.1785745560.py` | 18d | `agents/core/social_relations_review_patch.py` | **JUNK** |
| 13 | `technology_infra_review_patch.1785745563.py` | 18d | `agents/core/technology_infra_review_patch.py` | **JUNK** |
| 14 | `water_review_patch.1785745555.py` | 18d | `agents/core/water_review_patch.py` | **JUNK** |
| 15 | `ecosystems_biodiversity_review_patch.1785804161.py` | 17d | `agents/core/ecosystems_biodiversity_review_patch.py` | **JUNK** |
| 16 | `social_relations_review_patch.1785804165.py` | 17d | `agents/core/social_relations_review_patch.py` | **JUNK** |
| 17 | `social_relations_review_patch.1785835073.py` | 17d | `agents/core/social_relations_review_patch.py` | **JUNK** |
| 18 | `technology_infra_review_patch.1785804170.py` | 17d | `agents/core/technology_infra_review_patch.py` | **JUNK** |
| 19 | `technology_infra_review_patch.1785835083.py` | 17d | `agents/core/technology_infra_review_patch.py` | **JUNK** |
| 20 | `water_review_agent_patch.1785835016.py` | 17d | `agents/core/water_review_agent_patch.py` | **JUNK** |
| 21 | `ecosystems_biodiversity_review_patch.1785912052.py` | 16d | `agents/core/ecosystems_biodiversity_review_patch.py` | **JUNK** |
| 22 | `technology_infra_review_patch.1785912064.py` | 16d | `agents/core/technology_infra_review_patch.py` | **JUNK** |
| 23 | `technology_infra_review_patch.1785999884.py` | 15d | `agents/core/technology_infra_review_patch.py` | **JUNK** |
| 24 | `water_review_agent_patch.1785999905.py` | 15d | `agents/core/water_review_agent_patch.py` | **JUNK** |
| 25 | `ecosystems_biodiversity_review_patch.1786063817.py` | 14d | `agents/core/ecosystems_biodiversity_review_patch.py` | **JUNK** |
| 26 | `technology_infra_review_patch.1786063828.py` | 14d | `agents/core/technology_infra_review_patch.py` | **JUNK** |
| 27 | `water_review_agent_patch.1786063833.py` | 14d | `agents/core/water_review_agent_patch.py` | **JUNK** |
| 28 | `water_review_patch.1786063839.py` | 14d | `agents/core/water_review_patch.py` | **JUNK** |
| 29 | `ecosystems_biodiversity_review_patch.1786171906.py` | 13d | `agents/core/ecosystems_biodiversity_review_patch.py` | **JUNK** |
| 30 | `ecosystems_biodiversity_review_patch.1786236159.py` | 12d | `agents/core/ecosystems_biodiversity_review_patch.py` | **JUNK** |
| 31 | `technology_ai_review_patch.1786236200.py` | 12d | `agents/core/technology_ai_review_patch.py` | **JUNK** |
| 32 | `governance_institutions_review_patch.1786322784.py` | 11d | `agents/core/governance_institutions_review_patch.py` | **JUNK** |
| 33 | `technology_ai_review_patch.1786322819.py` | 11d | `agents/core/technology_ai_review_patch.py` | **JUNK** |
| 34 | `water_review_agent_patch.1786322808.py` | 11d | `agents/core/water_review_agent_patch.py` | **JUNK** |
| 35 | `governance_institutions_review_patch.1786438182.py` | 10d | `agents/core/governance_institutions_review_patch.py` | **JUNK** |
| 36 | `technology_ai_review_patch.1786438193.py` | 10d | `agents/core/technology_ai_review_patch.py` | **JUNK** |
| 37 | `cortex_core_agent_patch.1786520091.py` | 9d | `agents/core/cortex_core_agent_patch.py` | **JUNK** |
| 38 | `general_patch.1786755265.py` | 6d | `agents/core/general_patch.py` | **REVIEW** |

### What each one does

**1. `general_patch.1784940113.py`** — 27d, 99 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Writes three hardcoded 'existential risk mitigation strategies' (climate,
> nuclear war, pandemic) as JSON files under memory/existential_risk_strategies/,
> each with status 'planned', and logs the writes to existential_risk_log.json.
> The measurable output is the count of files it just created. assess_existing_gaps()
> reads a body_scan 'existential_risk' category that no scan ever emits.

> **JUNK**

**2. `general_patch.1785306175.py`** — 23d, 92 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> The only patch that touches the LLM path. Creates config/llm_rate_limit.json and
> raises limits to 5000 rpm / 1000 burst, then sets core.groq_backend.RATE_LIMIT at
> runtime. Nothing reads either the file or that attribute, so applying it changes
> no behaviour today — but the idea (a rate-limit config for the groq backend) is
> about real machinery. NOTE: _measure_effect() fires a live call_groq() on import.

> **REVIEW**

**3. `general_patch.1785353275.py`** — 23d, 47 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Registers a 'WATER_REVIEW' agent in a new agents/registry.json, pointing at module
> agents.water.water_review_agent — which does not exist in this repo. Nothing reads
> agents/registry.json either. So it writes a registry, of one entry, naming an
> absent module, for a loader that was never built. Inert on both ends.

> **JUNK**

**4. `general_patch.1785353287.py`** — 23d, 58 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Proposes config-driven agent loading: writes config/fast_cycle_config.json with
> {module, class, enabled} for agents.energy.energy_review_agent_qwen, which DOES
> exist here. Nothing reads fast_cycle_config.json, so it is inert as written, and
> the runner's step list is code, not config. Worth a human look because it is a
> real proposal about how agents get wired, not an invented domain.

> **REVIEW**

**5. `general_patch.1785353298.py`** — 23d, 101 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> A DailyAnalysisAgent that calls memory.existence_model.am_i_alive() and
> memory.body_scan.full_scan() — both real modules here — and appends
> {timestamp, system_alive, last_body_scan} to memory/daily_log.json. Its own
> docstring calls integrate_into_execution_chain() a stub. Duplicates what the
> heartbeat and body_scan step already record, but it is about this system.

> **REVIEW**

**6. `social_relations_review_patch.1785353303.py`** — 23d, 77 lines, target `agents/core/social_relations_review_patch.py`, quarantined for: Traceback (most recent call last):

> Community-programme tracker. CRASHES ON ITS OWN FIRST CALL: load_programs() has
> {'last_score': null} — the JavaScript literal, not None — so any run raises
> NameError before writing anything. Even if fixed, the score is
> min(100, total_participants * 0.1) over participant counts (25, 15) that __main__
> makes up. Nothing reads memory/social_relations/programs.json.

> **JUNK**

**7. `social_patch.1785372158.py`** — 22d, 69 lines, target `agents/core/social_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\social_patch.py

> Collects two 'social cohesion indicators' whose values are typed into main():
> trust_index 0.6 and conflict_incidents 0.1. Computes a weighted score from them
> (+1.0 / -1.0 weights) and writes it to semantic memory via remember(), which is a
> real call — so the fabricated number would enter the memory other agents query.
> That is the harm: invented data reaching a real store.

> **JUNK**

**8. `water_review_patch.1785372131.py`** — 22d, 139 lines, target `agents/core/water_review_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> A WaterStressAgent that computes a weighted Water Stress Index from precipitation,
> reservoir level, soil moisture and groundwater depth. The weights (0.3/0.3/0.2/0.2)
> are stated without justification and both inputs are marked 'mock' in the source.
> The files it reads are created empty by its own constructor, so every run reports
> 0 critical regions. Writes memory/water_stress/daily_report.json.

> **JUNK**

**9. `energy_review_patch.1785483242.py`** — 21d, 73 lines, target `agents/core/energy_review_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Invents a grid-storage deployment plan under memory/energy_storage/plan.json.
> _simulate_deployments() writes five hardcoded installations (Western Europe
> Lithium-Ion 5.0 GWh, Mediterranean Flow Battery 4.5, ...) totalling 16.5 GWh,
> then reports 82.5% progress against a target_gwh of 20 that the same file set.
> The 'measurement' is arithmetic over constants the patch itself wrote.

> **JUNK**

**10. `social_relations_review_patch.1785564191.py`** — 20d, 75 lines, target `agents/core/social_relations_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\social_relation

> Records a 'Telegram approval' as a bare timestamp in a list, then multiplies a
> stored score by 1.10 for having any approval at all. If the score is 0 it
> substitutes 1.0 so the multiplication produces something. No approval text, no
> approver, no link to the real Telegram approval path in this repo — the word
> 'approval' is the only connection. Writes memory/social_relations_review.json.

> **JUNK**

**11. `general_patch.1785653292.py`** — 19d, 78 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> 'Audits' water systems by walking memory/water_audit/ and counting the JSON files
> it finds. That directory does not exist. The transparency score is defined as
> 1/(1+issues_found), so an empty directory scores a perfect 1.0 and finding more
> data lowers the score. Imports semantic_memory and call_groq and uses neither.
> Writes memory/water_audit/audit_report.json.

> **JUNK**

**12. `social_relations_review_patch.1785745560.py`** — 18d, 132 lines, target `agents/core/social_relations_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\social_relation

> Registers five city projects (New York, Mumbai, Lagos, São Paulo, Berlin), sets a
> 5% inequality-reduction target for each, then reports achievements — 5.2%, 4.9%,
> 5.0% — that __main__ types in directly. The score counts cities where its own
> invented achievement beats its own invented target. Writes
> memory/social_relations_progress.json.

> **JUNK**

**13. `technology_infra_review_patch.1785745563.py`** — 18d, 114 lines, target `agents/core/technology_infra_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_infr

> EV battery registry, attempt 1 of 6. Registers EVBAT_0001..0005, collects three,
> recycles them, and asserts a 90% material recovery rate as a literal
> (recovery_rate = 0.9). Prints registered/produced percentages computed entirely
> from the rows it wrote seconds earlier. Writes battery_registry.json,
> recycling_hubs.json, recycling_stats.json — none read by anything.

> **JUNK**

**14. `water_review_patch.1785745555.py`** — 18d, 143 lines, target `agents/core/water_review_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Aggregates well extraction by US state from memory/water_sensors/*.json — a
> directory that does not exist — so it prints 'No sensor data available' and exits.
> Its quota rule would set each state's target to 90% of a 2025 reference, but the
> reference file is written by the same run from the current values, so the target
> is always 90% of today and compliance is always false.

> **JUNK**

**15. `ecosystems_biodiversity_review_patch.1785804161.py`** — 17d, 107 lines, target `agents/core/ecosystems_biodiversity_review_patch.py`, quarantined for: Traceback (most recent call last):

> Invents a biodiversity-reserve registry. _example_setup() hardcodes three
> reserves ('Green Corridor Alpha', Midwest USA, 150 ha) and writes them to
> memory/biodiversity_reserves.json. Bumblebee population change is not measured:
> _simulate_population_change() returns 0.5% per reserve row, capped at 30%.
> Prints a pass/fail report against a 2027 target from those invented numbers.

> **JUNK**

**16. `social_relations_review_patch.1785804165.py`** — 17d, 92 lines, target `agents/core/social_relations_review_patch.py`, quarantined for: Traceback (most recent call last):

> Same file, second attempt. Hardcodes 49 US city names as 'started projects', then
> fabricates the measurement outright: baseline 0.55 if no history, and each run
> multiplies the last score by (1 + 0.10/3) and records it as a new measurement.
> It is a compounding counter that will report steady improvement forever without
> reading anything. Writes memory/social_relations_progress.json.

> **JUNK**

**17. `social_relations_review_patch.1785835073.py`** — 17d, 84 lines, target `agents/core/social_relations_review_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Writes two hardcoded community programmes and projects a score from a baseline of
> 50 plus 5 per run. BROKEN: _record_metric() does 'data, _ = _safe_load(...)',
> unpacking a dict into two names, which raises before the metric is stored. So the
> run writes community_programs.json, then dies. Nothing reads either file.

> **JUNK**

**18. `technology_infra_review_patch.1785804170.py`** — 17d, 86 lines, target `agents/core/technology_infra_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_infr

> Attempt 2. Same registry, described as 'блок-чейн-подобна' but it is a JSON list.
> __main__ registers EV20260001/2, collects one, and recycles it with recovered
> materials {'lithium': 5.2, 'cobalt': 2.1} — numbers with no source. The output
> then reports 50% recycled, which is 1 of the 2 rows it just created.

> **JUNK**

**19. `technology_infra_review_patch.1785835083.py`** — 17d, 111 lines, target `agents/core/technology_infra_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_infr

> Attempt 3, and the only one that imports real modules (body_scan,
> existence_model, groq_backend) — none of which it ever calls. Recovery efficiency
> divides recovered kg by an 'assumed 1 kg per battery per material' denominator
> the code invents in a comment. Registers five CN-EV-* batteries and recycles the
> even-numbered ones. Writes battery_registry.json, recycling_stats.json.

> **JUNK**

**20. `water_review_agent_patch.1785835016.py`** — 17d, 142 lines, target `agents/core/water_review_agent_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Groundwater sensor monitor. Registers sensor_A1 in region_IA and adds two depth
> readings, 48.2 and 47.5, from __main__. The baseline it measures against is
> invented in measurable_output(): if semantic memory has no '2024 baseline', it
> writes depletion_rate = 100 and then reports the reduction from it. Alerts and
> the fabricated baseline both go into the real semantic memory via remember().

> **JUNK**

**21. `ecosystems_biodiversity_review_patch.1785912052.py`** — 16d, 112 lines, target `agents/core/ecosystems_biodiversity_review_patch.py`, quarantined for: Traceback (most recent call last):

> Same invented reserve registry, second attempt. register_reserve() takes lat/lon;
> update_measurements() would compute real percent change IF given real bumblebee
> counts, but __main__ passes dummy_counts = {'EU-01': 1200, 'US-07': 950} and a
> total_regions of 100 chosen on the spot. Writes memory/biodiversity_measure.json.
> Nothing in the repo produces bumblebee counts or reads either file.

> **JUNK**

**22. `technology_infra_review_patch.1785912064.py`** — 16d, 105 lines, target `agents/core/technology_infra_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_infr

> Attempt 4. NO-OP AT THE END: the last line is 'print_measurable' without
> parentheses, so the function is referenced and never called and the run produces
> no output at all. Recovery efficiency is measured against theoretical = {'lithium':
> 1000, 'cobalt': 500}, two constants with no provenance. Registers BAT001/BAT002
> and recycles one. Writes battery_registry.json, battery_stats.json.

> **JUNK**

**23. `technology_infra_review_patch.1785999884.py`** — 15d, 98 lines, target `agents/core/technology_infra_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_infr

> Attempt 5. Adds a flow journal (battery_flow.json) beside the registry. __main__
> registers five batteries from 'ManufacturerA', collects three in Beijing, recycles
> two with recovered materials logged as the strings '95%' and '92%'. The measurable
> output is the ratio between those literals. Same two files as attempt 6.

> **JUNK**

**24. `water_review_agent_patch.1785999905.py`** — 15d, 77 lines, target `agents/core/water_review_agent_patch.py`, quarantined for: Traceback (most recent call last):

> Reads memory/water_sensor_data.json, which nothing writes, so readings is empty
> and analyze_and_recommend() returns None — whereupon print_measurable_result()
> unpacks that None into three names and raises TypeError. It cannot complete a run
> in this repo. The recommendation text would otherwise be a threshold of 40.0 m
> 'above sea level' applied to groundwater depth.

> **JUNK**

**25. `ecosystems_biodiversity_review_patch.1786063817.py`** — 14d, 138 lines, target `agents/core/ecosystems_biodiversity_review_patch.py`, quarantined for: Traceback (most recent call last):

> Third attempt at the same registry, now with a Reserve class. __main__ adds
> 'Midwest_USA' and 'Bavaria_DE', then calls apply_biological_control() and
> enforce_pesticide_reduction(), which are explicitly labelled 'mock functions'
> and just add 3% and 5% to a stored number. Baseline populations (1000, 800) are
> written by the script itself, so the recovery it then measures is its own input.

> **JUNK**

**26. `technology_infra_review_patch.1786063828.py`** — 14d, 103 lines, target `agents/core/technology_infra_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_infr

> Attempt 6, nearly identical to 5 with English comments and 'EcoMotor Inc.' as the
> manufacturer. Recycling efficiency is a single logged event with efficiency 92.5,
> typed into __main__. registered_percent counts rows whose status != 'unknown',
> which is every row the script writes, so it always reports 100%.

> **JUNK**

**27. `water_review_agent_patch.1786063833.py`** — 14d, 95 lines, target `agents/core/water_review_agent_patch.py`, quarantined for: Traceback (most recent call last):

> Same shape against memory/water_sensors.json (which does exist, holding earlier
> invented SENSOR-01 rows). Records a 'depletion_rate' metric of 0.45 that __main__
> labels as simulated, then computes progress as the change between the last two
> such simulated values. Writes water_recommendations.json and water_metrics.json.

> **JUNK**

**28. `water_review_patch.1786063839.py`** — 14d, 99 lines, target `agents/core/water_review_patch.py`, quarantined for: Traceback (most recent call last):

> Reads groundwater_sensors.json and satellite_estimates.json, neither of which
> exists, so the well list is empty and it prints 'No well data available'. The
> quota rule (0.8 safety factor, extra 0.9 on over-extraction, never above the
> existing quota) is coherent but has nothing to run on. _measure_progress()
> compares against q['historical_extraction'], a key nothing ever sets.

> **JUNK**

**29. `ecosystems_biodiversity_review_patch.1786171906.py`** — 13d, 109 lines, target `agents/core/ecosystems_biodiversity_review_patch.py`, quarantined for: Traceback (most recent call last):

> Fourth attempt. add_reserve() writes a fixed flower list ['local_flower_1',
> 'local_flower_2']. simulate_population_growth() projects 2027 from a base value
> of 1000 'assumed' per region and a flat 1.01**3 growth factor. The set of
> 'critical regions' is a four-item literal inside measurable_report(), described
> in its own comment as фиктивен. Writes memory/bumblebee_population.json.

> **JUNK**

**30. `ecosystems_biodiversity_review_patch.1786236159.py`** — 12d, 132 lines, target `agents/core/ecosystems_biodiversity_review_patch.py`, quarantined for: Traceback (most recent call last):

> Fifth attempt, the most structured: normalised region keys, a monitoring
> time-series, an on_track/behind evaluation against 2027 targets. Every input is
> still supplied by __main__ — two reserves and four bumblebee counts typed into
> the file, with the comment 'in practice gathered by drones + AI'. Writes
> memory/bumblebee_monitoring.json and memory/critical_regions.json.

> **JUNK**

**31. `technology_ai_review_patch.1786236200.py`** — 12d, 111 lines, target `agents/core/technology_ai_review_patch.py`, quarantined for: Patch execution timeout (>30s)

> Simulates AI plastic sorting. Loops ten times calling call_groq() to 'classify'
> an image id that is just a timestamp string — this is why the guardian killed it
> on a >30s timeout. Weight collected is 5 * the model's own confidence. Route
> optimisation is sorted(locations) with 5 km assumed between stops. Divides by an
> 'example' national consumption of 1,000,000 kg to print a recycling rate.

> **JUNK**

**32. `governance_institutions_review_patch.1786322784.py`** — 11d, 128 lines, target `agents/core/governance_institutions_review_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> A farm water-quota allocator. load_satellite_soil_moisture() and
> load_precipitation_forecast() are documented as симулирана and return the
> defaults 0.5 and 100 because the files they read do not exist. The farm registry
> is empty, so zero allocations are produced. It then 'reduces' groundwater drawdown
> by multiplying a stored 0 by 0.8 and prints the result as a 20% reduction.

> **JUNK**

**33. `technology_ai_review_patch.1786322819.py`** — 11d, 92 lines, target `agents/core/technology_ai_review_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> Same domain without the LLM calls. simulate_collection() writes four literal rows
> (Bangkok Central 120 kg PET, Jakarta 200 kg PP, ...) and simulate_marketplace()
> three literal transactions. The recycling rate is those constants over a national
> waste figure the comment marks as a placeholder. Writes three files under
> memory/plastic_recycling/ that nothing reads.

> **JUNK**

**34. `water_review_agent_patch.1786322808.py`** — 11d, 104 lines, target `agents/core/water_review_agent_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> The clearest case in the set: simulate_sensor_input() returns
> random.uniform(0.4, 1.0) for three US regions, and the rest of the file evaluates
> those random numbers against thresholds, records them as metrics and prints
> 'Средно ниво на подпочвени води'. Re-running produces different groundwater
> levels for the same day. Writes memory/water_monitoring/*.json.

> **JUNK**

**35. `governance_institutions_review_patch.1786438182.py`** — 10d, 127 lines, target `agents/core/governance_institutions_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\governance_inst

> Second quota allocator. Soil moisture, rainfall and socioeconomic impact are all
> derived from sum(ord(c) for c in farm_id) % 100 — a hash of the farm's name
> dressed as satellite data, one of them mixed with the current timestamp so it
> changes every run. __main__ invents farm_A/B/C and three basin measurements
> (500000, 420000, 380000) and prints the 24% 'reduction' between its own literals.

> **JUNK**

**36. `technology_ai_review_patch.1786438193.py`** — 10d, 124 lines, target `agents/core/technology_ai_review_patch.py`, quarantined for: C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED\agents\core\technology_ai_r

> Third attempt. classify_plastic() ignores its argument and returns the string
> 'PET' — the comment says so. optimise_route() returns pending_locations[0] and
> calls it optimisation. Three collection weights (5000, 7200, 3100 kg) are typed
> into __main__ and divided by an assumed 100,000 t national total. Writes
> plastic_collection_log.json, routing_log.json, recycled_material_marketplace.json.

> **JUNK**

**37. `cortex_core_agent_patch.1786520091.py`** — 9d, 98 lines, target `agents/core/cortex_core_agent_patch.py`, quarantined for: Traceback (most recent call last):

> Invents an electricity-grid planner: reads memory/grid_current_data.json for
> transmission lines, flags any line loaded >80% of capacity, prices a fix with
> arbitrary cost/benefit factors, and writes a phased roadmap to
> memory/grid_upgrade_plan.json. Current renewable share is a literal 35.0 from
> _mock_current_renewable_integration(); each phase is assumed to add 4%.

> **JUNK**

**38. `general_patch.1786755265.py`** — 6d, 76 lines, target `agents/core/general_patch.py`, quarantined for: write_text() target not statically verified under an allowed directory

> DANGEROUS. The only patch that rewrites a live file: it read-modify-writes
> fast_cycle_runner.py, inserting 'from agents.water_review_agent import
> water_review_agent' after the last top-level import. That module does not exist,
> so the next cycle start dies on ImportError. 'execution_chain' appears 0 times in
> the runner, so the registration half is a no-op. Read it before anything else.

> **REVIEW**

## The 34 JUNK — bulk reject commands (NOT executed)

`--reject` moves the file and its sidecar into `patches/quarantine/rejected/`.
Nothing is deleted, and the move is reversible with a plain `mv`.

```powershell
cd C:\Users\emilb\Desktop\AGI\CORTEX++_MERGED
venv\Scripts\python.exe scripts\review_quarantine.py --reject general_patch.1784940113.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject general_patch.1785353275.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject social_relations_review_patch.1785353303.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject social_patch.1785372158.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_patch.1785372131.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject energy_review_patch.1785483242.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject social_relations_review_patch.1785564191.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject general_patch.1785653292.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject social_relations_review_patch.1785745560.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_infra_review_patch.1785745563.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_patch.1785745555.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject ecosystems_biodiversity_review_patch.1785804161.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject social_relations_review_patch.1785804165.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject social_relations_review_patch.1785835073.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_infra_review_patch.1785804170.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_infra_review_patch.1785835083.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_agent_patch.1785835016.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject ecosystems_biodiversity_review_patch.1785912052.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_infra_review_patch.1785912064.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_infra_review_patch.1785999884.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_agent_patch.1785999905.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject ecosystems_biodiversity_review_patch.1786063817.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_infra_review_patch.1786063828.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_agent_patch.1786063833.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_patch.1786063839.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject ecosystems_biodiversity_review_patch.1786171906.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject ecosystems_biodiversity_review_patch.1786236159.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_ai_review_patch.1786236200.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject governance_institutions_review_patch.1786322784.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_ai_review_patch.1786322819.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject water_review_agent_patch.1786322808.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject governance_institutions_review_patch.1786438182.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject technology_ai_review_patch.1786438193.py
venv\Scripts\python.exe scripts\review_quarantine.py --reject cortex_core_agent_patch.1786520091.py
```

Or, the same list in one loop:

```powershell
$junk = @(
  'general_patch.1784940113.py'
  'general_patch.1785353275.py'
  'social_relations_review_patch.1785353303.py'
  'social_patch.1785372158.py'
  'water_review_patch.1785372131.py'
  'energy_review_patch.1785483242.py'
  'social_relations_review_patch.1785564191.py'
  'general_patch.1785653292.py'
  'social_relations_review_patch.1785745560.py'
  'technology_infra_review_patch.1785745563.py'
  'water_review_patch.1785745555.py'
  'ecosystems_biodiversity_review_patch.1785804161.py'
  'social_relations_review_patch.1785804165.py'
  'social_relations_review_patch.1785835073.py'
  'technology_infra_review_patch.1785804170.py'
  'technology_infra_review_patch.1785835083.py'
  'water_review_agent_patch.1785835016.py'
  'ecosystems_biodiversity_review_patch.1785912052.py'
  'technology_infra_review_patch.1785912064.py'
  'technology_infra_review_patch.1785999884.py'
  'water_review_agent_patch.1785999905.py'
  'ecosystems_biodiversity_review_patch.1786063817.py'
  'technology_infra_review_patch.1786063828.py'
  'water_review_agent_patch.1786063833.py'
  'water_review_patch.1786063839.py'
  'ecosystems_biodiversity_review_patch.1786171906.py'
  'ecosystems_biodiversity_review_patch.1786236159.py'
  'technology_ai_review_patch.1786236200.py'
  'governance_institutions_review_patch.1786322784.py'
  'technology_ai_review_patch.1786322819.py'
  'water_review_agent_patch.1786322808.py'
  'governance_institutions_review_patch.1786438182.py'
  'technology_ai_review_patch.1786438193.py'
  'cortex_core_agent_patch.1786520091.py'
)
foreach ($p in $junk) {
  & venv\Scripts\python.exe scripts\review_quarantine.py --reject $p
}
```

## The 4 for your eyes

- **`general_patch.1785306175.py`** (23d, target `agents/core/general_patch.py`)
  <br>The only patch that touches the LLM path. Creates config/llm_rate_limit.json and raises limits to 5000 rpm / 1000 burst, then sets core.groq_backend.RATE_LIMIT at runtime. Nothing reads either the file or that attribute, so applying it changes no behaviour today — but the idea (a rate-limit config for the groq backend) is about real machinery. NOTE: _measure_effect() fires a live call_groq() on import.

- **`general_patch.1785353287.py`** (23d, target `agents/core/general_patch.py`)
  <br>Proposes config-driven agent loading: writes config/fast_cycle_config.json with {module, class, enabled} for agents.energy.energy_review_agent_qwen, which DOES exist here. Nothing reads fast_cycle_config.json, so it is inert as written, and the runner's step list is code, not config. Worth a human look because it is a real proposal about how agents get wired, not an invented domain.

- **`general_patch.1785353298.py`** (23d, target `agents/core/general_patch.py`)
  <br>A DailyAnalysisAgent that calls memory.existence_model.am_i_alive() and memory.body_scan.full_scan() — both real modules here — and appends {timestamp, system_alive, last_body_scan} to memory/daily_log.json. Its own docstring calls integrate_into_execution_chain() a stub. Duplicates what the heartbeat and body_scan step already record, but it is about this system.

- **`general_patch.1786755265.py`** (6d, target `agents/core/general_patch.py`)
  <br>DANGEROUS. The only patch that rewrites a live file: it read-modify-writes fast_cycle_runner.py, inserting 'from agents.water_review_agent import water_review_agent' after the last top-level import. That module does not exist, so the next cycle start dies on ImportError. 'execution_chain' appears 0 times in the runner, so the registration half is a no-op. Read it before anything else.

Read `general_patch.1786755265.py` first. It is the only patch in the set that
writes to a file the system actually runs, and what it writes breaks the next
boot. It does not need approving to be worth knowing about.

No patch was applied and no patch was rejected in producing this report.

---

## EXECUTED — 22 August 2026

Emil ran the bulk-reject list above. The 34 JUNK patches were rejected with
`scripts/review_quarantine.py --reject`, one command each, exactly as printed.

    quarantine before   38 patches
    quarantine after     4 patches   (the REVIEW four, untouched)
    rejected/ before    20 patches
    rejected/ after     54 patches   (20 + 34)

NOTHING WAS DELETED. `--reject` MOVES the patch and its `.json` sidecar into
`patches/quarantine/rejected/`, which now holds 108 files (54 patches + 54
sidecars). Every rejected patch is still readable, and the move is reversible
with a plain `mv`. That is the point of the directory: a rejected patch is a
record of what the system tried to do, and deleting it would leave no evidence
of the attempt.

The partition was cross-checked against disk before anything moved: the 34 JUNK
names plus the 4 REVIEW names are exactly the 38 files that were in quarantine,
with no overlap and nothing unaccounted for. Afterwards the 4 remaining files
were diffed against the REVIEW list and matched exactly.

### The four that remain, for a one-by-one review later

    general_patch.1785306175.py   LLM rate-limit config + a live call_groq() on import
    general_patch.1785353287.py   config-driven agent loading (fast_cycle_config.json)
    general_patch.1785353298.py   DailyAnalysisAgent over the real existence_model/body_scan
    general_patch.1786755265.py   DANGEROUS — rewrites fast_cycle_runner.py to import
                                  agents.water_review_agent, which does not exist.
                                  Applied, the next boot dies on ImportError.

Read the last one first. It does not need approving to be worth knowing about.
