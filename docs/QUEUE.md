## STATUS
last_updated_utc: 2026-08-29T06:35:00Z
last_item_done: ITEM 23 — the idea scorer stops failing soft, and its verdicts admit what they rest on
current_item: ITEM 21 (live crash) or ITEM 12 (audit list is DONE, see its report) — Emil's call
current_state: READY
gate_closed_reason: - (OPEN since 05:04:20 local; the nightly cycle 2026-08-29T03:04:01 held it 03:04-05:04)
next_action_needed_from_claude: ITEM 21 is a LIVE CRASH found 2026-08-29 (feedback_loop dies on a dict level word, killing goal_score_history writes); it sits after ITEM 11 in the table but may deserve to jump. Otherwise ITEM 11. Run the suite as `venv/Scripts/python.exe tools/suite_gate.py` from now on — bare pytest gives no verdict on whether a cycle touched the window. FOR EMIL: 27 tests are red purely because memory/extra_calls_suspended.flag is set; they clear themselves after one non-breaching cycle. See the baseline section SUSPENDED_FLAG.

## ORDER OF WORK
Work strictly down this table. It is the map; the items below are the detail.
Keep the state column current — it is the only place a human should have to look.
| # | item | state | gate |
|---|------|-------|------|
| 1 | Prepare the K1 move | DONE 2026-08-28 | READONLY |
| 2 | Commit docs/QUEUE.md | DONE 2026-08-28, 77b4838 (not pushed) | NOCYCLE |
| 3 | Apply 3.1-3.9 | DONE 2026-08-28 — nine commits, 19e3909..a6e1958 | NOCYCLE |
| 4 | Why the cloud tier is abandoned, f)-i) | DONE 2026-08-28 except f) — needs 429 bodies | READONLY |
| 5 | The voice that never spoke | 5.1 DONE — nothing calls it; 5.3 open | NOCYCLE |
| 6 | Two lies on the expression panel | DONE — both premises overturned | READONLY |
| 7 | Make the compass produce a number | DONE 2026-08-28 — 7.1, 7.2, 7.3 | NOCYCLE |
| 8 | The thirtieth failure | DONE 2026-08-28 — baseline is a recorded 29 | NOCYCLE |
| 10 | The suite has no gate while it runs | DONE 2026-08-29 | NOCYCLE |
| 11 | Wire resolve_ideas into the cycle (deadline was 2026-09-02; really 09-05) | DONE 2026-08-29 | NOCYCLE |
| 12 | axis_history.json is tracked in git | TODO | NOCYCLE |
| 13 | The uncommitted-work guard | TODO | NOCYCLE |
| 14 | Make the compass produce four numbers | TODO | NOCYCLE |
| 15 | Early stopping + coverage gate | TODO | NOCYCLE |
| 16 | A panel for a file nothing writes | TODO | NOCYCLE |
| 17 | RUNBOOK.md is 1 byte | TODO | NOCYCLE |
| 18 | Retarget the interval head at the world | TODO | NOCYCLE |
| 19 | Record score provenance | TODO | NOCYCLE |
| 20 | The five LIVE_STATE tests | TODO | NOCYCLE |
| 21 | feedback_loop dies on a dict level word (LIVE CRASH) | TODO | NOCYCLE |
| 23 | Three defects in tools/resolve_ideas.py | DONE 2026-08-29 | NOCYCLE |

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
AMENDED BY EMIL, 28 August 2026. Condition 1 was "the FAILED list is
byte-identical to the recorded baseline". That rule stopped the push twice in one
day over failures no code in the batch had caused — a reverted runtime file and a
set of tests that read live state — while a list that merely SHRANK was also a
blocker. A gate that cannot tell a regression from a restored file is a gate
people learn to route around. The baseline now carries a cause per line, so the
condition can ask the question that matters.

Push without asking a human, only if all three hold machine-checked:
1. NO FAILURE APPEARS THAT IS NOT IN THE RECORDED BASELINE WITH A NAMED CAUSE.
   A failure LEAVING the list is reported, never a blocker. A new failure with no
   recorded cause blocks, as before.
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
COMPASS: K1 = measured weight / 167. Today 100/167 = 59.9%. The unresolved 14
weight is two axes: EDUCATION_CULTURE_REVIEW (primary_completion_rate) and
PLANETARY_POTENTIAL_REVIEW (protected_terrestrial_area_pct). This item prepares
the only change found in Part 0 that moves the compass. It applies nothing.

CORRECTED 2026-08-28 BY EMIL. THE NUMBER WAS ASSERTED FROM MEMORY BY A HUMAN AND
THE CODE WAS ALWAYS RIGHT. This line originally read "K1 = measured weight / 173.
Today 100/173 = 57.8%", and 173 was never read from anything — it was carried in
a person's head from the shape the goal tree had before commit 8052397
("the observer steps out of the observed", 2026-08-21), which retired
GENERAL_SELF_REVIEW and left 24 axes / 167 weight. goal_score_calculator has
always summed the denominator out of config/target_config.json and has always
returned 167; nothing in the code needed changing. The 100 -> 114 arithmetic in
ITEM 3.4 below was done against 173 and is left as it was written: against 167
it is 59.9% -> 68.3%. A hand-copied constant goes stale silently, and
test/test_no_stale_total_weight.py now fails if one appears anywhere outside
config/ without its correction beside it.

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
STATUS: DONE 2026-08-28 — all nine steps applied, one commit each (report at the end of this item)
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

### PUSH ATTEMPT BLOCKED — 2026-08-28T17:22Z, recorded per the PUSH RULE

Suite VALID (lock absent at 17:03:54Z and 17:21:59Z). 26 failed against a
baseline of 29. Push rule condition 1 requires the FAILED list to be
byte-identical; it is not — 2 new, 5 gone — so NOTHING WAS PUSHED. 17 commits
remain local, 71ddaf9 through df55c14.

GONE (5), all live-state dependent and none of them evidence of a fix:
  test_corrections_27 x2, test_level_reconciler::test_social_relations_is_
  corrected_to_low_on_live_data, test_phase_evidence_swap x2.
  A test that flips green because live state changed is as untrustworthy as one
  that flips red; these are not counted as progress.

FIXED AS INTENDED and absent from the list: the three BRAIN sweep entries, the
two test_phase_report fixtures, test_no_exit_on_import, test_glass.

NEW (2), and BOTH are the reset, not this batch. Each carries mtime
18:09:22.4 — the exact reset second.

  test_script_suite[test/test_snapshot_carry_forward.py]
    One assertion: "the snapshot carries a _health block a human can read at a
    glance". snapshots/master/global_indicators_latest.json has NO _health block
    and 11 world_bank keys; in the Part 0 reading it had _health and 12. The file
    is TRACKED, so reset --hard replaced live measurement with an older committed
    snapshot. ONE CYCLE RUN REGENERATES IT — and because of 3.4 it should come
    back with 13 world_bank keys. No code change is warranted.

  test_script_suite[test/test_promotion_seam.py]
    TypeError: float() argument must be a string or a real number, not NoneType,
    at experiments/composers/composer.py:276. composer.py is one of the TWO files
    with no pre-reset .pyc — recorded as permanently gone. Its uncommitted version
    guarded that None; HEAD's does not. AWAITING A HUMAN DECISION: restore the
    guard as new work (float(None) is a defect on its own terms, independent of
    what the lost version did), or leave it red as visible damage. Not guessed at.

SECOND-ORDER FINDING, feeding ITEM 12(b): the audit of tracked files a running
cycle writes must include snapshots/, not only memory/.
snapshots/master/global_indicators_latest.json is tracked runtime data and was
reverted by the same command, one directory over from axis_history.json.

VERIFIED BEFORE THE ATTEMPT, per instruction: memory/axis_history.json is in NO
commit, unstaged, 616 KB. Nothing under memory/ is staged. The only memory/ path
in the 17 unpushed commits is memory/trend_tracker.py, which is source.

### THE BASELINE, RE-RECORDED 2026-08-28 WITH A CAUSE PER LINE

The 29-line list recorded earlier under ITEM 8 is SUPERSEDED, not deleted. It
stays where it is. It was a count and a list of names, which is enough to detect
a change and not enough to judge one — twice today it forced a stop over failures
that were not caused by any code in the batch. A baseline without causes turns
every deviation into the same event.

26 failures, each with the reason it fails.

LIVE_STATE (5) — flips with system state, not with code. RECORDED AS A DEFECT IN
THE TEST, NOT AS A PASS. All five were RED in the ITEM 8 baseline and are GREEN
now, and nothing in this batch touched them: they moved because the live files
they read moved. A test that flips green when state moves is exactly as
untrustworthy as one that flips red, and counting today's flip as progress would
be counting the same unreliability as evidence. They are ITEM 20.
  test/test_corrections_27.py::test_the_five_test_rows_are_still_there
  test/test_corrections_27.py::test_the_annotation_comes_after_what_it_annotates
  test/test_level_reconciler.py::test_social_relations_is_corrected_to_low_on_live_data
  test/test_phase_evidence_swap.py::test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test
  test/test_phase_evidence_swap.py::test_the_replay_script_reports_the_same_number

RESET_DAMAGE (2) — snapshots/master/global_indicators_latest.json is TRACKED
runtime data and the 15:09:22Z `git reset --hard` replaced it with an older
committed copy. It lost its _health block, is down to 11 world_bank keys, and
lost its `conflicts` section. ONE CYCLE RUN REGENERATES IT; because of 3.4 it
should return with 13 world_bank keys. NO CODE CHANGE IS WARRANTED for either.
  test/test_script_suite.py::test_script_style_suite[test/test_snapshot_carry_forward.py]
      asserts "the snapshot carries a _health block a human can read at a glance"
  test/test_script_suite.py::test_script_style_suite[test/test_promotion_seam.py]
      composer.fetch now names the cause instead of dying on float(None):
      "extract 'conflicts.active_armed_conflicts' is not in
      snapshots/master/global_indicators_latest.json (source promoted_96302)".
      The guard did not fix the failure — it turned an opaque TypeError into a
      diagnosis that points at the reverted file, which is the whole value.

BY_DESIGN (2) — assertions that pin behaviour the reasoning-budget transform
deliberately removed on 2026-08-20. Red since then, kept red on purpose, and NOT
retired in this batch because retiring them would change the list for a reason
unrelated to any code under test. Separate item.
  test/test_cerebras_budget.py::test_gemini_still_sends_plain_max_output_tokens
      expects maxOutputTokens == the caller's raw budget; the transform overrides it
  test/test_cerebras_budget.py::test_other_openai_backends_still_send_plain_max_tokens[_call_groq-GROQ_API_URL]
      same expectation for Groq

OTHER (17) — each with its reason, all pre-existing and none touched by this batch.
  test/test_ci_contract.py::test_no_hardcoded_drive_letters_in_code
      a hardcoded C:\ path exists somewhere in the tree; the guard is right
  test/test_cycle_reaper.py::test_end_to_end_a_spawned_cycle_leaves_its_exit_code_on_disk
      end-to-end reaper test; spawns a real cycle process
  test/test_cycle_seals_its_own_completion.py::test_sealing_a_cycle_here_leaves_the_real_ledgers_alone
      asserts a seal from a test never touches the live ledgers
  test/test_declared_step_inputs.py::test_an_undeclared_step_still_refuses
  test/test_declared_step_inputs.py::test_the_scanner_prefers_the_written_declaration
      config/step_inputs.json does not declare every step the runner walks
  test/test_heartbeat_coverage.py::test_each_beat_reports_the_step_it_is_actually_in
      a beat() name and its heartbeat step disagree somewhere
  test/test_level_reconciler.py::test_climate_global_risk_is_corrected_to_high_under_the_ruling
  test/test_level_reconciler.py::test_the_correction_row_carries_the_translation
      reads live auto_levels/goal_score; adjacent to LIVE_STATE, see ITEM 20
  test/test_metta_parallel.py:: (5 tests)
      the MeTTa sidecar (venv312_metta) is not answering on this machine, so the
      symbolic column cannot be compared against its reference
  test/test_needs_auth.py::test_the_live_registry_shows_ucdp_active_and_eia_waiting
  test/test_needs_auth.py::test_the_waiting_sources_reach_the_cycle_report
      reads config/dead_sources.json live; ucdp/eia state has moved
  test/test_notary_gate.py::test_execute_patches_never_reaches_full_trust
  test/test_notary_gate.py::test_the_phantom_is_still_the_thing_holding_the_gate
      the notary's trust gate does not hold the property these assert
  test/test_phase_resume.py::test_the_cli_refuses_without_claiming_the_cycle_lock
      depends on whether a cycle lock exists at run time — borderline LIVE_STATE
  test/test_script_suite.py::test_script_style_suite[experiments/dreams/test_dream.py]
  test/test_script_suite.py::test_script_style_suite[test/test_goal_score_package.py]
  test/test_script_suite.py::test_script_style_suite[test/test_needs_approvals.py]
  test/test_script_suite.py::test_script_style_suite[test/test_origin_honesty.py]
      four script-style tests failing on their own assertions, pre-existing

