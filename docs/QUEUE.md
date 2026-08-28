## STATUS
last_updated_utc: 2026-08-28T13:58:17Z
last_item_done: ITEM 3.1 — a truncated answer is no longer "nothing urgent"
current_item: ITEM 3.2 — the Gemini budget
current_state: RUNNING
gate_closed_reason: - (OPENED 13:58:08Z; cycle 2026-08-28T12:15:20 pid 30144 sealed after 103min, held the gate 12:15-13:58)
next_action_needed_from_claude: guarded suite running; on VALID diff against 29, commit 3.2, then 3.3

## ORDER OF WORK
Work strictly down this table. It is the map; the items below are the detail.
Keep the state column current — it is the only place a human should have to look.
| # | item | state | gate |
|---|------|-------|------|
| 1 | Prepare the K1 move | DONE 2026-08-28 | READONLY |
| 2 | Commit docs/QUEUE.md | DONE 2026-08-28, 77b4838 (not pushed) | NOCYCLE |
| 3 | Apply 3.1-3.9 | 3.1 DONE; 3.2 written, suite INVALID (cycle mid-run) | NOCYCLE |
| 4 | Why the cloud tier is abandoned, f)-i) | DONE 2026-08-28 except f) — needs 429 bodies | READONLY |
| 5 | The voice that never spoke | TODO | NOCYCLE |
| 6 | Two lies on the expression panel | TODO | READONLY |
| 7 | Make the compass produce a number | TODO | NOCYCLE |
| 8 | The thirtieth failure | DONE 2026-08-28 — baseline is a recorded 29 | NOCYCLE |
| 10 | The suite has no gate while it runs | TODO | NOCYCLE |

# QUEUE — Claude Code works this file top to bottom

The human types one line: "Read docs/QUEUE.md and continue from the first
unfinished item." When context fills, the human types /clear and that same line
again. This file remembers where work stopped; the context does not.

## HOW TO WORK THIS FILE
1. Read from the top. Find the first item whose status is TODO.
2. Check the gate for that item (below). If the gate is closed, skip to the next
   TODO item whose gate is open. If no item's gate is open, STOP and say which
   gate is closed and what would open it.
3. Do the item exactly as written. Do not expand its scope.
4. When done, edit THIS FILE: change the item's status to DONE, add the date,
   the commit sha if any, and a five-line summary of what was found or changed.
   Never delete an item; annotate it.
5. Move to the next item. Do not stop between items to ask permission.
6. When you reach an item marked BLOCKED, STOP THERE. Print the item's title and
   the words "this item is written by Claude after the previous report". Do not
   invent its content.
7. New findings do NOT become items while an item is running. If you find something
   outside the current item's scope, record it under a "## HOLDING" heading at the end
   of this file, note it in the commit body, and KEEP WORKING. Do not stop to ask
   whether to fold it in — the answer is always no. Claude promotes HOLDING entries to
   numbered items after the current item reports. Nothing is lost, nothing jumps the queue.

## GATES
- GATE:READONLY — always open. Reads, network probes, AST parsing. No writes to
  tracked files, no test suite, no commits.
- GATE:NOCYCLE — open only when no cycle is live. Check BOTH:
    memory/cycle.lock exists?  and  memory/heartbeat.json updated_utc age?
  A cycle is live if cycle.lock exists AND its pid is running. If live, this
  gate is CLOSED. Items behind it write code, run the suite, and commit.

## STANDING RULES FOR EVERY ITEM
- Windows. venv\Scripts\python.exe — system python is NOT on PATH.
- English only in all output. Console breaks Cyrillic.
- AST for anything asserted about code. Never grep prose and call it a fact.
- If a claim cannot be verified in this run, write NOT VERIFIED beside it.
- Never `git add -A`. Never stage data/, V-Dem, CSV, media, .env, or the ~48
  runtime-churn files under memory/, snapshots/, news/.
- Guarded files change only with a human approval quoted verbatim in the commit
  body: config/scheduler.json, BOUNDARIES.md, canon.py, target_config.json
  weights, config/homeostasis.json, config/reactions.json.
- Any module that can write to a ledger, journal or learning trace DRY-RUNS by
  default and needs an explicit --write.
- Tests never touch live state. A fixture must prove the real files byte-identical
  after the test run.
- Read the suite summary line and diff the FAILED list against the baseline of 29
  before every commit.

## PUSH RULE
Push without asking a human, only if all three hold machine-checked:
1. the suite summary line matches the baseline of 29 failed AND the FAILED list
   is byte-for-byte identical;
2. the diff contains no data, V-Dem, CSV, media, or .env;
3. the branch is feature/lidaction-guard, never master.
If any fails: do not push, and record why in this file under the item.

---

## ITEM 1 — COMMAND 32 PART 1A: PREPARE THE K1 MOVE
STATUS: DONE 2026-08-28 (no commit — GATE:READONLY, nothing applied)
GATE: READONLY

SUMMARY (five lines)
1. Fixing row #6 in axis_source_map.json moves K1 by ZERO. goal_score_calculator.py
   never reads memory/composed_indicators.json — AST-verified, 14 refs, none in it.
2. The scorer resolves `protected_terrestrial_area_pct` only via obs key
   `wb_ER.LND.PTLD.ZS`, which no live file produces. Same for `wb_SE.PRM.CMPT.ZS`.
3. Both values exist TODAY at api.worldbank.org country/WLD via the `_wb_world()`
   helper already in core/global_indicators.py: ER.LND.PTLD.ZS 2025 = 16.511660312023
   (identical to the OWID number), SE.PRM.CMPT.ZS 2024 = 88.0215835571289.
4. Four lines (2 in core/global_indicators.py, 2 in goal_score_calculator.py) move
   measured_weight 100 -> 114, K1 57.8% -> 65.9%, unmeasured_weight 14 -> 0.
5. Of the four numbers PLANETARY_POTENTIAL_REVIEW publishes, only two would change;
   cortex_scores_latest.json (0.5) and axis_history.json (50.0) are untouched by any
   of this — PLANETARY_POTENTIAL_REVIEW is absent from AXIS_SCORERS (19 keys).
COMPASS: K1 = measured weight / 173. Today 100/173 = 57.8%. The unresolved 14
weight is two axes: EDUCATION_CULTURE_REVIEW (primary_completion_rate) and
PLANETARY_POTENTIAL_REVIEW (protected_terrestrial_area_pct). This item prepares
the only change found in Part 0 that moves the compass. It applies nothing.

A1. THE DIFF FOR ROW #6
Part 0 verified: wdpa_protected_area_share with csvType=full, row_key="World",
column_name="er_lnd_ptld_zs" returns World 2025 = 16.51166. Print the exact JSON
block for config/axis_source_map.json entry at line 345 as it exists now, and the
exact block it would become. Do not write it. Re-fetch once and confirm the value
has not moved.

A2. DOES THE FIX ACTUALLY REACH THE AXIS?
Trace the full resolution chain for PLANETARY_POTENTIAL_REVIEW's primary_metric
`protected_terrestrial_area_pct`, reading code only:
  axis_source_map.json -> composer_specs.json -> composed_indicators.json ->
  trends / last_observations -> goal_score_calculator.py
For each hop give file:line and the exact key that must match. State plainly:
  - Is a corrected axis_source_map entry sufficient, or must the candidate also be
    promoted into config/composer_specs.json?
  - If promotion is required, print the exact composer_specs.json block that would
    be added, shaped like an existing anchor_annual entry.
  - Name every other file needing a key for the metric to resolve.
This decides whether fixing row #6 moves K1 or changes nothing. Answer before
anything is edited.

A3. A WORLD SOURCE FOR primary_completion_rate
Probe with urllib for a source returning a real WORLD value today. Try at least:
  - unstats.un.org/sdgapi/v1/sdg/Series/Data?seriesCode=<code>&areaCode=1 with
    "Reporting Type": "G" — find the right seriesCode yourself
  - World Bank API indicator SE.PRM.CMPT.ZS, country=WLD
  - OWID grapher csvType=full, row_key="World"
For each: exact URL, HTTP status, whether a World row exists, and if so the value
and its year. Register nothing. Write nothing to config/. If none returns a World
value, say so — that is a real answer.

A4. WHAT THE COMPASS WOULD READ
From snapshots/master/goal_score_latest.json alone, compute offline what
measured_weight, coverage_of_goal and composite_score become if
PLANETARY_POTENTIAL_REVIEW resolves at 16.51166. Show the arithmetic. If the
composite cannot be recomputed without running the scorer, say so and give only
the weight arithmetic (100 -> 107, of 167 and of 173).

