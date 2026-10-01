# OPENCLAW FIX — command C-OC-1, 1 Oct 2026

Every number below comes from a command run in this session, or it is marked UNVERIFIED.

## What does not work

1. **No atom exists yet: ATOMS 0/105.**
   - The real chain run (4f) produced 0 cards. The 56 new seeds are lifecycle CANDIDATEs, so their readings are stored as SHADOW, and a shadow never becomes a card.
   - `core/source_lifecycle.py` sets `PROMOTE_AFTER = 5` clean observations, which is about 1.25 days at 4 runs a day.
   - I did not run the worker five times in a row to force promotion. That would satisfy the letter of the lifecycle and defeat its stability check.
   - **UNVERIFIED** until the seeds promote. To check: `PYTHONIOENCODING=utf-8 venv/Scripts/python.exe tools/taxonomy_coverage.py` after the 2 Oct 23:50 chain.
2. **planetary-agent cannot answer through the script interface.**
   - The interface exists: `openclaw agent --agent planetary-agent --message ... --json`.
   - The local default model `qwen2.5:7b` never answered.
     - In 0b, "Reply with the single word READY." got `status: timeout` after 603 s: 6 assistant turns, 33,652 input tokens, payload "⚠️ Tool Call failed".
     - In Part 5, a JSON-only source question got `status: timeout` after 900 s: 9 turns, 53,869 input tokens, payload "⚠️ Tool Call blocked".
   - The 7B model loops on tool calls.
   - **Part 5 therefore has no proposed URL to check.**
3. **planetary-agent can write to this repo, with no human in the loop.**
   - Its effective exec policy is `security=full`, `ask=off`. Sandbox `mode: off`.
   - Its tools are `ls, read, edit, write, apply_patch, exec, process, openclaw, …`.
   - Nothing was changed (0d).
4. **None of the 25 earlier sources remains TRUSTED-and-measured** (3c).
   - All 25 lack `subcategory` and `place`; 24 lack a same-record period; 13 have no real unit; 11 use `#len`.
   - The 15 the lifecycle still calls TRUSTED now fall to SHADOW.
5. **Lifecycle-TRUSTED coverage is 0/105.** The 56 verified seeds cover **37/105** world subcategories with a declared, live-verified source (A 13/26, B 14/41, C 9/25, D 1/13). They need 5 clean runs to count as TRUSTED.
6. **Three of my own mistakes, each caught and repaired:**
   - **Live ledger writes.** My first Part 1 test runs wrote 6 rows into `memory/source_lifecycle_ledger.jsonl` (synthetic ids `wb_forest_wld`, `b`, `local`). I removed exactly those 6 rows (1513 → 1507) after a backup, and the tests now use `tmp_path` ledgers.
   - **Live atoms.** Part 4 test judges wrote 3 fixture atoms into the live `atoms/`. I removed them, and `card_intake._atoms_root_for` now writes live atoms only when the live observations file is the target; a mutation test pins this.
   - **A failing test was pushed.** `4d812c6` went out with `test_every_allowlisted_axis_exists_in_target_config` failing: my shell chain read `tail`'s exit status, not pytest's. It was fixed in `a05c282`, and every later commit is gated on pytest's own exit code.
7. **Pre-existing failures I did not touch.**
   - `test_compass_wired::test_the_expiry_has_not_passed`: `K2_NOT_WIRED_UNTIL = 2026-10-01`, today. This is a decision for Emil.
   - Five `test_metta_parallel` live tests: `memory/auto_levels.json` now says HIGH where the tests expect LOW.
   - `test/test_provenance_pairs.py` calls `sys.exit()` at import and crashes collection when named explicitly.
8. **The brief's numbers versus the file.**
   - `memory/verified_observations.jsonl` holds **29 rows = 28 ACCEPTED + 1 NULL_WITH_REASON**, not 29 ACCEPTED.
   - The chain run at 11:50 local had `skipped 207`. Mine had `skipped 208`.

## Commits

All were pushed to `origin/experimental/self-mod`, each on its own.

| Part | Commit | Subject |
|---|---|---|
| 1 | `e3cd49e` | openclaw: a source declares what it measures, where and when; a mislabelled number is refused |
| 2 | `1625ac1` | observations: a retraction is a row, and every reader sees one truth |
| 3 | `4d812c6` | openclaw sources by taxonomy: every world subcategory with a keyless dated JSON source gets one |
| 3 (fix) | `a05c282` | test: a TAXONOMY:<subcategory> axis is the goal's own tree, anything else still refused |
| 4 | `3017e54` | atoms: an accepted card becomes one atom in its subcategory folder |
| 6 | see §6 | reports: D1-W draft and taxonomy implementation, 1 Oct |

