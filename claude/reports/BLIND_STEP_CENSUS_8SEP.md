# THE BLIND-STEP CENSUS — which steps run without a trace, and what depends on them

**2026-09-08. DIAGNOSIS ONLY. Nothing in this report has been implemented.**

Read-only. Every number below was computed against this repo on 2026-09-08 and the
command that reproduces it is given. No file was changed to produce it.

---

## 0. THE NUMBERS IN THE BRIEF WERE ONE REVISION STALE

The brief asked for "all 31 blind steps" out of "66 cycle steps". Measured:

| | brief | measured 2026-09-08 | why |
|---|---|---|---|
| distinct steps in `core/cycle_map.STEPS` | 66 | **70** | the map has grown; 71 `beat()` calls carry 70 distinct names (`body_scan` runs twice, at index 0 and index 13) |
| steps that record nothing | 31 | **30** | `hyperclaw_plan` came off the list in commit `b8c1c07` |
| steps covered by `_run()` | — | **40** | |

Reproduce:

```
venv\Scripts\python.exe -m pytest test/test_checkpoint_wiring.py::test_the_uncovered_steps_are_counted_and_not_growing -q
```

`test/test_checkpoint_wiring.py` is the authoritative definition and I have used
its own computation rather than a second one: a step is **covered** if
`fast_cycle_runner.py` contains `_run("<name>", …)` for it, after alias
resolution. That test is a ratchet — the limit moved 31 → 30 in `b8c1c07` and may
only ever move down.

---

## 1. WHAT "BLIND" ACTUALLY COSTS — TWO DIFFERENT THINGS, OFTEN CONFLATED

This distinction is the single most important finding in the census, and getting
it wrong sends a fix to the wrong layer.

| layer | written by | what it carries | what its absence costs |
|---|---|---|---|
| **crash trace** | `_run()` → `core/blackbox.py` | one fsync'd `begin`/`end` line per step | a hard kill inside the step leaves nothing; a raised exception never reaches `phase_tracker.note_failure()`, so the phase report cannot name it |
| **provenance stamp** | `beat()` → `memory/heartbeat.py:191` → `core.notary.attest()` | the 5-dimension vector, the level, the products, hash-chained | the artifact carries no origin level, and every irreversible step downstream inherits `UNKNOWN(0)` |

**Every one of the 70 steps gets a provenance stamp.** `beat()` is called for all
of them. Only 40 get a crash trace.

So "blind" in the sense of *bypasses `_run()`* is **not** the reason
`hyperclaw_plan` stamped `level_0` — that was a missing entry in
`config/step_inputs.json` plus an empty `produces` on its predecessor. Wiring a
step through `_run()` changes its notary level by **exactly zero**. Both holes are
worth closing; they are not the same hole, and a fix aimed at one does nothing
for the other.

---

## 2. THE 30, RANKED BY RISK

Ranking: feeds a notary-gated decision (1000) > is a declared verifier but cannot
say what it reads (500) > declares no inputs (100) > is backbone (50) > 10 per
artifact produced.

`decl` = has an entry in `config/step_inputs.json`. `ver` = listed in
`core.notary.VERIFIERS`, which may **break** an inherited level. `bb` = backbone.

### TIER 1 — feeds a notary-gated decision (2 steps)

| step | idx | decl | ver | feeds |
|---|---|---|---|---|
| `auto_levels` | 12.5 | **N** | N | `memory/auto_levels.json` → `self_modifier` |
| `web_intelligence` | 1 | Y | Y | `memory/web_intelligence` → `github_publish` |

`auto_levels` is the highest-value single fix in this table. It produces an
artifact `self_modifier` declares as an input and it cannot say what it reads, so
it stamps `UNKNOWN(0)` on `memory/auto_levels.json` every night and step 18
inherits that 0. Declaring its inputs is the same one-entry change that fixed
`hyperclaw_plan`.

`web_intelligence` already declares its inputs — it is Tier 1 only for the missing
crash trace, and it is the longest step in the cycle (00:11:06 → 00:31:09 on
2026-09-08, twenty minutes), which is precisely where a hard kill is most likely
and least visible.

### TIER 2 — declared verifiers that cannot say what they read (3 steps)

| step | idx | decl | ver |
|---|---|---|---|
| `global_indicators` | 2.5 | **N** | Y |
| `browser_scout` | 2.55 | **N** | Y |
| `sensorium_ingest` | 2.54 | **N** | Y |

Plus `internet_intelligence` (idx 4), which **is** covered by `_run()` and so is
not in the 30, but shares the defect: it is in `VERIFIERS` and declares nothing.

This tier is the sharpest contradiction in the system. A verifier is trusted to
**break inheritance** — to wash a bad stamp clean because it checked against a
live external source — and these four cannot say what they read. They are granted
the strongest privilege in the notary on the weakest evidence.

This is already a failing test, and it has been failing for some time:

```
venv\Scripts\python.exe -m pytest test/test_verifier_inputs.py::test_every_verifier_declares_what_it_reads -q
```

Its own message: *"Each resolves to `_age_state([])` → UNKNOWN(0), which stamps
level_0 on everything it produces and refuses every irreversible step that
inherits from it. This is what cost 15 nights of `github_publish` and 19 of
`self_modifier`."*