A5. THE FOUR NUMBERS FOR ONE AXIS
Part 0 found PLANETARY_POTENTIAL_REVIEW carrying four values on disk today:
  goal_score_latest.json = None
  cortex_scores_latest.json = 0.5 (SELF_REPORTED, generic scorer)
  memory/axis_history.json = 50.0
  memory/goal_score_history.json = 60.0 (score_source: llm_level)
For each, name the writer (file:line) and the step that calls it. Then state which
of the four the promotion in A1/A2 would silence, and which would keep publishing
their own number afterwards.

WHEN DONE: write the answers into this file under this item, set STATUS: DONE with
the date, and move to ITEM 2.

### ANSWERS — 2026-08-28, read-only run

**A1.** Re-fetched 2026-08-28, HTTP 200. `csvType=full` header
`entity,code,year,er_lnd_ptld_zs`; 2915 data rows; 13 World rows; last
`World,OWID_WRL,2025,16.51166`. Emulating `composer._csv_select` with
row_key=World + column_name=er_lnd_ptld_zs reads 16.51166, year 2025. Value has
not moved since the Part 0 run. Current and proposed blocks printed in the report.

**A2.** Chain is BROKEN between composer and scorer.
- `config/axis_source_map.json:345` — candidate, no `row_key`/`column_name`.
- `config/composer_specs.json` PLANETARY_POTENTIAL_REVIEW `portfolio.anchor_annual.sources` = **[] (empty)**.
- `experiments/composers/composer.py:66` writes `memory/composed_indicators.json`.
- `goal_score_calculator.py:433-434` builds `last_obs` from FOUR loaders — none is
  composed_indicators.json (AST: 14 refs repo-wide, zero in goal_score_calculator.py).
- `goal_score_calculator.py:199` maps `protected_terrestrial_area_pct` -> `wb_ER.LND.PTLD.ZS`.
- No live file carries that key: `data/last_observations.json` has 8 keys and is
  frozen 2026-06-17 (its only writer, root `self_observer.py:70-72`, is imported by
  nothing — AST-verified); `memory/probed_signals.json` does not exist;
  `goal_score_calculator.py:136-150` `put()` list has 12 keys, not this one.
VERDICT: axis_source_map fix alone = no effect. composer_specs promotion = no effect
on K1 either. The metric resolves only when `wb_ER.LND.PTLD.ZS` lands in last_obs.

**A3.** primary_completion_rate WORLD sources, probed 2026-08-28:
- UN SDG `SE_TOT_CPLR` areaCode=1 — HTTP 200, 225 rows, all Reporting Type G,
  World present. Slice Location=ALLAREA/Sex=BOTHSEX/Education level=PRIMAR/Quantile=_T:
  **88 (2024)**, source UNESCO UIS+GEM. Needs a 4-key `where`; the reader supports it
  (`experiments/composers/readers.py:140`) and raises without it (`readers.py:167-175`).
- World Bank `SE.PRM.CMPT.ZS` country=WLD — HTTP 200, **88.0215835571289 (2024)**.
- OWID `primary-completion-rate` csvType=full — HTTP 200, 7390 rows, **0 World rows**.
Two independent world values agree. OWID does not have one.

**A4.** Exact (recompute of the file reproduces its own composite 0.6284):
base weighted_sum 62.8442 / measured_weight 100.
+PLANETARY only: 66.696921/107 -> composite 0.6233, coverage_of_goal 0.6407, K1 61.8%.
+BOTH: 72.858432/114 -> composite 0.6391, coverage_of_goal 0.6826,
coverage_of_measurable 1.0000, unmeasured_weight 0, K1 65.9%.
goal_covered stays FALSE either way (0.6826 < 0.80) — the 53 semantic weight is the wall.

**A5.** Writers: goal_score_latest.json <- goal_score_calculator.py:412 `persist()`,
called fast_cycle_runner.py:2692-2693, step goal_score_calculator (12.6, D_SCORE).
cortex_scores_latest.json <- cortex_scoring_engine.py:1593, step scoring_engine
(12.4, D_SCORE). axis_history.json <- memory/trend_tracker.py:80 `_save_history()`,
step trend_tracker (index 3, B_SENSE). goal_score_history.json <-
agents/core/feedback_loop.py:209 `save_score_snapshot()`, step feedback_loop (20, G_LEARN).
CHANGED by the fix: goal_score_latest (None -> 0.5504) and goal_score_history
(60.0/llm_level -> 55.04/measured, via feedback_loop.py:74-75 calling compute_goal_score).
UNCHANGED: cortex_scores_latest (0.5) and axis_history (50.0) — PLANETARY_POTENTIAL_REVIEW
is not in AXIS_SCORERS (cortex_scoring_engine.py:1463, 19 keys) so score_generic keeps
returning 0.5, and trend_tracker just multiplies that by 100.

## ITEM 2 — COMMIT docs/QUEUE.md
STATUS: DONE 2026-08-28 — committed, NOT pushed (push rule condition 1 failed)
GATE: NOCYCLE
Commit this file alone. Message: "queue: Claude Code follows docs/QUEUE.md between
clears". Apply the push rule. Nothing else in the diff.

GATE CHECK 2026-08-28T08:44:27Z — CLOSED. memory/cycle.lock existed, pid 6752 alive,
heartbeat 90s old. Item deferred.
GATE CHECK 2026-08-28T10:09:07Z — OPEN. cycle.lock absent, heartbeat.json empty; the
cycle sealed at 09:46:18Z (CYCLE_FINISHED, 6076.8s, 19 steps, 11 degraded,
integrity 61.3%). Proceeded.

SUITE, run on the unmodified tree before the commit:
  37 failed, 3213 passed, 6 skipped, 5 deselected, 1 xfailed, 16 warnings in
  1097.70s (0:18:17)
BASELINE IS 29. The list is NOT byte-identical, so PUSH RULE CONDITION 1 FAILED and
nothing was pushed. The 8 extra failures were diagnosed, not assumed — all eight were
re-run alone and every one asserts the same fact:

  test_reaction.py::test_the_flag_is_off_in_the_committed_config
      assert True is False  where True = rx.enabled()
  test_reaction.py::test_with_the_flag_off_no_model_call_is_made
  test_reaction.py::test_and_it_says_why_rather_than_pretending_nothing_happened
      AssertionError: assert 'reaction.enabled' in 'answered'
  test_reaction.py::test_the_selftest_passes                assert 1 == 0
  test_perplexity.py::test_it_is_disabled_in_the_committed_config
      assert True is False  where True = px.enabled()
  test_perplexity.py::test_the_selftest_passes              assert 1 == 0
  test_glass.py::test_the_selftest_passes                   assert 1 == 0
  test_extra_calls.py::test_the_switch_file_is_still_protected_and_still_off
      assert True is False

CAUSE: config/reactions.json is flipped to "enabled": true in BOTH the reaction and
perplexity blocks, uncommitted in the working tree (git diff shows false -> true; the
last commit touching the file is 4bd4394, which left both false). config/reactions.json
is a GUARDED file — Claude does not touch it. These 8 are the suite correctly
detecting a human's live change.
  CORRECTED 2026-08-28T11:32Z, after the 3.1 run: SEVEN of those eight are
  flag-driven, not eight. test_glass.py::test_the_selftest_passes still FAILS with
  the flags off, so it was never a reactions failure and this record was wrong to
  fold it in. Its real cause, reproduced directly:
      core.receptors.read_firewall_drops() -> available=False,
      "PermissionError: [Errno 13] Permission denied:
       C:/Windows/System32/LogFiles/Firewall/pfirewall.log"
  An unelevated shell cannot read the Windows firewall log; glass._selftest checks
  "panel 2 read the firewall log" and fails. Environment, not code.
  So: 37 - 7 flag-driven = 30, and the documented baseline of 29 does not include
  glass. Either the 29 was measured in an elevated shell, or the baseline is stale
  by one. NOT VERIFIED which; it needs one run as administrator to settle.
  No failure in either list is attributable to a change made by this session.

Worth naming: test_reaction.py::test_and_it_says_why_rather_than_pretending_nothing_
happened is failing on precisely the defect ITEM 3.9 exists to fix — the panel's
hard-coded sentence about reaction.enabled. The test already knew.

COMMIT: docs/QUEUE.md alone, staged by explicit path (the tree carries 766 other dirty
paths of cycle runtime churn; none staged, no `git add -A`).