## PART 0 — the gateway (read-only)

**0a. Is anything listening, and who started it.**
- `netstat -ano | grep 18789` → `TCP 127.0.0.1:18789 0.0.0.0:0 LISTENING 12500`.
- PID 12500 is `"C:\Program Files\nodejs\node.exe" …\npm/node_modules/openclaw/openclaw.mjs gateway run`, started 13:18:32 local today. Its parent is an interactive `powershell.exe`, so it was started **by hand**.
- `curl http://127.0.0.1:18789/` → `http 200`.
- A scheduled task **OpenClaw Gateway** exists (logon trigger) with action `C:\Users\emilb\.openclaw\gateway.cmd`, which runs `node …\openclaw\dist\index.js gateway --port 18789` (v2026.6.10). It last ran at 08:45:41 today (at boot) with result `0xC000013A`: terminated by Ctrl-C or window close.
- No Run-key entry, startup-folder entry or service exists for it.

**Why my earlier answer differed.**
- The earlier command was `curl -s -m 5 -o /dev/null -w "gw %{http_code} %{time_total}\n" http://127.0.0.1:18789/` → `gw 000`, exit 7, plus `netstat -ano | grep 18789` → empty.
- It ran this morning, before 10:20 local. At that time the logon-started gateway had already been terminated (0xC000013A), and the current process did not start until 13:18.
- Both answers were true at their times.

**0b. Talking to planetary-agent without a browser.**
- The command:
  ```
  openclaw agent --agent planetary-agent --message "Reply with the single word READY." --json
  ```
- It exited 1 after 608,228 ms (wall clock). The JSON reported `status: "timeout"`, `timeoutPhase: "provider"`, `durationMs: 603188`.
- Model: `provider ollama, model qwen2.5:7b, responseModel qwen2.5:7b`.
- `assistantTurns: 6`, `usage input 33652 / output 124`. The payloads were "⚠️ Tool Call failed" and "Request timed out before a response was generated".
- **No READY.**
- Relevant help was read: `openclaw agent --help` (options `--agent, --message, --message-file, --model, --session-id, --thinking, --timeout, --json`) and `openclaw agents --help`/`list`.

**0c.** `ollama.exe` is not on PATH; I used `C:\Users\emilb\AppData\Local\Programs\Ollama\ollama.exe`.
```
NAME                       ID              SIZE      MODIFIED
nomic-embed-text:latest    0a109f422b47    274 MB    13 days ago
cortex-l1b-3b:latest       36da9c04d420    1.9 GB    2 weeks ago
cortex-l1-3b:latest        11d4d2afb1cf    1.9 GB    2 weeks ago
qwen2.5:3b                 357c53fb659c    1.9 GB    2 months ago
qwen3:8b                   500a1f067a9f    5.2 GB    7 months ago
qwen2.5:7b                 845dbda0ea48    4.7 GB    7 months ago
=====
NAME          ID              SIZE      PROCESSOR          CONTEXT    UNTIL
qwen2.5:7b    845dbda0ea48    6.1 GB    43%/57% CPU/GPU    16384      Stopping...
```

**0d. Agent tools, workspace and access.**
- `openclaw agents list`: planetary-agent has workspace `~\.openclaw\agents\planetary-agent\workspace` (AGENTS.md, DREAMS.md, IDENTITY.md, SOUL.md, USER.md, memory/), agent dir `~\.openclaw\agents\planetary-agent\agent` (openclaw-agent.sqlite), and model `ollama/qwen2.5:7b`. The config file is `~\.openclaw\openclaw.json`.
- Tools, from the run's system-prompt report: `ls, read, edit, write, apply_patch, exec, process, openclaw, sessions_yield, tool_search, tool_describe, tool_call`.
  - There is no browser tool and no fetch tool in its list.
  - `openclaw config get tools` shows `web.fetch.enabled: true` and `web.search.enabled: false`.
- `openclaw exec-policy show` gives agent:planetary-agent effective `security=full, ask=off` (askFallback deny). The run report shows `sandbox: {mode: off}`.
- **Write access to this repo: YES, in effect.** `exec`, `write` and `apply_patch` run unsandboxed as this Windows user, with no approval step.
- Nothing was changed.

## PART 1 — declarations (`e3cd49e`)

