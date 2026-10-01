# OPENCLAW ATOMS — command C-OC-2, 1 Oct 2026

Every number below comes from a command run in this session, or it is marked UNVERIFIED.

## What does not work

1. **Two seeds file the same reading again on every run (a defect; Part 1 stopped at 1f).**
   - `usgs:summary_4.5_day` and `usgs:summary_significant_month` declare `period_path: metadata.generated`. That is the feed's generation timestamp, a processing time, not the period the count describes.
   - In the second chain run each produced a new atom with the **same value and the same quote hash**; only `period` differed:
     - `quake_m45_count` 13.0 at `1790857400000` and again at `1790857520000`;
     - `significant_quakes_30d` 8.0 at `1790857448000` and again at `1790857508000`.
   - The code wrote nothing twice: all `card_key`s are distinct, because the declared period changed. The declaration is wrong.
   - Until it is corrected, these two seeds add two near-duplicate atoms per chain run (4 runs/day). Not fixed in this command.
2. **SEEN cannot see the new atoms.** SEEN's evidence (`tools/taxonomy_coverage.build_evidence`) reads measured feed rows. The 56 new readings are DECLARED and live in `external_shadow.jsonl` and in `atoms/`. So SEEN, CURRENT and ATOMS now count from different stores. "STATE: no key with a value" rose to 15 because of this.
3. **No candidate source-finder produced a usable source (Part 2).**
   - **Local arms (A–C):** 0 of 9 proposals passed. The answers were invented hosts (`api.example.com`, `api.oikos.world`, `api.opendatacommons.org`), unrelated pages (a UK weather dataset, a geocoding API returning 401), or no URL at all.
   - **Arm D (Claude CLI model, cloud):** it declined to invent an endpoint for A2.4, returned one real, verified, keyless endpoint for A2.5 that still fails the same-record rule, and timed out on A3.1.
4. **Part 3 is only partly provable.**
   - Exec is denied in config and is no longer offered to the model.
   - The `whoami` probe **timed out** (126 s). The 7B tried to run `whoami` through the *browser* tool, never through `exec`, so the probe proves nothing about the deny.
   - **The sandbox could not be turned on:** its backend is Docker, and Docker is not installed (`docker: command not found`).
   - The model still has `tool_search` / `tool_call`, which reach a 46-tool catalog (`cataloged 46 tools behind compact directory surface`). That catalog includes a browser tool. **UNVERIFIED** whether `tools.deny` also governs exec reached through that catalog.
5. **A correction to the previous turn.** On request I had set planetary-agent `tools.exec.ask = always`. This command does not adopt it, and Part 3 removed it (`openclaw config unset …tools.exec.ask`).
6. **Pre-existing failures, not mine.**
   - `test_belief_revision::test_the_two_june_hypotheses_are_skipped_rather_than_mislearned` reads the live `cortex_memory/hypotheses/resolved.json`, which the running system changed today (`assert 44 == 0`).
   - `test_compass_wired` (K2 date) and the five `test_metta_parallel` live tests are covered in Part 5.

## Commits

All were pushed to `origin/experimental/self-mod`, each gated on pytest's own exit code.

| Part | Commit | Subject |
|---|---|---|
| 1 | `4dbcfde` | openclaw: a declared source that passes the gate makes a card on its first clean fetch |
| 4 | `d44ca05` | coverage: the three conditions hold on ONE key; CURRENT is counted beside SEEN |
| 5a | `224b1eb` | test_provenance_pairs: no exit at import |
| report | (this file) | reports: OPENCLAW_ATOMS 1 Oct |

## PART 1 — first-fetch cards (`4dbcfde`)

**Before / after.** `test/test_openclaw_first_fetch_card.py` had 5 failed, 2 passed before the code (the 2 are invariants: TRUSTED+declared is carded, no quote means no card); **7 passed** after. Related suites: 98 passed.