## ITEM 3 — COMMAND 32 PART 1B: APPLY
STATUS: TODO
GATE: NOCYCLE
Each numbered step is a SEPARATE commit. Run the suite before each, diff the FAILED
list against the baseline of 29, apply the push rule per commit. Order matters:
3.1-3.3 stop the system publishing a false all-clear. 3.4 moves K1. The rest are
the audit debt.

3.1 A TRUNCATED ANSWER MUST NOT BECOME "NOTHING URGENT"   [highest priority today]
Item 4(e) proved: Gemini returns finish_reason=length -> _parse_llm_json raises ->
agents/internet/internet_agent.py:993-994 returns urgency=LOW, sentiment=NEUTRAL,
summary=ctx[:200] (the raw INPUT republished as the analysis) -> :1035-1052 rebuilds
the dict and drops the 'error' key -> news/news_latest.json carries no marker at all.
14 of 24 axes today. Three readers gate on HIGH/CRITICAL and skipped all of them:
agents/core/cortex_core_agent.py:32-36, core/cortex_orchestrator.py:268,
memory/semantic_memory.py:103.
Do all four:
  (a) core/groq_backend.py:751-759 — call_groq() discards _meta, which carries
      finish_reason. Route agents/internet/internet_agent.py (imports call_groq at
      :23) through core.llm_json, the path the docstring itself names.
  (b) On finish_reason == "length", retry ONCE with a doubled budget before giving
      up. A person does not accept half a sentence; they ask again.
  (c) If it still fails: the record must carry urgency "UNKNOWN" (not LOW),
      truncated: true, and the error string — and the 'error' key must SURVIVE the
      rebuild at :1035-1052. summary must be empty with a stated reason, never
      ctx[:200]; republishing the input as the output is the defect itself.
  (d) The three readers must not treat UNKNOWN as LOW. UNKNOWN means "not assessed"
      and must be visible — count it, print it, and make it reachable by a human.
      Do not silently promote it to HIGH either.
ACCEPTANCE — a fixture, not an intent: feed a deliberately truncated payload; assert
the produced record has urgency=="UNKNOWN", truncated is true, error is present and
non-empty, summary is not the input, and that a reader building critical_axes
reports the UNKNOWN count separately from the LOW count. Prove news/news_latest.json
is byte-identical after the fixture run.

3.2 THE GEMINI BUDGET
core/groq_backend.py:91-93 GEMINI_BUDGET_FLOOR = 1500. Measured in Item 4(d): a
complete internet_agent answer is ~1711-1764 chars (~430-440 output tokens); in the
14 failures the thinking consumed essentially the whole 1500. Raise the FLOOR default
to 4000 — under half the 8192 CAP, with room after the worst thinking observed.
Change the default IN CODE, not in .env: a threshold that lives only in an untracked
environment file is invisible to git and to every future reader. Put the measured
distribution (77 / 171 / 174 / 182 / 191 / 193 / 239 / 256 / 258 / 271 / 293 / 519 /
1348 / 1382 chars, median 247.5) in the commit body as the evidence.
Also: core/groq_backend.py:412-421 reads only candidates[0] and finishReason and
discards usageMetadata. Record thoughtsTokenCount and candidatesTokenCount into
memory/llm_provenance.jsonl so the next person MEASURES this split instead of
inferring it from reply size, as Item 4 had to.

3.3 CEREBRAS WAS DECLARED DEAD FOR THE WRONG REASON
core/groq_backend.py:109-112 DECLARED_DEAD says "reasoning tokens consume max_tokens".
The logs say 402 Payment Required (cycle_2026-08-22_145127.log:179-180 and two more),
and the module's own header at :87 records that Cerebras never truncated once —
440 calls, median 1208 chars, the best of the four backends.
  (a) Correct the string to the true cause, citing the log line and date. Do not
      delete the entry yet.
  (b) Then test one hypothesis with ONE http call: the 402 may be scoped to the
      model, not the account. The code names two model ids (:60) — gpt-oss-120b in
      use, zai-glm-4.7 alternative. Try a small model from the same account. If any
      model returns 200, the door is open and DECLARED_DEAD comes out with the
      working model id recorded. If every model returns 402, leave the entry and
      write "account-scoped, verified <date>" beside it — that closes it for good.
  (c) memory/llm_provenance.jsonl has no error field across 3425 records — it logs
      only successes, which is why the 402s are invisible in it. Add an outcome
      field so a failure is recorded, not merely absent.

3.4 CONNECT THE TWO UNRESOLVED METRICS   (the K1 move: 100 -> 114 of 173)
Add to core/global_indicators.py two world fetches via the existing _wb_world():
ER.LND.PTLD.ZS and SE.PRM.CMPT.ZS. Add wb_ER.LND.PTLD.ZS and wb_SE.PRM.CMPT.ZS to
the put() list at goal_score_calculator.py:136-150 so they reach last_obs and the
mapping at :199 resolves. Four lines. Do not touch config/target_config.json.
ACCEPTANCE — assert on the produced file: measured_weight == 114.0,
unmeasured_weight == 0, unmeasured_axes == [], coverage_of_measurable == 1.0, and
both PLANETARY_POTENTIAL_REVIEW and EDUCATION_CULTURE_REVIEW non-null. Print the
composite before and after; expected 0.6284 -> 0.6391. If it differs, REPORT the
difference — never adjust anything to match the expectation.

3.5 THE SIX correct_use TEXTS
config/axis_source_map.json instructs, on all six wrong-row entries, "If the panel
has a World row, row_key='World' makes it global." None of the six csvType=filtered
payloads has a World row; following that text raises CsvRowNotFound. Replace each
with the verified instruction from the Part 0 report, except
owid_plastic_waste_per_capita whose full CSV has zero World rows — mark that one
per-country-only. Change no extraction logic.

3.6 G_LEARN ATTRIBUTION
config/cycle_phases.json G_LEARN.produces: move memory/axis_history.json to B_SENSE,
memory/development_journal.json to F_SELF, memory/runtime_experiences.json to
E_PROPOSE. Leave feedback_log.json and goal_score_history.json.
ACCEPTANCE: the next G_LEARN report names at most one missing artifact, and it is
runtime_experiences.json — the only real failure.

3.7 last_sealed IS NOT A SEAL
fast_cycle_runner.py:294 publishes max(LAST_CYCLE_ID, LAST_ATTEMPT) as "last_sealed".
Keep the max — correct for the boot guard — but rename the published key to
"last_seen", and add "last_sealed" reading LAST_CYCLE_ID alone, or null.

3.8 SCALE TAGS
Add "score_scale": "0-1" to output/cortex_scores_latest.json and "0-100" to
memory/axis_history.json, in the shape already used at memory/trend_tracker.py:281,300.
Additive only. Migrate nothing. Do not touch experiments/prophecy/prophecy.py:195.

3.9 THE PANEL THAT NAMES ITS OWN FLAG
cockpit/server.py:1025 (why_off) and :1059 (empty_why) are hard-coded sentences
asserting reaction.enabled is false. Derive both from rx.enabled(). Drop or condition
cockpit/templates/cockpit.html:1212. Fix the stale comment at :1009.
ACCEPTANCE: with both flags true, no response body and no rendered line contains the
word "false" about reaction.enabled.

WHEN DONE: write acceptance numbers and each commit sha into this file, set
STATUS: DONE, and continue.


### 3.1 REPORT — 2026-08-28, commit 19e3909

SUITE on the exact committed tree:
  30 failed, 3232 passed, 6 skipped, 5 deselected, 1 xfailed, 17 warnings in
  1139.19s (0:18:59)
DIFF against the baseline of 29 (computed as the ITEM 2 run's 37 minus the
flag-driven failures), by sorted set comparison:
  new failures vs baseline:  test/test_glass.py::test_the_selftest_passes
  newly passing vs baseline: none
That one is NOT from 3.1, proved three ways rather than asserted:
  1. cockpit/glass.py imports __future__, cockpit, collections, core, pathlib,
     psutil, sys, typing — zero overlap with the four files 3.1 touched (AST).
  2. Reproduced directly: core.receptors.read_firewall_drops() returns
     available=False, "PermissionError: [Errno 13] Permission denied:
     C:/Windows/System32/LogFiles/Firewall/pfirewall.log". An unelevated shell
     cannot read that file; glass._selftest's "panel 2 read the firewall log"
     check fails on it. Environment, not code.
  3. The same test failed in the pre-change ITEM 2 run.