**Before / after.** `test/test_openclaw_declarations.py` went from 21 failed, 1 passed, 1 error before the code to **22 passed** after. The one pre-pass is the old-card-key invariant, which must hold both before and after.

**1a. Declaring a source.**
- `declaration_problems(source)` names each missing piece: `subcategory`, `place` (ISO3 / WLD / `point:<name>`), `unit` (not empty or "unknown"), and `period_path`/`data_date_path` in the SAME record as `path` (same parent). `#len` paths have no record.
- A source the lifecycle calls TRUSTED but which has problems → SHADOW, with `undeclared` listed. A shadow never becomes a card.
- A declared subcategory that does not resolve → REFUSED, by name.
- There is a mutation test (guard removed → card produced).

**1b. The World Bank header.**
- `worldbank_header_problem` refuses a path into element 0 of `[header, rows]` as "World Bank header, not an observation".
- Tested on a real capture of the Forest-area body (`test/fixtures/openclaw/wb_AG.LND.FRST.ZS_country_all.json`, header `"total":17490`), and live in 4f: `REFUSED scout:World Bank:59de1a4c … World Bank header, not an observation (path '0.total')`.
- `1.0.value` / `1.0.date` on the WLD capture passes (31.0951828663057, "2023").

**1c. New card fields.**
- `CARD_FIELDS` and `core/quote_gate.REQUIRED` gain `subcategory, place, period`.
- A card without them → MALFORMED.
- An old card's `card_key` is pinned to the value `verified_observations.jsonl` holds: `e8d18c26a2055de1…6165`.

**1d. Record-bound quotes.**
- `quote_from_record` cuts the quote starting AT the value, inside the JSON object that parses equal to the record the path walked.
- Tested with a body in which the same digits occur earlier in another field, plus a mutation test (first textual match → wrong field).

**1e. Network down.**
- `network_down` is true when nothing fetched and every http(s) source failed on the network.
- The finish row then carries `network_down` and `retried`, and the worker exits `EXIT_NETWORK_DOWN = 3`.
- `run_with_retry` retries the whole pass once after `NETWORK_RETRY_SEC = 120`.
- Tested with an injected getter, plus a mutation test.

**Existing fixtures updated to the new contract** (no assertion weakened): `test_quote_gate`, `test_openclaw_wire_to_the_gate` (the USGS body gains a same-record `day`), `test_card_intake_and_corpus`, `test_openclaw_axis_worker`. 125 passed; in a wider run, 456 passed and 1 failed (the date-driven compass test).

## PART 2 — retractions (`1625ac1`)

**Before / after.** 1 failed, 1 passed, 9 errors before; **11 passed** after.

**2a. The single door.**
- `core.card_intake`: `RETRACTIONS = memory/observation_retractions.jsonl`, plus `retract(card_key, reason, by)`, `retracted_keys()` and `accepted_rows(verdicts=("ACCEPTED",))`.
- An unreadable retractions file raises `RetractionsUnreadable`.
- `core/alarm_bands` (and `core/counterfactual_probe` through it), `scripts/agi_scoreboard` and `training/verified_corpus` read only through `accepted_rows`.
- `tools/ask.py readers memory/verified_observations.jsonl` after the change:
  ```
  READERS — code that reads it (2):
    core/card_intake.py   [117: _read_jsonl(...) -> .read_text(), 145: _read_jsonl(...) -> .read_text()]
    test/test_openclaw_wire_to_the_gate.py   [229: .read_text()]
  READERS, INDIRECT — calls a reading function of a direct reader (5):
    core/alarm_bands.py:248   via core/card_intake.py::accepted_rows()
    scripts/agi_scoreboard.py:114   via core/card_intake.py::accepted_rows()
    ... training/verified_corpus.py:100   via core/card_intake.py::accepted_rows()
  ```
- `accepted_rows` is written with a plain rebinding rather than `path or ACCEPTED`, because `ask.py` cannot follow an `or` expression (the same false negative I found this morning).
- `test_only_core_card_intake_opens_the_observations_file` uses `ask.readers` and has a mutation case.
- The import-linter contracts are unchanged: 3 kept, 2 broken, as before.

**2b. Audit of the 28 ACCEPTED rows (read-only).**