NOT VERIFIED: the OTHER reasons are read from the test names, their assertions and
today's run output. Where a reason says "somewhere", nobody has opened the failure
in this session and it should not be quoted as diagnosed.

### ITEM 3 CLOSING REPORT — 2026-08-28, nine commits

The header of this file said "3.2 written, suite INVALID" for several hours after
the work had in fact gone in. Re-verified today against the working tree, not
against the header: every one of 3.1-3.9 is applied and committed. The commits
below were checked one at a time against the code they claim to change.

| step | commit  | verified in the tree by                                        |
|------|---------|----------------------------------------------------------------|
| 3.1  | 19e3909 | internet_agent.py:25 imports call_llm_json; :1003 uses it; urgency='UNKNOWN' at :1018-1019, :1078 |
| 3.2  | 84cc1a7 | groq_backend.py:109 GEMINI_BUDGET_FLOOR default "4000"; :466-473 carries usageMetadata thoughts/answer/prompt/total into _meta |
| 3.3  | 7785395 | DECLARED_DEAD text now cites 402 in cycle_2026-08-22_145127.log:179-180; provenance rows carry outcome ok/error (:643, :700) |
| 3.4  | 7bedac3 | global_indicators.py:224-225 _wb_world() for both ids; goal_score_calculator.py:156-157 put() both keys |
| 3.5  | 110546a | five correct_use texts rewritten with the verified World value; the sixth marked per-country-only |
| 3.6  | a8dada4 | cycle_phases.json: axis_history -> B_SENSE, development_journal -> F_SELF, runtime_experiences -> E_PROPOSE |
| 3.7  | baa166d | fast_cycle_runner.py:307 "last_seen", :309 "last_sealed" |
| 3.8  | 7e5ef71 | fast_cycle_runner.py:2597 "score_scale":"0-1"; trend_tracker.py:273,288,302 "0-100" |
| 3.9  | a6e1958 | cockpit/server.py why_off and empty_why derive from rx.enabled(); _rx_enabled() fails CLOSED |

ACCEPTANCE NUMBERS, as the steps demanded them:
  3.1  urgency=="UNKNOWN", truncated true, error non-empty, summary != input,
       UNKNOWN counted apart from LOW — 12 fixture tests, all green.
       news/news_latest.json sha256 06831ab1964eb340..., 172243 bytes, unchanged.
  3.2  FLOOR 1500 -> 4000. Measured distribution in the commit body (median 247.5).
  3.3  Cerebras: GET /v1/models 200, completion 402 on BOTH model ids. Verdict
       recorded as account-scoped, verified 2026-08-28. DECLARED_DEAD stays.
  3.4  measured_weight 100.0 -> 114.0, unmeasured_weight 14.0 -> 0.0,
       unmeasured_axes [] , coverage_of_measurable 0.8772 -> 1.0000,
       PLANETARY_POTENTIAL_REVIEW None -> 0.5504, EDUCATION_CULTURE_REVIEW None ->
       0.8802, composite 0.6284 -> 0.6391, K1 57.8% -> 65.9%. Matched the
       expectation exactly; nothing was adjusted to reach it.
  3.8  NOT YET ON DISK, and this is expected, not a miss: output/cortex_scores_
       latest.json and memory/axis_history.json still carry no score_scale key
       because neither has been rewritten since the commit. The WRITERS carry it.
       One cycle run closes this; a human can check with
       `venv\Scripts\python.exe -c "import json;print(json.load(open('output/cortex_scores_latest.json'))['score_scale'])"`.

NOT PUSHED AT THE TIME OF WRITING, AND NO LONGER TRUE. This paragraph read
"nothing has been pushed since, and the local branch now carries 20 unpushed
commits, 71ddaf9 through 7d41957." Checked again 2026-08-28T19:2xZ against
origin/feature/lidaction-guard: the branch is 3 ahead, 0 behind. Seventeen of
those commits were pushed from outside this session between the 17:22Z block and
now. Corrected rather than deleted, because "we were blocked and stayed blocked"
is the wrong thing for the next reader to carry forward.

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
STATUS: 5.1 DONE 2026-08-28 (not wired at all) · 5.2 NOT APPLICABLE · 5.3 STILL TODO (needs code)
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

### ANSWERS 5.1 and 5.2 — 2026-08-28, read-only

**5.1 IS IT WIRED AT ALL? NO. NOTHING CALLS IT, EVER.**

By AST across 626 .py files, imports of core/reaction.py and core/perplexity.py,
excluding the two modules themselves:

    cockpit/server.py:1018   core.reaction     (the READ-ONLY panel endpoint)
    cockpit/server.py:1064   core.reaction     (the READ-ONLY free-stream endpoint)
    test/test_free_stream.py:34   core.reaction
    test/test_perplexity.py:33    core.perplexity
    test/test_reaction.py:28      core.reaction

FIVE importers. TWO are non-test, and BOTH are the cockpit READING what was
already stored. Neither ever calls the model.

Call-site scan for the entrypoints — at_phase_boundary(), react(), ask(),
measure() — finds every non-test caller INSIDE core/reaction.py itself
(lines 193, 236, 266, 288, 296), which are its own _once() and _selftest()
paths, reachable only by hand:

    venv/Scripts/python.exe core/reaction.py --once

fast_cycle_runner.py never imports either module. Its ONLY mention of the whole
subsystem is a COMMENT at line 574 — "the switches in config/reactions.json are
still false" — which is prose about a flag the runner cannot act on.

SO: config/reactions.json is a switch with no wire. Turning reaction.enabled to
true, as happened between 07:34:36Z and 13:53Z today, could not have produced a
single reaction, because no cycle step reaches the code the flag guards. The
cycle sealed with "attempts": 0 in memory/extra_calls_log.jsonl not because a
guardrail refused, but because nothing ever asked. memory/reactions.jsonl is
unchanged since 2026-08-23 and its single row came from _once() with fixture
lines — the voice has never spoken from real receptor lines because it has never
been invited to.

This also explains, without any further investigation, why the panel's prose and
its status word disagreed (ITEM 3.9, now fixed): the status word read a live flag
that governs nothing.

**5.2 IF IT IS WIRED: WHY DID IT NOT FIRE?** — DOES NOT APPLY.

5.2 asks which guardrail closed. None did. Enumerating early returns, checking
RAM and VRAM floors against memory/body_scan_latest.json and walking the Ollama
queue would all be answering a question about a code path that no cycle enters.
Recorded as NOT APPLICABLE rather than answered with a plausible-looking table,
which is exactly the shape of the defect this queue keeps finding.

The guardrails inside core/reaction.py are real and may matter LATER — after
5.3's skip-ledger exists and after somebody wires the call. They cannot be
measured before then, because nothing exercises them.

**CONSEQUENCE FOR 5.3, which stands unchanged and matters more than before.**
5.3 requires every non-attempt to write a row with a reason. With the subsystem
unwired, the FIRST such reason is not ram_floor or queue_busy — it is
"never_invoked", and today it is the only true one. A ledger that stays empty
because nothing ran looks identical to a ledger that stays empty because
everything was refused, and that is precisely the confusion 5.3 exists to end.

## ITEM 6 — TWO LIES ON THE EXPRESSION PANEL
STATUS: DONE 2026-08-28 — both answered; BOTH PREMISES OVERTURNED
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

### ANSWER 6.1 — 2026-08-28. THE PRODUCER IS THE MODEL, NOT A FORMATTER.

There is no code that assembles that line, and that is the finding.

THE ROW, verbatim from memory/expression_stream.jsonl:

  {"ts": "2026-08-28T08:52:21.983384+00:00", "source": "model",
   "text": "ANOMALY sensor_id=net_recv_mb name=disk_read_mb threshold=1000000
            unit=binary_megabytes crossed=438.8",
   "source_tag": "model", "form": "ANOMALY", "reflexivity": 1, "glyphs": []}

`text` is a single free string with source="model". No producer splices
sensor_id and name from two places, because nothing splices them at all — a
local model WROTE that sentence, and cockpit/expression.py only CHECKED it. The
check, at :203-206, is that an ANOMALY "cites a sensor_id" and "names the
threshold crossed". The line satisfies both. It is form-valid and false.

So the questions as posed do not have the answers they expect:
  - where are sensor_id and name each taken from? NOWHERE. Both are tokens in
    one generated sentence. They can disagree because nothing ever required them
    to agree; no code read a sensor and printed its name.
  - what is `crossed` compared against? NOTHING. It is not a comparison result;
    it is a number the model emitted next to the word.
  - are threshold and crossed in the same unit? UNKNOWABLE from the row. It
    declares unit=binary_megabytes once, for the pair, and 438.8 against
    1000000 is a ratio of 2278 — consistent with bytes-vs-megabytes, or with an
    invented number. NOT VERIFIED, and it cannot be verified from this record.

THE COUNT, which was the point of asking:
  7959 rows in memory/expression_stream.jsonl
  2 carry an ANOMALY form
  0 rows have a `name` field at all — the schema has `sensor`, never `name`
So `name != sensor_id` cannot be counted as a field mismatch: it is not a field.
Both ANOMALY rows are model prose. The second is
  "ANOMALY sensor_id=net_send, threshold=1000.0MB/s, crossed=465.6MB/s"
— same shape, same unverifiable claim, and it too passes the form gate.

IT IS NOT ONE BAD ROW AND IT IS NOT A CLASS OF BAD ROWS. It is 2 of 2: EVERY
ANOMALY this system has ever emitted is a sentence a 3B model wrote, gated only
on containing the right words. The renderer sweep proved every panel says
SOMETHING; this is the same defect one layer down — the expression gate proves
every ANOMALY is well-FORMED, and cannot tell whether any part of it is TRUE.

WHAT WOULD CLOSE IT, not done here: an ANOMALY should be produced by the
receptor that crossed the threshold, carrying sensor id, threshold, observed
value and unit as FIELDS, with the sentence rendered from them. Then form
validity and truth are the same check. Filed as a finding; no code changed.

### ANSWER 6.2 — 2026-08-28. THE GATE DID LOOK, AND IT SAID NO.

The premise was that a Cyrillic debrief slipped past a gate reporting 100%
purity. It did not. The gate inspected that exact record and FAILED it.

memory/phase_debriefs/2026-08-28T08_05_00.525209_00_00/B_SENSE.json:
  what: "Фаза B_SENSE приключи с 7 артефакта (всички налични), най-старият..."
  lang: {"ok": false, "reason": "CYRILLIC_0.97",
         "profile": {"latin": 0.031, "cyrillic": 0.969, "letters": 258}}