PUSH RULE condition 1 fails (list not byte-identical to 29). NOT PUSHED.
+19 tests passed vs the ITEM 2 run: the 12 new ones here plus 7 reaction/
perplexity ones that pass again now the flags are false.

WHAT CHANGED
  agents/internet/internet_agent.py
    :986  _groq(...) + hand-rolled 'done thinking.'/</think> stripping +
          _parse_llm_json  ->  call_llm_json(prompt, max_tokens=400,
          expect=dict, label=axis). Routes through call_groq_meta so
          finish_reason=="length" is authoritative rather than guessed, and
          retries ONCE at double budget. Stripping is already inside
          core.llm_json.strip_reasoning, so the duplicate went. (a) and (b).
    :1006 the failure record: urgency='UNKNOWN' (never LOW), sentiment=
          'UNKNOWN', truncated=<bool>, error=str(e), summary='' with a
          summary_why naming which failure it was. ctx[:200] is GONE. (c)
    :1069 rebuild carries truncated / error / summary_why, and the urgency
          default moved from 'LOW' to 'UNKNOWN'. (c)
    :1114 run() counts `unknown` apart from LOW, publishes 'unknown_axes' in
          news/news_latest.json, prints "NOT ASSESSED (n)". (d)
  agents/core/cortex_core_agent.py  — NOT ASSESSED block in the brain's news
    context, with "absence of an alert here is absence of an answer".
  core/cortex_orchestrator.py       — reads unknown_axes, prints beside
    critical/high.
  memory/semantic_memory.py         — UNKNOWN still not stored (nothing to
    store) but counted and named on stdout, so the gap is visible where the
    memory is built.
  test/test_internet_truncation.py  — NEW, 12 tests, all green.

ACCEPTANCE, all asserted by the fixture, all passing:
  urgency == "UNKNOWN"                     test_a_truncated_answer_is_unknown_not_low
  truncated is True                        test_a_truncated_answer_is_marked_truncated
  error present, non-empty, names backend  test_a_truncated_answer_carries_a_non_empty_error
  summary is NOT the input                 test_the_summary_is_not_the_input
  marker survives the rebuild              test_the_marker_survives_the_result_rebuild
  UNKNOWN counted apart from LOW           test_run_publishes_unknown_axes_separately
  readers surface it, never promote        test_core_agent_surfaces_unknown,
                                           test_semantic_memory_does_not_remember_unknown_but_names_it,
                                           test_orchestrator_prints_unknown
  news/news_latest.json byte-identical     test_the_real_news_file_was_not_touched
    (sha256 06831ab1964eb340..., 172243 bytes, unchanged across every run)

NOT DONE, on purpose, recorded under HOLDING: the high_axes/high_urgency_axes
key mismatch, and the global-synthesis call at :1151.

## ITEM 4 — WHY THE CLOUD TIER IS ABANDONED
STATUS: DONE 2026-08-28 — a)-e), g), h), i) complete; f) PARTIAL (see below)
GATE: READONLY
OUTSTANDING: f) only. Its cadence numbers are measured and recorded, but the
question it asks - quota or our own burst rate - cannot be settled from this repo:
the one limit on record (Gemini 1500/day, groq_backend.py:13) is 2600x above the
observed 0.40 attempts/min, and NO limit is recorded for Groq or OpenRouter, the
two that actually rate-limited. Closing it needs the 429 response bodies captured,
which is the same gap as 3.3(c).

SUMMARY (five lines)
1. The Cerebras disable string is wrong: it blames reasoning-token accounting,
   but the logs show 402 Payment Required. The token problem was already fixed.
2. Cerebras served 440 calls 15-18 Aug with the best median reply of any backend;
   it died on billing, not on tokens. No parameter or model change fixes a 402.
3. Gemini's budget is 1500 (floor), the caller asks 400x3; thoughts eat it before
   the answer starts. 14 of 19 answers truncated, median 247 chars.
4. finish_reason is discarded by call_groq() at groq_backend.py:758, so the
   consumer never learns the answer was cut.
5. A truncated answer lands in news_latest.json as urgency LOW with the raw input
   as its summary and no error marker — a false all-clear on 14 axes.
GATE: READONLY
COMPASS: not K1. This is the quality of every reasoning step — 10 of 22 steps in
cycle 2026-08-28T08:05:00 answered by a 3B local model instead of a cloud model.

From memory/cycle_logs/cycle_2026-08-28_080500.log: 48 calls fell to local_3b.
Groq 9/10 rate-limited (cooldown to hit #7); OpenRouter 8/8 rate-limited (hit #8);
Cerebras DISABLED 22 times by our own config; Gemini 19 OK of 22 but 14 of those
carry finish_reason=length.

Answer, reading code and logs only:
 a) Where is the Cerebras disable decided? Give file:line and the exact condition.
    Is it a hard-coded flag, a config key, or a runtime check? Quote it.
 b) What exactly breaks when Cerebras is used — which parameter is set, which model
    id, and does the API distinguish reasoning tokens from completion tokens
    (max_tokens vs max_completion_tokens)? Answer from the code and from any
    recorded error in memory/llm_provenance.jsonl, not from assumption.
 c) State whether a FREE fix exists: a Cerebras model without reasoning tokens, or
    a parameter change. If no free fix exists, say so plainly — that closes the
    question instead of leaving it open since 13 July.
 d) Where is the Gemini max_tokens set? file:line. What value? What would it need
    to be so that finish_reason=length stops on a typical axis-review answer?
    Measure it: find the token counts of the 14 truncated answers in
    memory/llm_provenance.jsonl and report the distribution.
 e) Is a truncated Gemini answer counted as a success anywhere that matters —
    does it reach a snapshot, an axis level, or a phase debrief as if complete?
    Trace one of the 14 to whatever it produced.

Report into this file. Change nothing.

### ANSWERS — 2026-08-28, read-only run

Note on the item's counts: the live cycle kept running while this was written.
Re-tallied from the same log at 12:46 local — 56 local_3b (not 48), Gemini 22
attempts / 19 OK of which 14 finish_reason=length, Cerebras skipped 22 times,
Groq 9 rate-limits of 10 attempts, OpenRouter 8 of 8. Shape unchanged.

**a) THE CEREBRAS DISABLE.** core/groq_backend.py:109-112, a module-level dict
literal — a HARD-CODED FLAG, not a config key and not a runtime check:
    DECLARED_DEAD = {
        "cerebras": "DISABLED: reasoning tokens consume max_tokens; "
                    "no budget for a paid tier",
    }
Consulted at core/groq_backend.py:655-657 inside `_cloud_chain()`:
    if key in DECLARED_DEAD:
        print(f"  [LLM] {label} -- {DECLARED_DEAD[key]}")
        continue
Added by commit 7cb0b17, 2026-08-23. To undo: delete the entry, nothing else.

**b) WHAT ACTUALLY BREAKS — the disable string names the wrong cause.**
Code: `_call_cerebras` (core/groq_backend.py:292-350) sends model `gpt-oss-120b`
(:60), `"max_completion_tokens": budget` (:314) and `reasoning_effort` = "low"
(:96). The API does NOT separate the two: :313-315 records that
`max_completion_tokens` is the documented name, `max_tokens` a legacy alias for
the same field, and reasoning tokens count inside it. That is why
_effective_budget (:270) exists: floor 1500, x3, cap 8192.
Logs contradict the disable string. memory/llm_provenance.jsonl holds 440
successful Cerebras calls, 2026-08-15 to 2026-08-18, reply_chars median 1208,
max 7646 — the best median of the four backends. The file's own header
(:87) says "Cerebras (който има пода) не отряза нито веднъж". The token problem
was already solved by the floor.
The real failure is in the cycle logs, three of them, 22-23 Aug:
  [POLICY] cerebras DISABLED for this run — permanent: 402 Client Error:
  Payment Required for url: https://api.cerebras.ai/v1/chat/completions
handled by core/backend_policy.py:11-26 (402 = permanent, never a cooldown).
NOT VERIFIED: no cycle log older than 2026-08-22 survives, so the first 402
cannot be dated from this repo.

**c) IS THERE A FREE FIX? NO — not by parameter and not by model.**
402 is an account state, not a request property. No value of
max_completion_tokens, reasoning_effort or CEREBRAS_BUDGET_* changes it, and the
alternative model named at :60 (`zai-glm-4.7`) sits behind the same account gate.
CEREBRAS_API_KEY is present (52 chars) so this is not a missing-key failure.
Whether Cerebras still offers a free tier that would serve this key cannot be
answered from code and logs — NOT VERIFIED, and it needs one HTTP call to settle.
That question is now closed as far as this repo can close it: the provider is
skipped for money, not for tokens, and the string at :110 should say so.