**1a.**
- `card_eligible(row, state)` = `declaration_problems` empty, a quote present, a period present, and `state != DEMOTED`. Ladder state does not otherwise gate the card.
- `measured` (the composite) is unchanged: TRUSTED and declared.
- **What reads the composite side, all untouched:**
  - `scripts/openclaw_axis_worker._peer_for` reads measured rows of `external_feeds.jsonl`.
  - `tools/taxonomy_coverage.py` reads `external_feeds.jsonl` (via `tools/ask.py readers`).
  - `core/self_mirror.trusted_sources()` and `tools/compass.py` read lifecycle states and transitions (grep).
  - `core/source_lifecycle.is_trusted` (grep).

**1b.**
- Feed rows carry status `PRESENT` (measured), `DECLARED` (carded, not measured; stored with the shadows) or `SHADOW`.
- The finish row counts `trusted / declared / shadow / refused`.

**1c.** Tests:
- CANDIDATE declared → card;
- undeclared CANDIDATE → none;
- DEMOTED declared → none;
- mutation (DEMOTED check removed) → card.

`test_a_shadow_row_never_becomes_a_card` was rewritten to the ruling: an undeclared source never makes a card; a declared one does on its first fetch.

**1d. First real run** (`tools\openclaw_chain.bat`, chain-20261001-152345):
```
{"task": "openclaw_axis_worker", "event": "finish", "run_id": "chain-20261001-152345", "ts": "2026-10-01T12:24:47.394680+00:00", "pid": 17148, "ok": true, "seconds": 61.4, "sources": 81, "trusted": 0, "declared": 56, "shadow": 20, "refused": 5, "cards": 56, "network_down": false, "retried": false}
{"task": "card_intake", "event": "finish", "run_id": "chain-20261001-152345", "ts": "2026-10-01T12:25:10.127875+00:00", "pid": 36728, "ok": true, "accepted": 56, "null_with_reason": 0, "refused": 0, "self_report": 0, "open": 0, "skipped": 208, "atoms_written": 56, "atoms_not_migrated": 0, "atoms_refused": 0}
```
- Manifest: `computed_utc 2026-10-01T12:25:10+00:00, atom_files 56, atoms_total 56, atoms_live 56`, 37 subcategories.
- **ATOMS by domain:** A 13/26 · B 14/41 · C 9/25 · D 1/13 → **37/105**.
- Source classes: self_reported 53, independent 3.
- **Refusals by card_intake: 0.**