| # | key as written | value | quote (start) | url (start) | measures what the key says? |
|---|---|---|---|---|---|
| 1 | co2_ppm_mauna_loa | 426.62 | `September 09:   426.62 ppm` | gml.noaa.gov/ccgg/trends/monthly.html | YES |
| 3 | gdacs_wildfire_burned_area_ha | 18310 | `Orange impact for forestfire in 18310 ha` | gdacs … eventlist=WF | CANNOT TELL — one event's area; the key names no event and no total |
| 4 | usgs_m5plus_7d_count | 38 | `"count": 38` | fdsnws count, M5+, 2026-09-03..09-10 | YES |
| 5 | co2_annual_increase_ppm | 2.23 | `2025	2.23	0.11` | gml.noaa.gov/ccgg/trends/gr.html | YES |
| 6 | gdacs_wildfire_orange_red_7d_count | 0 | `"Belgium","fromdate":…` | gdacs … WF | YES — the gate recounted 0 in the window |
| 7 | usgs_m5plus_52w_weekly_counts | 2026 | `"count": 2026` | fdsnws count, M5+, 2025-09-12..2026-09-11 | YES (the unit says 52-week total; the key's "weekly" is misleading) |
| 8, 10, 17, 19, 21 | quakes_m45_last_24h | 13, 14, 18, 16, 15 | `13,"maxAllowed":20000}` … | fdsnws count, M4.5+, now-1days | YES |
| 9, 11, 16, 18, 20, 22, 23 | surface_temp_c_sofia | 27.2, 24.3, 19.0, 16.4, 21.8, 21.9, 15.0 | `27.2}}` … | api.open-meteo.com 42.7/23.3 current | YES (one city) |
| 12 | Youth literacy rate (ages 15-24) % | 83.3899993896484 | `83.389…,"unit":""` | WB country/all SE.ADT.1524.LT.ZS | **NO** — row 1.1 is Africa Eastern and Southern (AFE) 2024 |
| 13 | Fixed broadband subscriptions per 100 inhabitants | 1.41 | `1.41,"unit":""` | WB country/all IT.NET.BBND.P2 | **NO** — row 1.0 is AFE 2025 |
| 14 | Access to electricity (% of population) | 52.5981705163589 | `52.598…,"unit":""` | WB country/all EG.ELC.ACCS.ZS | **NO** — row 1.1 is AFE 2024 |
| 15 | Renewable internal freshwater resources per capita | 5392.94445818055 | `5392.944…,"unit":""` | WB WLD ER.H2O.INTR.PC mrv=1 | YES (world) |
| 24–28 | Minute-resolution planetary Kp index | 4, 4, 3, 2, 2 | `4,"estimated_kp":4.00,…` | swpc planetary_k_index_1m.json | YES (path `0.` is the OLDEST minute of the list, not the latest) |
| 29 | Forest area (% of total land area) | 17490 | `17490,"sourceid":"2",…` | WB country/all AG.LND.FRST.ZS | **NO** — the header's row count |

- Row 2 is the NULL_WITH_REASON row and is not audited as ACCEPTED.
- The AFE identity was verified by fetching each body and reading `rows[0..1].countryiso3code`.
- **Retracted through `ci.retract`** (by "Claude (C-OC-1 audit, 1 Oct 2026)"): rows 12, 13, 14 and 29.
- `accepted_rows()` is now 24.
- `memory/verified_observations.jsonl` sha256 is unchanged before and after: `12585ed0a4dcdfd8…304c`.

**2c. The training corpus.**
- `training/verified_corpus.build()` does not train. Two dry builds gave the same `sha256`, so it is deterministic; only `built_utc` varies.
- Rebuilt: 635 rows → **631**, `sensor_card` 29 → **25**, sha256 `f9672235182bb779…e452`.
- The corpus files are rebuilt by the morning chain (runtime churn), so they are **not committed**.

## PART 3 — seed sources by taxonomy (`4d812c6`, fix `a05c282`)

**Before / after.** 3 failed, 2 passed, 1 skipped before; 85 passed after, and 255 at the fix.

**3a / 3b. The live probe.**
- 75 candidates, each fetched once live through `openclaw_axis_worker.fetch_one` and the Part 1 checks.
- The first pass gave 49 PASS. Eight World Bank candidates had failed only on `ReadTimeout` and were re-fetched once at 90 s.
- **Final: 56 PASS, 19 FAIL.**
- **PASS** means a finite value, a period from the same record, no declaration problem, and a quotable value.
- The 56 PASS entered `config/openclaw_sources.json` with `subcategory, axis TAXONOMY:<sub>, key, unit, place, url, path, period_path, org, why, _verified{value, period}`.

**Failed candidates:**

| sub | candidate | reason |
|---|---|---|
| A1.1 | wb:SN.ITK.DEFC.ZS (undernourishment) | latest WLD value is null (`expected a number, got NoneType`) |
| A1.1 | wb:SH.STA.STNT.ZS (stunting) | no world figure — body `[header, null]` |
| A2.2 | wb:SM.POP.REFG.OR | no world figure — one-element error body |
| A2.6 | wb:SH.UHC.SRVS.CV.XD, wb:SH.UHC.OOPC.10.ZS | no world figure — one-element error body |
| A4.3 | wb:SL.TLF.0714.ZS (child labour) | no world figure |
| A4.5 | wb:SI.DST.10TH.10 (top-10% income share) | no world figure |
| A5.1 | wb:SE.PRM.UNER (out of school) | no world figure |
| A5.6 | wb:SL.UEM.NEET.ZS | no world figure |
| B1.1 | wb:VC.BTL.DETH (battle deaths) | no world figure |
| B2.1 / B2.2 / B2.5 | wb:RL.EST, CC.EST, GE.EST (WGI) | no world figure — WGI estimates are not served for WLD |
| B3.3 | wb:GC.DOD.TOTL.GD.ZS | no world figure |
| C3.1 | wb:ER.H2O.FWST.ZS (water stress) | no world figure |
| C1.1 | gw:co2_trend, gw:methane (global-warming.org) | the value is a JSON **string** ('427.98', '1939.44'); the DMZ rule requires a number |
| C1.3 | gw:temperature | the value is a JSON string ('1.66') |
| A5.5 | who:healthy_life_expectancy | not quotable — 61.91107106 is not verbatim in its record |

**Named in the candidate lists, not probed, because they fail Part 1 by construction:**
- NASA EONET category counts and CelesTrak object counts: the value is `#len`, so there is no record to quote or date.
- OpenAlex `meta.count`: no period in the same record.
- The USGS fdsnws `count` endpoint: no date anywhere in the body.

**3c.** As item 4 above: 0 of the 25 earlier sources remain TRUSTED-and-measured.

**3d. Sources and coverage.**
- Sources before: 25 (4 seed + 21 discovered). After: **81** (60 seed + 21 discovered).
- Declared and verified: **37/105** world subcategories — A 13/26, B 14/41, C 9/25, D 1/13.
- Lifecycle-TRUSTED and declared: **0/105** today.
- `tools/build_taxonomy_key_map.py` now treats a seed's declared subcategory as the rule for its key, and refuses a contradiction. The map is now 233 live keys, 198 mapped, 35 UNMAPPED.
- **Judgement:** `test_source_lifecycle`'s "discovered sources outnumber the seed" was rewritten to its intent: every discovered source still reaches the worker. With 56 verified seeds the ratio no longer measures discovery.

## PART 4 — atoms (`3017e54`)

**Before / after.** A collection error before (no module); **13 passed** after, 15 with the two live-root tests, and 174 in the related set.

**4a.** `core/atoms.py`:
- `write` (JSON line plus `(obs …)` MeTTa line); `atom_of`, which raises `AtomRefused` on an unresolvable or domain-E subcategory or a missing value, unit, place or period;
- `read`, which skips retracted keys; `compute_manifest` and `write_manifest`;
- `--selftest`, which reports every integration LIVE: taxonomy, reporter_independence, openclaw_sources, card_intake → atoms.write, and coverage counts ATOMS.

**4b.** `card_intake` counts `atoms_written / atoms_not_migrated / atoms_refused`.

**4c.** `MANIFEST.json` is recomputed from disk. There is a mutation test: an incremented manifest would keep a hand edit.

**4d.** `atoms/*` is gitignored and `!atoms/.gitkeep` is tracked.

**4e.** Coverage gains `totals.atoms`. The board headline adds `ATOMS n/105 world`, and a coverage file without it is MISSING.

**4f. The real run.** `tools\openclaw_chain.bat`, chain-20261001-145106:
```
{"task": "openclaw_axis_worker", "event": "finish", "run_id": "chain-20261001-145106", "ts": "2026-10-01T11:52:05.539943+00:00", "pid": 34324, "ok": true, "seconds": 58.7, "sources": 81, "trusted": 0, "shadow": 76, "refused": 5, "cards": 0, "network_down": false, "retried": false}
{"task": "card_intake", "event": "finish", "run_id": "chain-20261001-145106", "ts": "2026-10-01T11:52:05.665476+00:00", "pid": 34140, "ok": true, "accepted": 0, "null_with_reason": 0, "refused": 0, "self_report": 0, "open": 0, "skipped": 208, "atoms_written": 0, "atoms_not_migrated": 0, "atoms_refused": 0}
```
- Worker summary line: `[DMZ] 0 trusted / 76 shadow / 5 refused / 0 card(s) of 81 sources (29 TRUSTED, 71 CANDIDATE, 5 DEMOTED)`.
- The 5 refused were `deliberately_broken_path`, `scout:UCDP/PRIO:cbd450c7` (local://), `scout:World Bank:59de1a4c` (**World Bank header, not an observation**), and two Open-Meteo paths that resolve to lists.
- Manifest: `atom_files 0, atoms_total 0, atoms_live 0, subcategories_with_live_atoms []`.
- **ATOMS 0/105 in every domain** (A 0/26, B 0/41, C 0/25, D 0/13; E 0/18 separate).
- **No atom exists to paste verbatim.** Both atom shapes are pinned by `test_one_accepted_card_is_one_json_line_and_one_metta_line`:
  ```
  {"subcategory": "C2.1", "key": "forest_area_pct", "value": 31.0951828663057, "unit": "pct_land_area", "place": "WLD", "period": "2023", "source_id": ..., "source_class": ..., "quote_hash": "<sha256 of the quote>", "card_key": "ck1", "judged_utc": "..."}
  (obs "C2.1" "forest_area_pct" "WLD" "2023" 31.095183 "pct_land_area" "<source_class>" "<quote_hash>")
  ```

## PART 5 — planetary-agent as source-finder

- **Subcategory chosen:** A2.4 Legal security, the first world subcategory without a declared, verified source. Its first wanted key is `arbitrary_detention`. Every subcategory is lifecycle-untrusted today, so "TRUSTED" was read in the Part 3 sense.
- **The question** (`--message-file`, fresh `--session-id`, `--thinking off`, `--timeout 900`):
  > Name ONE keyless JSON endpoint (no API key, no login) that publishes the global or per-country value of "arbitrary_detention" (taxonomy subcategory A2.4 Legal security). Reply with JSON only, no prose, exactly these fields: {"url": "...", "path": "dotted path to the number", "period_path": "dotted path to that number's own year or date in the SAME record", "unit": "...", "place": "ISO3 or WLD"}. If you do not know one, reply {"none": "reason"}.
- **The reply:** `status: "timeout"` after 907 s wall clock (`durationMs 900099`), model `qwen2.5:7b`, 9 assistant turns, 53,869 input / 212 output tokens, and no successful tool. Payloads: `⚠️ Tool Call blocked` and `Request timed out before a response was generated…`.
- **Checks:** none could run, because no URL was proposed. The source was not added.

## PART 6 — reports and branches

- **6a.** `claude/reports/D1W_DRAFT_2026-10-01.md`, `claude/reports/TAXONOMY_IMPL_2026-10-01.md` and this report are committed as "reports: D1-W draft and taxonomy implementation, 1 Oct" (hash in the reply).
- **6b.** Both branches were already fully contained in `experimental/self-mod` (`git log experimental/self-mod..<b>` gave 0 commits), so pushing them publishes no new content.
  - `git push -u origin fix/retire-self-grading-loop` → `* [new branch]`.
  - `git push -u origin wt/edges` → `* [new branch]`.
  - `git ls-remote --heads origin`:
    ```
    3017e54dfed02b86895cb735bb522b3b77717203	refs/heads/experimental/self-mod
    b42bec91068bbefbf0200fc7aa50764f42143317	refs/heads/feat/scorer-self-check
    ac013e44db7bae1425659902091ca5223abe7bc1	refs/heads/feature/lidaction-guard
    552113579495bec3f26f2c9905e43d71af65ed51	refs/heads/fix/climate-normalizer-dead-inputs
    6654a4f01bd5ceb6ef842e26af5d5ba711b3237a	refs/heads/fix/education-culture-dead-scorer
    528e43cef62f958480677067abdcac199ea135b4	refs/heads/fix/k1a-seal-axis-predictions
    104fb42cde6157ea95860fe4e30c2a2285d6bc51	refs/heads/fix/retire-self-grading-loop
    a7e90051b3290f7e033f4355a7c2c3c7c6757612	refs/heads/master
    89ebfdba35d19c27fac57f930035cbe1895288a2	refs/heads/survival/keep-awake
    4f13060111519fd941741db3eb697bbf38fcb1fe	refs/heads/wt/edges
    ```
    The local `master` (3bc920e) is behind `origin/master`. I did not touch it.
- **6c.** See the end of this section; the numbers are final after the reports commit.

STATUS_TABLE