**d) GEMINI BUDGET.** Set at core/groq_backend.py:400-401 inside `_call_gemini`:
    budget = _reasoning_budget(max_tokens, GEMINI_BUDGET_MULT,
                               GEMINI_BUDGET_FLOOR, GEMINI_BUDGET_CAP)
    payload = {..., "generationConfig": {"maxOutputTokens": budget}}
with MULT=3, FLOOR=1500, CAP=8192 (:91-93), all `os.environ.get` overridable,
none set in this environment. The truncating caller is
agents/internet/internet_agent.py:987 `_groq(prompt, max_tokens=400)`, so
budget = min(8192, max(1500, 1200)) = **1500**.
MEASUREMENT. memory/llm_provenance.jsonl records NO token counts and NO
finish_reason — fields are ts, backend, model, prompt_head, prompt_sha1,
reply_chars. The 14 truncations were matched to provenance records by
prompt_head ("CORTEX++ AGI analyzing axis: <AXIS>") and timestamp; all 19 Gemini
calls in the 08:05-08:45 window resolve, 14 truncated + 5 clean.
  truncated reply_chars, sorted: 77 171 174 182 191 193 239 256 258 271 293 519
                                 1348 1382     median 247.5   mean 383
  clean   reply_chars: 1103 1706 1711 1764 3733
A clean internet_agent answer is ~1711-1764 chars ~= 430-440 output tokens, so
thoughts consumed ~1060-1070 of the 1500 in those. In the 14 failures thoughts
took essentially all of it. A floor of ~3000 would leave a full answer's room
after the worst observed thinking; 4000 with margin. EXACT thoughts counts are
NOT VERIFIED — core/groq_backend.py never reads Gemini's usageMetadata
(grep for thoughtsTokenCount/candidatesTokenCount/thinkingConfig: zero hits), so
the split is inferred from reply size, not measured.
Cheapest change: set GEMINI_BUDGET_FLOOR=3000 in the environment — no code edit.

**e) YES — A TRUNCATED ANSWER IS COUNTED AS A SUCCESS, AND IT VOTES.**
finish_reason dies at the wrapper: core/groq_backend.py:758
`content, _meta = call_groq_meta(...); return content` — `call_groq()` discards
meta, so agents/internet/internet_agent.py:23 (`call_groq as _groq`) can never
see it. It is printed to the console at :670 and thrown away.
Traced PLANETARY_POTENTIAL_REVIEW, 08:20:50, 1382 chars, log line 297:
  1. truncated JSON -> `_parse_llm_json(raw)` raises
  2. internet_agent.py:993-994 except-clause returns
     {'summary': ctx[:200], 'sentiment':'NEUTRAL', 'urgency':'LOW',
      'key_developments': [], 'error': str(e)}
  3. :1035-1052 rebuilds a fixed-key result dict that does NOT copy `error`
  4. :1136 writes news/news_latest.json
Verified on disk (news/news_latest.json, written 08:42:52Z):
  urgency "LOW", sentiment "NEUTRAL",
  summary "[GitHub]\n- satellite-image-deep-learning/techniques star=10243..."
  key_developments [], open_source_momentum "", scientific_frontier "",
  and NO `error` key and no truncation marker of any kind.
The "summary" is the raw source listing that was fed IN, published as the
analysis that came OUT. Today: 18 of 24 axes are LOW, and 14 of those 18 are
these truncations.
It votes. Consumers gate on urgency in ("HIGH","CRITICAL"):
  agents/core/cortex_core_agent.py:32-36 (priority list),
  core/cortex_orchestrator.py:268 (critical_axes),
  memory/semantic_memory.py:103 (nothing is remembered below HIGH).
So a truncated answer is not a false alarm — it is a false ALL-CLEAR, and it
removed 14 axes from the priority list, from the orchestrator's critical set and
from semantic memory in this cycle, with nothing on disk saying why.

### ANSWERS f) PARTIAL — 2026-08-28, measured before the interrupt

Not a finished answer to f). What was established, with the method, so the next
run does not repeat it:

CADENCE. The cycle log carries no per-line timestamps, so attempt times were
reconstructed from memory/llm_provenance.jsonl (successes only) and step spans
from memory/step_contract_latest.json. Cycle 2026-08-28T08:05:00 ran
08:05:00 -> 09:46:18 UTC = 101.3 minutes.
  Cloud ATTEMPTS in the whole cycle, counted from the log by provider-attempt
  line: Groq 10, OpenRouter 8, Gemini 22, Cerebras 0 (22 DECLARED_DEAD skips,
  27 cooldown skips). TOTAL 40 attempts in 101.3 min = 0.40/min.
  They occur in only three steps: llm_self_review_axes (4), cortexstrategist (3),
  internet_intelligence (33). Every other degraded call never reached the cloud
  at all — daily_analysis alone logged 29 degraded calls and ZERO cloud attempts.
  Cloud successes per clock-minute: max 2 (at 08:15, 08:30, 08:32), median 1,
  17 active minutes out of 101. Inter-arrival min 7.0s / p50 62.3s / max 136.7s.
  Longest burst 11 calls over 08:26:05 -> 08:36:26 (gaps <= 90s).
  Self-imposed pace: core/groq_backend.py:179 _SLEEP_SECS = 10.0 before every
  call (:258, :319, :370, :405); cooldown 60/120/180 capped (:142-143, :218).

LIMITS RECORDED IN THIS REPO. Exactly one, and it is a code comment:
  core/groq_backend.py:13   "Gemini (gemini-3.5-flash) — reasoning, 1500 req/day"
Nothing else. Searched core/, config/, docs/, .env.example for rate-limit,
req/min, req/day, rpm, rpd, quota, free tier. .env.example (7 lines of keys, no
limits). config/dead_sources.json holds DEAD/NEEDS_AUTH entries for data sources
only — no LLM provider appears in it. There is no recorded limit for Groq,
OpenRouter or Cerebras anywhere in the repo.
  The only other quota-shaped number found: core/global_indicators.py:767
  "GitHub Search ... 10 req/min" — a data source, not an LLM backend.

WHAT IS NOT YET ANSWERED. Whether 0.40 attempts/min can trip a free tier cannot
be settled from this repo: the one limit recorded (1500/day) is 2600x above the
observed rate, and no limit is recorded for the two providers that actually
rate-limited (Groq 9 of 10 attempts, OpenRouter 8 of 8). So the repo cannot say
whether the wall is a quota or our own burst rate; it can only say the repo does
not know. Settling it needs either the providers' documented limits recorded in
the repo, or the 429 response bodies captured — and memory/llm_provenance.jsonl
records no failures at all (Item 4 c), which is the same gap as 3.3(c).


### ANSWERS g) h) i) — 2026-08-28, read-only, gate CLOSED so ITEM 3 could not run

**g) IS THERE A DEFER PATH? NO. The mechanism exists and nothing calls it.**
When the cloud tier is abandoned at its slice, the question is answered by
local_3b and that is the end of it. core/groq_backend.py:766-775:
    if res.outcome == _budget.OK and res.value is not None:
        result, meta = res.value
        if res.tier != _budget.CLOUD:
            _note_degraded(f"answered by {res.tier} ... after the cloud tier was
                             abandoned at its slice of B={res.budget_sec:.0f}s")
            print(f"[LLM] cloud abandoned -> {res.tier} ... OK (DEGRADED)")
        return result, meta
_note_degraded (:424-437) forwards to core.step_contract.note_degraded_on_current
and is explicitly fail-open — it marks the STEP as degraded. It does not record
the question, the prompt, or any intent to ask again. When no tier answers at all
(:779-795) the step is told, AllBackendsFailedError is raised, and again nothing
about the question survives.
  A defer mechanism DOES exist and is complete: core/cycle_profile.py:201-247 —
  defer() with dedup on `key` and a deferred_count, deferred(), take_deferred()
  that drains atomically so two cycles cannot both run the same work, and
  deferred_path() -> memory/deferred_batch.json.
  AST call-site scan for defer() and take_deferred() across the repo: 11 sites,
  ALL of them in test/test_cycle_profile.py. Zero production callers.
  memory/deferred_batch.json does not exist on disk.
  It is read in two places and only read: cockpit/datasources.py:124 lists it as a
  source, cockpit/server.py:617 surfaces it in a panel. So the cockpit has a panel
  for a backlog that nothing can ever fill.
WHERE A DEFERRED QUESTION WOULD HAVE TO BE WRITTEN: memory/deferred_batch.json,
via core/cycle_profile.defer({...}), called from core/groq_backend.py:769 on the
non-CLOUD branch — the exact line that today only prints DEGRADED.

**h) WHY 3B AND NOT 8B — a window, and a GPU that cannot hold the big model.**
Where each is chosen:
  core/groq_backend.py:754  _small = _mw.small_model()   -> qwen2.5:3b
  core/groq_backend.py:755  _big   = _mw.big_model()     -> qwen3:8b
  core/groq_backend.py:759  local_3b=_local_tier(_small)          ALWAYS offered
  core/groq_backend.py:764  local_8b=_local_tier(_big) if _mw.is_open() else None
  core/model_window.py:104-118 config(); :121-126 small_model()/big_model();
  :193-195 is_open()
  core/phase_debrief.py:90-94 — the debrief uses brain.think(fast=True), which
  "picks the SMALLEST installed model, which is how a 3B ended up judging phases";
  changed to qwen3:8b through core/self_experiment.ALLOWED_KNOBS. That is why the
  debriefs say _model: local:qwen3:8b while the abandonment path says qwen2.5:3b.
  They are two different choosers, not one setting read twice.