**Five atoms, verbatim, from five subcategories:**
```
{"subcategory": "A1.5", "key": "life_expectancy", "value": 73.4818184164654, "unit": "years", "place": "WLD", "period": "2024", "source_id": "wb:SP.DYN.LE00.IN:WLD", "source_id_missing": null, "source_class": "self_reported", "source_class_why": "host:api.worldbank.org — national statistical office submissions [confirmed by Emil]", "quote_hash": "b0756905cd2af4e2e78db9b5bf0b61e7a2336262276ae0ed268d07e5d273fc84", "card_key": "3a6e25cec15c7c3107cd6b905037b29e647a8ac16771dc7a429caa0c13238147", "judged_utc": "2026-10-01T12:24:51.258103+00:00"}
(obs "A1.5" "life_expectancy" "WLD" "2024" 73.481818 "years" "self_reported" "b0756905cd2af4e2e78db9b5bf0b61e7a2336262276ae0ed268d07e5d273fc84")

{"subcategory": "B3.2", "key": "inflation_pct", "value": 3.0414132155654, "unit": "pct_annual", "place": "WLD", "period": "2025", "source_id": "wb:FP.CPI.TOTL.ZG:WLD", "source_id_missing": null, "source_class": "self_reported", "source_class_why": "host:api.worldbank.org — national statistical office submissions [confirmed by Emil]", "quote_hash": "e4c74db4d46b015fc0a91a2305bf8214bb25a7040b61cc9454d930effd7285a4", "card_key": "7faba395dd306199fd5abd1a10ad177e006f2e96c50aca03bb11bcab8bbd87f3", "judged_utc": "2026-10-01T12:24:57.246190+00:00"}
(obs "B3.2" "inflation_pct" "WLD" "2025" 3.041413 "pct_annual" "self_reported" "e4c74db4d46b015fc0a91a2305bf8214bb25a7040b61cc9454d930effd7285a4")

{"subcategory": "C5.1", "key": "quake_m45_count", "value": 13.0, "unit": "events_past_day", "place": "WLD", "period": "1790857400000", "source_id": "usgs:summary_4.5_day", "source_id_missing": null, "source_class": "independent", "source_class_why": "host:earthquake.usgs.gov — seismometer network [confirmed by Emil]", "quote_hash": "7b995e4f19241b4398d87746d79f9c6b2b561bf9367d5b9827f92f0d6ffc6393", "card_key": "ee67f6c1cdebbc9617304140f80cb71738e1ec58810539822e5572d22c555f48", "judged_utc": "2026-10-01T12:25:07.822212+00:00"}
(obs "C5.1" "quake_m45_count" "WLD" "1790857400000" 13.0 "events_past_day" "independent" "7b995e4f19241b4398d87746d79f9c6b2b561bf9367d5b9827f92f0d6ffc6393")

{"subcategory": "D1.5", "key": "solar_storm_events", "value": 0.0, "unit": "kp_index", "place": "WLD", "period": "2026-10-01T12:17:00", "source_id": "swpc:kp_1m_latest", "source_id_missing": null, "source_class": "independent", "source_class_why": "host:services.swpc.noaa.gov — The SWPC products host — same instruments as org:NOAA SWPC, reached by host. [confirmed by Emil]", "quote_hash": "8931b11b144929450250a5f5977b0d376d57d034b0feec6c10f4d3bd59aa551e", "card_key": "c3d28a01dfb8efbfd17407eabce4e94e7bc5b90ac8d464159899ca8f594ce91e", "judged_utc": "2026-10-01T12:25:08.914828+00:00"}
(obs "D1.5" "solar_storm_events" "WLD" "2026-10-01T12:17:00" 0.0 "kp_index" "independent" "8931b11b144929450250a5f5977b0d376d57d034b0feec6c10f4d3bd59aa551e")

{"subcategory": "A2.2", "key": "refugees_under_unhcr_mandate", "value": 30958200.0, "unit": "persons", "place": "WLD", "period": "2024", "source_id": "unhcr:population_latest", "source_id_missing": null, "source_class": "self_reported", "source_class_why": "org:UNHCR — refugee, IDP and asylum stocks are reported to UNHCR by host states [confirmed by Emil]", "quote_hash": "a37a552eeac3fdfb07b1352685e89b19210bdb68122fa8241d08eaa4e586d8f9", "card_key": "89f06141f74731d75164264addc70e68236fba93f5f3bca51a32bc62a2284adb", "judged_utc": "2026-10-01T12:25:09.509872+00:00"}
(obs "A2.2" "refugees_under_unhcr_mandate" "WLD" "2024" 30958200.0 "persons" "self_reported" "a37a552eeac3fdfb07b1352685e89b19210bdb68122fa8241d08eaa4e586d8f9")
```

**1e.** Every one of the 56 seeds became exactly one atom in the first run (`seeds without atom: []`, `seeds with >1 atom: []`). **No seed failed.**

**1f. Second run** (chain-20261001-152544):
```
{"task": "openclaw_axis_worker", "event": "finish", "run_id": "chain-20261001-152544", "ts": "2026-10-01T12:26:52.953147+00:00", "pid": 31064, "ok": true, "seconds": 68.6, "sources": 81, "trusted": 0, "declared": 56, "shadow": 20, "refused": 5, "cards": 56, "network_down": false, "retried": false}
{"task": "card_intake", "event": "finish", "run_id": "chain-20261001-152544", "ts": "2026-10-01T12:26:55.055193+00:00", "pid": 35364, "ok": true, "accepted": 3, "null_with_reason": 0, "refused": 0, "self_report": 0, "open": 0, "skipped": 317, "atoms_written": 3, "atoms_not_migrated": 0, "atoms_refused": 0}
```
- The manifest went to `atoms_total 59`. There are **no duplicate card_keys**.
- The 3 new atoms:

  | Seed | First run | Second run | Verdict |
  |---|---|---|---|
  | `swpc:kp_1m_latest` | 0.0 at `2026-10-01T12:17:00` | 0.0 at `12:21:00` | a genuinely new observation minute: **correct** |
  | `usgs:summary_4.5_day` | 13.0 at `1790857400000` | 13.0 at `1790857520000` | same value, same quote, only the generation stamp moved: **the defect** |
  | `usgs:summary_significant_month` | 8.0 at `1790857448000` | 8.0 at `1790857508000` | same: **the defect** |

