# READERS CENSUS — who reads what the cycle leaves behind
### 6 September 2026. `config/cycle_phases.json` promises 47 files. This is what reads them.

## The headline finding is about the method, not the files

**I could not answer this question by scanning the code, and I tried four times.** Each
attempt was wrong, and each was wrong in a different direction:

| attempt | method | result | why it was wrong |
|---|---|---|---|
| v1 | match the literal basename | **176 false "never read"** | reads go through module constants, not literals |
| v2 | walk to the parent directory | **0 unread** | everything resolved to `memory/`, so everything looked read |
| v3 | classify a read/write window around each hit | **17 unread** | the whole snapshot family was false — they are read by `rglob("*_snapshot_latest.json")` |
| v4 | v3 plus glob awareness | **0 unread** | `"*.json"` matches all 47, so every path looked covered |

Even **writer** detection failed. `memory/belief_state.json` reads as "nothing writes
it" because the write goes through `STATE = REPO / "memory" / "belief_state.json"` and
happens far from the literal. `memory/brain_cycle_plan.json` and
`memory/cortex_full_state.json` are the same.

**Reads in this repo happen through constants, through globs, and through helpers far
from the path literal. The question is not decidable by grep here.** That is the census
result, and reporting a confident number instead would have been the fifth wrong answer.

## So it is declared, not detected

`config/produces_readers.json` names a reader for every one of the 47 promised paths,
with a `status` saying how much that name is worth:

```
glob         26   a specific glob in that module matches this file — verified
UNVERIFIED   21   seeded by the scan, NOT confirmed by a human
empty         0
```

The 26 `glob` entries are real: `core/phase_evidence.py` globs `*_latest.json` and
`core/cortex_orchestrator.py` and `core/data_scout.py` both glob
`*_snapshot_latest.json`. A glob only counts when its stem is at least six characters,
so `"*.json"` — which is what produced v4's false zero — is rejected.

## The 21 UNVERIFIED, listed by name

These have a plausible reader and nobody has checked it. **They are carried by name so
they cannot disappear into a count**, and `test_the_unverified_entries_are_carried_by_name`
prints all 21 on every suite run and fails if the number moves without the work being
done.

```
cortex_memory/archive/merkle_root.txt      <- merkle_memory.py
data/cortex_hypergraph.json                <- agents/cortex_strategist/…, system_hypergraph.py
memory/active_canon_frame.txt              <- core/brain.py
memory/auto_levels.json                    <- agents/core/cortex_core_agent.py, goal_planner.py
memory/axis_history.json                   <- cockpit/server.py, core/constancy.py
memory/axis_observations.jsonl             <- core/axis_history.py
memory/belief_state.json                   <- core/belief_revision.py
memory/brain_cycle_plan.json               <- core/brain.py, core/reconsider.py
memory/brain_stance.json                   <- cockpit/datasources.py, cockpit/server.py
memory/composed_indicators.json            <- core/constancy.py, core/deduction.py
memory/cortex_full_state.json              <- cortex_scanner.py
memory/development_journal.json            <- agents/core/feedback_loop.py, goal_planner.py
memory/feedback_log.json                   <- agents/core/feedback_loop.py
memory/goal_score_history.json             <- agents/core/feedback_loop.py, goal_planner.py
memory/grounding_ledger.jsonl              <- cockpit/datasources.py, cockpit/server.py
memory/idea_resolutions.jsonl              <- tools/resolve_ideas.py
memory/improvement_proposals.json          <- _check_proposals.py, _clean_proposals.py
memory/runtime_experiences.json            <- memory/body_scan.py, memory/existence_model.py
memory/self_experiments.json               <- core/self_experiment.py, scripts/micro_cycle.py
memory/self_mirror_log.jsonl               <- core/self_mirror.py, scripts/micro_cycle.py
memory/web_intelligence/latest.json        <- _diag.py, _refresh_three_axes.py
```

**Two of these deserve a second look when somebody gets to them.**
`memory/improvement_proposals.json` and `memory/web_intelligence/latest.json` are named
only by `_`-prefixed scratch scripts (`_check_proposals.py`, `_diag.py`,
`_refresh_three_axes.py`). A scratch script is not a reader the cycle depends on. If
those are the only readers, the files are candidates for retirement — but I am not
asserting that, because the same scan said `feedback_log.json` had no reader and
`core/phase_evidence.py` reads it.

## The test

`test/test_produces_has_a_reader.py`, 6 tests:

1. **every promised path has an entry** — a produces path with no entry is a file
   nobody has said they need;
2. **every entry names at least one reader** — an empty list is the same as no
   declaration;
3. **no stale entries** — a path that stops being produced must leave here too, or the
   declaration decays into a list of files that no longer exist;
4. **phase attribution matches** `cycle_phases.json`;
5. **the 21 UNVERIFIED are printed by name, and the count is pinned** — promoting one
   without doing the work fails, and adding a new unconfirmed path fails;
6. **status values come from the declared set.**

## The rule this makes enforceable

> Nothing new is written into the cycle without a named reader in the same commit.

Before today that was a sentence. Now a commit that adds a `produces` path without an
entry in `config/produces_readers.json` fails the suite, and one that adds an
UNVERIFIED entry fails the count.

## What this census does NOT say

**It does not say all 47 files are read.** It says 26 have a verified glob reader and
21 have a name nobody has checked. The wire-or-retire verdict per file — which the
brief asked for — is exactly the thing four scans could not produce honestly, and
producing it by declaration would be circular: I would be reading back the names I just
seeded. The 21 are the work that remains, and they are on the page rather than in a
percentage.