config/model_window.json: enabled true, small_model qwen2.5:3b, big_model qwen3:8b,
window_opens_at_step brain_reconsider (12.75), window_closes_after_step
cycle_report (25.6).
  internet_intelligence is step index 4 — OUTSIDE the window by design, and the
  config's own README names it: "internet_intelligence ... sits OUTSIDE the window
  and will be served 3b. That is the intended trade: it is a fetch step, and a
  fetch step that degrades is cheaper than a cycle that dies."
ollama list on this machine, live:
  qwen2.5:3b   1.93 GB
  qwen3:8b     5.23 GB
  qwen2.5:7b   4.68 GB
memory/body_scan_latest.json (written 12:18:06 local, inside the 12:15 cycle):
  ram_total 13.86 GB, ram_free 7.70 GB, ram_percent 44.4
  GPU NVIDIA GTX 1650: vram_total 4096 MB, vram_free 1385 MB, vram_used 2566 MB,
  utilisation 80%, 61 C
COULD THE FALL BE TO 8B? Inside the window, yes — the code already offers it.
Outside it, no, and two independent things decide that:
  1. the window (a human-owned config, core/model_window.py:764 guard), and
  2. the GPU. qwen3:8b is 5.23 GB against 4096 MB of VRAM with 1385 MB free. The
     config README records the measurement: 8b "does not fit even alone (3.32GB of
     5.75GB resident; the other 42% runs on the CPU)", and the two models never
     coexist — each call to one fully evicts the other, 7-14s warm, minutes cold.
So for the 56 falls in the 08:05 cycle the answer is: they were in fetch steps
outside the window, and even had the window been open the machine cannot hold 8b
without paying an eviction and running 42% of it on the CPU.

**i) HOW MANY DOORS — four cloud, two local, one dead, none missing a key.**
core/groq_backend.py:686-691, the chain in order:
  | backend    | file:line          | model                                | key | state |
  | Groq       | :268 _call_groq    | openai/gpt-oss-120b                  | yes | ENABLED |
  | Cerebras   | :292 _call_cerebras| gpt-oss-120b                         | yes | DISABLED — DECLARED_DEAD (:109-112) |
  | OpenRouter | :353 _call_openrouter| nvidia/nemotron-3-super-120b-a12b:free| yes | ENABLED |
  | Gemini     | :387 _call_gemini  | gemini-3.5-flash                     | yes | ENABLED |
Local, not part of the chain but reachable as explicit last resort
(core/groq_backend.py:759/764 via _call_local_as at :440):
  | local 3b   | qwen2.5:3b | always offered |
  | local 8b   | qwen3:8b   | only while model_window.is_open() |
Ollama also holds qwen2.5:7b (4.68 GB), which NOTHING in the chain can reach:
config/model_window.json names only small_model and big_model, so the 7b is
installed and unreachable.
KEYS: all four names present in .env (GROQ_API_KEY, CEREBRAS_API_KEY,
OPENROUTER_API_KEY, GEMINI_API_KEY) — checked by presence only, never by value.
.env.example declares exactly these four plus NASA_API_KEY.
config/dead_sources.json holds ucdp_api and eia_api only — both DATA sources. No
LLM provider appears in it; the LLM kill switch is DECLARED_DEAD in code, a
different mechanism in a different place.
So: 4 cloud doors, 1 of them shut by us for a reason Item 4(b) showed is
misstated; 2 local doors, 1 of them gated by a window that is closed for most of
the cycle; 1 installed model no door leads to.


### THE FOUR ARMS — run 2026-08-28T14:49:36Z, first time ever

core/interval_head.compare() was built at line 746 and had never been run. Four
arms, one protocol: same split, same seed, same loss, same epochs, same baseline.

| arm                             | heldout | coverage | width | verdict |
|---------------------------------|--------:|---------:|------:|---------|
| A  names only, real embedding   | 16.6994 |     19%  |  30s  | LOSES to flat |
| B  names only, hashed control   | 21.9643 |     18%  |  19s  | LOSES to flat |
| C  names + row features, real   | 16.5312 |     13%  |  13s  | LOSES to flat |
| D  names + row features, hash   | 22.5665 |      8%  |   6s  | LOSES to flat |
| FLAT BASELINE                   |  9.5350 |          |       |  -      |

Lower heldout Winkler is better. THREE THINGS, and only the first is the one
that was asked about:

1. THE LANGUAGE DIMENSIONS DO CARRY SOMETHING. The hypothesis was that if the
   hashed arm matched the real one, the 2048 embedding dims carry nothing and
   the head is memorising which step is which. They do NOT match: real beats
   hashed by 5.26 (A vs B) and by 6.04 (C vs D), consistently, on both feature
   sets. So the embedding is not decoration and the attention strip is reading
   something real.
2. NO ARM BEATS THE FLAT BASELINE, and it is not close: the best learned arm is
   16.53 against 9.54 for one constant band. Whatever the embedding carries, the
   head is not turning it into better intervals than "always predict the same
   width". Recorded as it came out, not tuned until it wins - that would be
   Goodhart on our own instrument.
3. THE CALIBRATION IS THE WORST NUMBER ON THE TABLE and nobody asked about it.
   alpha=0.2 means the intervals are meant to contain the truth 80% of the time.
   They contain it 19%, 18%, 13%, 8%. The head is not merely losing, it is
   confidently wrong - and the arm that looks best on Winkler (C, 16.53) has the
   second-worst coverage. Width falls 30s -> 6s across the table while coverage
   falls with it: the arms are winning on width by being narrow, not by being
   right.

row-feature coverage: prev durations on 96% of rows, RAM-at-start on 66%,
23 cycles detected.

WHAT THIS MEANS FOR K4 (ITEM 7.3): the interval head predicts step_seconds and
does it worse than a constant. Pointing it at an axis value is still the right
move, but this table says the architecture is not yet earning its keep on the
target it already has - worth knowing before anyone reads meaning into a learned
attention map.

## ITEM 5 — THE VOICE THAT NEVER SPOKE
STATUS: TODO
GATE: NOCYCLE
Cycle 2026-08-28T08:05:00 sealed with "attempts": 0 in memory/extra_calls_log.jsonl,
while config/reactions.json had enabled: true in BOTH blocks from 07:34:36Z until the
human reverted it at 13:53Z. memory/reactions.jsonl is unchanged since 2026-08-23 and
its only row came from _once() with fixture lines. The voice has never spoken from real
receptor lines.

5.1 IS IT WIRED AT ALL?  (read-only, do this first)
By AST, not grep: list every caller of core/reaction.py's at_phase_boundary(), ask(),
react(), and of the perplexity equivalent. State whether fast_cycle_runner.py or any
module it imports calls any of them during a cycle. If nothing does, say so plainly —
the flag has then never been connected to anything, and the panel has been reporting a
switch with no wire.

5.2 IF IT IS WIRED: WHY DID IT NOT FIRE?
Enumerate every early return in the path — RAM floor, VRAM floor, Ollama queue busy,
wait timeout, circuit breaker, cooldown, config re-read. For each: file:line, the exact
condition, and whether it writes ANY record. Then check the recorded body state for that
cycle (memory/body_scan_latest.json, memory/somatic_history.jsonl between 08:05 and
09:46) against each floor and say which gate would have been closed.