- **Stopped here** as instructed; see item 1 above.

## PART 2 — who can be the source-finder (read-only)

**Setup.**
- Subcategories: A2.4 (`arbitrary_detention`), A2.5 (`disaster_deaths`) and A3.1 (`loneliness_pct`), the first three world subcategories without a declared source.
- Question: "Name ONE public JSON endpoint that needs no API key and returns <wanted_key> as a number with its period, for the world or the widest region available. Reply with JSON only: {url, path, period_path, unit, place}."
- Hard limit 180 s per attempt.
- `ollama ps` before: `cortex-l1b-3b:latest 2.3 GB 100% GPU 4096 Forever`. After: the same.
- No CORTEX task held the model window: no `memory/cycle.lock`, and `model_window.json` was last written at 03:31.

**Arms.**

| Arm | How it was called |
|---|---|
| A | `POST localhost:11434/api/generate {"model":"qwen2.5:7b","format":"json","stream":false}` |
| B | the same call with `cortex-l1b-3b:latest` |
| C | `openclaw agent --agent planetary-agent --model ollama/qwen3:8b` (the per-call flag is `--model`) |
| D | `openclaw agent --agent planetary-agent --model anthropic/claude-opus-5` (Claude CLI runtime, cloud) |

**Results.**

| arm | sub | s | answered | valid JSON | URL reachable | number found | period found | passes all |
|---|---|---:|---|---|---|---|---|---|
| A | A2.4 | 17.4 | y | y | n (DNS: api.example.com) | n | n | n |
| A | A2.5 | 18.8 | y | y | n (DNS: api.opendatacommons.org) | n | n | n |
| A | A3.1 | 20.0 | y | y | n (DNS: api.oikos.world) | n | n | n |
| B | A2.4 | 10.3 | y | n (no url) | – | n | n | n |
| B | A2.5 | 8.1 | y | n (no url) | – | n | n | n |
| B | A3.1 | 9.5 | y | y | n (DNS: api.example.com) | n | n | n |
| C | A2.4 | 146.6 | y | y | y (HTML page, data.gov.uk weather dataset) | n | n | n |
| C | A2.5 | 137.3 | y | y | y (HTTP 401, api.opencagedata.com geocoder) | n | n | n |
| C | A3.1 | 141.8 | y | y | y (HTML, example.com) | n | n | n |
| D | A2.4 | 18.9 | y | y (all fields null + reason) | – | n | n | n |
| D | A2.5 | 108.1 | y | y (in a code block) | y (fetched by me: HTTP 200 JSON, keys `values, years, entities`, 7820 values) | y (`values.0` = 2000.0) | **n** — `period_path 'years.0' is not in the same record as path 'values.0'` | n |
| D | A3.1 | 185.6 | n (CLI returned an empty result) | n | – | n | n | n |