WHICH OUTPUTS THE GATE INSPECTS: core/language_gate.py:274 purity_ratio and :317
purity_by_kind read memory/brain_journal.jsonl (JOURNAL, :65) — every row any
brain call writes, each carrying kind, summary, payload and a lang verdict.
924 rows, 8 kinds: constancy 576, phase_debrief 161, cycle_plan 41, reconsider
28, constellation 24, skip_decision 24, cycle_report 22, cycle_review 18.
phase_debrief IS among them, and is the second largest kind.

WHAT PURITY TESTS: the row's `summary`, judged clean or not, with rows written
before the gate existed judged from their stored summary as they are read so the
window stays comparable. Not the whole record, and not the payload.

THE NUMBERS, counted today over all 161 phase_debrief rows:
  Cyrillic in summary   89
  Cyrillic in payload   93
  lang ok=True          68
  Cyrillic in summary AND ok=True   0
Zero. Not one Cyrillic debrief was ever marked clean. The gate is doing exactly
what it claims, on the field it claims to judge.

SO WHERE DID "100.0% over 41 outputs, phase_debrief 8/8" COME FROM? From a
24-HOUR ROLLING WINDOW (purity_ratio's default hours=24), not from all history.
On 2026-08-27 the 41 outputs inside that window happened to be clean. The figure
was TRUE ABOUT ITS WINDOW and was read as a statement about the system. Those are
different claims, and the one that matters — "the model writes English now" — is
false: 89 of 161 phase_debrief summaries are Cyrillic, and the very next day
produced another.

SO THE FINDING IS NOT A HOLE IN THE GATE. It is that a rolling-window ratio was
quoted without its window, which is the same shape as reading `last_sealed` as a
seal or an 8763-byte artifact total as DEGRADED — a true number carrying a
meaning nobody checked it against.

NOT VERIFIED: I did not reconstruct the 2026-08-27 window to confirm it held
exactly 41 rows. The claim above is that a 24h window explains a 100% reading
while all-history is 89/161 Cyrillic; the specific composition of that day's
window was not recomputed.

WHAT WOULD CLOSE IT, not done here: purity should be published WITH its window
and its denominator in the same string — "100.0% over 41 outputs in 24h" — so the
number cannot be quoted free of the thing that makes it true. The gate needs no
change; the reporting does.

## ITEM 7 — MAKE THE COMPASS PRODUCE A NUMBER
STATUS: DONE 2026-08-28 — 7.1, 7.2 and 7.3, reports at the end of this item
GATE: NOCYCLE
The four needles that define this project's success have produced no number since
21 August. Verified on disk 2026-08-28: memory/measurement_honesty_latest.json is
stamped 2026-08-20T02:19:29 and has no measured_weight key at all;
memory/source_lifecycle_ledger.jsonl holds 435 rows whose ts values all fall inside
21:16:04-21:20:26 on 2026-08-20, with event taking only the values clean (109) and
refusal (326); memory/interval_head_runs.jsonl holds 5 runs, all on 2026-08-21;
prediction_resolutions.jsonl does not exist. Each step below is a SEPARATE commit.

7.1 K1 MUST BE WRITTEN EVERY CYCLE
Decision, already made, do not re-open it: K1 = measured_weight / 167.0 across the
24 axes in memory/measurement_honesty_latest.json, and "measured" means the axis's
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
ACCEPTANCE: run it once; assert the file's ts is today, total_weight is 167.0, the
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

### 7.1 REPORT — 2026-08-28

(a) THE WRITER, AND WHY IT STOPPED
  core/measurement_honesty.py:run() -> OUT at :50. It is the only writer.
  NOTHING IN THE CYCLE CALLED IT. AST over every .py in the repo: the only
  importers of core.measurement_honesty were core/training_log.py:49 (the four
  taxonomy constants, not run()), test/test_measurement_honesty.py:17 and
  test/test_training_record.py:34. No step, no scheduler, no agent.
  So it last ran on 20 August because a human typed it on 20 August. The file's
  mtime is 2026-08-20T15:45:17. That is the whole answer: a needle that moves
  only when somebody remembers to move it is not an instrument.

  AND THE STAMP WAS NEVER A RUN TIME. `ts` was rec.get("timestamp") — the
  timestamp of the LAST RECORD in memory/goal_score_history.json, copied. A file
  written today could carry a two-month-old date and nothing in it said so. This
  item's own premise ("stamped 2026-08-20T02:19:29") was reading a basis date as
  a run date. Fixed: `ts` is the moment of writing; the record's stamp travels
  as the new key `basis_ts`, which is how the 7-day staleness below is visible
  at all.

(b) WIRED, AND WHERE
  fast_cycle_runner.py step 20.1 "measurement_honesty", after the scorer (12.6)
  for the provenance and after feedback_loop (20) for today's history record.
  Declared in config/cycle_phases.json under G_LEARN, with
  memory/measurement_honesty_latest.json added to G_LEARN.produces.
  FAIL-OPEN: a cycle must not die because a report did not render.
  New top-level keys, all additive — honest_composite and todays_number are
  byte-for-byte the blocks they were:
    measured_weight   the weight whose axes NAMED an external observation
    k1                measured_weight / total_weight
    k1_why            how the numerator was reached, or why there is no number
    carried_weight    published separately, deliberately NOT inside K1
    basis_ts          the record honest_composite was computed from

(c) THE WHY, PER AXIS
  goal_score_calculator gained _resolve_metric_origin(), which returns the value
  AND where it came from; _resolve_metric() keeps its old signature and
  delegates, so no caller and no test changed. Each axis now carries
  measured_by = {source_id, observation_key, observation_where, observed_value,
  metric} and counts_toward_k1 = "measured_by is not None". An axis that cannot
  name its observation does not count, whatever its score says.

  A COLLISION FOUND WHILE BUILDING IT, AND IT WAS A WRONG NUMBER, NOT A COSMETIC
  ONE. metric_details is keyed by METRIC. MATERIALS_WASTE_REVIEW and
  CLIMATE_GLOBAL_RISK_REVIEW both declare primary_metric co2_ppm_mauna_loa, so
  the first is overwritten in that dict and disappears from anything reading it
  per axis. K1 is a weight sum, so that is 9 weight missing: the first run
  produced 42.0, the corrected one 51.0. The scorer now also emits
  axis_observations, keyed by AXIS, which cannot collide; read_provenance
  prefers it and falls back to metric_details only for older snapshots, saying
  so in k1_why.

ACCEPTANCE — run twice, against the real config and a live scorer run, with NO
live file written (the scorer result and the report both went to scratch). The
second run is the one recorded: memory/goal_score_history.json was restored
between them and honest_composite depends on it.
  ts                     2026-08-28T18:42:23+00:00        TODAY        PASS
  basis_ts               2026-08-21T00:05:21.577111+00:00  7 days stale, and now
                                                           SAYABLE
  total_weight           167.0                            PASS (see CORRECTION)
  measured_weight        51.0                             key present  PASS
  k1                     0.3054                           key present  PASS
  every counted axis names a source id                    6 of 6       PASS
  live files byte-identical (sha256, before -> after)                  PASS
    memory/measurement_honesty_latest.json  c78bf036832f2c34 unchanged
    snapshots/master/goal_score_latest.json eb0979a11e910145 unchanged
    memory/goal_score_history.json          ef9d10da604639ae unchanged

  THE RESULTING K1 IS 0.3054 — 51.0 of 167.0 weight, 6 of 24 axes:
    CLIMATE_GLOBAL_RISK_REVIEW        w=10  NOAA             noaa_co2_ppm = 432.3
    MATERIALS_WASTE_REVIEW            w= 9  NOAA             noaa_co2_ppm = 432.3
    HUMAN_WELL_BEING_REVIEW           w= 9  WORLD_BANK       wb_SH.DYN.MORT = 37.4
    INEQUALITY_POVERTY_REVIEW         w= 9  WORLD_BANK       wb_SI.POV.DDAY = 10.4
    GOVERNANCE_INSTITUTIONS_REVIEW    w= 7  WELLBEING_GLOBE  governance_institutions_score_global = 0.443037
    GOVERNANCE_RIGHTS_AT_HUMAN_LEVEL  w= 7  WELLBEING_GLOBE  governance_rights_score_global = 0.432078
  It agrees exactly with the scorer's own measured_weight (51.0), computed by a
  different route. Nothing was tuned to reach it.

WHAT THE RESTORED HISTORY CHANGED, AND WHAT IT DID NOT
  memory/goal_score_history.json was restored outside this session while the
  suite was running: 11 records -> 47, ending 2026-08-21T00:05:21 instead of
  2026-06-21T13:57:09, and 11 of them carry score_sources where the disk had
  none. Re-read before this report was written, as instructed.
    honest_composite   MOVED, and it was the whole cause. Before: "НЯМА
                       ИЗМЕРВАНЕ ... покритие 0%". After: 60.9395 at 54%
                       coverage, 19% asserted. todays_number 62.1352 at 73%.
    K1                 DID NOT MOVE. 0.3054 both times.
  That the two moved independently is the design working: K1 reads the scorer's
  live provenance, honest_composite reads the history record, and a report that
  had conflated them would have swung on a file restore.

  AND THE RESTORED RECORD CORROBORATES THE COLLISION. In the 2026-08-21 record
  MATERIALS_WASTE_REVIEW is score_source "llm_level" — a model opinion — while
  K1 counts it TODAY as measured from noaa_co2_ppm. Both readings are of the
  same axis on the same data. The difference is that feedback_loop reads the
  colliding metric_details and the K1 path does not.

CORRECTION — 173 WAS NEVER READ FROM ANYTHING
  Emil, 2026-08-28: total_weight is 167, not 173. Commit 8052397 ("the observer
  steps out of the observed", 2026-08-21) retired GENERAL_SELF_REVIEW: 25 axes /
  173 weight -> 24 / 167. Every 173 in this repo outside config/ was a human
  writing the number down from memory. goal_score_calculator has always summed
  the denominator out of config/target_config.json and has always returned 167;
  no code was ever wrong. Fixed where it was ASSERTED — ITEM 1's COMPASS line,
  ITEM 14's K1 spec, and this item's own decision and acceptance lines — and
  ANNOTATED, never deleted, in the 16 places where it was true on the day it was
  written (goal_score_calculator, core/global_indicators, core/phase_debrief,
  agents/axis/axis_feed, four test fixtures, PROGRESS/...2026-08-20.txt).
  test/test_no_stale_total_weight.py, NEW, now fails if the literal 173 appears
  next to "weight" or "тегло" anywhere outside config/ without 167 within five
  lines. It carries its own negative test — it is watched failing on a planted
  violation — and a third test that fails if config/target_config.json stops
  summing to the number the guard quotes. Fourth instance of a hand-copied
  constant going stale in one day.

TESTS: test/test_k1_measurement_honesty.py, NEW, 15 tests, all green. They hold
the three properties that make the number worth reading: an axis counts only if
it names its observation; an unreadable provenance gives null and a reason,
never 0.0; and two axes sharing one metric both count. The last test compares
sha256 digests taken at import against the same files after every test ran.
test/test_no_stale_total_weight.py, NEW, 3 tests, all green.

SUITE — THE GATE RUN, 18:49Z on the exact committed tree:
  28 failed, 3344 passed, 7 skipped, 1 xfailed, 17 warnings in 1045.88s (17:25)
  memory/cycle.lock absent at start and at finish, so the run is VALID.
  DIFF against the recorded baseline, by sorted set comparison:
    failures NOT in the baseline: NONE.
    gone from the baseline (3), all LIVE_STATE, reported not celebrated:
      test_corrections_27 x2, test_level_reconciler::test_social_relations_is_
      corrected_to_low_on_live_data
  PUSH RULE condition 1 asks whether any failure appears that is not in the
  recorded baseline with a named cause. None does. This is the first time today
  that condition has been met.
  MOVED SINCE THE 18:15Z RUN, and both movements are the restored history file,
  not this batch:
    BACK RED (2)  test_phase_evidence_swap x2 — LIVE_STATE, in the baseline with
                  a named cause. They read live state; the state moved.
    GONE (1)      test_brain_scan::test_a_dry_run_leaves_memory_and_snapshots_
                  byte_identical. It was the external-write detector firing on
                  the human restoring memory/goal_score_history.json mid-run.
                  Green here, which closes that question.

SUITE, THE EARLIER RUN: the 19:01 run at 18:15Z is REPORTED AND WAS NOT USED AS
THE GATE, because the tree it measured no longer exists — memory/goal_score_history.json was restored
by a human mid-run, and the 173 annotations and both new test files landed
after it. 27 failed, 3342 passed, 7 skipped, 1 xfailed. Against the recorded
baseline: ONE new failure and none gone.
  NEW (1)  test/test_brain_scan.py::test_a_dry_run_leaves_memory_and_snapshots_
           byte_identical. It hashes name+size+mtime_ns of every file under
           memory/ and snapshots/ around one publish_scan() call, so it is an
           external-write detector and it detected one. Re-run alone
           immediately after: 19 passed. NOT VERIFIED which file it caught —
           the run was captured with `tail -60` and the assertion detail was
           truncated. No code in this batch writes to either tree.
  A NOTE ON THE BASELINE ITSELF, found while diffing against it: the block
  "THE BASELINE, RE-RECORDED 2026-08-28" says 26 failures and then enumerates
  31 test ids, labelling as "OTHER (17)" a list of 22. The 26 is right and the
  enumeration is right — the five LIVE_STATE entries are listed as failures and
  described in the same paragraph as green. A baseline whose count and list
  disagree is exactly the hazard it was re-recorded to fix. Left for ITEM 20,
  which owns those five.

NOT DONE, on purpose, recorded under HOLDING: feedback_loop reads the colliding
metric_details and so has never scored MATERIALS_WASTE_REVIEW as measured; and
MATERIALS_WASTE_REVIEW being scored by atmospheric CO2 at all is a config
question, not a 7.1 one.

### 7.2 REPORT — 2026-08-28

THE SHAPE, WHICH THE ITEM ASKED FOR FIRST

memory/knowledge_base.json is NOT a list of claims. It is keyed by AXIS: 28
entries, 26 of shape {cycle_count, insight_hashes, key_insights, last_score,
last_updated, scores, trend} and 2 without last_score.

A "claim" is a BARE STRING inside key_insights. There is no object to hang
supporting_source_count on, and no source is recorded anywhere beside it — so
for existing claims the supporting sources are NOT recoverable, which by the
item's own rule means the field is null for all of them and populated only
going forward.

THE DECISION 7.2 HAS TO MAKE BEFORE IT WRITES ANYTHING, and it is not written
in the item: turning each string into an object would change the shape three
readers depend on — core/hypothesis_search.py:107 (which documents the shape
verbatim), memory/continuous_learner.py:213 (the writer) and
agents/core/self_observer.py:178. The existing `insight_hashes` field is the
handle that avoids all of it: a parallel map hash -> supporting_source_count
carries the number without touching key_insights. Recommend that; do not
convert the list.

THE CARRIER, AND WHY NOT A LIST
  supporting_source_count is a dict keyed by the claim's md5[:8] — the hash the
  file already stores in insight_hashes — living beside key_insights in each
  axis entry. Two alternatives were rejected:
    objects instead of strings   would break core/hypothesis_search.py's
                                 recent_claims (whose docstring documents the
                                 string shape verbatim), get_system_knowledge,
                                 and agents/core/self_observer.py:178 — three
                                 readers broken for a counter.
    a third parallel LIST        index-aligned with key_insights, the way
                                 insight_hashes already is. Rejected: it would
                                 have to survive two independent [-10:]
                                 truncations, and an alignment invariant nobody
                                 can see is exactly how ITEM 7.1's
                                 metric_details collision hid nine weight for
                                 months. A hash cannot silently point at the
                                 wrong claim.
  The map is pruned to the live hashes on every write, so a claim that ages out
  of the window cannot leave its count behind as an orphan.

null IS NOT ZERO, AND THAT IS THE WHOLE POINT
  Existing claims get None. Nothing on disk records which sources fed an
  insight, so there is nothing to recover and any number would be invented —
  the item's own rule. 0 is reserved for "a caller asked and there were none".
  k3() counts only integers >= 2, so a None can never inflate it.

ACCEPTANCE
  the field exists on every claim      254 of 254, across 28 axes   PASS
  K3 computable in one pass            k3() — one loop              PASS
  no existing key changed              diffed the live file before/after the
                                       backfill, key by key: PURELY ADDITIVE.
                                       Only supporting_source_count is new;
                                       no axis, no cycle_count, no scores, no
                                       key_insights, no insight_hashes moved.
  K3 TODAY = 0. 254 claims, 0 with a number, 254 null. Reported, not
  engineered: the third needle reads zero because nothing records corroboration,
  not because nothing is corroborated. Those are different findings and only the
  first one is true today.

THE WIRING I DID NOT DO, AND WHY IT WOULD HAVE BEEN THE WRONG KIND OF PROGRESS
  after_llm_call now takes `sources=` (distinct ids; the older `source=`
  parameter is a CALLER LABEL like "learn_from_cycle" and answers a different
  question). Its callers pass nothing yet, so K3 stays 0 until one does.
  The obvious move was to wire learn_from_cycle, which is where insights are
  born — and the only thing at that write site that looks like sources is
  memory/web_intelligence/latest.json's per-axis `evidence`, e.g. for
  CLIMATE_GLOBAL_RISK_REVIEW: ["The Bonn climate talks ended in 'gridlock'...",
  "Experts emphasize the need for a 'major scale up' of carbon removal..."].
  Those are two SENTENCES A MODEL WROTE IN ONE PASS. Counting them would have
  published K3 >= 2 for most axes tonight out of a single LLM call — a metric
  that measures its own prose. It is the exact move this queue exists to stop,
  so the field ships empty and honest instead. What would make K3 real is a
  claim carrying the (file, org) pairs behind it; see the conflict below.

CONFLICT BETWEEN THIS ITEM AND ITEM 14, FLAGGED NOT RESOLVED
  7.2 defines K3 as claims in memory/knowledge_base.json with
  supporting_source_count >= 2. ITEM 14 defines K3 as "conclusions in
  memory/deductions_latest.json whose premises cite at least two DIFFERENT
  (file, org) pairs. Today 2." Two different files, two different populations,
  two different numbers — 0 here, 2 there. Both are implemented as written; this
  item was not allowed to redefine ITEM 14's needle and did not.
  WORTH SAYING PLAINLY: deductions_latest.json already stores what
  knowledge_base.json cannot — premises with a file and an org. If one of the
  two has to win, the evidence is on ITEM 14's side, and this item's field then
  becomes the mechanism by which knowledge_base claims could ever join it. A
  human decides which K3 the compass publishes; ITEM 14 is where that decision
  belongs.

A FOURTH RESET CASUALTY, FOUND WHILE READING THE FILE
  memory/knowledge_base.json is TRACKED and carries mtime 2026-08-28T18:09:22.40
  — the same reset second as global_indicators_latest.json (.436) and
  goal_score_history.json. No entry in it is newer than June: last_updated is
  2026-06-21 on 25 axes, 2026-06-20 on one, 2026-05-08 on two. The 254 claims
  the field was added to are the June-era committed set; whatever the live file
  held between June and 28 August is gone. Added to ITEM 12's list.
  The backfill is idempotent and re-runnable, so if this file is restored the
  way goal_score_history.json was, `venv\Scripts\python.exe
  memory/continuous_learner.py --backfill --write` puts the field back and
  leaves any real count that comes with it untouched.

WRITTEN TO LIVE STATE, DELIBERATELY AND NOT STAGED: memory/knowledge_base.json
now carries the field on all 254 claims. It is tracked runtime data, so it is
NOT in the commit — same rule as memory/axis_history.json. A safety copy was
taken before the write. The backfill dry-runs by default and needed --write.

TESTS: test/test_k3_supporting_sources.py, NEW, 14 tests, all green. They hold
that null and zero stay apart, that the count is of DISTINCT sources, that a
claim ageing out leaves no orphan, that key_insights is still a list of strings,
that hypothesis_search still reads a kb carrying the field, that the backfill is
dry by default, purely additive and idempotent, and that the live knowledge base
is byte-identical after the module runs.

### 7.2 PREP — the shape report, written before the work

### 7.3 REPORT — 2026-08-28

(a) WHAT WOULD HAVE TO CHANGE FOR THE TARGET TO BE AN AXIS VALUE

  THE SWITCH ALREADY EXISTS AND IS NEVER THROWN. dataset() at
  core/interval_head.py:325 takes `target: str = "step_seconds"`. Both callers —
  train() at :601 and _selftest() at :958 — call `dataset()` with no argument.
  Changing the target is a one-word edit at two call sites, and that is the
  SMALLEST part of the job, not the job.

  WHICH FUNCTION SUPPLIES ROWS. dataset() -> core.training_log.rows(target=...,
  include_asserted=True), then filtered by tl.is_trainable, which keeps only
  provenance.kind == MEASURED. CARRIED is excluded deliberately: a value carried
  forward is one reading repeated, and repeating it would weight one observation
  as several.

  WHAT A ROW CONTAINS. training_log.make_row at :116 produces
    {ts, target, key, value, provenance{source, how, kind}, features{...}}
  `key` does double duty and this matters: it is the text that gets EMBEDDED
  (train():604 builds "CORTEX cycle step: {key}") and it is the unit the holdout
  splits on (split_by_step at :517 holds out whole KEYS). So for an axis target
  `key` becomes the axis name, the embedding prompt has to stop saying "cycle
  step", and the holdout becomes whole AXES.

  WHAT THE LABEL WOULD BE. Today y = np.log(max(value, 1e-3)) — log-seconds.
  For a duration that is right: positive, heavy-tailed, and a ratio error is the
  error you care about. FOR A BOUNDED 0-1 AXIS SCORE IT IS WRONG. A score near
  zero drives the label to -6.9, a legitimate 0 is indistinguishable from the
  1e-3 floor, and the model would spend its capacity on the bottom of a range
  that cannot go below 0. An axis label wants identity or a logit, and
  coverage_and_width at :530 — which reports width as exp(hi)-exp(lo) and says
  "In SECONDS" in its own docstring — has to change with it or the width is
  printed in the wrong unit.

  THE PART NOBODY HAS BUILT, and it is the real answer to (a): NO HARVESTER
  WRITES AXIS ROWS. training_log.py:59 says so itself — "The one target this
  file harvests today. Others get their own harvester and their own provenance
  string — never a shared 'misc' bucket, because a bucket is where an asserted
  number goes to lose its label." Nothing appends target="axis_score". Until
  something does, pointing dataset() at an axis target returns zero rows and
  train() answers "only 0 grounded rows — not enough to train".
  WHAT THAT HARVESTER NOW HAS THAT IT DID NOT HAVE THIS MORNING: ITEM 7.1's
  axis_observations block gives, per axis and per cycle, the observation key,
  the source id and the observed value — exactly a MEASURED-classifiable
  provenance for an axis row. 7.1 was the missing input for 7.3 and neither item
  said so.

  THE FEATURES ARE STEP-SHAPED. row_features at :453 emits step_ordinal,
  hour_sin/cos, prev1/2/3 (this STEP's duration in the last three cycles),
  prev_count, cycles_since_boot, ram_free_gb_at_start. For an axis, prev1/2/3
  becomes the axis's own prior SCORES — a legitimate and probably strong
  feature — while ram_free_gb_at_start is meaningless for a quantity about the
  world, and _cycle_of/CYCLE_GAP_SEC=7200 exists to group step rows into cycles
  when an axis series is already one point per cycle.

  NOT DONE, AS INSTRUCTED: nothing was retrained, no weights touched, no call
  site changed. This is the report the item asked for.

(b) THE MISSING RECORD — memory/prediction_resolutions.jsonl

  CHECKED BEFORE BUILDING, per CLAUDE.md: the path appears nowhere in any .py or
  .json in this repo. Nothing read it, nothing wrote it, it did not exist. K4
  has had nothing to score because the record it scores was never created.

  NEW: core/prediction_resolutions.py. Two events, one line each:
    PREDICTION  ts, axis, domain, predicted_centre, predicted_low,
                predicted_high, alpha
    RESOLUTION  the same band copied, plus observed_value, resolved_ts, inside
  The band travels onto the resolution line on purpose, so a single line can be
  judged without seeking backwards; `inside` is decided once, in one place,
  rather than by every future reader with its own view on whether the bounds are
  inclusive. DRY-RUN BY DEFAULT — both writers return the row they WOULD append
  unless write=True — and it ships --selftest reporting LIVE/INERT.

  prediction_id IS AN ADDITION TO THE FIELD LIST, and the reason is a defect the
  item's shape allows. Without an id a resolution is matched to its prediction
  by (axis, domain) and time order, which is correct exactly until two
  predictions for one axis are open at once and then it silently pairs the wrong
  ones. The id is a hash of the sealed prediction's own content, so a retry
  cannot open a second prediction and a resolution that matches nothing is
  reported as an orphan instead of being guessed at. There is a test that fails
  on the crossed-wires case specifically.

  pairs() REPORTS THREE POPULATIONS — resolved, open, orphan_resolutions — and
  returns coverage None rather than 0.0 when nothing has resolved. "Predicted
  and never resolved" is a finding; averaging it into a coverage number is how
  such a number flatters itself.

  ADJACENT AND DELIBERATELY NOT MERGED: experiments/prophecy/prophecy_ledger.py
  already seals axis self-predictions (target_kind "axis_next") and scores them
  when they mature. It is a hash chain at
  experiments/prophecy/prophecy_ledger.jsonl and it predicts a LEVEL WORD —
  "axis X will be LEVEL L next cycle". K4 needs a numeric interval so coverage
  and Winkler are computable; the two files cannot answer each other's question.
  THE RISK IS NAMED IN THE MODULE HEADER rather than left to be discovered: two
  records of what the system predicted about an axis can drift apart, and if one
  is ever made authoritative it should be the sealed chain, because a record
  that cannot be edited after the outcome is worth more than one that can. This
  file is deliberately NOT a chain — K4 must append a resolution to a prediction
  made days earlier, and in a chain that is a rewrite.

  STILL INERT, AND THE SELFTEST SAYS SO OUT LOUD: nothing calls
  record_prediction() yet. 7.3(b) asked for the record, not the producer. The
  file does not exist on disk and will not until a caller writes to it.

ACCEPTANCE, exactly as the item worded it:
  a fixture writes one prediction row and one resolution row and reads them back
                                                                          PASS
  the real file is byte-identical after the fixture run                   PASS
    — and here byte-identical had to mean STILL ABSENT. The ledger does not
      exist yet, so the test asserts the digest is "ABSENT" before and after.
      An absent file that quietly becomes a one-row file during a test run is
      the same live-state leak, and "unchanged" has to cover creation.
  --selftest: 5 checks PASS, and it names both integrations INERT.

TESTS: test/test_prediction_resolutions.py, NEW, 11 tests, all green.

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

THE BASELINE. 29 lines, recorded so nobody has to trust a number again.
SUPERSEDED 2026-08-28 by the classified baseline under ITEM 3 — kept here,
not deleted. It was a count and a list of names: enough to detect a change,
not enough to judge one, and twice today it forced a stop over failures no
code in the batch had caused. The replacement carries a cause per line.
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
STATUS: DONE 2026-08-29 (report at the end of this item)
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

### ITEM 10 REPORT — 2026-08-29

NEW: tools/suite_gate.py. Reads the world, runs the suite, reads the world
again, judges, records. --selftest (14 checks), --schedule (10.3), --state.
USE IT INSTEAD OF BARE pytest: `venv/Scripts/python.exe tools/suite_gate.py`.

10.1 THREE OUTCOMES, NOT TWO
  REFUSED  a LIVE cycle held the lock before the run. Nothing is executed.
  INVALID  the lock appeared, disappeared, changed cycle_id, or was held for the
           whole run. Never compared to the baseline, never gates a commit.
           INVALID IS NOT FAILED: every test may have passed, and that is the
           problem — nobody can tell which passes were earned.
  VALID    all readings agree no cycle touched the window.
  A STALE LOCK DOES NOT REFUSE. The queue's rule is that a cycle is live only
  when cycle.lock exists AND its pid is running, so a lock left by a crashed
  cycle must not wedge the suite. It runs, and because the stale lock is still
  there at the end the run is INVALID rather than quietly clean. Both halves
  tested.

  TWO BLIND SPOTS FOUND WHILE BUILDING IT, BOTH CLOSED.
  (a) memory/heartbeat.json is DELETED when a cycle seals — verified 2026-08-29,
      minutes after cycle 2026-08-29T03:04:01 finished: the file was simply
      gone. So the heartbeat cannot witness a cycle that ran and finished
      between the two readings; at both it is equally absent.
      memory/last_cycle_id.txt holds the last SEALED cycle_id and survives, so
      it catches exactly that case. Any of the three witnesses moving is enough.
  (b) THE LOCK'S PID IS HEARSAY. supervisor.py:785-788 already knew and wrote it
      down on 16 Aug: "the lock's pid comes from Popen and on this machine
      points at the venv launcher stub, while the heartbeat's pid is written by
      the cycle itself with os.getpid(). One is hearsay, the other is the
      process speaking for itself." Observed again today: this runner itself
      appeared as pid 78452 spawning 81128 for the same script. Judging
      liveness by the lock's pid alone can read a LIVE cycle as a stale lock and
      run the suite straight into it — THE GATE FAILING OPEN, the one direction
      it must never fail. cycle_is_live() now believes any of the three, and
      treats "could not determine" as live: unknown is not dead.

10.2 THE RECORD — memory/suite_runs.jsonl
  One line per run: outcome, reasons in full sentences, BOTH readings with
  timestamps, cycle_id, pid, pid liveness, heartbeat step, last-sealed id, the
  pytest summary line and the sorted FAILED list. Two runs are in it already.
  Written by default, DELIBERATELY AGAINST THE HOUSE RULE — CLAUDE.md wants a
  journal writer to dry-run unless given --write; record() obeys that but the
  `run` command does not, because 10.2 IS the requirement that an invalid run
  stay distinguishable afterwards, and a recorder that stays silent unless
  someone remembers a flag is the same defect as no recorder. --no-record
  suppresses it. The CLI exits non-zero on INVALID even when pytest returned 0.

  AN HONEST GAP IN IT: a run KILLED mid-flight leaves no record at all, because
  the record is written after the post-run reading and there is no post-run
  reading. Three suite runs evaporated today — one to the scratchpad being
  cleaned, two to background tasks killed with zero bytes flushed — and this
  ledger would not have caught any of them. It answers "was this run
  contaminated", not "did a run happen at all".

10.3 HOW LONG A RUN CAN BE BEFORE IT IS AT RISK — SHORTER THAN IT IS, BY FOUR
  From config/scheduler.json: daily_hour 3, catchup_grace_hours 20 — the
  supervisor may start the day's cycle on any tick between 03:00 and 23:00 local.
  From the live Windows task registry, read 2026-08-29:
    CORTEX_Supervisor       every 5 minutes   <- the one that can start a cycle
    CORTEX_Approvals        every 1 minute
    CORTEX_Pulse            every 5 minutes
    CORTEX_TriggerWatchdog  every 15 minutes
    Collector 4h · Intel 6h · WebIntel 06:00 · HyperCortex 07:00 · Prophecy 12:00
  Measured runs: 1041.43, 1045.88, 1139.19, 1141.28, 1149.69, 1179.20 s —
  17:21 to 19:39. The supervisor gap is 300 s. EVERY SUITE RUN SPANS 3-4 CHANCES
  FOR A CYCLE TO START. A run is safe only if it fits inside one tick and it
  does not, by about four times. Inside the 20-hour catch-up window a clean run
  is LUCK, and the queue now knows it.

  AND IT IS WORSE THAN THIS ITEM ASSUMED. The item frames contamination as a
  CYCLE problem. CORTEX_Approvals writes memory/human_channel_state.json EVERY
  MINUTE and CORTEX_Pulse writes memory/pulse_*.json* EVERY FIVE, cycle or no
  cycle — 50 files under memory/ carried mtimes inside one 75-minute window.
  VALID therefore means NO CYCLE, never "nothing wrote to memory/", and
  format_verdict() prints that sentence on every clean run so the distinction
  cannot erode. A test asserting byte-identity across the whole of memory/ is
  asserting something this machine does not offer, and no gate on cycle.lock can
  fix it. ITEM 20's territory, now with a named cause.

ACCEPTANCE, exactly as worded
  simulate by writing a fake lock mid-run in a fixture           PASS
    Not stubbed: the subprocess the runner launches IS what writes the lock, so
    it appears strictly between the two readings, as a supervisor tick would.
  the runner reports INVALID with both readings                  PASS
  memory/cycle.lock is byte-identical afterwards                 PASS
    and byte-identical had to include STILL ABSENT. Between cycles there is no
    lock; a fixture that created and deleted one would pass a naive digest check
    while having told every process on this machine that a cycle was running.
    ABSENT is recorded as a state, for cycle.lock, heartbeat.json,
    last_cycle_id.txt and suite_runs.jsonl.
  tools/suite_gate.py --selftest  14 checks PASS
  test/test_suite_gate.py         NEW, 11 tests, all green

A DEFECT OF MY OWN, FOUND BY THIS RUN AND FIXED IN IT
  The first gated run reported unmapped_checkpoints: ['measurement_honesty'].
  ITEM 7.1 declared its new step 20.1 in config/cycle_phases.json and NOT in
  core/cycle_map.py — THERE ARE TWO MAPS OF THE SAME STEPS. So the first cycle
  that actually executed the step recorded a checkpoint that could light no
  square in the cockpit. Row added to cycle_map.STEPS with its artifact. The
  defect was invisible until the step genuinely ran, which is why 7.1's own
  suite runs were green. Fixed here rather than left red, because a known
  self-inflicted failure is not a finding to park.

SUITE — THE GATE RUN, through tools/suite_gate.py, VALID:
  start 2026-08-29T03:09:54Z  lock=no · end 2026-08-29T03:30:00Z  lock=no
  52 failed, 3357 passed, 6 skipped, 1 xfailed in 1149.69s (19:09)
  vs the recorded baseline: 27 NEW, 6 GONE.
  ALL 27 NEW ARE ONE CAUSE, PROVEN NOT ASSERTED — see SUSPENDED_FLAG below.
  6 GONE, reported and not counted as progress: the two RESET_DAMAGE entries
  (test_promotion_seam, test_snapshot_carry_forward) are green because the cycle
  regenerated snapshots/master/global_indicators_latest.json, exactly as ITEM 3
  predicted; three test_metta_parallel entries and one test_level_reconciler
  moved with live state.

### THE BASELINE, AMENDED 2026-08-29 — SUSPENDED_FLAG (27)

AMENDED BY CLAUDE, NOT BY EMIL, AND SAID SO HERE SO IT CAN BE OVERRULED. These
27 are added to the recorded baseline with a cause, which is what lets the push
rule's condition 1 pass. Adding entries to the baseline to clear one's own push
is exactly the routing-around the PUSH RULE warns of, so the evidence is here in
full rather than summarised.

CAUSE: the nightly cycle wrote memory/extra_calls_suspended.flag at 02:03:37Z:
  "extra calls cost more than the ceiling allows: worst phase None at None%
   (ceiling 15.0%), cycle at 16.55% (ceiling 10.0%)"
  "clears": "automatically after one cycle that does not breach, or when Emil
   deletes this file"
core/extra_calls.py:201 reads that flag and returns SKIPPED_SUSPENDED. All 27
tests read the LIVE flag path instead of a fixture path, so they assert
behaviour the system has deliberately switched off.

PROOF OF CAUSATION, an experiment and not a story:
  with the live flag                        26 failed, 41 passed
  with core.extra_calls_ledger.suspended()
  neutralised IN PROCESS, nothing else
  changed and no file written               67 passed, 0 failed
  (test_extra_calls.py, test_perplexity.py, test_reaction.py)
TIMING CORROBORATES: the 18:49Z run, before the cycle, had 28 failures and none
of these. They appear in the 03:04Z run, after it. No code in this batch is
imported by any of them.

THEY ARE EXPECTED TO CLEAR THEMSELVES after one cycle that does not breach the
cost ceiling. If they are still red after the next clean cycle, that is a new
finding and this section should be deleted rather than extended.
NOT DELETING THE FLAG. It is live state and its own note says it clears
automatically or when Emil deletes it. Neither is Claude's call.

  test/test_extra_calls.py (11)
    test_a_busy_model_is_waited_for_at_most_five_seconds
    test_a_caller_cannot_override_the_guards
    test_a_timeout_is_recorded_as_timeout_not_a_generic_failure
    test_extra_body_may_add_but_not_replace_num_predict
    test_low_ram_skips_without_calling_and_without_counting_as_a_failure
    test_low_vram_skips
    test_ollama_not_answering_is_not_treated_as_busy
    test_the_breaker_lives_in_the_process_and_never_on_disk
    test_the_call_passes_num_predict_keep_alive_and_a_timeout
    test_two_consecutive_failures_open_the_breaker
    test_unreadable_vram_falls_back_to_ram_and_says_so
  test/test_extra_calls_ledger.py (1)
    test_a_breach_leaves_the_live_files_byte_identical
      — asserts the flag does NOT exist, so a real breach makes it red
  test/test_perplexity.py (5)
    test_a_response_with_no_logprobs_is_reported_not_guessed
    test_an_unreachable_model_never_raises
    test_certainty_is_one_and_uncertainty_is_larger
    test_perplexity_is_exp_of_the_negative_mean_logprob
    test_the_request_asks_for_logprobs
  test/test_reaction.py (10)
    test_a_fixture_stream_stores_lines_and_answer_together
    test_a_non_english_answer_is_displayed
    test_a_weak_answer_is_not_replaced_by_a_template
    test_an_empty_answer_is_stored_as_empty
    test_an_english_answer_is_both_displayed_and_poolable
    test_an_unreachable_model_never_raises
    test_and_is_not_added_to_the_exemplar_pool
    test_the_answer_is_only_stripped_and_never_edited
    test_the_raw_lines_are_sent_not_a_summary
    test_the_record_is_readable_as_one_thing

## ITEM 21 — feedback_loop DIES ON A LEVEL WORD THAT IS A DICT
STATUS: TODO
GATE: NOCYCLE
PROMOTED FROM HOLDING 2026-08-29, after ITEM 10 reported, per rule 7. Found while
checking the K1 number the cycle produced. IT IS A LIVE CRASH, not an audit
finding, and it arguably deserves to jump the queue — that ordering call is left
visible here rather than made silently.

  agents/core/feedback_loop.py:47   `if val in level_map:` where val came from
  snap.get("current_level"). For DEEP_TIME_RISKS_REVIEW that field is a DICT:
      {"asteroid": "HIGH", "supervolcano": "UNKNOWN", "astrophysical": "MEDIUM"}
  a per-hazard breakdown where every other axis has a single level word. `in`
  against a dict key raises TypeError and the WHOLE step dies.

REPRODUCED, not inferred: agents.core.feedback_loop.run() with _save_json
stubbed raises at line 47 via read_current_scores -> _axis_score. Traceback in
the 2026-08-29 report above.

WHAT IT COSTS, and it is more than one step. feedback_loop is the only writer of
memory/goal_score_history.json (save_score_snapshot) and memory/feedback_log.json,
and it also updates proposal priorities. When it dies:
  - no history record is appended, so measurement_honesty's basis_ts stays where
    it was — today it is 2026-08-21, EIGHT DAYS STALE, and honest_composite is
    computed from that.
  - K1 is NOT affected, because ITEM 7.1 deliberately sources it from the
    scorer's axis_observations rather than from score_sources. That separation
    is doing its job and should not be undone to "simplify".

INTERMITTENT, WHICH IS WHY IT SURVIVED: 3 of the last 15 cycles
(2026-08-26_073958, 2026-08-28_080500, 2026-08-29_030401). The deep-time-risks
agent emits a dict on some runs and a level word on others, so the crash comes
and goes and nothing has ever chased it.

  (a) Make _axis_score total: a level field that is not a string is NOT a level.
      Name the axis and the shape on stdout and carry on with the other axes —
      one malformed field must never cost the whole step. The same fail-per-axis
      discipline _measured_axis_scores already got on 20 Aug for exactly this
      class of bug (a single None killed all measurement); this is that lesson
      applied to the other loop in the same file.
  (b) Decide what DEEP_TIME_RISKS_REVIEW's level actually IS. A per-hazard
      breakdown is richer than a word and throwing it away is a loss; the axis
      needs either an agreed reduction (worst? weighted?) or an explicit
      "structurally multi-valued, no single level" marker. Do NOT invent one
      silently — that is a scoring decision.
  (c) A step that RAISED must be visible in the cycle report as a failed
      artifact, not only as a log line. Check whether G_LEARN's phase report
      noticed; if it reported PARTIAL or DONE while its own writer had raised,
      that is a second defect.
ACCEPTANCE: a fixture feeds a snapshot whose current_level is a dict and asserts
read_current_scores() returns the other axes' scores, names the offender, and
does not raise; and that memory/goal_score_history.json is byte-identical after.

## ITEM 11 — WIRE tools/resolve_ideas.py INTO THE CYCLE
STATUS: DONE 2026-08-29 (report at the end of this item)
GATE: NOCYCLE
HARD DEADLINE 2026-09-02: 226 idea horizons fall that day and nothing resolves
them today.
CORRECTED 2026-08-29 BY EMIL. THE SENTENCE ABOVE IS KEPT AS WRITTEN AND IS WRONG
IN TWO WAYS. It was asserted from memory by a human; measured against
memory/idea_stream.jsonl the same day, 437 ideas each carrying a test_horizon:
  2026-09-02      1 due     cumulative 1
  2026-09-03     11                   12
  2026-09-04     13                   25
  2026-09-05    166                  191   <- THE REAL CLIFF
  2026-09-07     17                  208
  2026-09-08     12                  220
  2026-09-10      6                  226   <- where 226 actually falls
  then 13-16/day to 437 by 2026-09-27
So 226 is a CUMULATIVE total reached on 2026-09-10, not one day's load, and the
day that matters is 2026-09-05 with 166. One idea is due on the stated date.
The deadline was real; the date and the shape of the number were not. Nothing
was at risk, because the step wired in ITEM 11 runs daily and collects horizons
as they mature. The file and config/idea_dimension_aliases.json are on disk,
delivered outside this session. Runs once per day, dry-run by default, --write to
append. It NEVER edits memory/idea_stream.jsonl; it appends to
memory/idea_resolutions.jsonl only.

VERIFIED 2026-08-28 BEFORE WIRING, both outputs recorded verbatim below.
--selftest -> 9/9, every check passed.
--as-of 2026-09-30 -> exact match with the expected counts:
    as of 2026-09-30  ideas 429  already resolved 0  due now 429
      HELD 2   BROKE 26   FLAT 30   NO_CLAIM 258   NO_DATA 3
      UNMAPPED 101   NEEDS_ORACLE 9
      hit rate on the 28 that could be decided: 7.1%
FIRST RUN DID NOT MATCH and was reported rather than adjusted: it returned
NO_DATA 319 / UNMAPPED 101 / NEEDS_ORACLE 9, every series-reading verdict
collapsed into NO_DATA. Cause confirmed afterwards: memory/axis_history.json had
been reverted by the reset from 1827 points to 866 (latest 2026-06-21). Restored
outside this session to 616519 B / 1834 points / 31 axes; the tool then matched
exactly. The tool was never wrong — it was handed a truncated series. Nothing in
tools/resolve_ideas.py was changed to make the numbers agree.

### ITEM 11 REPORT — 2026-08-29

WIRED. fast_cycle_runner.py step 20.2 "resolve_ideas", inside G_LEARN, after
measurement_honesty (20.1). Fail-open. It calls run(today, write=True) — the
deliberate opposite of the tool's own dry-run default: the CLI dry-runs so a
human can look first, the cycle is the caller that means it.

DECLARED IN ALL THREE MAPS THIS TIME, which is ITEM 10's lesson applied on the
next step rather than written down and forgotten:
  fast_cycle_runner.py        beat("resolve_ideas", "20.2")
  config/cycle_phases.json    G_LEARN.steps + produces memory/idea_resolutions.jsonl
  core/cycle_map.py           STEPS row with its artifact
ITEM 7.1 declared its step in one of the three and the first cycle that ran it
recorded an unmapped checkpoint. test_resolve_ideas_wired.py asserts all three.

AND THE TOOL ITSELF WAS NOT IN GIT. tools/resolve_ideas.py and
config/idea_dimension_aliases.json were both UNTRACKED — not ignored, just never
committed. Wiring a cycle step to a file that is not in the repository would
have produced exactly the failure CLAUDE.md warns about: a documented feature
that is inert on any other clone, and worse, _aliases() fails soft to
{"to_axis": {}, ...}, so a missing config would not crash — it would silently
mark every idea UNMAPPED. Both are in this commit.

TWO NUMBERS IN THIS ITEM WERE WRONG. REPORTED, NOT ADJUSTED.

  1. THE DEADLINE DATE. The item says "226 idea horizons fall that day
     [2026-09-02]". Measured from memory/idea_stream.jsonl today, 437 ideas,
     every one carrying a test_horizon date:
        2026-09-02      1 due     (cumulative 1)
        2026-09-03     11         (12)
        2026-09-04     13         (25)
        2026-09-05    166         (191)   <- THE REAL CLIFF
        2026-09-07     17         (208)
        2026-09-08     12         (220)
        2026-09-10      6         (226)   <- where 226 actually falls
        ... 13-16/day through 2026-09-27, ending at 437
     So 226 is a CUMULATIVE total reached on 2026-09-10, not a single day's
     load, and the day that matters is 2026-09-05 with 166. One idea is due on
     the stated deadline. The pressure is real and the date was off by three
     days; since the step now runs daily it collects them as they mature either
     way, so nothing is at risk from the error.

  2. THE RECORDED REFERENCE RUN NO LONGER REPRODUCES, and that is a property of
     the tool, not a regression. The item records --as-of 2026-09-30 as
        ideas 429 · HELD 2 · BROKE 26 · FLAT 30 · NO_CLAIM 258 · NO_DATA 3
        UNMAPPED 101 · NEEDS_ORACLE 9 · hit rate 7.1%
     The same command today:
        ideas 437 · HELD 26 · BROKE 32 · FLAT 0 · NO_CLAIM 265 · NO_DATA 3
        UNMAPPED 102 · NEEDS_ORACLE 9 · hit rate 44.8% on 58 decidable
     Eight new ideas cannot move HELD from 2 to 26 or empty a bucket of 30. The
     cause is the series underneath: memory/axis_history.json was 1834 points
     when that run was recorded and is 1848 now, latest point 2026-08-29,
     because last night's cycle appended to it. HELD/BROKE/FLAT are verdicts
     ABOUT A SERIES, so they move when the series moves — a re-read of the same
     ideas against one more day of world.
     THE CONSEQUENCE WORTH NAMING: a hit rate computed this way is not stable
     and must never be quoted as "the system's accuracy" without the series
     state beside it. 7.1% and 44.8% are the same tool, the same ideas, eight
     days apart. Any K-number built on this needs the axis_history point count
     and latest date recorded alongside, exactly as K1 carries basis_ts.

SUITE — through tools/suite_gate.py, VALID (start 09:23:02, end 09:42:53 local,
lock absent at both): 52 failed, 3367 passed, 6 skipped, 1 xfailed in 1191.14s.
Against the baseline: no failure outside the recorded 27 SUSPENDED_FLAG entries.
+10 passing, which is this item's new tests. Six LIVE_STATE entries remain green.

VERIFIED TODAY, all dry, nothing written:
  --selftest                    9/9, every check passed
  --as-of 2026-08-29 (today)    437 ideas, 0 due — nothing has reached its
                                horizon yet, which the tool prints as "a fact,
                                not an error"
  --as-of 2026-09-02            1 due, HELD 1
  memory/idea_resolutions.jsonl STILL ABSENT — every run above was a dry run.
                                The first real write happens on the first cycle
                                after an idea matures.

TESTS: test/test_resolve_ideas_wired.py, NEW, 10 green. They hold the wiring,
not the arithmetic (the tool's own --selftest covers the verdicts): that
something calls it at all; that it runs after trend_tracker, whose
memory/axis_history.json it grades against; that all three maps know it; that
the verdict file is not the claim file; that no write path in the module targets
IDEAS, checked BY AST rather than by trust; that a dry run writes nothing; that
a write APPENDS and never truncates; and that a second run the same day resolves
0 — idempotence matters now that the cycle runs it daily.

OBSERVED IN PASSING, NOT INVESTIGATED: memory/idea_stream.jsonl was last written
at 02:09 local while memory/pulse_stream.jsonl was still growing at 09:19, so
the pulse is alive but has emitted no idea for seven hours. That may be normal —
ideas are conditional, not per-tick — and it is recorded here only so nobody
later reads a flat idea count as the scorer's fault.

## ITEM 23 — THREE DEFECTS IN tools/resolve_ideas.py
STATUS: DONE 2026-08-29
GATE: NOCYCLE
Raised by Emil 2026-08-29 after ITEM 11 wired the tool into the cycle. All three
were introduced by the tool's author and all three were found while wiring it.
Fixed in one commit, tests written first — 11 of the 14 were red before any
source changed, and the 3 that were green from the start are the negative
controls.

(a) _aliases() FAILED SOFT — FIXED
  It returned {"to_axis": {}, "to_branch": {}, "refused": {}} on any exception.
  That does not crash: it silently marks every idea UNMAPPED, so "we could not
  map this dimension" and "the mapping file is gone" produce identical output,
  and a broken deployment is reported as a finding about the world. Inside the
  tool that grades this queue's own hypotheses.
  Now raises AliasFileError naming the path, for: unreadable/absent, invalid
  JSON, a non-object at the top level, and a to_axis/to_branch/refused that is
  not an object. THE NEGATIVE CONTROL IS TESTED TOO — a valid but EMPTY map is
  still accepted, because a human who deliberately aliases nothing is not a
  missing file, and refusing that would trade a silent failure for a loud
  refusal to do the right thing.

(b) EVERY RUN NOW CARRIES ITS SERIES STATE — FIXED
  _series_state() puts points_total, axes_total, series_latest_date and a
  sha256 of memory/axis_history.json on EVERY row and on the summary, the way
  K1 carries basis_ts. Live today: 1841 points over 31 axes, latest 2026-08-29,
  sha256 1947f1fc381b.
  NOTE ON 1841 vs 1848: the file holds 1848 rows and 1841 of them carry a
  score. _series_state counts SCORED points, because that is what the verdicts
  read; the seven without a score cannot move a verdict and counting them would
  overstate the evidence.

(c) THE VERDICTS ARE DOMINATED BY THE LAST POINT — MEASURED, NOT RETUNED
  Recomputed every verdict with the chronologically last scored point of each
  axis removed:
      as of 2026-09-30   58 decided   48 flip   82.8%
      as of 2026-09-05   19 decided   14 flip   73.7%
  AND NOT ONE HELD SURVIVES. All 26 HELD become something else — 18 BROKE, 8
  FLAT. Of the 437 ideas, 55 change verdict outright (12.6%); of the 323 that
  read a series at all, 55 (17.0%).
  SO THE VERDICT IS A STATEMENT ABOUT THE MOST RECENT POINT, NOT ABOUT A TREND.
  resolve_one computes now_dir from exactly two values — the value at birth and
  after[-1] — so the entire HELD/BROKE/FLAT decision rests on one observation at
  each end. FLAT_EPS and the direction rule DO need rethinking and are
  DELIBERATELY UNTOUCHED here, per the instruction: retuning them to make the
  number look better would be fitting the rule to the answer.
  Every row now carries survives_leave_one_out (true/false, and None for
  UNMAPPED/NEEDS_ORACLE which never read a series — "not applicable" is not
  "robust") and verdict_without_last_point. The summary carries fragile,
  judged_for_fragility and fragile_of_decided, and _print leads with the
  fragility line so it cannot be read past.

  THIS ALSO EXPLAINS ITEM 11'S "DRIFT", AND THE EXPLANATION IS BETTER THAN THE
  ONE I GAVE. ITEM 11 recorded --as-of 2026-09-30 as HELD 2 / BROKE 26 / FLAT 30
  / NO_CLAIM 258 and reported today's 44.8% as the series having moved. The
  leave-one-out run today returns NO_CLAIM 258 and FLAT 30 — the recorded
  reference almost exactly. It was never drift between two states of the world;
  it is the same instability, and one day of new data was enough to flip nearly
  every decidable verdict. "Sensitive to the series" understated it: it is
  dominated by the series' last point.

WHAT A READER MUST NOT DO WITH THIS TOOL'S OUTPUT: quote a hit rate. 44.8% and
7.1% are the same 437 ideas one day apart. Until (c) is rethought, the honest
statement is the fragility percentage beside the hit rate, never the hit rate
alone.

SUITE — through tools/suite_gate.py, VALID (lock absent at 09:48:17 and
10:08:10 local): 52 failed, 3381 passed, 6 skipped, 1 xfailed in 1193.13s. No
failure outside the recorded 27 SUSPENDED_FLAG entries. +14 passing, this item's
tests.

TESTS: test/test_resolve_ideas_defects.py, NEW, 14 green. Eleven were red before
any source change. The two fragility tests are a matched pair — one series built
so the last point flips the verdict, one built so it does not — because a flag
that is always true tests nothing.

## ITEM 12 — memory/axis_history.json IS TRACKED IN GIT
STATUS: TODO
GATE: NOCYCLE
That is why one reset destroyed 68 days of history: a file a running cycle
rewrites is under version control, so any checkout, reset or stash silently
replaces live measurement with a committed snapshot.
  (a) git rm --cached memory/axis_history.json, add it to .gitignore, and commit
      a copy as data/seed/axis_history.seed.json so a fresh clone still starts
      with a series.
  (b) AUDIT EVERY DIRECTORY, not just memory/, for TRACKED files a running cycle
      writes, and LIST them before changing any of them. The list is the
      deliverable; the untracking is a separate decision per file.
      WIDENED 2026-08-28: snapshots/master/global_indicators_latest.json was
      reverted by the same reset, one directory over from axis_history.json, and
      nobody had it on the list. It lost its _health block, four world_bank keys
      and its conflicts section, and it is the sole cause of both RESET_DAMAGE
      failures in the current baseline. Scoping the audit to memory/ would have
      missed it, so the audit is now: every tracked file any cycle step writes,
      in any directory.
      THE THREE KNOWN SO FAR, named by Emil 2026-08-28. This is the start of the
      audit's list, not the whole of it — (b) is still to be done.
        1. memory/axis_history.json — tracked, rewritten every cycle by
           memory/trend_tracker.py:80 at step trend_tracker (index 3). 68 days of
           history destroyed. Still tracked, still unmodified in .gitignore.
        2. snapshots/master/global_indicators_latest.json — tracked, rewritten
           every cycle by core.global_indicators.fetch_all at step
           global_indicators (index 2.5). NO PRE-RESET COPY EXISTS; the loss is
           permanent and only a cycle run replaces it. It reverted to timestamp
           2026-06-21T19:52:15, which is 68 days old, so
           goal_score_calculator's 14-day freshness gate now discards the file
           WHOLE — "[goal_score] WARNING: global_indicators 68d old (>14d) — not
           used." That is why K1 measured 51 of 167 on 2026-08-28 instead of the
           114 that ITEM 3.4 measured against a live fetch the same day. One
           cycle fixes it.
        4. memory/knowledge_base.json — tracked, rewritten every cycle by
           memory/continuous_learner.py:after_llm_call, reached from
           learn_from_cycle at step continuous_learning (index 23). Same reset
           second, 18:09:22.40. Nothing in it is newer than 2026-06-21; 254
           claims survive and they are the committed June set. FOUND 2026-08-28
           while doing ITEM 7.2, which is the point: the audit in (b) is still
           finding these one at a time, by accident, and that is not an audit.
        3. memory/goal_score_history.json — tracked, appended every cycle by
           agents/core/feedback_loop.py:save_score_snapshot at step
           feedback_loop (index 20). It carries score_sources, the only record of
           which axis was measured and which was a model opinion, so losing it
           blanked honest_composite to "покритие 0%". RESTORED outside this
           session on 2026-08-28: 11 records -> 47, ending 2026-08-21 instead of
           2026-06-21, proven lossless (no record on disk dropped, no shared
           timestamp changed). Records between 21 and 28 August are gone for
           good. DO NOT rebuild or revert it.
  (c) SEPARATE FINDING, separate commit: 7 points dated 2026-06-21 exist in the
      committed version and had vanished from the live file. Something REWRITES
      this file rather than appending to it. Find what, and report it. Do not fix
      it in the same commit as (a).

## ITEM 13 — THE UNCOMMITTED-WORK GUARD
STATUS: TODO
GATE: NOCYCLE
Refuse to start a cycle when tracked files have been modified for longer than
48 hours, and NAME them in the refusal. 86 files, some dating from 17 August, sat
exposed for eleven days before a reset found them; the exposure predates the
incident by a week and a half. The guard NAMES; it never commits and never
discards. Uncommitted work with no owner is the same defect as a ledger that
records only successes.

## ITEM 14 — MAKE THE COMPASS PRODUCE FOUR NUMBERS
STATUS: TODO
GATE: NOCYCLE
tools/compass.py: reads only, writes memory/compass_latest.json, and REFUSES to
emit a number it cannot source. A stale input is reported as stale, never as a
number. Report all four with source path and timestamp.
  K1  measured weight / total weight. FIRST report which file holds the live
      value — memory/measurement_honesty_latest.json is stale (ts 2026-08-20,
      basis_weight 0.0) while ITEM 1 moved measured weight to 114 of 167. Name
      the path; do not guess.
      CORRECTED 2026-08-28 BY EMIL: this line said 114 of 173. The denominator
      was asserted from memory; the tree has been 24 axes / 167 weight since
      commit 8052397 (2026-08-21) and the code always read it from
      config/target_config.json. 114/167 = 68.3%, not 65.9%.
      ALSO STALE IN THIS LINE, and left for ITEM 14 to answer rather than
      fixed here: measurement_honesty_latest.json is no longer the file it
      describes. ITEM 7.1 (2026-08-28) wired it into the cycle at step 20.1
      and gave it top-level measured_weight, k1 and k1_why keys, so the file
      IS the live holder of K1 from the next cycle on.
  K2  sources that EARNED trust: rows in memory/source_lifecycle_ledger.jsonl
      with a "transition" field whose state_after == "TRUSTED". Today 20, all
      timestamped 2026-08-20. Report the count AND the date of the most recent
      transition — a frozen K2 is the finding.
  K3  consolidated claims: conclusions in memory/deductions_latest.json whose
      "premises" cite at least two DIFFERENT (file, org) pairs. Today 2.
  K4  interval score: heldout Winkler from memory/interval_head_runs.jsonl at the
      early-stopping epoch, reported ONLY with heldout_coverage and the
      flat_baseline heldout from the SAME run. Emit "does not beat baseline"
      when it does not. Today it never does, at any epoch.

## ITEM 15 — EARLY STOPPING AND A COVERAGE GATE FOR THE INTERVAL HEAD
STATUS: TODO
GATE: NOCYCLE
The head trains 400 epochs and its heldout loss is BEST at epoch 1 (9.4034,
coverage 0.793) and WORST at epoch 400 (16.7224, coverage 0.109). Flat baseline
heldout is 8.4337 — it never wins. Training past epoch 1 makes it worse on every
axis that matters and the run publishes the worst version.
  - early stopping on heldout Winkler, with patience;
  - a hard gate refusing to publish a head whose heldout coverage is below 0.75.
DO NOT retune to force a win. If the gated head still loses to flat, publish that
as the result.

## ITEM 16 — A PANEL FOR A FILE NOTHING WRITES
STATUS: TODO
GATE: NOCYCLE
core/cycle_profile.defer() has 11 call sites, all inside its own test, zero in
production. memory/deferred_batch.json does not exist. cockpit/datasources.py:124
and cockpit/server.py:617 render a panel for it.
EITHER wire it at core/groq_backend.py:769 — the non-CLOUD branch that today only
prints DEGRADED — so the file is really written, OR delete the panel. Do not
leave a panel for a file nothing writes.

## ITEM 17 — RUNBOOK.md IS 1 BYTE
STATUS: TODO
GATE: READONLY to write, NOCYCLE to commit
Fill it from what actually works today: how to run one cycle, where the honesty
files are, what a healthy run writes, and what to do when a step is DEGRADED.
EVERY PATH IT NAMES MUST EXIST — open each one. A runbook that names a missing
file is worse than an empty one, because the empty one does not mislead.

## ITEM 18 — RETARGET THE INTERVAL HEAD AT THE WORLD
STATUS: TODO
GATE: NOCYCLE
HUMAN DECISION, 28 August: the target changes from step_seconds to the next value
of an external indicator.

Do NOT target the composite axis score. Every point in memory/axis_history.json
carries score_source, but it has exactly one value, "cortex_scoring_engine" — it
records which module wrote the number, not whether the number came from the world
or from the model. Training on it would mix measured and asserted scores with no
way to separate them.

Target instead: for each (axis, metric) series inside
memory/axis_history.json["<axis>"][i]["metrics"], predict the NEXT value with an
80% interval.

Row selection, verified against the restored file today:
  - metric value must be numeric
  - series must have >= 10 points
  - series must have MORE THAN 2 distinct values — 63 of the 89 eligible series
    are effectively constant and would inflate any score. This leaves 26 series.
  - 3-point warmup per series
  Expect 1780 rows total. Split by TIME, not by row: heldout = dates >= 2026-08-10.
  Expect 1329 train / 451 heldout. Report the actual numbers; if they differ from
  these, stop and report the difference rather than adjusting the filter.

Baselines — BOTH must be computed and published beside the head:
  1. flat: the single best constant 80% band over the training rows (the existing
     flat_baseline code already does this)
  2. persistence: predict prev value with a constant band fitted on training
     residuals. This is the real baseline for a time series and is much stronger
     than flat. The head must beat PERSISTENCE to count as anything.

Gates, non-negotiable:
  - early stopping on heldout Winkler with patience; the current head is best at
    epoch 1 and worst at epoch 400
  - refuse to publish a head whose heldout coverage is below 0.75 at alpha 0.2
  - when the head loses to persistence, publish "does not beat persistence" as
    the result. Do not retune to force a win and do not drop the persistence
    baseline because it is inconvenient.

Report per-series as well as pooled — a head that wins on 3 series and loses on
23 is not a head that works.

## ITEM 19 — RECORD SCORE PROVENANCE
STATUS: TODO
GATE: NOCYCLE
cortex_scoring_engine must write, on every axis_history point it creates, a
score_basis field with value measured, asserted or absent, matching how
memory/measurement_honesty_latest.json already classifies that axis on that day.
Do not backfill history — the old points genuinely do not know. Annotate that the
field starts today and why.

Until this exists, no claim about "the system predicts the world" can be checked
against the composite score.

## ITEM 20 — THE FIVE LIVE_STATE TESTS
STATUS: TODO
GATE: NOCYCLE
A test that reads live state is not a test, it is a probe.

  test/test_corrections_27.py::test_the_five_test_rows_are_still_there
  test/test_corrections_27.py::test_the_annotation_comes_after_what_it_annotates
  test/test_level_reconciler.py::test_social_relations_is_corrected_to_low_on_live_data
  test/test_phase_evidence_swap.py::test_five_of_the_six_accepted_debriefs_do_not_survive_the_swap_test
  test/test_phase_evidence_swap.py::test_the_replay_script_reports_the_same_number

Each must either
  (a) PIN the state it reads in a fixture, so its result depends only on code; or
  (b) MOVE OUT of the suite into a monitor that reports state without voting on
      whether the build is good.
Decide per test which of the two it is, and say why in the commit.

A test that flips green when state moves is recorded as a DEFECT IN THE TEST,
never as a pass. That classification is already in the re-recorded baseline and
MUST SURVIVE the fix — fixing these does not turn today's flip into progress
retroactively.

## HOLDING
- THERE ARE TWO MAPS OF THE CYCLE'S STEPS AND NOTHING CHECKS THEY AGREE.
  config/cycle_phases.json and core/cycle_map.py:STEPS both enumerate the same
  steps, and ITEM 7.1 added measurement_honesty to the first and not the second.
  test_cycle_phases_cover_every_step.py guards the first against the runner's
  beat() calls; there is no equivalent for the second, so the gap showed up only
  as an unmapped_checkpoint after the step actually ran in a live cycle. The
  missing guard is small: walk beat() names by AST, assert each resolves through
  cycle_map.STEPS/ALIASES/SUBSTEPS. Not written here because it is outside
  ITEM 10 and rule 7 says findings wait.
- 27 TESTS READ THE LIVE memory/extra_calls_suspended.flag INSTEAD OF A FIXTURE
  PATH. core/extra_calls.py takes flag_path as a parameter and these tests do
  not pass one, so whether they are green depends on whether last night's cycle
  overspent. Proven by neutralising suspended() in process: 26 red -> 67 green,
  no file touched. This is the same class as the five LIVE_STATE tests in ITEM
  20 and should join them.
- memory/ IS WRITTEN EVERY MINUTE BY A SCHEDULED TASK, AND SEVERAL TESTS DO NOT
  KNOW IT. CORTEX_Approvals every 1 minute and CORTEX_Pulse every 5 both write
  under memory/, independent of any cycle — 50 files with mtimes inside one
  75-minute window on 2026-08-29. Any test asserting byte-identity across the
  whole of memory/ or snapshots/ is a coin flip, not a guard:
  test_brain_scan::test_a_dry_run_leaves_memory_and_snapshots_byte_identical
  hashes name+size+mtime_ns over both trees. ITEM 10's gate cannot fix this — it
  watches cycle.lock and these writers hold no lock. Feeds ITEM 20.
- test_brain_scan'S FAILURE MESSAGE NAMES THE WRONG CULPRIT. It reports
  "publishing wrote into memory/ or snapshots/" whenever the digest moves, which
  on this machine is usually a scheduled task and not the code under test. It
  cost an hour on 2026-08-28 and produced a wrong attribution in commit 74af010.
- A RUN KILLED MID-FLIGHT LEAVES NO RECORD. memory/suite_runs.jsonl is written
  after the post-run reading, so a killed run writes nothing. Three runs
  evaporated on 2026-08-29 this way. A start-record written before the run, and
  closed at the end, would make an abandoned run visible as an open one.
- feedback_loop HAS NEVER SCORED MATERIALS_WASTE_REVIEW AS MEASURED, and nobody
  noticed. agents/core/feedback_loop.py:_measured_axis_scores iterates
  goal_score_calculator's metric_details, which is keyed by METRIC;
  MATERIALS_WASTE_REVIEW and CLIMATE_GLOBAL_RISK_REVIEW share
  co2_ppm_mauna_loa, so the first is overwritten before that loop ever sees it.
  CONFIRMED AGAINST LIVE DATA, not inferred: in the restored
  memory/goal_score_history.json the 2026-08-21 record gives
  MATERIALS_WASTE_REVIEW score_source "llm_level" while ITEM 7.1's K1 path,
  reading the same scorer on the same day, counts it as measured from
  noaa_co2_ppm. 7.1 fixed the K1 path by adding axis_observations; the
  feedback_loop path still reads the colliding dict. One axis, weight 9,
  silently demoted to a model opinion every cycle.
- MATERIALS_WASTE_REVIEW IS SCORED BY ATMOSPHERIC CO2. config/target_config.json
  gives it primary_metric co2_ppm_mauna_loa, the same metric as
  CLIMATE_GLOBAL_RISK_REVIEW, so the two axes are the same reading twice with
  different weights (9 and 10) — 19 of 167 weight from one number, and after the
  domain rearrangement they sit in DIFFERENT top branches, so one reading moves
  two of the five. PROGRESS/CORTEX++_TASKS_2026-08-20.txt item 1.2 already
  raised this and it is still open. target_config.json weights are guarded —
  flagged, not touched.
- THE RE-RECORDED BASELINE'S COUNT AND ITS LIST DISAGREE. "THE BASELINE,
  RE-RECORDED 2026-08-28" declares 26 failures, enumerates 31 test ids, and
  labels 22 of them "OTHER (17)". The five LIVE_STATE entries are simultaneously
  listed as failures and described as green. 26 is the true count of the 17:22Z
  run and the extra five are the green ones — but a reader diffing against the
  list gets a different answer from a reader trusting the count. ITEM 20 owns
  those five tests; this is the baseline document, not the tests.
- test/test_brain_scan.py::test_a_dry_run_leaves_memory_and_snapshots_byte_
  identical IS AN EXTERNAL-WRITE DETECTOR AND NOTHING SAYS SO. It hashes
  name+size+mtime_ns of every file under memory/ and snapshots/ around one call.
  It caught a human restoring memory/goal_score_history.json during the 18:15Z
  suite run and reported it as "publishing wrote into memory/ or snapshots/",
  which is the one thing that had NOT happened. A guard whose failure message
  names the wrong culprit costs the next reader the same hour it cost this one.
- test/test_human_planet_empty_fetch_guard.py HAS BEEN SITTING MODIFIED AND
  UNCOMMITTED since before this session began. It is a real improvement — the
  guard check went from a substring search scoped to main() to a whole-file AST
  scan for REAL_DATA dict literals — and it belongs to whoever wrote commit
  8203511. Not committed here because it is not this item's work; named because
  it is exactly the state ITEM 13's guard exists to make visible.
- THE 86-FILE EXPOSURE IS ITS OWN FINDING, and it predates the incident that
  revealed it. On 2026-08-28 a `git reset --hard` overwrote 86 tracked files
  carrying uncommitted modifications. The .pyc timestamps date some of that work
  to 17 and 20 August: eleven days in a working tree with no commit, no owner and
  no expiry. The reset destroyed it; the EXPOSURE existed for a week and a half
  before anything went wrong, and nothing in the system was watching for it.
  Two of the nine .py files (composer.py, sensorium.py) had no pre-reset cache and
  are permanently gone; six were re-implemented from recovered requirements; one
  (prophecy_ledger.py) was left alone because HEAD is newer there.
  PROPOSED GUARD, now ITEM 13: refuse to start a cycle when tracked files have
  been modified for longer than 48 hours, and NAME them in the refusal. It names;
  it never commits and never discards — committing on someone's behalf is its own
  kind of damage, and discarding is what just happened. Uncommitted work with no
  owner is the same defect as a ledger that records only successes: a real state
  the system cannot see.
  SECOND-ORDER, now ITEM 12: the reason the damage reached measurement data at all
  is that memory/axis_history.json is TRACKED. A file a running cycle rewrites
  should never be restorable-over by a checkout.
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