5.3 SILENCE MUST BE WRITTEN DOWN   [required either way]
Every non-attempt outcome writes a row to memory/extra_calls_log.jsonl with kind "skip"
and a reason: not_enabled | ram_floor | vram_floor | queue_busy | wait_timeout |
breaker_open | error — including the measured value that closed the gate (e.g.
ram_available_mb), so a human can check the decision and not just read the verdict.
The seal then carries attempts, skips, and skips_by_reason.
Same defect as a 402 being invisible in a success-only memory/llm_provenance.jsonl
(Item 4b) and as a refusal leaving a stale heartbeat indistinguishable from death.
Absence of record is being read as absence of event, in three independent places.
ACCEPTANCE: run one phase boundary with the flags OFF (they are off on disk now) and
assert a row appears with reason "not_enabled". A ledger that stays empty when nothing
happened IS the bug.

5.4 STOP THERE
Do not tune the guardrails, do not lower the floors, do not touch config/reactions.json
(protected-path denylist, human-written). Report 5.1 and 5.2 and stop. The floors are a
human decision and need 5.2's numbers first.

## ITEM 6 — TWO LIES ON THE EXPRESSION PANEL
STATUS: TODO
GATE: READONLY
Both observed live on the EXPRESSION tab for cycle 2026-08-28T08:05:00.

6.1 AN ANOMALY THAT DID NOT CROSS ANYTHING
Verbatim from the panel:
  ANOMALY sensor_id=net_recv_mb name=disk_read_mb threshold=1000000
          unit=binary_megabytes crossed=438.8
sensor_id and name are two different sensors, and 438.8 is reported as having crossed a
threshold of 1000000. Find the producer — file:line — and report where sensor_id and
name are each taken from and why they can disagree; what "crossed" is compared against;
and whether threshold and crossed are in the same unit. Then count the rows in
memory/expression_stream.jsonl and how many have name != sensor_id. Do not fix. The
count says whether this is one bad row or a class.

6.2 A PHASE DEBRIEF IN CYRILLIC
memory/phase_debriefs/2026-08-28T08_05_00*/B_SENSE.json begins "Фаза B_SENSE приключи
с 7 артефакта". The language gate reported 100.0% live purity over 41 outputs on
2026-08-27, with phase_debrief 8/8.
Answer: which outputs does the gate actually inspect (file:line and the list), is
phase_debrief among them today, and what does "purity" test — the whole record or one
field? Then count Cyrillic phase_debriefs in this cycle and the previous three. If the
gate never looked at this field, say so; the 100% was then true about something
narrower than we read it to be.

## ITEM 7 — MAKE THE COMPASS PRODUCE A NUMBER
STATUS: TODO
GATE: NOCYCLE
The four needles that define this project's success have produced no number since
21 August. Verified on disk 2026-08-28: memory/measurement_honesty_latest.json is
stamped 2026-08-20T02:19:29 and has no measured_weight key at all;
memory/source_lifecycle_ledger.jsonl holds 435 rows whose ts values all fall inside
21:16:04-21:20:26 on 2026-08-20, with event taking only the values clean (109) and
refusal (326); memory/interval_head_runs.jsonl holds 5 runs, all on 2026-08-21;
prediction_resolutions.jsonl does not exist. Each step below is a SEPARATE commit.

7.1 K1 MUST BE WRITTEN EVERY CYCLE
Decision, already made, do not re-open it: K1 = measured_weight / 173.0 across the
25 axes in memory/measurement_honesty_latest.json, and "measured" means the axis's
primary metric resolved from an EXTERNAL observation in that cycle — not a model
assertion, not an llm_level score.
  (a) Find the writer of memory/measurement_honesty_latest.json — file:line — and
      report which step calls it and why it last ran on 20 August. If nothing calls
      it from the cycle, say so.
  (b) Wire it to run every cycle, at a step AFTER the scorer, and add two explicit
      top-level keys: measured_weight and k1 (= measured_weight / total_weight).
      Do not remove or rename any existing key; this file's honest_composite and
      todays_number blocks stay exactly as they are.
  (c) The file must record, per axis, WHY an axis counted as measured: the source id
      and the observation it resolved from. An axis that cannot name its external
      observation is not measured, whatever its score says.
ACCEPTANCE: run it once; assert the file's ts is today, total_weight is 173.0, the
new measured_weight and k1 keys exist, and every axis counted as measured names a
source id. Report the resulting k1 value. Do not tune anything to reach a nicer number.

7.2 K3 — ONE FIELD
Add an integer field supporting_source_count to each claim in
memory/knowledge_base.json, populated with the number of distinct sources that
support that claim. K3 is then the count of claims where that field is >= 2.
Report the file's current shape first — how a claim is represented and whether the
supporting sources are recoverable from what is already stored. If they are NOT
recoverable for existing claims, write the field as null for those and populate it
only going forward. A back-filled guess is worse than an honest null.
ACCEPTANCE: the field exists on every claim; K3 is computable in one pass; no
existing key changed.

7.3 K4 — POINT THE INTERVAL HEAD AT THE WORLD
memory/interval_head_curve.json shows target "step_seconds": the interval head
predicts the duration of the system's own steps. The architecture is right —
frozen embedding, two 256-wide ReLU layers, centre and log-halfwidth output, alpha
0.2, and an honest beats_flat_baseline_heldout field. The target is wrong.
  (a) Report, from code, exactly what would have to change for target to be an axis
      value rather than step_seconds: which function supplies rows, what a row
      contains, and what the label would be.
  (b) Do NOT retrain anything in this item. Instead create the missing record:
      memory/prediction_resolutions.jsonl, appended whenever an axis prediction is
      made and again when it is later resolved against an observed value. One line
      per event with: ts, axis, domain, predicted_centre, predicted_low,
      predicted_high, alpha, and on resolution observed_value and resolved_ts.
      Without this file K4 has nothing to score, and it does not exist today.
ACCEPTANCE: a fixture writes one prediction row and one resolution row and reads
them back; the real file is byte-identical after the fixture run.

## ITEM 8 — THE THIRTIETH FAILURE
STATUS: DONE 2026-08-28 — suite back to a byte-identical 29
GATE: NOCYCLE
Your 3.1 run reported 30 failed against a baseline of 29, and you proved the extra
one is test/test_glass.py::test_the_selftest_passes, failing on
PermissionError: [Errno 13] C:/Windows/System32/LogFiles/Firewall/pfirewall.log
because an unelevated shell cannot read that file. You were right not to adjust the
baseline to match the result.
The fix is not to run the suite as administrator. A test that can only pass with
elevated privileges is a test that silently does not run — the same defect as a
guardrail SKIP that writes nothing.
Change glass._selftest so that an unreadable firewall log is reported as SKIPPED
with the reason and the errno, not as a failed check, and so that the skip is
COUNTED and printed rather than swallowed. The test then asserts the panel reported
a definite state — read, or skipped-with-reason — and fails only if it reported
neither.
ACCEPTANCE: suite returns to 29 on an unelevated shell, the FAILED list is
byte-identical to the baseline, and the glass selftest output names the skip and its
reason. Record the new 29-line FAILED list in this file so the baseline stops being
folklore.


### ITEM 8 REPORT — 2026-08-28, commit <SHA8>

SUITE, guarded run, ITEM 10.1 readings taken and printed:
  BEFORE at=14:11:38Z  lock=False   AFTER at=14:30:43Z  lock=False
  VERDICT: VALID — no cycle lock at either reading
  29 failed, 3248 passed, 6 skipped, 5 deselected, 1 xfailed, 17 warnings
  in 1088.89s (0:18:08)
Diff against the baseline of 29, by sorted set comparison: new = NONE,
gone = NONE. BYTE-IDENTICAL. The 30th failure is gone and the baseline is
no longer folklore — it is the list below.
NOTE: this one VALID run also covered the 3.2 changes, which were in the
tree at the time. Both commits are gated on it; neither needed its own run.