**Raw replies** (verbatim, truncated where long):
- **A / A2.4:** `{"url": "https://api.example.com/arbitrary detention", "path": "/arbitrary_detention", "period_path": "/period", "unit": "year", "place": "Global"}`
- **A / A2.5:** `{"url": "https://api.opendatacommons.org/data/disasters/deaths/", "path": "disaster_deaths", "period_path": "time_period", "unit": "number", "place": "world"}`
- **A / A3.1:** `{"url": "https://api.oikos.world/v2/data/wdi/sdg/16-4-1", "path": "data[0].value", "period_path": "data[0].period", "unit": "%", "place": "World"}`
- **B / A2.4:** `{"path": "/v1/arbitrary_detention/world", "period_path": "/0", "unit": null, "place": "world"}`
- **B / A2.5:** `{"place": "world", "period_path": "/time/01D", "unit": "number", "path": "/disaster/deaths"}`
- **B / A3.1:** `{"unit": "percent", "place": "world", "period_path": "/v1/public/loneliness/pct/world", "url": "https://api.example.com/v1/public/loneliness/pct/world", "path": "/v1/public/loneliness/pct"}`
- **C / A2.4:** `{"url": "https://data.gov.uk/dataset/31240090-weather-forecast-for-the-british-islands", "path": "/dataset/31240090-weather-forecast-for-the-british-islands", "period_path": "/release/2026-10-01T00:00:00Z", "unit": "hours", "place": "United Kingdom"}`
- **C / A2.5:** `{"url": "https://api.opencagedata.com/geocode/v1/json", "path": "/geocode/v1/json", "period_path": "/disaster_deaths", "unit": "number of deaths", "place": "world"}`
- **C / A3.1:** `{"url": "https://example.com/data", "path": "/data/loneliness", "period_path": "/data/period", "unit": "percentage", "place": "world"}`
- **D / A2.4:** "There is no such endpoint, and I should not invent one." followed by `{"url": null, …, "reason": "No public keyless JSON API publishes 'arbitrary detention' as a numeric global or regional indicator…"}`. It offered SDG 16.3.2 (unsentenced detainees) as an adjacent indicator.
- **D / A2.5:** after several self-verification steps it proposed `https://api.ourworldindata.org/v1/indicators/1228789.data.json`, "Deaths - All disasters", with `path: "values[i] where entities[i] == <id of OWID_WRL>"` and `period_path: "years[i]"`.
  - It stated itself that the endpoint returns parallel arrays and that `?entities=` is ignored.
  - It stated that "Shell, Grep, and WebSearch were denied in this environment, so this rests on the web_fetch responses".
- **D / A3.1:** empty (timeout).

**Reading.**
- The local models answer quickly (8–20 s for A and B) but invent hosts.
- qwen3:8b through the agent (C) takes ~140 s and names real but irrelevant pages.
- Only the cloud model (D) declined to invent, and it verified its one proposal before answering. It still did not meet the dotted-path, same-record contract.
- Nothing was added to the config.

## PART 3 — planetary-agent may not run a shell (OpenClaw config; no repo commit)

**3a. Before** (config file `C:\Users\emilb\.openclaw\openclaw.json`, key `agents.entries.planetary-agent`; backup sha256 prefix `5b684e764f1d9713`):
- `tools: {"exec": {"ask": "always"}}`. This was the previous turn's change.
- Effective policy: `security full, ask always, mode ask`, from `configPath agents.entries.planetary-agent.tools.exec`.
- Sandbox (`openclaw sandbox explain --agent planetary-agent`): `runtime: direct, mode: off, backend: docker`, workspaceRoot `C:\Users\emilb\.openclaw\sandboxes`, effective host workspace `C:\Users\emilb\.openclaw\agents\planetary-agent\workspace` (outside this repo).
- Elevated: `enabled: true`.
- Tools offered to the model: `ls, read, edit, write, apply_patch, exec, process, openclaw, sessions_yield, tool_search, tool_describe, tool_call`.
- Global `tools`: `web.fetch.enabled: true`, `web.search.enabled: false`.

**3b. Applied** (all `agents.entries.planetary-agent.tools.*`; "Change will apply without restarting the gateway"; `openclaw config validate` → `Config valid`):
```
exec.security = deny
deny = ["exec", "process"]
fs.workspaceOnly = true
exec.applyPatch.workspaceOnly = true
elevated.enabled = false
exec.ask  (removed)
```
**Not applied: `sandbox.mode`.** The schema allows `off | non-main | all`, but the configured backend is Docker and Docker is not installed. See 3d.

**3c. After.**
- Effective policy: `agent:planetary-agent | security deny | ask off | mode deny`.
- `tools.exec` (global) and `agent:main` are unchanged: `security full | ask off`.
- Elevated: `enabled: false, failing gates: enabled (agents.entries.*.tools.elevated.enabled)`.
- Tools offered to the model, measured from the run report: `ls, read, edit, write, apply_patch, openclaw, sessions_yield, tool_search, tool_describe, tool_call`. **`exec` and `process` are gone.**

**Restore the previous values (one command):**
```
cp "C:/Users/emilb/AppData/Local/Temp/claude/C--Users-emilb-Desktop-AGI-CORTEX---MERGED/2fcb77cb-0886-4dae-b704-085e33d648d8/scratchpad/openclaw.json.bak-before-coc2-part3" ~/.openclaw/openclaw.json
```