### TIER 3 — backbone, no crash trace (9 steps)

`boot` (-1), `canon_load` (0.05), `brain_briefing` (0.2), `dependency_check`
(0.5), `update_master` (12), `scoring_engine` (12.4), `merklememory_commit` (24),
`brain_debrief` (25.5), `cycle_report` (25.6).

Backbone means *never skipped by opinion — the audit chain does not break*. A
backbone step that dies without a record breaks the audit chain in the one way
the chain cannot detect. `dependency_check` is the only step that can stop the
cycle; `merklememory_commit` seals memory; `boot` is the first proof of life.

### TIER 4 — the remaining 16

`composers` (2.6), `constancy_and_constellation` (12.66), `deduction` (12.65),
`telegram_approvals` (0.1), `axis_feed` (12.68), `brain_reconsider` (12.75),
`cognitive_orchestrator` (12.7), `continuous_learning` (23), `grounding_ledger`
(2.7), `needs_reanalysis_scan` (0.7), `notify_patches_and_initiatives` (0.25),
`trend_tracker` (3), `facade_self_check` (12.45), `llm_self_review_axes` (2.75),
`system_hypergraph` (12.3), `training_data_accumulation` (25).

None declares inputs. `telegram_approvals` is worth pulling forward out of tier
order: it applies the human's OK/NO before the plan, so it is where a human veto
enters the system, and it records neither a crash trace nor a declared input.

---

## 3. WHAT THE GATE SEES TONIGHT

```
venv\Scripts\python.exe core/blind_producers.py --selftest
```

```
self_modifier   : auto_levels -> memory/auto_levels.json
                  self_observer -> memory/development_journal.json
execute_patches : self_observer -> memory/development_journal.json
github_publish  : (none)
```

Two blind producers still feed `self_modifier`, down from three. Since `b8c1c07`
they are named in `memory/night_events.jsonl` on every gate crossing, pass or
refuse, under subject `СЛЯПИ_ПРОИЗВОДИТЕЛИ`.

`self_observer` appears in this list only since commit `68aacb6`, which corrected
its `produces` from an artifact it never wrote to `memory/development_journal.json`,
which it does write. The correction made a real dependency visible; it did not
create one.

---

## 4. AND IT WOULD STILL NOT OPEN THE GATE

Declaring all of these would **not** make `self_modifier` act, and any plan that
assumes otherwise will produce a disappointing night.

`self_modifier`'s own vector, from the live chain at 2026-09-08T01:35:34:

```
{witness: 3, human: 3, thought: 3, age: 1, promise: 1}   own = 1
age     "най-стар вход memory/self_awareness.json: 180.3 дни"
```

`own = 1` is already below `IRREVERSIBLE_MIN = 2`, and `level = min(own,
inherited)`. Inheritance cannot lift it. The binding constraint is that
`memory/self_awareness.json` — a declared input of step 18 — was last written
**2026-03-11**, 180.7 days ago.

So the ranked work above buys **honest refusals**, not passage. The question
"should step 18 still be reading a file from March, and if not, what should it
read instead?" is a separate decision and is not answered here.

(`promise` has since moved 1 → 3: commit `68aacb6` gave `self_observer` a product
it actually writes, so `kept_promise` now reads `ОБНОВИ` instead of `НЕ ПИПНА`.
Measured read-only after that commit. `age` is untouched and still binds.)

---

## 5. SUGGESTED ORDER, AND THE HONEST COST

One step per commit, each with the module read line by line — the
`config/step_inputs.json` contract requires `derived_from` to say where the list
came from, and a guessed declaration is worse than none because it looks
authoritative.

1. **`auto_levels`** — the only remaining blind producer feeding a gate that is
   not already fixed by a decision elsewhere.
2. **The four verifiers** (`global_indicators`, `sensorium_ingest`,
   `browser_scout`, `internet_intelligence`) — turns a standing red green and
   removes the strongest-privilege-on-weakest-evidence contradiction. The test's
   own message notes the alternative: *"If the step does not belong in VERIFIERS,
   remove it from `core/notary.VERIFIERS` instead — either answer is acceptable;
   leaving it undeclared is not."*
3. **`self_observer`** — the last blind producer feeding both F_SELF steps.
4. **The nine backbone steps through `_run()`** — cheap, mechanical, one ratchet
   decrement each.
5. **`telegram_approvals`** — out of tier order, because it is the human veto path.
6. The rest.

Each `_run()` wiring lowers `UNCOVERED_STEP_LIMIT` in
`test/test_checkpoint_wiring.py` by one, in the same commit, as that ratchet
requires.

**The cost this report does not hide:** items 1–3 are nine declarations, and each
one requires reading a module and listing what it opens *on the path the cycle
actually calls*. That is the expensive part, it cannot be scanned — four static
classifiers were written on 6 Sep and all four were wrong — and it is the only
part that changes what the notary reads.

---

## 6. REPRODUCE THE WHOLE CENSUS

```
venv\Scripts\python.exe -m pytest test/test_checkpoint_wiring.py -q      # the 30
venv\Scripts\python.exe -m pytest test/test_verifier_inputs.py -q        # the 4
venv\Scripts\python.exe core/blind_producers.py --selftest               # what feeds the gates
venv\Scripts\python.exe core/passage_rules.py --selftest                 # the rules being applied
```