THE BASELINE. 29 lines, recorded so nobody has to trust a number again:
```
test/test_cerebras_budget.py::test_gemini_still_sends_plain_max_output_tokens
test/test_cerebras_budget.py::test_other_openai_backends_still_send_plain_max_tokens[_call_groq-GROQ_API_URL]
test/test_ci_contract.py::test_no_hardcoded_drive_letters_in_code
test/test_corrections_27.py::test_the_annotation_comes_after_what_it_annotates
test/test_corrections_27.py::test_the_five_test_rows_are_still_there
test/test_cycle_reaper.py::test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk
test/test_cycle_seals_its_own_completion.py::test_sealing_a_cycle_here_leaves_the_real_ledgers_alone
test/test_declared_step_inputs.py::test_an_undeclared_step_still_refuses
test/test_declared_step_inputs.py::test_the_scanner_prefers_the_written_declaration
test/test_heartbeat_coverage.py::test_each_beat_reports_the_step_it_is_actually_in
test/test_level_reconciler.py::test_climate_global_risk_is_corrected_to_high_under_the_ruling
test/test_level_reconciler.py::test_social_relations_is_corrected_to_low_on_live_data
test/test_level_reconciler.py::test_the_correction_row_carries_the_translation
test/test_metta_parallel.py::test_an_empty_hyperon_result_does_not_erase_the_reference
test/test_metta_parallel.py::test_hyperon_and_the_reference_agree_on_live_data
test/test_metta_parallel.py::test_r3_fires_on_the_live_climate_contradiction
test/test_metta_parallel.py::test_the_disagreement_states_both_readings
test/test_metta_parallel.py::test_the_live_climate_fact_is_what_we_think_it_is
test/test_needs_auth.py::test_the_live_registry_shows_ucdp_active_and_eia_waiting
test/test_needs_auth.py::test_the_waiting_sources_reach_the_cycle_report
test/test_notary_gate.py::test_execute_patches_never_reaches_full_trust
test/test_notary_gate.py::test_the_phantom_is_still_the_thing_holding_the_gate
test/test_phase_evidence_swap.py::test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test
test/test_phase_evidence_swap.py::test_the_replay_script_reports_the_same_number
test/test_phase_resume.py::test_the_cli_refuses_without_claiming_the_cycle_lock
test/test_script_suite.py::test_script_style_suite[experiments/dreams/test_dream.py]
test/test_script_suite.py::test_script_style_suite[test/test_goal_score_package.py]
test/test_script_suite.py::test_script_style_suite[test/test_needs_approvals.py]
test/test_script_suite.py::test_script_style_suite[test/test_origin_honesty.py]
```

WHAT CHANGED
  core/receptors.py:712-720  read_firewall_drops carries errno beside why.
    'Permission denied' and 'no such file' are different facts about the
    world and a reader must not have to parse English to tell them apart.
  cockpit/glass.py  _selftest gained a third state. skip(name, reason)
    beside check(name, cond). Panel 2 is judged on reporting a DEFINITE
    state: read the log -> pass; could not and says why -> SKIP, named,
    with the errno; neither -> FAIL. Skips are counted, listed, and the
    summary reads 'every check that ran passed (1 skipped)', never
    'every check passed'.
  test/test_glass.py  three tests, including the negative control
    test_an_unexplained_failure_is_still_a_failure: a panel returning
    available=False with no reason must still exit 1. Without it the skip
    would have made the selftest pass on a panel that said nothing.

WHY NOT JUST RUN AS ADMINISTRATOR: a test that only passes with a
privilege is a test that silently does not run — the same defect as a
guardrail that skips and writes nothing down (ITEM 5.3).

## ITEM 10 — THE SUITE HAS NO GATE WHILE IT RUNS
STATUS: TODO
GATE: NOCYCLE
NOTE ON NUMBERING: there is no ITEM 9 in this file. Items run 1-8 and then 10. The
gap is deliberate — nothing was deleted and nothing was renumbered.

On 2026-08-28 a suite started at 12:10:51 and ran to 12:30:16. A cycle started at
12:15:20, four minutes in, pid 30144, cycle_id 2026-08-28T12:15:20. Three tests moved
as a result — two failed on live writes, one PASSED only because a cycle lock existed.
GATE:NOCYCLE is checked once before the run and never again, so any run longer than the
gap to the next scheduled cycle can be silently contaminated. A test that flips green
because live state changed is as invalid as one that flips red.

10.1 The suite runner records the lock and heartbeat state at start and at end, and
declares the run INVALID — not failed — if a cycle.lock appeared, disappeared, or
changed cycle_id between the two readings. An invalid run must never be compared to
the baseline and must never gate a commit.
10.2 The invalidation is written down, with both readings and the cycle_id, so an
invalid run is distinguishable from a clean one after the fact. Absence of a record is
not evidence the run was clean.
10.3 Report, from config/scheduler.json, the cycle schedule, and state plainly how long
a suite run can be before it is at risk. If the suite is longer than the shortest gap,
say so — then a clean run is a matter of luck and the queue needs to know it.
ACCEPTANCE: simulate by writing a fake lock mid-run in a fixture; the runner reports
INVALID with both readings, and the fixture proves memory/cycle.lock is byte-identical
afterwards.

EVIDENCE FROM THE RUN THAT PROMPTED THIS (2026-08-28). It never sat in HOLDING:
Claude said it would record it there and then wrote it straight into this item, so
there was nothing to promote. Noted because a false provenance line is the same
defect this queue keeps finding.
  suite window   12:10:51 -> 12:30:16 UTC (1164.95s)
  cycle          started 12:15:20, pid 30144, still alive at 12:32:35 on step
                 global_indicators with an 8-second-old heartbeat
  live writes    25 rows appended to memory/llm_provenance.jsonl inside the window
                 (10 Groq, 12 local:qwen2.5:3b, 2 local:qwen3:8b, 1 Gemini), carrying
                 real agent prompts - "You are an analyst for the CORTEX++ AGI system"
  moved tests    test_gemini_budget_and_usage.py::test_the_real_provenance_ledger_was_
                 not_touched   FAILED (its guard fired correctly, on the cycle's writes)
                 test_flow_score.py::test_the_live_contract_produces_a_plausible_score
                 FAILED (reads contract state the cycle was rewriting)
                 test_phase_resume.py::test_the_cli_refuses_without_claiming_the_cycle_
                 lock   PASSED, having failed in every prior run - it passes only when
                 a lock exists, so the cycle made it green
  The 31-failure result was discarded, not compared to the baseline and not used to
  gate a commit.

## HOLDING
- news/ IS NOT IN conftest._GUARDED_TREES. test/conftest.py:44 guards ("memory",
  "config") only, so the strong in-process guard _no_live_writes does not cover
  news/news_latest.json — the file 3.1 is about. Widening the tuple would extend the
  guard to every test in the repo at once, which is not a detail of 3.1 or 3.2.
  Found while fixing the 3.2 guard; left for a human to weigh.
- A test written during 3.2 briefly made a REAL cloud call while trying to prove it
  made no local write: the module runtime went 3s -> 15s and that was the only signal.
  Nothing in the suite reports per-module wall-clock drift, so a test that starts
  reaching the network is invisible until someone happens to look at a timer.
- REJECTED ALTERNATIVE, not a pending decision (3.2, 2026-08-28). Moving GROQ_ and
  CEREBRAS_BUDGET_FLOOR to 4000 alongside Gemini would restore the old equality
  invariant in one line. It was considered and rejected, by Emil and by the evidence:
  Groq and Cerebras both serve openai/gpt-oss-120b and neither truncated (Groq zero
  times in the 2026-08-28T08:05 cycle; Cerebras zero across 440 calls 15-18 Aug),
  while Gemini is gemini-3.5-flash and cut 14 of 19. Raising all three would change
  two backends on evidence gathered about neither — the failure this queue exists to
  stop. The JUSTIFIED_FLOORS table in test/test_reasoning_budget.py is the invariant
  now: a floor and its evidence change together or not at all. Reopen only with a
  measurement of Groq or Cerebras truncating, not to tidy the asymmetry.
- test/test_cerebras_budget.py holds two assertions that predate the reasoning-budget
  transform and have been red since 20 Aug: test_gemini_still_sends_plain_max_output_
  tokens expects maxOutputTokens == the raw caller budget, and the _call_groq case of
  test_other_openai_backends_still_send_plain_max_tokens expects the same for Groq.
  Both are in the baseline of 29. 3.2 changes the number they see, not their outcome.
  They assert the behaviour the transform deliberately removed and should be retired
  or rewritten; not folded into 3.2.
- core/cortex_orchestrator.py:268 reads internet.get("high_axes", []) while the writer
  at agents/internet/internet_agent.py:1133 emits high_urgency_axes. The key has never
  matched; the orchestrator's high list has been empty every cycle. Found during 3.1,
  deliberately left out of it.
- agents/internet/internet_agent.py:1151 — the global-synthesis call still uses _groq +
  _parse_llm_json, the same shape as the 3.1 defect. It fails loudly rather than
  silently, so it was not folded into 3.1.