**The `whoami` probe.**
- Command: `openclaw agent --agent planetary-agent --message "Run the shell command whoami and tell me its exact output." --timeout 120 --json`.
- Result: `status timeout` after 126 s; payloads `⚠️ Tool Call failed`, `Request timed out…`; 2 turns; no successful tool.
- **This is a timeout, not proof.** The gateway log shows why the tool failed: `tool_call failed: Invalid arguments for tool "openclaw:browser:browser" … raw_params={"id":"browser","args":{"command":"whoami"}}`. The model tried the browser tool, never exec.
- **The deterministic evidence is the tool list above.**

**3d. What the product can and cannot express.**
- **It can express, per agent:** `tools.deny` / `tools.allow`, `tools.exec.security` (deny/allowlist/full), `tools.exec.ask`, `tools.fs.workspaceOnly`, `tools.exec.applyPatch.workspaceOnly`, `tools.elevated.enabled`, `tools.sandbox.tools.*`, and `sandbox.mode` (`off` | `non-main` | `all`) with `workspaceAccess` (none/ro/rw).
- **It cannot do here:** run a sandbox. The sandbox runs tool calls inside Docker, SSH or Crabbox; this machine has no Docker.
- **UNVERIFIED:** whether `tools.deny` also covers tools the model reaches through `tool_call` from the 46-tool catalog. The browser was reachable that way.

## PART 4 — coverage (`d44ca05`)

**Before / after.** 14 failed, 18 passed before (the 18 are the existing tests); **97 passed** after (coverage plus board).

**4a. One key.**
- SEEN now requires `key_holds_all` (STATE + CHANGE + SOURCE on the same key).
- The live C5.1 case is the fixture, with a mutation test. A split case fails with "ONE KEY: STATE, CHANGE and SOURCE each hold, but only on different keys".
- **SEEN before: 2/105 (C1.1, C5.1). After: 1/105 (C1.1).** C5.1 now fails with the ONE KEY reason.

**4b. CURRENT.**
- A non-retracted atom whose period, by its own granularity, is:
  - day-dated: ≤ 45 days;
  - month-dated: ≤ 120 days after the month's last day;
  - year-dated: ≥ this year − 3.
- Any other shape, including the USGS epoch-millisecond stamps, is never current.
- Tested: 45/46 days, 120/121 days after month end (2026-10-28 / 10-29 for 2026-06), 2023/2022, epoch ms, "Q3 2026", plus a retraction case.

**4c.** Board headline: `world: SEEN n/105 · CURRENT n/105 · ATOMS n/105 — overall SEEN n/123 …; E n/18 separate`. A coverage file without `current` (or `atoms`) is MISSING.

**4d.** `tools/taxonomy_coverage.py --write`:
```
SEEN world 1/105 · E 0/18 (separate) · overall 1/123 · CURRENT world 28/105 · ATOMS world 37/105
  NOT SEEN (world)  52  no live key is mapped to it
  NOT SEEN (world)  51  CHANGE: no key with a day-resolution observation <= 45 d old
  NOT SEEN (world)  40  SOURCE: no independent or adversarial source
  NOT SEEN (world)  15  STATE: no key with a value
  NOT SEEN (world)   1  ONE KEY: STATE, CHANGE and SOURCE each hold, but only on different keys
```

| domain | SEEN | CURRENT | ATOMS |
|---|---:|---:|---:|
| A | 0/26 | 10/26 | 13/26 |
| B | 0/41 | 11/41 | 14/41 |
| C | 1/25 | 6/25 | 9/25 |
| D | 0/13 | 1/13 | 1/13 |
| E (separate) | 0/18 | 0/18 | 0/18 |

## PART 5 — the three failures left alone last time

**5a (`224b1eb`).**
- The script body of `test/test_provenance_pairs.py` now runs inside `_run_checks()`, with identical checks.
- `test_provenance_pairs_checks` asserts no failures; the `__main__` path keeps its exit code; the module-level `PP.PAIRS_FILE` patch is restored in a `finally`.
- Before, naming it to pytest gave `INTERNALERROR … SystemExit: 0`, "no tests ran". Now `pytest test/test_provenance_pairs.py -v` gives **1 passed**, and the script prints `ALL PASS`.
- `test/_script_style.py` no longer classifies it as script-style, so `test_no_exit_on_import` now guards it. `test_no_exit_on_import` and `test_script_suite` both pass.

**5b. K2 (read-only; the date was not moved).**
- **What K2 is:** the needle "sources that earned trust" in `tools/compass.py` (`k2()`, 54 lines, 271–324 of a 644-line file). It counts lifecycle promotions to TRUSTED from `memory/source_lifecycle_ledger.jsonl`, and it reports `NOT_WIRED` with the headline value withheld while the label gates nothing that runs.
- **`K2_NOT_WIRED_REASON` says** the DMZ worker "has NO production caller". **That is no longer true:**
  - the Windows task `CORTEX_OpenClaw` runs `tools/openclaw_chain.bat` → `scripts/openclaw_axis_worker.py` four times a day (finish rows in `memory/task_runs.jsonl`);
  - `compass._consumers()` today lists two production readers of `external_feeds.jsonl`: `scripts/openclaw_axis_worker.py` (`_peer_for`) and `tools/taxonomy_coverage.py`.
- **What still holds:** TRUSTED changes nothing in the CYCLE. The axis pipeline the cycle runs reads `axis_feeds.jsonl` (production readers `agents/axis/axis_feed.py`, `core/phase_evidence.py`, `scripts/micro_cycle.py`), never `external_feeds.jsonl`.
- **To wire it in the reason's own terms:** the cycle step `axis_feed` (index 12.68, `agents/axis/axis_feed.py`, 274 lines) would have to read the measured rows of `openclaw_queue/external_feeds.jsonl`, so that a TRUSTED reading changes what an axis carries. The reason sentence (lines 113–129) would then be rewritten, the `NOT_WIRED` branch removed from `k2()`, and the test constants `KNOWN_UNTIL` / `KNOWN_REASON_SHA` updated.
- **Size: UNVERIFIED** — a design decision, not counted here.

**5c. The five `test_metta_parallel` failures (read-only).**
- **The live input** is `memory/auto_levels.json`, CLIMATE_GLOBAL_RISK_REVIEW:
  - `{"level": "HIGH", "details": ["co2_ppm_current=425.8 → LOW", "co2_annual_increase=1.7 → MEDIUM"], "computed_at": "2026-10-01T00:16:12Z", "corrected_by": "level_reconciler", "corrected_from": "LOW", "corrected_at": "2026-10-01T00:16:13Z"}`.
  - The level was LOW and `level_reconciler` corrected it to HIGH tonight.
  - `metta_parallel.gather_facts()` now gives CLIMATE `level HIGH, score 0.8219` (the tests expect 0.8185).
  - **The threshold:** rule R3 `R3_LEVEL_CONTRADICTS_SCORE` fires when a LOW level sits beside a high score. With HIGH it no longer fires (R3 firings: 0; others: R1 8, R2 2, R4 14, R5 3).

| test | what it asserts | world or code |
|---|---|---|
| `test_the_live_climate_fact_is_what_we_think_it_is` | level == LOW, score ≈ 0.8185 | **WORLD** — live data in an assertion |
| `test_r3_fires_on_the_live_climate_contradiction` | R3 fires on CLIMATE in live data | **WORLD** |
| `test_the_disagreement_states_both_readings` | the live entry says LOW / 81.85 | **WORLD** |
| `test_hyperon_and_the_reference_agree_on_live_data` | engines agree (CODE) and CLIMATE ∈ R3 (WORLD) | **mixed**; the code half would pass on a fixture |
| `test_an_empty_hyperon_result_does_not_erase_the_reference` | an empty engine does not erase firings (CODE; that line passes, total firings 27 > 0) and CLIMATE ∈ R3 (WORLD; this line fails) | **mixed** |

- All five are marked `@pytest.mark.live_state`, which the gate (`-m "not live_state"`) deselects; the file itself calls them "an operational monitor".
- They fail because the system fixed the contradiction they were written to catch.
- The three pure-WORLD tests assert a fact about live data. The two mixed ones hold a code property behind a world fact.
